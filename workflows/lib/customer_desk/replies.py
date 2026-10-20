"""Where an approved reply goes, and where a draft is saved.

Every external effect here runs inside `hub.operation.run`, so Hubzoid
records it before it happens, applies the write mode (`off`, `draft`,
`approve`) and never repeats an uncertain send on its own.

Adapters by channel:
* `sample-email`: drafts go to the sample mailbox's Drafts and sends to the
  sample outbox. Nothing leaves this machine. The receipt says so.
* `sample-whatsapp`: no drafts (WhatsApp has none). Sends go to the sample
  outbox, and a closed 24 hour window holds the reply.
* `zoho_desk`: drafts are unsent Zoho Desk draft replies. The desk never sends
  from the helpdesk, so a send is refused before anything leaves.
* a Hubzoid email or WhatsApp channel: replies go through `hub.thread.post`
  (text only, see the README limits).
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import time
from pathlib import Path

from . import pipeline, store

SAMPLE_CHANNELS = ("sample-email", "sample-whatsapp")
NO_DRAFT = ("sample-whatsapp",)
WHATSAPP_WINDOW_HOURS = 24


class Held(Exception):
    """WhatsApp only allows a free-form reply within 24 hours of the customer's message."""


def channel_kind(channel_id: str | None) -> str:
    if not channel_id:
        return "internal"
    if channel_id in ("zoho_desk", "freshdesk"):
        return "helpdesk"
    if "whatsapp" in channel_id:
        return "whatsapp"
    return "email"


def idem_key(case_id: str, reply_revision: int, kind: str) -> str:
    return f"desk:{case_id}:{reply_revision}:{kind}"


def outbox_rows(hub_dir: Path, *, case_id: str | None = None, kind: str | None = None) -> list[dict]:
    conn = store.connect(hub_dir)
    where, args = [], []
    if case_id:
        where.append("case_id=?")
        args.append(case_id)
    if kind:
        where.append("idem_key LIKE ?")
        args.append(f"%:{kind}")
    sql = "SELECT * FROM outbox" + (f" WHERE {' AND '.join(where)}" if where else "") + " ORDER BY accepted_at"
    return store.rows(conn.execute(sql, args))


def _sample_write(hub_dir: Path, args: dict, kind: str, approved_by: str | None) -> dict:
    """One row in the sample outbox (kind send) or the sample mailbox drafts
    (kind draft), in one transaction keyed by the operation, so a retry finds
    the row instead of writing a second."""
    key = idem_key(args["case_id"], args["reply_revision"], kind)
    with store.tx(hub_dir) as conn:
        found = store.row(conn.execute("SELECT * FROM outbox WHERE idem_key=?", (key,)).fetchone())
        if found:
            return receipt(found, kind)
        oid = "SAMPLE-" + hashlib.sha256(key.encode()).hexdigest()[:12].upper()
        now = dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
        conn.execute("INSERT INTO outbox(id, case_id, reply_revision, channel_id, channel_kind, recipients, subject, "
                     "body, attachments, digest, idem_key, accepted_at, approved_by) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                     (oid, args["case_id"], args["reply_revision"], args["channel"], channel_kind(args["channel"]),
                      store.dumps(args["recipients"]), args.get("subject"), args["body"],
                      store.dumps(args["attachments"]), args["digest"], key, now, approved_by))
        return receipt(store.row(conn.execute("SELECT * FROM outbox WHERE id=?", (oid,)).fetchone()), kind)


def receipt(row: dict, kind: str) -> dict:
    text = ("Sample outbox accepted the reply. No customer delivery." if kind == "send" else
            "Saved as a draft in the sample mailbox. Nothing was sent.")
    return {"receipt_id": row["id"], "accepted_at": row["accepted_at"], "kind": kind, "channel": row["channel_id"],
            "synthetic": True, "note": text,
            "attachments": [{"name": a["name"], "sha256": a["sha256"]} for a in row["attachments"]]}


