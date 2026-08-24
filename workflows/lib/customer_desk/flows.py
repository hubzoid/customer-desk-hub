"""The bodies of the desk's work items, bound to Hubzoid.

* `triage_item` runs unattended for every incoming message (sample channels,
  Hubzoid email and WhatsApp channels, helpdesk tickets) and for reruns a
  person asks for. It ends at a case ready for a person. It never parks for
  an approval and never sends.
* `case_item` runs attended, as the person who asked: it saves a real draft
  or sends the exact reply after that person approves it on the Work items
  page.
"""
from __future__ import annotations

import os
from pathlib import Path

from . import cases, config, envelopes, pipeline, recheck, replies, store, views

SCRIPTED_ENV = "DESK_SCRIPTED_STATIONS"
RETRY_HINT = ("Your answer did not match the required JSON. Return exactly one JSON object with the fields your "
              "schema lists, and nothing else.")


def scripted() -> bool:
    return os.environ.get(SCRIPTED_ENV, "").strip().lower() in ("1", "true", "yes")


class HubRunner(pipeline.Runner):
    """Stages are work item checkpoints and stations are `hub.call_agent`."""

    def __init__(self, hub_dir: Path):
        from hubzoid import hub

        self.hub_dir = hub_dir
        self.item_id = hub.work_item.id
        self._scripted = None
        self.label = "scripted" if scripted() else None
        if scripted():
            from .scripted import ScriptedStations

            self._scripted = ScriptedStations(lambda: pipeline.load(hub_dir))

    def checkpoint(self, stage, fn):
        from hubzoid import hub

        return hub.work_item.checkpoint(stage, fn)

    def station(self, agent, *, stage, revision, message):
        if self._scripted is not None:
            from hubzoid import hub

            return hub.work_item.checkpoint(f"scripted-{stage}-{revision}",
                                            lambda: self._scripted(agent, stage=stage, revision=revision,
                                                                   message=message))
        from hubzoid import hub
        from hubzoid.stations import StationError, StationOutputError

        try:
            return hub.call_agent(message, agent=agent, stage=stage, revision=revision)
        except StationOutputError as exc:
            try:
                return hub.retry_station(exc.call_id, RETRY_HINT)
            except (StationOutputError, StationError) as again:
                raise pipeline.StationFailed(agent, getattr(again, "code", "station_failed"), str(again)) from None
        except StationError as exc:
            code = getattr(exc, "code", "station_failed")
            text = str(exc)
            if "login" in text.lower() or "auth" in text.lower() or "credential" in text.lower():
                code = "model_auth_required"
            raise pipeline.StationFailed(agent, code, text) from None


def start_work(hub_dir: Path):
    """The `start` function actions use: Hubzoid work items, as the person."""

    def start(workflow: str, *, key: str, route: str, input: dict, requester: str) -> dict:
        from hubzoid.work_items import service as wi

        origin = {"surface": "desk", "requested_by": requester, "acts_as": requester}
        item, _ = wi.admit_and_start(hub_dir, workflow=workflow, key=key, route=route, input=input,
                                     requester=requester, origin=origin)
        return item

    return start


# -- triage ---------------------------------------------------------------------------------

