"""The sample backend: the synthetic dataset on disk, read only.

INTERIM until the canonical module is vendored. Same contract as the REST
backends: party and company scoping, allowlisted fields, `not_found` for
anything outside scope, a deterministic PDF for submitted invoices only.
"""
from __future__ import annotations

import json
from pathlib import Path

from . import pdf
from .contract import MAX_PDF_BYTES, RESOURCES, ERPContext, ERPError, in_scope, not_found, record

FILES = {"customers": "customers.json", "items": "items.json", "prices": "prices.json",
         "availability": "availability.json", "sales_orders": "sales_orders.json",
         "sales_invoices": "sales_invoices.json"}


def matches(resource: str, raw: dict, query: dict) -> bool:
    """The bounded filters every backend understands."""
    q = query or {}
    if q.get("ids") and raw["name"] not in q["ids"]:
        return False
    if q.get("item_codes") and raw.get("item_code") not in q["item_codes"]:
        return False
    if q.get("docstatus") is not None and raw.get("docstatus") != q["docstatus"]:
        return False
    if q.get("open_only") and resource == "sales_orders":
        if raw.get("docstatus") != 1 or raw.get("status") in ("Completed", "Closed", "Cancelled"):
            return False
    if q.get("outstanding_only") and float(raw.get("outstanding_amount") or 0) == 0:
        return False
    if q.get("warehouses") and raw.get("warehouse") not in q["warehouses"]:
        return False
    if q.get("price_lists") and raw.get("price_list") not in q["price_lists"]:
        return False
    date_field = {"sales_orders": "transaction_date", "sales_invoices": "posting_date"}.get(resource)
    if date_field:
        if q.get("date_from") and (raw.get(date_field) or "") < q["date_from"]:
            return False
        if q.get("date_to") and (raw.get(date_field) or "") > q["date_to"]:
            return False
    if q.get("name_search"):
        needle = q["name_search"].casefold()
        hay = " ".join(str(raw.get(k) or "") for k in ("name", "item_code", "item_name", "customer_name"))
        if needle not in hay.casefold():
            return False
    return True


class SampleBackend:
    name = "sample"
    synthetic = True

    def __init__(self, dataset_dir: Path, *, company: str, overlay: Path | None = None):
        self.dir = Path(dataset_dir)
        self.company = company
        # Edits a person makes "in ERPNext" during a sample demo, kept outside the
        # immutable dataset: {resource: {record id: {field: value}}}.
        self.overlay = json.loads(overlay.read_text()) if overlay and overlay.is_file() else {}
        manifest = self.dir / "manifest.json"
        if not manifest.is_file():
            raise ERPError("config_invalid", f"No sample dataset at {self.dir}. Install it first.", status=422)
        self.manifest = json.loads(manifest.read_text())
        self._cache: dict[str, list[dict]] = {}

    def _rows(self, resource: str) -> list[dict]:
        if resource not in self._cache:
            path = self.dir / FILES[resource]
            rows = json.loads(path.read_text()) if path.is_file() else []
            edits = self.overlay.get(resource) or {}
            for row in rows:
                for field, value in (edits.get(row["name"]) or {}).items():
                    row[field] = value
                    row["modified"] = "2000-01-15T12:00:00Z"
            self._cache[resource] = rows
        return self._cache[resource]

    def _wrap(self, resource: str, raw: dict) -> dict:
        return record(resource, raw, backend=self.name, synthetic=True, company=self.company)

    def get_record(self, resource: str, record_id: str, context: ERPContext) -> dict:
        if resource not in RESOURCES:
            raise ERPError("invalid_request", f"Unknown resource {resource!r}.", status=400)
        for raw in self._rows(resource):
            if raw["name"] == record_id:
                if not in_scope(resource, raw, context):
                    break
                return self._wrap(resource, raw)
        raise not_found(resource, record_id)

    def list_records(self, resource: str, query: dict, context: ERPContext) -> list[dict]:
        if resource not in RESOURCES:
            raise ERPError("invalid_request", f"Unknown resource {resource!r}.", status=400)
        limit = min(int((query or {}).get("limit") or 50), 200)
        rows = [r for r in self._rows(resource) if in_scope(resource, r, context) and matches(resource, r, query)]
        rows.sort(key=lambda r: r["name"])
        return [self._wrap(resource, r) for r in rows[:limit]]

    def get_print_pdf(self, resource: str, record_id: str, print_format: str, context: ERPContext) -> bytes:
        if resource != "sales_invoices":
            raise ERPError("erp_print_unavailable", "Only Sales Invoice prints are available.", status=422)
        rec = self.get_record(resource, record_id, context)
        if rec["fields"]["docstatus"] != 1:
            raise not_found(resource, record_id)
        raw = next(r for r in self._rows(resource) if r["name"] == record_id)
        cust = next((c for c in self._rows("customers") if c["name"] == raw.get("customer")), {})
        data = pdf.invoice_pdf(raw, cust.get("customer_name", ""), self.company, print_format)
        if len(data) > MAX_PDF_BYTES or not data.startswith(b"%PDF"):
            raise ERPError("erp_print_unavailable", "The print was not a valid PDF under 5 MiB.")
        return data

    def doctor(self, context: ERPContext) -> list[dict]:
        rows = []
        for resource in FILES:
            count = len(self._rows(resource))
            rows.append({"id": f"erp.read.{resource}", "status": "ok" if count else "warn",
                         "summary": f"{count} synthetic {resource} rows"})
        return rows
