# Customer Desk

**A ready-made Hubzoid hub for your customer care team. Context to resolution: each customer request ends in an action taken or a reply ready to send.**

[![Built on Hubzoid](https://img.shields.io/badge/built%20on-Hubzoid-2f5bd3)](https://github.com/hubzoid/hubzoid)

This checkout implements the 20 October support proposal. Real provider, installed-runtime and hosting qualification is recorded separately in [the evidence log](docs/provider-qualification.md). Synthetic success is not a production-support claim.

Customer Desk prepares internal support suggestions from approved company knowledge, the current conversation and relevant resolved helpdesk answers. Connect Zoho Desk or Freshdesk without ERP. Optional read-only ERP jobs retain order, invoice, stock and policy safeguards. People review replies and send personally in their helpdesk. The desk never writes to ERPNext or sends on its own.

Start with [your own material and a saved correction](docs/setup-support.md). Claude Code, available Cowork capabilities or Codex can follow that file/CLI path. [Zoho](docs/helpdesk-zoho.md) retains native drafts. [Freshdesk](docs/helpdesk-freshdesk.md) uses an authenticated native editor app and an explicit replacement confirmation. Editor placement remains pending provider confirmation until persistence can be verified.

The optional ERP path retains these six jobs:

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
- With **Zoho**, the desk adds tags, private source evidence and an unsent draft after readback. With **Freshdesk**, tags and evidence are written server-side and the checked suggestion is available in its native app. An operator explicitly replaces editor text. Placement is not proof of a saved draft. Neither integration sends, closes or assigns a ticket.

There is no automatic sending in this release.

## Run the existing synthetic ERP sample

You need Python 3.11/3.12 and a tested Hubzoid 2.0 revision, with your selected installed runtime configured. Record the exact pin and authentication used. Promotion requires a tagged SDK release. No setup-time guarantee of elapsed time or unattended subscription use is implied.

The one prompt for Claude Code or Codex:

> Set up the Customer Desk from this folder on the synthetic distributor. Install Hubzoid, run the hub doctor, load the twenty sample customer requests, and show me what the desk proposes for each and why. Stop before anything is sent.

The same steps by hand:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-sdk.txt -r requirements.txt
export DESK_PYTHON="$PWD/.venv/bin/python"
```

Use Python 3.11 or 3.12 for `python3` and have Git installed for the immutable SDK requirement. This installs SDK commit `c4bf1dbeaf0e498c364bfa1b1b97f10c7ae3c60c`, not a moving branch. The pin is development evidence, with a tagged SDK release still required for promotion.

```bash
.venv/bin/python -m hubzoid hub doctor .
```

```bash
HUBZOID_SCHEDULES=1 .venv/bin/python -m hubzoid run . --port 8721
```

```bash
./desk sample load --wait 900
```

```bash
./desk list
```

Open the web app at http://127.0.0.1:8721 and ask: "What is waiting on the desk?" or "Show CD-000007".

What you should see, on labelled synthetic data for Synthetic Meridian Distribution:

- six order status answers: three orders on track, one late order with a delivery ticket, one order still a draft and so not confirmed, one cancelled order
- four invoice copies with the ERPNext print attached, one found from the customer's own order number
- two open-invoice statements
- three price and availability answers: a customer's contract price, an item out of stock in the main warehouse, and a disabled item the desk will not quote
- two delivery changes: one proposal for the delivery team, one explained as already delivered
- three complaints logged as tickets, one refund above the policy amount waiting for the exception team to decide

Every case shows its facts with the ERPNext record and field they came from, the policy rules it used, all ten checks and the reviewer's verdict. Nothing is sent.

`desk sample load --adversarial` loads six harder messages from the same dataset: an unknown sender, which waits for a binding before anything is read, a request for another customer's invoice, which reads as not found, two attempts to give the desk instructions, which it ignores and flags, a statement for every year since 1990, and a question resent on a new thread.

The sample data is the `distributor-v1` dataset of the Order & Invoice Desk's ERP module, which this hub carries as an exact copy of its read parts (see [ARCHITECTURE.md](ARCHITECTURE.md#erpnext)).

## Make it yours

- **Your policy**: edit `knowledge/desk-policy.md`. The settings at the top are enforced in code, the numbered rules are cited by the desk. `./desk policy validate` lists every problem with its line and the settings your file leaves to defaults. See [docs/policy-authoring.md](docs/policy-authoring.md).
- **Your reply style**: edit `knowledge/customer-messages.md`, with three to five of your best past replies and an approved template per outcome.
- **A correction**: in chat, "Never give customers exact stock numbers. Say in stock, limited or out of stock, with limited meaning fewer than 20 units." The desk proposes the policy change as a reviewed hub change. Apply it, rerun a case, and the next reply follows it, also after a restart.
- **Your ERPNext**: set `connectors/erpnext.yaml` to `backend: frappe_rest` with a read-only API key, then apply it with `./desk erp-configure`. See [docs/erp-permissions.md](docs/erp-permissions.md).
- **Your helpdesk**: [Zoho](docs/helpdesk-zoho.md) or [Freshdesk](docs/helpdesk-freshdesk.md), with the [ERP-free setup path](docs/setup-support.md).
- **Your senders**: import who speaks for which customer with `./desk bindings import --file contacts.csv --dry-run`. See [docs/bindings.md](docs/bindings.md).

## The team

Roles are granted per person in Settings, Agents, this agent, Access: desk operator, delivery team, complaints team, exception decisions and sender bindings. See [docs/operator-guide.md](docs/operator-guide.md).

## Evals

`python tests/customer_eval.py --runtime claude-local --runs 4` runs the twenty requests, the dataset's six adversarial messages, twelve multi-turn conversations and six safety cases, each in a fresh copy of the hub, and reports pass^1 to pass^4. The method follows Sierra's tau-bench: graded on the final state and the facts delivered, repeated to measure consistency. These are release gates on synthetic data, not a measure of quality on your data. See [docs/evals.md](docs/evals.md).

## More

- [ARCHITECTURE.md](ARCHITECTURE.md): how a message becomes a case, the stations, the checks, the write modes.
- [demo/PROMPT.md](demo/PROMPT.md), [demo/CALL-SCRIPT.md](demo/CALL-SCRIPT.md) and `demo/reset`: the one prompt, a ten minute call, and starting again.
- [docs/errors.md](docs/errors.md): every error code and what to do.
- [docs/metrics.md](docs/metrics.md): what the measures count.
- [.claude/skills/setup-customer-desk/SKILL.md](.claude/skills/setup-customer-desk/SKILL.md): setup steps for Claude Code and Codex. It sits outside `skills/` so the desk's own chat assistant does not load builder instructions.

Need it running for your team? Build with us: https://hubzoid.com (link to the Build with us page, to confirm before publishing).

Apache-2.0. ERPNext is a separate GPL-3.0 application. None of its code is in this hub.