def sample_reconcile(hub_dir: Path, kind: str):
    """For an interrupted sample send: the outbox is local and written in one
    transaction, so a row is proof it happened and no row is proof it did not."""
    from hubzoid.work_items import Reconciled

    def check(args: dict):
        key = idem_key(args["case_id"], args["reply_revision"], kind)
        row = store.row(store.connect(hub_dir).execute("SELECT * FROM outbox WHERE idem_key=?", (key,)).fetchone())
        if row:
            return Reconciled("applied", receipt(row, kind), {"outbox_id": row["id"]})
        return Reconciled("safe_to_retry")

    return check


def whatsapp_window_open(hub_dir: Path, case: dict, now: dt.datetime | None = None) -> bool:
    conn = store.connect(hub_dir)
    evs = [e for e in store.events(conn, case["id"]) if e["author_kind"] == "customer"]
    if not evs:
        return False
    last = dt.datetime.fromisoformat(evs[-1]["received_at"].replace("Z", "+00:00"))
    now = now or real_now_in_desk_clock(hub_dir)
    return (now - last).total_seconds() <= WHATSAPP_WINDOW_HOURS * 3600


def real_now_in_desk_clock(hub_dir: Path) -> dt.datetime:
    from . import config

    return dt.datetime.fromisoformat(config.now_iso(hub_dir).replace("Z", "+00:00"))


def payload(hub_dir: Path, case: dict, reply: dict) -> dict:
    """The exact content an approval binds to. Recipients come only from the
    stored origin: never from the draft, the model or a Reply-To."""
    return {"case_id": case["id"], "case_number": case["number"], "reply_revision": reply["revision"],
            "channel": case["channel_id"], "thread": case["thread_key"], "recipients": reply["recipients"],
            "subject": reply.get("subject"), "body": reply["rendered"],
            "attachments": [{"name": a["name"], "media_type": a["media_type"], "sha256": a["sha256"],
                             "bytes": a["bytes"]} for a in reply["attachments"]],
            "digest": reply["digest"], "typed_by_person": reply.get("typed_values") or [],
            "author_kind": reply["author_kind"]}


def attachment_payloads(hub_dir: Path, attachments: list[dict]) -> list[tuple[str, bytes, str]]:
    return [(a["name"], pipeline.attachment_bytes(hub_dir, a["sha256"]), a["media_type"]) for a in attachments]


def zoho_draft(hub_dir: Path, values: dict, case: dict, reply: dict, *, transport=None):
    """The `draft` function for a helpdesk case: an unsent Zoho Desk draft."""
    from .helpdesk import desk, zoho

    def save(args: dict) -> dict:
        from hubzoid.work_items import NotSent, Rejected

        from . import recheck

        conn = store.connect(hub_dir)
        current = store.get_case(conn, case["id"])
        fresh_reply = store.get_reply(conn, case["id"], reply["revision"])
        resolution = store.get_resolution(conn, case["id"], reply["resolution"])
        loaded = pipeline.load(hub_dir)
        active = loaded.values
        if (current["provider"] != active["DESK_HELPDESK"] or values["DESK_HELPDESK"] != active["DESK_HELPDESK"]
                or current["current_reply"] != reply["revision"] or fresh_reply["state"] in ("superseded", "rejected")
                or current["state"] in ("received", "triaging", "cancelled")
                or any(resolution[k + "_digest"] != loaded.digests()[k] for k in ("policy", "style", "kinds"))
                or recheck.changed_facts(hub_dir, current, store.get_facts(conn, case["id"], reply["resolution"]),
                                        policy=loaded.policy)):
            raise Rejected("reply_stale: case, rules or evidence changed before draft dispatch")
        reader, writer = desk.readers(hub_dir, values, transport=transport)
        if writer is None or not writer.policy.allow_drafts:
            raise NotSent("helpdesk_drafts_off: drafts need DESK_HELPDESK_MODE live and DESK_HELPDESK_DRAFTS true.")
        if values.get("DESK_HELPDESK") == "freshdesk":
            from .helpdesk import editor

            return editor.prepare(hub_dir, case, reply, reader)
        ticket_id = case["helpdesk_ticket_id"]
        conn = store.connect(hub_dir)
        inbound = conn.execute("SELECT latest_inbound_id FROM helpdesk_tickets WHERE ticket_id=?",
                               (str(ticket_id),)).fetchone()
        inbound_id = inbound["latest_inbound_id"] if inbound else None
        mark = zoho.marker(ticket_id, f"{case['id']}:{reply['revision']}")
        decision, existing = desk.preflight_draft(reader, ticket_id, inbound_id, mark)
        if decision == "exists":
            return {"provider_draft_id": existing, "ticket_id": ticket_id, "reconciled": True}
        if decision != "write":
            raise Rejected(f"draft_not_written: {decision}")
        # The draft goes only to the sender this case is bound to. A ticket whose
        # contact changed since is left for a person.
        ticket = reader.ticket(ticket_id)
        to = case["sender_key"]
        if not to or (ticket.get("email") or "").strip().lower() != to.lower():
            raise Rejected("recipient_changed: the ticket's contact is no longer the bound sender of "
                           f"{case['number']}. Check the ticket in Zoho Desk.")
        ids = []
        for name, data, media in attachment_payloads(hub_dir, reply["attachments"]):
            up = writer.upload(name, data, media)
            ids.append(str(up["id"]))
        try:
            th = writer.draft_reply(ticket_id, from_address=values.get("ZOHO_DESK_FROM_ADDRESS") or "support@desk.example",
                                    to=to, html=desk.draft_html(args["body"], mark), in_reply_to=inbound_id,
                                    attachment_ids=ids)
        except (zoho.WriteRefused, zoho.WritesBlocked) as exc:
            raise NotSent(f"helpdesk_write_blocked: {exc}") from None
        verified = reader.thread(ticket_id, str(th["id"]))
        if verified.get("status") != "DRAFT" or mark not in (verified.get("content") or ""):
            raise zoho.ZohoError(0, "draft_unconfirmed", "Draft creation lacks verified provider readback")
        return {"provider_draft_id": str(th["id"]), "ticket_id": ticket_id, "attachments": len(ids)}

    return save


