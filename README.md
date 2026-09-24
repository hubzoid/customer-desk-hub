# Customer Desk

**A ready-made Hubzoid hub for your customer care team. Context to resolution: each customer request ends in an action taken or a reply ready to send.**

[![Built on Hubzoid](https://img.shields.io/badge/built%20on-Hubzoid-2f5bd3)](https://github.com/hubzoid/hubzoid)

DRAFT. This README is a draft for review. Nothing here is published.

Customer Desk reads each customer email, WhatsApp message, helpdesk ticket, call note or meeting transcript, works out what the customer asked, reads the answer from your ERPNext, and prepares a reply your team can trust. A person approves every reply. The desk never writes to ERPNext and never sends anything on its own.

It handles six kinds of request:

| Request | What the desk does |
|---|---|
| Where is my order | Reads the order: status, delivery date, what is delivered. A late order opens a ticket for the delivery team. |
| Invoice copy | Attaches the official ERPNext print of the customer's own submitted invoice. |
| Account statement | Lists the customer's open invoices and credit notes, with a CSV. |
| Price and availability | Quotes the customer's own price list, and stock as your policy allows: exact, in bands, or not at all. |
| Delivery date change | Checks the notice period and proposes the change to the delivery team. It confirms only after ERPNext shows the new date. |
| Complaint or refund | Opens a ticket. A refund outside your policy waits for a named person to decide. |

## How replies leave

- The desk **never writes to ERPNext**. Its connection is read only, and `hubzoid hub doctor` fails if writes are switched on.
- Replies are **off until you connect a channel**.
- **Email replies are saved as drafts by default**, in your mailbox or helpdesk, for a person to finish and send there.
- **WhatsApp has no drafts**, so WhatsApp replies stay off until you turn on approved sending.
- **Approved sending** (`approve` mode, off by default): Hubzoid sends only after the person who asked approves the exact reply, recipients and attachments on the Work items page. Just before sending it rereads every ERPNext fact the reply uses. If anything changed, it refuses and drafts a new revision.
- With a **helpdesk** (Zoho Desk first), the desk adds tags, a private note with the ERP facts and their sources, and the reply as an unsent draft. It never sends, closes or assigns a ticket.

There is no automatic sending in this release.

## Try it in ten minutes (sample data)

You need Python 3.11 or 3.12, Hubzoid 2.0 (until it is released, install it from the Hubzoid repository's main branch), and Claude Code or Codex signed in on this machine. No API key.

The one prompt for Claude Code or Codex:

> Set up the Customer Desk from this folder on the synthetic distributor. Install Hubzoid, run the hub doctor, load the twenty sample customer requests, and show me what the desk proposes for each and why. Stop before anything is sent.

The same steps by hand:

```bash
python -m venv .venv && .venv/bin/pip install "hubzoid @ git+https://github.com/hubzoid/hubzoid@main" babel
```

```bash
.venv/bin/hubzoid hub doctor .
```

```bash
echo "HUBZOID_SCHEDULES=1" >> .env && .venv/bin/hubzoid run . --port 8721
```

```bash
.venv/bin/python desk sample load --wait 900
```

```bash
.venv/bin/python desk list
```

Open the web app at http://127.0.0.1:8721 and ask: "What is waiting on the desk?" or "Show CD-000007".

What you should see, on labelled synthetic data for Synthetic Meridian Distribution:

- six order status answers, one of them a late order with a delivery ticket, one an order that belongs to another customer answered as not found
- four invoice copies with the ERPNext print attached
- two open-invoice statements
- three price and availability answers, one asking which of two similar items the customer means
- two delivery changes: one proposal for the delivery team, one explained as already delivered
- three complaints logged as tickets, one waiting for the exception team to decide a refund outside policy

Every case shows its facts with the ERPNext record and field they came from, the policy rules it used, all ten checks and the reviewer's verdict. Nothing is sent.

## Make it yours

- **Your policy**: edit `knowledge/desk-policy.md`. The settings at the top are enforced in code, the numbered rules are cited by the desk. `./desk policy validate` lists every problem with its line and the settings your file leaves to defaults. See [docs/policy-authoring.md](docs/policy-authoring.md).
- **Your reply style**: edit `knowledge/customer-messages.md`, with three to five of your best past replies and an approved template per outcome.
- **A correction**: in chat, "Never give customers exact stock numbers. Say in stock, limited or out of stock, with limited meaning fewer than 20 units." The desk proposes the policy change as a reviewed hub change. Apply it, rerun a case, and the next reply follows it, also after a restart.
- **Your ERPNext**: set `connectors/erpnext.yaml` to `backend: frappe_rest` with a read-only API key. See [docs/erp-permissions.md](docs/erp-permissions.md).
- **Your helpdesk**: [docs/helpdesk-zoho.md](docs/helpdesk-zoho.md).
- **Your senders**: import who speaks for which customer with `./desk bindings import --file contacts.csv --dry-run`. See [docs/bindings.md](docs/bindings.md).

## The team

Roles are granted per person in Settings, Agents, this agent, Access: desk operator, delivery team, complaints team, exception decisions and sender bindings. See [docs/operator-guide.md](docs/operator-guide.md).

## Evals

`python tests/customer_eval.py --runtime claude-local --runs 4` runs twenty requests, twelve multi-turn conversations and six safety cases, each in a fresh copy of the hub, and reports pass^1 to pass^4. The method follows Sierra's tau-bench: graded on the final state and the facts delivered, repeated to measure consistency. These are release gates on synthetic data, not a measure of quality on your data. See [docs/evals.md](docs/evals.md).

## More

- [ARCHITECTURE.md](ARCHITECTURE.md): how a message becomes a case, the stations, the checks, the write modes.
- [demo/PROMPT.md](demo/PROMPT.md), [demo/CALL-SCRIPT.md](demo/CALL-SCRIPT.md) and `demo/reset`: the one prompt, a ten minute call, and starting again.
- [docs/errors.md](docs/errors.md): every error code and what to do.
- [docs/metrics.md](docs/metrics.md): what the measures count.
- [.claude/skills/setup-customer-desk/SKILL.md](.claude/skills/setup-customer-desk/SKILL.md): setup steps for Claude Code and Codex. It sits outside `skills/` so the desk's own chat assistant does not load builder instructions.

Need it running for your team? Build with us: https://hubzoid.com (link to the Build with us page, to confirm before publishing).

Apache-2.0. ERPNext is a separate GPL-3.0 application. None of its code is in this hub.
