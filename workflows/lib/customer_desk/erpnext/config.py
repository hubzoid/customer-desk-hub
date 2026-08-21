"""`connectors/erpnext.yaml`: load, validate and build the read backend.

INTERIM until the canonical module is vendored. The keys follow HUB-108. This
hub refuses `writes_enabled: true` outright (`erp_not_read_only`): it mounts
no ERP write tool and never needs one.
"""
from __future__ import annotations

import ipaddress
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

import yaml

from .contract import BACKENDS, ERPError

KEYS = {"version", "backend", "dataset", "site_url", "credential_ref", "submit_credential_ref", "company",
        "currency", "warehouses", "selling_price_list", "buying_price_list", "writes_enabled", "timeout_seconds",
        "read_attempts", "page_size", "private_network_cidrs"}
FILE = Path("connectors") / "erpnext.yaml"


@dataclass(frozen=True)
class ConnectorConfig:
    backend: str
    dataset: str | None
    site_url: str | None
    credential_ref: str | None
    company: str
    currency: str
    warehouses: tuple[str, ...]
    selling_price_list: str | None
    writes_enabled: bool
    timeout_seconds: int
    read_attempts: int
    page_size: int
    path: str


def problems(data: dict) -> list[dict]:
    """Every problem at once, each `{code, field, message}`."""
    out: list[dict] = []

    def bad(code, field, message):
        out.append({"code": code, "field": field, "message": message})

    if not isinstance(data, dict):
        return [{"code": "config_invalid", "field": None, "message": "connectors/erpnext.yaml must be a mapping."}]
    for key in sorted(set(data) - KEYS):
        bad("config_invalid", key, f"Unknown key {key!r}. Allowed: {', '.join(sorted(KEYS))}.")
    if data.get("version") != 1:
        bad("config_invalid", "version", "version must be 1.")
    backend = data.get("backend")
    if backend not in BACKENDS:
        bad("config_invalid", "backend", f"backend must be one of {', '.join(BACKENDS)}.")
    if data.get("writes_enabled") is not False:
        bad("erp_not_read_only", "writes_enabled",
            "writes_enabled must be false. The Customer Desk only reads ERPNext and has no ERP write tool.")
    if data.get("submit_credential_ref"):
        bad("erp_not_read_only", "submit_credential_ref", "The Customer Desk never submits ERP documents. "
            "Remove submit_credential_ref.")
    if not isinstance(data.get("company"), str) or not data.get("company"):
        bad("config_invalid", "company", "company is the exact ERPNext company name.")
    if backend in ("sample", "fake_rest") and not data.get("dataset"):
        bad("config_invalid", "dataset", "The sample and fake_rest backends need dataset: distributor-v1.")
    if backend == "frappe_rest" and data.get("dataset"):
        bad("config_invalid", "dataset", "A live ERPNext has no dataset. Remove it.")
    url = data.get("site_url")
    if backend in ("fake_rest", "frappe_rest"):
        if not isinstance(url, str) or not url:
            bad("config_invalid", "site_url", "site_url is required for a REST backend.")
        else:
            p = urlparse(url)
            if p.username or p.password or p.query or p.fragment:
                bad("config_invalid", "site_url", "site_url may not carry credentials, a query or a fragment.")
            host = p.hostname or ""
            loopback = host in ("localhost",) or _is_loopback(host)
            if backend == "fake_rest" and not (p.scheme == "http" and loopback):
                bad("config_invalid", "site_url", "fake_rest must be a loopback http:// origin.")
            if backend == "frappe_rest" and p.scheme != "https":
                bad("config_invalid", "site_url", "A live ERPNext must use https://.")
            if backend == "frappe_rest" and loopback:
                bad("config_invalid", "site_url", "A live ERPNext cannot be a loopback address.")
        if backend == "frappe_rest" and not data.get("credential_ref"):
            bad("config_invalid", "credential_ref", "credential_ref names the API key secret, for example "
                "secret:hub/customer-desk/erpnext-reader.")
    for key, lo, hi in (("timeout_seconds", 1, 60), ("read_attempts", 1, 3), ("page_size", 1, 100)):
        if key in data and not (isinstance(data[key], int) and not isinstance(data[key], bool) and lo <= data[key] <= hi):
            bad("config_invalid", key, f"{key} is a whole number from {lo} to {hi}.")
    wh = data.get("warehouses", [])
    if not isinstance(wh, list) or not all(isinstance(w, str) for w in wh):
        bad("config_invalid", "warehouses", "warehouses is a list of ERPNext warehouse names.")
    return out


def _is_loopback(host: str) -> bool:
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def load(hub_dir: Path) -> ConnectorConfig:
    path = Path(hub_dir) / FILE
    if not path.is_file():
        raise ERPError("config_invalid", f"{FILE} is missing. Copy the sample from the README.", status=422)
    try:
        data = yaml.safe_load(path.read_text()) or {}
    except yaml.YAMLError as exc:
        raise ERPError("config_invalid", f"{FILE} is not valid YAML: {exc}", status=422) from None
    found = problems(data)
    if found:
        first = found[0]
        raise ERPError(first["code"], f"{FILE}: {first['message']}", status=422)
    return ConnectorConfig(
        backend=data["backend"], dataset=data.get("dataset"), site_url=data.get("site_url"),
        credential_ref=data.get("credential_ref"), company=data["company"], currency=data.get("currency", "USD"),
        warehouses=tuple(data.get("warehouses") or ()), selling_price_list=data.get("selling_price_list"),
        writes_enabled=False, timeout_seconds=data.get("timeout_seconds", 20), read_attempts=data.get("read_attempts", 3),
        page_size=data.get("page_size", 50), path=str(FILE))


def dataset_dir(hub_dir: Path, dataset: str) -> Path:
    return Path(hub_dir) / "fixtures" / "erp" / dataset


def backend(hub_dir: Path, cfg: ConnectorConfig | None = None, *, transport=None):
    """The read backend the config names."""
    cfg = cfg or load(hub_dir)
    if cfg.backend == "sample":
        from .sample import SampleBackend

        return SampleBackend(dataset_dir(hub_dir, cfg.dataset), company=cfg.company)
    from .frappe_rest import FrappeRestBackend

    token = None
    if cfg.backend == "fake_rest":
        from .fake_rest import TOKEN

        token = TOKEN
    elif cfg.credential_ref:
        from hubzoid import secretstore

        try:
            token = secretstore.resolve(cfg.credential_ref, hub_dir)
        except Exception as exc:  # noqa: BLE001 - never echo a value, only the reference
            raise ERPError("secret_missing", f"The ERPNext credential {cfg.credential_ref} is not available: "
                           f"{getattr(exc, 'message', type(exc).__name__)}", status=503) from None
    return FrappeRestBackend(cfg.site_url, company=cfg.company, token=token, backend=cfg.backend,
                             timeout=cfg.timeout_seconds, attempts=cfg.read_attempts, page_size=cfg.page_size,
                             transport=transport)
