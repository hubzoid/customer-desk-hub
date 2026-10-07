---
version: 1
name: customer-messages
description: How replies to customers read, with approved reply templates per outcome. Placeholders in double square brackets are filled by the desk from ERPNext facts.
greeting: "Hello [[sender_name]],"
closing: "Kind regards,"
templates:
  order_status.answer: |
    Thank you for checking in. Order [[order_ref]] is [[order_status]]. ERPNext shows a delivery date of [[delivery_date]] and [[per_delivered]] of the order delivered.
  order_status.overdue_ticket: |
    Order [[order_ref]] was due on [[delivery_date]] and some lines have not been delivered yet. I have asked our delivery team to look into it, and they will update you directly.
  order_status.not_confirmed: |
    Thank you for checking in. Order [[reference]] is with our team and is not confirmed yet. We will confirm the delivery date with you shortly.
  order_status.cancelled: |
    Order [[reference]] was cancelled in our system. A member of our team will contact you about it.
  invoice_copy.send_copy: |
    Please find attached a copy of invoice [[invoice]], dated [[posting_date]], for [[grand_total]]. The outstanding amount is [[outstanding]].
  invoice_copy.not_found: |
    We could not find that invoice under your account. Could you check the invoice number and send it again?
  account_statement.statement: |
    Here are the open invoices on your account. A CSV copy is attached.
  delivery_change.proposal: |
    Thank you. I have passed your request to move order [[order_ref]] to [[requested_date]] to our delivery team. I will confirm once the new date shows in our system.
  delivery_change.confirmed: |
    Order [[order_ref]] is now scheduled for delivery on [[delivery_date]], as you asked.
  delivery_change.declined: |
    I am sorry, we cannot move order [[order_ref]] to [[requested_date]]. Our delivery team will contact you about the options.
  delivery_change.already_delivered: |
    Order [[order_ref]] has already been delivered in full, so its delivery date can no longer be changed.
  complaint.ticket: |
    I am sorry to hear about this. I have logged it as [[ticket]], and our complaints team will follow up with you.
  complaint.refund_to_accounts: |
    I have logged your request as [[ticket]] and passed it to our accounts team, who will confirm the next steps with you.
  complaint.refund_decision: |
    I have logged your request as [[ticket]]. It needs a decision from our team, and we will come back to you once it is made.
  complaint.exception_approved: |
    Thank you for your patience. Our team has approved an exception for invoice [[invoice]]. Our accounts team will issue the credit note and confirm it to you.
  complaint.exception_declined: |
    Thank you for your patience. Our team has reviewed your request about invoice [[invoice]] and cannot make an exception to our refund policy in this case. Your request stays logged as [[ticket]].
  other.acknowledge: |
    Thank you for your message. A member of our team will reply shortly.
---

# Reply style

SYNTHETIC SAMPLE STYLE for Synthetic Meridian Distribution. Replace it with your own style and three to five of your best past replies.

- Write short, warm, plain replies. One idea per sentence. No jargon.
- Start with the greeting above and end with the closing and the policy's signature.
- Answer every request in the order the customer asked. Use a short paragraph for each.
- Never type a number, date, amount, quantity or document number. Use the placeholder for the fact instead, for example `[[F3]]`. The desk fills it from ERPNext.
- Never promise a date, a refund, compensation or an outcome the facts do not show.
- When something is missing, ask one clear question.
- The templates above are approved wording for each outcome. Use them as the model for tone. With `reply.composition: templates` in the policy, use them word for word.
