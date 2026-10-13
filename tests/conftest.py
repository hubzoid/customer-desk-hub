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

COPY = ["AGENTS.md", "settings.yaml", "hub.settings.yaml", "hub.manifest.yaml", "knowledge", "connectors", "agents", "evals", "work-items.yaml", "hitl.yaml", "workflows", "tools_local", "restricted", "identity",
        "cards", "mcp-apps.yaml", "doctor"]


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
            shutil.copytree(src, root / name, ignore=shutil.ignore_patterns("__pycache__"))
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
    plan = bindings.plan_import(conn, dataset_file(hub, "bindings.csv").read_text(),
                                company="Synthetic Meridian Distribution", customer_lookup=lookup)
    with store.tx(hub) as tconn:
        for a in plan["adds"]:
            bindings.add(tconn, company=a["company"], channel_kind=a["channel_kind"], sender=a["sender"],
                         customer_id=a["customer_id"], actor="test", source_ref=a["source_ref"], synthetic=True)
    return hub


def dataset_file(hub_dir, *parts) -> Path:
    """A file of the vendored distributor-v1 dataset in this hub copy."""
    return Path(hub_dir) / "workflows" / "lib" / "erp" / "datasets" / "distributor-v1" / Path(*parts)


def load_sample(hub_dir, name="customer-desk.jsonl"):
    """The dataset's twenty Customer Desk requests, or another messages file by name
    (customer-desk-adversarial.jsonl for the six adversarial ones)."""
    out = []
    for line in dataset_file(hub_dir, "messages", name).read_text().splitlines():
        if line.strip():
            out.append(json.loads(line))
    return out


def envelope(hub_dir, event_id, **over):
    """One dataset request by its event id (CD-001, CD-A03), with fields replaced."""
    for name in ("customer-desk.jsonl", "customer-desk-adversarial.jsonl"):
        for env in load_sample(hub_dir, name):
            if env["provider_event_id"] == event_id:
                return dict(env, **over)
    raise KeyError(event_id)


def triage_envelope(hub_dir, env, runner=None):
    runner = runner or LocalRunner(hub_dir)
    opened = cases.intake(hub_dir, envelopes.from_envelope(env))
    result = pipeline.triage(hub_dir, opened["case_id"], runner, trigger=f"event-{opened['seq']}")
    return opened, result, runner
