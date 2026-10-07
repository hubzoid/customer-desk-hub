"""Desk operator tools: claim a case, edit its reply, save a draft, ask to
send, rerun, open an internal case. Only people granted desk_operator see
these. A send waits for the requester's own approval on the Work items page."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

from agents import function_tool

_spec = importlib.util.spec_from_file_location(
    "_customer_desk_path_r", Path(__file__).resolve().parents[1] / "tools_local" / "_desk_path.py")
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)
HUB = _mod.HUB

from customer_desk import actions, chat  # noqa: E402
from customer_desk.flows import start_work  # noqa: E402


def _a():
    return chat.actor(HUB)


@function_tool
@chat.guard
def desk_claim(case: str) -> str:
    """Claim a case so you are the one working on it."""
    return json.dumps(actions.claim(HUB, case, _a()))


@function_tool
@chat.guard
def desk_release(case: str) -> str:
    """Release a case you hold back to its queue."""
    return json.dumps(actions.release(HUB, case, _a()))


@function_tool
@chat.guard
def desk_edit_reply(case: str, body: str, keep_attachments: bool = True) -> str:
    """Save the teammate's own version of the reply, exactly as they wrote it. Never change their words. Fact
    placeholders such as [[F3]] may stay. Values they type are flagged on the approval card. keep_attachments false
    drops the attachments, for a channel that carries text only."""
    return json.dumps(actions.edit_reply(HUB, case, _a(), body, keep_attachments=keep_attachments))


@function_tool
@chat.guard
def desk_request_send(case: str, reply_revision: int, digest: str) -> str:
    """Ask to send the exact reply revision with this digest. Hubzoid sends only after the person asking approves
    the exact content on the Work items page. Only in approve mode."""
    out = actions.request_send(HUB, case, _a(), reply_revision=reply_revision, digest=digest, expected_revision=None,
                               start=start_work(HUB))
    return chat.progress(out, out["message"])


@function_tool
@chat.guard
def desk_save_draft(case: str, reply_revision: int, digest: str) -> str:
    """Save the exact reply as a real, unsent draft in the mailbox (draft mode only). A person finishes it there."""
    out = actions.save_draft(HUB, case, _a(), reply_revision=reply_revision, digest=digest, start=start_work(HUB))
    return chat.progress(out, "Saving the draft. Nothing is sent.")


@function_tool
@chat.guard
def desk_rerun(case: str, instruction: str | None = None) -> str:
    """Prepare the case again, optionally with an internal instruction for the resolver. It cannot change the
    customer, the tools or the policy."""
    out = actions.rerun(HUB, case, _a(), instruction=instruction, start=start_work(HUB))
    return chat.progress(out, "Rerunning: reading ERPNext and drafting a new reply revision.")


@function_tool
@chat.guard
def desk_open_case(customer_id: str, text: str) -> str:
    """Open an internal case for a named customer, for example a phone call: "SYN-CUST-002 called for a copy of
    invoice ACC-SINV-2000-00004". The reply is for the teammate to deliver. It is never sent."""
    out = actions.open_internal(HUB, _a(), customer_id=customer_id, text=text, start=start_work(HUB))
    return chat.progress(out, "Opening an internal case and preparing a reply for you to deliver.")


@function_tool
@chat.guard
def desk_share_plan(case: str, plan: str) -> str:
    """Share a written resolution plan for an escalated case. The complaint team reviews it before a reply can be
    requested. Approving a plan never approves a send."""
    return json.dumps(actions.share_plan(HUB, case, _a(), plan))


@function_tool
@chat.guard
def desk_set_state(case: str, to: str, reason: str) -> str:
    """Resolve, reopen or cancel a case: to is resolved, needs_owner (reopen) or cancelled."""
    return json.dumps(actions.set_state(HUB, case, _a(), to=to, reason=reason))


@function_tool
@chat.guard
def desk_import_transcript(customer_id: str, transcript_text: str, name: str = "transcript.txt") -> str:
    """Read a call or meeting transcript with one named customer. The desk opens one internal case per customer
    request it finds, each citing its transcript lines, with a ready reply for the teammate to deliver."""
    from customer_desk.transcripts import import_transcript

    out = import_transcript(HUB, _a(), customer_id=customer_id, text=transcript_text, name=name,
                            start=start_work(HUB))
    return chat.progress(out, f"Reading {out['lines']} transcript lines for customer requests.")


@function_tool
@chat.guard
def desk_preview(customer_id: str, text: str) -> str:
    """Try a customer message against the desk for a named customer without opening a case: shows the outcome,
    the facts, the reply and its checks, and the policy settings the policy file leaves to defaults. Nothing is
    saved to the queue, drafted or sent."""
    out = actions.preview(HUB, _a(), customer_id=customer_id, text=text, start=start_work(HUB))
    return chat.progress(out, f"Preparing preview {out['preview']}. Ask for desk_preview_result {out['preview']} in "
                              "a minute.")


@function_tool
@chat.guard
def desk_preview_result(preview: str) -> str:
    """The result of a preview: outcomes, facts, the reply with its checks, and the policy gaps."""
    from customer_desk import store

    c = store.get_case(store.connect(HUB), preview)
    if c is None or c["namespace"] != "preview":
        return json.dumps({"error": "not_found", "message": f"No preview {preview}."})
    return json.dumps(actions.preview_result(HUB, c["id"]))