def triage_item(inp: dict | None = None) -> dict:
    from hubzoid import hub

    hub_dir = _hub_dir()
    values = config.settings(hub_dir)
    inp = inp if inp is not None else (hub.work_item.input or {})
    kind = inp.get("kind") or ("intake" if inp.get("intake_id") else "unknown")
    if kind in ("envelope", "intake", "helpdesk") and not values["DESK_INTAKE_ENABLED"]:
        return {"state": "intake_paused", "message": "DESK_INTAKE_ENABLED is false. The message waits in intake."}
    trigger = kind
    instruction = None
    if kind == "envelope":
        env = envelopes.from_envelope(inp["envelope"])
        opened = hub.work_item.checkpoint("intake", lambda: cases.intake(hub_dir, env))
    elif kind == "intake":
        if inp.get("channel") not in values["DESK_EXTERNAL_CHANNELS"]:
            return {"state": "ignored", "message": f"Channel {inp.get('channel')} is not in DESK_EXTERNAL_CHANNELS."}
        env = envelopes.from_intake_item(inp)
        opened = hub.work_item.checkpoint("intake", lambda: cases.intake(hub_dir, env))
    elif kind == "helpdesk":
        opened = helpdesk_intake(hub_dir, values, str(inp["ticket_id"]))
        if opened is None:
            return {"state": "no_new_message", "ticket_id": inp["ticket_id"]}
    elif kind == "transcript":
        from . import transcripts

        runner = HubRunner(hub_dir)
        opened_all = transcripts.split(hub_dir, inp, runner)
        start = start_work(hub_dir)
        started = []
        for o in opened_all:
            if o["action"] == "duplicate":
                continue
            item = hub.work_item.checkpoint(f"transcript-start-{o['case_id'][:8]}", lambda o=o: start(
                "customer_desk_intake", key=f"internal:{o['case_id']}:{o['seq']}", route="triage",
                input={"kind": "case", "case_id": o["case_id"], "seq": o["seq"]}, requester=inp["opened_by"]))
            started.append({"case": o["number"], "work_item": item["id"]})
        return {"state": "split", "cases": started}
    elif kind in ("rerun", "bound", "case", "decision"):
        opened = {"case_id": inp["case_id"], "seq": inp.get("seq")}
        trigger = inp.get("reason") or kind
        instruction = inp.get("instruction")
    else:
        return {"state": "ignored", "message": f"Unknown input kind {kind!r}."}
    if opened.get("action") == "duplicate":
        return {"state": "duplicate", "case": opened["number"]}
    try:
        result = pipeline.triage(hub_dir, opened["case_id"], HubRunner(hub_dir), trigger=trigger,
                                 instruction=instruction)
    except pipeline.StationFailed as exc:
        def fail():
            with store.tx(hub_dir) as conn:
                store.update_case(conn, opened["case_id"], state="triaging",
                                  note=f"{exc.code}: the {exc.agent} station could not run. Deterministic setup is "
                                       "complete. Fix model access, then rerun.")
            return {"state": "triaging", "error": exc.code}
        return hub.work_item.checkpoint("station-failed", fail)
    publish_case_page(hub_dir, opened["case_id"])
    case = store.get_case(store.connect(hub_dir), opened["case_id"])
    if case["surface"] == "helpdesk" and values["DESK_HELPDESK"] == "zoho_desk":
        result["helpdesk"] = helpdesk_writeback(hub_dir, values, case)
    return result


def _hub_dir() -> Path:
    from hubzoid.workflows.context import _ctx

    return Path(_ctx().hub_dir)


def publish_case_page(hub_dir: Path, case_id: str) -> dict | None:
    """The case as one page in Hubzoid's artifact viewer, one link per case
    that always shows the newest revision."""
    from hubzoid import hub

    from . import casepage

    view = views.case(hub_dir, case_id)
    if view is None:
        return None
    path = Path(hub.run_dir) / f"case-{view['case']['number']}.html"
    path.write_text(casepage.render(view))
    digest = casepage.digest(view)
    try:
        page = hub.publish_artifact(str(path), title=f"Case {view['case']['number']}",
                                    key=f"case-{view['case']['number'].lower()}", digest=digest, audience="hub")
    except Exception as exc:  # noqa: BLE001 - the page is a view; the case itself is saved
        return {"error": type(exc).__name__}
    url = (page or {}).get("latest_url") or (page or {}).get("url")
    if url:
        with store.tx(hub_dir) as conn:
            conn.execute("UPDATE cases SET page_url=? WHERE id=?", (url, case_id))
    return page


# -- the helpdesk ----------------------------------------------------------------------------

def helpdesk_intake(hub_dir: Path, values: dict, ticket_id: str) -> dict | None:
    """Reread the ticket. The webhook body is never trusted."""
    from hubzoid import hub

    from .helpdesk import desk

    def read():
        reader, _ = desk.readers(hub_dir, values)
        got = desk.read_ticket(reader, ticket_id)
        if got["inbound"] is None:
            return None
        dept = values.get("ZOHO_DESK_DEPARTMENT_ID") or ""
        if dept and str(got["ticket"].get("departmentId")) != dept:
            return None
        if not desk.claim_message(hub_dir, got["ticket"], str(got["inbound"]["id"])):
            return None
        env = envelopes.from_helpdesk(got["ticket"], got["inbound"],
                                      synthetic=config.namespace(values) == "sample")
        opened = cases.intake(hub_dir, env)
        desk.link_case(hub_dir, ticket_id, opened["case_id"])
        return opened

    return hub.work_item.checkpoint("helpdesk-intake", read)


