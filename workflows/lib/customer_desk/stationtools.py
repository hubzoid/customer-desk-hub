"""The resolver's read tools. They take no customer, case or company from the
model: the case comes from the running work item (trusted context), and the
customer from that case's binding. A record of another customer reads as
`not_found`. Every value they return is registered in the resolution's fact
sheet, so the reply can cite it by placeholder.
"""
from __future__ import annotations

import json
from pathlib import Path

from . import facts as facts_lib, gather, policy as policy_lib, store
from .erpnext import config as erp_config
from .erpnext.contract import ERPContext, ERPError

MAX_CODES = 20


class NoCase(Exception):
    pass


def _context(hub_dir: Path):
    from hubzoid import hub

    item_id = hub.work_item.id
    conn = store.connect(hub_dir)
    row = conn.execute("SELECT * FROM item_cases WHERE work_item_id=?", (item_id,)).fetchone()
    if row is None:
        raise NoCase("This tool runs only inside a desk triage, for its own case.")
    case = store.get_case(conn, row["case_id"])
    cfg = erp_config.load(hub_dir)
    erp = erp_config.backend(hub_dir, cfg)
    ctx = ERPContext(hub_id=Path(hub_dir).name.lower(), company=cfg.company, party_scope=case["customer_id"],
                     principal="desk-resolver", warehouses=cfg.warehouses)
    existing = store.get_facts(conn, case["id"], row["resolution"])
    start = max([int(f["fact_id"][1:]) for f in existing] or [0]) + 1
    sheet = facts_lib.FactSheet(observed_at=existing[0]["observed_at"] if existing else "", backend=erp.name,
                                start=start)
    return case, row["resolution"], erp, ctx, sheet, existing


def _save(hub_dir: Path, case: dict, resolution: int, sheet: facts_lib.FactSheet, existing: list[dict]) -> list[dict]:
    """Persist new facts, reusing an existing id for a value already on the sheet."""
    known = {(f["kind"], json.dumps(f["source"], sort_keys=True)): f for f in existing}
    fresh, out = [], []
    for f in sheet.facts:
        dup = known.get((f["kind"], json.dumps(f["source"], sort_keys=True)))
        if dup is not None:
            out.append(dup)
        else:
            fresh.append(f)
            out.append(f)
    if fresh:
        with store.tx(hub_dir) as conn:
            store.save_facts(conn, case["id"], resolution, fresh)
    return out


def _result(facts: list[dict], extra: dict | None = None) -> str:
    body = {"facts": [{"id": f["fact_id"], "kind": f["kind"], "value": f["display"],
                       "source": f"{f['source'].get('doctype')} {f['source'].get('name')}.{f['source'].get('field')}"}
                      for f in facts]}
    body.update(extra or {})
    return json.dumps(body)


def _run(hub_dir: Path, fn) -> str:
    try:
        case, resolution, erp, ctx, sheet, existing = _context(hub_dir)
        extra = fn(case, erp, ctx, sheet) or {}
        return _result(_save(hub_dir, case, resolution, sheet, existing), extra)
    except NoCase as exc:
        return json.dumps({"error": "no_case", "message": str(exc)})
    except ERPError as exc:
        return json.dumps({"error": exc.code, "message": exc.message})


def orders(hub_dir: Path, order_ids: list[str] | None, open_only: bool) -> str:
    def go(case, erp, ctx, sheet):
        recs, missing = [], []
        if order_ids:
            for rid in order_ids[:5]:
                try:
                    r = erp.get_record("sales_orders", rid, ctx)
                    if r["fields"]["docstatus"] == 1:
                        recs.append(r)
                    else:
                        missing.append(rid)
                except ERPError as exc:
                    if exc.code != "not_found":
                        raise
                    missing.append(rid)
        else:
            recs = erp.list_records("sales_orders", {"open_only": bool(open_only), "docstatus": 1, "limit": 5}, ctx)
        c = gather.Context(erp=erp, ctx=ctx, policy=None, today=None, sheet=sheet, owners=None)
        for r in recs:
            gather.order_facts(c, r)
        return {"not_found": missing}
    return _run(hub_dir, go)


