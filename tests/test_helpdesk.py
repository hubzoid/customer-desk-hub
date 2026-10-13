"""Zoho Desk: the read client only reads, the write client reaches only its
five endpoints, the stop switch is read at the moment of writing, and the
draft is placed only after a fresh reread. Against the fake Zoho Desk."""
from __future__ import annotations

import pytest

from customer_desk import store
from customer_desk.helpdesk import desk, fake_zoho, zoho


@pytest.fixture
def fake(monkeypatch):
    f = fake_zoho.FakeZoho()
    base = f.start()
    monkeypatch.setattr(zoho, "SLEEP", lambda s: None)
    zoho.reset_caches()
    yield f, base
    f.stop()


def creds(base, write=False):
    if write:
        return zoho.Credentials("write-client", "write-secret", "write-refresh", f"{base}/api/v1", base)
    return zoho.Credentials("read-client", "read-secret", "read-refresh", f"{base}/api/v1", base)


def set_mode(hub, mode, drafts=True, case_field="cf_desk_case"):
    """The helpdesk settings in force at the moment of writing."""
    import yaml

    path = hub / "hub.settings.yaml"
    doc = yaml.safe_load(path.read_text())
    doc["values"].update({"DESK_HELPDESK_MODE": mode, "DESK_HELPDESK_DRAFTS": drafts,
                          "ZOHO_DESK_CASE_FIELD": case_field})
    path.write_text(yaml.safe_dump(doc, sort_keys=False))
    from hubzoid.hubs import settings as hub_settings

    hub_settings.forget()          # Hubzoid reads hub settings once per process


def writer(hub, base, **kw):
    mode, drafts = kw.pop("mode", "live"), kw.pop("drafts", True)
    set_mode(hub, mode, drafts)
    pol = zoho.WritePolicy(mode=mode, tag_prefix="desk-", allow_drafts=drafts,
                           case_field=kw.pop("case_field", "cf_desk_case"))
    return zoho.Writer(creds(base, True), pol, hub_dir=hub, state_dir=hub / ".z")


def test_reader_never_writes(hub, fake):
    f, base = fake
    r = zoho.Reader(creds(base), state_dir=hub / ".z")
    t = f.add_ticket(subject="Order", text="Where is HF-7001?", email="purchasing@harbor-foods.example", notify=False)
    assert r.ticket(t["id"])["subject"] == "Order"
    with pytest.raises(zoho.WriteRefused):
        r._request("POST", f"/tickets/{t['id']}/sendReply", body={"content": "x"})
    assert f.writes == []


def test_writer_reaches_only_its_endpoints(hub, fake):
    f, base = fake
    t = f.add_ticket(subject="Order", text="Hi", email="purchasing@harbor-foods.example", notify=False)
    w = writer(hub, base)
    mark = zoho.marker(t["id"], "k")
    w.associate_tags(t["id"], ["desk-order-status"])
    w.private_note(t["id"], f"Facts...\n{mark}")
    w.set_case_field(t["id"], "CD-000001")
    w.draft_reply(t["id"], from_address="support@desk.example", to="purchasing@harbor-foods.example",
                  html=desk.draft_html("Hello", mark), in_reply_to=None)
    assert f.tags[t["id"]] == {"desk-order-status"}
    assert f.comments[t["id"]][0]["isPublic"] is False
    assert f.tickets[t["id"]]["cf"] == {"cf_desk_case": "CD-000001"}
    assert len(f.drafts(t["id"])) == 1
    for method, path, body in (
            ("POST", f"/tickets/{t['id']}/sendReply", {"channel": "EMAIL", "content": "x"}),
            ("PATCH", f"/tickets/{t['id']}", {"status": "Closed"}),
            ("PATCH", f"/tickets/{t['id']}", {"assigneeId": "1"}),
            ("PATCH", f"/tickets/{t['id']}", {"cf": {"cf_other": "x"}}),
            ("POST", f"/tickets/{t['id']}/associateTag", {"tags": ["vip"]}),
            ("POST", f"/tickets/{t['id']}/comments", {"isPublic": True, "contentType": "plainText", "content": mark}),
            ("POST", f"/tickets/{t['id']}/comments", {"isPublic": False, "contentType": "plainText", "content": "no mark"}),
            ("POST", f"/tickets/{t['id']}/draftReply", {"channel": "EMAIL", "content": "no marker",
                                                        "fromEmailAddress": "s@x.example"}),
            ("DELETE", f"/tickets/{t['id']}", None)):
        with pytest.raises(zoho.WriteRefused):
            w._request(method, path, body=body, retry=False)
    assert f.forbidden == []          # nothing outside the five endpoints ever left


