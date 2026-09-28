"""The desk on the real Hubzoid engine (child process, scripted stations):
approvals, refusals, staleness, uncertain sends, crash recovery, the
WhatsApp window and the Zoho Desk draft. Run with: pytest -m engine"""
from __future__ import annotations

import json
import time

import pytest

from conftest import load_sample
from engine import OWNER, Engine, wait_case, wait_item, waiting_op

pytestmark = pytest.mark.engine


def approve_mode(hub, channel="sample-email"):
    (hub / "work-items.yaml").write_text("version: 1\nwrite_modes:\n  customer_reply.send: approve\n"
                                         "write_mode_overrides:\n  sample-whatsapp:\n    customer_reply.send: approve\n"
                                         if channel == "sample-whatsapp" else
                                         "version: 1\nwrite_modes:\n  customer_reply.send: approve\n"
                                         "write_mode_overrides:\n  sample-whatsapp:\n    customer_reply.send: \"off\"\n")


def owner():
    from customer_desk import actions

    return actions.Actor(OWNER, lambda role: True)


def load(hub, events):
    from customer_desk import cases, envelopes
    from customer_desk.flows import start_work

    start = start_work(hub)
    out = []
    for env in load_sample(hub):
        if env["provider_event_id"] in events:
            opened = cases.intake(hub, envelopes.from_envelope(env))
            start("customer_desk_intake", key=f"t:{opened['case_id']}", route="triage",
                  input={"kind": "case", "case_id": opened["case_id"], "seq": opened["seq"]}, requester="")
            out.append(opened["number"])
    for n in out:
        wait_case(hub, n, ("needs_owner",))
    return out


def ask_to_send(hub, number):
    from customer_desk import actions, store
    from customer_desk.flows import start_work

    actions.claim(hub, number, owner())
    c = store.get_case(store.connect(hub), number)
    r = store.get_reply(store.connect(hub), c["id"], c["current_reply"])
    return actions.request_send(hub, number, owner(), reply_revision=r["revision"], digest=r["digest"],
                                expected_revision=None, start=start_work(hub))


def test_send_waits_for_requester_then_sends_once(bound, tmp_path):
    from hubzoid.work_items import WorkItemError, service

    from customer_desk import replies, store

    approve_mode(bound)
    engine = Engine(bound, tmp_path)
    try:
        [number] = load(bound, {"syn-007"})
        out = ask_to_send(bound, number)
        assert out["state"] == "human_action_required"
        op = waiting_op(bound, out["work_item_id"])
        payload_case = store.get_case(store.connect(bound), number)
        assert payload_case["state"] == "waiting_approval"
        with pytest.raises(WorkItemError):           # nobody but the requester decides, admins included
            service.approve(bound, op["id"], "someone.else@desk.example", digest=op["args_digest"])
        assert replies.outbox_rows(bound) == []
        service.approve(bound, op["id"], OWNER, digest=op["args_digest"])
        wait_item(bound, out["work_item_id"], ("completed",))
        c = wait_case(bound, number, ("resolved",))
        rows = replies.outbox_rows(bound)
        assert len(rows) == 1 and rows[0]["recipients"] == ["accounts@synthetic-harbor.example"]
        assert rows[0]["attachments"][0]["name"] == "SYN-SINV-0001.pdf"
        send = store.case_sends(store.connect(bound), c["id"])[0]
        assert send["receipt"]["note"] == "Sample outbox accepted the reply. No customer delivery."
        assert c["first_reply_accepted_at"]
    finally:
        engine.close()


def test_rejected_send_has_no_effect(bound, tmp_path):
    from hubzoid.work_items import service

    from customer_desk import replies, store

    approve_mode(bound)
    engine = Engine(bound, tmp_path)
    try:
        [number] = load(bound, {"syn-001"})
        out = ask_to_send(bound, number)
        op = waiting_op(bound, out["work_item_id"])
        service.deny(bound, op["id"], OWNER, reason="Wrong tone")
        wait_case(bound, number, ("in_review",))
        c = store.get_case(store.connect(bound), number)
        assert store.get_reply(store.connect(bound), c["id"], c["current_reply"])["state"] == "rejected"
        assert replies.outbox_rows(bound) == []
    finally:
        engine.close()


