"""The helpdesk side of a case: read the ticket in, write the desk's work back.

In: a webhook or the modified-ticket poll names a ticket id. The body is never
trusted. The desk rereads the ticket and its threads through the read client
and handles the newest inbound customer message once.

Out, in this order, each as a recorded Hubzoid operation:
1. tags: the request kinds and flags, with the desk prefix
2. a private note with the case number, outcomes, the ERP facts and their sources
3. the desk case number in one configured custom field, when set
4. the proposed reply as an unsent draft (`customer_reply.send` in `draft` mode)

The desk never sends, closes, assigns or changes a ticket's status. Just
before the draft is written the ticket is reread. Nothing is written if it was
closed, an agent replied after the customer, or someone else's draft is open.
An older desk draft is never edited: the note says it is out of date.

Modes: `dry-run` records the intended writes only. `shadow` writes tags with a
`shadow-` prefix and keeps notes and drafts as previews. `live` writes, and
drafts need the second switch `DESK_HELPDESK_DRAFTS`.
"""
from __future__ import annotations

import html
import json
import re
import time
from pathlib import Path

from .. import config, store
from . import zoho

AUTO_ACK = ("auto-reply", "automatic reply", "we have received your request", "this is an automated")


def readers(hub_dir: Path, values: dict, *, transport=None) -> tuple[zoho.Reader, zoho.Writer | None]:
    state = store.db_path(hub_dir).parent / "zoho"
    reader = zoho.Reader(zoho.credentials(hub_dir, values, write=False), state_dir=state, transport=transport)
    writer = None
    policy = zoho.policy_from(values)
    if policy is not None:
        writer = zoho.Writer(zoho.credentials(hub_dir, values, write=True), policy, hub_dir=hub_dir, state_dir=state,
                             transport=transport)
    return reader, writer


def latest_inbound(threads: list[dict]) -> dict | None:
    real = [t for t in threads if t.get("direction") == "in" and t.get("status") != "DRAFT"]
    real = [t for t in real if not any(a in (t.get("summary") or "").lower() for a in AUTO_ACK)]
    return max(real, key=lambda t: (t.get("createdTime") or "", int(t["id"]) if str(t.get("id", "")).isdigit() else 0)) \
        if real else None


def awaiting_reply(threads: list[dict]) -> bool:
    sent = [t for t in threads if t.get("status") != "DRAFT"]
    if not sent:
        return False
    last = max(sent, key=lambda t: (t.get("createdTime") or "", int(t["id"]) if str(t.get("id", "")).isdigit() else 0))
    return last.get("direction") == "in"


def read_ticket(reader: zoho.Reader, ticket_id: str) -> dict:
    """The ticket, its threads, and the newest inbound message with its text."""
    ticket = reader.ticket(ticket_id)
    threads = reader.threads(ticket_id)
    inbound = latest_inbound(threads)
    message = reader.thread(ticket_id, inbound["id"]) if inbound else None
    return {"ticket": ticket, "threads": threads, "inbound": message}


def claim_message(hub_dir: Path, ticket: dict, inbound_id: str, *, owner: str | None = None) -> bool:
    """True the first time this inbound message is seen, and again for the
    same work item replaying after a crash before the case was linked. The
    desk's own tag and draft writes change the ticket's modified time, and
    this check is what stops them from starting a new case loop."""
    with store.tx(hub_dir) as conn:
        row = store.row(conn.execute("SELECT * FROM helpdesk_tickets WHERE ticket_id=?", (str(ticket["id"]),))
                        .fetchone())
        if row and row.get("handled_message_id") == inbound_id:
            return row.get("status") == "claimed" and bool(owner) and row.get("owner") == owner
        conn.execute("INSERT INTO helpdesk_tickets(ticket_id, number, observed_modified, latest_inbound_id, "
                     "handled_message_id, status, owner, claimed_at, updated) VALUES (?,?,?,?,?, 'claimed', ?, ?, ?) "
                     "ON CONFLICT(ticket_id) DO UPDATE SET number=excluded.number, "
                     "observed_modified=excluded.observed_modified, latest_inbound_id=excluded.latest_inbound_id, "
                     "handled_message_id=excluded.handled_message_id, status='claimed', owner=excluded.owner, "
                     "claimed_at=excluded.claimed_at, updated=excluded.updated",
                     (str(ticket["id"]), ticket.get("ticketNumber"), ticket.get("modifiedTime"), inbound_id, inbound_id,
                      owner, time.time(), time.time()))
        return True


