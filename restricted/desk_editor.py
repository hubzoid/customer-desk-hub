"""Freshdesk editor payloads, callable through the SDK's authenticated MCP."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

from agents import function_tool

_spec = importlib.util.spec_from_file_location("_customer_editor_path", Path(__file__).resolve().parents[1] / "tools_local" / "_desk_path.py")
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)
HUB = _mod.HUB

from customer_desk import chat, config  # noqa: E402
from customer_desk.helpdesk import desk, editor  # noqa: E402


@function_tool
@chat.guard
def desk_editor_payload(ticket_id: str, agent_id: str, placed_digest: str | None = None,
                        claim: bool = False, placement_token: str | None = None) -> str:
    """For the native Freshdesk app: fetch a current scoped reply, or acknowledge editor placement.
    Identity is the verified MCP caller, never an email supplied in arguments. Placement does not attest persistence."""
    reader, _ = desk.readers(HUB, config.settings(HUB))
    return json.dumps(editor.payload(HUB, chat.actor(HUB), ticket_id=ticket_id, agent_id=agent_id,
                                     reader=reader, placed_digest=placed_digest, claim=claim, placement_token=placement_token))


@function_tool
@chat.guard
def desk_editor_attachment(ticket_id: str, agent_id: str, sha256: str) -> str:
    """Download one checked invoice PDF for the linked operator to attach personally in Freshdesk.
    Does not upload or send. Rechecks current ticket, identity and draft grants."""
    reader, _ = desk.readers(HUB, config.settings(HUB))
    return json.dumps(editor.attachment(HUB, chat.actor(HUB), ticket_id=ticket_id, agent_id=agent_id,
                                        sha256=sha256, reader=reader))
