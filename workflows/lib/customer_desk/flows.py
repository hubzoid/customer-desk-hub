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

import hashlib
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

            def scripted_call():
                delay = float(os.environ.get("DESK_SCRIPTED_DELAY") or 0)
                if delay and agent == "desk-resolver":
                    import time

                    time.sleep(delay)     # a test seam: room to kill the engine mid-station
                return self._scripted(agent, stage=stage, revision=revision, message=message)

            return hub.work_item.checkpoint(f"scripted-{stage}-{revision}", scripted_call)
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

    def start(workflow: str, *, key: str, route: str, input: dict, requester: str, origin: dict | None = None) -> dict:
        from hubzoid.work_items import WorkItemError
        from hubzoid.work_items import service as wi

        origin = origin or {"surface": "desk", "requested_by": requester, "acts_as": requester}
        args = dict(workflow=workflow, key=key, route=route, input=input, requester=requester, origin=origin)
        try:
            item, _ = wi.admit_and_start(hub_dir, **args)
        except WorkItemError as exc:
            if getattr(exc, "code", "") != "unavailable":
                raise
            # The engine is restarting. Hubzoid records the work before it
            # looks for the engine, and runs it once the engine is back. The
            # same admission again returns that recorded work, or raises if
            # nothing was recorded.
            item, _ = wi.admit(hub_dir, **args)
            item = dict(item, queued=True)
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
        env = dict(envelopes.from_envelope(inp["envelope"]), work_item_id=hub.work_item.id)
        opened = hub.work_item.checkpoint("intake", lambda: cases.intake(hub_dir, env))
    elif kind == "intake":
        if inp.get("channel") not in values["DESK_EXTERNAL_CHANNELS"]:
            return {"state": "ignored", "message": f"Channel {inp.get('channel')} is not in DESK_EXTERNAL_CHANNELS."}
        env = dict(envelopes.from_intake_item(inp), work_item_id=hub.work_item.id)
        opened = hub.work_item.checkpoint("intake", lambda: cases.intake(hub_dir, env))
        hub.work_item.checkpoint("origin", lambda: remember_origin(hub_dir, opened["case_id"]))
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
    elif kind == "page":
        # Desk roles changed: republish this case's page for the current readers only.
        return {"state": "page", "page": publish_case_page(hub_dir, inp["case_id"])}
    elif kind in ("rerun", "bound", "case", "decision"):
        opened = {"case_id": inp["case_id"], "seq": inp.get("seq")}
        trigger = inp.get("reason") or kind
        instruction = inp.get("instruction")
    else:
        return {"state": "ignored", "message": f"Unknown input kind {kind!r}."}
    if opened.get("action") == "duplicate":
        return {"state": "duplicate", "case": opened["number"]}
    hub.work_item.checkpoint("cancel-stale-sends", lambda: cancel_pending_sends(hub_dir, opened["case_id"]))
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
    if result.get("state") == "outdated":
        return result          # the newer triage of this case publishes and writes back
    publish_case_page(hub_dir, opened["case_id"])
    case = store.get_case(store.connect(hub_dir), opened["case_id"])
    if case["surface"] == "helpdesk" and values["DESK_HELPDESK"] in ("zoho_desk", "freshdesk"):
        result["helpdesk"] = helpdesk_writeback(hub_dir, values, case)
    return result


def remember_origin(hub_dir: Path, case_id: str) -> dict:
    """Keep the channel origin of the first message, so a person's reply goes
    back on the same thread through `hub.thread`, and nowhere else."""
    from hubzoid import hub
    from hubzoid.work_items import store as wi_store

    item = wi_store.get_item(hub_dir, hub.work_item.id)
    origin = dict((item or {}).get("origin_json") or {})
    with store.tx(hub_dir) as conn:
        c = store.get_case(conn, case_id)
        if not c.get("origin") and origin.get("surface") == "channel":
            store.update_case(conn, case_id, origin=origin)
    return origin


def _hub_dir() -> Path:
    from hubzoid.workflows.context import _ctx

    return Path(_ctx().hub_dir)


#: Who may open a case page: the people who may see the case in chat.
PAGE_ROLES = ("desk_operator", "desk_delivery", "desk_complaints", "desk_exceptions", "desk_bindings",
              "manage_access")


