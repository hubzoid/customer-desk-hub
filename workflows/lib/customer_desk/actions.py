"""What people do on a case. Chat tools and the CLI call these, so the rules
are the same everywhere.

Every action names its actor, the person verified by Hubzoid's sign-in, and
checks that person's desk role. Nothing here can be done by a model on its
own: the chat tools that reach a decision ask the person first (`hitl.yaml`),
and a reply leaves only through an operation the requester approves on the
Work items page.

Work that runs on the engine (a send, a draft, a rerun) is started through
`start`, which the hub binds to Hubzoid's work items and tests bind inline.
"""
from __future__ import annotations

import hashlib
import time
from pathlib import Path
from typing import Callable

from . import bindings as bindings_lib
from . import cases, checks, config, envelopes, facts as facts_lib, pipeline, render, replies, store
from .erpnext import config as erp_config
from .erpnext.contract import ERPContext, ERPError

ADMIN = "manage_access"


class ActionError(Exception):
    def __init__(self, code: str, message: str, status: int = 409, **fields):
        super().__init__(message)
        self.code, self.message, self.status, self.fields = code, message, status, fields

    def to_json(self) -> dict:
        return {"error": self.code, "message": self.message, **self.fields}


class Actor:
    """A verified person: their email and what they may do in this hub."""

    def __init__(self, email: str, can: Callable[[str], bool]):
        self.email = (email or "").strip().lower()
        self._can = can

    def can(self, role: str) -> bool:
        return bool(self.email) and self._can(role)

    def any(self, *roles) -> bool:
        return any(self.can(r) for r in roles)


def require(actor: Actor, *roles: str) -> None:
    if not actor.any(*roles, ADMIN):
        raise ActionError("permission_denied", f"This needs one of these desk roles: {', '.join(roles)}. Ask the agent's "
                          "manager to grant it in Settings, Access.", 403)


def _case(hub_dir: Path, ref: str) -> dict:
    c = store.get_case(store.connect(hub_dir), ref)
    if c is None:
        raise ActionError("not_found", f"No case {ref}.", 404)
    return c


def _claimed(case: dict, actor: Actor) -> None:
    if case["claimed_by"] != actor.email:
        who = case["claimed_by"] or "nobody"
        raise ActionError("claim_required", f"Claim {case['number']} first. It is held by {who}.", 409)


# -- claim and release -------------------------------------------------------------------

def claim(hub_dir: Path, ref: str, actor: Actor, *, expected_revision: int | None = None) -> dict:
    case = _case(hub_dir, ref)
    role = config.QUEUE_ROLE.get(case["queue"] or "operators", "desk_operator")
    require(actor, role, "desk_operator")
    if case["state"] in ("binding_required", "triaging", "received", "sending", "cancelled"):
        raise ActionError("state_conflict", f"{case['number']} is {case['state']} and cannot be claimed now.")
    if case["claimed_by"] and case["claimed_by"] != actor.email:
        since = time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime(case["claimed_at"] or 0))
        raise ActionError("claim_conflict", f"{case['claimed_by']} holds {case['number']} since {since}.",
                          held_by=case["claimed_by"])
    with store.tx(hub_dir) as conn:
        state = "in_review" if case["state"] == "needs_owner" else case["state"]
        c = store.update_case(conn, case["id"], expected_revision=expected_revision, claimed_by=actor.email,
                              claimed_at=time.time(), state=state)
        store.audit(conn, actor.email, "case_claim", c["id"])
    return {"case": c["number"], "state": c["state"], "revision": c["revision"], "claimed_by": actor.email}


def release(hub_dir: Path, ref: str, actor: Actor) -> dict:
    case = _case(hub_dir, ref)
    if case["claimed_by"] != actor.email and not actor.can(ADMIN):
        raise ActionError("permission_denied", "Only the person holding the case, or a manager, can release it.", 403)
    with store.tx(hub_dir) as conn:
        state = "needs_owner" if case["state"] == "in_review" else case["state"]
        c = store.update_case(conn, case["id"], claimed_by=None, claimed_at=None, state=state)
        store.audit(conn, actor.email, "case_release", c["id"])
    return {"case": c["number"], "state": c["state"], "revision": c["revision"]}


