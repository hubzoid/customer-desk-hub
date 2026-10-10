"""The category rules (HUB-8 section 6.3): for each classified request, read
the bound customer's records, register the facts, and decide the outcome.

This is deterministic code between the stations, as in Mastra's support
workflow: the classifier says what was asked, these rules decide what the
policy allows, and the resolver only words the reply. Every read is scoped to
the case's bound customer through `ERPContext.party_scope`, so a record of
another customer reads as `not_found`.

Owner items (tickets, delivery proposals, exception decisions) are local desk
records. `Owners` creates them idempotently per case, so a rerun reuses them.
"""
from __future__ import annotations

import csv
import datetime as dt
import io
import re
from dataclasses import dataclass, field
from decimal import Decimal

from . import ids
from .erpnext.contract import ERPContext, ERPError
from .facts import FactSheet, display

SEVERITIES = ("low", "normal", "high", "critical")


@dataclass
class Outcome:
    request_no: int
    category: str
    outcome: str
    allowed: list[str]
    rule_refs: list[str]
    slots: dict = field(default_factory=dict)
    facts: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    attachments: list[dict] = field(default_factory=list)
    queue: str | None = None
    questions: list[str] = field(default_factory=list)

    def to_json(self) -> dict:
        return {"request_no": self.request_no, "category": self.category, "outcome": self.outcome,
                "allowed": self.allowed, "rule_refs": self.rule_refs, "slots": self.slots, "facts": self.facts,
                "notes": self.notes, "attachments": self.attachments, "queue": self.queue,
                "questions": self.questions}


class Owners:
    """Creates owner items. The pipeline passes one bound to the store."""

    def ticket(self, *, key: str, severity: str, owner_role: str, summary: str, reason: str) -> dict:
        raise NotImplementedError

    def proposal(self, *, key: str, sales_order: str, scope, observed_date, requested_date: str) -> dict:
        raise NotImplementedError

    def decision(self, *, key: str, kind: str, inputs: dict) -> dict:
        raise NotImplementedError

    def attachment(self, *, name: str, media_type: str, data: bytes) -> dict:
        raise NotImplementedError


@dataclass
class Context:
    erp: object
    ctx: ERPContext
    policy: object
    today: dt.date
    sheet: FactSheet
    owners: Owners
    print_format: str | None = None       # the connector's print_format, a server setting
    customer: dict | None = None
    escalations: list[str] = field(default_factory=list)


def _ids(refs: list[str], kind: str, patterns=None) -> list[str]:
    """Document references as the customer wrote them, cleaned. With the
    policy's id patterns, the matching part is taken from each reference (the
    longest match, see ids.py). `kind` is only a hint and never filters a
    live reference."""
    out = []
    for r in refs or []:
        text = str(r).strip().strip(".,;:#()[]").upper()
        if not text:
            continue
        for ref in ids.find(text, patterns or []) or [text]:
            if ref not in out:
                out.append(ref)
    return out


def _d(value) -> dt.date | None:
    if not value:
        return None
    try:
        return dt.date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def _read(c: Context, resource: str, rid: str) -> dict | None:
    try:
        return c.erp.get_record(resource, rid, c.ctx)
    except ERPError as exc:
        if exc.code == "not_found":
            return None
        raise


def _order_for(c: Context, ref: str) -> dict | None:
    """An order by its ERPNext id, or by the customer's own order number
    (ERPNext's `po_no`). Read whole, with its lines."""
    rec = _read(c, "sales_orders", ref)
    if rec is not None:
        return rec
    found = c.erp.list_records("sales_orders", {"po_no": ref, "limit": 5}, c.ctx)
    if not found:
        return None
    # Prefer a submitted order when a draft and a submitted one share the number.
    best = sorted(found, key=lambda r: (r["fields"].get("docstatus") != 1, r["id"]))[0]
    return _read(c, "sales_orders", best["id"])


