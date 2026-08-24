"""Delivery team tools: verify a delivery date change in ERPNext, or decline it."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

from agents import function_tool

_spec = importlib.util.spec_from_file_location(
    "_customer_desk_path_d", Path(__file__).resolve().parents[1] / "tools_local" / "_desk_path.py")
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)
HUB = _mod.HUB

from customer_desk import actions, chat  # noqa: E402
from customer_desk.flows import start_work  # noqa: E402


@function_tool
@chat.guard
def desk_verify_delivery(proposal_id: str) -> str:
    """After you changed the date in ERPNext: reread the order. Only a matching date drafts a confirmation."""
    return json.dumps(actions.verify_delivery(HUB, proposal_id, chat.actor(HUB), start=start_work(HUB)))


@function_tool
@chat.guard
def desk_decline_delivery(proposal_id: str, note: str) -> str:
    """Decline a delivery date change, with a note the reply explains to the customer."""
    return json.dumps(actions.decline_delivery(HUB, proposal_id, chat.actor(HUB), note=note, start=start_work(HUB)))