def helpdesk_writeback(hub_dir: Path, values: dict, case: dict) -> dict:
    """Tags, a private note, the case field and an unsent draft, each a
    recorded operation, in the helpdesk mode in force at the moment of writing."""
    from hubzoid import hub
    from hubzoid.work_items import NotSent, OperationFailed, Reconciled, Rejected, WorkItemError

    from .helpdesk import desk, zoho

    mode = config.settings(hub_dir)["DESK_HELPDESK_MODE"]
    view = views.case(hub_dir, case["id"])
    loaded = pipeline.load(hub_dir)
    ticket_id = case["helpdesk_ticket_id"]
    rev = case["current_resolution"] or 0
    reply = view.get("reply")
    mark = zoho.marker(ticket_id, f"{case['id']}:{reply['revision'] if reply else 0}")
    tags = desk.tags_for(view, values, loaded.kinds)
    note = desk.note_for(view, mark)
    out = {"mode": mode, "ticket_id": ticket_id}
    if mode == "dry-run":
        def preview():
            for kind, req in (("tags", {"tags": tags}), ("note", {"content": note}),
                              ("draft", {"body": reply["rendered"] if reply else None})):
                desk.record(hub_dir, kind=kind, mode=mode, ticket_id=ticket_id, case_id=case["id"],
                            idem=f"dry-run:{kind}:{ticket_id}:{case['id']}:{rev}", request=req, status="dry-run")
            return {"tags": tags, "note": "previewed", "draft": "previewed"}
        out.update(hub.work_item.checkpoint(f"helpdesk-preview-r{rev}", preview))
        return out
    reader, writer = desk.readers(hub_dir, values)

    def tags_dispatch(args):
        try:
            return {"tags": writer.associate_tags(ticket_id, args["tags"])}
        except (zoho.WriteRefused, zoho.WritesBlocked) as exc:
            raise NotSent(str(exc)) from None
        except zoho.ZohoError as exc:
            if 400 <= exc.status < 500:
                raise Rejected(exc.message) from None
            raise

    def tags_reconcile(args):
        present = set(reader.tags(ticket_id))
        return Reconciled("applied", {"tags": sorted(present)}) if set(args["tags"]) <= present else \
            Reconciled("safe_to_retry")

    prefix = writer.policy.effective_prefix
    shown = sorted({t.replace(values["ZOHO_DESK_TAG_PREFIX"], prefix, 1) for t in tags})
    try:
        hub.operation.run(name="helpdesk_tags", target={"ticket": ticket_id}, arguments={"tags": shown},
                          recovery="reconcile", reconcile=tags_reconcile, actions="helpdesk.annotate",
                          dispatch=tags_dispatch, key=f"r{rev}")
        out["tags"] = shown
        desk.record(hub_dir, kind="tags", mode=mode, ticket_id=ticket_id, case_id=case["id"],
                    idem=f"{mode}:tags:{ticket_id}:{case['id']}:{rev}", request={"tags": shown}, status="written")
    except (OperationFailed, WorkItemError) as exc:
        out["tags_error"] = getattr(exc, "message", str(exc))
    if mode != "live":
        desk.record(hub_dir, kind="note", mode=mode, ticket_id=ticket_id, case_id=case["id"],
                    idem=f"{mode}:note:{ticket_id}:{case['id']}:{rev}", request={"content": note}, status="previewed")
        out["note"] = out["draft"] = "previewed (shadow mode)"
        return out

    def note_dispatch(args):
        try:
            return writer.private_note(ticket_id, args["content"])
        except (zoho.WriteRefused, zoho.WritesBlocked) as exc:
            raise NotSent(str(exc)) from None

    def note_reconcile(args):
        for c in reader.comments(ticket_id):
            if mark in (c.get("content") or ""):
                return Reconciled("applied", {"id": c.get("id")})
        return Reconciled("safe_to_retry")

    try:
        hub.operation.run(name="helpdesk_note", target={"ticket": ticket_id}, arguments={"content": note},
                          recovery="reconcile", reconcile=note_reconcile, actions="helpdesk.annotate",
                          dispatch=note_dispatch, key=f"r{rev}")
        out["note"] = "written"
        desk.record(hub_dir, kind="note", mode=mode, ticket_id=ticket_id, case_id=case["id"],
                    idem=f"live:note:{ticket_id}:{case['id']}:{rev}", request={"content": note}, status="written")
    except (OperationFailed, WorkItemError) as exc:
        out["note_error"] = getattr(exc, "message", str(exc))
    if writer.policy.case_field:
        try:
            hub.operation.run(name="helpdesk_case_field", target={"ticket": ticket_id},
                              arguments={"case": case["number"]}, recovery="idempotent", actions="helpdesk.annotate",
                              dispatch=lambda a: writer.set_case_field(ticket_id, a["case"]), key=f"r{rev}")
            out["case_field"] = case["number"]
        except (OperationFailed, WorkItemError) as exc:
            out["case_field_error"] = getattr(exc, "message", str(exc))
    if reply and (reply.get("checks") or {}).get("passed") and case["state"] == "needs_owner":
        out["draft"] = helpdesk_draft(hub_dir, values, case, reply)
    else:
        out["draft"] = "not written: the reply needs a person first"
    return out