def _invoices_for_order(c: Context, ref: str) -> list[dict]:
    """The customer's submitted invoices for an order, by the customer's order
    number on the invoice, or by the order's lines."""
    found = c.erp.list_records("sales_invoices", {"po_no": ref, "docstatus": 1, "limit": 10}, c.ctx)
    if found:
        return [r for r in (_read(c, "sales_invoices", f["id"]) for f in found) if r]
    order = _read(c, "sales_orders", ref)
    if order is None:
        return []
    submitted = c.erp.list_records("sales_invoices", {"docstatus": 1, "limit": 200}, c.ctx)
    out = []
    for s in submitted:
        rec = _read(c, "sales_invoices", s["id"])
        if rec and any(row.get("sales_order") == order["id"] for row in rec["fields"].get("items") or []):
            out.append(rec)
    return out


def _invoice_from(c: Context, req: dict) -> tuple[dict | None, list[str], str | None]:
    """The one invoice a request names: (record, candidates, reference). By
    invoice number first, then as the customer's order number or an order the
    invoice belongs to. A customer often names an invoice by their own order
    number ("the invoice for PC-0031"), so a reference is tried both ways,
    whichever list the classifier put it in."""
    pats = c.policy.data["facts"]["id_patterns"]
    refs = _ids(req["references"]["invoices"], "SINV", pats)
    refs += [r for r in _ids(req["references"]["orders"], "SO", pats) if r not in refs]
    if not refs:
        return None, [], None
    ref = refs[0]
    rec = _read(c, "sales_invoices", ref)
    if rec is not None:
        return rec, [], ref
    found = _invoices_for_order(c, ref)
    if len(found) == 1:
        return found[0], [], ref
    return None, [r["id"] for r in found], ref


# -- order status ---------------------------------------------------------------------

def order_facts(c: Context, rec: dict) -> dict:
    s, f = c.sheet, rec["fields"]
    status_text = None
    per = Decimal(str(f.get("per_delivered") or 0))
    if f.get("status") in ("To Deliver and Bill", "To Deliver") and 0 < per < 100:
        status_text = "confirmed and partly delivered"
    order = s.erp("order", rec, "name", rec["id"], party=f.get("customer"))
    # The customer's own order number (ERPNext's po_no) is what they know the order by.
    ref = s.erp("customer_ref", rec, "po_no", party=f.get("customer")) if f.get("po_no") else order
    slots = {"order": order, "order_ref": ref,
             "order_status": s.erp("order_status", rec, "status", party=f.get("customer"), display_text=status_text),
             "delivery_date": s.erp("delivery_date", rec, "delivery_date", party=f.get("customer")),
             "per_delivered": s.erp("per_delivered", rec, "per_delivered", party=f.get("customer"))}
    lines = []
    for row in f.get("items") or []:
        lines.append({"item": s.erp("line_item", rec, "item_name", row.get("item_name"), row_id=row.get("name"),
                                    party=f.get("customer")),
                      "ordered": s.erp("qty_ordered", rec, "qty", row.get("qty"), row_id=row.get("name"),
                                       party=f.get("customer")),
                      "delivered": s.erp("qty_delivered", rec, "delivered_qty", row.get("delivered_qty"),
                                         row_id=row.get("name"), party=f.get("customer"))})
    slots["lines"] = lines
    return slots


