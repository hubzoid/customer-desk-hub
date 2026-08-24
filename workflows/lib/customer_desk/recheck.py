"""Reread every ERP fact a reply relies on, at send-request time and again
just before dispatch. A changed value means the reply is stale: the send is
refused and a new resolution is drafted. This is the approval precondition
recheck applied to ERP facts."""
from __future__ import annotations

from decimal import Decimal
from pathlib import Path

from . import store
from .erpnext import config as erp_config
from .erpnext.contract import ERPContext, ERPError

DOCTYPES = {"Sales Order": "sales_orders", "Sales Invoice": "sales_invoices", "Item": "items",
            "Item Price": "prices", "Bin": "availability", "Customer": "customers"}
ERP_BACKENDS = ("sample", "fake_rest", "frappe_rest")


def _num(v):
    try:
        return Decimal(str(v))
    except Exception:  # noqa: BLE001
        return v


def changed_facts(hub_dir: Path, case: dict, facts: list[dict], *, erp=None, policy=None) -> list[dict]:
    """Facts whose ERP source now reads differently. Empty means current."""
    erp = erp or erp_config.backend(hub_dir)
    cfg = erp_config.load(hub_dir)
    ctx = ERPContext(hub_id=Path(hub_dir).name.lower(), company=cfg.company, party_scope=case["customer_id"],
                     principal="desk-recheck", warehouses=cfg.warehouses)
    cache: dict[tuple, dict | None] = {}

    def read(resource, rid):
        key = (resource, rid)
        if key not in cache:
            try:
                cache[key] = erp.get_record(resource, rid, ctx)
            except ERPError as exc:
                if exc.code != "not_found":
                    raise
                cache[key] = None
        return cache[key]

    out = []
    for f in facts:
        src = f["source"]
        if src.get("backend") not in ERP_BACKENDS:
            continue
        resource = DOCTYPES.get(src.get("doctype"))
        if resource is None:
            continue
        names = [n for n in str(src.get("name") or "").split(",") if n]
        if f["kind"] in ("availability_qty", "availability_band"):
            total = Decimal(0)
            for n in names:
                rec = read("availability", n)
                if rec is not None:
                    total += Decimal(str(rec["fields"].get("projected_qty") or 0))
            if f["kind"] == "availability_qty":
                now = str(total)
                if _num(now) != _num(f["value"]):
                    out.append({"fact_id": f["fact_id"], "was": f["value"], "now": now})
            elif policy is not None:
                limit = Decimal(policy.category("price_availability")["availability"]["limited_below"] or 0)
                band = "out of stock" if total <= 0 else "limited" if total < limit else "in stock"
                if band != f["value"]:
                    out.append({"fact_id": f["fact_id"], "was": f["value"], "now": band})
            continue
        if f["kind"] in ("statement_table", "credit_note", "statement_total"):
            for n in names:
                rec = read("sales_invoices", n)
                if rec is None or Decimal(str(rec["fields"].get("outstanding_amount") or 0)) == 0:
                    out.append({"fact_id": f["fact_id"], "was": n, "now": "no longer open"})
                    break
            continue
        rec = read(resource, names[0]) if names else None
        if rec is None:
            out.append({"fact_id": f["fact_id"], "was": f["value"], "now": "not found"})
            continue
        field = src.get("field")
        if src.get("row_id"):
            row = next((r for r in rec["fields"].get("items") or [] if r.get("name") == src["row_id"]), None)
            now = row.get(field) if row else None
        elif field == "name":
            now = rec["id"]
        else:
            now = rec["fields"].get(field)
        if _num(now) != _num(f["value"]):
            out.append({"fact_id": f["fact_id"], "was": f["value"], "now": now})
    return out


def facts_state(hub_dir: Path, case: dict, resolution: int, *, policy=None) -> list:
    """A stable summary for an approval's target version: the changed facts, if any."""
    facts = store.get_facts(store.connect(hub_dir), case["id"], resolution)
    return sorted((c["fact_id"], str(c["now"])) for c in changed_facts(hub_dir, case, facts, policy=policy))
