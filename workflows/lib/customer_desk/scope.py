"""The one customer a case may read, decided now, never from a stored id alone.

An external case reads only while its sender still resolves to exactly one
active binding for the same customer the case was bound to. An internal case
(a teammate's chat, Slack or transcript request) reads the customer the
teammate named. Anything else reads nothing: every ERP context for a case is
built here, and a case without a current customer gets no context at all, so
no read can ever run without a party scope.
"""
from __future__ import annotations

from pathlib import Path

from . import bindings, config, store
from .erpnext import config as erp_config
from .erpnext.contract import ERPContext


class ScopeError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code, self.message = code, message


def current_customer(hub_dir: Path, case: dict, values: dict | None = None) -> str | None:
    """The customer this case may read right now, or None."""
    if case["origin_kind"] == "internal":
        return case["customer_id"] or None
    if not case.get("customer_id") or not case.get("sender_key"):
        return None
    values = values or config.settings(hub_dir)
    binding, _ = bindings.resolve(store.connect(hub_dir), values["DESK_COMPANY"], case["sender_kind"],
                                  case["sender_key"])
    if binding is None or binding["customer_id"] != case["customer_id"]:
        return None
    return case["customer_id"]


def erp_context(hub_dir: Path, case: dict, *, principal: str, cfg=None, values: dict | None = None) -> ERPContext:
    """The ERP context for one case, scoped to its current customer."""
    customer = current_customer(hub_dir, case, values)
    if not customer:
        raise ScopeError("binding_required", f"{case['number']} has no exact customer binding now. Nothing was read.")
    cfg = cfg or erp_config.load(hub_dir)
    return ERPContext(hub_id=Path(hub_dir).name.lower(), company=cfg.company, party_scope=customer,
                      principal=principal, warehouses=cfg.warehouses)