def test_fact_change_after_approval_refuses_the_send(bound, tmp_path):
    from hubzoid.work_items import service

    from customer_desk import replies, store

    approve_mode(bound)
    engine = Engine(bound, tmp_path)
    try:
        [number] = load(bound, {"syn-007"})
        out = ask_to_send(bound, number)
        op = waiting_op(bound, out["work_item_id"])
        path = bound / "fixtures" / "erp" / "distributor-v1" / "sales_invoices.json"
        rows = json.loads(path.read_text())
        next(r for r in rows if r["name"] == "SYN-SINV-0001")["outstanding_amount"] = "250.00"   # a payment landed
        path.write_text(json.dumps(rows))
        service.approve(bound, op["id"], OWNER, digest=op["args_digest"])
        wait_item(bound, out["work_item_id"], ("completed", "failed", "stopped"))
        assert replies.outbox_rows(bound) == []
        deadline = time.time() + 120
        while time.time() < deadline:
            c = wait_case(bound, number, ("needs_owner", "in_review"), timeout=120)   # the operator still holds it
            if c["current_reply"] and c["current_reply"] >= 2:
                break
            time.sleep(0.5)
        reply = store.get_reply(store.connect(bound), c["id"], c["current_reply"])
        assert "$250.00" in reply["rendered"] and reply["revision"] >= 2     # redrafted from the new fact
        assert store.get_reply(store.connect(bound), c["id"], 1)["state"] == "superseded"
    finally:
        engine.close()


def test_new_customer_message_supersedes_a_pending_send(bound, tmp_path):
    from hubzoid.work_items import store as wi_store

    from customer_desk import cases, envelopes, replies, store
    from customer_desk.flows import start_work

    approve_mode(bound)
    engine = Engine(bound, tmp_path)
    try:
        [number] = load(bound, {"syn-001"})
        out = ask_to_send(bound, number)
        waiting_op(bound, out["work_item_id"])
        env = [e for e in load_sample(bound) if e["provider_event_id"] == "syn-001"][0]
        follow = dict(env, provider_event_id="syn-001-b", text="Actually, can you also send invoice SYN-SINV-0002?")
        opened = cases.intake(bound, envelopes.from_envelope(follow))
        assert opened["action"] == "appended" and opened["number"] == number
        start_work(bound)("customer_desk_intake", key=f"t:{opened['case_id']}:2", route="triage",
                          input={"kind": "case", "case_id": opened["case_id"], "seq": opened["seq"]}, requester="")
        wait_item(bound, out["work_item_id"], ("cancelled",), timeout=120)
        c = wait_case(bound, number, ("in_review",), timeout=120)      # redrafted, still held by its operator
        assert store.get_reply(store.connect(bound), c["id"], 1)["state"] == "superseded"
        assert replies.outbox_rows(bound) == []
        assert wi_store.get_item(bound, out["work_item_id"])["state"] == "cancelled"
    finally:
        engine.close()


def test_uncertain_send_is_never_resent_on_its_own(bound, tmp_path):
    from hubzoid.work_items import service, store as wi_store

    from customer_desk import replies

    approve_mode(bound)
    engine = Engine(bound, tmp_path, env={"DESK_SAMPLE_FAULT": "ambiguous"})
    try:
        [number] = load(bound, {"syn-001"})
        out = ask_to_send(bound, number)
        op = waiting_op(bound, out["work_item_id"])
        service.approve(bound, op["id"], OWNER, digest=op["args_digest"])
        blocked = wait_item(bound, out["work_item_id"], ("needs_input",))
        assert blocked["reason"] == "operation_ambiguous"
        assert wi_store.get_op(bound, op["id"])["state"] == "ambiguous"
        assert len(replies.outbox_rows(bound)) == 1          # it may have gone out: no second attempt
        row = replies.outbox_rows(bound)[0]
        service.resolve(bound, op["id"], OWNER, decision="done", evidence=f"Outbox row {row['id']}")
        wait_item(bound, out["work_item_id"], ("completed",))
        wait_case(bound, number, ("resolved",))
        assert len(replies.outbox_rows(bound)) == 1
    finally:
        engine.close()


