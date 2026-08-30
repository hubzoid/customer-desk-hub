"""Sender binding and party scope: no customer data before an exact binding,
foreign records read as not_found, the model never picks the customer."""
from __future__ import annotations

import pytest

from conftest import LocalRunner, load_sample, triage_envelope
from customer_desk import actions, bindings, cases, envelopes, pipeline, store
from customer_desk.erpnext import config as erp_config
from customer_desk.erpnext.contract import ERPContext, ERPError

CO = "Synthetic Meridian Distribution"


def test_sender_key_normalisation():
    assert bindings.sender_key("email", "Buyer <Buyer.One@SYNTHETIC-Harbor.example>") == "Buyer.One@synthetic-harbor.example"
    assert bindings.sender_key("whatsapp", "+1 555 010 0102") == "+15550100102"
    with pytest.raises(bindings.BindingError):
        bindings.sender_key("email", "not an address")


def test_binding_exact_ambiguous_revoked(hub):
    with store.tx(hub) as conn:
        a = bindings.add(conn, company=CO, channel_kind="email", sender="x@synthetic-a.example",
                         customer_id="SYN-CUST-001", actor="t")
    conn = store.connect(hub)
    found, cands = bindings.resolve(conn, CO, "email", "x@synthetic-a.example")
    assert found["customer_id"] == "SYN-CUST-001" and cands == ["SYN-CUST-001"]
    with store.tx(hub) as conn:
        bindings.add(conn, company=CO, channel_kind="email", sender="x@synthetic-a.example",
                     customer_id="SYN-CUST-002", actor="t")
    found, cands = bindings.resolve(store.connect(hub), CO, "email", "x@synthetic-a.example")
    assert found is None and cands == ["SYN-CUST-001", "SYN-CUST-002"]
    with store.tx(hub) as conn:
        bindings.revoke(conn, a["id"], actor="t")
    found, _ = bindings.resolve(store.connect(hub), CO, "email", "x@synthetic-a.example")
    assert found["customer_id"] == "SYN-CUST-002"


def test_import_plans_conflicts_without_writing(hub):
    erp = erp_config.backend(hub)
    ctx = ERPContext(hub_id="h", company=CO)

    def lookup(cid):
        try:
            return erp.get_record("customers", cid, ctx)
        except ERPError:
            return None

    plan = bindings.plan_import(store.connect(hub), (hub / "fixtures" / "bindings.csv").read_text(), company=CO,
                                customer_lookup=lookup)
    assert len(plan["adds"]) == 6
    assert [c["reason"] for c in plan["conflicts"]] == ["Customer SYN-CUST-004 is disabled in ERPNext."]
    assert bindings.list_bindings(store.connect(hub)) == []


def test_unbound_sender_reads_nothing(hub):
    env = load_sample(hub, "fixtures/intake/unknown-sender.jsonl")[0]
    runner = LocalRunner(hub)
    opened, result, _ = triage_envelope(hub, env, runner)
    assert result["state"] == "binding_required"
    assert runner.stations.calls == []          # no model saw it
    conn = store.connect(hub)
    case = store.get_case(conn, opened["case_id"])
    assert case["customer_id"] is None and store.get_facts(conn, case["id"], 1) == []
    assert case["queue"] == "bindings"


def test_binding_admin_binds_then_desk_reads(bound):
    env = load_sample(bound, "fixtures/intake/unknown-sender.jsonl")[0]
    opened, _, _ = triage_envelope(bound, env)
    started = []

    def start(workflow, **kw):
        started.append((workflow, kw))
        return {"id": "item-1"}

    admin = actions.Actor("binder@desk.example", lambda r: r == "desk_bindings")
    with pytest.raises(actions.ActionError) as exc:
        actions.bind_case(bound, opened["number"], actions.Actor("op@desk.example", lambda r: r == "desk_operator"),
                          "SYN-CUST-001", start=start)
    assert exc.value.code == "permission_denied"
    with pytest.raises(actions.ActionError) as exc:
        actions.bind_case(bound, opened["number"], admin, "SYN-CUST-004", start=start)
    assert exc.value.code == "binding_conflict"
    out = actions.bind_case(bound, opened["number"], admin, "SYN-CUST-001", start=start)
    assert out["customer"] == "SYN-CUST-001" and started[0][1]["input"]["kind"] == "bound"
    result = pipeline.triage(bound, opened["case_id"], LocalRunner(bound), trigger="bound")
    assert result["state"] == "needs_owner"


