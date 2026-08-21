"""Write the synthetic ERP fixtures the Customer Desk uses until the canonical
`distributor-v1` dataset from the Order & Invoice Desk is vendored.

Everything here is invented. Every display label starts with "Synthetic",
contacts use reserved `.example` domains, and phone numbers sit in the
fictional 555-01XX range. The fixed clock is 2000-01-15T10:00:00Z, the same
as HUB-108's dataset, so relative dates in the sample messages resolve the
same way on every run.

Run from the hub folder:  python scripts/make_sample_erp.py
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "fixtures" / "erp" / "distributor-v1"
COMPANY = "Synthetic Meridian Distribution"
CLOCK = "2000-01-15T10:00:00Z"
MODIFIED = "2000-01-14T18:00:00Z"


def customers():
    return [
        {"name": "SYN-CUST-001", "customer_name": "Synthetic Harbor Retail", "disabled": 0,
         "default_currency": "USD", "default_price_list": "SYN-RETAIL"},
        {"name": "SYN-CUST-002", "customer_name": "Synthetic Lakeside Foods", "disabled": 0,
         "default_currency": "USD", "default_price_list": "SYN-RETAIL"},
        {"name": "SYN-CUST-003", "customer_name": "Synthetic Summit Hardware", "disabled": 0,
         "default_currency": "USD", "default_price_list": "SYN-WHOLESALE"},
        {"name": "SYN-CUST-004", "customer_name": "Synthetic Old Mill Traders", "disabled": 1,
         "default_currency": "USD", "default_price_list": "SYN-RETAIL"},
    ]


ITEMS = [
    ("SYN-ITEM-001", "Synthetic corrugated box, small", 0),
    ("SYN-ITEM-002", "Synthetic corrugated box, medium", 0),
    ("SYN-ITEM-003", "Synthetic corrugated box, large", 0),
    ("SYN-ITEM-004", "Synthetic packing tape, 48 mm", 0),
    ("SYN-ITEM-005", "Synthetic stretch wrap roll", 0),
    ("SYN-ITEM-006", "Synthetic pallet, standard", 0),
    ("SYN-ITEM-007", "Synthetic pallet, heavy duty", 0),
    ("SYN-ITEM-008", "Synthetic bubble wrap roll", 0),
    ("SYN-ITEM-009", "Synthetic shipping label pack", 0),
    ("SYN-ITEM-010", "Synthetic void fill paper", 0),
    ("SYN-ITEM-011", "Synthetic storage crate, large", 0),
    ("SYN-ITEM-012", "Synthetic tote, discontinued", 1),
]


def items():
    return [{"name": code, "item_code": code, "item_name": label, "stock_uom": "Nos", "disabled": disabled,
             "is_stock_item": 1, "uoms": [{"uom": "Nos", "conversion_factor": "1"},
                                           {"uom": "Box", "conversion_factor": "20"}]}
            for code, label, disabled in ITEMS]


def bins():
    projected = {"SYN-ITEM-001": "640", "SYN-ITEM-002": "310", "SYN-ITEM-003": "45", "SYN-ITEM-004": "1200",
                 "SYN-ITEM-005": "12", "SYN-ITEM-006": "85", "SYN-ITEM-007": "14", "SYN-ITEM-008": "0",
                 "SYN-ITEM-009": "400", "SYN-ITEM-010": "220", "SYN-ITEM-011": "0", "SYN-ITEM-012": "30"}
    out = []
    for code, qty in projected.items():
        out.append({"name": f"BIN-{code}-MAIN", "item_code": code, "warehouse": "SYN-MAIN",
                    "actual_qty": qty, "reserved_qty": "0", "projected_qty": qty})
        out.append({"name": f"BIN-{code}-EAST", "item_code": code, "warehouse": "SYN-EAST",
                    "actual_qty": "500", "reserved_qty": "0", "projected_qty": "500"})
    return out


def prices():
    retail = {"SYN-ITEM-001": "1.20", "SYN-ITEM-002": "1.85", "SYN-ITEM-003": "2.60", "SYN-ITEM-004": "3.40",
              "SYN-ITEM-005": "18.00", "SYN-ITEM-006": "14.50", "SYN-ITEM-007": "22.00", "SYN-ITEM-008": "26.00",
              "SYN-ITEM-009": "9.75", "SYN-ITEM-010": "11.00", "SYN-ITEM-011": "34.00", "SYN-ITEM-012": "6.00"}
    wholesale = {"SYN-ITEM-001": "1.05", "SYN-ITEM-002": "1.60", "SYN-ITEM-003": "2.25", "SYN-ITEM-004": "2.95",
                 "SYN-ITEM-005": "15.50", "SYN-ITEM-006": "12.75", "SYN-ITEM-007": "19.50", "SYN-ITEM-011": "29.00"}
    out = []
    n = 1
    for code, rate in retail.items():
        out.append({"name": f"SYN-PRICE-{n:04d}", "item_code": code, "price_list": "SYN-RETAIL", "currency": "USD",
                    "price_list_rate": rate, "uom": "Nos", "customer": None, "supplier": None,
                    "valid_from": "1999-01-01", "valid_upto": None})
        n += 1
    for code, rate in wholesale.items():
        out.append({"name": f"SYN-PRICE-{n:04d}", "item_code": code, "price_list": "SYN-WHOLESALE",
                    "currency": "USD", "price_list_rate": rate, "uom": "Nos", "customer": None, "supplier": None,
                    "valid_from": "1999-01-01", "valid_upto": None})
        n += 1
    # Customer specific rows for SYN-CUST-002, one of them expired.
    out.append({"name": f"SYN-PRICE-{n:04d}", "item_code": "SYN-ITEM-007", "price_list": "SYN-RETAIL",
                "currency": "USD", "price_list_rate": "20.40", "uom": "Nos", "customer": "SYN-CUST-002",
                "supplier": None, "valid_from": "1999-06-01", "valid_upto": None})
    n += 1
    out.append({"name": f"SYN-PRICE-{n:04d}", "item_code": "SYN-ITEM-005", "price_list": "SYN-RETAIL",
                "currency": "USD", "price_list_rate": "16.00", "uom": "Nos", "customer": "SYN-CUST-002",
                "supplier": None, "valid_from": "1999-01-01", "valid_upto": "1999-12-31"})
    n += 1
    # A selling price for a supplier-only row, which the desk must never quote.
    out.append({"name": f"SYN-PRICE-{n:04d}", "item_code": "SYN-ITEM-001", "price_list": "SYN-BUYING",
                "currency": "USD", "price_list_rate": "0.70", "uom": "Nos", "customer": None,
                "supplier": "SYN-SUPP-001", "valid_from": "1999-01-01", "valid_upto": None})
    return out


def _line(row_id, code, qty, delivered, rate, delivery_date):
    label = next(label for c, label, _ in ITEMS if c == code)
    return {"name": row_id, "item_code": code, "item_name": label, "qty": qty, "delivered_qty": delivered,
            "uom": "Nos", "rate": rate, "amount": f"{float(qty) * float(rate):.2f}", "delivery_date": delivery_date}


def sales_orders():
    rows = [
        ("SYN-SO-0001", "SYN-CUST-001", "2000-01-05", "2000-01-20", "SYN-PO-H-1001", 1, "To Deliver and Bill",
         [("SO1-1", "SYN-ITEM-001", "400", "0", "1.20"), ("SO1-2", "SYN-ITEM-004", "60", "0", "3.40")]),
        ("SYN-SO-0002", "SYN-CUST-001", "1999-12-28", "2000-01-10", "SYN-PO-H-0998", 1, "To Deliver and Bill",
         [("SO2-1", "SYN-ITEM-006", "40", "40", "14.50"), ("SO2-2", "SYN-ITEM-005", "20", "0", "18.00")]),
        ("SYN-SO-0003", "SYN-CUST-002", "1999-12-20", "2000-01-05", "SYN-PO-L-501", 1, "Completed",
         [("SO3-1", "SYN-ITEM-002", "300", "300", "1.85"), ("SO3-2", "SYN-ITEM-008", "10", "10", "26.00")]),
        ("SYN-SO-0004", "SYN-CUST-002", "2000-01-10", "2000-01-22", "SYN-PO-L-517", 1, "To Deliver and Bill",
         [("SO4-1", "SYN-ITEM-007", "50", "0", "20.40")]),
        ("SYN-SO-0005", "SYN-CUST-003", "2000-01-11", "2000-01-25", "SYN-PO-S-77", 1, "To Deliver and Bill",
         [("SO5-1", "SYN-ITEM-003", "200", "0", "2.25"), ("SO5-2", "SYN-ITEM-011", "8", "0", "29.00")]),
        ("SYN-SO-0006", "SYN-CUST-003", "2000-01-14", "2000-01-31", "SYN-PO-S-80", 0, "Draft",
         [("SO6-1", "SYN-ITEM-001", "100", "0", "1.05")]),
    ]
    out = []
    for name, cust, tdate, ddate, po, docstatus, status, lines in rows:
        items_ = [_line(r, c, q, d, rate, ddate) for r, c, q, d, rate in lines]
        qty = sum(float(i["qty"]) for i in items_)
        delivered = sum(float(i["delivered_qty"]) for i in items_)
        per_delivered = f"{(delivered / qty * 100) if qty else 0:.1f}"
        total = sum(float(i["amount"]) for i in items_)
        delivery_status = ("Fully Delivered" if delivered >= qty else
                           "Partly Delivered" if delivered else "Not Delivered")
        out.append({"name": name, "customer": cust, "company": COMPANY, "transaction_date": tdate,
                    "delivery_date": ddate, "po_no": po, "docstatus": docstatus, "status": status,
                    "currency": "USD", "total": f"{total:.2f}", "grand_total": f"{total:.2f}",
                    "per_delivered": per_delivered, "per_billed": "100.0" if name == "SYN-SO-0003" else "0.0",
                    "delivery_status": delivery_status,
                    "billing_status": "Fully Billed" if name == "SYN-SO-0003" else "Not Billed",
                    "modified": MODIFIED, "items": items_})
    return out


def sales_invoices():
    rows = [
        ("SYN-SINV-0001", "SYN-CUST-001", "1999-12-20", "2000-01-19", "SYN-PO-H-0990", 0, 1, "Unpaid",
         "1250.00", "1250.00", [("SI1-1", "SYN-ITEM-002", "500", "2.50")]),
        ("SYN-SINV-0002", "SYN-CUST-001", "2000-01-08", "2000-02-07", "SYN-PO-H-0998", 0, 1, "Paid",
         "580.00", "0.00", [("SI2-1", "SYN-ITEM-006", "40", "14.50")]),
        ("SYN-SINV-0003", "SYN-CUST-002", "1999-11-20", "1999-12-20", "SYN-PO-L-480", 0, 1, "Paid",
         "960.00", "0.00", [("SI3-1", "SYN-ITEM-005", "60", "16.00")]),
        ("SYN-SINV-0004", "SYN-CUST-002", "2000-01-05", "2000-02-04", "SYN-PO-L-501", 0, 1, "Unpaid",
         "815.00", "815.00", [("SI4-1", "SYN-ITEM-002", "300", "1.85"), ("SI4-2", "SYN-ITEM-008", "10", "26.00")]),
        ("SYN-SINV-0005", "SYN-CUST-003", "2000-01-12", "2000-02-11", "SYN-PO-S-70", 0, 1, "Unpaid",
         "300.00", "300.00", [("SI5-1", "SYN-ITEM-004", "100", "3.00")]),
        ("SYN-SINV-0006", "SYN-CUST-001", "2000-01-02", "2000-01-02", "SYN-PO-H-0990", 1, 1, "Return",
         "-100.00", "-100.00", [("SI6-1", "SYN-ITEM-002", "-40", "2.50")]),
        ("SYN-SINV-0007", "SYN-CUST-003", "2000-01-03", "2000-02-02", "SYN-PO-S-66", 0, 2, "Cancelled",
         "75.00", "0.00", [("SI7-1", "SYN-ITEM-009", "8", "9.375")]),
        ("SYN-SINV-0008", "SYN-CUST-001", "2000-01-14", "2000-02-13", "SYN-PO-H-1001", 0, 0, "Draft",
         "480.00", "480.00", [("SI8-1", "SYN-ITEM-001", "400", "1.20")]),
    ]
    out = []
    for name, cust, posting, due, po, is_return, docstatus, status, total, outstanding, lines in rows:
        items_ = [{"name": r, "item_code": c, "item_name": next(label for cc, label, _ in ITEMS if cc == c),
                   "qty": q, "rate": rate, "amount": f"{float(q) * float(rate):.2f}", "uom": "Nos"}
                  for r, c, q, rate in lines]
        out.append({"name": name, "customer": cust, "company": COMPANY, "posting_date": posting, "due_date": due,
                    "po_no": po, "is_return": is_return, "docstatus": docstatus, "status": status,
                    "currency": "USD", "total": total, "grand_total": total, "outstanding_amount": outstanding,
                    "modified": MODIFIED, "items": items_})
    return out


def contacts():
    """Customer contacts, used only to build the sample sender bindings."""
    return [
        {"name": "SYN-CONT-0001", "customer": "SYN-CUST-001", "email": "buyer.one@synthetic-harbor.example",
         "phone": None, "display_name": "Synthetic Avery"},
        {"name": "SYN-CONT-0002", "customer": "SYN-CUST-001", "email": "accounts@synthetic-harbor.example",
         "phone": None, "display_name": "Synthetic Harbor Accounts"},
        {"name": "SYN-CONT-0003", "customer": "SYN-CUST-002", "email": "orders@synthetic-lakeside.example",
         "phone": "+15550100102", "display_name": "Synthetic Blake"},
        {"name": "SYN-CONT-0004", "customer": "SYN-CUST-003", "email": "desk@synthetic-summit.example",
         "phone": "+15550100103", "display_name": "Synthetic Casey"},
        {"name": "SYN-CONT-0005", "customer": "SYN-CUST-004", "email": "office@synthetic-oldmill.example",
         "phone": None, "display_name": "Synthetic Drew"},
    ]


FILES = {
    "customers.json": customers,
    "items.json": items,
    "availability.json": bins,
    "prices.json": prices,
    "sales_orders.json": sales_orders,
    "sales_invoices.json": sales_invoices,
    "contacts.json": contacts,
}


def main() -> None:
    ROOT.mkdir(parents=True, exist_ok=True)
    digests = {}
    for name, fn in FILES.items():
        data = json.dumps(fn(), indent=2, sort_keys=True) + "\n"
        (ROOT / name).write_text(data)
        digests[name] = "sha256:" + hashlib.sha256(data.encode()).hexdigest()
    manifest = {"version": 1, "dataset": "distributor-v1", "variant": "customer-desk-interim",
                "synthetic": True, "seed": 108, "clock": CLOCK, "company": COMPANY, "currency": "USD",
                "warehouses": ["SYN-MAIN"], "selling_price_lists": ["SYN-RETAIL", "SYN-WHOLESALE"],
                "note": ("Interim Customer Desk fixtures built to the HUB-108 contract. They are replaced by the "
                         "vendored canonical distributor-v1 dataset from the Order & Invoice Desk when it lands."),
                "files": digests}
    (ROOT / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    print(f"wrote {len(FILES)} files to {ROOT}")


if __name__ == "__main__":
    main()
