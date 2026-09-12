"""The desk on Hubzoid's own email channel, on the real engine: a signed message
from a bound sender becomes a case, an unknown sender waits in intake until a
person releases it, and an approved reply goes back on the same thread to the
sender only. Fake IMAP and SMTP, as in the SDK's own channel tests."""
from __future__ import annotations

import base64
import json
import time
from email.message import EmailMessage
from pathlib import Path

import dkim
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from engine import OWNER, Engine, wait_case, wait_item, waiting_op

pytestmark = pytest.mark.engine

MAILBOX = "care@synthetic-meridian.example"
BOUND = "accounts@synthetic-harbor.example"
KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
PRIV = KEY.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.TraditionalOpenSSL,
                         serialization.NoEncryption())
PUB = base64.b64encode(KEY.public_key().public_bytes(serialization.Encoding.DER,
                                                     serialization.PublicFormat.SubjectPublicKeyInfo)).decode()


def dns(name, timeout=5):
    if name in (b"sel._domainkey.synthetic-harbor.example.",):
        return f"v=DKIM1; k=rsa; p={PUB}".encode()
    return b""


def message(sender, subject, body, msgid):
    m = EmailMessage()
    m["From"] = f"Synthetic Harbor Accounts <{sender}>"
    m["To"] = MAILBOX
    m["Subject"] = subject
    m["Message-ID"] = msgid
    m["Date"] = "Sat, 15 Jan 2000 09:00:00 +0000"
    m.set_content(body)
    raw = bytes(m)
    domain = sender.rpartition("@")[2].encode()
    if domain == b"synthetic-harbor.example":
        raw = dkim.sign(raw, b"sel", domain, PRIV, include_headers=[b"from", b"subject", b"to", b"date"]) + raw
    return raw


@pytest.fixture
def channel(bound, monkeypatch, tmp_path):
    from hubzoid.access import store_for
    from hubzoid.channels import config
    from hubzoid.channels.email import mime

    monkeypatch.setattr(mime, "verify_dkim", lambda raw, sender, dnsfunc=None, _real=mime.verify_dkim:
                        _real(raw, sender, dnsfunc=dnsfunc or dns))
    monkeypatch.setenv("DESK_TEST_MAILBOX_PASSWORD", "imap-test-value")   # gitleaks:allow (a test value)
    monkeypatch.setenv("DESK_TEST_FAKE_MAIL", str(tmp_path / "mail"))
    path = bound / "hub.settings.yaml"
    path.write_text(path.read_text().replace("DESK_EXTERNAL_CHANNELS: [sample-email, sample-whatsapp]",
                                             "DESK_EXTERNAL_CHANNELS: [sample-email, sample-whatsapp, care-email]"))
    (bound / "work-items.yaml").write_text("version: 1\nwrite_modes:\n  customer_reply.send: approve\n"
                                           "  email.send: approve\n")
    tls = {"port": 993, "tls": "implicit", "username": MAILBOX, "password_ref": "env:DESK_TEST_MAILBOX_PASSWORD"}
    doc = {"version": 1, "id": "care-email", "provider": "email", "enabled": True, "workflow": "customer_desk_intake",
           "run_as": "workflow", "provider_config": {
               "transport": "imap", "mailbox": MAILBOX, "imap": {"host": "imap.synthetic-meridian.example", **tls},
               "smtp": {"host": "smtp.synthetic-meridian.example", **tls, "port": 465},
               "sender_policy": {"allowed": [BOUND]}}}
    v = config.load_text(bound, config.render(doc))
    assert v.valid, v.errors
    config.apply(bound, v.data, expected_revision="absent", actor="test")
    store_for(bound).grant(OWNER, bound.name.lower(), "workflows_manage", actor="test")
    return bound, config.active(bound, "care-email"), tmp_path / "mail"


def route(hub):
    from hubzoid.channels import router, store

    for row in store.open_deliveries(hub, hub.name.lower()):
        router._route_one(hub, row, None)