def test_process_death_after_send_reconciles_without_a_second_send(bound, tmp_path):
    from hubzoid.work_items import service

    from customer_desk import replies

    approve_mode(bound)
    engine = Engine(bound, tmp_path, env={"DESK_SAMPLE_FAULT": "die_after_write"})
    try:
        [number] = load(bound, {"syn-001"})
        out = ask_to_send(bound, number)
        op = waiting_op(bound, out["work_item_id"])
        service.approve(bound, op["id"], OWNER, digest=op["args_digest"])
        engine.proc.wait(60)                       # it died right after the outbox accepted the reply
        assert len(replies.outbox_rows(bound)) == 1
    finally:
        engine.close()
    engine = Engine(bound, tmp_path)               # recovery reads the outbox instead of sending again
    try:
        wait_item(bound, out["work_item_id"], ("completed",), timeout=120)
        wait_case(bound, number, ("resolved",))
        assert len(replies.outbox_rows(bound)) == 1
    finally:
        engine.close()


def test_whatsapp_window_closed_holds_the_reply(bound, tmp_path):
    from hubzoid.work_items import service

    from customer_desk import cases, envelopes, replies
    from customer_desk.flows import start_work

    approve_mode(bound, "sample-whatsapp")
    engine = Engine(bound, tmp_path)
    try:
        env = [e for e in load_sample(bound) if e["provider_event_id"] == "syn-005"][0]
        env = dict(env, received_at="2000-01-13T09:00:00Z")      # more than 24 hours before the desk's today
        opened = cases.intake(bound, envelopes.from_envelope(env))
        start_work(bound)("customer_desk_intake", key="t:wa", route="triage",
                          input={"kind": "case", "case_id": opened["case_id"], "seq": opened["seq"]}, requester="")
        wait_case(bound, opened["number"], ("needs_owner",))
        out = ask_to_send(bound, opened["number"])
        op = waiting_op(bound, out["work_item_id"])
        service.approve(bound, op["id"], OWNER, digest=op["args_digest"])
        wait_case(bound, opened["number"], ("held",))
        assert replies.outbox_rows(bound) == []
    finally:
        engine.close()


def test_crash_mid_triage_resumes_without_duplicates(bound, tmp_path):
    from hubzoid.work_items import store as wi_store

    from customer_desk import cases, envelopes, store
    from customer_desk.flows import start_work

    engine = Engine(bound, tmp_path, env={"DESK_SCRIPTED_DELAY": "4"})
    try:
        env = [e for e in load_sample(bound) if e["provider_event_id"] == "syn-018"][0]
        opened = cases.intake(bound, envelopes.from_envelope(env))
        item = start_work(bound)("customer_desk_intake", key="t:crash", route="triage",
                                 input={"kind": "case", "case_id": opened["case_id"], "seq": opened["seq"]},
                                 requester="")
        deadline = time.time() + 60
        while time.time() < deadline:
            if store.case_tickets(store.connect(bound), opened["case_id"]):
                break                                            # gathered: the ticket exists
            time.sleep(0.2)
        engine.kill()                                            # dies before the resolver answers
    finally:
        engine.close()
    engine = Engine(bound, tmp_path)
    try:
        wait_item(bound, item["id"], ("completed",), timeout=120)
        conn = store.connect(bound)
        assert len(store.case_tickets(conn, opened["case_id"])) == 1
        assert [r["revision"] for r in store.replies(conn, opened["case_id"])] == [1]
        assert wi_store.get_item(bound, item["id"])["state"] == "completed"
    finally:
        engine.close()