def order_status(c: Context, n: int, req: dict) -> Outcome:
    pol = c.policy.category("order_status")
    out = Outcome(n, "order_status", "answer", ["answer", "not_found", "overdue_ticket", "no_open_orders", "clarify",
                                                "not_confirmed", "cancelled"], ["R3", "R4"])
    refs = _ids(req["references"]["orders"], "SO", c.policy.data["facts"]["id_patterns"])
    recs, missing, drafts, cancelled = [], [], [], []
    if refs:
        for rid in refs[: pol["max_orders"]]:
            rec = _order_for(c, rid)
            if rec is None:
                missing.append(rid)
            elif rec["fields"]["docstatus"] == 0:
                drafts.append((rid, rec))
            elif rec["fields"]["docstatus"] == 2:
                cancelled.append((rid, rec))
            else:
                recs.append(rec)
    else:
        found = c.erp.list_records("sales_orders", {"open_only": True, "limit": 50}, c.ctx)
        found.sort(key=lambda r: (r["fields"].get("transaction_date") or "", r["id"]), reverse=True)
        recs = [r for r in (_read(c, "sales_orders", f["id"]) for f in found[: pol["max_orders"]]) if r]
    for rid in missing:
        out.slots.setdefault("not_found", []).append(c.sheet.message("reference", rid, field="order reference"))
    for rid, rec in drafts:
        out.notes.append(f"Order {rid} is a draft in ERPNext ({rec['id']}). Confirm it before telling the customer "
                         "a date.")
    for rid, rec in cancelled:
        out.notes.append(f"Order {rid} ({rec['id']}) is cancelled in ERPNext. Check why before the reply goes.")
    if not recs:
        if drafts or cancelled:
            rid, rec = (drafts or cancelled)[0]
            out.outcome = "not_confirmed" if drafts else "cancelled"
            out.rule_refs = ["R3", "R19"]
            out.slots["reference"] = c.sheet.message("reference", rid, field="order reference")
            out.queue = "operators"
            return out
        out.outcome = "not_found" if missing else "no_open_orders"
        out.rule_refs = ["R1", "R4"] if missing else ["R4"]
        return out
    out.slots["orders"] = []
    overdue = []
    for rec in recs:
        slots = order_facts(c, rec)
        out.slots["orders"].append(slots)
        f = rec["fields"]
        due = _d(f.get("delivery_date"))
        undelivered = any(Decimal(str(r.get("delivered_qty") or 0)) < Decimal(str(r.get("qty") or 0))
                          for r in f.get("items") or [])
        if due and due < c.today and undelivered:
            overdue.append(rec)
    if overdue:
        out.rule_refs = ["R3", "R4", "R5"]
        if pol["overdue_action"] == "ticket":
            for rec in overdue:
                t = c.owners.ticket(key=f"overdue:{rec['id']}", severity="normal", owner_role="delivery",
                                    summary=f"Order {rec['id']} is past its delivery date with lines undelivered",
                                    reason="overdue_order")
                out.slots["ticket"] = c.sheet.local("ticket", t["number"], name=t["number"], field="number")
            out.outcome = "overdue_ticket"
            out.queue = "delivery"
        else:
            out.outcome = "answer"
            out.notes.append("The order is overdue. Policy says reply only, no ticket.")
    if missing and out.outcome == "answer":
        out.notes.append(f"Not found under this account: {', '.join(missing)}.")
    return out


# -- invoice copy -----------------------------------------------------------------------

def invoice_copy(c: Context, n: int, req: dict) -> Outcome:
    pol = c.policy.category("invoice_copy")
    out = Outcome(n, "invoice_copy", "send_copy", ["send_copy", "not_found", "too_old", "clarify"], ["R3", "R6"])
    rec, candidates, rid = _invoice_from(c, req)
    if rid is None or len(_ids(req["references"]["invoices"], "SINV", c.policy.data["facts"]["id_patterns"])) > 1:
        out.outcome = "clarify"
        out.rule_refs = ["R17"]
        out.questions.append("Which invoice number would you like a copy of?")
        return out
    if candidates:
        out.outcome = "clarify"
        out.rule_refs = ["R6", "R17"]
        out.notes.append(f"Order {rid} has more than one invoice: {', '.join(candidates)}.")
        out.questions.append("That order has more than one invoice. Which invoice number would you like?")
        return out
    if rec is None or rec["fields"]["docstatus"] != 1:
        out.outcome = "not_found"
        out.rule_refs = ["R7"]
        out.slots["reference"] = c.sheet.message("reference", rid, field="invoice reference")
        return out
    f = rec["fields"]
    cur = f.get("currency")
    party = f.get("customer")
    out.slots.update({
        "invoice": c.sheet.erp("invoice", rec, "name", rec["id"], party=party),
        "posting_date": c.sheet.erp("posting_date", rec, "posting_date", party=party),
        "grand_total": c.sheet.erp("grand_total", rec, "grand_total", currency=cur, party=party),
        "outstanding": c.sheet.erp("outstanding", rec, "outstanding_amount", currency=cur, party=party)})
    posted = _d(f.get("posting_date"))
    if posted and (c.today - posted).days > pol["max_age_days"]:
        out.outcome = "too_old"
        out.slots["max_age"] = c.sheet.policy("categories.invoice_copy.max_age_days", pol["max_age_days"],
                                              kind="policy_days", display_text=display("days", pol["max_age_days"]))
        return out
    data = c.erp.get_print_pdf("sales_invoices", rec["id"], c.print_format, c.ctx)
    att = c.owners.attachment(name=f"{rec['id']}.pdf", media_type="application/pdf", data=data)
    att["source"] = {"doctype": "Sales Invoice", "name": rec["id"], "print_format": c.print_format or "Standard",
                     "backend": rec["backend"]}
    out.attachments.append(att)
    return out


