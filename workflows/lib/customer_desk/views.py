"""Read models: the queue, one case in full, metrics and desk health.

Chat tools, cards, the CLI, the published case page and the helpdesk note
all read through here, so every surface shows the same state.
"""
from __future__ import annotations

import datetime as dt
import statistics
from pathlib import Path

from . import config, store

STATE_TEXT = {
    "received": "Received. The desk is about to read it.",
    "binding_required": "We could not match this sender to a customer. A binding admin binds the sender first. "
                        "No customer data was read.",
    "triaging": "Reading the request, checking ERPNext and checking the reply.",
    "needs_owner": "Ready for a person.",
    "in_review": "Claimed. A teammate is working on it.",
    "mailbox_draft_saved": "A draft is saved in the mailbox. Finish and send it there.",
    "helpdesk_draft_saved": "An unsent draft is in the helpdesk. Edit and send it there.",
    "waiting_decision": "Waiting for the exception team to decide.",
    "waiting_plan": "Waiting for the complaint team to review the escalation plan.",
    "waiting_approval": "Waiting for the requester to approve the exact reply on the Work items page.",
    "sending": "Sending.",
    "held": "Held: WhatsApp allows a free-form reply only within 24 hours of the customer's last message.",
    "ambiguous": "The reply may have been sent. Check before sending again. Only reconcile is offered.",
    "sent": "The reply was accepted.",
    "waiting_customer": "A clarifying question was sent. A new message from the customer resumes the case.",
    "open_items": "Replied, with a ticket or delivery proposal still open.",
    "resolved": "Resolved.",
    "cancelled": "Cancelled.",
    "failed": "Failed. See the note.",
}


def _age_hours(case: dict) -> float | None:
    try:
        first = dt.datetime.fromisoformat((case["first_received_at"] or "").replace("Z", "+00:00"))
    except ValueError:
        return None
    return max(0.0, (dt.datetime.now(dt.timezone.utc) - first).total_seconds() / 3600)


def _categories(conn, case: dict) -> list[str]:
    if not case.get("current_resolution"):
        return []
    res = store.get_resolution(conn, case["id"], case["current_resolution"])
    return [o["category"] for o in (res or {}).get("requests") or []]


def queue(hub_dir: Path, *, tab: str = "all", viewer: str | None = None, limit: int = 25, offset: int = 0,
          customer: str | None = None) -> dict:
    """Tabs: mine, operators, delivery, complaints, decisions, held, bindings, all."""
    values = config.settings(hub_dir)
    ns = config.namespace(values)
    from .sync import sync_sends

    sync_sends(hub_dir)
    conn = store.connect(hub_dir)
    where, args = ["namespace=?"], [ns]
    if tab == "mine" and viewer:
        where.append("claimed_by=?")
        args.append(viewer)
    elif tab in ("operators", "delivery", "complaints", "decisions", "bindings"):
        where.append("queue=?")
        args.append(tab)
        where.append("state NOT IN ('resolved','cancelled','sent')")
    elif tab == "held":
        where.append("state IN ('held','ambiguous')")
    elif tab == "open":
        where.append("state NOT IN ('resolved','cancelled','failed')")
    if customer:
        where.append("customer_id=?")
        args.append(customer)
    total = conn.execute(f"SELECT COUNT(*) AS n FROM cases WHERE {' AND '.join(where)}", args).fetchone()["n"]
    rows = store.rows(conn.execute(f"SELECT * FROM cases WHERE {' AND '.join(where)} ORDER BY number LIMIT ? OFFSET ?",
                                   (*args, max(1, min(limit, 100)), max(0, offset))))
    target = int(values["DESK_RESPONSE_TARGET_HOURS"])
    out = []
    for c in rows:
        reply = store.get_reply(conn, c["id"], c["current_reply"]) if c["current_reply"] else None
        age = _age_hours(c)
        out.append({"case": c["number"], "customer": c["customer_id"] or "unbound", "channel": c["channel_id"] or c["surface"],
                    "categories": ", ".join(_categories(conn, c)), "state": c["state"], "queue": c["queue"] or "",
                    "assignee": c["claimed_by"] or "", "first_line": (reply["rendered"].split("\n\n")[1][:90]
                                                                    if reply and "\n\n" in reply["rendered"] else ""),
                    "over_target": bool(age is not None and age > target and c["state"] not in ("resolved", "sent"))})
    return {"tab": tab, "namespace": ns, "total": total, "rows": out, "next_offset": offset + len(out)
            if offset + len(out) < total else None}


def case(hub_dir: Path, ref: str) -> dict | None:
    conn = store.connect(hub_dir)
    c = store.get_case(conn, ref)
    if c is None:
        return None
    from .sync import sync_sends

    if sync_sends(hub_dir, c["id"]):
        c = store.get_case(conn, c["id"])
    res = store.get_resolution(conn, c["id"], c["current_resolution"]) if c["current_resolution"] else None
    facts = store.get_facts(conn, c["id"], c["current_resolution"]) if c["current_resolution"] else []
    replies = store.replies(conn, c["id"])
    current = next((r for r in replies if r["revision"] == c["current_reply"]), None)
    tickets = store.case_tickets(conn, c["id"])
    for t in tickets:
        t["notes"] = store.ticket_notes(conn, t["id"])
    return {"case": c, "state_text": STATE_TEXT.get(c["state"], c["state"]), "events": store.events(conn, c["id"]),
            "resolution": res, "facts": facts, "reply": current, "replies": replies, "tickets": tickets,
            "proposals": store.case_proposals(conn, c["id"]), "decisions": store.case_decisions(conn, c["id"]),
            "sends": store.case_sends(conn, c["id"]),
            "outbox": store.rows(conn.execute("SELECT * FROM outbox WHERE case_id=? ORDER BY accepted_at", (c["id"],)))}