@pytest.fixture
def zoho_hub(bound, monkeypatch):
    from customer_desk.helpdesk import fake_zoho, zoho

    fake = fake_zoho.FakeZoho()
    base = fake.start()
    monkeypatch.setattr(zoho, "SLEEP", lambda s: None)
    for k, v in fake.env(base).items():
        monkeypatch.setenv(k, v)
    monkeypatch.setenv("DESK_LOOPBACK_ONLY", "1")
    path = bound / "hub.settings.yaml"
    path.write_text(path.read_text().replace("DESK_HELPDESK: none", "DESK_HELPDESK: zoho_desk").replace(
        "DESK_HELPDESK_MODE: dry-run", "DESK_HELPDESK_MODE: live\n  DESK_HELPDESK_DRAFTS: true\n"
        "  ZOHO_DESK_FROM_ADDRESS: care@synthetic-meridian.example\n  ZOHO_DESK_CASE_FIELD: cf_desk_case\n"
        f"  ZOHO_DESK_API_BASE: {base}/api/v1\n  ZOHO_DESK_ACCOUNTS_BASE: {base}"))
    yield bound, fake
    fake.stop()


def test_zoho_ticket_becomes_tags_note_and_an_unsent_draft(zoho_hub, tmp_path):
    from customer_desk import store
    from customer_desk.flows import start_work
    from customer_desk.helpdesk import desk

    hub, fake = zoho_hub
    engine = Engine(hub, tmp_path)
    try:
        t = fake.add_ticket(subject="Invoice copy", text="Please send a copy of invoice SYN-SINV-0001.",
                            email="accounts@synthetic-harbor.example", first="Synthetic", last="Accounts",
                            notify=False)
        item = start_work(hub)("customer_desk_intake", key=f"helpdesk:{t['id']}:1", route="triage",
                               input={"kind": "helpdesk", "ticket_id": t["id"]}, requester="")
        wait_item(hub, item["id"], ("completed",), timeout=120)
        c = store.get_case(store.connect(hub), store.connect(hub).execute(
            "SELECT case_id FROM helpdesk_tickets WHERE ticket_id=?", (t["id"],)).fetchone()["case_id"])
        assert c["state"] == "helpdesk_draft_saved"
        assert fake.tags[t["id"]] == {"desk-invoice-copy"}
        note = fake.comments[t["id"]][0]
        assert note["isPublic"] is False and "SYN-SINV-0001" in note["content"] and "Sales Invoice" in note["content"]
        drafts = fake.drafts(t["id"])
        assert len(drafts) == 1 and "$1,250.00" in drafts[0]["plainText"] and drafts[0]["attachmentIds"]
        assert fake.tickets[t["id"]]["cf"] == {"cf_desk_case": c["number"]}
        assert fake.forbidden == [] and fake.tickets[t["id"]]["status"] == "Open"
        assert not any("sendReply" in p for _, p, _ in fake.writes)
        # The desk's own writes changed the ticket. A second event for it starts nothing new.
        again = start_work(hub)("customer_desk_intake", key=f"helpdesk:{t['id']}:2", route="triage",
                                input={"kind": "helpdesk", "ticket_id": t["id"]}, requester="")
        done = wait_item(hub, again["id"], ("completed",))
        assert done["result_json"]["result"]["state"] == "no_new_message"
        assert len(fake.drafts(t["id"])) == 1
        assert [w["status"] for w in desk.ledger(hub, ticket_id=t["id"])] == ["written", "written"]
    finally:
        engine.close()


def test_zoho_dry_run_writes_nothing(zoho_hub, tmp_path):
    from customer_desk.flows import start_work
    from customer_desk.helpdesk import desk

    hub, fake = zoho_hub
    path = hub / "hub.settings.yaml"
    path.write_text(path.read_text().replace("DESK_HELPDESK_MODE: live", "DESK_HELPDESK_MODE: dry-run"))
    engine = Engine(hub, tmp_path)
    try:
        t = fake.add_ticket(subject="Where", text="Where is order SYN-SO-0001?", email="buyer.one@synthetic-harbor.example",
                            notify=False)
        item = start_work(hub)("customer_desk_intake", key=f"helpdesk:{t['id']}:1", route="triage",
                               input={"kind": "helpdesk", "ticket_id": t["id"]}, requester="")
        wait_item(hub, item["id"], ("completed",), timeout=120)
        assert fake.writes == [] and fake.tags[t["id"]] == set()
        assert {w["status"] for w in desk.ledger(hub, ticket_id=t["id"])} == {"dry-run"}
    finally:
        engine.close()