def test_party_scope_returns_not_found_for_foreign_records(hub):
    erp = erp_config.backend(hub)
    mine = ERPContext(hub_id="h", company=CO, party_scope="SYN-CUST-001")
    assert erp.get_record("sales_orders", "SYN-SO-0001", mine)["id"] == "SYN-SO-0001"
    for resource, rid in (("sales_orders", "SYN-SO-0004"), ("sales_invoices", "SYN-SINV-0004"),
                          ("customers", "SYN-CUST-002")):
        with pytest.raises(ERPError) as exc:
            erp.get_record(resource, rid, mine)
        assert exc.value.code == "not_found"
        with pytest.raises(ERPError) as exc2:
            erp.get_record(resource, "SYN-NOPE-9999", mine)
        # A foreign record and a missing one read the same, so existence never leaks.
        assert exc.value.message.replace(rid, "X") == exc2.value.message.replace("SYN-NOPE-9999", "X")
    rows = erp.list_records("sales_invoices", {"limit": 50}, mine)
    assert {r["fields"]["customer"] for r in rows} == {"SYN-CUST-001"}
    prices = erp.list_records("prices", {"item_codes": ["SYN-ITEM-007"]}, mine)
    assert all(p["fields"]["customer"] in (None, "SYN-CUST-001") for p in prices)


def test_foreign_order_answers_not_found_without_details(bound):
    env = [e for e in load_sample(bound) if e["provider_event_id"] == "syn-006"][0]
    opened, _, _ = triage_envelope(bound, env)
    conn = store.connect(bound)
    case = store.get_case(conn, opened["case_id"])
    reply = store.get_reply(conn, case["id"], case["current_reply"])
    facts = store.get_facts(conn, case["id"], case["current_resolution"])
    assert all(f["source"].get("party") in (None, "SYN-CUST-001") for f in facts)
    assert "Lakeside" not in reply["rendered"] and "January 22" not in reply["rendered"]


def test_desk_never_mounts_erp_write_tools(hub):
    import ast

    from conftest import HUB

    erp_dir = HUB / "workflows" / "lib" / "customer_desk" / "erpnext"
    for path in erp_dir.glob("*.py"):
        tree = ast.parse(path.read_text())
        names = {n.name for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
        assert not names & {"create_draft", "submit_draft", "submit_approved", "update", "delete", "post"}, path
    source = (erp_dir / "frappe_rest.py").read_text()
    assert ".post(" not in source and ".put(" not in source and ".delete(" not in source
    from hubzoid.loaders import tools_local

    names = set(tools_local.load_all(HUB))
    assert not any(n.startswith("erp_") for n in names)


def test_doctor_refuses_writes_enabled(hub):
    import sys

    sys.path.insert(0, str(hub))
    path = hub / "connectors" / "erpnext.yaml"
    path.write_text(path.read_text().replace("writes_enabled: false", "writes_enabled: true"))
    from conftest import HUB
    import importlib.util

    spec = importlib.util.spec_from_file_location("desk_checks", HUB / "doctor" / "checks.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    out = mod.erp_read_only({"hub_dir": str(hub), "settings": {}})
    assert out["status"] == "fail" and "erp_not_read_only" in out["summary"]
    with pytest.raises(ERPError) as exc:
        erp_config.load(hub)
    assert exc.value.code == "erp_not_read_only"