# -- account statement ---------------------------------------------------------------------

STATEMENT_LIMIT = 200

def account_statement(c: Context, n: int, req: dict) -> Outcome:
    pol = c.policy.category("account_statement")
    out = Outcome(n, "account_statement", "statement", ["statement", "no_open_invoices", "clarify"], ["R3", "R8"])
    dates = req["references"]["dates"]
    to = _d(dates.get("to")) or c.today
    frm = _d(dates.get("from")) or (to - dt.timedelta(days=pol["max_range_days"]))
    if (to - frm).days > pol["max_range_days"]:
        frm = to - dt.timedelta(days=pol["max_range_days"])
        out.notes.append("The requested period was longer than policy allows, so it was shortened.")
    query = {"docstatus": 1, "outstanding_only": True, "date_from": frm.isoformat(), "date_to": to.isoformat(),
             "limit": STATEMENT_LIMIT}
    recs = c.erp.list_records("sales_invoices", query, c.ctx)
    if getattr(recs, "truncated", False):
        out.outcome = "clarify"
        out.notes.append(f"More than {STATEMENT_LIMIT} open invoices in the period. The desk does not send a partial "
                         "statement. Send it from ERPNext, or ask the customer for a shorter period.")
        return out
    open_, credits = [r for r in recs if not r["fields"].get("is_return")], [r for r in recs if r["fields"].get("is_return")]
    out.slots["period_from"] = c.sheet.add("date", frm.isoformat(), source={"backend": "desk", "doctype": "desk",
                                                                          "name": "statement", "field": "from"})
    out.slots["period_to"] = c.sheet.add("date", to.isoformat(), source={"backend": "desk", "doctype": "desk",
                                                                       "name": "statement", "field": "to"})
    if not open_ and not credits:
        out.outcome = "no_open_invoices"
        return out

    def table(rows):
        lines = ["| Invoice | Date | Due | Total | Outstanding |", "|---|---|---|---|---|"]
        for r in rows:
            f = r["fields"]
            lines.append(f"| {r['id']} | {display('posting_date', f['posting_date'])} | "
                         f"{display('posting_date', f['due_date'])} | "
                         f"{display('grand_total', f['grand_total'], currency=f['currency'])} | "
                         f"{display('outstanding', f['outstanding_amount'], currency=f['currency'])} |")
        return "\n".join(lines)

    # The query and each invoice's outstanding amount travel with the facts, so
    # the send-time recheck relists the same period and catches a payment, a
    # new invoice or a credit note, not only an invoice that closed.
    src = {"backend": recs[0]["backend"], "doctype": "Sales Invoice", "name": ",".join(r["id"] for r in recs),
           "field": "outstanding_amount", "observed_at": recs[0]["observed_at"], "query": query}

    def amounts(rows):
        return {r["id"]: str(Decimal(str(r["fields"]["outstanding_amount"]))) for r in rows}

    party = c.ctx.party_scope
    if open_:
        out.slots["table"] = c.sheet.add("statement_table", [r["id"] for r in open_], source=dict(src, name=",".join(
            r["id"] for r in open_), amounts=amounts(open_)), display_text=table(open_), party=party)
        totals: dict[str, Decimal] = {}
        for r in open_:
            totals[r["fields"]["currency"]] = totals.get(r["fields"]["currency"], Decimal(0)) + Decimal(
                str(r["fields"]["outstanding_amount"]))
        out.slots["totals"] = [c.sheet.add("statement_total", str(v), source=dict(src, field=f"total:{k}", currency=k),
                                           currency=k, party=party) for k, v in sorted(totals.items())]
    if credits:
        out.slots["credit_notes"] = c.sheet.add("credit_note", [r["id"] for r in credits],
                                                source=dict(src, name=",".join(r["id"] for r in credits),
                                                            amounts=amounts(credits)),
                                                display_text=table(credits), party=party)
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["invoice", "posting_date", "due_date", "currency", "grand_total", "outstanding_amount", "is_return"])
    for r in open_ + credits:
        f = r["fields"]
        w.writerow([r["id"], f["posting_date"], f["due_date"], f["currency"], f["grand_total"], f["outstanding_amount"],
                    int(bool(f.get("is_return")))])
    att = c.owners.attachment(name="open-invoices.csv", media_type="text/csv", data=buf.getvalue().encode())
    att["source"] = {"doctype": "Sales Invoice", "name": "statement", "backend": recs[0]["backend"]}
    out.attachments.append(att)
    # When the desk read ERPNext: desk metadata, not an invoice field.
    out.slots["observed"] = c.sheet.add("observed", c.sheet.observed_at[:10],
                                        source={"backend": "desk", "doctype": "desk", "name": "statement",
                                                "field": "observed_at"},
                                        display_text=display("date", c.sheet.observed_at[:10]))
    return out