def zoho_reconcile(hub_dir: Path, values: dict, case: dict, reply: dict, *, transport=None):
    from hubzoid.work_items import Reconciled

    from .helpdesk import desk, zoho

    def check(args):
        # Only a complete listing without the marker is proof the draft is not
        # there. A ticket too long to read in full is left to its requester.
        reader, _ = desk.readers(hub_dir, values, transport=transport)
        if values.get("DESK_HELPDESK") == "freshdesk":
            row = store.connect(hub_dir).execute("SELECT state FROM editor_deliveries WHERE case_id=? AND reply_revision=?",
                                                (case["id"], reply["revision"])).fetchone()
            return Reconciled("applied", {"state": row["state"]}) if row else Reconciled("safe_to_retry")
        mark = zoho.marker(case["helpdesk_ticket_id"], f"{case['id']}:{reply['revision']}")
        threads, complete = reader.all_threads(case["helpdesk_ticket_id"])
        for t in threads:
            if t.get("status") == "DRAFT" and mark in (reader.thread(case["helpdesk_ticket_id"], t["id"]).get("content") or ""):
                return Reconciled("applied", {"provider_draft_id": str(t["id"]), "reconciled": True}, {"thread": t["id"]})
        return Reconciled("safe_to_retry" if complete else "unknown")

    return check


def refuse_helpdesk_send(args):
    from hubzoid.work_items import Rejected

    raise Rejected("helpdesk_send_unsupported: the desk never sends from the helpdesk. A person sends the draft in "
                   "the helpdesk.")


def target_version(hub_dir: Path, case_id: str, reply_revision: int, recheck) -> callable:
    """What must not change between approval and dispatch: the reply is still
    the current one, no new customer message arrived, and every ERP fact still
    reads the same."""

    def version() -> str:
        conn = store.connect(hub_dir)
        case = store.get_case(conn, case_id)
        reply = store.get_reply(conn, case_id, reply_revision)
        events = store.events(conn, case_id)
        facts_state = recheck()
        body = {"current_reply": case["current_reply"], "reply_state_ok": reply["state"] in ("requested", "ready"),
                "reply_digest": reply["digest"], "customer_messages": sum(1 for e in events if e["author_kind"] == "customer"),
                "facts": facts_state}
        return "sha256:" + hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()

    return version


def now_ts() -> float:
    return time.time()
