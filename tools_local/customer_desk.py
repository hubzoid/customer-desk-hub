"""Customer Desk tools anyone with a desk role may use, plus the resolver
station's read tools. Every tool checks the signed-in person's role, and the
resolver tools take their case from the running work item, never from the
model."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

from agents import function_tool

_spec = importlib.util.spec_from_file_location("_customer_desk_path", Path(__file__).with_name("_desk_path.py"))
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)
HUB = _mod.HUB

from customer_desk import actions, chat, stationtools  # noqa: E402
from customer_desk.flows import start_work  # noqa: E402


# -- views for teammates ----------------------------------------------------------------------

@function_tool
@chat.guard
def desk_queue(tab: str = "open", cursor: str | None = None, customer: str | None = None) -> str:
    """The Customer Desk queue as a table. tab is one of open, mine, operators, delivery, complaints, decisions,
    held, bindings or all. Pass cursor from the previous page for the next one. customer narrows to one ERP
    customer id."""
    return chat.queue(HUB, tab, cursor, customer)


@function_tool
@chat.guard
def desk_show_case(case: str) -> str:
    """One case in full: the conversation, each request with its outcome and policy rules, the facts read from
    ERPNext with their sources, the proposed reply with every check and the reviewer's verdict, owner items and
    drafts or sends. case is a case number such as CD-000007."""
    return chat.show(HUB, case)


@function_tool
@chat.guard
def desk_lookup(customer_id: str, kind: str, ref: str | None = None) -> str:
    """Read only ERPNext lookup for one named customer: kind is order, orders, invoice or invoices, ref an
    optional document id. Use it when a teammate asks about a customer in chat."""
    return chat.lookup(HUB, customer_id, kind, ref)


@function_tool
@chat.guard
def desk_metrics() -> str:
    """The desk's measures observed in this deployment: requests resolved, response time, reopen rate and
    the share of replies sent without edits."""
    return chat.metrics(HUB)


@function_tool
@chat.guard
def desk_health() -> str:
    """Queue health for admins: channels and their reply modes, what is waiting in each queue, held and
    uncertain sends, and the helpdesk connection."""
    return chat.health(HUB)


@function_tool
@chat.guard
def desk_pending_approval(case: str) -> str:
    """The reply on this case that waits for its requester's approval, as an approval card."""
    return chat.pending_approval(HUB, case)


@function_tool
@chat.guard
def desk_policy_show() -> str:
    """The active desk policy rules and the settings the policy file leaves to defaults."""
    return chat.policy_summary(HUB)


@function_tool
@chat.guard
def desk_update_ticket(ticket: str, state: str | None = None, assignee: str | None = None,
                       note: str | None = None) -> str:
    """Change a desk ticket: state (open, in_progress, resolved, cancelled), assignee email, or add a note.
    Needs the delivery role for delivery tickets and the complaints role for the rest."""
    import json

    return json.dumps(actions.update_ticket(HUB, ticket, chat.actor(HUB), state=state, assignee=assignee, note=note,
                                            start=start_work(HUB)))


# -- the resolver station's read tools (case from the running work item) -------------------------

@function_tool
def desk_orders(order_ids: list[str] | None = None, open_only: bool = True) -> str:
    """This case's customer's sales orders: the ids given, or their open orders. Returns facts with ids."""
    return stationtools.orders(HUB, order_ids, open_only)


@function_tool
def desk_invoice(invoice_id: str) -> str:
    """One submitted invoice of this case's customer. Returns facts with ids, or not_found."""
    return stationtools.invoice(HUB, invoice_id)


@function_tool
def desk_open_invoices(from_date: str | None = None, to_date: str | None = None) -> str:
    """This case's customer's submitted invoices with an outstanding amount, optionally within dates (YYYY-MM-DD)."""
    return stationtools.open_invoices(HUB, from_date, to_date)


@function_tool
def desk_prices(item_codes: list[str]) -> str:
    """Valid prices for up to 20 item codes on this case's customer's price list. Returns facts with ids."""
    return stationtools.prices(HUB, item_codes)


@function_tool
def desk_availability(item_codes: list[str]) -> str:
    """Availability for up to 20 item codes, disclosed as the policy allows. Returns facts with ids."""
    return stationtools.availability(HUB, item_codes)


@function_tool
def desk_find_items(text: str) -> str:
    """Up to 10 active items whose names match the text. Returns facts with ids."""
    return stationtools.find_items(HUB, text)


@function_tool
def desk_policy(section: str) -> str:
    """One policy value by dotted key, such as refunds.within_days, registered as a fact, plus the rule texts."""
    return stationtools.policy(HUB, section)
