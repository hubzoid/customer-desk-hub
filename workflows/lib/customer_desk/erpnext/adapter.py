"""The desk's read client over the vendored `erp.read.ERPReader`.

It keeps one record shape for the desk's rules (child rows under the field
name ERPNext uses, each with its row `name`), translates the desk's few query
words into the reader's allowlisted filters, and adds the two filters ERPNext
cannot express exactly ("open orders", "invoices with something outstanding")
on the records read. Every read goes out with `party_scope` set when the
caller is a case, and only for the six resources the desk needs.
"""
from __future__ import annotations

from decimal import Decimal

from erp.models import ERPContext as ReaderContext

from .contract import CHILD_KEY, DESK_RESOURCES, MAX_PDF_BYTES, ERPContext, ERPError, Records

#: The most records one listing scans before it reports itself truncated.
MAX_SCAN = 1000
CLOSED_ORDER = ("Completed", "Closed", "Cancelled")
QUERY_WORDS = {"ids", "item_codes", "docstatus", "open_only", "outstanding_only", "warehouses", "price_lists",
               "date_from", "date_to", "name_search", "po_no", "limit"}


def _dec(value) -> Decimal:
    return Decimal(str(value if value not in (None, "") else 0))


class DeskERP:
    def __init__(self, service, cfg):
        self.service = service
        self.cfg = cfg
        self.transport = service.transport()
        self.reader = service.reader(self.transport)
        self.name = self.transport.name
        self.synthetic = cfg.synthetic

    # -- context and shape ------------------------------------------------------------------------
    @staticmethod
    def reader_context(ctx: ERPContext) -> ReaderContext:
        party = ctx.party_scope
        return ReaderContext(hub_id=ctx.hub_id, principal=ctx.principal or "desk",
                             party_scope=("customer", party) if party else None,
                             allowed_resources=frozenset(DESK_RESOURCES))

    @staticmethod
    def shape(rec: dict) -> dict:
        out = dict(rec)
        fields = dict(rec["fields"])
        key = CHILD_KEY.get(rec["resource"])
        if key and rec.get("rows") is not None:
            fields[key] = [dict(row, name=row.get("row_id")) for row in rec["rows"]]
        out["fields"] = fields
        return out

    # -- reads ------------------------------------------------------------------------------------
    def get_record(self, resource: str, record_id: str, ctx: ERPContext) -> dict:
        return self.shape(self.reader.get_record(resource, record_id, self.reader_context(ctx)))

    def list_records(self, resource: str, query: dict | None, ctx: ERPContext) -> Records:
        q = dict(query or {})
        unknown = set(q) - QUERY_WORDS
        if unknown:
            raise ERPError("invalid_filter", f"The desk cannot filter {resource} by {', '.join(sorted(unknown))}.",
                           status=400)
        limit = max(1, min(int(q.get("limit") or 50), MAX_SCAN))
        base: dict = {}
        for word, key in (("ids", "ids"), ("docstatus", "docstatus"), ("date_from", "date_from"),
                          ("date_to", "date_to"), ("po_no", "po_no"), ("name_search", "search")):
            if q.get(word) not in (None, "", []):
                base[key] = q[word]
        keep = []
        if q.get("open_only") and resource == "sales_orders":
            base["docstatus"] = 1
            keep.append(lambda r: r["fields"].get("status") not in CLOSED_ORDER)
        if q.get("outstanding_only"):
            keep.append(lambda r: _dec(r["fields"].get("outstanding_amount")) != 0)
        variants = [base]
        if q.get("item_codes"):
            variants = [dict(base, item_code=code) for code in list(q["item_codes"])[:20]]
        if q.get("price_lists"):
            variants = [dict(v, price_list=p) for v in variants for p in list(q["price_lists"])[:5]]
        # `warehouses` is the configured set, which the reader enforces on every Bin read.
        rctx = self.reader_context(ctx)
        out, seen, truncated = [], set(), False
        for v in variants:
            recs = self.reader.all_records(resource, v, rctx, max_records=MAX_SCAN)
            truncated = truncated or len(recs) >= MAX_SCAN
            for r in recs:
                if r["id"] in seen:
                    continue
                seen.add(r["id"])
                if all(k(r) for k in keep):
                    out.append(self.shape(r))
        out.sort(key=lambda r: r["id"])
        if len(out) > limit:
            out, truncated = out[:limit], True
        return Records(out, truncated=truncated)

    def get_print_pdf(self, resource: str, record_id: str, print_format: str | None, ctx: ERPContext) -> bytes:
        """The official print. The print format is the connector's setting
        (`print_format` in connectors/erpnext.yaml), never the caller's."""
        doc = self.reader.get_print_pdf(resource, record_id, self.reader_context(ctx))
        data = doc["bytes"]
        if len(data) > MAX_PDF_BYTES or not data.startswith(b"%PDF"):
            raise ERPError("erp_print_unavailable", "The print was not a valid PDF under 5 MiB.", status=502)
        return data

    def doctor(self, ctx: ERPContext) -> list[dict]:
        """One read per resource the desk uses, as the integration user."""
        rows = []
        try:
            rows.append({"id": "erp.identity", "status": "ok", "summary": f"Connected as {self.transport.logged_user()}."})
        except ERPError as exc:
            return [{"id": "erp.identity", "status": "fail", "summary": exc.message}]
        rctx = self.reader_context(ctx)
        for resource in DESK_RESOURCES:
            try:
                page = self.reader.list_records(resource, {}, rctx, limit=1)
                rows.append({"id": f"erp.read.{resource}", "status": "ok" if page.records else "warn",
                             "summary": f"{resource} readable" + ("" if page.records else ", but none found")})
            except ERPError as exc:
                rows.append({"id": f"erp.read.{resource}", "status": "fail", "summary": f"{resource}: {exc.message}"})
        return rows
