"""Zoho Desk intake: a webhook names a ticket, and a poll catches follow-ups
the webhook missed. The body is never trusted. Each ticket is reread."""
import sys
from pathlib import Path

_LIB = Path(__file__).resolve().parents[1] / "lib"
if str(_LIB) not in sys.path:
    sys.path.insert(0, str(_LIB))

from hubzoid import hub, workflow  # noqa: E402
from customer_desk import flows, intake_poll  # noqa: E402
from customer_desk.routes import TRIAGE  # noqa: E402


@workflow(on_webhook="zoho-desk", work_items={"triage": TRIAGE}, timeout="30m", concurrency=2,
          concurrency_key="ticketId")
def zoho_desk_ticket():
    """A Zoho Desk ticket was created or the customer replied."""
    ticket_id = intake_poll.ticket_id_from(hub.event.body if hub.event else hub.work_item.input)
    if ticket_id is None:
        return {"state": "ignored", "message": "The event named no ticket id."}
    return flows.triage_item({"kind": "helpdesk", "ticket_id": ticket_id})


@workflow("every 1 minute")
def zoho_desk_poll():
    """Common provider poll: Zoho or Freshdesk, with a 15 minute overlap.

    The existing workflow name is retained for scheduler compatibility.
    """
    return intake_poll.poll()
