"""The Frappe REST backend, read only. Used for `fake_rest` (a loopback fake
server) and `frappe_rest` (a live ERPNext site).

INTERIM until the canonical module is vendored. The adapter builds Frappe
filters itself. It only ever sends GET. It never follows redirects, retries
GET at most three attempts with backoff, honours Retry-After up to 60 seconds,
and never retries 401 or 403.
"""
from __future__ import annotations

import json
import time
from typing import Callable
from urllib.parse import quote

import httpx

from .contract import (COMPANY_SCOPED, MAX_PDF_BYTES, RESOURCES, ERPContext, ERPError, Records, in_scope,
                       not_found, record)

#: At most this many pages per list read. Past it the list comes back truncated.
MAX_LIST_PAGES = 20
SLEEP: Callable[[float], None] = time.sleep


class FrappeRestBackend:
    synthetic = False

    def __init__(self, base_url: str, *, company: str, token: str | None, backend: str = "frappe_rest",
                 timeout: float = 20.0, attempts: int = 3, page_size: int = 50,
                 transport: httpx.BaseTransport | None = None):
        self.name = backend
        self.synthetic = backend == "fake_rest"
        self.base = base_url.rstrip("/")
        self.company = company
        self.attempts = max(1, min(3, attempts))
        self.page_size = max(1, min(100, page_size))
        headers = {"Accept": "application/json"}
        if token:
            headers["Authorization"] = f"token {token}"
        self.http = httpx.Client(base_url=self.base, headers=headers, timeout=timeout, follow_redirects=False,
                                 transport=transport)

    # -- the one request method: GET only ------------------------------------------
    def _get(self, path: str, params: dict | None = None, *, raw: bool = False):
        last: ERPError | None = None
        for attempt in range(self.attempts):
            try:
                resp = self.http.get(path, params=params)
            except httpx.TimeoutException:
                last = ERPError("erp_unavailable", "ERPNext did not answer in time. Nothing was changed.",
                                status=503, retryable=True)
            except httpx.HTTPError:
                last = ERPError("erp_unavailable", "ERPNext could not be reached. Nothing was changed.",
                                status=503, retryable=True)
            else:
                if resp.status_code in (401, 403):
                    code = "erp_auth_failed" if resp.status_code == 401 else "erp_permission_denied"
                    raise ERPError(code, "ERPNext refused the integration user. Check its read permissions.",
                                   status=resp.status_code)
                if resp.status_code == 404:
                    return None
                if resp.status_code == 429 or resp.status_code >= 500:
                    code = "erp_rate_limited" if resp.status_code == 429 else "erp_unavailable"
                    last = ERPError(code, "ERPNext is busy or failing. Nothing was changed.", status=503,
                                    retryable=True)
                    wait = resp.headers.get("Retry-After")
                    if attempt + 1 < self.attempts:
                        SLEEP(min(float(wait) if wait and wait.isdigit() else 2 ** attempt, 60))
                    continue
                if 300 <= resp.status_code < 400:
                    raise ERPError("erp_protocol_error", "ERPNext answered with a redirect, which is refused.")
                if len(resp.content) > MAX_PDF_BYTES:
                    raise ERPError("erp_protocol_error", "ERPNext's answer was larger than 5 MiB.")
                if raw:
                    return resp.content
                try:
                    return resp.json()
                except ValueError:
                    raise ERPError("erp_protocol_error", "ERPNext's answer was not JSON.") from None
            if attempt + 1 < self.attempts:
                SLEEP(min(2 ** attempt, 10))
        raise last or ERPError("erp_unavailable", "ERPNext could not be reached.", status=503)

    def _doctype(self, resource: str) -> str:
        if resource not in RESOURCES:
            raise ERPError("invalid_request", f"Unknown resource {resource!r}.", status=400)
        return RESOURCES[resource][0]

    def _wrap(self, resource: str, raw: dict) -> dict:
        return record(resource, raw, backend=self.name, synthetic=self.synthetic, company=self.company)

    def get_record(self, resource: str, record_id: str, context: ERPContext) -> dict:
        doctype = self._doctype(resource)
        body = self._get(f"/api/resource/{quote(doctype)}/{quote(record_id)}")
        raw = (body or {}).get("data") if isinstance(body, dict) else None
        if not raw or not in_scope(resource, raw, context):
            raise not_found(resource, record_id)
        return self._wrap(resource, raw)

    def _filters(self, resource: str, query: dict, context: ERPContext) -> list:
        q = query or {}
        f: list = []
        _doctype, party, _allowed = RESOURCES[resource]
        if resource in COMPANY_SCOPED:
            f.append([resource_doctype(resource), "company", "=", context.company])
        if context.party_scope and party and resource != "prices":
            f.append([resource_doctype(resource), party, "=", context.party_scope])
        if q.get("ids"):
            f.append([resource_doctype(resource), "name", "in", list(q["ids"])])
        if q.get("item_codes"):
            f.append([resource_doctype(resource), "item_code", "in", list(q["item_codes"])])
        if q.get("docstatus") is not None:
            f.append([resource_doctype(resource), "docstatus", "=", q["docstatus"]])
        if q.get("open_only") and resource == "sales_orders":
            # Filtered by ERPNext itself, so closed orders never fill the page.
            f.append([resource_doctype(resource), "docstatus", "=", 1])
            f.append([resource_doctype(resource), "status", "not in", ["Completed", "Closed", "Cancelled"]])
        if q.get("outstanding_only"):
            f.append([resource_doctype(resource), "outstanding_amount", "!=", 0])
        if q.get("warehouses"):
            f.append([resource_doctype(resource), "warehouse", "in", list(q["warehouses"])])
        if q.get("price_lists"):
            f.append([resource_doctype(resource), "price_list", "in", list(q["price_lists"])])
        date_field = {"sales_orders": "transaction_date", "sales_invoices": "posting_date"}.get(resource)
        if date_field and q.get("date_from"):
            f.append([resource_doctype(resource), date_field, ">=", q["date_from"]])
        if date_field and q.get("date_to"):
            f.append([resource_doctype(resource), date_field, "<=", q["date_to"]])
        if q.get("name_search"):
            field = "item_name" if resource == "items" else "name"
            f.append([resource_doctype(resource), field, "like", f"%{q['name_search']}%"])
        return f

    def list_records(self, resource: str, query: dict, context: ERPContext) -> Records:
        """Pages through ERPNext until `limit` matching records are found or the
        list ends. One more than asked is looked for, so a longer list comes
        back marked `truncated` instead of silently cut."""
        from .sample import matches

        doctype = self._doctype(resource)
        limit = min(int((query or {}).get("limit") or self.page_size), 200)
        filters = json.dumps(self._filters(resource, query, context))
        out: list[dict] = []
        start = 0
        for _ in range(MAX_LIST_PAGES):
            params = {"filters": filters, "fields": json.dumps(["name"]), "limit_start": str(start),
                      "limit_page_length": str(self.page_size), "order_by": "name asc"}
            rows = (self._get(f"/api/resource/{quote(doctype)}", params) or {}).get("data") or []
            for row in rows:
                try:
                    rec = self.get_record(resource, row["name"], context)
                except ERPError as exc:
                    if exc.code == "not_found":
                        continue
                    raise
                # The desk rechecks scope and the bounded filters on the full record,
                # so a Frappe filter that a site ignores never widens what is shown.
                raw = dict(rec["fields"], name=rec["id"], company=rec["company"] or context.company)
                if in_scope(resource, raw, context) and matches(resource, raw, query):
                    out.append(rec)
                    if len(out) > limit:
                        return Records(out[:limit], truncated=True)
            if len(rows) < self.page_size:
                return Records(out, truncated=False)
            start += len(rows)
        return Records(out[:limit], truncated=True)

    def get_print_pdf(self, resource: str, record_id: str, print_format: str, context: ERPContext) -> bytes:
        if resource != "sales_invoices":
            raise ERPError("erp_print_unavailable", "Only Sales Invoice prints are available.", status=422)
        rec = self.get_record(resource, record_id, context)
        if rec["fields"]["docstatus"] != 1:
            raise not_found(resource, record_id)
        data = self._get("/api/method/frappe.utils.print_format.download_pdf",
                         {"doctype": "Sales Invoice", "name": record_id, "format": print_format, "no_letterhead": "0"},
                         raw=True)
        if not data or not data.startswith(b"%PDF"):
            raise ERPError("erp_print_unavailable",
                           f"ERPNext did not return a PDF for {record_id} with print format {print_format}. "
                           "Ask the ERP administrator for print permission on that format.", status=422)
        return data

    def doctor(self, context: ERPContext) -> list[dict]:
        rows = []
        try:
            who = self._get("/api/method/frappe.auth.get_logged_user") or {}
            rows.append({"id": "erp.identity", "status": "ok", "summary": f"Signed in as {who.get('message')}"})
        except ERPError as exc:
            rows.append({"id": "erp.identity", "status": "fail", "summary": exc.message})
            return rows
        for resource in RESOURCES:
            try:
                self.list_records(resource, {"limit": 1}, ERPContext(hub_id=context.hub_id, company=context.company))
                rows.append({"id": f"erp.read.{resource}", "status": "ok", "summary": f"{resource} readable"})
            except ERPError as exc:
                rows.append({"id": f"erp.read.{resource}", "status": "fail", "summary": exc.message})
        return rows


def resource_doctype(resource: str) -> str:
    return RESOURCES[resource][0]
