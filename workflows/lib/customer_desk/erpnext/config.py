"""The connector configuration as the desk uses it, and the desk's two rules on top.

`connectors/erpnext.yaml` is the vendored module's file (erp/config.py): it
validates it and keeps applied revisions in the hub's data folder. The desk
adds what a read-only desk must hold: `writes_enabled` is false and no submit
credential is set. `load` refuses anything else (`erp_not_read_only`), so the
desk never even builds a client for a writable configuration.
"""
from __future__ import annotations

import json
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from erp import config as erp_config
from erp.resources import RESOURCES
from erp.service import ERPService

from .contract import ERPError, not_found

FILE = erp_config.FILE
BACKENDS = erp_config.BACKENDS


@dataclass(frozen=True)
class ConnectorConfig:
    backend: str
    dataset: str | None
    site_url: str | None
    company: str
    currency: str
    warehouses: tuple[str, ...]
    selling_price_list: str
    print_format: str | None
    synthetic: bool
    revision: int
    drift: str | None
    writes_enabled: bool = False


def service(hub_dir: Path) -> ERPService:
    return ERPService.for_hub(Path(hub_dir))


def _read_only(cfg) -> None:
    if cfg.writes_enabled:
        raise ERPError("erp_not_read_only", f"{FILE}: writes_enabled must be false. The Customer Desk only reads "
                       "ERPNext and has no ERP write tool.", status=422, field="writes_enabled")
    if cfg.submit_credential_ref:
        raise ERPError("erp_not_read_only", f"{FILE}: the Customer Desk never submits ERP documents. Remove "
                       "submit_credential_ref.", status=422, field="submit_credential_ref")


def load(hub_dir: Path) -> ConnectorConfig:
    """The configuration in force, refused unless it is read only."""
    applied = service(hub_dir).applied()
    cfg = applied.config
    _read_only(cfg)
    return ConnectorConfig(backend=cfg.backend, dataset=cfg.dataset, site_url=cfg.site_url, company=cfg.company,
                           currency=cfg.currency, warehouses=tuple(cfg.warehouses),
                           selling_price_list=cfg.selling_price_list, print_format=cfg.print_format,
                           synthetic=cfg.synthetic, revision=applied.revision, drift=applied.drift)


def problems(text: str) -> list[dict]:
    """Every problem the file on disk has, each `{code, field, message}`, for doctor."""
    try:
        cfg = erp_config.parse(text, str(FILE))
    except ERPError as exc:
        return [{"code": exc.code, "field": exc.fields.get("field"), "message": exc.message}]
    try:
        _read_only(cfg)
    except ERPError as exc:
        return [{"code": exc.code, "field": exc.fields.get("field"), "message": exc.message}]
    return []


def apply_file(hub_dir: Path, *, actor: str):
    """Apply connectors/erpnext.yaml as the next configuration revision. The
    file must be valid and read only. Until it is applied, the last applied
    revision stays in force, and doctor reports the drift."""
    text = (Path(hub_dir) / FILE).read_text()
    found = problems(text)
    if found:
        raise ERPError(found[0]["code"], found[0]["message"], status=422)
    svc = service(hub_dir)
    current = erp_config.current(hub_dir, svc.state_dir)
    return erp_config.apply(hub_dir, svc.state_dir, erp_config.parse(text), write_file=False,
                            expected_revision=current.revision if current else "absent", actor=actor)


def backend(hub_dir: Path, cfg: ConnectorConfig | None = None):
    """The desk's read client for the configuration in force."""
    from .adapter import DeskERP

    cfg = cfg or load(hub_dir)
    return DeskERP(service(hub_dir), cfg)


def dataset_dir(hub_dir: Path, dataset: str) -> Path:
    return service(hub_dir).datasets_root / dataset


# -- the sample backend's own state ---------------------------------------------------------------

def _sample_transport(hub_dir: Path):
    cfg = load(hub_dir)
    if cfg.backend != "sample":
        raise ERPError("sample_only", "This changes only the sample ERP. The connector is not the sample backend.",
                       status=409)
    transport = service(hub_dir).transport()
    return transport


def sample_edit(hub_dir: Path, resource: str, record_id: str, field: str, value) -> dict:
    """Stand in for a person changing one field in ERPNext, for a sample demo
    or a test. The change goes into the sample backend's own state file, the
    one it keeps drafts in, as a newer copy of the document. The dataset files
    never change."""
    transport = _sample_transport(hub_dir)
    res = RESOURCES[resource]
    doc = transport.get_doc(res.doctype, record_id)
    if doc is None:
        raise not_found(resource, record_id)
    doc[field] = value
    doc["modified"] = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S.%f")
    with closing(transport._db()) as db:
        db.execute("INSERT OR REPLACE INTO sample_docs (doctype, name, marker, doc_json) VALUES (?,?,NULL,?)",
                   (res.doctype, record_id, json.dumps(doc, default=str)))
    return {"resource": resource, "id": record_id, "field": field, "value": value}


def sample_reset(hub_dir: Path) -> None:
    """Forget every sample ERP edit (sample backend only)."""
    _sample_transport(hub_dir).reset_state()


def sample_edits(hub_dir: Path) -> int:
    """How many documents the sample state holds, for the eval's read-only check."""
    transport = _sample_transport(hub_dir)
    with closing(transport._db()) as db:
        return db.execute("SELECT COUNT(*) FROM sample_docs").fetchone()[0]