def page_readers(hub_dir: Path, hub_name: str) -> list[str]:
    """Every account that holds a desk role in this hub now, sorted. A case
    page is shared with exactly these people, never with the whole hub."""
    from hubzoid.access import store_for

    gs = store_for(Path(hub_dir))
    subjects = sorted({s for s, h, _p in gs.list_grants() if h in (hub_name, "*") and "@" in s})
    return [s for s in subjects if any(gs.can(s, hub_name, role) for role in PAGE_ROLES)]


def _page_hub(hub_dir: Path) -> str:
    from hubzoid import hub
    from hubzoid.access import normalize
    from hubzoid.assertions import hub_key

    try:
        # runtime.init permits a deployment-provided hub_name; artifact.publish
        # normalizes this exact context identity, so upkeep must use it too.
        return normalize(hub.name)
    except RuntimeError:
        return hub_key(hub_dir)  # trusted-host maintenance outside a workflow


def publish_case_page(hub_dir: Path, case_id: str) -> dict | None:
    """The case as one page in Hubzoid's artifact viewer, one link per case
    that always shows the newest revision, readable only by desk role holders.
    Older copies are deleted, so a person who lost their role cannot open an
    earlier one. A failure is recorded on the case and never stops triage."""
    from hubzoid import hub

    from . import casepage

    view = views.case(hub_dir, case_id)
    if view is None:
        return None
    number = view["case"]["number"]
    path = Path(hub.run_dir) / f"case-{number}.html"
    path.write_text(casepage.render(view))
    readers = page_readers(hub_dir, _page_hub(hub_dir))
    # Returning to a previous ACL must create a fresh copy after its old copy
    # was retired. Include the successful publication generation in the digest.
    generation = int(view["case"].get("page_generation") or 0)
    digest = casepage.digest(view) + ":" + hashlib.sha256(",".join(readers).encode()).hexdigest()[:16] + f":{generation}"
    try:
        if readers:
            page = hub.publish_artifact(str(path), title=f"Case {number}", key=f"case-{number.lower()}",
                                        digest=digest, audience="people", share_with=readers)
        else:
            page = hub.publish_artifact(str(path), title=f"Case {number}", key=f"case-{number.lower()}",
                                        digest=digest, audience="owner")
        _prune_older_pages(hub_dir, page)
    except Exception as exc:  # noqa: BLE001 - the page is a view; the case itself is saved
        with store.tx(hub_dir) as conn:
            # A failed page work item is completed too. Advance its next key so
            # the upkeep tick retries publication instead of reusing failure.
            conn.execute("UPDATE cases SET page_generation=page_generation+1 WHERE id=?", (case_id,))
            store.audit(conn, "desk", "case_page_failed", case_id, {"error": type(exc).__name__,
                                                                    "message": str(exc)[:300]})
        return {"error": type(exc).__name__, "message": str(exc)[:300]}
    url = (page or {}).get("latest_url") or (page or {}).get("url")
    if url:
        with store.tx(hub_dir) as conn:
            # A global cursor let the first refreshed case hide the remaining
            # old ACLs. Each case now acknowledges its own reader snapshot.
            conn.execute("UPDATE cases SET page_url=?, page_readers=?, page_generation=page_generation+1, "
                         "page_revision=? WHERE id=?", (url, ",".join(readers), view["case"]["revision"], case_id))
    return page


def _prune_older_pages(hub_dir: Path, page: dict | None) -> None:
    """Keep one copy per case page: the run's own account deletes the older ones."""
    from sqlalchemy import text

    from hubzoid import artifacts

    latest = artifacts.get(hub_dir, (page or {}).get("id") or "")
    if latest is None or not latest.series_id:
        return
    with artifacts._engine(hub_dir).connect() as c:
        ids = [r[0] for r in c.execute(text("SELECT id FROM hz_artifacts WHERE series_id=:s AND deleted IS NULL "
                                            "AND id != :a"), {"s": latest.series_id, "a": latest.id}).fetchall()]
    for old in ids:
        art = artifacts.get(hub_dir, old)
        if art is not None and art.owner == latest.owner:
            artifacts.delete(hub_dir, art, latest.owner)