# -- replies -------------------------------------------------------------------------------

def edit_reply(hub_dir: Path, ref: str, actor: Actor, body: str, *, keep_attachments: bool = True) -> dict:
    """A person's own revision. It may use fact placeholders. Values they type
    are flagged, and checks 1, 2, 3, 6, 7 and 9 run."""
    require(actor, "desk_operator")
    case = _case(hub_dir, ref)
    _claimed(case, actor)
    if not (body or "").strip():
        raise ActionError("validation_failed", "The reply is empty.", 422)
    loaded = pipeline.load(hub_dir)
    conn = store.connect(hub_dir)
    base = store.get_reply(conn, case["id"], case["current_reply"]) if case["current_reply"] else None
    if base is None:
        raise ActionError("state_conflict", "There is no reply to edit yet. Rerun the case first.")
    res = store.get_resolution(conn, case["id"], base["resolution"])
    attachments = base["attachments"] if keep_attachments else []
    facts = {f["fact_id"]: f for f in store.get_facts(conn, case["id"], base["resolution"])}
    rendered = render.render(body, facts, sender_name=render.safe_name(case["sender_display"]),
                             observed=facts_lib.display("date", (next(iter(facts.values()))["observed_at"]
                                                                 if facts else "2000-01-01")[:10]), strict=False)
    outcomes = res["requests"]
    result = checks.run(case=case, source=body, rendered=rendered, facts=facts, policy=loaded.policy,
                        author_kind="person", outcomes=outcomes, resolver_outcomes=None, attachments=attachments,
                        language=base["language"], current_digests=loaded.digests(), used_digests=loaded.digests(),
                        decisions=store.case_decisions(conn, case["id"]))
    with store.tx(hub_dir) as tconn:
        rev = store.next_reply(tconn, case["id"])
        for old in store.replies(tconn, case["id"]):
            if old["state"] in ("ready", "requested", "mailbox_draft_saved", "helpdesk_draft_saved"):
                store.set_reply_state(tconn, case["id"], old["revision"], "superseded")
        dg = render.digest(case_id=case["id"], reply_revision=rev, body=rendered, subject=base["subject"],
                           recipients=base["recipients"], attachments=attachments,
                           policy_digest=loaded.policy.digest, fact_sheet_digest=res["fact_sheet_digest"],
                           origin={"channel": case["channel_id"], "thread": case["thread_key"]})
        reply = store.save_reply(tconn, case["id"], rev, resolution=base["resolution"], author_kind="person",
                                 author=actor.email, source_md=body, rendered=rendered, language=base["language"],
                                 recipients=base["recipients"], subject=base["subject"], attachments=attachments,
                                 digest=dg, checks={"results": result["checks"], "passed": result["passed"],
                                                    "style": checks.style_notes(rendered, loaded.style)},
                                 typed_values=result["typed_values"], state="ready")
        c = store.update_case(tconn, case["id"], current_reply=rev)
        store.audit(tconn, actor.email, "reply_edit", case["id"], {"revision": rev})
    return {"case": c["number"], "reply": rev, "digest": dg, "checks_passed": result["passed"],
            "checks": result["checks"], "typed_by_person": result["typed_values"], "revision": c["revision"]}


def _mode(hub_dir: Path, channel: str | None) -> str:
    """The reply mode for this channel. A Hubzoid email channel also performs
    email.send, so the stricter of the two applies, as Hubzoid enforces."""
    from hubzoid.work_items import config as wi_config

    from . import replies

    acts = ["customer_reply.send"]
    if channel and channel not in replies.SAMPLE_CHANNELS and replies.channel_kind(channel) == "email":
        acts.append("email.send")
    return wi_config.mode_for(wi_config.load(hub_dir), acts, channel)