# -- price and availability ------------------------------------------------------------

def _stem(word: str) -> str:
    """A plain English plural stem: boxes and box, pallets and pallet, crates and crate."""
    for end in ("xes", "ses", "shes", "ches", "zes"):
        if word.endswith(end) and len(word) > len(end) + 1:
            return word[: -2]
    if word.endswith("ies") and len(word) > 4:
        return word[:-3] + "y"
    return word[:-1] if word.endswith("s") and not word.endswith("ss") and len(word) > 3 else word


def _find_items(c: Context, text: str) -> list[dict]:
    text = (text or "").strip()
    codes = ids.find(text, c.policy.data["facts"]["id_patterns"])
    for code in codes:
        rec = _read(c, "items", code)
        if rec:
            return [rec]
    words = [w for w in re.findall(r"[a-z0-9]+", text.casefold()) if len(w) > 2 and w not in
             {"the", "and", "for", "your", "you", "what", "price", "stock", "have", "any", "our", "how", "much", "many",
              "units", "unit", "please", "synthetic", "available"}]
    if not words:
        return []
    every = c.erp.list_records("items", {"limit": 200}, c.ctx)
    scored = []
    for rec in every:
        name = (rec["fields"].get("item_name") or "").casefold()
        stems = {_stem(w) for w in re.findall(r"[a-z0-9]+", name)}
        hits = sum(1 for w in words if _stem(w) in stems)
        if hits:
            scored.append((hits, rec))
    if not scored:
        return []
    best = max(h for h, _ in scored)
    return [r for h, r in sorted(scored, key=lambda x: x[1]["id"]) if h == best][:10]


def _price(c: Context, item_code: str) -> dict | None:
    cust = c.customer or {}
    price_list = (cust.get("fields") or {}).get("default_price_list")
    rows = c.erp.list_records("prices", {"item_codes": [item_code], "limit": 50}, c.ctx)
    today = c.today.isoformat()
    valid = [r for r in rows if (r["fields"].get("valid_from") or "0000") <= today
             and (r["fields"].get("valid_upto") in (None, "") or r["fields"]["valid_upto"] >= today)]
    specific = [r for r in valid if r["fields"].get("customer") == c.ctx.party_scope]
    if specific:
        return sorted(specific, key=lambda r: r["id"])[0]
    listed = [r for r in valid if r["fields"].get("price_list") == price_list and not r["fields"].get("customer")]
    return sorted(listed, key=lambda r: r["id"])[0] if listed else None


