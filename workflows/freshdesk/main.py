"""Freshdesk authenticated notification intake. The API is the source of truth."""
from __future__ import annotations

import sys
from pathlib import Path

_LIB = Path(__file__).resolve().parents[1] / "lib"
if str(_LIB) not in sys.path:
    sys.path.insert(0, str(_LIB))

from hubzoid import hub, workflow  # noqa: E402
from customer_desk import config, flows, intake_poll  # noqa: E402
from customer_desk.routes import TRIAGE  # noqa: E402


@workflow(on_webhook="freshdesk", work_items={"triage": TRIAGE}, timeout="30m", concurrency=2,
          concurrency_key="ticket_id")
def freshdesk_ticket():
    """A provider event names a ticket. Reread it under the configured scope."""
    values = config.settings(flows._hub_dir())
    if values["DESK_HELPDESK"] != "freshdesk":
        return {"state": "off"}
    ticket_id = intake_poll.ticket_id_from(hub.event.body if hub.event else hub.work_item.input)
    return flows.triage_item({"kind": "helpdesk", "ticket_id": ticket_id}) if ticket_id else {"state": "ignored"}