def refresh_pages_if_readers_changed(hub_dir: Path, start, *, limit: int = 100) -> int:
    """When desk roles change, republish case pages for the new set of readers
    (run every minute by desk_upkeep). Each refresh is a small triage work item,
    so the page stays in its own workflow's series."""
    conn = store.connect(hub_dir)
    hub_name = _page_hub(hub_dir)
    readers = ",".join(page_readers(hub_dir, hub_name))
    # Immediately retire every stale case copy, including copies beyond this
    # tick's work budget. New pages are published under the upkeep identity.
    # This avoids an old artifact owner retaining a revoked desk role's data.
    stale = store.rows(conn.execute("SELECT id, number, page_generation FROM cases WHERE page_url IS NOT NULL "
                                   "AND (page_readers IS NULL OR page_readers != ?) ORDER BY page_generation, updated", (readers,)))
    if not stale:
        return 0
    from sqlalchemy import bindparam, text
    from hubzoid import artifacts

    keys = [f"case-{c['number'].lower()}" for c in stale]
    with artifacts._engine(hub_dir).begin() as db:
        # Operational maintenance of this hub's own generated case artifacts.
        # Tombstone every historical copy before any asynchronous refresh.
        query = text("UPDATE hz_artifacts SET deleted=:now WHERE hub=:hub AND latest_key IN :keys "
                     "AND deleted IS NULL").bindparams(bindparam("keys", expanding=True))
        import time
        for offset in range(0, len(keys), 256):
            db.execute(query, {"now": time.time(), "hub": hub_name, "keys": keys[offset:offset + 256]})
    tag = hashlib.sha256(readers.encode()).hexdigest()[:12]
    n = 0
    for c in stale[:limit]:
        try:
            start("customer_desk_intake", key=f"page:{c['id']}:{c['page_generation']}:{tag}", route="triage",
                  input={"kind": "page", "case_id": c["id"]}, requester="")
            n += 1
        except Exception:  # noqa: BLE001 - the next tick tries again
            continue
    return n