def test_stop_switch_is_read_at_write_time(hub, fake, monkeypatch):
    f, base = fake
    t = f.add_ticket(subject="Order", text="Hi", email="purchasing@harbor-foods.example", notify=False)
    w = writer(hub, base)
    (store.db_path(hub).parent / "STOP_WRITES").write_text("stop")
    with pytest.raises(zoho.WritesBlocked):
        w.associate_tags(t["id"], ["desk-complaint"])
    (store.db_path(hub).parent / "STOP_WRITES").unlink()
    monkeypatch.setenv("DESK_STOP_WRITES", "1")
    with pytest.raises(zoho.WritesBlocked):
        w.associate_tags(t["id"], ["desk-complaint"])
    monkeypatch.delenv("DESK_STOP_WRITES")
    w.associate_tags(t["id"], ["desk-complaint"])
    assert f.tags[t["id"]] == {"desk-complaint"}


def test_shadow_mode_prefixes_tags_and_refuses_notes_and_drafts(hub, fake):
    f, base = fake
    t = f.add_ticket(subject="Order", text="Hi", email="purchasing@harbor-foods.example", notify=False)
    w = writer(hub, base, mode="shadow", drafts=False)
    with pytest.raises(zoho.WriteRefused):
        w.associate_tags(t["id"], ["desk-complaint"])
    w.associate_tags(t["id"], ["shadow-desk-complaint"])
    with pytest.raises(zoho.WriteRefused):
        w.private_note(t["id"], zoho.marker(t["id"], "k"))
    assert f.tags[t["id"]] == {"shadow-desk-complaint"}


def test_draft_preflight_rereads_the_ticket(hub, fake):
    f, base = fake
    t = f.add_ticket(subject="Order", text="Where is it?", email="purchasing@harbor-foods.example", notify=False)
    r = zoho.Reader(creds(base), state_dir=hub / ".z")
    inbound = desk.latest_inbound(r.threads(t["id"]))
    mark = zoho.marker(t["id"], "k1")
    assert desk.preflight_draft(r, t["id"], inbound["id"], mark) == ("write", None)
    f.customer_reply(t["id"], "Also, any news?", notify=False)
    assert desk.preflight_draft(r, t["id"], inbound["id"], mark)[0] == "newer_message"
    inbound = desk.latest_inbound(r.threads(t["id"]))
    f._thread(t["id"], direction="out", text="An agent answered", sender="agent@desk.example")
    assert desk.preflight_draft(r, t["id"], inbound["id"], mark)[0] == "answered"
    t2 = f.add_ticket(subject="Two", text="Hello", email="orders@alpine-hardware.example", notify=False)
    in2 = desk.latest_inbound(r.threads(t2["id"]))
    f._thread(t2["id"], direction="out", text="someone's draft", sender="x@desk.example", status="DRAFT")
    assert desk.preflight_draft(r, t2["id"], in2["id"], zoho.marker(t2["id"], "k"))[0] == "other_draft"
    f.tickets[t2["id"]]["statusType"] = "Closed"
    assert desk.preflight_draft(r, t2["id"], in2["id"], zoho.marker(t2["id"], "k"))[0] == "closed"


def test_own_writes_do_not_loop(hub, fake):
    f, base = fake
    t = f.add_ticket(subject="Order", text="Where is it?", email="purchasing@harbor-foods.example", notify=False)
    r = zoho.Reader(creds(base), state_dir=hub / ".z")
    got = desk.read_ticket(r, t["id"])
    assert desk.claim_message(hub, got["ticket"], str(got["inbound"]["id"])) is True
    writer(hub, base).associate_tags(t["id"], ["desk-order-status"])      # changes modifiedTime
    again = desk.read_ticket(r, t["id"])
    assert desk.claim_message(hub, again["ticket"], str(again["inbound"]["id"])) is False
    f.customer_reply(t["id"], "Hello again", notify=False)
    third = desk.read_ticket(r, t["id"])
    assert desk.claim_message(hub, third["ticket"], str(third["inbound"]["id"])) is True


