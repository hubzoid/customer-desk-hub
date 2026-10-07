"""Sender bindings: which email address or phone number speaks for which ERP
customer. Personal data, so they live in the operational store, never in Git.

A case binds only when exactly one active binding matches the sender. None or
more than one leaves the case `binding_required` and nothing about any
customer is read. A model never chooses the customer.
"""
from __future__ import annotations

import csv
import io
import re
import time

from . import store

KINDS = ("email", "whatsapp", "helpdesk")
CSV_COLUMNS = ["company", "channel_kind", "sender", "customer_id", "source_ref"]
#: The ERP dataset's own format (distributor-v1 bindings.csv), with the party type spelled out.
PARTY_COLUMNS = ["company", "channel_kind", "sender", "party_type", "party_id", "source_ref"]
MAX_IMPORT_ROWS = 10000
E164 = re.compile(r"^\+[1-9][0-9]{6,14}$")
EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class BindingError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code, self.message = code, message


def sender_key(kind: str, raw: str) -> str:
    """The normalised sender: an email with its domain lowercased and IDNA
    encoded (local part preserved), or an E.164 number. Helpdesk contacts are
    keyed by their email address."""
    raw = (raw or "").strip()
    if kind in ("email", "helpdesk"):
        m = re.search(r"<([^>]+)>", raw)
        addr = (m.group(1) if m else raw).strip()
        if not EMAIL.match(addr):
            raise BindingError("binding_invalid", f"{raw!r} is not an email address.")
        local, _, domain = addr.rpartition("@")
        try:
            domain = domain.encode("idna").decode("ascii").lower()
        except UnicodeError:
            raise BindingError("binding_invalid", f"{raw!r} has an invalid domain.") from None
        return f"{local}@{domain}"
    if kind == "whatsapp":
        digits = "+" + re.sub(r"\D", "", raw)
        if not E164.match(digits):
            raise BindingError("binding_invalid", f"{raw!r} is not an E.164 phone number.")
        return digits
    raise BindingError("binding_invalid", f"channel_kind must be one of {', '.join(KINDS)}.")


def channel_kind_for(surface: str) -> str:
    return {"email": "email", "sample-email": "email", "whatsapp": "whatsapp", "helpdesk": "helpdesk"}.get(surface,
                                                                                                         surface)


def lookup(conn, company: str, kind: str, key: str) -> list[dict]:
    """Active bindings for this sender. A helpdesk contact also matches the
    email bindings for the same address, since it is the same mailbox."""
    kinds = ("helpdesk", "email") if kind == "helpdesk" else (kind,)
    return store.rows(conn.execute(
        f"SELECT * FROM bindings WHERE state='active' AND company=? AND sender_key=? AND channel_kind IN "
        f"({', '.join('?' for _ in kinds)}) ORDER BY created", (company, key, *kinds)))


def resolve(conn, company: str, kind: str, key: str) -> tuple[dict | None, list[str]]:
    """(binding, candidates): the binding when exactly one customer matches."""
    found = lookup(conn, company, kind, key)
    customers = sorted({b["customer_id"] for b in found})
    if len(customers) == 1:
        return found[0], customers
    return None, customers


def add(conn, *, company: str, channel_kind: str, sender: str, customer_id: str, actor: str,
        source_ref: str | None = None, synthetic: bool = False) -> dict:
    key = sender_key(channel_kind, sender)
    existing = conn.execute("SELECT * FROM bindings WHERE state='active' AND company=? AND channel_kind=? AND "
                            "sender_key=? AND customer_id=?", (company, channel_kind, key, customer_id)).fetchone()
    if existing is not None:
        return store.row(existing)
    bid = store.new_id()
    conn.execute("INSERT INTO bindings(id, company, channel_kind, sender_key, customer_id, state, source_ref, "
                 "synthetic, created_by, created) VALUES (?,?,?,?,?,'active',?,?,?,?)",
                 (bid, company, channel_kind, key, customer_id, source_ref, int(synthetic), actor, time.time()))
    store.audit(conn, actor, "binding_add", bid, {"channel_kind": channel_kind, "customer_id": customer_id})
    return store.row(conn.execute("SELECT * FROM bindings WHERE id=?", (bid,)).fetchone())