def price_availability(c: Context, n: int, req: dict) -> Outcome:
    pol = c.policy.category("price_availability")
    out = Outcome(n, "price_availability", "quote", ["quote", "candidates", "not_quotable", "clarify"],
                  ["R3", "R9", "R10"])
    wanted = req["references"]["items"] or []
    if not wanted:
        out.outcome = "clarify"
        out.rule_refs = ["R11", "R17"]
        out.questions.append("Which item would you like a price or stock check for?")
        return out
    out.slots["items"] = []
    disclosure = pol["availability"]["disclosure"]
    any_candidates = False
    any_quoted = False
    any_unknown = False
    for want in wanted[:20]:
        found = _find_items(c, want.get("text", ""))
        active = [r for r in found if not r["fields"].get("disabled")]
        if len(found) == 1 and found[0]["fields"].get("disabled"):
            out.slots["items"].append({"item": c.sheet.erp("item", found[0], "item_name"), "quotable": False})
            out.notes.append(f"{found[0]['id']} is disabled and cannot be quoted.")
            continue
        if not active:
            any_unknown = True
            out.slots["items"].append({"asked": c.sheet.message("item_text", want.get("text", ""), field="item text"),
                                       "unknown": True})
            continue
        if len(active) > 1:
            any_candidates = True
            out.slots["items"].append({"asked": c.sheet.message("item_text", want.get("text", ""), field="item text"),
                                       "candidates": [c.sheet.erp("item", r, "item_name") for r in active]})
            continue
        item = active[0]
        entry = {"item": c.sheet.erp("item", item, "item_name"), "code": c.sheet.erp("item_code", item, "item_code")}
        if pol["price_source"] == "customer_price_list":
            price = _price(c, item["id"])
            if price is not None:
                entry["price"] = c.sheet.erp("price", price, "price_list_rate", currency=price["fields"]["currency"],
                                             party=price["fields"].get("customer"))
                entry["uom"] = c.sheet.erp("uom", price, "uom")
            else:
                entry["price"] = None
                out.notes.append(f"No valid price for {item['id']} on this customer's price list.")
        if disclosure != "none":
            bins = c.erp.list_records("availability", {"item_codes": [item["id"]],
                                                       "warehouses": list(c.ctx.warehouses) or None, "limit": 20},
                                      c.ctx)
            total = sum(Decimal(str(b["fields"].get("projected_qty") or 0)) for b in bins)
            src = {"backend": bins[0]["backend"] if bins else c.sheet.backend, "doctype": "Bin",
                   "name": ",".join(b["id"] for b in bins) or item["id"], "field": "projected_qty",
                   "observed_at": bins[0]["observed_at"] if bins else c.sheet.observed_at}
            entry["availability_kind"] = disclosure
            if disclosure == "exact" and total <= 0:
                # Nothing to count: say out of stock rather than "0 available".
                entry["availability_kind"] = "band"
                entry["availability"] = c.sheet.add("availability_band", "out of stock", source=dict(src, banded=True))
            elif disclosure == "exact":
                entry["availability"] = c.sheet.add("availability_qty", str(total), source=src)
            else:
                limit = Decimal(pol["availability"]["limited_below"])
                band = "out of stock" if total <= 0 else "limited" if total < limit else "in stock"
                entry["availability"] = c.sheet.add("availability_band", band, source=dict(src, banded=True))
        any_quoted = True
        out.slots["items"].append(entry)
    if any_candidates and not any_quoted:
        out.outcome = "candidates"
        out.rule_refs = ["R11"]
        out.questions.append("Which of these items do you mean?")
    elif any_candidates:
        out.notes.append("Some items matched more than one product. Ask which one.")
        out.questions.append("Which of these items do you mean?")
    elif any_unknown and not any_quoted:
        out.outcome = "clarify"
        out.rule_refs = ["R11", "R17"]
        out.questions.append("We could not find that item. Could you send its item code or full name?")
    elif not any_quoted:
        out.outcome = "not_quotable"
        out.rule_refs = ["R9"]
    if any_unknown and any_quoted:
        out.notes.append("Some item names matched nothing. Ask for the item code.")
    return out


# -- delivery change -------------------------------------------------------------------

