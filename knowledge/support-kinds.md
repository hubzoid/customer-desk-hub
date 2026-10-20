---
version: 1
name: support-request-kinds
tag_prefix: desk-
kinds:
  product_guidance:
    tag: desk-product-guidance
    label: Product guidance
    guidance: Instructions for using a product or service, without a live account lookup.
    behavior: answer
    examples: ["How do I export a report?", "Where can I find the user guide?"]
  policy_question:
    tag: desk-policy-question
    label: Company policy
    guidance: A question about documented conditions or process. Never claim a particular refund or action was approved.
    behavior: answer
    examples: ["What are the return conditions?", "Which documents does your support process require?"]
  account_status:
    tag: desk-account-status
    label: Current account or transaction status
    guidance: A request for current order, invoice, payment, shipment or account facts requiring an authoritative live system.
    behavior: review
    examples: ["Has my order shipped?", "Was my refund approved?"]
  complaint:
    tag: desk-complaint
    label: Complaint or consequential remedy
    guidance: A reported service/product problem or a request to perform a refund, compensation or account action.
    behavior: review
    examples: ["The item arrived broken and I want a refund.", "Please cancel my account."]
  other:
    tag: desk-other
    label: Other support
    guidance: Another support question. Answer only from applicable approved evidence, otherwise hold for a person.
    behavior: answer
    examples: ["I have another question.", "Can you explain this service?"]
boundaries:
  - Asking about policy conditions is different from asking to perform or confirm an action.
  - Current account status requires a live authoritative source, never another customer's resolved ticket.
risk_flags:
  legal_threat: A threat involving a court, lawyer or regulator.
  safety_issue: A product may be unsafe or have injured someone.
  personal_data_request: A request to inspect, delete or change personal data.
  other_customer_data: A request for another customer's data.
---

Owner-reviewed general-support taxonomy. Categories select response behaviour, never new tools or executable business actions. Customize this file through the existing reviewed Hub-change path.
