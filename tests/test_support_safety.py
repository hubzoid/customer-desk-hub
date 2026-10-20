"""Regression checks for ACL sweeps, source retrieval and optional-ERP setup."""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text

from customer_desk import config, flows, recheck, store
from customer_desk.helpdesk import retrieval
from test_support import configure, open_support


def test_acl_refresh_retires_all_stale_copies_and_drains_past_100(hub, monkeypatch):
    from hubzoid import artifacts

    configure(hub)
    engine = create_engine("sqlite://")
    with engine.begin() as db:
        db.execute(text("CREATE TABLE hz_artifacts(id TEXT, hub TEXT, latest_key TEXT, deleted REAL)"))
    monkeypatch.setattr(artifacts, "_engine", lambda _: engine)
    monkeypatch.setattr(flows, "page_readers", lambda *a: ["new@example.test"])
    ids = []
    for n in range(105):
        opened = open_support(hub, event=f"acl-{n}")
        ids.append(opened["case_id"])
        with store.tx(hub) as conn:
            store.update_case(conn, opened["case_id"], page_url=f"/portal/case-{n}")
            conn.execute("UPDATE cases SET page_readers=? WHERE id=?", ("old@example.test", opened["case_id"]))
        with engine.begin() as db:
            db.execute(text("INSERT INTO hz_artifacts VALUES(:id,:hub,:key,NULL)"),
                       {"id": str(n), "hub": hub.name.lower(), "key": f"case-{opened['number'].lower()}"})
    # Reproduce the old global-cursor trap: a refreshed case already wrote
    # current readers, even while another 104 cases retain old ACLs.
    with store.tx(hub) as conn:
        conn.execute("INSERT INTO cursor VALUES('page_readers','new@example.test')")
    queued = []

    def start(_workflow, **kw):
        queued.append(kw["input"]["case_id"])
        return {"id": "queued"}

    assert flows.refresh_pages_if_readers_changed(hub, start, limit=100) == 100
    with engine.connect() as db:
        assert db.execute(text("SELECT COUNT(*) FROM hz_artifacts WHERE deleted IS NULL")).scalar() == 0
    first = list(queued)
    with store.tx(hub) as conn:
        for case_id in first:
            conn.execute("UPDATE cases SET page_readers='new@example.test' WHERE id=?", (case_id,))
    queued.clear()
    assert flows.refresh_pages_if_readers_changed(hub, start, limit=100) == 5
    assert set(queued).isdisjoint(first)
    assert set(first + queued) == set(ids)


