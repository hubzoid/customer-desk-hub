"""Offline Freshdesk HTTP contract and scoped native-editor delivery."""
from __future__ import annotations

import json

import httpx
import pytest

from customer_desk import actions, config, flows, pipeline, replies, store
from customer_desk.helpdesk import desk, editor, freshdesk, retrieval, zoho
from test_support import SupportRunner, configure, open_support


class Provider:
    def __init__(self):
        self.ticket = {"id": 42, "subject": "Export report", "description_text": "How do I export reports?",
            "description": "How do I export reports?", "status": 2, "group_id": 7, "product_id": None,
            "requester": {"email": "customer@example.test", "name": "Synthetic Customer"},
            "updated_at": "2026-10-20T10:00:00Z", "created_at": "2026-10-20T09:00:00Z", "tags": ["vip"]}
        self.conversations = []
        self.agent = {"id": 9, "active": True, "ticket_scope": 1, "group_ids": [7],
                      "contact": {"email": "operator@example.test"}}
        self.calls = []

    def request(self, request):
        path = request.url.path.removeprefix("/api/v2")
        body = json.loads(request.content) if request.content else None
        self.calls.append((request.method, path, body))
        if request.method == "GET":
            if path == "/tickets/42":
                return httpx.Response(200, json=self.ticket)
            if path == "/tickets/42/conversations":
                return httpx.Response(200, json=self.conversations)
            if path == "/agents/9":
                return httpx.Response(200, json=self.agent)
            if path == "/search/tickets":
                # An invented free-text filter would fail this contract.
                assert request.url.params["query"] == '"(status:4 OR status:5) AND group_id:7"'
                return httpx.Response(200, json={"total": 0, "results": []})
        if request.method == "PUT" and path == "/tickets/42":
            assert set(body) == {"tags"}
            self.ticket["tags"] = body["tags"]
            return httpx.Response(200, json=self.ticket)
        if request.method == "POST" and path == "/tickets/42/notes":
            note = {"id": len(self.conversations) + 2, **body, "incoming": False,
                    "created_at": "2026-10-20T11:00:00Z"}
            self.conversations.append(note)
            return httpx.Response(201, json=note)
        return httpx.Response(404, json={"description": "No such qualified endpoint"})


@pytest.fixture
def provider(hub, monkeypatch):
    configure(hub, DESK_HELPDESK="freshdesk", FRESHDESK_API_BASE="https://desk.example.test/api/v2",
              FRESHDESK_GROUP_ID="7", DESK_HELPDESK_MODE="live", DESK_HELPDESK_DRAFTS=True)
    monkeypatch.setenv("FRESHDESK_API_KEY", "synthetic-key")
    source = Provider()
    transport = httpx.MockTransport(source.request)
    reader = freshdesk.Reader(hub, config.settings(hub), transport=transport)
    monkeypatch.setattr(desk, "readers", lambda *a, **kw: (reader, None))
    return source, reader, transport


def ready(hub, reader):
    got = desk.read_ticket(reader, "42")
    assert desk.claim_message(hub, got["ticket"], got["inbound"]["id"], owner="test-item")
    opened = open_support(hub, provider="freshdesk", ticket_id="42")
    desk.link_case(hub, "42", opened["case_id"])
    result = pipeline.triage(hub, opened["case_id"], SupportRunner())
    assert result["checks_passed"]
    case = store.get_case(store.connect(hub), opened["case_id"])
    return case, store.get_reply(store.connect(hub), case["id"], case["current_reply"])


def test_reader_and_writer_cannot_send_close_assign_or_delete(hub, provider):
    source, reader, transport = provider
    writer = freshdesk.Writer(hub, config.settings(hub), transport=transport)
    writer.associate_tags("42", ["desk-export"])
    assert source.ticket["tags"] == ["desk-export", "vip"]
    for method, path, body in [("POST", "/tickets/42/reply", {"body": "unsafe"}),
            ("PUT", "/tickets/42", {"status": 5}), ("PUT", "/tickets/42", {"responder_id": 3}),
            ("DELETE", "/tickets/42", None), ("POST", "/tickets/42/notes", {"body": "x", "private": False})]:
        with pytest.raises(zoho.WriteRefused):
            writer._request(method, path, body=body)
    with pytest.raises(zoho.WriteRefused):
        reader._request("PUT", "/tickets/42", body={"tags": []})
    assert all(path != "/tickets/42/reply" for _, path, _ in source.calls)


def test_native_freshdesk_facets_and_initial_description(hub, provider):
    _, reader, _ = provider
    got = desk.read_ticket(reader, "42")
    assert got["inbound"]["id"] == "description"
    assert got["inbound"]["plainText"] == "How do I export reports?"
    reader.search_resolved("export", department_id="7")
    reader.search_resolved("report", department_id="7")
    assert sum(path == "/search/tickets" for _, path, _ in provider[0].calls) == 1


