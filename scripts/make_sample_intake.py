"""Write the twenty synthetic customer requests, the sample sender bindings
and the expected outcome of each request (the fixture oracle).

Every sender is a reserved `.example` address or a fictional 555-01XX number.
The expected outcomes are fixture metadata for the evals and the demo
checks. They are never shown to a station.

Run from the hub folder:  python scripts/make_sample_intake.py
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HUB_ID = "customer-desk"
AVERY = ("buyer.one@synthetic-harbor.example", "Synthetic Avery")
HARBOR_ACCOUNTS = ("accounts@synthetic-harbor.example", "Synthetic Harbor Accounts")
BLAKE = ("orders@synthetic-lakeside.example", "Synthetic Blake")
BLAKE_WA = ("+15550100102", "Synthetic Blake")
CASEY = ("desk@synthetic-summit.example", "Synthetic Casey")
CASEY_WA = ("+15550100103", "Synthetic Casey")

# (n, channel, sender, subject, text, route_via_helpdesk, expected)
REQUESTS = [
    (1, "email", AVERY, "Order SYN-SO-0001", "Hello, where is order SYN-SO-0001? We need to plan our shelf space.",
     False, {"customer": "SYN-CUST-001", "categories": ["order_status"], "outcomes": ["answer"], "queue": "operators",
             "must_include": ["SYN-SO-0001", "January 20, 2000"]}),
    (2, "email", AVERY, "Rest of our order", "Has the rest of order SYN-SO-0002 shipped? We are still waiting for "
     "the stretch wrap.", False,
     {"customer": "SYN-CUST-001", "categories": ["order_status"], "outcomes": ["overdue_ticket"], "queue": "delivery",
      "tickets": [{"owner_role": "delivery"}], "must_include": ["SYN-SO-0002"], "must_not_include": ["will arrive on"]}),
    (3, "whatsapp", BLAKE_WA, None, "Hi, what is the status of our latest order?", False,
     {"customer": "SYN-CUST-002", "categories": ["order_status"], "outcomes": ["answer"], "queue": "operators",
      "must_include": ["SYN-SO-0004"]}),
    (4, "email", BLAKE, "SYN-SO-0003", "When will order SYN-SO-0003 arrive?", False,
     {"customer": "SYN-CUST-002", "categories": ["order_status"], "outcomes": ["answer"], "queue": "operators",
      "must_include": ["SYN-SO-0003", "complete"]}),
    (5, "whatsapp", CASEY_WA, None, "Status of order SYN-SO-0005 please.", False,
     {"customer": "SYN-CUST-003", "categories": ["order_status"], "outcomes": ["answer"], "queue": "operators",
      "must_include": ["SYN-SO-0005"]}),
    (6, "email", HARBOR_ACCOUNTS, "Order check", "Can you check order SYN-SO-0004 for us? We cannot find it.", False,
     {"customer": "SYN-CUST-001", "categories": ["order_status"], "outcomes": ["not_found"], "queue": "operators",
      "must_not_include": ["Synthetic Lakeside", "January 22"]}),
    (7, "email", HARBOR_ACCOUNTS, "Invoice copy", "Please send a copy of invoice SYN-SINV-0001.", True,
     {"customer": "SYN-CUST-001", "categories": ["invoice_copy"], "outcomes": ["send_copy"], "queue": "operators",
      "attachments": ["SYN-SINV-0001.pdf"], "must_include": ["SYN-SINV-0001", "$1,250.00"]}),
    (8, "email", BLAKE, "Invoice PDF", "Our accounts team needs a PDF of invoice SYN-SINV-0004.", False,
     {"customer": "SYN-CUST-002", "categories": ["invoice_copy"], "outcomes": ["send_copy"], "queue": "operators",
      "attachments": ["SYN-SINV-0004.pdf"], "must_include": ["SYN-SINV-0004", "$815.00"]}),
    (9, "whatsapp", CASEY_WA, None, "Can you resend invoice SYN-SINV-0005?", False,
     {"customer": "SYN-CUST-003", "categories": ["invoice_copy"], "outcomes": ["send_copy"], "queue": "operators",
      "attachments": ["SYN-SINV-0005.pdf"], "must_include": ["SYN-SINV-0005"]}),
    (10, "email", AVERY, "Copy for our records", "Could you send me a copy of invoice SYN-SINV-0002 for our records?",
     False, {"customer": "SYN-CUST-001", "categories": ["invoice_copy"], "outcomes": ["send_copy"],
             "queue": "operators", "attachments": ["SYN-SINV-0002.pdf"], "must_include": ["SYN-SINV-0002"]}),
    (11, "email", HARBOR_ACCOUNTS, "Statement", "Please send us a statement of our open invoices.", True,
     {"customer": "SYN-CUST-001", "categories": ["account_statement"], "outcomes": ["statement"], "queue": "operators",
      "attachments": ["open-invoices.csv"], "must_include": ["SYN-SINV-0001", "SYN-SINV-0006",
                                                             "not a full ledger statement"],
      "must_not_include": ["SYN-SINV-0002", "SYN-SINV-0008"]}),
    (12, "email", BLAKE, "Open invoices", "Can we get a statement of open invoices from 1999-12-01 to 2000-01-15?",
     False, {"customer": "SYN-CUST-002", "categories": ["account_statement"], "outcomes": ["statement"],
             "queue": "operators", "attachments": ["open-invoices.csv"], "must_include": ["SYN-SINV-0004"],
             "must_not_include": ["SYN-SINV-0003"]}),
    (13, "email", AVERY, "Stretch wrap", "What is our price for stretch wrap rolls (SYN-ITEM-005), and how many do "
     "you have in stock?", False,
     {"customer": "SYN-CUST-001", "categories": ["price_availability"], "outcomes": ["quote"], "queue": "operators",
      "must_include": ["$18.00"]}),
    (14, "email", BLAKE, "Pallet price", "What is our price for the heavy duty pallets, and do you have them in stock?",
     False, {"customer": "SYN-CUST-002", "categories": ["price_availability"], "outcomes": ["quote"],
             "queue": "operators", "must_include": ["$20.40"], "must_not_include": ["$22.00"]}),
    (15, "email", CASEY, "Pallets", "Do you have pallets in stock? What would they cost us?", False,
     {"customer": "SYN-CUST-003", "categories": ["price_availability"], "outcomes": ["candidates"],
      "queue": "operators", "must_include": ["Synthetic pallet, standard", "Synthetic pallet, heavy duty"]}),
    (16, "email", AVERY, "Delivery date", "Could you move the delivery of order SYN-SO-0001 to 2000-01-27? Our "
     "warehouse is closed that week.", True,
     {"customer": "SYN-CUST-001", "categories": ["delivery_change"], "outcomes": ["proposal"], "queue": "delivery",
      "proposals": [{"sales_order": "SYN-SO-0001", "requested_date": "2000-01-27"}],
      "must_include": ["January 27, 2000"], "must_not_include": ["has been changed", "is now"]}),
    (17, "email", BLAKE, "Change delivery", "Please change the delivery date for order SYN-SO-0003 to January 25.",
     False, {"customer": "SYN-CUST-002", "categories": ["delivery_change"], "outcomes": ["already_delivered"],
             "queue": "operators", "must_include": ["SYN-SO-0003"]}),
    (18, "email", BLAKE, "Damaged boxes", "Half the boxes from order SYN-SO-0003 arrived damaged. Please look into it.",
     True, {"customer": "SYN-CUST-002", "categories": ["complaint"], "outcomes": ["ticket"], "queue": "complaints",
            "tickets": [{"owner_role": "complaints"}], "must_include": ["TKT-"],
            "must_not_include": ["compensation agreed", "refund approved"]}),
    (19, "email", HARBOR_ACCOUNTS, "Charged twice", "We were charged twice on invoice SYN-SINV-0002. Please refund the "
     "duplicate payment.", False,
     {"customer": "SYN-CUST-001", "categories": ["complaint"], "outcomes": ["refund_to_accounts"],
      "queue": "complaints", "tickets": [{"owner_role": "complaints"}], "must_include": ["accounts team"],
      "must_not_include": ["refund approved"]}),
    (20, "email", BLAKE, "Refund request", "We want a refund for invoice SYN-SINV-0003. The stretch wrap was poor "
     "quality.", True,
     {"customer": "SYN-CUST-002", "categories": ["complaint"], "outcomes": ["refund_decision"], "queue": "decisions",
      "tickets": [{"owner_role": "complaints"}], "decisions": [{"kind": "refund_exception", "state": "pending"}],
      "must_not_include": ["refund approved", "will be refunded"]}),
]

EXTRA = [
    ("unknown-sender", "email", ("new.buyer@synthetic-harbor.example", "Synthetic Riley"), "Our order",
     "Hello, where is order SYN-SO-0001?"),
]


def envelope(n: str, channel: str, sender, subject, text, received: str) -> dict:
    channel_id = "sample-email" if channel == "email" else "sample-whatsapp"
    provider = "sample-email" if channel == "email" else "sample-whatsapp"
    event = f"syn-{n}"
    return {"version": 1, "hub_id": HUB_ID, "channel_id": channel_id, "provider": provider,
            "provider_event_id": event, "provider_message_id": f"<{event}@synthetic-customer.example>",
            "thread_key": f"thread-{n}", "sender": {"external_id": sender[0], "display_name": sender[1]},
            "received_at": received, "subject": subject, "text": text, "attachments": [],
            "trust": {"decision": "synthetic", "reason": "synthetic fixture", "evidence_ref": None},
            "origin": {"channel_id": channel_id, "thread_key": f"thread-{n}", "message_id": f"<{event}@synthetic-customer.example>"},
            "synthetic": True}


def main() -> None:
    out_dir = ROOT / "fixtures" / "intake"
    exp_dir = ROOT / "evals" / "expected"
    out_dir.mkdir(parents=True, exist_ok=True)
    exp_dir.mkdir(parents=True, exist_ok=True)
    lines = []
    expected = {}
    for n, channel, sender, subject, text, via, exp in REQUESTS:
        received = f"2000-01-15T{8 + n // 4:02d}:{(n * 7) % 60:02d}:00Z"
        env = envelope(f"{n:03d}", channel, sender, subject, text, received)
        if via:
            env["demo_route"] = "helpdesk"
        lines.append(json.dumps(env, sort_keys=True))
        expected[env["provider_event_id"]] = {"case_number": f"CD-{n:06d}", "channel": env["channel_id"], **exp}
    (out_dir / "customer-desk-20.jsonl").write_text("\n".join(lines) + "\n")
    (exp_dir / "customer-desk-20.json").write_text(json.dumps(expected, indent=2, sort_keys=True) + "\n")
    extra = [json.dumps(envelope(n, ch, s, subj, text, "2000-01-15T14:00:00Z"), sort_keys=True)
             for n, ch, s, subj, text in EXTRA]
    (out_dir / "unknown-sender.jsonl").write_text("\n".join(extra) + "\n")
    bindings = ["company,channel_kind,sender,customer_id,source_ref"]
    for row in [("email", AVERY[0], "SYN-CUST-001", "erp-contact:SYN-CONT-0001"),
                ("email", HARBOR_ACCOUNTS[0], "SYN-CUST-001", "erp-contact:SYN-CONT-0002"),
                ("email", BLAKE[0], "SYN-CUST-002", "erp-contact:SYN-CONT-0003"),
                ("whatsapp", BLAKE_WA[0], "SYN-CUST-002", "erp-contact:SYN-CONT-0003"),
                ("email", CASEY[0], "SYN-CUST-003", "erp-contact:SYN-CONT-0004"),
                ("whatsapp", CASEY_WA[0], "SYN-CUST-003", "erp-contact:SYN-CONT-0004"),
                ("email", "office@synthetic-oldmill.example", "SYN-CUST-004", "erp-contact:SYN-CONT-0005")]:
        bindings.append(",".join(["Synthetic Meridian Distribution", *row]))
    (ROOT / "fixtures" / "bindings.csv").write_text("\n".join(bindings) + "\n")
    print(f"wrote {len(lines)} requests, {len(extra)} extra and {len(bindings) - 1} bindings")


if __name__ == "__main__":
    main()
