"""Authenticated per-person Freshdesk editor payloads. Never attest persistence.

The native app calls these domain operations through Hubzoid's existing MCP
OAuth transport. Browser input is never identity or provider proof.
"""
from __future__ import annotations

import time
import hashlib
import hmac
import secrets
from pathlib import Path

from .. import actions, config, pipeline, recheck, store
from . import desk, retrieval, zoho

EDITOR_STATES = frozenset(("awaiting_provider_editor", "placing", "awaiting_provider_confirmation", "requires_manual_attachment"))


def link(hub_dir: Path, actor, *, agent_id: str, principal: str, reader) -> dict:
    actions.require(actor, "manage_access")
    agent = reader.agent(agent_id)
    email = ((agent.get("contact") or {}).get("email") or agent.get("email") or "").lower()
    principal = principal.strip().lower()
    if (not email or email != principal or agent.get("deleted") or agent.get("active") is False
            or (agent.get("contact") or {}).get("active") is False):
        raise actions.ActionError("identity_mismatch", "Freshdesk agent email must match the verified Hubzoid principal", 403)
    with store.tx(hub_dir) as conn:
        conn.execute("INSERT INTO editor_links(provider,agent_id,principal,state,verified_by,verified_at) VALUES "
                     "('freshdesk',?,?, 'active',?,?) ON CONFLICT(provider,agent_id) DO UPDATE SET "
                     "principal=excluded.principal,state='active',verified_by=excluded.verified_by,verified_at=excluded.verified_at",
                     (str(agent_id), principal, actor.email, time.time()))
        store.audit(conn, actor.email, "editor_link", principal, {"agent_id": agent_id})
    return {"provider": "freshdesk", "agent_id": str(agent_id), "principal": principal}


def prepare(hub_dir: Path, case: dict, reply: dict, reader) -> dict:
    """Inert server-side delivery record. It is not a provider draft."""
    values = config.settings(hub_dir)
    got = desk.read_ticket(reader, case["helpdesk_ticket_id"])
    if not retrieval.permitted(got["ticket"], values) or not desk.awaiting_reply(got["threads"]):
        raise actions.ActionError("ticket_changed", "Ticket is out of scope, closed or already answered")
    inbound = str(got["inbound"]["id"])
    recorded = store.connect(hub_dir).execute("SELECT latest_inbound_id FROM helpdesk_tickets WHERE ticket_id=?",
        (desk.ticket_key(values, case["helpdesk_ticket_id"]),)).fetchone()
    if recorded is None or str(recorded["latest_inbound_id"]) != inbound:
        raise actions.ActionError("ticket_changed", "A newer customer message requires fresh triage")
    if (got["ticket"].get("email") or "").lower() != (case.get("sender_key") or "").lower():
        raise actions.ActionError("recipient_changed", "Ticket contact changed. Rerun the case")
    if got["ticket"].get("statusType") in ("closed", "resolved"):
        raise actions.ActionError("ticket_changed", "Ticket is closed")
    if recheck.changed_facts(hub_dir, case, store.get_facts(store.connect(hub_dir), case["id"], reply["resolution"])):
        raise actions.ActionError("reply_stale", "Evidence changed since drafting")
    with store.tx(hub_dir) as conn:
        unresolved = conn.execute("SELECT reply_revision FROM editor_deliveries WHERE case_id=? AND inbound_id=? "
            "AND reply_revision != ? AND state IN ('placing','awaiting_provider_confirmation','requires_manual_attachment') LIMIT 1",
            (case["id"], inbound, reply["revision"])).fetchone()
        if unresolved:
            raise actions.ActionError("previous_delivery_uncertain", "An earlier suggestion for this message may be in the editor. Check Freshdesk before replacement")
        old = conn.execute("SELECT * FROM editor_deliveries WHERE case_id=? AND reply_revision=?",
                           (case["id"], reply["revision"])).fetchone()
        if old and (old["digest"] != reply["digest"] or old["inbound_id"] != inbound):
            raise actions.ActionError("reply_stale", "Delivery identity changed")
        conn.execute("INSERT OR IGNORE INTO editor_deliveries(case_id,reply_revision,digest,inbound_id,state,updated) "
                     "VALUES (?,?,?,?, 'awaiting_provider_editor',?)",
                     (case["id"], reply["revision"], reply["digest"], inbound, time.time()))
        state = old["state"] if old else "awaiting_provider_editor"
    return {"state": state, "ticket_id": case["helpdesk_ticket_id"], "digest": reply["digest"],
            "note": "Prepared for the native Freshdesk editor. Provider persistence is not yet verified."}


