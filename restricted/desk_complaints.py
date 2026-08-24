"""Complaint team tools: review escalation plans."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

from agents import function_tool

_spec = importlib.util.spec_from_file_location(
    "_customer_desk_path_c", Path(__file__).resolve().parents[1] / "tools_local" / "_desk_path.py")
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)
HUB = _mod.HUB

from customer_desk import actions, chat  # noqa: E402


@function_tool
@chat.guard
def desk_review_plan(case: str, approve: bool, note: str) -> str:
    """Approve an escalation plan, or ask for changes with a note. Approving a plan never approves a send."""
    return json.dumps(actions.review_plan(HUB, case, chat.actor(HUB), approve=approve, note=note))