def helpdesk_draft(hub_dir: Path, values: dict, case: dict, reply: dict) -> str:
    from hubzoid import hub
    from hubzoid.work_items import OperationFailed, WorkItemError

    pl = replies.payload(hub_dir, case, reply)
    try:
        result = hub.operation.run(name="customer_reply", target={"case": case["number"], "reply": reply["revision"]},
                                   arguments=pl, recovery="reconcile",
                                   reconcile=replies.zoho_reconcile(hub_dir, values, case, reply),
                                   actions="customer_reply.send", channel="zoho_desk",
                                   dispatch=replies.refuse_helpdesk_send,
                                   draft=replies.zoho_draft(hub_dir, values, case, reply))
    except WorkItemError as exc:
        return f"not written: {exc.message}"
    except OperationFailed as exc:
        return f"not written: {exc}"

    def settle():
        with store.tx(hub_dir) as conn:
            store.upsert_send(conn, case["id"], reply["revision"], "draft", synthetic=case["synthetic"],
                              provider_draft_id=result.get("provider_draft_id"), status="draft_saved",
                              receipt=result, requested_by="desk")
            store.set_reply_state(conn, case["id"], reply["revision"], "helpdesk_draft_saved")
            store.update_case(conn, case["id"], state="helpdesk_draft_saved")
        return result

    hub.work_item.checkpoint(f"helpdesk-draft-r{reply['revision']}", settle)
    return f"unsent draft {result.get('provider_draft_id')}"


# -- the attended send or draft ----------------------------------------------------------------