def test_acl_grant_revoke_restore_republishes_with_fresh_generation(hub, monkeypatch, tmp_path):
    from types import SimpleNamespace

    import hubzoid
    from hubzoid import artifacts, assertions

    configure(hub)
    opened = open_support(hub, event="acl-cycle")
    case_id = opened["case_id"]
    engine = create_engine("sqlite://")
    with engine.begin() as db:
        db.execute(text("CREATE TABLE hz_artifacts(id TEXT, hub TEXT, latest_key TEXT, deleted REAL)"))
        db.execute(text("INSERT INTO hz_artifacts VALUES('unrelated','another-hub',:key,NULL)"),
                   {"key": f"case-{opened['number'].lower()}"})
    monkeypatch.setattr(artifacts, "_engine", lambda _: engine)
    monkeypatch.setattr(assertions, "hub_key", lambda _: "different-folder-key")
    readers = ["owner@example.test"]
    def current_readers(_hub_dir, name):
        assert name == "canonical-desk"  # actual runtime identity wins over folder key
        return list(readers)
    monkeypatch.setattr(flows, "page_readers", current_readers)
    monkeypatch.setattr(flows, "_prune_older_pages", lambda *a: None)
    digests = []
    fail_next = []

    def publish(_path, **kw):
        if fail_next:
            fail_next.pop()
            raise RuntimeError("synthetic publication outage")
        digests.append(kw["digest"])
        ident = f"page-{len(digests)}"
        with engine.begin() as db:
            db.execute(text("INSERT INTO hz_artifacts VALUES(:id,'canonical-desk',:key,NULL)"),
                       {"id": ident, "key": kw["key"]})
        return {"id": ident, "latest_url": "/portal/latest/canonical-desk/case"}

    monkeypatch.setattr(hubzoid, "hub", SimpleNamespace(name="canonical-desk", run_dir=tmp_path,
                                                       publish_artifact=publish))
    assert flows.publish_case_page(hub, case_id)["id"] == "page-1"
    completed = set()

    def start(_workflow, **kw):
        # The work service returns an existing completed item for a repeated key.
        if kw["key"] not in completed:
            flows.publish_case_page(hub, kw["input"]["case_id"])
            completed.add(kw["key"])
        return {"id": kw["key"]}

    readers.append("teammate@example.test")
    fail_next.append(True)
    assert flows.refresh_pages_if_readers_changed(hub, start) == 1
    with engine.connect() as db:
        assert db.execute(text("SELECT COUNT(*) FROM hz_artifacts WHERE hub='canonical-desk' AND deleted IS NULL")).scalar() == 0
    for desired in (["owner@example.test", "teammate@example.test"],
                    ["owner@example.test"],
                    ["owner@example.test", "teammate@example.test"]):
        readers[:] = desired
        assert flows.refresh_pages_if_readers_changed(hub, start) == 1
        with engine.connect() as db:
            live = db.execute(text("SELECT id FROM hz_artifacts WHERE hub='canonical-desk' AND deleted IS NULL")).all()
            assert live == [(f"page-{len(digests)}",)]
            assert db.execute(text("SELECT deleted FROM hz_artifacts WHERE id='unrelated'")).scalar() is None
    assert len(completed) == 4 and len(set(digests)) == 4
    with store.tx(hub) as conn:
        row = conn.execute("SELECT page_readers,page_generation FROM cases WHERE id=?", (case_id,)).fetchone()
    assert row["page_readers"] == ",".join(readers) and row["page_generation"] == 5


class History:
    def search_resolved(self, term, *, department_id):
        return [{"id": "2", "departmentId": "7", "statusType": "resolved", "subject": "Export reports"},
                {"id": "3", "departmentId": "8", "statusType": "resolved", "subject": "Export reports"},
                {"id": "4", "departmentId": "7", "statusType": "open", "subject": "Export reports"}]

    def ticket(self, ticket_id):
        assert ticket_id == "2"
        return {"id": "2", "departmentId": "7", "statusType": "resolved",
                "contact": {"firstName": "Private Name", "email": "private@example.test"}}

    def all_threads(self, ticket_id):
        assert ticket_id == "2"
        return [{"id": "a", "status": "SENT", "direction": "out", "createdTime": "2026-10-19"},
                {"id": "b", "status": "DRAFT", "direction": "out", "createdTime": "2026-10-20"}], True

    def thread(self, ticket_id, thread_id):
        assert ticket_id == "2" and thread_id == "a"
        return {"plainText": "Private Name, open the report menu and choose Export to download the visible columns.\nRegards\nPrivate Operator"}


def test_resolved_retrieval_enforces_department_human_sent_and_masks_names(hub):
    configure(hub, DESK_HELPDESK="freshdesk", FRESHDESK_GROUP_ID="7")
    got = retrieval.similar_resolved(History(), {"id": "1", "departmentId": "7"}, "export report", config.settings(hub))
    assert len(got["answers"]) == 1
    answer = got["answers"][0]
    assert answer["ref"] == "resolved:2:a" and answer["source_time"] == "2026-10-19"
    assert "Private Name" not in answer["text"] and "Private Operator" not in answer["text"]