def _current_reply(hub_dir: Path, case: dict, reply_revision: int, digest: str) -> dict:
    conn = store.connect(hub_dir)
    reply = store.get_reply(conn, case["id"], int(reply_revision))
    if reply is None:
        raise ActionError("not_found", f"{case['number']} has no reply {reply_revision}.", 404)
    if case["current_reply"] != reply["revision"] or reply["state"] not in ("ready", "mailbox_draft_saved",
                                                                            "helpdesk_draft_saved"):
        raise ActionError("reply_stale", f"Reply {reply_revision} is no longer current ({reply['state']}). Review "
                          f"reply {case['current_reply']}.", current_reply=case["current_reply"])
    if digest != reply["digest"]:
        raise ActionError("reply_stale", "The digest does not match this reply. Reload the case.",
                          current_digest=reply["digest"])
    if not (reply["checks"] or {}).get("passed"):
        failed = [c["id"] for c in reply["checks"]["results"] if c["status"] == "fail"]
        raise ActionError("checks_failed", f"Reply {reply_revision} failed checks: {', '.join(failed)}. Edit or rerun.")
    return reply


def _plan_ok(hub_dir: Path, case: dict) -> None:
    loaded = pipeline.load(hub_dir)
    conn = store.connect(hub_dir)
    res = store.get_resolution(conn, case["id"], case["current_resolution"]) if case["current_resolution"] else {}
    escalated = (res or {}).get("actions", {}).get("escalations")
    if escalated and loaded.policy.data["escalation"]["plan_review"] == "required":
        plan = conn.execute("SELECT * FROM plans WHERE case_id=? ORDER BY version DESC LIMIT 1", (case["id"],)).fetchone()
        if plan is None or plan["state"] != "approved":
            raise ActionError("plan_required", f"{case['number']} is escalated. Share a resolution plan and get the "
                              "complaint team's review before asking to send.")


def _stale_facts(hub_dir: Path, case: dict, reply: dict) -> list[dict]:
    from . import recheck

    facts = store.get_facts(store.connect(hub_dir), case["id"], reply["resolution"])
    try:
        return recheck.changed_facts(hub_dir, case, facts, policy=pipeline.load(hub_dir).policy)
    except ERPError as exc:
        raise ActionError(exc.code, f"ERPNext could not be reread ({exc.message}). Nothing was sent.", 503) from None


def _origin(case: dict, actor: Actor) -> dict:
    """A reply on a Hubzoid channel goes back on the case's stored thread. The
    person asking is who acts and who approves."""
    origin = case.get("origin") or {}
    if origin.get("surface") != "channel":
        return {}
    return {"origin": dict(origin, acts_as=actor.email, released_by=origin.get("released_by"))}


def request_send(hub_dir: Path, ref: str, actor: Actor, *, reply_revision: int, digest: str,
                 expected_revision: int | None, start) -> dict:
    """Ask Hubzoid to send the exact reply after the requester approves it."""
    require(actor, "desk_operator")
    case = _case(hub_dir, ref)
    _claimed(case, actor)
    if expected_revision is not None and case["revision"] != expected_revision:
        raise ActionError("revision_conflict", "The case changed since you loaded it. Reload.",
                          current_revision=case["revision"])
    if case["origin_kind"] == "internal":
        raise ActionError("mode_unsupported", "An internal case has no customer origin. Copy the reply and deliver it "
                          "yourself.", 422)
    if replies.channel_kind(case["channel_id"]) == "helpdesk":
        raise ActionError("mode_unsupported", "Helpdesk replies are sent by a person in the helpdesk. Save a draft "
                          "there instead.", 422)
    mode = _mode(hub_dir, case["channel_id"])
    if mode != "approve":
        raise ActionError("write_mode_" + mode.replace("direct", "off"), f"Replies on {case['channel_id']} are in "
                          f"{mode} mode. Sending needs customer_reply.send: approve in work-items.yaml.", 403)
    reply = _current_reply(hub_dir, case, reply_revision, digest)
    if (case.get("origin") or {}).get("surface") == "channel" and reply["attachments"]:
        raise ActionError("attachments_unsupported", "Replies through a Hubzoid channel carry text only, and this reply "
                          "attaches " + ", ".join(a["name"] for a in reply["attachments"]) + ". Save it as a draft "
                          "in the mailbox, or edit the reply to send it without the attachment.", 422)
    _plan_ok(hub_dir, case)
    stale = _stale_facts(hub_dir, case, reply)
    if stale:
        rerun(hub_dir, ref, actor, instruction=None, start=start, reason="facts_changed", stale=stale)
        raise ActionError("reply_stale", "ERPNext changed since this reply was drafted: "
                          + ", ".join(f"{s['fact_id']} {s['was']} -> {s['now']}" for s in stale)
                          + ". A new revision is being drafted. Review it.", stale=stale)
    item = start("customer_desk_case", key=f"send:{case['id']}:{reply['revision']}", route="send",
                 input={"action": "send", "case_id": case["id"], "reply_revision": reply["revision"],
                        "digest": reply["digest"]}, requester=actor.email, **_origin(case, actor))
    with store.tx(hub_dir) as conn:
        store.set_reply_state(conn, case["id"], reply["revision"], "requested")
        store.upsert_send(conn, case["id"], reply["revision"], "approve", synthetic=case["synthetic"],
                          work_item_id=item["id"], status="waiting_approval", requested_by=actor.email)
        c = store.update_case(conn, case["id"], state="waiting_approval")
        store.audit(conn, actor.email, "send_request", case["id"], {"reply": reply["revision"], "item": item["id"]})
    return {"state": "human_action_required", "case": c["number"], "reply": reply["revision"], "digest": reply["digest"],
            "work_item_id": item["id"], "revision": c["revision"],
            "message": "Approve the exact reply on the Work items page. Only you, the requester, can approve it."}