def refresh_changed_pages(hub_dir: Path, start, *, limit: int = 50) -> int:
    """Republish case pages whose case changed after the page was made: a
    person's edit, a decision, a send that settled (run every minute by
    desk_upkeep). The old copy stays readable until the new one replaces it."""
    conn = store.connect(hub_dir)
    rows = store.rows(conn.execute("SELECT id, revision FROM cases WHERE page_url IS NOT NULL AND "
                                   "revision > page_revision ORDER BY updated LIMIT ?", (limit,)))
    n = 0
    for c in rows:
        try:
            start("customer_desk_intake", key=f"page:{c['id']}:r{c['revision']}", route="triage",
                  input={"kind": "page", "case_id": c["id"]}, requester="")
            n += 1
        except Exception:  # noqa: BLE001 - the next tick tries again
            continue
    return n


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
        from .helpdesk.retrieval import permitted

        if not permitted(got["ticket"], values):
            return None
        item_id = hub.work_item.id
        if not desk.claim_message(hub_dir, got["ticket"], str(got["inbound"]["id"]), owner=item_id):
            return None
        env = dict(envelopes.from_helpdesk(got["ticket"], got["inbound"],
                                           provider=values["DESK_HELPDESK"],
                                           synthetic=config.namespace(values) == "sample"), work_item_id=item_id)
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
    if mode == "live" and reply and (reply.get("checks") or {}).get("passed"):
        def older_draft():
            row = store.connect(hub_dir).execute("SELECT latest_inbound_id FROM helpdesk_tickets WHERE ticket_id=?",
                                                 (str(ticket_id),)).fetchone()
            try:
                decision, _ = desk.preflight_draft(reader, ticket_id, row["latest_inbound_id"] if row else None, mark)
            except zoho.ZohoError:
                return False
            return decision == "other_draft"

        if hub.work_item.checkpoint(f"helpdesk-older-draft-r{rev}", older_draft):
            note = desk.note_for(view, mark, replace_draft=True)

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
        # A complete listing without the marker proves the note is not there.
        comments, complete = reader.all_comments(ticket_id)
        for c in comments:
            if mark in (c.get("content") or ""):
                return Reconciled("applied", {"id": c.get("id")})
        return Reconciled("safe_to_retry" if complete else "unknown")

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
    from hubzoid.work_items import config as wi_config

    # Unattended triage writes an unsent draft only. Any other mode would park
    # for an approval nobody attends, so it writes nothing and says why.
    channel = values["DESK_HELPDESK"]
    mode = wi_config.mode_for(wi_config.load(hub_dir), ["customer_reply.send"], channel)
    if mode != "draft":
        return f"not written: customer_reply.send is {mode} for {channel}, and the helpdesk takes drafts only"
    pl = replies.payload(hub_dir, case, reply)
    try:
        result = hub.operation.run(name="customer_reply", target={"case": case["number"], "reply": reply["revision"]},
                                   arguments=pl, recovery="reconcile",
                                   reconcile=replies.zoho_reconcile(hub_dir, values, case, reply),
                                   actions="customer_reply.send", channel=channel,
                                   dispatch=replies.refuse_helpdesk_send,
                                   draft=replies.zoho_draft(hub_dir, values, case, reply))
    except WorkItemError as exc:
        return f"not written: {exc.message}"
    except OperationFailed as exc:
        return f"not written: {exc}"

    def settle():
        with store.tx(hub_dir) as conn:
            if result.get("state") or channel == "freshdesk":
                state = _editor_result_state(result)
                store.upsert_send(conn, case["id"], reply["revision"], "draft", synthetic=case["synthetic"],
                                  status=state, receipt=result, requested_by="desk")
                store.update_case(conn, case["id"], state=state)
                return result
            store.upsert_send(conn, case["id"], reply["revision"], "draft", synthetic=case["synthetic"],
                              provider_draft_id=result.get("provider_draft_id"), status="draft_saved",
                              receipt=result, requested_by="desk")
            store.set_reply_state(conn, case["id"], reply["revision"], "helpdesk_draft_saved")
            store.update_case(conn, case["id"], state="helpdesk_draft_saved")
        return result

    hub.work_item.checkpoint(f"helpdesk-draft-r{reply['revision']}", settle)
    return result.get("state") or f"unsent draft {result.get('provider_draft_id')}"


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
    if action == "send" and reply["state"] not in ("requested", "ambiguous"):
        # "ambiguous" is a send whose outcome its requester is deciding on the
        # Work items page: the operation settles it, never this guard.
        return {"state": "reply_stale", "message": f"Reply {reply['revision']} is {reply['state']}. Nothing was sent."}
    loaded = pipeline.load(hub_dir)
    stale = hub.work_item.checkpoint("recheck", lambda: recheck.changed_facts(hub_dir, case, store.get_facts(
        store.connect(hub_dir), case["id"], reply["resolution"]), policy=loaded.policy))
    if stale:
        return _stale(hub_dir, case, reply, requester, stale)
    pl = replies.payload(hub_dir, case, reply)
    channel = case["channel_id"]
    # Staleness is checked inside dispatch, after the requester's approval and
    # just before anything leaves: a newer reply or message, a changed ERP
    # fact, or a changed policy refuses the send outright (Rejected), and the
    # desk drafts a new revision. A fresh approval of stale content is never
    # what a person wants, so no target_version re-park is used here.

    def dispatch(args):
        fresh = dispatch_check(hub_dir, case, reply, requester, loaded)
        if channel == "sample-whatsapp" and not replies.whatsapp_window_open(hub_dir, fresh):
            raise Rejected("window_closed: WhatsApp allows a free-form reply only within 24 hours of the "
                           "customer's last message.")
        _mark(hub_dir, case, reply, "sending")
        fault = os.environ.get("DESK_SAMPLE_FAULT", "")
        if fault == "fail_before_write" and not _fault_used(hub_dir, "before"):
            raise TimeoutError("injected: the outbox did not answer")
        result = replies._sample_write(hub_dir, args, "send", requester)
        if fault == "ambiguous" and not _fault_used(hub_dir, "after"):
            raise TimeoutError("injected: the outbox accepted it, then the connection dropped")
        if fault == "die_after_write" and not _fault_used(hub_dir, "after"):
            os._exit(9)          # injected: the process dies after the outbox accepted the reply
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
    elif channel in ("zoho_desk", "freshdesk"):
        kwargs = dict(dispatch=replies.refuse_helpdesk_send, draft=replies.zoho_draft(hub_dir, values, case, reply),
                      reconcile=replies.zoho_reconcile(hub_dir, values, case, reply))
    else:
        return channel_send(hub_dir, case, reply, requester, action, loaded)
    try:
        result = hub.operation.run(name="customer_reply", target={"case": case["number"], "reply": reply["revision"]},
                                   arguments=pl, recovery="reconcile", actions="customer_reply.send", channel=channel,
                                   **kwargs)
    except OperationFailed as exc:
        out = hub.work_item.checkpoint("settle-failed", lambda: _failed(hub_dir, case, reply, action, exc, requester))
        if out.get("state") == "reply_stale":
            _redraft(hub_dir, case, requester, reason="stale_at_dispatch")
        return out
    return hub.work_item.checkpoint("settle", lambda: _settled(hub_dir, case, reply, action, result, requester))