def payload(hub_dir: Path, actor, *, ticket_id: str, agent_id: str, reader, placed_digest: str | None = None,
            claim: bool = False, placement_token: str | None = None, expected_digest: str | None = None) -> dict:
    actions.require(actor, "desk_editor")
    actions.require(actor, "desk_operator")
    values = config.settings(hub_dir)
    if (values["DESK_HELPDESK"] != "freshdesk" or values["DESK_HELPDESK_MODE"] != "live"
            or not values["DESK_HELPDESK_DRAFTS"] or zoho.stop_switch(hub_dir)):
        raise actions.ActionError("drafts_off", "Freshdesk drafts are not enabled", 403)
    from hubzoid.work_items import config as wi_config

    if wi_config.mode_for(wi_config.load(hub_dir), ["customer_reply.send"], "freshdesk") != "draft":
        raise actions.ActionError("drafts_off", "The current reply action mode does not permit unattended draft placement", 403)
    conn = store.connect(hub_dir)
    linked = conn.execute("SELECT * FROM editor_links WHERE provider='freshdesk' AND agent_id=? AND principal=? "
                          "AND state='active'", (str(agent_id), actor.email)).fetchone()
    if linked is None:
        raise actions.ActionError("identity_unlinked", "An administrator must verify your Freshdesk account link", 403)
    agent = reader.agent(agent_id)
    email = ((agent.get("contact") or {}).get("email") or agent.get("email") or "").lower()
    if (email != actor.email or agent.get("deleted") or agent.get("active") is False
            or (agent.get("contact") or {}).get("active") is False):
        raise actions.ActionError("identity_revoked", "Freshdesk agent identity is no longer active", 403)
    ticket = reader.ticket(ticket_id)
    if not retrieval.permitted(ticket, values):
        raise actions.ActionError("permission_denied", "Ticket is outside the configured source scope", 403)
    # Mirror provider agent ticket_scope as well as Hubzoid's grants.
    scope = agent.get("ticket_scope")
    if scope == 3 and str(ticket.get("responder_id")) != str(agent_id):
        raise actions.ActionError("permission_denied", "Ticket is not assigned to this Freshdesk agent", 403)
    if scope == 2 and (str(ticket.get("group_id")) not in {str(g) for g in agent.get("group_ids") or []}
                       and str(ticket.get("responder_id")) != str(agent_id)):
        raise actions.ActionError("permission_denied", "Ticket is outside this agent's groups", 403)
    if scope not in (1, 2, 3):
        raise actions.ActionError("permission_denied", "Freshdesk ticket scope could not be verified", 403)
    rows = store.rows(conn.execute("SELECT * FROM cases WHERE provider='freshdesk' AND helpdesk_ticket_id=? "
                                   "AND current_reply IS NOT NULL ORDER BY updated DESC LIMIT 1", (str(ticket_id),)))
    if not rows:
        raise actions.ActionError("not_found", "No current checked reply for this ticket", 404)
    case = rows[0]
    reply = store.get_reply(conn, case["id"], case["current_reply"])
    if not reply["checks"].get("passed") or reply["state"] in ("superseded", "rejected"):
        raise actions.ActionError("reply_stale", "Reply is not safe/current")
    if claim and expected_digest != reply["digest"]:
        raise actions.ActionError("reply_stale", "Suggestion changed since confirmation. Show it again before replacement")
    resolution = store.get_resolution(conn, case["id"], reply["resolution"])
    loaded = pipeline.load(hub_dir)
    if any(resolution[k + "_digest"] != loaded.digests()[k] for k in ("policy", "style", "kinds")):
        raise actions.ActionError("reply_stale", "Rules changed. Rerun this case")
    prepared = prepare(hub_dir, case, reply, reader)
    delivery = conn.execute("SELECT * FROM editor_deliveries WHERE case_id=? AND reply_revision=?",
                            (case["id"], reply["revision"])).fetchone()
    if placed_digest:
        if placed_digest != reply["digest"]:
            raise actions.ActionError("reply_stale", "Editor placement refers to an older reply")
        supplied = hashlib.sha256((placement_token or "").encode()).hexdigest()
        if (delivery["state"] != "placing" or delivery["placed_by"] != actor.email
                or not hmac.compare_digest(supplied, delivery["claim_hash"] or "")):
            raise actions.ActionError("placement_claim_required", "Only the matching editor claim can acknowledge placement", 403)
        state = "requires_manual_attachment" if reply.get("attachments") else "awaiting_provider_confirmation"
        with store.tx(hub_dir) as tconn:
            changed = tconn.execute("UPDATE editor_deliveries SET state=?,updated=? "
                          "WHERE case_id=? AND reply_revision=? AND state='placing' AND placed_by=? AND claim_hash=?",
                          (state, time.time(), case["id"], reply["revision"], actor.email, supplied)).rowcount
            if changed != 1:
                raise actions.ActionError("placement_claim_lost", "Placement was already acknowledged or changed")
            store.update_case(tconn, case["id"], state=state)
        return {"state": state, "digest": reply["digest"], "attachments": reply["attachments"],
                "note": ("Body placed. Download and attach the checked PDF personally in Freshdesk. No attachment delivery or persistence claimed."
                         if reply.get("attachments") else "Editor placement acknowledged. Provider persistence remains unverified.")}
    if delivery["state"] != "awaiting_provider_editor":
        return {"state": delivery["state"], "digest": reply["digest"], "body": None,
                "attachments": reply["attachments"], "case": case["number"],
                "note": "Placement is claimed or acknowledged. Check Freshdesk manually. No automatic retry or expiry."}
    token = None
    if claim:
        token = secrets.token_urlsafe(32)
        with store.tx(hub_dir) as tconn:
            current = store.get_case(tconn, case["id"])
            if current["current_reply"] != reply["revision"]:
                raise actions.ActionError("reply_stale", "Reply changed before editor placement")
            changed = tconn.execute("UPDATE editor_deliveries SET state='placing',placed_by=?,claim_hash=?,updated=? "
                "WHERE case_id=? AND reply_revision=? AND state='awaiting_provider_editor'",
                (actor.email, hashlib.sha256(token.encode()).hexdigest(), time.time(), case["id"], reply["revision"])).rowcount
            if changed != 1:
                return {"state": "placing", "body": None, "digest": reply["digest"], "note": "Another operator claimed this suggestion. Check Freshdesk."}
            store.update_case(tconn, case["id"], state="provider_delivery_uncertain")
    return {**prepared, "case": case["number"], "reply_revision": reply["revision"], "body": reply["rendered"],
            "placement_token": token,
            "inbound_id": delivery["inbound_id"], "attachments": reply["attachments"]}