def save_draft(hub_dir: Path, ref: str, actor: Actor, *, reply_revision: int, digest: str, start) -> dict:
    """Save the exact reply as a real, unsent draft in the mailbox or helpdesk."""
    require(actor, "desk_operator")
    case = _case(hub_dir, ref)
    _claimed(case, actor)
    if case["origin_kind"] == "internal":
        raise ActionError("mode_unsupported", "An internal case has no mailbox to draft in.", 422)
    if case["channel_id"] in replies.NO_DRAFT or replies.channel_kind(case["channel_id"]) == "whatsapp":
        raise ActionError("mode_unsupported", "WhatsApp has no drafts. Use approve mode to send, or reply yourself.", 422)
    mode = _mode(hub_dir, case["channel_id"])
    if mode != "draft":
        raise ActionError("write_mode_" + mode, f"Replies on {case['channel_id']} are in {mode} mode, not draft.", 403)
    reply = _current_reply(hub_dir, case, reply_revision, digest)
    item = start("customer_desk_case", key=f"draft:{case['id']}:{reply['revision']}", route="draft",
                 input={"action": "draft", "case_id": case["id"], "reply_revision": reply["revision"],
                        "digest": reply["digest"]}, requester=actor.email, **_origin(case, actor))
    with store.tx(hub_dir) as conn:
        store.upsert_send(conn, case["id"], reply["revision"], "draft", synthetic=case["synthetic"],
                          work_item_id=item["id"], status="saving", requested_by=actor.email)
        store.audit(conn, actor.email, "draft_request", case["id"], {"reply": reply["revision"], "item": item["id"]})
    return {"case": case["number"], "reply": reply["revision"], "work_item_id": item["id"], "state": "saving_draft"}


# -- reruns and bindings -----------------------------------------------------------------------

def rerun(hub_dir: Path, ref: str, actor: Actor, *, instruction: str | None, start, reason: str = "rerun",
          stale=None) -> dict:
    require(actor, "desk_operator", "desk_delivery", "desk_complaints", "desk_exceptions", "desk_bindings")
    case = _case(hub_dir, ref)
    if case["state"] in ("binding_required",) and reason != "bound":
        raise ActionError("binding_required", "Bind the sender before the desk reads anything.")
    if case["state"] in ("sending", "ambiguous"):
        raise ActionError("state_conflict", f"{case['number']} is {case['state']}. Reconcile it first.")
    if instruction and len(instruction) > 2000:
        raise ActionError("validation_failed", "Keep the instruction under 2,000 characters.", 422)
    with store.tx(hub_dir) as conn:
        n = store.next_resolution(conn, case["id"])
        for r in store.replies(conn, case["id"]):
            if r["state"] in ("ready", "requested", "mailbox_draft_saved", "helpdesk_draft_saved"):
                store.set_reply_state(conn, case["id"], r["revision"], "superseded")
        store.update_case(conn, case["id"], state="triaging")
        store.audit(conn, actor.email, f"case_{reason}", case["id"], {"stale": stale or []})
    nonce = hashlib.sha256(f"{case['id']}:{n}:{reason}:{instruction or ''}".encode()).hexdigest()[:12]
    item = start("customer_desk_intake", key=f"rerun:{case['id']}:{n}:{nonce}", route="triage",
                 input={"kind": "rerun", "case_id": case["id"], "instruction": instruction, "reason": reason},
                 requester=actor.email)
    return {"case": case["number"], "state": "triaging", "work_item_id": item["id"], "resolution": n}