def test_live_intake_writeback_note_keeps_editor_available(hub, provider, monkeypatch):
    from types import SimpleNamespace
    import hubzoid

    source, reader, transport = provider
    # Real intake adapter, triage, writeback and editor service, with only SDK
    # checkpoint/operation dispatch performed inline (no engine/model/network).
    writer = freshdesk.Writer(hub, config.settings(hub), transport=transport)
    monkeypatch.setattr(desk, "readers", lambda *a, **kw: (reader, writer))
    def operation(**kw):
        fn = kw["draft"] if kw["name"] == "customer_reply" else kw["dispatch"]
        return fn(kw["arguments"])
    monkeypatch.setattr(hubzoid, "hub", SimpleNamespace(
        work_item=SimpleNamespace(id="live-intake", checkpoint=lambda _name, fn: fn()),
        operation=SimpleNamespace(run=operation)))
    opened = flows.helpdesk_intake(hub, config.settings(hub), "42")
    assert opened
    pipeline.triage(hub, opened["case_id"], SupportRunner())
    case = store.get_case(store.connect(hub), opened["case_id"])
    out = flows.helpdesk_writeback(hub, config.settings(hub), case)
    assert out["note"] == "written" and out["draft"] == "awaiting_provider_editor"
    assert source.conversations[-1]["private"] is True
    assert desk.awaiting_reply(desk.read_ticket(reader, "42")["threads"])
    actor = actions.Actor("operator@example.test", lambda _: True)
    editor.link(hub, actor, agent_id="9", principal=actor.email, reader=reader)
    assert editor.payload(hub, actor, ticket_id="42", agent_id="9", reader=reader)["body"]


@pytest.mark.parametrize("state", sorted(editor.EDITOR_STATES) + [None, "unexpected"])
def test_freshdesk_delivery_states_never_settle_as_saved(hub, provider, state, monkeypatch):
    from types import SimpleNamespace
    import hubzoid

    _, reader, _ = provider
    case, reply = ready(hub, reader)
    result = {"state": state} if state else {}
    monkeypatch.setattr(hubzoid, "hub", SimpleNamespace(
        work_item=SimpleNamespace(checkpoint=lambda _name, fn: fn()),
        operation=SimpleNamespace(run=lambda **kw: result)))
    flows.helpdesk_draft(hub, config.settings(hub), case, reply)
    out = flows._settled(hub, case, reply, "draft", result, "operator@example.test")
    conn = store.connect(hub)
    assert out["state"] != "helpdesk_draft_saved"
    assert store.get_reply(conn, case["id"], reply["revision"])["state"] == "ready"
    assert conn.execute("SELECT status FROM sends WHERE case_id=?", (case["id"],)).fetchone()["status"] != "draft_saved"


def test_freshdesk_prepare_refusal_is_rejected_not_uncertain(hub, provider, monkeypatch):
    from hubzoid.work_items import Rejected

    _, reader, transport = provider
    case, reply = ready(hub, reader)
    writer = freshdesk.Writer(hub, config.settings(hub), transport=transport)
    monkeypatch.setattr(desk, "readers", lambda *a, **kw: (reader, writer))
    def refuse(*a, **kw):
        raise actions.ActionError("ticket_changed", "A newer message requires rerun")
    monkeypatch.setattr(editor, "prepare", refuse)
    with pytest.raises(Rejected, match="ticket_changed"):
        replies.zoho_draft(hub, config.settings(hub), case, reply)({"body": reply["rendered"]})


def test_editor_requires_link_both_grants_and_current_provider_scope(hub, provider):
    source, reader, _ = provider
    case, reply = ready(hub, reader)
    actor = actions.Actor("operator@example.test", lambda role: role in ("desk_editor", "desk_operator"))
    with pytest.raises(actions.ActionError, match="administrator"):
        editor.payload(hub, actor, ticket_id="42", agent_id="9", reader=reader)
    editor.link(hub, actions.Actor("owner@example.test", lambda _: True), agent_id="9",
                principal=actor.email, reader=reader)
    data = editor.payload(hub, actor, ticket_id="42", agent_id="9", reader=reader)
    assert data["body"] == reply["rendered"] and data["state"] == "awaiting_provider_editor"
    with pytest.raises(actions.ActionError):
        editor.payload(hub, actions.Actor(actor.email, lambda role: role == "desk_operator"),
                       ticket_id="42", agent_id="9", reader=reader)
    source.agent.update(ticket_scope=3)
    with pytest.raises(actions.ActionError, match="assigned"):
        editor.payload(hub, actor, ticket_id="42", agent_id="9", reader=reader)
    source.agent.update(ticket_scope=1)
    source.ticket["group_id"] = 8
    with pytest.raises(actions.ActionError, match="scope"):
        editor.payload(hub, actor, ticket_id="42", agent_id="9", reader=reader)


