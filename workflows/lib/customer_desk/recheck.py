"""Reread every ERP fact a reply relies on, at send-request time and again
just before dispatch. A changed value means the reply is stale: the send is
refused and a new resolution is drafted. This is the approval precondition
recheck applied to ERP facts."""
from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

from . import scope, store
from .erpnext import config as erp_config
from .erpnext.contract import ERPError

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
    support_changes = []
    for fact in facts:
        src = fact.get("source") or {}
        if src.get("backend") == "support" and src.get("kind") == "approved_knowledge":
            import hashlib

            rel = str(src.get("ref") or "").removeprefix("kb:")
            path = (Path(hub_dir) / rel).resolve()
            if (not path.is_relative_to(Path(hub_dir).resolve()) or not path.is_file()
                    or "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest() != src.get("revision")):
                support_changes.append({"fact_id": fact["fact_id"], "was": src.get("revision"), "now": "source changed/removed"})
        if src.get("backend") == "support" and src.get("kind") == "historical_precedent":
            from . import config
            from .helpdesk import desk, retrieval

            try:
                reader, _ = desk.readers(hub_dir, config.settings(hub_dir))
                _, ticket_id, thread_id = src["ref"].split(":", 2)
                ticket = reader.ticket(ticket_id)
                original_scope = src.get("scope") or {}
                if (not retrieval.permitted(ticket, config.settings(hub_dir))
                        or str(ticket.get("departmentId")) != str(original_scope.get("department"))
                        or str(ticket.get("statusType") or ticket.get("status")).lower() not in ("resolved", "closed")):
                    raise ValueError("Historical source scope/status changed")
                current = reader.thread(ticket_id, thread_id)
                names = list((ticket.get("contact") or {}).values())
                text = retrieval.clean(current.get("plainText") or current.get("content") or "", names)
                if current.get("status") == "DRAFT" or current.get("private") or text != src["text"]:
                    raise ValueError("Historical answer changed")
            except Exception:  # A denied/deleted/offline source cannot authorize draft delivery.
                support_changes.append({"fact_id": fact["fact_id"], "was": src.get("ref"), "now": "historical source unavailable/changed"})
    if not any((f.get("source") or {}).get("backend") in ERP_BACKENDS for f in facts):
        return support_changes
    try:
        ctx = scope.erp_context(hub_dir, case, principal="desk-recheck")
    except scope.ScopeError:
        # The sender no longer resolves to exactly this customer: every fact is
        # out of date, and nothing is read for anyone.
        return [{"fact_id": "binding", "was": case.get("customer_id"), "now": "no exact binding"}]
    erp = erp or erp_config.backend(hub_dir)
    cache: dict[tuple, dict | None] = {}
    lists: dict[str, dict[str, dict]] = {}

    def statement(query: dict) -> dict[str, dict]:
        key = json.dumps(query, sort_keys=True)
        if key not in lists:
            recs = erp.list_records("sales_invoices", query, ctx)
            lists[key] = None if getattr(recs, "truncated", False) else {r["id"]: r["fields"] for r in recs}
        return lists[key]

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

    out = list(support_changes)
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
            change = _statement_change(f, src, statement(src["query"]) if src.get("query") else None, names, read)
            if change:
                out.append({"fact_id": f["fact_id"], **change})
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


def _statement_change(f: dict, src: dict, now_open: dict | None, names: list[str], read) -> dict | None:
    """What changed in a statement since it was drafted: the set of open
    invoices or credit notes in the period, an invoice's outstanding amount,
    or a currency total. None when it reads the same."""
    if not src.get("query"):
        # Drafted before statements kept their query: only a closed invoice is detectable.
        for n in names:
            rec = read("sales_invoices", n)
            if rec is None or Decimal(str(rec["fields"].get("outstanding_amount") or 0)) == 0:
                return {"was": n, "now": "no longer open"}
        return None
    if now_open is None:
        return {"was": "statement", "now": "too many open invoices to recheck"}
    if f["kind"] == "statement_total":
        currency = src.get("currency") or str(src.get("field", "")).partition(":")[2]
        total = sum((Decimal(str(r.get("outstanding_amount") or 0)) for r in now_open.values()
                     if not r.get("is_return") and r.get("currency") == currency), Decimal(0))
        return None if total == _num(f["value"]) else {"was": f["value"], "now": str(total)}
    credit = f["kind"] == "credit_note"
    ids = sorted(i for i, r in now_open.items() if bool(r.get("is_return")) == credit)
    if ids != sorted(f["value"]):
        return {"was": ",".join(sorted(f["value"])), "now": ",".join(ids) or "none open"}
    for i, amount in (src.get("amounts") or {}).items():
        if _num(now_open[i].get("outstanding_amount") or 0) != _num(amount):
            return {"was": f"{i} {amount}", "now": f"{i} {now_open[i].get('outstanding_amount')}"}
    return None


def facts_state(hub_dir: Path, case: dict, resolution: int, *, policy=None) -> list:
    """A stable summary for an approval's target version: the changed facts, if any."""
    facts = store.get_facts(store.connect(hub_dir), case["id"], resolution)
    return sorted((c["fact_id"], str(c["now"])) for c in changed_facts(hub_dir, case, facts, policy=policy))