def test_precedent_recheck_uses_identical_contact_masking(hub, monkeypatch):
    from customer_desk.helpdesk import desk

    configure(hub, DESK_HELPDESK="freshdesk", FRESHDESK_GROUP_ID="7")
    reader = History()
    answer = retrieval.similar_resolved(reader, {"id": "1", "departmentId": "7"}, "export report",
                                         config.settings(hub))["answers"][0]
    monkeypatch.setattr(desk, "readers", lambda *a: (reader, None))
    fact = {"fact_id": "S1", "source": {"backend": "support", **answer}}
    assert recheck.changed_facts(hub, {}, [fact]) == []
    monkeypatch.setattr(reader, "thread", lambda *a: {"plainText": "The answer has changed to different instructions."})
    assert recheck.changed_facts(hub, {}, [fact])[0]["now"] == "historical source unavailable/changed"


@pytest.mark.parametrize("change", [{"departmentId": "8"}, {"statusType": "open"},
                                   {"productId": "different"}, {"language": "fr"}])
def test_resolved_source_reread_rejects_stale_search_scope(hub, change):
    configure(hub, DESK_HELPDESK="freshdesk", FRESHDESK_GROUP_ID="7")
    class Moved(History):
        def ticket(self, ticket_id):
            return {**super().ticket(ticket_id), "productId": "p", **change}
        def search_resolved(self, *a, **kw):
            return [{**r, "productId": "p"} for r in super().search_resolved(*a, **kw)]
    got = retrieval.similar_resolved(Moved(), {"id": "1", "departmentId": "7", "productId": "p"},
                                     "export report", config.settings(hub))
    assert got["answers"] == []


def test_failed_history_search_is_distinct_from_no_match(hub):
    configure(hub)

    class Offline(History):
        def search_resolved(self, *a, **kw):
            raise RuntimeError("unavailable")

    got = retrieval.similar_resolved(Offline(), {"id": "1", "departmentId": "7"}, "export report", config.settings(hub))
    assert got["answers"] == [] and got["errors"]
    assert retrieval.similar_resolved(History(), {"id": "1"}, "export", config.settings(hub))["errors"] == ["history_scope_missing"]


def test_support_only_doctor_never_requires_or_initializes_erp(hub):
    configure(hub, DESK_MODE="live")
    (hub / "connectors/erpnext.yaml").unlink()
    spec = importlib.util.spec_from_file_location("support_doctor", hub / "doctor/checks.py")
    checks = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(checks)
    context = {"hub_dir": hub, "settings": config.settings(hub)}
    for name in ("erp_read_only", "erp_company", "erp_reads", "sample_data", "live_mode"):
        assert getattr(checks, name)(context)["status"] == "ok"
    assert not (hub / ".hubzoid/data/erp").exists()


def test_concurrent_first_erp_initialization_reads_one_revision(hub):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    from customer_desk.erpnext import config as erp_config

    barrier = Barrier(4)

    def first_read(_):
        barrier.wait(timeout=10)
        svc = erp_config.service(hub)
        return svc.deployment_id, svc.applied().revision

    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(first_read, range(4)))
    assert len({identity for identity, _ in results}) == 1
    assert {revision for _, revision in results} == {1}


def test_custom_data_root_requires_migrating_legacy_erp_identity(hub, tmp_path, monkeypatch):
    import shutil

    from erp.errors import ERPError
    from erp.service import ERPService

    original = ERPService.for_hub(hub)
    old_identity = original.deployment_id
    legacy = hub / ".hubzoid/data/erp"
    identity_bytes = (legacy / "deployment-id").read_bytes()
    data_root = tmp_path / "customer-runtime"
    target = data_root / ".hubzoid/data/erp"
    monkeypatch.setenv("HUBZOID_DATA_DIR", str(data_root))
    with pytest.raises(ERPError) as exc:
        ERPService.for_hub(hub)
    assert exc.value.code == "data_root_migration_required" and exc.value.status == 409
    assert not target.exists()  # guard runs before allocating a new identity
    assert (legacy / "deployment-id").read_bytes() == identity_bytes
    target.parent.mkdir(parents=True)
    shutil.move(str(legacy), str(target))  # reviewed migration of the entire existing store
    restored = ERPService.for_hub(hub)
    assert restored.deployment_id == old_identity
    assert (target / "deployment-id").read_bytes() == identity_bytes