def attachment(hub_dir: Path, actor, *, ticket_id: str, agent_id: str, sha256: str, reader) -> dict:
    """Explicit operator download, scoped through the same live payload wall.

    Freshdesk's native attachment UI remains the human's action. This tool
    never uploads, sends or claims an attachment has reached the provider.
    """
    import base64

    checked = payload(hub_dir, actor, ticket_id=ticket_id, agent_id=agent_id, reader=reader)
    # An already placed suggestion still has case identity for scoped reads.
    rows = store.rows(store.connect(hub_dir).execute("SELECT * FROM cases WHERE provider='freshdesk' "
        "AND helpdesk_ticket_id=? AND current_reply IS NOT NULL ORDER BY updated DESC LIMIT 1", (str(ticket_id),)))
    case = rows[0]
    reply = store.get_reply(store.connect(hub_dir), case["id"], case["current_reply"])
    if checked["digest"] != reply["digest"]:
        raise actions.ActionError("reply_stale", "Reply changed during attachment read")
    match = next((a for a in reply["attachments"] if a["sha256"] == sha256), None)
    if match is None or match["media_type"] != "application/pdf" or match["bytes"] > 5 * 1024 * 1024:
        raise actions.ActionError("not_found", "No permitted invoice attachment on this checked reply", 404)
    data = pipeline.attachment_bytes(hub_dir, sha256)
    if "sha256:" + hashlib.sha256(data).hexdigest() != sha256:
        raise actions.ActionError("attachment_changed", "Stored attachment digest does not match")
    return {"name": match["name"], "media_type": match["media_type"], "base64": base64.b64encode(data).decode(),
            "digest": reply["digest"], "note": "Download and attach this file personally in Freshdesk. No provider upload claimed."}


def reconcile(hub_dir: Path, actor, *, ticket_id: str, decision: str) -> dict:
    """Trusted-host human recovery after inspecting the actual provider editor."""
    actions.require(actor, "manage_access")
    if decision not in ("not_inserted", "placed"):
        raise actions.ActionError("validation_failed", "Choose not_inserted or placed after checking Freshdesk")
    with store.tx(hub_dir) as conn:
        rows = store.rows(conn.execute("SELECT d.* FROM editor_deliveries d JOIN cases c ON c.id=d.case_id "
            "WHERE c.provider='freshdesk' AND c.helpdesk_ticket_id=? AND d.state='placing'", (str(ticket_id),)))
        if len(rows) != 1:
            raise actions.ActionError("state_conflict", "Expected exactly one uncertain editor claim")
        old = rows[0]
        reply = store.get_reply(conn, old["case_id"], old["reply_revision"])
        state = ("awaiting_provider_editor" if decision == "not_inserted" else
                 "requires_manual_attachment" if reply.get("attachments") else "awaiting_provider_confirmation")
        conn.execute("UPDATE editor_deliveries SET state=?,claim_hash=NULL,placed_by=NULL,updated=? "
            "WHERE case_id=? AND reply_revision=? AND state='placing'", (state, time.time(), old["case_id"], old["reply_revision"]))
        store.update_case(conn, old["case_id"], state=state)
        store.audit(conn, actor.email, "editor_manual_reconcile", old["case_id"],
                    {"decision": decision, "digest": old["digest"], "reply_revision": old["reply_revision"]})
    return {"state": state, "digest": old["digest"], "provider_persistence": "unverified"}
