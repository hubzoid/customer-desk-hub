"""Exception team tools: decide a refund or goodwill request outside policy.
The decision is recorded with who made it. The desk then drafts the reply
from that decision. Accounts make any credit note in ERPNext."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from typing import Literal

from agents import function_tool

_spec = importlib.util.spec_from_file_location(
    "_customer_desk_path_e", Path(__file__).resolve().parents[1] / "tools_local" / "_desk_path.py")
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)
HUB = _mod.HUB

from customer_desk import actions, chat  # noqa: E402
from customer_desk.flows import start_work  # noqa: E402


@function_tool
@chat.guard
def desk_decide_exception(case: str, decision_id: str, decision: Literal["approve", "decline"], amount: str,
                          customer_message: int, note: str) -> str:
    """Approve or decline a refund or goodwill request outside policy. Only the person deciding may call this,
    and they confirm the exact decision on the card first. Nothing is refunded here: accounts make any credit
    note in ERPNext.

    Args:
        case: The case number, for example CD-000020.
        decision_id: The decision id from the case's owner items.
        decision: approve or decline.
        amount: The amount the customer asked for, as the case shows it, so the card names it.
        customer_message: The customer's latest message number the person saw on the case.
        note: Why, in the person's words.
    """
    return json.dumps(actions.decide_exception(HUB, decision_id, chat.actor(HUB), approve=decision == "approve",
                                               note=note, start=start_work(HUB), case_number=case,
                                               seen_message=customer_message))