def case_item() -> dict:
    from hubzoid import hub
    from hubzoid.work_items import OperationFailed, Rejected

    hub_dir = _hub_dir()
    values = config.settings(hub_dir)
    inp = hub.work_item.input
    action = inp["action"]
    requester = hub.work_item.requester
    conn = store.connect(hub_dir)
    case = store.get_case(conn, inp["case_id"])
    reply = store.get_reply(conn, case["id"], int(inp["reply_revision"]))
    if reply is None or reply["digest"] != inp["digest"]:
        return {"state": "reply_stale", "message": "The reply changed after the request. Nothing was sent."}
    if action == "send" and reply["state"] != "requested":
        return {"state": "reply_stale", "message": f"Reply {reply['revision']} is {reply['state']}. Nothing was sent."}
    loaded = pipeline.load(hub_dir)
    stale = hub.work_item.checkpoint("recheck", lambda: recheck.changed_facts(hub_dir, case, store.get_facts(
        store.connect(hub_dir), case["id"], reply["resolution"]), policy=loaded.policy))
    if stale:
        return _stale(hub_dir, case, reply, requester, stale)
    pl = replies.payload(hub_dir, case, reply)
    channel = case["channel_id"]
    version = replies.target_version(hub_dir, case["id"], reply["revision"],
                                     lambda: recheck.facts_state(hub_dir, case, reply["resolution"], policy=loaded.policy))

    def dispatch(args):
        fresh = store.get_case(store.connect(hub_dir), case["id"])
        if fresh["current_reply"] != reply["revision"]:
            raise Rejected("reply_stale: a newer reply or customer message replaced this one.")
        if recheck.changed_facts(hub_dir, fresh, store.get_facts(store.connect(hub_dir), case["id"], reply["resolution"]),
                                 policy=loaded.policy):
            raise Rejected("reply_stale: ERPNext changed after approval.")
        if channel == "sample-whatsapp" and not replies.whatsapp_window_open(hub_dir, fresh):
            raise Rejected("window_closed: WhatsApp allows a free-form reply only within 24 hours of the "
                           "customer's last message.")
        _mark(hub_dir, case, reply, "sending")
        fault = os.environ.get("DESK_SAMPLE_FAULT", "")
        if fault == "fail_before_write" and not _fault_used(hub_dir, "before"):
            raise TimeoutError("injected: the outbox did not answer")
        result = replies._sample_write(hub_dir, args, "send", requester)
        if fault in ("lose_receipt", "ambiguous") and not _fault_used(hub_dir, "after"):
            raise TimeoutError("injected: the outbox accepted it, then the connection dropped")
        return result

    def draft(args):
        return replies._sample_write(hub_dir, args, "draft", requester)

    def reconcile(args):
        from hubzoid.work_items import Reconciled

        if os.environ.get("DESK_SAMPLE_FAULT") == "ambiguous":
            return Reconciled("unknown")
        return replies.sample_reconcile(hub_dir, "draft" if action == "draft" else "send")(args)

    if channel in replies.SAMPLE_CHANNELS:
        kwargs = dict(dispatch=dispatch, draft=None if channel in replies.NO_DRAFT else draft, reconcile=reconcile)
    elif channel == "zoho_desk":
        kwargs = dict(dispatch=replies.refuse_helpdesk_send, draft=replies.zoho_draft(hub_dir, values, case, reply),
                      reconcile=replies.zoho_reconcile(hub_dir, values, case, reply))
    else:
        return channel_send(hub_dir, case, reply, requester)
    try:
        result = hub.operation.run(name="customer_reply", target={"case": case["number"], "reply": reply["revision"]},
                                   arguments=pl, recovery="reconcile", actions="customer_reply.send", channel=channel,
                                   target_version=version, **kwargs)
    except OperationFailed as exc:
        return hub.work_item.checkpoint("settle-failed", lambda: _failed(hub_dir, case, reply, action, exc, requester))
    return hub.work_item.checkpoint("settle", lambda: _settled(hub_dir, case, reply, action, result, requester))


def _fault_used(hub_dir: Path, which: str) -> bool:
    flag = store.db_path(hub_dir).parent / f"fault-{which}.used"
    if flag.exists():
        return True
    flag.write_text("1")
    return False


def _mark(hub_dir, case, reply, state):
    with store.tx(hub_dir) as conn:
        store.update_case(conn, case["id"], state=state)


def _stale(hub_dir, case, reply, requester, stale):
    from hubzoid import hub

    def go():
        with store.tx(hub_dir) as conn:
            store.set_reply_state(conn, case["id"], reply["revision"], "superseded")
            store.upsert_send(conn, case["id"], reply["revision"], "approve", synthetic=case["synthetic"],
                              status="reply_stale", receipt={"stale": stale})
        return {"state": "reply_stale", "stale": stale}

    out = hub.work_item.checkpoint("stale", go)
    from . import actions

    actor = actions.Actor(requester, lambda role: True)
    try:
        actions.rerun(hub_dir, case["number"], actor, instruction=None, start=start_work(hub_dir), reason="facts_changed",
                      stale=stale)
    except actions.ActionError:
        pass
    return out