def delivery_change(c: Context, n: int, req: dict) -> Outcome:
    pol = c.policy.category("delivery_change")
    out = Outcome(n, "delivery_change", "proposal", ["proposal", "rule_refusal", "already_delivered", "not_found",
                                                     "clarify", "confirmed", "declined"], ["R3", "R12"])
    refs = _ids(req["references"]["orders"], "SO", c.policy.data["facts"]["id_patterns"])
    if len(refs) != 1:
        out.outcome = "clarify"
        out.rule_refs = ["R17"]
        out.questions.append("Which order should we move, and to which date?")
        return out
    rec = _order_for(c, refs[0])
    if rec is None or rec["fields"]["docstatus"] != 1:
        out.outcome = "not_found"
        out.rule_refs = ["R1", "R12"]
        out.slots["reference"] = c.sheet.message("reference", refs[0], field="order reference")
        return out
    f = rec["fields"]
    party = f.get("customer")
    out.slots["order"] = c.sheet.erp("order", rec, "name", rec["id"], party=party)
    out.slots["order_ref"] = (c.sheet.erp("customer_ref", rec, "po_no", party=party) if f.get("po_no")
                              else out.slots["order"])
    out.slots["delivery_date"] = c.sheet.erp("delivery_date", rec, "delivery_date", party=party)
    if Decimal(str(f.get("per_delivered") or 0)) >= 100:
        out.outcome = "already_delivered"
        out.rule_refs = ["R13"]
        return out
    requested = _d(req["references"]["dates"].get("requested_delivery"))
    if requested is None:
        out.outcome = "clarify"
        out.rule_refs = ["R12", "R17"]
        out.questions.append("Which date would you like the order delivered on?")
        return out
    out.slots["requested_date"] = c.sheet.message("requested_date", requested.isoformat(), field="requested date")
    notice = pol["min_notice_days"]
    if (requested - c.today).days < notice:
        out.outcome = "rule_refusal"
        out.rule_refs = ["R12", "R13"]
        out.slots["min_notice"] = c.sheet.policy("categories.delivery_change.min_notice_days", notice,
                                                 kind="policy_days", display_text=display("days", notice))
        return out
    p = c.owners.proposal(key=f"delivery:{rec['id']}:{requested.isoformat()}", sales_order=rec["id"],
                          scope={"whole_order": True}, requested_date=requested.isoformat(),
                          observed_date={"fact_id": out.slots["delivery_date"], "value": f.get("delivery_date")})
    out.slots["proposal"] = p["id"]
    if p["state"] == "verified" and f.get("delivery_date") == requested.isoformat():
        # ERPNext now holds the requested date: confirm it, quoting ERPNext's value.
        out.outcome = "confirmed"
        out.rule_refs = ["R3", "R12"]
        return out
    if p["state"] == "declined":
        out.outcome = "declined"
        out.rule_refs = ["R12", "R13"]
        out.slots["reason"] = c.sheet.local("note", p.get("note") or "", name=p["id"], field="note")
        return out
    out.queue = "delivery"
    return out


# -- complaint -----------------------------------------------------------------------------

