"""The ERP read contract (HUB-108), read parts only.

INTERIM: written in this hub to the HUB-108 contract until the canonical
ERPNext module from the Order & Invoice Desk is vendored here, unchanged and
marked VENDORED with its source commit. Everything the desk calls goes through
these names, so swapping in the vendored module changes no desk code.

The Customer Desk never writes to ERPNext. There is no create, submit, update
or delete anywhere in this package, and `config.load` refuses
`writes_enabled: true`.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field

#: Resource name -> (Frappe DocType, the party field that scopes it, allowed fields).
RESOURCES: dict[str, tuple[str, str | None, tuple[str, ...]]] = {
    "customers": ("Customer", "name", ("customer_name", "disabled", "default_currency", "default_price_list")),
    "items": ("Item", None, ("item_code", "item_name", "stock_uom", "disabled", "is_stock_item", "uoms")),
    "prices": ("Item Price", "customer", ("item_code", "price_list", "currency", "price_list_rate", "uom",
                                          "customer", "supplier", "valid_from", "valid_upto")),
    "availability": ("Bin", None, ("item_code", "warehouse", "actual_qty", "reserved_qty", "projected_qty")),
    "sales_orders": ("Sales Order", "customer", (
        "customer", "transaction_date", "delivery_date", "po_no", "docstatus", "status", "currency", "total",
        "grand_total", "per_delivered", "per_billed", "delivery_status", "billing_status", "items")),
    "sales_invoices": ("Sales Invoice", "customer", (
        "customer", "po_no", "is_return", "posting_date", "due_date", "docstatus", "status", "currency",
        "outstanding_amount", "total", "grand_total", "items")),
}

#: Child row fields kept per resource.
CHILD_FIELDS = {
    "sales_orders": ("name", "item_code", "item_name", "qty", "delivered_qty", "uom", "rate", "amount",
                     "delivery_date"),
    "sales_invoices": ("name", "item_code", "item_name", "qty", "rate", "amount", "uom"),
    "items": ("uom", "conversion_factor"),
}

#: Resources that carry a company field and are filtered by it.
COMPANY_SCOPED = ("sales_orders", "sales_invoices")

BACKENDS = ("sample", "fake_rest", "frappe_rest")
MAX_PDF_BYTES = 5 * 1024 * 1024


class ERPError(Exception):
    """A read that failed. `code` is stable: `not_found`, `erp_unavailable`,
    `erp_rate_limited`, `erp_auth_failed`, `erp_permission_denied`,
    `erp_print_unavailable`, `erp_protocol_error`, `config_invalid`."""

    def __init__(self, code: str, message: str, *, status: int = 502, retryable: bool = False):
        super().__init__(message)
        self.code, self.message, self.status, self.retryable = code, message, status, retryable


def not_found(resource: str, record_id: str) -> ERPError:
    # The same answer whether the record is missing or belongs to someone
    # else, so a caller cannot learn that another customer's document exists.
    return ERPError("not_found", f"No {resource.rstrip('s').replace('_', ' ')} {record_id} for this account.",
                    status=404)


@dataclass(frozen=True)
class ERPContext:
    """Who is reading, built by trusted hub code. `party_scope` is the bound
    customer of the case. When set, every party-bearing record outside it
    reads as `not_found`. None of these fields ever comes from a model."""

    hub_id: str
    company: str
    party_scope: str | None = None
    principal: str = ""
    connector_id: str = "erpnext"
    allowed_resources: tuple[str, ...] = tuple(RESOURCES)
    warehouses: tuple[str, ...] = ()
    purpose: str = "desk"
    extra: dict = field(default_factory=dict)


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def record(resource: str, raw: dict, *, backend: str, synthetic: bool, company: str | None,
           observed_at: str | None = None) -> dict:
    """The normalized record shape every backend returns."""
    doctype, _party, allowed = RESOURCES[resource]
    fields: dict = {}
    for key in allowed:
        value = raw.get(key)
        if key in ("items", "uoms") and isinstance(value, list):
            keep = CHILD_FIELDS.get(resource, ())
            value = [{k: row.get(k) for k in keep} for row in value]
        fields[key] = value
    return {"resource": resource, "id": raw["name"], "company": company if resource in COMPANY_SCOPED else None,
            "modified_at": raw.get("modified"), "observed_at": observed_at or utc_now(), "backend": backend,
            "synthetic": synthetic, "fields": fields,
            "source": {"doctype": doctype, "name": raw["name"], "fields": list(allowed)}}


class Records(list):
    """A list read. `truncated` is true when more matching records exist than
    were returned, so a caller never presents a partial list as complete."""

    truncated: bool = False

    def __init__(self, items=(), truncated: bool = False):
        super().__init__(items)
        self.truncated = truncated


def in_scope(resource: str, raw: dict, context: ERPContext) -> bool:
    """Whether a raw record is visible to this context."""
    if resource not in context.allowed_resources:
        return False
    if resource in COMPANY_SCOPED and raw.get("company") not in (None, context.company):
        return False
    _doctype, party, _allowed = RESOURCES[resource]
    if context.party_scope is None or party is None:
        return True
    if resource == "prices":
        # Prices carry no customer unless they are customer specific. A row
        # for another customer, or for a supplier, is never visible.
        if raw.get("supplier"):
            return False
        return raw.get("customer") in (None, context.party_scope)
    return raw.get(party) == context.party_scope
