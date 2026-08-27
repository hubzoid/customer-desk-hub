"""Keep each case in step with its send and draft work.

A person decides a send on the Work items page. When they deny it, cancel it
or settle an uncertain one as abandoned, Hubzoid stops that work item without
running the desk's code again. This reads the work item's real state and
moves the case and reply to match, so the queue never shows a stale
"waiting for approval". It runs when a case is read and every minute.
"""
from __future__ import annotations

from pathlib import Path

from . import store

OPEN = ("waiting_approval", "saving", "sending", "ambiguous")


def sync_sends(hub_dir: Path, case_id: str | None = None) -> list[dict]:
    try:
        from hubzoid.work_items import store as wi_store
    except ImportError:  # pragma: no cover
        return []
    hub = Path(hub_dir).name.lower()
    conn = store.connect(hub_dir)
    sql = "SELECT * FROM sends WHERE status IN ('waiting_approval','saving','sending','ambiguous') AND work_item_id IS NOT NULL"
    args: tuple = ()
    if case_id:
        sql += " AND case_id=?"
        args = (case_id,)
    changed = []
    for s in store.rows(conn.execute(sql, args)):
        try:
            item = wi_store.get_item(hub_dir, s["work_item_id"])
        except Exception:  # noqa: BLE001 - the operational store is not reachable from here
            return changed
        if item is None:
            continue
        ops = wi_store.list_ops(hub_dir, hub, item_id=item["id"])
        state, reason = item["state"], item.get("reason")
        with store.tx(hub_dir) as tconn:
            case = store.get_case(tconn, s["case_id"])
            back = "in_review" if case["claimed_by"] else "needs_owner"
            if state == "stopped" and reason == "approval_denied":
                store.upsert_send(tconn, s["case_id"], s["reply_revision"], s["mode"], status="rejected")
                reply = store.get_reply(tconn, s["case_id"], s["reply_revision"])
                if reply and reply["state"] == "requested":
                    store.set_reply_state(tconn, s["case_id"], s["reply_revision"], "rejected")
                if case["state"] in ("waiting_approval", "sending"):
                    store.update_case(tconn, case["id"], state=back, note="The requester rejected the reply. Nothing "
                                      "was sent. Edit it or rerun.")
                changed.append({"case": case["number"], "to": "rejected"})
            elif state == "stopped" and reason == "operation_abandoned":
                store.upsert_send(tconn, s["case_id"], s["reply_revision"], s["mode"], status="abandoned")
                store.update_case(tconn, case["id"], state=back, note="An uncertain send was abandoned. The reply may "
                                  "or may not have reached the customer. Check before writing again.")
                changed.append({"case": case["number"], "to": "abandoned"})
            elif state == "cancelled":
                store.upsert_send(tconn, s["case_id"], s["reply_revision"], s["mode"], status="cancelled")
                if case["state"] == "waiting_approval":
                    store.update_case(tconn, case["id"], state=back)
                changed.append({"case": case["number"], "to": "cancelled"})
            elif state == "needs_input" and reason == "operation_ambiguous":
                if s["status"] != "ambiguous":
                    store.upsert_send(tconn, s["case_id"], s["reply_revision"], s["mode"], status="ambiguous",
                                      operation_id=next((o["id"] for o in ops if o["state"] == "ambiguous"), None))
                    store.set_reply_state(tconn, s["case_id"], s["reply_revision"], "ambiguous")
                    store.update_case(tconn, case["id"], state="ambiguous")
                    changed.append({"case": case["number"], "to": "ambiguous"})
            elif state == "failed":
                store.upsert_send(tconn, s["case_id"], s["reply_revision"], s["mode"], status="failed")
                store.update_case(tconn, case["id"], state=back, note=f"The send work failed: {item.get('error') or reason}")
                changed.append({"case": case["number"], "to": "failed"})
            elif state == "waiting" and s["status"] == "waiting_approval":
                op = next((o for o in ops if o["state"] == "awaiting_approval"), None)
                if op and not s.get("operation_id"):
                    store.upsert_send(tconn, s["case_id"], s["reply_revision"], s["mode"], operation_id=op["id"])
    return changed