def _customer(hub_dir: Path, customer_id: str) -> dict:
    cfg = erp_config.load(hub_dir)
    erp = erp_config.backend(hub_dir, cfg)
    try:
        return erp.get_record("customers", customer_id, ERPContext(hub_id=Path(hub_dir).name.lower(),
                                                                   company=cfg.company))
    except ERPError as exc:
        raise ActionError("binding_conflict", f"ERPNext has no customer {customer_id} for this company "
                          f"({exc.code}).", 422) from None


def bind_case(hub_dir: Path, ref: str, actor: Actor, customer_id: str, *, start) -> dict:
    """Bind an unknown sender to one ERP customer, then let the desk read."""
    require(actor, "desk_bindings")
    case = _case(hub_dir, ref)
    if case["state"] != "binding_required":
        raise ActionError("state_conflict", f"{case['number']} is not waiting for a binding.")
    if not case["sender_key"]:
        raise ActionError("binding_invalid", "This case has no sender address to bind.", 422)
    cust = _customer(hub_dir, customer_id)
    if cust["fields"].get("disabled"):
        raise ActionError("binding_conflict", f"Customer {customer_id} is disabled in ERPNext.", 422)
    values = config.settings(hub_dir)
    with store.tx(hub_dir) as conn:
        b = bindings_lib.add(conn, company=values["DESK_COMPANY"], channel_kind=case["sender_kind"],
                             sender=case["sender_key"], customer_id=customer_id, actor=actor.email,
                             source_ref=f"case:{case['number']}", synthetic=bool(case["synthetic"]))
        store.update_case(conn, case["id"], binding_id=b["id"], customer_id=customer_id, candidates=[],
                          state="received", queue=None)
    item = start("customer_desk_intake", key=f"bound:{case['id']}:{b['id']}", route="triage",
                 input={"kind": "bound", "case_id": case["id"]}, requester=actor.email)
    return {"case": case["number"], "binding": b["id"], "customer": customer_id, "state": "triaging",
            "work_item_id": item["id"]}


def bind_sender(hub_dir: Path, actor: Actor, *, channel_kind: str, sender: str, customer_id: str,
                synthetic: bool = False) -> dict:
    require(actor, "desk_bindings")
    cust = _customer(hub_dir, customer_id)
    if cust["fields"].get("disabled"):
        raise ActionError("binding_conflict", f"Customer {customer_id} is disabled in ERPNext.", 422)
    values = config.settings(hub_dir)
    try:
        with store.tx(hub_dir) as conn:
            b = bindings_lib.add(conn, company=values["DESK_COMPANY"], channel_kind=channel_kind, sender=sender,
                                 customer_id=customer_id, actor=actor.email, synthetic=synthetic)
    except bindings_lib.BindingError as exc:
        raise ActionError(exc.code, exc.message, 422) from None
    return {"binding": b["id"], "sender": b["sender_key"], "customer": customer_id}


def revoke_binding(hub_dir: Path, actor: Actor, binding_id: str) -> dict:
    require(actor, "desk_bindings")
    with store.tx(hub_dir) as conn:
        try:
            b = bindings_lib.revoke(conn, binding_id, actor=actor.email)
        except bindings_lib.BindingError as exc:
            raise ActionError(exc.code, exc.message, 404) from None
        affected = store.rows(conn.execute("SELECT * FROM cases WHERE binding_id=? AND state NOT IN "
                                           "('resolved','cancelled','failed','sent')", (b["id"],)))
        for c in affected:
            for r in store.replies(conn, c["id"]):
                if r["state"] in ("ready", "requested", "mailbox_draft_saved", "helpdesk_draft_saved"):
                    store.set_reply_state(conn, c["id"], r["revision"], "superseded")
            store.update_case(conn, c["id"], state="binding_required", binding_id=None, customer_id=None,
                              queue="bindings", claimed_by=None, note="The sender's binding was revoked.")
    return {"binding": b["id"], "state": b["state"], "cases_back_to_binding": [c["number"] for c in affected]}