def link_case(hub_dir: Path, ticket_id: str, case_id: str) -> None:
    """The message is a case now: handled for good."""
    with store.tx(hub_dir) as conn:
        conn.execute("UPDATE helpdesk_tickets SET case_id=?, status='handled' WHERE ticket_id=?",
                     (case_id, str(ticket_id)))


# -- what to write -------------------------------------------------------------------

def tags_for(view: dict, values: dict, kinds) -> list[str]:
    prefix = values["ZOHO_DESK_TAG_PREFIX"]
    case = view["case"]
    tags = []
    if case["state"] == "binding_required":
        return [f"{prefix}binding-required"]
    res = view.get("resolution") or {}
    for o in res.get("requests") or []:
        tags.append(kinds.tag(o["category"]))
    cls = res.get("classifier") or {}
    if cls.get("low_confidence"):
        tags.append(f"{prefix}low-confidence")
    for f in cls.get("escalation_flags") or []:
        tags.append(f"{prefix}{f.replace('_', '-')}")
    if case.get("queue") == "decisions":
        tags.append(f"{prefix}decision-needed")
    return sorted(set(tags))


def note_for(view: dict, mark: str, *, replace_draft: bool = False) -> str:
    case = view["case"]
    lines = [f"Customer Desk case {case['number']} ({case['state']}, queue {case.get('queue') or 'none'}).",
             "Internal note from the desk. Not visible to the customer.", ""]
    if case["state"] == "binding_required":
        lines += ["The sender is not bound to exactly one customer, so no customer data was read.",
                  "A binding admin binds the sender in the desk, then the desk prepares the case."]
    else:
        res = view.get("resolution") or {}
        lines.append(f"Customer: {case.get('customer_id')}")
        for o in res.get("requests") or []:
            lines.append(f"Request {o['request_no']}: {o['category']} -> {o['outcome']} "
                         f"(rules {', '.join(o['rule_refs'])})")
        lines.append("")
        lines.append("Facts read from ERPNext:")
        for f in view.get("facts") or []:
            s = f["source"]
            if s.get("backend") in ("policy", "desk"):
                continue
            where = f"{s.get('doctype')} {s.get('name')}.{s.get('field')}" + (f" row {s['row_id']}" if s.get("row_id") else "")
            if f["kind"] in ("statement_table", "credit_note"):
                ids = f["value"] if isinstance(f["value"], list) else [f["value"]]
                shown = f"{len(ids)} {'credit notes' if f['kind'] == 'credit_note' else 'open invoices'}: {', '.join(ids)}"
                where = f"{s.get('doctype')} outstanding_amount"
            else:
                shown = f["display"].replace("\n", " / ")
            lines.append(f"- {f['fact_id']} {shown[:120]}  [{where}, read {f['observed_at']}]")
        for t in view.get("tickets") or []:
            lines.append(f"Ticket {t['number']}: {t['severity']}, owned by {t['owner_role']}, {t['state']}.")
        reply = view.get("reply") or {}
        if reply:
            failed = [c["id"] for c in (reply.get("checks") or {}).get("results", []) if c["status"] == "fail"]
            lines.append("")
            lines.append(f"Proposed reply revision {reply['revision']}: checks "
                         f"{'passed' if not failed else 'failed: ' + ', '.join(failed)}.")
            if replace_draft and not failed:
                # The desk never edits or deletes a draft, so a newer reply
                # travels in this note while an older desk draft is on the ticket.
                lines += ["An earlier desk draft is on this ticket and is out of date. The desk does not edit or "
                          "delete drafts. Replace that draft's text with this reply before you send it:", "",
                          reply.get("rendered") or ""]
        if case.get("note"):
            lines.append(f"Desk notes: {case['note']}")
    lines += ["", mark]
    return "\n".join(lines)


TABLE_RULE = re.compile(r"\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)*\|?")


