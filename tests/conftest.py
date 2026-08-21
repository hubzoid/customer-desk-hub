"""Shared test setup: a throwaway copy of this hub with its own desk store.

No model, no network and no engine: stations are the scripted stand-ins and
stages run inline. Engine and real-model runs are in tests/customer_eval.py.
"""
from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

import pytest

HUB = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HUB / "workflows" / "lib"))

from customer_desk import bindings, cases, envelopes, pipeline, store  # noqa: E402
from customer_desk.scripted import ScriptedStations  # noqa: E402

COPY = ["AGENTS.md", "settings.yaml", "hub.settings.yaml", "knowledge", "connectors", "fixtures", "agents",
        "evals", "work-items.yaml", "hitl.yaml"]


class LocalRunner(pipeline.Runner):
    def __init__(self, hub_dir):
        self.stations = ScriptedStations(lambda: pipeline.load(hub_dir))
        self.stages: list[str] = []

    def checkpoint(self, stage, fn):
        self.stages.append(stage)
        return json.loads(json.dumps(fn(), default=str))

    def station(self, agent, *, stage, revision, message):
        return self.stations(agent, stage=stage, revision=revision, message=message)


@pytest.fixture
def hub(tmp_path, monkeypatch):
    root = tmp_path / "customer-desk"
    root.mkdir()
    for name in COPY:
        src = HUB / name
        if src.is_dir():
            shutil.copytree(src, root / name)
        elif src.exists():
            shutil.copy(src, root / name)
    monkeypatch.setenv("DESK_DB", str(tmp_path / "desk.sqlite"))
    for var in ("HUBZOID_DATA_DIR", "DATABASE_URL", "HUBZOID_OPERATIONAL_DB"):
        monkeypatch.delenv(var, raising=False)
    store.reset_connections()
    yield root
    store.reset_connections()


@pytest.fixture
def bound(hub):
    """The sample bindings imported."""
    from customer_desk.erpnext import config as erp_config
    from customer_desk.erpnext.contract import ERPContext

    erp = erp_config.backend(hub)
    ctx = ERPContext(hub_id="customer-desk", company="Synthetic Meridian Distribution")

    def lookup(cid):
        try:
            return erp.get_record("customers", cid, ctx)
        except Exception:  # noqa: BLE001
            return None

    conn = store.connect(hub)
    plan = bindings.plan_import(conn, (hub / "fixtures" / "bindings.csv").read_text(),
                                company="Synthetic Meridian Distribution", customer_lookup=lookup)
    with store.tx(hub) as tconn:
        for a in plan["adds"]:
            bindings.add(tconn, company=a["company"], channel_kind=a["channel_kind"], sender=a["sender"],
                         customer_id=a["customer_id"], actor="test", source_ref=a["source_ref"], synthetic=True)
    return hub


def load_sample(hub_dir, path="fixtures/intake/customer-desk-20.jsonl"):
    out = []
    for line in (Path(hub_dir) / path).read_text().splitlines():
        if line.strip():
            out.append(json.loads(line))
    return out


def triage_envelope(hub_dir, env, runner=None):
    runner = runner or LocalRunner(hub_dir)
    opened = cases.intake(hub_dir, envelopes.from_envelope(env))
    result = pipeline.triage(hub_dir, opened["case_id"], runner, trigger=f"event-{opened['seq']}")
    return opened, result, runner