def test_bound_sender_becomes_a_case_and_the_approved_reply_goes_back_on_the_thread(channel, tmp_path):
    from hubzoid.channels.email import poller
    from hubzoid.intake import service as intake
    from hubzoid.work_items import service as wi

    from customer_desk import actions, store
    from customer_desk.flows import start_work

    hub, conn, mail = channel
    engine = Engine(hub, tmp_path)
    try:
        poller.process(conn, {"id": "1", "raw": message(BOUND, "Invoice copy", "Please send a copy of invoice "
                                                      "SYN-SINV-0002.", "<inv-1@synthetic-harbor.example>")})
        route(hub)
        [item] = intake.list_items(hub)["items"]
        assert item["state"] == "dispatched"
        deadline = time.time() + 120
        case = None
        while time.time() < deadline and case is None:
            row = store.connect(hub).execute("SELECT number FROM cases WHERE intake_id=?", (item["id"],)).fetchone()
            case = row and wait_case(hub, row["number"], ("needs_owner",))
            time.sleep(0.5)
        assert case["channel_id"] == "care-email" and case["customer_id"] == "SYN-CUST-001"
        assert case["origin"]["surface"] == "channel"
        owner = actions.Actor(OWNER, lambda r: True)
        actions.claim(hub, case["number"], owner)
        reply = store.get_reply(store.connect(hub), case["id"], case["current_reply"])
        assert reply["attachments"]                         # the invoice PDF
        with pytest.raises(actions.ActionError) as exc:      # Hubzoid channel replies carry text only
            actions.request_send(hub, case["number"], owner, reply_revision=reply["revision"],
                                 digest=reply["digest"], expected_revision=None, start=start_work(hub))
        assert exc.value.code == "attachments_unsupported"
        edited = actions.edit_reply(hub, case["number"], owner, "Hello, invoice [[F2]] is on its way by post.",
                                    keep_attachments=False)
        c = store.get_case(store.connect(hub), case["id"])
        r2 = store.get_reply(store.connect(hub), c["id"], c["current_reply"])
        out = actions.request_send(hub, case["number"], owner, reply_revision=r2["revision"], digest=r2["digest"],
                                   expected_revision=None, start=start_work(hub))
        op = waiting_op(hub, out["work_item_id"])
        assert not list(mail.glob("sent-*.json")) if mail.exists() else True
        wi.approve(hub, op["id"], OWNER, digest=op["args_digest"])
        wait_item(hub, out["work_item_id"], ("completed",))
        sent = [json.loads(p.read_text()) for p in sorted(mail.glob("sent-*.json"))]
        assert len(sent) == 1 and sent[0]["to"] == [BOUND]
        assert "In-Reply-To: <inv-1@synthetic-harbor.example>" in sent[0]["raw"]
        assert "SYN-SINV-0002" in sent[0]["raw"]
        assert edited["typed_by_person"] == []
    finally:
        engine.close()


def test_unknown_sender_waits_in_intake_until_a_person_releases_it(channel, tmp_path):
    from hubzoid.channels.email import poller
    from hubzoid.intake import service as intake

    from customer_desk import actions, store

    hub, conn, mail = channel
    engine = Engine(hub, tmp_path)
    try:
        poller.process(conn, {"id": "2", "raw": message("stranger@synthetic-other.example", "Order",
                                                      "Where is order SYN-SO-0001?", "<s-1@synthetic-other.example>")})
        route(hub)
        [item] = intake.list_items(hub)["items"]
        assert item["state"] == "quarantined" and not item.get("work_item_id")
        assert store.connect(hub).execute("SELECT COUNT(*) AS n FROM cases").fetchone()["n"] == 0   # no case, no model
        actions.bind_sender(hub, actions.Actor(OWNER, lambda r: True), channel_kind="email",
                            sender="stranger@synthetic-other.example", customer_id="SYN-CUST-001")
        out = intake.release(hub, item["id"], actor=OWNER, reason="New buyer, bound to SYN-CUST-001",
                             expected_revision=item["revision"])
        assert out["state"] == "dispatched"
        deadline = time.time() + 120
        while time.time() < deadline:
            row = store.connect(hub).execute("SELECT number FROM cases WHERE intake_id=?", (item["id"],)).fetchone()
            if row:
                c = wait_case(hub, row["number"], ("needs_owner",))
                assert c["customer_id"] == "SYN-CUST-001"
                return
            time.sleep(0.5)
        raise AssertionError("the released message did not become a case")
    finally:
        engine.close()