def revoke(conn, binding_id: str, *, actor: str) -> dict:
    cur = store.row(conn.execute("SELECT * FROM bindings WHERE id=? OR id LIKE ?", (binding_id, f"{binding_id}%"))
                    .fetchone())
    if cur is None:
        raise BindingError("not_found", "No such binding.")
    if cur["state"] == "revoked":
        return cur
    conn.execute("UPDATE bindings SET state='revoked', revoked_by=?, revoked=?, revision=revision+1 WHERE id=?",
                 (actor, time.time(), cur["id"]))
    store.audit(conn, actor, "binding_revoke", cur["id"], {})
    return store.row(conn.execute("SELECT * FROM bindings WHERE id=?", (cur["id"],)).fetchone())


def list_bindings(conn, *, company: str | None = None, include_revoked: bool = False) -> list[dict]:
    where, args = [], []
    if company:
        where.append("company=?")
        args.append(company)
    if not include_revoked:
        where.append("state='active'")
    sql = "SELECT * FROM bindings" + (f" WHERE {' AND '.join(where)}" if where else "") + " ORDER BY created"
    return store.rows(conn.execute(sql, args))


def plan_import(conn, text: str, *, company: str, customer_lookup) -> dict:
    """Read a bindings CSV and say what would happen, changing nothing.
    `customer_lookup(customer_id)` returns the ERP customer record or None."""
    reader = csv.DictReader(io.StringIO(text))
    columns = [c.strip() for c in reader.fieldnames or []]
    if columns not in (CSV_COLUMNS, PARTY_COLUMNS):
        raise BindingError("binding_invalid", f"The CSV columns must be exactly {','.join(CSV_COLUMNS)}, or "
                           f"{','.join(PARTY_COLUMNS)}.")
    adds, conflicts, rejects, existing = [], [], [], []
    seen: dict[tuple, str] = {}
    for n, raw in enumerate(reader, start=2):
        if n - 1 > MAX_IMPORT_ROWS:
            raise BindingError("payload_too_large", f"At most {MAX_IMPORT_ROWS} rows per import.")
        r = {k.strip(): (v or "").strip() for k, v in raw.items()}
        if columns == PARTY_COLUMNS:
            if r["party_type"].casefold() != "customer":
                # The desk binds customers only. Supplier senders belong to the Order & Invoice Desk.
                rejects.append({"line": n, "reason": f"{r['party_type'] or 'This'} rows are not customers. The "
                                "Customer Desk binds customers only."})
                continue
            r["customer_id"] = r["party_id"]
        try:
            key = sender_key(r["channel_kind"], r["sender"])
        except BindingError as exc:
            rejects.append({"line": n, "reason": exc.message})
            continue
        if r["company"] != company:
            conflicts.append({"line": n, "code": "binding_conflict", "sender": key,
                              "reason": f"Row is for company {r['company']!r}, not {company!r}."})
            continue
        cust = customer_lookup(r["customer_id"])
        if cust is None:
            conflicts.append({"line": n, "code": "binding_conflict", "sender": key,
                              "reason": f"ERPNext has no customer {r['customer_id']} for this company."})
            continue
        if cust["fields"].get("disabled"):
            conflicts.append({"line": n, "code": "binding_conflict", "sender": key,
                              "reason": f"Customer {r['customer_id']} is disabled in ERPNext."})
            continue
        ident = (r["channel_kind"], key)
        if ident in seen and seen[ident] != r["customer_id"]:
            conflicts.append({"line": n, "code": "binding_conflict", "sender": key,
                              "reason": "The same sender is listed for two customers. Cases from it would need a "
                                        "person to choose every time."})
        seen[ident] = r["customer_id"]
        current = lookup(conn, company, r["channel_kind"], key)
        if any(b["customer_id"] == r["customer_id"] for b in current):
            existing.append({"line": n, "sender": key, "customer_id": r["customer_id"]})
            continue
        adds.append({"line": n, "company": company, "channel_kind": r["channel_kind"], "sender": key,
                     "customer_id": r["customer_id"], "source_ref": r["source_ref"] or None})
    return {"adds": adds, "conflicts": conflicts, "rejects": rejects, "unchanged": existing}


def export_csv(conn, company: str) -> str:
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(CSV_COLUMNS)
    for b in list_bindings(conn, company=company):
        w.writerow([b["company"], b["channel_kind"], b["sender_key"], b["customer_id"], b["source_ref"] or ""])
    return out.getvalue()