def dispatch_check(hub_dir: Path, case: dict, reply: dict, requester: str, loaded) -> dict:
    """Everything that must still hold the moment a reply leaves, after the
    requester approved it: it is still the current reply, the sender still
    resolves to the same customer, the requester still holds the case and a
    desk role, and the ERP facts, policy and reply style are unchanged.
    Raises Rejected, so nothing is sent and the desk redrafts."""
    from hubzoid.access import store_for
    from hubzoid.work_items import Rejected

    from . import scope

    conn = store.connect(hub_dir)
    fresh = store.get_case(conn, case["id"])
    if fresh["current_reply"] != reply["revision"]:
        raise Rejected("reply_stale: a newer reply or customer message replaced this one.")
    if fresh["origin_kind"] == "external" and scope.current_customer(hub_dir, fresh) != case["customer_id"]:
        raise Rejected("reply_stale: the sender's binding changed after approval.")
    if fresh["claimed_by"] != requester:
        raise Rejected("claim_lost: the person who asked no longer holds this case.")
    gs = store_for(Path(hub_dir))
    hub_name = Path(hub_dir).name.lower()
    if not (gs.can(requester, hub_name, "desk_operator") or gs.can(requester, hub_name, "manage_access")):
        raise Rejected("role_lost: the person who asked no longer holds the desk operator role.")
    if recheck.changed_facts(hub_dir, fresh, store.get_facts(conn, case["id"], reply["resolution"]),
                             policy=loaded.policy):
        raise Rejected("reply_stale: ERPNext changed after approval.")
    current = pipeline.load(hub_dir)
    res = store.get_resolution(conn, case["id"], reply["resolution"])
    if current.policy.digest != res["policy_digest"] or current.style.digest != res["style_digest"]:
        raise Rejected("reply_stale: the policy or reply style changed after this reply was drafted.")
    return fresh


def _redraft(hub_dir: Path, case: dict, requester: str, *, reason: str, stale=None) -> None:
    """Start a new resolution for the person who asked, so they review a reply
    drafted from the current facts and policy."""
    from . import actions

    actor = actions.Actor(requester, lambda role: True)
    try:
        actions.rerun(hub_dir, case["number"], actor, instruction=None, start=start_work(hub_dir), reason=reason,
                      stale=stale)
    except actions.ActionError:
        pass


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
    _redraft(hub_dir, case, requester, reason="facts_changed", stale=stale)
    return out


def _editor_result_state(result):
    from .helpdesk.editor import EDITOR_STATES

    state = result.get("state")
    return ("provider_delivery_uncertain" if state == "placing" or state not in EDITOR_STATES else state)


def _settled(hub_dir, case, reply, action, result, requester):
    with store.tx(hub_dir) as conn:
        c = store.get_case(conn, case["id"])
        if action == "draft":
            if result.get("state") or c["channel_id"] == "freshdesk":
                state = _editor_result_state(result)
                store.update_case(conn, case["id"], state=state)
                store.upsert_send(conn, case["id"], reply["revision"], "draft", synthetic=case["synthetic"],
                                  status=state, receipt=result, requested_by=requester)
                return {"state": state, "receipt": result}
            state = "helpdesk_draft_saved" if c["channel_id"] in ("zoho_desk", "freshdesk") else "mailbox_draft_saved"
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
        elif "claim_lost" in text or "role_lost" in text:
            store.set_reply_state(conn, case["id"], reply["revision"], "ready")
            store.update_case(conn, case["id"], state="needs_owner", claimed_by=None, note=f"Not sent: {text[:200]}")
            status = "claim_lost" if "claim_lost" in text else "role_lost"
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


