# Writing the policy

DRAFT for review.

`knowledge/desk-policy.md` has two parts. The settings at the top are enforced by code. The rules below are list items starting `[R<n>]`, cited by the stations in every case. Check it with `./desk policy validate`: every problem is listed with its file, line and key, and the last valid policy stays active until the file is fixed.

## Settings

| Key | Values | Default | What it does |
|---|---|---|---|
| `reply.default_language`, `reply.languages` | language codes | `en`, `[en]` | Replies in another language fall back to the default with a note. |
| `reply.max_chars` | 100 to 10000 | 3000 | Longest rendered reply. |
| `reply.signature` | text | empty | The closing line of every reply. |
| `reply.never_say` | phrases | none | Compared after Unicode NFKC and casefolding. |
| `reply.composition` | `fluid`, `templates` | `fluid` | `templates` uses only the approved templates in `customer-messages.md`, with no model wording. |
| `facts.id_patterns` | up to 10 patterns, RE2 compatible | none | Your document numbering, for example `SAL-ORD-[0-9]{4}-[0-9]{5}`. Used to find references and to catch typed ids. |
| `categories.order_status.max_orders` | 1 to 20 | 5 | Open orders shown when no order is named. |
| `categories.order_status.overdue_action` | `ticket`, `reply_only` | `ticket` | A late order opens a delivery ticket. |
| `categories.invoice_copy.max_age_days` | 1 to 3650 | 730 | Older invoices are not sent. |
| `categories.account_statement.max_range_days` | 1 to 3660 | 366 | Longer periods are shortened, with a note. |
| `categories.price_availability.price_source` | `customer_price_list`, `none` | `customer_price_list` | `none` never quotes a price. |
| `categories.price_availability.availability` | `{disclosure: exact | band | none, limited_below}` | exact | `band` says in stock, limited or out of stock, with limited below `limited_below` units. |
| `categories.delivery_change.min_notice_days` | 0 to 60 | 2 | Notice a date change needs. |
| `categories.complaint.default_severity` | low, normal, high, critical | normal | Lowest severity for a complaint ticket. |
| `categories.<kind>.enabled` | true, false | true | A switched off kind gets a short acknowledgement for an operator. |
| `refunds.within_days` | 0 to 3650 | 30 | Refunds inside this many days of the invoice go to accounts. Outside, the exception team decides. |
| `escalate_on` | `legal_threat`, `safety_issue`, `personal_data_request`, `other_customer_data` | all four | Flags that open a high severity ticket. |
| `escalation.plan_review` | `required`, `none` | required | An escalated case needs a reviewed plan before a send. |

A setting your file leaves out uses the default, and `./desk policy validate` names it, for example "Your files do not say how many days notice a delivery change needs."

## Rules

Write one rule per list item, in plain words, with a unique number. Keep each to one idea. The resolver cites them, the reviewer checks replies against them, and the case page shows which rules a reply used.

## Changing the policy

From chat: "Never give customers exact stock numbers. Say in stock, limited or out of stock, with limited meaning fewer than 20 units." The assistant proposes the exact edit as a hub change. An agent manager reviews the diff and applies it. A case drafted under the old policy is now stale: its checks show `freshness: fail`, and a pending send is refused. Rerun the case to get a reply under the new rule.

## Bringing your own documents

Keep your originals unchanged in `knowledge/sources/`, then write the policy from them. Do not add rules your documents do not state. `./desk policy validate` lists what your files left to defaults so you can decide each one.