def draft_html(body: str, mark: str) -> str:
    """The reply's Markdown as the helpdesk's HTML: paragraphs, line breaks,
    bullet lists and tables (a statement), every value escaped."""
    esc = html.escape
    out = []
    for block in body.split("\n\n"):
        lines = [ln.rstrip() for ln in block.split("\n") if ln.strip()]
        if not lines:
            continue
        if len(lines) >= 2 and all(ln.lstrip().startswith("|") for ln in lines):
            rows = [[c.strip() for c in ln.strip().strip("|").split("|")] for ln in lines
                    if not TABLE_RULE.fullmatch(ln.strip())]
            head, rest = rows[0], rows[1:]
            out.append("<table border='1' cellpadding='4' cellspacing='0'><tr>" + "".join(f"<th>{esc(c)}</th>" for c in head)
                       + "</tr>" + "".join("<tr>" + "".join(f"<td>{esc(c)}</td>" for c in r) + "</tr>" for r in rest)
                       + "</table>")
        elif all(ln.lstrip().startswith(("- ", "* ")) for ln in lines):
            out.append("<ul>" + "".join(f"<li>{esc(ln.lstrip()[2:])}</li>" for ln in lines) + "</ul>")
        else:
            out.append("<p>" + "<br>".join(esc(ln) for ln in lines) + "</p>")
    return "".join(out) + f"<!-- {mark} -->"


def preflight_draft(reader: zoho.Reader, ticket_id: str, inbound_id: str, mark: str) -> tuple[str, str | None]:
    """Reread the ticket just before writing a draft. Returns (decision,
    thread_id): `write`, `exists` (our draft is already there), or a reason
    to hold off: `closed`, `answered`, `other_draft`, `newer_message`."""
    ticket = reader.ticket(ticket_id)
    if (ticket.get("statusType") or ticket.get("status") or "").lower() in ("closed", "resolved"):
        return "closed", None
    threads = reader.threads(ticket_id)
    newest = latest_inbound(threads)
    if newest and str(newest["id"]) != str(inbound_id):
        return "newer_message", None
    for t in threads:
        if t.get("status") == "DRAFT":
            full = reader.thread(ticket_id, t["id"])
            if mark in (full.get("content") or ""):
                return "exists", str(t["id"])
            return "other_draft", None
    if not awaiting_reply(threads):
        return "answered", None
    return "write", None


def record(hub_dir: Path, *, kind: str, mode: str, ticket_id: str, case_id: str, idem: str, request: dict,
           status: str, response=None, error: str | None = None) -> None:
    now = time.time()
    with store.tx(hub_dir) as conn:
        conn.execute("INSERT INTO helpdesk_writes(idem_key, kind, mode, ticket_id, case_id, request, response, status, "
                     "error, attempts, created, updated) VALUES (?,?,?,?,?,?,?,?,?,1,?,?) ON CONFLICT(idem_key) DO "
                     "UPDATE SET status=excluded.status, response=excluded.response, error=excluded.error, "
                     "attempts=helpdesk_writes.attempts+1, updated=excluded.updated",
                     (idem, kind, mode, str(ticket_id), case_id, store.dumps(request), store.dumps(response), status,
                      error, now, now))


def ledger(hub_dir: Path, *, case_id: str | None = None, ticket_id: str | None = None) -> list[dict]:
    conn = store.connect(hub_dir)
    where, args = [], []
    if case_id:
        where.append("case_id=?")
        args.append(case_id)
    if ticket_id:
        where.append("ticket_id=?")
        args.append(str(ticket_id))
    sql = "SELECT * FROM helpdesk_writes" + (f" WHERE {' AND '.join(where)}" if where else "") + " ORDER BY created"
    return store.rows(conn.execute(sql, args))


def health(hub_dir: Path) -> dict:
    conn = store.connect(hub_dir)
    by = {r["status"]: r["n"] for r in conn.execute("SELECT status, COUNT(*) AS n FROM helpdesk_writes GROUP BY status")}
    tickets = conn.execute("SELECT COUNT(*) AS n FROM helpdesk_tickets").fetchone()["n"]
    cursor = conn.execute("SELECT value FROM cursor WHERE name='zoho_poll'").fetchone()
    return {"tickets_seen": tickets, "writes": by, "poll_cursor": json.loads(cursor["value"]) if cursor else None,
            "stop_switch": zoho.stop_switch(hub_dir)}