def invoice(hub_dir: Path, invoice_id: str) -> str:
    def go(case, erp, ctx, sheet):
        try:
            r = erp.get_record("sales_invoices", invoice_id, ctx)
        except ERPError as exc:
            if exc.code == "not_found":
                return {"not_found": [invoice_id]}
            raise
        if r["fields"]["docstatus"] != 1:
            return {"not_found": [invoice_id]}
        f = r["fields"]
        sheet.erp("invoice", r, "name", r["id"], party=f.get("customer"))
        sheet.erp("posting_date", r, "posting_date", party=f.get("customer"))
        sheet.erp("grand_total", r, "grand_total", currency=f.get("currency"), party=f.get("customer"))
        sheet.erp("outstanding", r, "outstanding_amount", currency=f.get("currency"), party=f.get("customer"))
        return {}
    return _run(hub_dir, go)


def open_invoices(hub_dir: Path, from_date: str | None, to_date: str | None) -> str:
    def go(case, erp, ctx, sheet):
        q = {"docstatus": 1, "outstanding_only": True, "limit": 200}
        if from_date:
            q["date_from"] = from_date
        if to_date:
            q["date_to"] = to_date
        for r in erp.list_records("sales_invoices", q, ctx):
            f = r["fields"]
            sheet.erp("invoice", r, "name", r["id"], party=f.get("customer"))
            sheet.erp("outstanding", r, "outstanding_amount", currency=f.get("currency"), party=f.get("customer"))
        return {}
    return _run(hub_dir, go)


def prices(hub_dir: Path, item_codes: list[str]) -> str:
    def go(case, erp, ctx, sheet):
        try:
            customer = erp.get_record("customers", case["customer_id"], ctx)
        except ERPError:
            customer = None
        from . import config

        c = gather.Context(erp=erp, ctx=ctx, policy=None, today=config.today(hub_dir), sheet=sheet, owners=None,
                           customer=customer)
        missing = []
        for code in (item_codes or [])[:MAX_CODES]:
            p = gather._price(c, code)
            if p is None:
                missing.append(code)
            else:
                sheet.erp("price", p, "price_list_rate", currency=p["fields"]["currency"], party=p["fields"].get("customer"))
        return {"no_valid_price": missing}
    return _run(hub_dir, go)


def availability(hub_dir: Path, item_codes: list[str]) -> str:
    def go(case, erp, ctx, sheet):
        from decimal import Decimal

        pol = policy_lib.load(hub_dir)
        disclosure = pol.category("price_availability")["availability"]["disclosure"]
        if disclosure == "none":
            return {"note": "The policy does not disclose availability."}
        for code in (item_codes or [])[:MAX_CODES]:
            bins = erp.list_records("availability", {"item_codes": [code], "warehouses": list(ctx.warehouses) or None,
                                                     "limit": 20}, ctx)
            total = sum(Decimal(str(b["fields"].get("projected_qty") or 0)) for b in bins)
            src = {"backend": erp.name, "doctype": "Bin", "name": ",".join(b["id"] for b in bins) or code,
                   "field": "projected_qty"}
            if disclosure == "exact":
                sheet.add("availability_qty", str(total), source=src)
            else:
                limit = Decimal(pol.category("price_availability")["availability"]["limited_below"])
                sheet.add("availability_band", "out of stock" if total <= 0 else "limited" if total < limit
                          else "in stock", source=dict(src, banded=True))
        return {}
    return _run(hub_dir, go)


def find_items(hub_dir: Path, text: str) -> str:
    def go(case, erp, ctx, sheet):
        pol = policy_lib.load(hub_dir)
        c = gather.Context(erp=erp, ctx=ctx, policy=pol, today=None, sheet=sheet, owners=None)
        for r in [r for r in gather._find_items(c, text) if not r["fields"].get("disabled")][:10]:
            sheet.erp("item", r, "item_name")
            sheet.erp("item_code", r, "item_code")
        return {}
    return _run(hub_dir, go)


def policy(hub_dir: Path, section: str) -> str:
    def go(case, erp, ctx, sheet):
        pol = policy_lib.load(hub_dir)
        value = policy_lib.data_get(pol.data, section)
        if value is None:
            return {"error": "unknown_section", "message": "Use a dotted key such as refunds.within_days or "
                    "categories.delivery_change.min_notice_days."}
        if isinstance(value, (int, float)) and not isinstance(value, bool) and ("days" in section):
            sheet.policy(section, value, kind="policy_days", display_text=facts_lib.display("days", value))
        else:
            sheet.policy(section, value, display_text=json.dumps(value) if not isinstance(value, str) else value)
        return {"rules": {k: v for k, v in pol.rules.items()}}
    return _run(hub_dir, go)