def test_editor_placement_is_never_reported_persisted_or_reinserted(hub, provider):
    _, reader, _ = provider
    case, reply = ready(hub, reader)
    actor = actions.Actor("operator@example.test", lambda _: True)
    editor.link(hub, actor, agent_id="9", principal=actor.email, reader=reader)
    claimed = editor.payload(hub, actor, ticket_id="42", agent_id="9", reader=reader, claim=True, expected_digest=reply["digest"])
    with pytest.raises(actions.ActionError, match="matching editor claim"):
        editor.payload(hub, actor, ticket_id="42", agent_id="9", reader=reader, placed_digest=reply["digest"])
    busy = editor.payload(hub, actor, ticket_id="42", agent_id="9", reader=reader, claim=True, expected_digest=reply["digest"])
    assert busy["body"] is None and busy["state"] == "placing"
    ack = editor.payload(hub, actor, ticket_id="42", agent_id="9", reader=reader, placed_digest=reply["digest"],
                         placement_token=claimed["placement_token"])
    assert ack["state"] == "awaiting_provider_confirmation"
    again = editor.payload(hub, actor, ticket_id="42", agent_id="9", reader=reader)
    assert again["body"] is None and again["state"] == "awaiting_provider_confirmation"
    assert store.get_case(store.connect(hub), case["id"])["state"] != "helpdesk_draft_saved"


def test_claim_survives_restart_and_revoked_claimer_cannot_ack(hub, provider):
    _, reader, _ = provider
    case, reply = ready(hub, reader)
    actor = actions.Actor("operator@example.test", lambda _: True)
    editor.link(hub, actor, agent_id="9", principal=actor.email, reader=reader)
    claim = editor.payload(hub, actor, ticket_id="42", agent_id="9", reader=reader, claim=True, expected_digest=reply["digest"])
    store.reset_connections()
    assert editor.payload(hub, actor, ticket_id="42", agent_id="9", reader=reader)["body"] is None
    with pytest.raises(actions.ActionError):
        editor.payload(hub, actions.Actor(actor.email, lambda _: False), ticket_id="42", agent_id="9", reader=reader,
                       placed_digest=reply["digest"], placement_token=claim["placement_token"])
    row = store.connect(hub).execute("SELECT * FROM editor_deliveries WHERE case_id=?", (case["id"],)).fetchone()
    assert row["state"] == "placing" and row["claim_hash"] != claim["placement_token"]


def test_concurrent_editor_clicks_have_one_claimant(hub, provider):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    _, reader, _ = provider
    _, reply = ready(hub, reader)
    actor = actions.Actor("operator@example.test", lambda _: True)
    editor.link(hub, actor, agent_id="9", principal=actor.email, reader=reader)
    barrier = Barrier(2)

    def click(_):
        barrier.wait(timeout=10)
        return editor.payload(hub, actor, ticket_id="42", agent_id="9", reader=reader, claim=True, expected_digest=reply["digest"])

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(click, range(2)))
    assert sum(bool(r.get("placement_token")) for r in results) == 1
    assert sum(r.get("body") is None for r in results) == 1


def test_invoice_download_is_scoped_and_placement_requires_manual_attachment(hub, provider):
    _, reader, _ = provider
    case, reply = ready(hub, reader)
    actor = actions.Actor("operator@example.test", lambda _: True)
    editor.link(hub, actor, agent_id="9", principal=actor.email, reader=reader)
    invoice = pipeline.save_attachment(hub, name="synthetic-invoice.pdf", media_type="application/pdf", data=b"%PDF-synthetic")
    from customer_desk import facts, render
    loaded = pipeline.load(hub)
    digest = render.digest(case_id=case["id"], reply_revision=reply["revision"], body=reply["rendered"],
        subject=reply["subject"], recipients=reply["recipients"], attachments=[invoice],
        policy_digest=loaded.policy.digest,
        fact_sheet_digest=facts.digest(store.get_facts(store.connect(hub), case["id"], reply["resolution"])),
        origin={"channel": case["channel_id"], "thread": case["thread_key"]})
    with store.tx(hub) as conn:
        conn.execute("UPDATE replies SET attachments=?,digest=? WHERE case_id=? AND revision=?",
                     (store.dumps([invoice]), digest, case["id"], reply["revision"]))
    reply = store.get_reply(store.connect(hub), case["id"], reply["revision"])
    downloaded = editor.attachment(hub, actor, ticket_id="42", agent_id="9", sha256=invoice["sha256"], reader=reader)
    assert downloaded["media_type"] == "application/pdf" and downloaded["base64"]
    with pytest.raises(actions.ActionError):
        editor.attachment(hub, actions.Actor(actor.email, lambda _: False), ticket_id="42", agent_id="9",
                          sha256=invoice["sha256"], reader=reader)
    claim = editor.payload(hub, actor, ticket_id="42", agent_id="9", reader=reader, claim=True, expected_digest=reply["digest"])
    result = editor.payload(hub, actor, ticket_id="42", agent_id="9", reader=reader,
                           placed_digest=reply["digest"], placement_token=claim["placement_token"])
    assert result["state"] == "requires_manual_attachment"
    assert store.get_case(store.connect(hub), case["id"])["state"] != "helpdesk_draft_saved"