# -- owner decisions ---------------------------------------------------------------------------

def decide_exception(hub_dir: Path, decision_id: str, actor: Actor, *, approve: bool, note: str, start) -> dict:
    require(actor, "desk_exceptions")
    if not (note or "").strip():
        raise ActionError("validation_failed", "A decision needs a note saying why.", 422)
    with store.tx(hub_dir) as conn:
        try:
            d = store.decide(conn, decision_id, state="approved" if approve else "declined", note=note.strip(),
                             by=actor.email)
        except store.Conflict as exc:
            raise ActionError(exc.code, exc.message) from None
        case = store.get_case(conn, d["case_id"])
        store.audit(conn, actor.email, "exception_decided", case["id"], {"decision": d["id"], "state": d["state"]})
    out = rerun(hub_dir, case["number"], actor, instruction=None, start=start, reason="decision")
    return {"decision": d["id"], "state": d["state"], "case": case["number"], "rerun": out["work_item_id"]}


def verify_delivery(hub_dir: Path, proposal_id: str, actor: Actor, *, start) -> dict:
    """The delivery team says the date is changed in ERPNext. Reread the order:
    only a matching date produces a confirmation draft."""
    require(actor, "desk_delivery")
    conn = store.connect(hub_dir)
    p = store.get_proposal(conn, proposal_id)
    if p is None:
        raise ActionError("not_found", "No such delivery proposal.", 404)
    if p["state"] != "proposed":
        raise ActionError("state_conflict", f"The proposal is already {p['state']}.")
    case = store.get_case(conn, p["case_id"])
    cfg = erp_config.load(hub_dir)
    erp = erp_config.backend(hub_dir, cfg)
    try:
        order = erp.get_record("sales_orders", p["sales_order"], ERPContext(
            hub_id=Path(hub_dir).name.lower(), company=cfg.company, party_scope=case["customer_id"]))
    except ERPError as exc:
        raise ActionError(exc.code, f"ERPNext could not be read: {exc.message}", 503) from None
    now = order["fields"].get("delivery_date")
    if now != p["requested_date"]:
        raise ActionError("erp_mismatch", f"ERPNext still shows {facts_lib.display('delivery_date', now)} for "
                          f"{p['sales_order']}, not {facts_lib.display('delivery_date', p['requested_date'])}. Nothing "
                          "was drafted.", observed=now)
    with store.tx(hub_dir) as tconn:
        p = store.update_proposal(tconn, p["id"], expect_states=("proposed",), state="verified", decided_by=actor.email,
                                  verified={"delivery_date": now, "observed_at": order["observed_at"],
                                            "modified_at": order.get("modified_at")})
        for t in store.case_tickets(tconn, case["id"]):
            if t["owner_role"] == "delivery" and t["state"] in ("open", "in_progress"):
                store.update_ticket(tconn, t["id"], state="resolved")
                store.add_ticket_note(tconn, t["id"], actor.email, "Delivery date verified in ERPNext.")
    out = rerun(hub_dir, case["number"], actor, instruction=None, start=start, reason="delivery_verified")
    return {"proposal": p["id"], "state": "verified", "delivery_date": now, "case": case["number"],
            "rerun": out["work_item_id"]}


def decline_delivery(hub_dir: Path, proposal_id: str, actor: Actor, *, note: str, start) -> dict:
    require(actor, "desk_delivery")
    if not (note or "").strip():
        raise ActionError("validation_failed", "Declining needs a note for the customer reply.", 422)
    with store.tx(hub_dir) as conn:
        try:
            p = store.update_proposal(conn, proposal_id, expect_states=("proposed",), state="declined",
                                      decided_by=actor.email, note=note.strip())
        except store.Conflict as exc:
            raise ActionError(exc.code, exc.message) from None
        case = store.get_case(conn, p["case_id"])
    out = rerun(hub_dir, case["number"], actor, instruction=None, start=start, reason="delivery_declined")
    return {"proposal": p["id"], "state": "declined", "case": case["number"], "rerun": out["work_item_id"]}