def _settled(hub_dir, case, reply, action, result, requester):
    with store.tx(hub_dir) as conn:
        c = store.get_case(conn, case["id"])
        if action == "draft":
            state = "helpdesk_draft_saved" if c["channel_id"] == "zoho_desk" else "mailbox_draft_saved"
            store.upsert_send(conn, case["id"], reply["revision"], "draft", synthetic=case["synthetic"],
                              provider_draft_id=result.get("provider_draft_id") or result.get("receipt_id"),
                              status="draft_saved", receipt=result, requested_by=requester)
            store.set_reply_state(conn, case["id"], reply["revision"], state)
            store.update_case(conn, case["id"], state=state)
            return {"state": state, "receipt": result}
        store.upsert_send(conn, case["id"], reply["revision"], "approve", synthetic=case["synthetic"],
                          outbox_id=result.get("receipt_id"), status="sent", receipt=result, requested_by=requester)
        store.set_reply_state(conn, case["id"], reply["revision"], "sent")
        open_items = [t for t in store.case_tickets(conn, case["id"]) if t["state"] in ("open", "in_progress")]
        open_items += [p for p in store.case_proposals(conn, case["id"]) if p["state"] == "proposed"]
        open_items += [d for d in store.case_decisions(conn, case["id"]) if d["state"] == "pending"]
        res = store.get_resolution(conn, case["id"], reply["resolution"])
        asked = any(o["outcome"] in ("clarify", "candidates") for o in res["requests"])
        state = "waiting_customer" if asked else ("open_items" if open_items else "resolved")
        fields = {"state": state, "claimed_by": None}
        if not c["first_reply_accepted_at"]:
            fields["first_reply_accepted_at"] = result.get("accepted_at")
        if state == "resolved":
            fields["resolved_at"] = config.now_iso(hub_dir)
        store.update_case(conn, case["id"], **fields)
        store.audit(conn, requester, "reply_sent", case["id"], {"reply": reply["revision"],
                                                                "receipt": result.get("receipt_id")})
    return {"state": state, "receipt": result}


def _failed(hub_dir, case, reply, action, exc, requester):
    text = str(exc)
    code = getattr(exc, "code", "operation_failed")
    with store.tx(hub_dir) as conn:
        if "window_closed" in text:
            store.set_reply_state(conn, case["id"], reply["revision"], "held")
            store.update_case(conn, case["id"], state="held")
            status = "held"
        elif code == "approval_denied":
            store.set_reply_state(conn, case["id"], reply["revision"], "rejected")
            store.update_case(conn, case["id"], state="in_review")
            status = "rejected"
        elif "reply_stale" in text:
            store.set_reply_state(conn, case["id"], reply["revision"], "superseded")
            store.update_case(conn, case["id"], state="needs_owner", note="The reply went out of date before sending. "
                              "Nothing was sent. Review the new revision.")
            status = "reply_stale"
        else:
            store.update_case(conn, case["id"], state="in_review", note=f"{code}: {text[:300]}")
            status = code
        store.upsert_send(conn, case["id"], reply["revision"], "draft" if action == "draft" else "approve",
                          synthetic=case["synthetic"], status=status, receipt={"error": text[:500]},
                          requested_by=requester)
    return {"state": status, "message": text[:500]}


def channel_send(hub_dir: Path, case: dict, reply: dict, requester: str) -> dict:
    """A Hubzoid email or WhatsApp channel: the reply goes back on the case's
    stored origin thread through `hub.thread.post`, text only."""
    from hubzoid import hub
    from hubzoid.work_items import OperationFailed

    if reply["attachments"]:
        return {"state": "attachments_unsupported",
                "message": "Hubzoid channel replies carry text only. Save the reply as a draft, or send it with the "
                           "attachment from your own mailbox."}
    try:
        result = hub.thread.post(reply["rendered"], key=f"desk:{case['id']}:{reply['revision']}:send")
    except OperationFailed as exc:
        return hub.work_item.checkpoint("settle-failed", lambda: _failed(hub_dir, case, reply, "send", exc, requester))
    return hub.work_item.checkpoint("settle", lambda: _settled(hub_dir, case, reply, "send",
                                                               result if isinstance(result, dict) else {}, requester))
