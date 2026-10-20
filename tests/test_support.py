"""General support, safe sources and corrections without models or ERP."""
from __future__ import annotations

import json

import pytest
import yaml

from customer_desk import cases, config, pipeline, recheck, store, vocab
from customer_desk.erpnext import config as erp_config
from customer_desk.helpdesk import retrieval


def configure(hub, **values):
    path = hub / "hub.settings.yaml"
    data = yaml.safe_load(path.read_text())
    data["values"].update({"DESK_SUPPORT_ENABLED": True, "DESK_ERP_ENABLED": False, "DESK_CLOCK": "system", **values})
    path.write_text(yaml.safe_dump(data))
    from hubzoid.hubs import settings
    settings.forget()


def open_support(hub, *, provider=None, ticket_id=None, event="support-1"):
    return cases.intake(hub, {"surface": "helpdesk" if provider else "email", "source_kind": "test-support",
        "source_ref": event, "channel_id": provider or "email", "provider": provider or "email",
        "helpdesk_ticket_id": ticket_id, "thread_key": f"{provider}:{ticket_id}" if provider else None,
        "sender": {"kind": "email", "address": "customer@example.test"},
        "text": "How do I export a report as CSV?", "synthetic": True})


class SupportRunner(pipeline.Runner):
    def __init__(self, *, bad_citation=False, reply=None, verdict="pass", category="other", injection=False):
        self.bad_citation, self.reply, self.verdict, self.category, self.injection = bad_citation, reply, verdict, category, injection
        self.calls = []

    def station(self, agent, *, stage, revision, message):
        self.calls.append(agent)
        if agent == "desk-classifier":
            return {"requests": [{"category": self.category}], "language": "en", "confidence": 0.99,
                    "escalation_flags": [], "injection_detected": self.injection, "needs_clarification": False}
        if agent == "desk-support-drafter":
            source = json.loads(message)["sources"][0]
            return {"should_draft": True, "reply": self.reply or source["text"].strip(),
                    "citations": ["kb:missing" if self.bad_citation else source["ref"]], "reason": "Supported export guidance"}
        if agent == "desk-support-reviewer":
            return {"verdict": self.verdict, "reason": "Independent applicability check"}
        raise AssertionError(agent)


def test_general_support_never_opens_erp_and_keeps_evidence(hub, monkeypatch):
    configure(hub)
    monkeypatch.setattr(erp_config, "backend", lambda *a, **kw: pytest.fail("ERP is optional"))
    opened = open_support(hub)
    result = pipeline.triage(hub, opened["case_id"], SupportRunner())
    assert result["checks_passed"]
    c = store.get_case(store.connect(hub), opened["case_id"])
    assert c["customer_id"] is None and c["state"] == "needs_owner"
    facts = store.get_facts(store.connect(hub), c["id"], c["current_resolution"])
    assert facts[0]["source"]["kind"] == "approved_knowledge"
    assert facts[0]["source"]["revision"].startswith("sha256:")
    assert not recheck.changed_facts(hub, c, facts)


@pytest.mark.parametrize("runner", [SupportRunner(bad_citation=True), SupportRunner(verdict="revise"),
    SupportRunner(reply="Your export is guaranteed in 99 days."), SupportRunner(reply="Send your password."),
    SupportRunner(injection=True)])
def test_unsafe_or_uncited_support_is_held_without_reply(hub, runner):
    configure(hub)
    opened = open_support(hub)
    result = pipeline.triage(hub, opened["case_id"], runner)
    assert result["checks_passed"] is False
    assert store.get_case(store.connect(hub), opened["case_id"])["current_reply"] is None


def test_saved_source_correction_changes_next_result_and_invalidates_old_evidence(hub):
    configure(hub)
    opened = open_support(hub)
    pipeline.triage(hub, opened["case_id"], SupportRunner(), trigger="first")
    conn = store.connect(hub)
    case = store.get_case(conn, opened["case_id"])
    old_facts = store.get_facts(conn, case["id"], case["current_resolution"])
    old = store.get_reply(conn, case["id"], case["current_reply"])
    article = hub / "knowledge/support/export-guide.md"
    article.write_text(article.read_text().replace("choose Export", "choose Download"))
    assert recheck.changed_facts(hub, case, old_facts)[0]["now"] == "source changed/removed"
    pipeline.triage(hub, case["id"], SupportRunner(), trigger="saved-correction")
    current = store.get_case(conn, case["id"])
    new = store.get_reply(conn, case["id"], current["current_reply"])
    assert "choose Download" in new["rendered"] and old["digest"] != new["digest"]
    assert store.get_reply(conn, case["id"], old["revision"])["state"] == "superseded"


@pytest.mark.parametrize("change", [("status: approved", "status: draft"),
    ("company: Synthetic Meridian Distribution", "company: Another Company"),
    ("audience: customer", "audience: internal"), ("language: en", "language: fr")])
def test_unapproved_or_wrong_scope_articles_never_enter_context(hub, change):
    configure(hub)
    article = hub / "knowledge/support/export-guide.md"
    article.write_text(article.read_text().replace(*change))
    opened = open_support(hub)
    runner = SupportRunner()
    result = pipeline.triage(hub, opened["case_id"], runner)
    assert not result["checks_passed"] and runner.calls == ["desk-classifier"]


def test_knowledge_directory_cannot_escape_hub(hub):
    configure(hub)
    values = config.settings(hub)
    values["DESK_KNOWLEDGE_DIR"] = "../"
    with pytest.raises(ValueError, match="inside the hub"):
        retrieval.articles(hub, values, "export")


def test_owner_categories_cannot_create_executable_actions(hub):
    configure(hub)
    path = hub / "knowledge/request-kinds.md"
    text = path.read_text().replace("  other:\n", "  export_help:\n    tag: desk-export\n    label: Export help\n    guidance: Export reports\n    behavior: answer\n  other:\n")
    path.write_text(text)
    assert "export_help" in vocab.load_kinds(hub).kinds
    path.write_text(text.replace("behavior: answer", "behavior: execute_refund"))
    with pytest.raises(vocab.VocabularyError):
        vocab.load_kinds(hub)


def test_risk_and_live_fact_requests_hold_without_fake_erp_answer(hub):
    configure(hub)
    opened = open_support(hub)
    runner = SupportRunner(category="order_status")
    result = pipeline.triage(hub, opened["case_id"], runner)
    assert not result["checks_passed"] and runner.calls == ["desk-classifier"]
