"""The desk side of the ERP boundary.

The ERP module itself is vendored (`workflows/lib/erp`, copied unchanged from
the Order & Invoice Desk, see erp/VENDORED.md). These names are what the rest
of the desk uses, so the desk never builds a vendored context by hand and
never forgets the party scope.

The Customer Desk never writes to ERPNext. There is no create, submit, update
or delete anywhere in this package, and `config.load` refuses
`writes_enabled: true`.
"""
from __future__ import annotations

from dataclasses import dataclass

from erp.errors import ERPError
from erp.errors import not_found as _not_found

#: The only resources the desk reads. Suppliers and purchase documents stay out of reach.
DESK_RESOURCES = ("customers", "items", "prices", "availability", "sales_orders", "sales_invoices")

#: Where each resource's child rows appear in a desk record's fields.
CHILD_KEY = {"sales_orders": "items", "sales_invoices": "items", "items": "uoms"}

MAX_PDF_BYTES = 5 * 1024 * 1024

__all__ = ["CHILD_KEY", "DESK_RESOURCES", "ERPContext", "ERPError", "MAX_PDF_BYTES", "Records", "not_found"]


def not_found(resource: str, record_id: str = "") -> ERPError:
    """The same answer whether a record is missing or belongs to someone else."""
    return _not_found(resource.rstrip("s").replace("_", " "))


@dataclass(frozen=True)
class ERPContext:
    """Who is reading, built by trusted hub code. `party_scope` is the bound
    customer of the case: every record of another customer reads as
    `not_found`. None of these fields ever comes from a model. `company` and
    `warehouses` are informational: the vendored reader takes both from the
    applied connector configuration."""

    hub_id: str
    company: str = ""
    party_scope: str | None = None
    principal: str = "desk"
    warehouses: tuple[str, ...] = ()


class Records(list):
    """A list read. `truncated` is true when more matching records exist than
    were returned, so a caller never presents a partial list as complete."""

    truncated: bool = False

    def __init__(self, items=(), truncated: bool = False):
        super().__init__(items)
        self.truncated = truncated
