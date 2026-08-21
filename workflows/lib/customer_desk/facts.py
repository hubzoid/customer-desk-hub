"""The fact sheet: every value the desk read, with where it came from.

A reply never types a fact. It writes a placeholder such as `[[F3]]`, and the
renderer fills it from this sheet with Babel formatting in the reply
language. Each fact keeps its source (backend, DocType, record, field, child
row) and when it was observed, so a teammate can check it and the desk can
reread it before anything is sent.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
from decimal import Decimal, InvalidOperation

from babel.dates import format_date
from babel.numbers import format_currency, format_decimal, format_percent

LOCALES = {"en": "en_US"}
MAX_FACTS = 200

#: Fact kinds whose value belongs to a customer, checked by `facts_owned`.
PARTY_KINDS = {"order", "order_status", "delivery_date", "per_delivered", "line_item", "qty_ordered",
               "qty_delivered", "invoice", "posting_date", "grand_total", "outstanding", "statement_table",
               "statement_total", "credit_note", "price", "customer_name"}


class FactLimit(Exception):
    pass


def _locale(language: str) -> str:
    return LOCALES.get(language, "en_US")


ORDER_STATUS = {"Draft": "not yet confirmed", "To Deliver and Bill": "confirmed and not yet delivered",
                "To Deliver": "confirmed and not yet delivered", "To Bill": "delivered and awaiting its invoice",
                "Completed": "complete", "Closed": "closed", "On Hold": "on hold", "Cancelled": "cancelled"}
UOMS = {"Nos": "unit", "Unit": "unit", "Box": "box"}


def display(kind: str, value, *, currency: str | None = None, language: str = "en") -> str:
    loc = _locale(language)
    if kind == "order_status" and isinstance(value, str):
        return ORDER_STATUS.get(value, value.lower())
    if kind == "uom" and isinstance(value, str):
        return UOMS.get(value, value.lower())
    try:
        if kind in ("grand_total", "outstanding", "price", "statement_total", "amount") and value is not None:
            return format_currency(Decimal(str(value)), currency or "USD", locale=loc)
        if kind in ("delivery_date", "posting_date", "requested_date", "date", "observed_date") and value:
            return format_date(dt.date.fromisoformat(str(value)[:10]), format="long", locale=loc)
        if kind == "per_delivered" and value is not None:
            return format_percent(Decimal(str(value)) / 100, locale=loc)
        if kind in ("qty_ordered", "qty_delivered", "availability_qty", "quantity") and value is not None:
            return format_decimal(Decimal(str(value)), locale=loc)
        if kind in ("days", "policy_days") and value is not None:
            n = int(value)
            return f"{n} day" if n == 1 else f"{n} days"
    except (InvalidOperation, ValueError):
        pass
    return "" if value is None else str(value)


class FactSheet:
    def __init__(self, *, observed_at: str, backend: str, language: str = "en", start: int = 1):
        self.facts: list[dict] = []
        self.observed_at = observed_at
        self.backend = backend
        self.language = language
        self._next = start
        self._index: dict[tuple, str] = {}

    def add(self, kind: str, value, *, source: dict, display_text: str | None = None, currency: str | None = None,
            party: str | None = None) -> str:
        key = (kind, json.dumps(source, sort_keys=True), json.dumps(value, sort_keys=True, default=str))
        if key in self._index:
            return self._index[key]
        if len(self.facts) >= MAX_FACTS:
            raise FactLimit(f"A resolution holds at most {MAX_FACTS} facts.")
        fid = f"F{self._next}"
        self._next += 1
        src = {"backend": source.get("backend", self.backend), **source}
        if party is not None:
            src["party"] = party
        self.facts.append({"fact_id": fid, "kind": kind, "value": value,
                           "display": display_text if display_text is not None else display(
                               kind, value, currency=currency, language=self.language),
                           "source": src, "observed_at": source.get("observed_at") or self.observed_at})
        self._index[key] = fid
        return fid

    def erp(self, kind: str, rec: dict, field: str, value=None, *, row_id: str | None = None, currency=None,
            display_text: str | None = None, party: str | None = None) -> str:
        """A fact read from an ERP record."""
        src = {"backend": rec["backend"], "doctype": rec["source"]["doctype"], "name": rec["id"], "field": field,
               "observed_at": rec["observed_at"], "modified_at": rec.get("modified_at")}
        if row_id:
            src["row_id"] = row_id
        if value is None:
            value = rec["fields"].get(field)
        return self.add(kind, value, source=src, currency=currency, display_text=display_text, party=party)

    def policy(self, key: str, value, kind: str = "policy", display_text: str | None = None) -> str:
        return self.add(kind, value, source={"backend": "policy", "doctype": "desk-policy", "name": "policy",
                                             "field": key}, display_text=display_text)

    def local(self, kind: str, value, *, name: str, field: str, display_text: str | None = None) -> str:
        """A fact from the desk's own records, such as a ticket number."""
        return self.add(kind, value, source={"backend": "desk", "doctype": "desk", "name": name, "field": field},
                        display_text=display_text)

    def message(self, kind: str, value, *, field: str, display_text: str | None = None) -> str:
        """A value the customer stated, such as a requested date. Shown as theirs, never as an ERP fact."""
        return self.add(kind, value, source={"backend": "message", "doctype": "customer message", "name": "message",
                                             "field": field}, display_text=display_text)

    def by_id(self) -> dict[str, dict]:
        return {f["fact_id"]: f for f in self.facts}

    def digest(self) -> str:
        return digest(self.facts)


def digest(facts: list[dict]) -> str:
    body = [{k: f[k] for k in ("fact_id", "kind", "value", "source")} for f in facts]
    return "sha256:" + hashlib.sha256(json.dumps(body, sort_keys=True, default=str).encode()).hexdigest()


def prompt_table(facts: list[dict]) -> str:
    """The fact sheet as the resolver and reviewer read it."""
    lines = ["| id | kind | value | source |", "|---|---|---|---|"]
    for f in facts:
        s = f["source"]
        where = f"{s.get('doctype')} {s.get('name')}.{s.get('field')}" + (f" row {s['row_id']}" if s.get("row_id") else "")
        shown = f["display"].replace("\n", " / ").replace("|", "/")
        if len(shown) > 160:
            shown = shown[:157] + "..."
        lines.append(f"| {f['fact_id']} | {f['kind']} | {shown} | {where} |")
    return "\n".join(lines)
