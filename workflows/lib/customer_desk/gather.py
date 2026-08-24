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
    print_format: str = "Standard"
    customer: dict | None = None
    escalations: list[str] = field(default_factory=list)


def _ids(refs: list[str], kind: str, patterns=None) -> list[str]:
    """Document references as the customer wrote them, cleaned. With the
    policy's id patterns, the matching part is taken from each reference.
    `kind` is only a hint for the sample naming series and never filters a
    live reference."""
    out = []
    compiled = [re.compile(p, re.I) for p in (patterns or [])]
    for r in refs or []:
        text = str(r).strip().strip(".,;:#()[]").upper()
        if not text:
            continue
        found = [m.group(0).upper() for p in compiled for m in p.finditer(text)]
        for ref in found or [text]:
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


# -- order status ---------------------------------------------------------------------

def order_facts(c: Context, rec: dict) -> dict:
    s, f = c.sheet, rec["fields"]
    status_text = None
    per = Decimal(str(f.get("per_delivered") or 0))
    if f.get("status") in ("To Deliver and Bill", "To Deliver") and 0 < per < 100:
        status_text = "confirmed and partly delivered"
    slots = {"order": s.erp("order", rec, "name", rec["id"], party=f.get("customer")),
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
    out = Outcome(n, "order_status", "answer", ["answer", "not_found", "overdue_ticket", "no_open_orders", "clarify"],
                  ["R3", "R4"])
    refs = _ids(req["references"]["orders"], "SO", c.policy.data["facts"]["id_patterns"])
    recs, missing = [], []
    if refs:
        for rid in refs[: pol["max_orders"]]:
            rec = _read(c, "sales_orders", rid)
            if rec is None or rec["fields"]["docstatus"] != 1:
                missing.append(rid)
            else:
                recs.append(rec)
    else:
        found = c.erp.list_records("sales_orders", {"open_only": True, "limit": 50}, c.ctx)
        found.sort(key=lambda r: (r["fields"].get("transaction_date") or "", r["id"]), reverse=True)
        recs = found[: pol["max_orders"]]
    for rid in missing:
        out.slots.setdefault("not_found", []).append(c.sheet.message("reference", rid, field="order reference"))
    if not recs:
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
    refs = _ids(req["references"]["invoices"], "SINV", c.policy.data["facts"]["id_patterns"])
    if len(refs) != 1:
        out.outcome = "clarify"
        out.rule_refs = ["R17"]
        out.questions.append("Which invoice number would you like a copy of?")
        return out
    rid = refs[0]
    rec = _read(c, "sales_invoices", rid)
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
    att["source"] = {"doctype": "Sales Invoice", "name": rec["id"], "print_format": c.print_format,
                     "backend": rec["backend"]}
    out.attachments.append(att)
    return out


# -- account statement ---------------------------------------------------------------------

def account_statement(c: Context, n: int, req: dict) -> Outcome:
    pol = c.policy.category("account_statement")
    out = Outcome(n, "account_statement", "statement", ["statement", "no_open_invoices", "clarify"], ["R3", "R8"])
    dates = req["references"]["dates"]
    to = _d(dates.get("to")) or c.today
    frm = _d(dates.get("from")) or (to - dt.timedelta(days=pol["max_range_days"]))
    if (to - frm).days > pol["max_range_days"]:
        frm = to - dt.timedelta(days=pol["max_range_days"])
        out.notes.append("The requested period was longer than policy allows, so it was shortened.")
    recs = c.erp.list_records("sales_invoices", {"docstatus": 1, "outstanding_only": True, "date_from": frm.isoformat(),
                                                  "date_to": to.isoformat(), "limit": 200}, c.ctx)
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

    src = {"backend": recs[0]["backend"], "doctype": "Sales Invoice", "name": ",".join(r["id"] for r in recs),
           "field": "outstanding_amount", "observed_at": recs[0]["observed_at"]}
    party = c.ctx.party_scope
    if open_:
        out.slots["table"] = c.sheet.add("statement_table", [r["id"] for r in open_], source=dict(src, name=",".join(
            r["id"] for r in open_)), display_text=table(open_), party=party)
        totals: dict[str, Decimal] = {}
        for r in open_:
            totals[r["fields"]["currency"]] = totals.get(r["fields"]["currency"], Decimal(0)) + Decimal(
                str(r["fields"]["outstanding_amount"]))
        out.slots["totals"] = [c.sheet.add("statement_total", str(v), source=dict(src, field=f"total:{k}"),
                                           currency=k, party=party) for k, v in sorted(totals.items())]
    if credits:
        out.slots["credit_notes"] = c.sheet.add("credit_note", [r["id"] for r in credits],
                                                source=dict(src, name=",".join(r["id"] for r in credits)),
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
    out.slots["observed"] = c.sheet.add("observed", c.sheet.observed_at[:10], source=dict(src, field="observed_at"),
                                        display_text=display("date", c.sheet.observed_at[:10]))
    return out


# -- price and availability ------------------------------------------------------------

def _find_items(c: Context, text: str) -> list[dict]:
    text = (text or "").strip()
    codes = [m.group(0).upper() for p in c.policy.data["facts"]["id_patterns"]
             for m in re.finditer(p, text, re.I)]
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
        stems = {w.rstrip("s") for w in re.findall(r"[a-z0-9]+", name)}
        hits = sum(1 for w in words if w.rstrip("s") in stems)
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
    for want in wanted[:20]:
        found = _find_items(c, want.get("text", ""))
        active = [r for r in found if not r["fields"].get("disabled")]
        if len(found) == 1 and found[0]["fields"].get("disabled"):
            out.slots["items"].append({"item": c.sheet.erp("item", found[0], "item_name"), "quotable": False})
            out.notes.append(f"{found[0]['id']} is disabled and cannot be quoted.")
            continue
        if len(active) != 1:
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
            if disclosure == "exact":
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
    elif not any_quoted:
        out.outcome = "not_quotable"
        out.rule_refs = ["R9"]
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
    rec = _read(c, "sales_orders", refs[0])
    if rec is None or rec["fields"]["docstatus"] != 1:
        out.outcome = "not_found"
        out.rule_refs = ["R1", "R12"]
        out.slots["reference"] = c.sheet.message("reference", refs[0], field="order reference")
        return out
    f = rec["fields"]
    party = f.get("customer")
    out.slots["order"] = c.sheet.erp("order", rec, "name", rec["id"], party=party)
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
    refs = _ids(req["references"]["invoices"], "SINV", c.policy.data["facts"]["id_patterns"])
    inv = _read(c, "sales_invoices", refs[0]) if refs else None
    if inv is None or inv["fields"]["docstatus"] != 1:
        out.outcome = "refund_decision"
        out.rule_refs = ["R14", "R15"]
        out.notes.append("Refund requested without an invoice under this account. The exception team decides.")
        d = c.owners.decision(key=f"refund:{n}", kind="refund_exception",
                              inputs={"invoice": refs[0] if refs else None, "days_elapsed": None,
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
    if elapsed <= refunds["within_days"]:
        out.outcome = "refund_to_accounts"
        out.rule_refs = ["R14", "R15"]
        out.notes.append(f"Refund within policy ({elapsed} days after the invoice). Accounts confirm.")
    else:
        out.outcome = "refund_decision"
        out.rule_refs = ["R14", "R15"]
        d = c.owners.decision(key=f"refund:{inv['id']}", kind="refund_exception",
                              inputs={"invoice": inv["id"], "invoice_fact_id": out.slots["invoice"],
                                      "days_elapsed": elapsed, "within_days": refunds["within_days"],
                                      "amount_text": req.get("amount_text")})
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