def channel_send(hub_dir: Path, case: dict, reply: dict, requester: str, action: str = "send",
                 loaded=None) -> dict:
    """A Hubzoid email or WhatsApp channel: the reply goes back on the case's
    stored origin thread through `hub.thread.post`, text only.

    `hub.thread.post` takes no dispatch hook, so the dispatch-time check runs
    here, outside any checkpoint, right before the post: on the first run, and
    again when the work resumes after the requester's approval, which is the
    moment the post would send. A failed check abandons the approved post, so
    nothing waits or leaves."""
    from hubzoid import hub
    from hubzoid.work_items import OperationFailed, Rejected

    if reply["attachments"]:
        return {"state": "attachments_unsupported",
                "message": "Hubzoid channel replies carry text only. Save the reply as a draft, or send it with the "
                           "attachment from your own mailbox."}
    try:
        dispatch_check(hub_dir, case, reply, requester, loaded or pipeline.load(hub_dir))
    except Rejected as exc:
        _abandon_waiting_posts(hub_dir, hub.work_item.id, str(exc))
        out = hub.work_item.checkpoint("settle-refused", lambda: _failed(hub_dir, case, reply, action, exc, requester))
        if out.get("state") == "reply_stale":
            _redraft(hub_dir, case, requester, reason="stale_at_dispatch")
        return out
    try:
        # Both actions govern the post, so the stricter of the two write modes applies.
        posted = hub.thread.post(reply["rendered"], key=f"desk:{case['id']}:{reply['revision']}:{action}",
                                 actions="customer_reply.send")
    except OperationFailed as exc:
        return hub.work_item.checkpoint("settle-failed", lambda: _failed(hub_dir, case, reply, action, exc, requester))
    result = (posted[0] if isinstance(posted, list) and posted else posted) or {}
    if not isinstance(result, dict):
        result = {"result": result}
    return hub.work_item.checkpoint("settle", lambda: _settled(hub_dir, case, reply, action, result, requester))


def _abandon_waiting_posts(hub_dir: Path, item_id: str, reason: str) -> None:
    """Close this item's channel posts that wait for, or hold, an approval that
    can no longer be used, so none of them stays on the Work items page."""
    from hubzoid.work_items import store as wi_store

    for op in wi_store.list_ops(hub_dir, Path(hub_dir).name.lower(), item_id=item_id):
        if op["state"] == "awaiting_approval" and str(op.get("name", "")).startswith("channel."):
            try:
                wi_store.update_op(hub_dir, op["id"], expect_state=("awaiting_approval",), state="abandoned",
                                   resolution_json={"decision": "abandon", "by": "desk", "reason": reason[:300],
                                                    "at": wi_store.now()})
            except Exception:  # noqa: BLE001 - decided meanwhile: it was never dispatched by this run
                continue


def cancel_pending_sends(hub_dir: Path, case_id: str) -> list[str]:
    """A newer customer message made every unsent reply stale. Cancel the send
    work still waiting for approval, as its own requester, so no stale reply
    waits on the Work items page. Dispatch would refuse it anyway."""
    from hubzoid.work_items import service as wi

    cancelled = []
    conn = store.connect(hub_dir)
    for s in store.case_sends(conn, case_id):
        reply = store.get_reply(conn, case_id, s["reply_revision"])
        if reply is None or reply["state"] != "superseded":
            continue
        if s["status"] == "waiting_approval" and s.get("work_item_id") and s.get("requested_by"):
            try:
                wi.cancel(hub_dir, s["work_item_id"], s["requested_by"], reason="A newer customer message arrived.")
                cancelled.append(s["work_item_id"])
            except Exception:  # noqa: BLE001 - dispatch still refuses a stale reply
                continue
            with store.tx(hub_dir) as conn:
                store.upsert_send(conn, case_id, s["reply_revision"], s["mode"], status="cancelled_stale")
    return cancelled
