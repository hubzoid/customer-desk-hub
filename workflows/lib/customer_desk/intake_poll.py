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
MAX_OFFSET = 4900       # Zoho Desk's search offset limit


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
    if values["DESK_HELPDESK"] not in ("zoho_desk", "freshdesk") or not values["DESK_INTAKE_ENABLED"]:
        return {"state": "off"}
    reader, _ = desk.readers(hub_dir, values)
    return poll_once(hub_dir, values, reader, start_work(hub_dir))


def poll_once(hub_dir: Path, values: dict, reader, start) -> dict:
    """One look for modified tickets, from the stored cursor or window."""
    conn = store.connect(hub_dir)
    now = dt.datetime.now(dt.timezone.utc)
    # Direct callers predating the second provider pass only Zoho settings.
    # Keep that legacy service contract while the configured poll passes the
    # explicit provider from config.settings().
    provider = values.get("DESK_HELPDESK", "zoho_desk")
    name = "freshdesk_poll" if provider == "freshdesk" else "zoho_poll"
    row = conn.execute("SELECT value FROM cursor WHERE name=?", (name,)).fetchone()
    cur = json.loads(row["value"]) if row else {"cursor": _iso(now - dt.timedelta(minutes=LOOKBACK_MINUTES))}
    window = cur.get("window") or {"start": _iso(dt.datetime.fromisoformat(cur["cursor"].replace("Z", "+00:00"))
                                                 - dt.timedelta(minutes=OVERLAP_MINUTES)),
                                   "end": _iso(now), "offset": 0}
    started = []
    for _ in range(MAX_PAGES):
        page = reader.modified(window["start"], window["end"], offset=window["offset"], limit=PAGE,
                               department_id=values.get("ZOHO_DESK_DEPARTMENT_ID") or None)
        for t in page:
            from .helpdesk import desk
            from .helpdesk.retrieval import permitted

            if not permitted(t, values):
                continue
            seen = conn.execute("SELECT observed_modified FROM helpdesk_tickets WHERE ticket_id=?",
                                (desk.ticket_key(values, str(t["id"])),)).fetchone()
            if seen and seen["observed_modified"] == t.get("modifiedTime"):
                continue
            item = start("customer_desk_intake", key=f"{provider}:{t['id']}:{t.get('modifiedTime')}", route="triage",
                         input={"kind": "helpdesk", "ticket_id": str(t["id"])}, requester="")
            started.append(item["id"])
        window["offset"] += len(page)
        if len(page) < PAGE:
            cur = {"cursor": window["end"]}
            break
        if window["offset"] + PAGE > MAX_OFFSET and page[-1].get("modifiedTime"):
            # Zoho search cannot page past 5000. Results come oldest first, so
            # the window starts again at the last ticket read; tickets seen
            # twice are skipped by their recorded modified time.
            window = {"start": page[-1]["modifiedTime"], "end": window["end"], "offset": 0}
        cur = {"cursor": cur.get("cursor"), "window": window}
    with store.tx(hub_dir) as tconn:
        tconn.execute("INSERT INTO cursor(name, value) VALUES (?, ?) ON CONFLICT(name) DO UPDATE SET "
                      "value=excluded.value", (name, json.dumps(cur)))
    return {"state": "polled", "started": len(started), "cursor": cur}
