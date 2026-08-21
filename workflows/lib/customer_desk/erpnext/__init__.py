"""ERPNext reads for the Customer Desk (HUB-108 contract, read parts only).

INTERIM: written here to the HUB-108 contract. When the canonical module from
the Order & Invoice Desk lands, its read parts are copied in unchanged and
marked VENDORED with the source commit, replacing these files.
"""
from .contract import ERPContext, ERPError, RESOURCES
from .config import backend, load

__all__ = ["ERPContext", "ERPError", "RESOURCES", "backend", "load"]