def complaint(c: Context, n: int, req: dict, *, severity_floor: str = "normal") -> Outcome:
    pol = c.policy.category("complaint")
    out = Outcome(n, "complaint", "ticket", ["ticket", "refund_to_accounts", "refund_decision", "exception_approved",
                                             "exception_declined"], ["R14"])
    severity = max(pol["default_severity"], severity_floor, key=SEVERITIES.index)
    if c.escalations:
        severity = max(severity, "high", key=SEVERITIES.index)
    t = c.owners.ticket(key=f"complaint:{n}", severity=severity, owner_role="complaints",
                        summary=(req.get("summary") or "Customer complaint")[:200], reason="complaint")
    out.slots["ticket"] = c.sheet.local("ticket", t["number"], name=t["number"], field="number")
    out.queue = "complaints"
    if not req.get("refund_requested"):
        return out
    refunds = c.policy.data["refunds"]
    inv, _candidates, ref = _invoice_from(c, req)
    if inv is None or inv["fields"]["docstatus"] != 1:
        out.outcome = "refund_decision"
        out.rule_refs = ["R14", "R15"]
        out.notes.append("Refund requested without one invoice under this account. The exception team decides.")
        d = c.owners.decision(key=f"refund:{n}", kind="refund_exception",
                              inputs={"invoice": None, "reference": ref, "days_elapsed": None,
                                      "within_days": refunds["within_days"], "amount_text": req.get("amount_text"),
                                      "reason": "no_invoice"})
        out.slots["decision"] = d["id"]
        out.queue = "decisions"
        _decided(c, out, d)
        return out
    f = inv["fields"]
    out.slots["invoice"] = c.sheet.erp("invoice", inv, "name", inv["id"], party=f.get("customer"))
    out.slots["posting_date"] = c.sheet.erp("posting_date", inv, "posting_date", party=f.get("customer"))
    elapsed = (c.today - _d(f["posting_date"])).days
    out.slots["within_days"] = c.sheet.policy("refunds.within_days", refunds["within_days"], kind="policy_days",
                                              display_text=display("days", refunds["within_days"]))
    cap = refunds.get("max_amount")
    over = cap is not None and Decimal(str(f.get("grand_total") or 0)) > Decimal(str(cap))
    if elapsed <= refunds["within_days"] and not over:
        out.outcome = "refund_to_accounts"
        out.rule_refs = ["R14", "R15"]
        out.notes.append(f"Refund within policy ({elapsed} days after the invoice). Accounts confirm.")
    else:
        out.outcome = "refund_decision"
        out.rule_refs = ["R14", "R15"]
        reason = "above_max_amount" if over and elapsed <= refunds["within_days"] else "outside_window"
        out.notes.append("Refund " + ("above the policy amount" if reason == "above_max_amount" else
                                      f"outside the {refunds['within_days']} day window") + ". The exception team decides.")
        d = c.owners.decision(key=f"refund:{inv['id']}", kind="refund_exception",
                              inputs={"invoice": inv["id"], "invoice_fact_id": out.slots["invoice"],
                                      "days_elapsed": elapsed, "within_days": refunds["within_days"],
                                      "max_amount": cap, "reason": reason, "amount_text": req.get("amount_text")})
        out.slots["decision"] = d["id"]
        out.queue = "decisions"
        _decided(c, out, d)
    return out


def _decided(c: Context, out: Outcome, d: dict) -> None:
    """A recorded exception decision changes the outcome. The reply then says
    what the named person decided, and only that."""
    if d.get("state") == "approved":
        out.outcome = "exception_approved"
        out.queue = "complaints"
        out.slots["decided"] = c.sheet.local("decision", "approved", name=d["id"], field="state")
    elif d.get("state") == "declined":
        out.outcome = "exception_declined"
        out.queue = "complaints"
        out.slots["decided"] = c.sheet.local("decision", "declined", name=d["id"], field="state")


def other(c: Context, n: int, req: dict) -> Outcome:
    return Outcome(n, "other", "acknowledge", ["acknowledge", "clarify"], ["R17"], queue="operators")


RULES = {"order_status": order_status, "invoice_copy": invoice_copy, "account_statement": account_statement,
         "price_availability": price_availability, "delivery_change": delivery_change, "complaint": complaint,
         "other": other}

QUEUE_ORDER = ("decisions", "delivery", "complaints", "operators")


def run(c: Context, requests: list[dict], *, max_requests: int) -> tuple[list[Outcome], list[str]]:
    """Every request's outcome, and operator notes for anything dropped."""
    notes = []
    outcomes = []
    for n, req in enumerate(requests[:max_requests], start=1):
        cat = req["category"]
        if cat != "other" and not c.policy.category(cat)["enabled"]:
            o = Outcome(n, cat, "acknowledge", ["acknowledge"], ["R17"], queue="operators")
            o.notes.append(f"The {cat} category is switched off in the policy.")
        else:
            o = RULES[cat](c, n, req)
        outcomes.append(o)
    if len(requests) > max_requests:
        notes.append(f"{len(requests) - max_requests} more requests were in the message than the desk handles per "
                     "case. An operator should read the message.")
    return outcomes, notes


def queue_for(outcomes: list[Outcome], escalated: bool) -> str:
    queues = {o.queue for o in outcomes if o.queue}
    if escalated:
        queues.add("complaints")
    for q in QUEUE_ORDER:
        if q in queues:
            return q
    return "operators"
