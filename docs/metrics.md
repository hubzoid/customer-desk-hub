# Measures

DRAFT for review. `./desk metrics`, or "show the desk measures" in chat. These are counts observed in this deployment, not claims about the product.

| Measure | Definition |
|---|---|
| Requests resolved | Cases whose outcome is settled and, where a reply was due, accepted by the channel. |
| Response time | Median and 90th percentile hours from the first customer message to the first accepted reply. On the sample dataset's fixed clock it counts from when the case reached the desk, since the sample messages carry dates in the dataset's past. |
| Reopen rate | Reopened cases over resolved cases. |
| Unedited share | Sent replies identical to the first desk-written revision of the same resolution, over all sent replies. |
| Held and uncertain | WhatsApp replies held outside the window, and sends whose outcome is unknown. |
| Waiting for a binding | Cases whose sender is not matched yet. |

"Accepted" means the channel took the reply: the sample outbox in sample mode, the mail server for email, WhatsApp's API for WhatsApp. It never means the customer read it. A draft saved in a mailbox or helpdesk is not a sent reply.