def update_ticket(hub_dir: Path, ticket_ref: str, actor: Actor, *, state: str | None = None,
                  assignee: str | None = None, note: str | None = None, start=None) -> dict:
    conn = store.connect(hub_dir)
    t = store.get_ticket(conn, ticket_ref)
    if t is None:
        raise ActionError("not_found", f"No ticket {ticket_ref}.", 404)
    require(actor, "desk_delivery" if t["owner_role"] == "delivery" else "desk_complaints")
    if state and state not in ("open", "in_progress", "resolved", "cancelled"):
        raise ActionError("validation_failed", "state is open, in_progress, resolved or cancelled.", 422)
    with store.tx(hub_dir) as tconn:
        fields = {}
        if state:
            fields["state"] = state
        if assignee is not None:
            fields["assignee"] = assignee or None
        if fields:
            t = store.update_ticket(tconn, t["id"], **fields)
        if note:
            store.add_ticket_note(tconn, t["id"], actor.email, note.strip()[:4000])
        store.audit(tconn, actor.email, "ticket_update", t["id"], {"state": state})
        case = store.get_case(tconn, t["case_id"])
        open_items = [x for x in store.case_tickets(tconn, case["id"]) if x["state"] in ("open", "in_progress")]
        open_items += [p for p in store.case_proposals(tconn, case["id"]) if p["state"] == "proposed"]
        if not open_items and case["state"] == "open_items":
            store.update_case(tconn, case["id"], state="needs_owner", note="Every item is settled. A follow-up may be due.")
    return {"ticket": t["number"], "state": t["state"], "assignee": t["assignee"], "case": case["number"]}


def share_plan(hub_dir: Path, ref: str, actor: Actor, plan: str) -> dict:
    require(actor, "desk_operator", "desk_complaints")
    case = _case(hub_dir, ref)
    if not (plan or "").strip():
        raise ActionError("validation_failed", "The plan is empty.", 422)
    digest = "sha256:" + hashlib.sha256(plan.encode()).hexdigest()
    with store.tx(hub_dir) as conn:
        v = (conn.execute("SELECT COALESCE(MAX(version),0) AS n FROM plans WHERE case_id=?", (case["id"],))
             .fetchone()["n"]) + 1
        conn.execute("UPDATE plans SET state='superseded' WHERE case_id=? AND state='pending'", (case["id"],))
        conn.execute("INSERT INTO plans(case_id, version, body, digest, state, author, created) VALUES "
                     "(?,?,?,?,'pending',?,?)", (case["id"], v, plan.strip(), digest, actor.email, time.time()))
        store.update_case(conn, case["id"], state="waiting_plan")
    return {"case": case["number"], "plan_version": v, "digest": digest, "state": "waiting_plan"}


def review_plan(hub_dir: Path, ref: str, actor: Actor, *, approve: bool, note: str) -> dict:
    """The complaint team reviews an escalation plan. Approving a plan never approves a send."""
    require(actor, "desk_complaints")
    case = _case(hub_dir, ref)
    with store.tx(hub_dir) as conn:
        plan = conn.execute("SELECT * FROM plans WHERE case_id=? AND state='pending' ORDER BY version DESC LIMIT 1",
                            (case["id"],)).fetchone()
        if plan is None:
            raise ActionError("not_found", f"{case['number']} has no plan waiting for review.", 404)
        conn.execute("UPDATE plans SET state=?, reviewer=?, note=?, reviewed=? WHERE case_id=? AND version=?",
                     ("approved" if approve else "changes_requested", actor.email, note, time.time(), case["id"],
                      plan["version"]))
        store.update_case(conn, case["id"], state="in_review" if case["claimed_by"] else "needs_owner")
    return {"case": case["number"], "plan_version": plan["version"], "state": "approved" if approve else
            "changes_requested", "note": "Approving a plan never approves a send."}


