"""The Zoho Desk modified-ticket poll, with a cursor and an overlap, and the
id extraction for webhook bodies. A webhook body only names a ticket: the
desk always rereads the ticket through the API."""
from __future__ import annotations

import datetime as dt
import json
import re
from pathlib import Path

from . import config, store

OVERLAP_MINUTES = 15
LOOKBACK_MINUTES = 60
PAGE = 100
MAX_PAGES = 10


def ticket_id_from(body) -> str | None:
    """The first numeric ticket id in a webhook body: `ticketId`, `ticket_id`,
    or an `id` next to `ticketNumber`. Anything else in the body is ignored."""
    if isinstance(body, str):
        try:
            body = json.loads(body)
        except ValueError:
            return None
    stack = [body]
    while stack:
        node = stack.pop(0)
        if isinstance(node, dict):
            for key in ("ticketId", "ticket_id"):
                if re.fullmatch(r"\d{1,20}", str(node.get(key) or "")):
                    return str(node[key])
            if "ticketNumber" in node and re.fullmatch(r"\d{1,20}", str(node.get("id") or "")):
                return str(node["id"])
            stack.extend(v for v in node.values() if isinstance(v, (dict, list)))
        elif isinstance(node, list):
            stack.extend(node)
    return None


def _iso(t: dt.datetime) -> str:
    return t.strftime("%Y-%m-%dT%H:%M:%S.000Z")


def poll() -> dict:
    from hubzoid.workflows.context import _ctx

    from .flows import start_work
    from .helpdesk import desk

    hub_dir = Path(_ctx().hub_dir)
    values = config.settings(hub_dir)
    if values["DESK_HELPDESK"] != "zoho_desk" or not values["DESK_INTAKE_ENABLED"]:
        return {"state": "off"}
    reader, _ = desk.readers(hub_dir, values)
    conn = store.connect(hub_dir)
    now = dt.datetime.now(dt.timezone.utc)
    row = conn.execute("SELECT value FROM cursor WHERE name='zoho_poll'").fetchone()
    cur = json.loads(row["value"]) if row else {"cursor": _iso(now - dt.timedelta(minutes=LOOKBACK_MINUTES))}
    window = cur.get("window") or {"start": _iso(dt.datetime.fromisoformat(cur["cursor"].replace("Z", "+00:00"))
                                                 - dt.timedelta(minutes=OVERLAP_MINUTES)),
                                   "end": _iso(now), "offset": 0}
    started = []
    start = start_work(hub_dir)
    for _ in range(MAX_PAGES):
        page = reader.modified(window["start"], window["end"], offset=window["offset"], limit=PAGE,
                               department_id=values.get("ZOHO_DESK_DEPARTMENT_ID") or None)
        for t in page:
            seen = conn.execute("SELECT observed_modified FROM helpdesk_tickets WHERE ticket_id=?",
                                (str(t["id"]),)).fetchone()
            if seen and seen["observed_modified"] == t.get("modifiedTime"):
                continue
            item = start("customer_desk_intake", key=f"helpdesk:{t['id']}:{t.get('modifiedTime')}", route="triage",
                         input={"kind": "helpdesk", "ticket_id": str(t["id"])}, requester="")
            started.append(item["id"])
        window["offset"] += len(page)
        if len(page) < PAGE:
            cur = {"cursor": window["end"]}
            break
        cur = {"cursor": cur.get("cursor"), "window": window}
    with store.tx(hub_dir) as tconn:
        tconn.execute("INSERT INTO cursor(name, value) VALUES ('zoho_poll', ?) ON CONFLICT(name) DO UPDATE SET "
                      "value=excluded.value", (json.dumps(cur),))
    return {"state": "polled", "started": len(started), "cursor": cur}
