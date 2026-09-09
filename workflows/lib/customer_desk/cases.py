"""Messages become cases: a new case, a follow-up on an open one, or a reopen.

A message is identified by its source (`source_kind`, `source_ref`), so a
redelivered webhook or a replayed intake item attaches once. A follow-up on an
open case supersedes every reply that was not yet sent, so a pending approval
for an old reply can never dispatch.
"""
from __future__ import annotations

import datetime as dt
from pathlib import Path

from . import bindings, config, store

OPEN_STATES = ("received", "binding_required", "triaging", "needs_owner", "in_review", "mailbox_draft_saved",
               "helpdesk_draft_saved", "waiting_decision", "waiting_plan", "waiting_approval", "sending", "held",
               "ambiguous", "sent", "waiting_customer", "open_items")
SURFACES = ("email", "whatsapp", "helpdesk", "chat", "transcript", "slack")


class IntakeError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code, self.message = code, message


def _days_since(iso: str | None, today: dt.date) -> int | None:
    if not iso:
        return None
    try:
        return (today - dt.date.fromisoformat(iso[:10])).days
    except ValueError:
        return None


def intake(hub_dir: Path, env: dict) -> dict:
    """Attach one message. Returns {case_id, number, action, seq}. `action` is
    `created`, `appended`, `reopened` or `duplicate`."""
    hub_dir = Path(hub_dir)
    values = config.settings(hub_dir)
    ns = "preview" if env.get("preview") else config.namespace(values)
    surface = env["surface"]
    if surface not in SURFACES:
        raise IntakeError("invalid_request", f"surface must be one of {', '.join(SURFACES)}.")
    internal = surface in ("chat", "transcript", "slack")
    if internal and surface not in values["DESK_INTERNAL_SURFACES"] and surface != "chat":
        raise IntakeError("surface_disabled", f"{surface} is not in DESK_INTERNAL_SURFACES.")
    if not (env.get("text") or "").strip():
        raise IntakeError("invalid_request", "The message has no text.")
    sender = env.get("sender") or {}
    kind = sender.get("kind") or bindings.channel_kind_for(surface)
    try:
        key = bindings.sender_key(kind, sender.get("address") or "") if not internal else None
    except bindings.BindingError:
        key = None
    received = env.get("received_at") or config.now_iso(hub_dir, values)
    today = config.today(hub_dir, values)
    with store.tx(hub_dir) as conn:
        dup = conn.execute("SELECT case_id, seq FROM case_events WHERE source_kind=? AND source_ref=?",
                           (env["source_kind"], env["source_ref"])).fetchone()
        if dup is not None:
            c = store.get_case(conn, dup["case_id"])
            return {"case_id": c["id"], "number": c["number"], "action": "duplicate", "seq": dup["seq"]}
        case = None
        action = "created"
        related: list[str] = []
        if not internal and env.get("thread_key"):
            prior = store.rows(conn.execute(
                "SELECT * FROM cases WHERE namespace=? AND channel_id=? AND thread_key=? AND state NOT IN "
                "('cancelled','failed') ORDER BY created DESC", (ns, env.get("channel_id"), env["thread_key"])))
            for p in prior:
                if p["state"] in OPEN_STATES:
                    case, action = p, "appended"
                    break
                if p["state"] == "resolved":
                    since = _days_since(p.get("resolved_at"), today)
                    if since is not None and since <= int(values["DESK_REOPEN_DAYS"]):
                        case, action = p, "reopened"
                    else:
                        related.append(p["id"])
                    break
        if case is None:
            case = store.create_case(
                conn, prefix=values["DESK_CASE_PREFIX"], namespace=ns, origin_kind="internal" if internal else "external",
                surface=surface, channel_id=env.get("channel_id"), provider=env.get("provider"),
                thread_key=env.get("thread_key"), helpdesk_ticket_id=env.get("helpdesk_ticket_id"),
                intake_id=env.get("intake_id"), sender_kind=kind if not internal else None, sender_key=key,
                sender_display=sender.get("display"), customer_id=env.get("customer_id") if internal else None,
                state="received", first_received_at=received, related=related, opened_by=env.get("opened_by"),
                synthetic=1 if env.get("synthetic", ns == "sample") else 0)
        elif action == "reopened":
            case = store.update_case(conn, case["id"], state="received", reopen_count=case["reopen_count"] + 1,
                                     resolved_at=None)
        else:
            # A follow-up: every reply not yet sent is now out of date.
            for r in store.replies(conn, case["id"]):
                if r["state"] in ("ready", "requested", "mailbox_draft_saved", "helpdesk_draft_saved"):
                    store.set_reply_state(conn, case["id"], r["revision"], "superseded")
            case = store.update_case(conn, case["id"], state="received")
        ev, _ = store.add_event(conn, case["id"], source_kind=env["source_kind"], source_ref=env["source_ref"],
                                received_at=received, text=env["text"], sender_key=key,
                                sender_display=sender.get("display"), subject=env.get("subject"),
                                attachments=env.get("attachments") or [],
                                author_kind="teammate" if internal else "customer")
        store.audit(conn, env.get("opened_by") or "desk", f"case_{action}", case["id"],
                    {"surface": surface, "source_kind": env["source_kind"]})
        return {"case_id": case["id"], "number": case["number"], "action": action, "seq": ev["seq"]}