def compact(view: dict) -> dict:
    """The case as the chat agent reads it: everything a teammate needs, no raw ids."""
    c = view["case"]
    reply = view["reply"] or {}
    res = view["resolution"] or {}
    return {
        "case": c["number"], "state": c["state"], "state_text": view["state_text"], "queue": c["queue"],
        "page": c.get("page_url"),
        "customer": c["customer_id"], "channel": c["channel_id"] or c["surface"], "claimed_by": c["claimed_by"],
        "note": c["note"], "candidates": c["candidates"] if c["state"] == "binding_required" else None,
        "sender": c["sender_key"] if c["state"] == "binding_required" else None,
        "messages": [{"seq": e["seq"], "at": e["received_at"], "from": e["author_kind"], "subject": e["subject"],
                      "text": e["text"][:2000]} for e in view["events"]],
        "requests": [{"no": o["request_no"], "category": o["category"], "outcome": o["outcome"],
                      "rules": o["rule_refs"], "notes": o["notes"]} for o in res.get("requests") or []],
        "classification": {k: (res.get("classifier") or {}).get(k) for k in ("agreement", "low_confidence",
                                                                             "escalation_flags", "injection_detected")},
        "facts": [{"id": f["fact_id"], "kind": f["kind"], "value": f["display"][:300],
                   "source": f"{f['source'].get('doctype')} {f['source'].get('name')}.{f['source'].get('field')}",
                   "observed_at": f["observed_at"]} for f in view["facts"]],
        "reply": {"revision": reply.get("revision"), "author": reply.get("author_kind") + (
            " (scripted stand-in stations)" if reply.get("station_label") == "scripted" else ""),
                  "state": reply.get("state"),
                  "digest": reply.get("digest"), "text": reply.get("rendered"), "recipients": reply.get("recipients"),
                  "attachments": [a["name"] for a in reply.get("attachments") or []],
                  "checks": [f"{x['id']}: {x['status']}" for x in (reply.get("checks") or {}).get("results", [])],
                  "checks_passed": (reply.get("checks") or {}).get("passed"),
                  "typed_by_person": reply.get("typed_values")} if reply else None,
        "reviewer": res.get("reviewer"),
        "tickets": [{"number": t["number"], "severity": t["severity"], "owner": t["owner_role"], "state": t["state"],
                     "summary": t["summary"]} for t in view["tickets"]],
        "delivery_proposals": [{"id": p["id"][:8], "order": p["sales_order"], "requested": p["requested_date"],
                                "state": p["state"], "note": p["note"]} for p in view["proposals"]],
        "decisions": [{"id": d["id"][:8], "kind": d["kind"], "state": d["state"], "inputs": d["inputs"],
                       "decided_by": d["decided_by"], "note": d["note"]} for d in view["decisions"]],
        "sends": [{"reply": s["reply_revision"], "mode": s["mode"], "status": s["status"],
                   "receipt": s["receipt"]} for s in view["sends"]],
    }


def metrics(hub_dir: Path) -> dict:
    """Counts observed in this deployment (spec 6.13). Never a product claim."""
    values = config.settings(hub_dir)
    ns = config.namespace(values)
    conn = store.connect(hub_dir)
    cases = store.rows(conn.execute("SELECT * FROM cases WHERE namespace=?", (ns,)))
    resolved = [c for c in cases if c["state"] == "resolved"]
    reopened = [c for c in cases if c["reopen_count"]]
    times = []
    for c in cases:
        if c["first_reply_accepted_at"] and c["first_received_at"]:
            a = dt.datetime.fromisoformat(c["first_received_at"].replace("Z", "+00:00"))
            b = dt.datetime.fromisoformat(c["first_reply_accepted_at"].replace("Z", "+00:00"))
            times.append((b - a).total_seconds() / 3600)
    sent = store.rows(conn.execute("SELECT s.*, r.resolution AS res FROM sends s JOIN replies r ON r.case_id=s.case_id "
                                   "AND r.revision=s.reply_revision WHERE s.status IN ('sent','succeeded')"))
    unedited = 0
    for s in sent:
        first = conn.execute("SELECT digest, rendered FROM replies WHERE case_id=? AND resolution=? AND author_kind IN "
                             "('model','format') ORDER BY revision LIMIT 1", (s["case_id"], s["res"])).fetchone()
        mine = conn.execute("SELECT rendered FROM replies WHERE case_id=? AND revision=?",
                            (s["case_id"], s["reply_revision"])).fetchone()
        if first and mine and first["rendered"] == mine["rendered"]:
            unedited += 1
    by_state: dict[str, int] = {}
    for c in cases:
        by_state[c["state"]] = by_state.get(c["state"], 0) + 1
    return {"label": "Observed in this deployment. Not a quality claim.", "namespace": ns, "cases": len(cases),
            "by_state": by_state, "requests_resolved": len(resolved), "reopen_rate":
                round(len(reopened) / len(resolved), 3) if resolved else None,
            "response_hours_median": round(statistics.median(times), 2) if times else None,
            "response_hours_p90": round(sorted(times)[int(0.9 * (len(times) - 1))], 2) if times else None,
            "sent_replies": len(sent), "unedited_share": round(unedited / len(sent), 3) if sent else None,
            "held": by_state.get("held", 0), "uncertain": by_state.get("ambiguous", 0),
            "waiting_binding": by_state.get("binding_required", 0)}
