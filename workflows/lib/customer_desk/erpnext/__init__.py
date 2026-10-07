"""ERPNext for the Customer Desk: the vendored ERP module behind one read-only adapter.

The module is `workflows/lib/erp`, copied unchanged from the Order & Invoice
Desk (see erp/VENDORED.md). The desk reaches it only through this package:
`config.load` refuses a writable configuration, `adapter.DeskERP` reads six
resources and always for the case's customer, and nothing here can create,
change or submit an ERP document.
"""
from .config import backend, load
from .contract import ERPContext, ERPError, Records

__all__ = ["ERPContext", "ERPError", "Records", "backend", "load"]
