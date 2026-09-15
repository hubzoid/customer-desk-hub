# Operator guide

DRAFT for review. For the customer care team using the desk every day.

## Who does what

| Role | Granted as | What they do |
|---|---|---|
| Desk operator | `desk_operator` | Claims cases, edits replies, saves drafts, asks to send, reruns, opens cases for calls. |
| Delivery team | `desk_delivery` | Owns late orders and delivery date changes. Verifies a change in ERPNext. |
| Complaints team | `desk_complaints` | Owns complaint tickets. Reviews escalation plans. |
| Exception decisions | `desk_exceptions` | Decides refunds and goodwill outside policy. |
| Sender bindings | `desk_bindings` | Matches unknown senders to ERP customers. |

An agent manager grants roles in Settings, Agents, Customer Desk, Access, or with `hubzoid grant EMAIL desk_operator --hub customer-desk .`. A role you do not hold does not even show up as a tool in chat.

## The queue

Ask in chat "What is waiting on the desk?", or `./desk list --tab open`. Tabs: open, mine, operators, delivery, complaints, decisions, held, bindings, all. A case shows its number, customer, channel, request kinds, state, queue and who holds it.

## A case

"Show CD-000007" gives:

- the conversation
- each request with its outcome and the policy rules used
- the facts read from ERPNext, each with its record, field and when it was read
- the proposed reply, its attachments, all ten checks, and the reviewer's verdict
- tickets, delivery proposals and exception decisions
- drafts and sends so far

Every case also has a page in the artifact viewer with the same content.

## What you can do

1. **Claim** the case, so others see you are on it.
2. **Edit** the reply if needed. Your words are kept exactly. Values you type, such as a date or an amount, are flagged on the approval as "typed by a person, not checked against ERPNext".
3. Then, depending on the channel's mode:
   - **Draft mode**: save it as a draft in the mailbox, and finish and send it there.
   - **Helpdesk**: the unsent draft is already on the ticket. Edit and send it in the helpdesk.
   - **Approve mode**: ask to send. Open the Work items page, read exactly what will be sent and to whom, and approve or deny. Only you, the person who asked, can approve. An administrator cannot approve for you.
4. **Rerun** with an instruction ("mention the bank holiday") to get a new revision. The instruction cannot change the customer, the tools or the policy.
5. **Internal cases**: for a phone call, "SYN-CUST-002 called for a copy of invoice SYN-SINV-0004". The reply is for you to deliver. It is never sent.

## States you will see

| State | Meaning |
|---|---|
| binding_required | The sender is not matched to exactly one customer. Nothing was read. A binding admin binds them. |
| needs_owner | Ready for a person, in the queue shown. |
| in_review | Someone holds it. |
| waiting_approval | A send waits for its requester on the Work items page. |
| mailbox_draft_saved, helpdesk_draft_saved | A real draft is waiting in the mailbox or helpdesk. |
| sent, open_items, resolved | The reply was accepted. Open items are tickets or proposals still open. |
| held | WhatsApp only allows a free-form reply within 24 hours of the customer's last message. |
| ambiguous | The reply may have been sent. Check first, then say done, retry or abandon on the Work items page. Never resend blindly. |
| waiting_customer | A clarifying question went out. |

A new message from the customer on an open case makes every unsent reply stale and the desk prepares a new one. A message within the reopen window reopens a resolved case.

## Owner work

- **Delivery**: change the date in ERPNext, then "verify delivery proposal 1a2b3c4d". The desk rereads the order. Only a matching date drafts a confirmation. Otherwise it says what ERPNext still shows. Declining needs a note.
- **Exceptions**: "approve exception 5e6f7a8b: long-standing customer, one-off". You confirm the exact decision on the card. The desk drafts the reply from it. Accounts make any credit note in ERPNext.
- **Escalations**: a legal threat, a safety issue, a personal data request or another customer's data opens a high severity ticket. The operator shares a plan, the complaints team reviews it, and only then can a reply be requested. Approving a plan never approves a send.
- **Bindings**: "bind CD-000021 to SYN-CUST-001". You name the customer. The desk never suggests one.