def test_editor_refuses_new_message_revoked_link_stale_evidence_and_attachments(hub, provider):
    source, reader, _ = provider
    case, reply = ready(hub, reader)
    actor = actions.Actor("operator@example.test", lambda _: True)
    editor.link(hub, actor, agent_id="9", principal=actor.email, reader=reader)
    source.conversations.append({"id": 99, "incoming": True, "created_at": "2026-10-20T11:00:00Z",
                                  "body_text": "A new question", "from_email": "customer@example.test"})
    with pytest.raises(actions.ActionError, match="newer"):
        editor.payload(hub, actor, ticket_id="42", agent_id="9", reader=reader)
    source.conversations.clear()
    article = hub / "knowledge/support/export-guide.md"
    article.write_text(article.read_text() + "\nA reviewed correction.\n")
    with pytest.raises(actions.ActionError, match="Evidence changed"):
        editor.payload(hub, actor, ticket_id="42", agent_id="9", reader=reader)
    with store.tx(hub) as conn:
        conn.execute("UPDATE editor_links SET state='revoked'")
    with pytest.raises(actions.ActionError, match="administrator"):
        editor.payload(hub, actor, ticket_id="42", agent_id="9", reader=reader)


def test_provider_ticket_ids_do_not_collide_after_provider_switch(hub, provider):
    source, reader, _ = provider
    got = desk.read_ticket(reader, "42")
    assert desk.claim_message(hub, got["ticket"], "description", owner="fresh")
    configure(hub, DESK_HELPDESK="zoho_desk")
    assert desk.claim_message(hub, got["ticket"], "description", owner="zoho")
    ids = {r[0] for r in store.connect(hub).execute("SELECT ticket_id FROM helpdesk_tickets")}
    assert ids == {"42", "freshdesk:42"}


def test_editor_respects_current_action_mode_and_manual_recovery(hub, provider):
    _, reader, _ = provider
    _, reply = ready(hub, reader)
    actor = actions.Actor("operator@example.test", lambda _: True)
    editor.link(hub, actor, agent_id="9", principal=actor.email, reader=reader)
    editor.payload(hub, actor, ticket_id="42", agent_id="9", reader=reader, claim=True, expected_digest=reply["digest"])
    recovered = editor.reconcile(hub, actor, ticket_id="42", decision="not_inserted")
    assert recovered["state"] == "awaiting_provider_editor" and recovered["provider_persistence"] == "unverified"
    (hub / "work-items.yaml").write_text("version: 1\nwrite_modes:\n  customer_reply.send: 'off'\n")
    with pytest.raises(actions.ActionError, match="mode"):
        editor.payload(hub, actor, ticket_id="42", agent_id="9", reader=reader)


def test_stale_confirmation_never_claims_new_reply(hub, provider):
    _, reader, _ = provider
    case, reply = ready(hub, reader)
    actor = actions.Actor("operator@example.test", lambda _: True)
    editor.link(hub, actor, agent_id="9", principal=actor.email, reader=reader)
    assert editor.payload(hub, actor, ticket_id="42", agent_id="9", reader=reader)["digest"] == reply["digest"]
    for expected in (None, "sha256:older-confirmation"):
        with pytest.raises(actions.ActionError, match="since confirmation"):
            editor.payload(hub, actor, ticket_id="42", agent_id="9", reader=reader, claim=True, expected_digest=expected)
    row = store.connect(hub).execute("SELECT * FROM editor_deliveries WHERE case_id=?", (case["id"],)).fetchone()
    assert row["state"] == "awaiting_provider_editor" and row["claim_hash"] is None


def test_inactive_provider_contact_revokes_payload(hub, provider):
    source, reader, _ = provider
    ready(hub, reader)
    actor = actions.Actor("operator@example.test", lambda _: True)
    editor.link(hub, actor, agent_id="9", principal=actor.email, reader=reader)
    source.agent["contact"]["active"] = False
    with pytest.raises(actions.ActionError, match="no longer active"):
        editor.payload(hub, actor, ticket_id="42", agent_id="9", reader=reader)