def test_token_refresh_on_401_and_retry_on_503(hub, fake):
    f, base = fake
    t = f.add_ticket(subject="Order", text="Hi", email="purchasing@harbor-foods.example", notify=False)
    r = zoho.Reader(creds(base), state_dir=hub / ".z")
    r.ticket(t["id"])
    f.tokens.clear()                     # the cached token is no longer valid
    assert r.ticket(t["id"])["id"] == t["id"]
    f.fail("GET", r"/tickets/\d+$", 503, times=2)
    assert r.ticket(t["id"])["id"] == t["id"]


def test_webhook_body_only_names_a_ticket():
    from customer_desk.intake_poll import ticket_id_from

    assert ticket_id_from({"ticketId": "10001", "event": "x"}) == "10001"
    assert ticket_id_from('[{"payload": {"id": "10002", "ticketNumber": "102"}}]') == "10002"
    assert ticket_id_from({"ticketId": "../../etc"}) is None
    assert ticket_id_from({"subject": "no id"}) is None


def test_mode_is_read_at_write_time(hub, fake):
    f, base = fake
    t = f.add_ticket(subject="Order", text="Hi", email="purchasing@harbor-foods.example", notify=False)
    w = writer(hub, base)                       # made while the hub is live with drafts
    set_mode(hub, "dry-run")                    # switched while a triage runs
    with pytest.raises(zoho.WritesBlocked):
        w.associate_tags(t["id"], ["desk-order-status"])
    set_mode(hub, "live", drafts=False)         # drafts switched off
    with pytest.raises(zoho.WriteRefused):
        w.draft_reply(t["id"], from_address="support@desk.example", to="purchasing@harbor-foods.example",
                      html=desk.draft_html("Hello", zoho.marker(t["id"], "k")), in_reply_to=None)
    assert f.drafts(t["id"]) == [] and f.tags.get(t["id"], set()) == set()


def test_a_write_refreshes_a_revoked_token_once(hub, fake):
    f, base = fake
    t = f.add_ticket(subject="Order", text="Hi", email="purchasing@harbor-foods.example", notify=False)
    w = writer(hub, base)
    w.associate_tags(t["id"], ["desk-order-status"])
    f.tokens.clear()                            # the cached token was revoked
    w.associate_tags(t["id"], ["desk-order-status", "desk-low-confidence"])
    assert f.tags[t["id"]] == {"desk-order-status", "desk-low-confidence"}


def test_draft_html_renders_statement_tables_and_escapes_values():
    mark = zoho.marker("1", "k")
    out = desk.draft_html("Hello,\n\n| Invoice | Outstanding |\n|---|---|\n| ACC-SINV-2000-00001 | $1,250.00 <x> |\n\n"
                          "- one\n- two\n\nKind regards,\nDesk", mark)
    assert "<table" in out and "<td>ACC-SINV-2000-00001</td>" in out and "&lt;x&gt;" in out
    assert "<ul><li>one</li><li>two</li></ul>" in out and "<p>Kind regards,<br>Desk</p>" in out
    assert zoho.MARKER_RE.search(out) and "|---" not in out


def test_note_carries_the_new_reply_when_an_older_desk_draft_blocks_it():
    view = {"case": {"number": "CD-000016", "state": "needs_owner", "queue": "delivery", "customer_id": "SYN-CUST-001"},
            "resolution": {"requests": []}, "facts": [], "tickets": [],
            "reply": {"revision": 2, "rendered": "Order HF-7001 is now due on January 27, 2000.",
                      "checks": {"results": [{"id": "limits", "status": "pass"}]}}}
    mark = zoho.marker("10002", "c:2")
    plain = desk.note_for(view, mark)
    assert "January 27" not in plain
    note = desk.note_for(view, mark, replace_draft=True)
    assert "Replace that draft's text" in note and "January 27, 2000" in note and zoho.MARKER_RE.search(note)
