---
version: 1
name: request-kinds
description: The closed set of request kinds the desk recognises, the helpdesk tag for each, what each allows, and the rules for telling them apart.
tag_prefix: "desk-"
kinds:
  order_status:
    tag: desk-order-status
    label: Where is my order
    guidance: The customer asks about the status, progress, shipping or delivery date of an order they placed.
    outcomes: [answer, overdue_ticket, clarify]
    examples:
      - "Can you tell me where our order is and when it will arrive?"
      - "Has the rest of our last order shipped yet?"
  invoice_copy:
    tag: desk-invoice-copy
    label: Invoice copy
    guidance: The customer wants a copy or the PDF of one specific invoice.
    outcomes: [send_copy, not_found, too_old, clarify]
    examples:
      - "Please resend the invoice for our last delivery."
      - "Our accounts team needs a PDF of an invoice."
  account_statement:
    tag: desk-statement
    label: Account statement
    guidance: The customer wants a list of their open or unpaid invoices, or a statement for a period.
    outcomes: [statement, clarify]
    examples:
      - "Can you send us everything we still owe?"
      - "Please send a statement of open invoices for this quarter."
  price_availability:
    tag: desk-price-stock
    label: Price and availability
    guidance: The customer asks what an item costs them or whether it is in stock.
    outcomes: [quote, candidates, not_quotable, clarify]
    examples:
      - "What is our price for the blue widgets and do you have them?"
      - "Is the large crate in stock?"
  delivery_change:
    tag: desk-delivery-change
    label: Delivery date change
    guidance: The customer asks to move the delivery date of an existing order earlier or later.
    outcomes: [proposal, rule_refusal, already_delivered, clarify]
    examples:
      - "Could you deliver our order a week later?"
      - "We need the order brought forward to Monday."
  complaint:
    tag: desk-complaint
    label: Complaint
    guidance: The customer reports a problem with goods, service, billing or delivery, or asks for a refund or compensation.
    outcomes: [ticket, refund_to_accounts, refund_decision]
    examples:
      - "Half the boxes arrived damaged."
      - "We were charged twice and want our money back."
  other:
    tag: desk-other
    label: Other
    guidance: Anything that is none of the above, including greetings, thanks and requests the desk does not handle.
    outcomes: [acknowledge]
    examples:
      - "Thanks for your help last week."
boundaries:
  - "A refund or compensation request is always a complaint, even when it mentions an invoice."
  - "A request for a copy of one invoice is invoice_copy. A request for all open invoices is account_statement."
  - "Asking when an order arrives is order_status. Asking to move that date is delivery_change."
  - "Asking for a price or stock for items not yet ordered is price_availability, even if an order is mentioned."
  - "When one message asks for several things, return one request per thing, in the order asked."
risk_flags:
  legal_threat: "The sender threatens legal action, a lawyer, a court or a regulator."
  safety_issue: "A product may have hurt someone or may be unsafe."
  personal_data_request: "The sender asks for, or asks to delete or correct, personal data."
  other_customer_data: "The sender asks about documents, orders, prices or contacts that belong to a different customer."
---

# Request kinds

This file is the only source of request kinds and helpdesk tags. The classifier chooses from this list and nothing else. To add a kind, add it here with its tag, guidance, outcomes and two paraphrased examples, then add the matching rules to `desk-policy.md`.

The risk flags only ever add. A flag raised by either the classifier or the second opinion is kept.