def set_state(hub_dir: Path, ref: str, actor: Actor, *, to: str, reason: str) -> dict:
    """resolve, reopen or cancel."""
    require(actor, "desk_operator")
    case = _case(hub_dir, ref)
    if to not in ("resolved", "cancelled", "needs_owner"):
        raise ActionError("validation_failed", "to is resolved, cancelled or needs_owner (reopen).", 422)
    if case["state"] in ("sending", "ambiguous", "waiting_approval") and to != "needs_owner":
        raise ActionError("state_conflict", f"{case['number']} is {case['state']}. Settle the reply first.")
    with store.tx(hub_dir) as conn:
        fields = {"state": to, "note": reason[:500] if reason else None}
        if to == "resolved":
            fields["resolved_at"] = config.now_iso(hub_dir)
        if to == "needs_owner" and case["state"] == "resolved":
            fields["reopen_count"] = case["reopen_count"] + 1
            fields["resolved_at"] = None
        c = store.update_case(conn, case["id"], **fields)
        store.audit(conn, actor.email, f"case_{to}", case["id"], {"reason": reason})
    return {"case": c["number"], "state": c["state"]}


def open_internal(hub_dir: Path, actor: Actor, *, customer_id: str, text: str, surface: str = "chat",
                  start, source_ref: str | None = None) -> dict:
    """A teammate opens a case for a named customer: a phone call, a walk in, a Slack thread."""
    require(actor, "desk_operator")
    cust = _customer(hub_dir, customer_id)
    if cust["fields"].get("disabled"):
        raise ActionError("binding_conflict", f"Customer {customer_id} is disabled in ERPNext.", 422)
    ref = source_ref or hashlib.sha256(f"{actor.email}:{customer_id}:{text}:{time.time()}".encode()).hexdigest()[:16]
    env = envelopes.internal(surface=surface, customer_id=customer_id, text=text, opened_by=actor.email, source_ref=ref)
    try:
        opened = cases.intake(hub_dir, env)
    except cases.IntakeError as exc:
        raise ActionError(exc.code, exc.message, 422) from None
    item = start("customer_desk_intake", key=f"internal:{opened['case_id']}:{opened['seq']}", route="triage",
                 input={"kind": "case", "case_id": opened["case_id"], "seq": opened["seq"]}, requester=actor.email)
    return {"case": opened["number"], "state": "triaging", "work_item_id": item["id"]}


def preview(hub_dir: Path, actor: Actor, *, customer_id: str, text: str, start) -> dict:
    """Prepare a reply to a pasted message for a named customer, in a separate
    preview namespace: it never shows in the queue, has no recipient and can
    never be sent or drafted anywhere."""
    require(actor, "desk_operator")
    cust = _customer(hub_dir, customer_id)
    if cust["fields"].get("disabled"):
        raise ActionError("binding_conflict", f"Customer {customer_id} is disabled in ERPNext.", 422)
    ref = hashlib.sha256(f"preview:{actor.email}:{customer_id}:{text}:{time.time()}".encode()).hexdigest()[:16]
    env = envelopes.internal(surface="chat", customer_id=customer_id, text=text, opened_by=actor.email, source_ref=ref)
    env["preview"] = True
    opened = cases.intake(hub_dir, env)
    item = start("customer_desk_intake", key=f"preview:{opened['case_id']}", route="triage",
                 input={"kind": "case", "case_id": opened["case_id"], "seq": opened["seq"]}, requester=actor.email)
    return {"preview": opened["number"], "case_id": opened["case_id"], "work_item_id": item["id"]}


def preview_result(hub_dir: Path, case_id: str) -> dict:
    from . import policy as policy_lib, views

    view = views.case(hub_dir, case_id)
    cv = views.compact(view)
    values = config.settings(hub_dir)
    gaps = policy_lib.gaps(policy_lib.load(hub_dir, values["DESK_POLICY_FILE"]))
    return {"state": cv["state"], "requests": cv["requests"], "classification": cv["classification"],
            "facts": cv["facts"], "reply": cv["reply"], "policy_gaps": gaps,
            "note": "Preview only. No case in the queue, no draft and no send."}
