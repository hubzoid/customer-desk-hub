"""Hub settings, the desk clock and the files the desk reads, in one place."""
from __future__ import annotations

import datetime as dt
import json
from dataclasses import dataclass
from pathlib import Path

ROLES = {
    "desk_operator": "Answers customers: claims cases, edits replies, saves drafts and asks to send.",
    "desk_delivery": "Owns delivery proposals and late orders, and verifies date changes in ERPNext.",
    "desk_complaints": "Owns complaint tickets and reviews escalation plans.",
    "desk_exceptions": "Decides refunds and goodwill outside policy.",
    "desk_bindings": "Matches customer email addresses and phone numbers to ERP customers.",
}
QUEUE_ROLE = {"operators": "desk_operator", "delivery": "desk_delivery", "complaints": "desk_complaints",
              "decisions": "desk_exceptions"}


def settings(hub_dir: Path) -> dict:
    try:
        from hubzoid.hubs import settings as hub_settings

        values = dict(hub_settings.effective(Path(hub_dir)))
    except Exception:  # noqa: BLE001 - fall back to the values file for tests and the CLI
        import yaml

        values = (yaml.safe_load((Path(hub_dir) / "hub.settings.yaml").read_text()) or {}).get("values", {})
    defaults = {"DESK_MODE": "sample", "DESK_CLOCK": "dataset", "DESK_POLICY_FILE": "knowledge/desk-policy.md",
                "DESK_STYLE_FILE": "knowledge/customer-messages.md", "DESK_KINDS_FILE": "knowledge/request-kinds.md",
                "DESK_EXTERNAL_CHANNELS": ["sample-email", "sample-whatsapp"], "DESK_INTERNAL_SURFACES": ["chat", "transcript"],
                "DESK_SLACK_CHANNELS": [], "DESK_INTAKE_ENABLED": True,
                "DESK_MAX_REQUESTS_PER_CASE": 5, "DESK_REOPEN_DAYS": 14, "DESK_RESPONSE_TARGET_HOURS": 8,
                "DESK_CASE_PREFIX": "CD", "DESK_TICKET_PREFIX": "TKT", "DESK_SECOND_OPINION_BELOW": 0.75,
                "DESK_HELPDESK": "none", "DESK_HELPDESK_MODE": "dry-run", "DESK_HELPDESK_DRAFTS": False,
                "ZOHO_DESK_TAG_PREFIX": "desk-", "DESK_SUPPORT_ENABLED": False, "DESK_ERP_ENABLED": True,
                "DESK_KNOWLEDGE_DIR": "knowledge/support", "DESK_SUPPORT_HISTORY": True,
                "FRESHDESK_API_BASE": "", "FRESHDESK_GROUP_ID": "", "DESK_SUPPORT_PRODUCT": "",
                "DESK_SUPPORT_LANGUAGE": "en", "DESK_SUPPORT_AUDIENCE": "customer"}
    for k, v in defaults.items():
        values.setdefault(k, v)
    return values


def namespace(values: dict) -> str:
    return "sample" if values.get("DESK_MODE", "sample") == "sample" else "live"


def today(hub_dir: Path, values: dict | None = None) -> dt.date:
    """The desk's today: the sample dataset's fixed clock, or the real UTC date."""
    values = values or settings(hub_dir)
    if values.get("DESK_CLOCK") == "dataset" and values.get("DESK_ERP_ENABLED", True):
        from .erpnext import config as erp_config

        cfg = erp_config.load(hub_dir)
        if cfg.dataset:
            manifest = erp_config.dataset_dir(hub_dir, cfg.dataset) / "manifest.json"
            if manifest.is_file():
                clock = json.loads(manifest.read_text()).get("clock")
                if clock:
                    return dt.date.fromisoformat(clock[:10])
    return dt.datetime.now(dt.timezone.utc).date()


def now_iso(hub_dir: Path, values: dict | None = None) -> str:
    """Now, as the desk sees it. In dataset-clock mode the date is the
    dataset's and the time of day is real, so ordering still works."""
    real = dt.datetime.now(dt.timezone.utc).replace(microsecond=0)
    d = today(hub_dir, values)
    return real.replace(year=d.year, month=d.month, day=d.day).isoformat().replace("+00:00", "Z")


@dataclass(frozen=True)
class Files:
    policy: str
    style: str
    kinds: str


def files(values: dict) -> Files:
    return Files(values["DESK_POLICY_FILE"], values["DESK_STYLE_FILE"], values["DESK_KINDS_FILE"])
