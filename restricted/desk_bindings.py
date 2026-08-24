"""Binding admin tools: match a sender to one ERP customer. The model never
suggests the customer: the person names it, and the card shows it first."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

from agents import function_tool

_spec = importlib.util.spec_from_file_location(
    "_customer_desk_path_b", Path(__file__).resolve().parents[1] / "tools_local" / "_desk_path.py")
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)
HUB = _mod.HUB

from customer_desk import actions, bindings, chat, config, store  # noqa: E402
from customer_desk.flows import start_work  # noqa: E402


@function_tool
@chat.guard
def desk_bind_case(case: str, customer_id: str) -> str:
    """Bind the unknown sender of a binding_required case to the ERP customer the person names, then let the desk
    read that customer's records and prepare the case."""
    return json.dumps(actions.bind_case(HUB, case, chat.actor(HUB), customer_id, start=start_work(HUB)))


@function_tool
@chat.guard
def desk_bind_sender(channel_kind: str, sender: str, customer_id: str) -> str:
    """Add one binding: channel_kind email, whatsapp or helpdesk, the sender address or E.164 number, and the
    ERP customer id the person names."""
    return json.dumps(actions.bind_sender(HUB, chat.actor(HUB), channel_kind=channel_kind, sender=sender,
                                          customer_id=customer_id))


@function_tool
@chat.guard
def desk_revoke_binding(binding_id: str) -> str:
    """Revoke a binding. Open cases from that sender go back to waiting for a binding, and unsent replies on them
    are cancelled."""
    return json.dumps(actions.revoke_binding(HUB, chat.actor(HUB), binding_id))


@function_tool
@chat.guard
def desk_list_bindings() -> str:
    """Active sender bindings as a table."""
    actions.require(chat.actor(HUB), "desk_bindings")
    rows = [{"id": b["id"][:8], "kind": b["channel_kind"], "sender": b["sender_key"], "customer": b["customer_id"],
             "source": b["source_ref"] or ""}
            for b in bindings.list_bindings(store.connect(HUB), company=config.settings(HUB)["DESK_COMPANY"])]
    return json.dumps({"kind": "table", "title": "Sender bindings", "columns": [
        {"key": k, "label": k.title(), "type": "string"} for k in ("id", "kind", "sender", "customer", "source")],
        "rows": rows, "page": {"next_cursor": None, "total_rows": len(rows)}, "sources": []})
