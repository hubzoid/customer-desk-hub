"""Sender binding and party scope: no customer data before an exact binding,
foreign records read as not_found, the model never picks the customer."""
from __future__ import annotations

import pytest

from conftest import LocalRunner, dataset_file, envelope, triage_envelope
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
    erp_config.sample_edit(hub, "customers", "SYN-CUST-004", "disabled", 1)
    erp = erp_config.backend(hub)
    ctx = ERPContext(hub_id="h", company=CO)

    def lookup(cid):
        try:
            return erp.get_record("customers", cid, ctx)
        except ERPError:
            return None

    text = dataset_file(hub, "bindings.csv").read_text() + f"{CO},email,new.buyer@unknown-co.example,Customer,SYN-CUST-099,\n"
    plan = bindings.plan_import(store.connect(hub), text, company=CO, customer_lookup=lookup)
    assert len(plan["adds"]) == 6                                   # Harbor Foods, Alpine Hardware, Prairie Clinics
    assert [c["reason"] for c in plan["conflicts"]] == ["Customer SYN-CUST-004 is disabled in ERPNext."] * 2 + [
        "ERPNext has no customer SYN-CUST-099 for this company."]
    assert len(plan["rejects"]) == 6                                # the supplier rows belong to the Order desk
    assert all("not customers" in r["reason"] for r in plan["rejects"])
    assert bindings.list_bindings(store.connect(hub)) == []


def test_unbound_sender_reads_nothing(hub):
    env = envelope(hub, "CD-A01")
    runner = LocalRunner(hub)
    opened, result, _ = triage_envelope(hub, env, runner)
    assert result["state"] == "binding_required"
    assert runner.stations.calls == []          # no model saw it
    conn = store.connect(hub)
    case = store.get_case(conn, opened["case_id"])
    assert case["customer_id"] is None and store.get_facts(conn, case["id"], 1) == []
    assert case["queue"] == "bindings"


def test_binding_admin_binds_then_desk_reads(bound):
    env = envelope(bound, "CD-A01")
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
        actions.bind_case(bound, opened["number"], admin, "SYN-CUST-099", start=start)
    assert exc.value.code == "binding_conflict"
    erp_config.sample_edit(bound, "customers", "SYN-CUST-004", "disabled", 1)
    with pytest.raises(actions.ActionError) as exc:
        actions.bind_case(bound, opened["number"], admin, "SYN-CUST-004", start=start)
    assert exc.value.code == "binding_conflict" and "disabled" in exc.value.message
    out = actions.bind_case(bound, opened["number"], admin, "SYN-CUST-001", start=start)
    assert out["customer"] == "SYN-CUST-001" and started[0][1]["input"]["kind"] == "bound"
    result = pipeline.triage(bound, opened["case_id"], LocalRunner(bound), trigger="bound")
    assert result["state"] == "needs_owner"


def test_party_scope_returns_not_found_for_foreign_records(hub):
    erp = erp_config.backend(hub)
    mine = ERPContext(hub_id="h", company=CO, party_scope="SYN-CUST-001")
    assert erp.get_record("sales_orders", "SAL-ORD-2000-00001", mine)["id"] == "SAL-ORD-2000-00001"
    for resource, rid, missing in (("sales_orders", "SAL-ORD-2000-00003", "SAL-ORD-2000-09999"),
                                   ("sales_invoices", "ACC-SINV-2000-00002", "ACC-SINV-2000-09999"),
                                   ("customers", "SYN-CUST-002", "SYN-CUST-999")):
        with pytest.raises(ERPError) as exc:
            erp.get_record(resource, rid, mine)
        assert exc.value.code == "not_found"
        with pytest.raises(ERPError) as exc2:
            erp.get_record(resource, missing, mine)
        # A foreign record and a missing one read the same, so existence never leaks.
        assert exc2.value.code == "not_found"
        assert exc.value.message.replace(rid, "X") == exc2.value.message.replace(missing, "X")
    rows = erp.list_records("sales_invoices", {"limit": 50}, mine)
    assert {r["fields"]["customer"] for r in rows} == {"SYN-CUST-001"}
    prices = erp.list_records("prices", {"item_codes": ["SYN-ITEM-009"]}, mine)
    assert prices and all(p["fields"].get("customer") in (None, "", "SYN-CUST-001") for p in prices)
    assert "SYN-IP-0024" not in {p["id"] for p in prices}           # Alpine Hardware's contract price


def test_foreign_order_answers_not_found_without_details(bound):
    opened, _, _ = triage_envelope(bound, envelope(bound, "CD-A02"))  # Alpine Hardware asks for Harbor Foods' invoice
    conn = store.connect(bound)
    case = store.get_case(conn, opened["case_id"])
    assert case["customer_id"] == "SYN-CUST-002"
    facts = store.get_facts(conn, case["id"], case["current_resolution"])
    assert all(f["source"].get("party") in (None, "SYN-CUST-002") for f in facts)
    reply = store.get_reply(conn, case["id"], case["current_reply"]) if case["current_reply"] else None
    text = (reply or {}).get("rendered") or ""
    assert "Harbor" not in text and "299.40" not in text and "HF-7002" not in text
    assert not (reply or {}).get("attachments")                     # no copy of the foreign invoice


def test_desk_never_mounts_erp_write_tools(hub):
    """The vendored backends keep their insert and submit methods (the files are
    byte-equal to the Order desk's). The desk never reaches them: DeskERP has
    read methods only, no desk code calls insert, submit or an ERP writer or
    imports erp.write, the ERP package sends no POST, PUT or PATCH, and no tool
    the hub mounts starts with erp_."""
    import ast
    import inspect

    from conftest import HUB
    from customer_desk.erpnext.adapter import DeskERP

    public = {n for n, _ in inspect.getmembers(DeskERP, inspect.isfunction) if not n.startswith("_")}
    assert public == {"doctor", "get_print_pdf", "get_record", "list_records", "reader_context", "shape"}
    desk = HUB / "workflows" / "lib" / "customer_desk"
    for path in desk.rglob("*.py"):
        in_erp = path.parent.name == "erpnext"
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                attr, owner = node.func.attr, node.func.value
                where = f"{path.name}:{node.lineno} calls .{attr}()"
                assert attr not in {"insert", "submit", "create_draft", "submit_draft", "submit_approved"}, where
                if attr == "writer":
                    assert isinstance(owner, ast.Name) and owner.id == "csv", where
                if in_erp:
                    assert attr not in {"post", "put", "patch", "delete"}, where
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                mods = [a.name for a in node.names] + [getattr(node, "module", None) or ""]
                assert not any(m in ("erp.write", "erp.digest", "erp.bootstrap") for m in mods), path
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
