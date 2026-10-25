<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="https://raw.githubusercontent.com/hubzoid/hubzoid/72ac7bf1610c8a335b9b3ac3b536de8fdb6770f1/assets/mark-dark.svg">
    <img alt="Hubzoid" src="https://raw.githubusercontent.com/hubzoid/hubzoid/72ac7bf1610c8a335b9b3ac3b536de8fdb6770f1/assets/mark-light.svg" width="200">
  </picture>
</p>

<h1 align="center">Customer Desk</h1>
<h3 align="center">Customer replies, drafted from your knowledge and systems.</h3>
<p align="center">Every fact sourced. A person approves every reply.</p>
<p align="center">
  <a href="https://youtu.be/uJ6QdNVSFHM">Watch the video</a> ·
  <a href="#quick-start">Quick start</a> ·
  <a href="docs/setup-support.md">Setup guide</a> ·
  <a href="ARCHITECTURE.md">Architecture</a> ·
  <a href="https://github.com/hubzoid/hubzoid">Hubzoid</a>
</p>
<p align="center">
  <a href="https://github.com/hubzoid/hubzoid"><img src="https://img.shields.io/badge/Built%20on-Hubzoid-B5471F" alt="Built on Hubzoid"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/License-Apache%202.0-0B0B0C" alt="Apache License 2.0"></a>
  <a href="https://github.com/hubzoid/hubzoid/discussions"><img src="https://img.shields.io/badge/Community-Discussions-0B0B0C?logo=github" alt="GitHub Discussions"></a>
</p>

**The Customer Desk is a ready-to-use Hubzoid hub for your customer care team.** It reads each customer request in your helpdesk, finds the answer in your approved company knowledge, the ticket's conversation and relevant resolved answers, and prepares a reply your team reviews and sends. Connect Zoho Desk or Freshdesk. Add a read-only ERPNext connection to answer order, invoice, statement, price and delivery questions from your own records.

<p align="center">
  <a href="https://youtu.be/uJ6QdNVSFHM"><img alt="Watch: customer replies, drafted from your systems" src="https://img.youtube.com/vi/uJ6QdNVSFHM/maxresdefault.jpg" width="640"></a>
</p>

## How it works

| A customer asks | The desk does |
|---|---|
| A question your knowledge answers | Prepares the reply from your approved support articles, citing each source. |
| Where is my order | Reads the order from ERPNext: status, delivery date, what is delivered. A late order opens a ticket for the delivery team. |
| An invoice copy | Attaches the official ERPNext print of the customer's own submitted invoice. |
| An account statement | Lists the customer's open invoices and credit notes, with a CSV. |
| A price or availability | Quotes the customer's own price list, and stock as your policy allows: exact, in bands, or not at all. |
| A delivery date change | Checks the notice period and proposes the change to the delivery team. It confirms only after ERPNext shows the new date. |
| A complaint or refund | Opens a ticket. A refund outside your policy waits for a named person to decide. |

Behind each reply: intake checks the sender belongs to exactly one customer, a **classifier** sorts the request, code gathers that customer's own records as facts with their sources, a **resolver** words the reply, **ten checks** and an independent **reviewer** test every claim, and a person decides. Every case shows its facts with the record and field they came from, the policy rules it used, its checks and the reviewer's verdict.

Every case is a work item. A restart resumes it from its last saved step, and nothing finished runs again. [Architecture](ARCHITECTURE.md)

## Quick start

You need Python 3.11 or 3.12, Git, and Claude Code or Codex signed in on this machine. No API key. The quick start uses the labelled sample, so you need no helpdesk and no ERP.

Paste this into Claude Code or Codex from the cloned folder:

```text
Follow skills/setup-customer-desk/SKILL.md to set up the Customer Desk from this
folder on the synthetic distributor. Install Hubzoid, run the hub doctor, load
the twenty sample customer requests, and show me what the desk proposes for
each and why. Stop before anything is sent.
```

Or by hand:

```bash
git clone https://github.com/hubzoid/customer-desk-hub customer-desk
cd customer-desk
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
export DESK_PYTHON="$PWD/.venv/bin/python"
```

Keep the folder name lowercase. The desk runs on Claude Code by default. For Codex, set `MODEL=codex-local` in the hub's `.env`.

Give yourself the desk roles with your own Hubzoid account, then check and start:

```bash
for role in desk_operator desk_exceptions desk_delivery desk_complaints desk_bindings; do
  python -m hubzoid grant you@company.example $role .
done
python -m hubzoid hub doctor .
HUBZOID_SCHEDULES=1 python -m hubzoid run . --port 8721
```

If port 8000 is already in use, add `--bridge-port 8722`. In a second terminal, with the same environment activated:

```bash
./desk sample load --wait 900
./desk list
```

The sample is twenty customer requests to a fictional distributor, Synthetic Meridian Distribution, answered from a sample ERPNext. In the web chat at **http://127.0.0.1:8721**, ask:

> What is waiting on the desk?

You see six order status answers, including a late order with a delivery ticket, four invoice copies with the ERPNext print attached, two open-invoice statements, three price and availability answers, two delivery changes, and three complaints, one a refund above the policy amount waiting for the exception team. Ask *"Show CD-000007"* to see one case with its facts, sources, checks and verdict. Nothing is sent.

<!-- Screenshot: a case page with the reply, each fact with its ERPNext source, the checks and the reviewer's verdict. -->

`./desk sample load --adversarial` adds six harder messages: an unknown sender, another customer's invoice, two attempts to give the desk instructions, a statement since 1990 and a resent question. The [setup skill](skills/setup-customer-desk/SKILL.md) holds the same steps for your coding assistant. [Full setup](docs/setup-support.md)

## Integrations

| Works with | What the desk does |
|---|---|
| Zoho Desk | Tags the ticket, adds a private note with the facts and their sources, and leaves the reply as an unsent draft after reading it back. [Zoho Desk](docs/helpdesk-zoho.md) |
| Freshdesk | Writes tags and source evidence to the ticket. The checked reply appears in the Customer Desk app inside the ticket, and the agent inserts it with one explicit confirmation. [Freshdesk](docs/helpdesk-freshdesk.md) |
| ERPNext, read only | Answers order, invoice, statement, price and delivery questions from your own records. [ERP permissions](docs/erp-permissions.md) |
| A support mailbox or WhatsApp Business | Takes requests from `channels/support-email.yaml.example` and `channels/support-whatsapp.yaml.example`. Add each channel id to `DESK_EXTERNAL_CHANNELS`. |

Your team sends the reply in the helpdesk. The desk never sends, closes or assigns a ticket.

Ready for your own helpdesk? Ask your coding assistant to follow the [setup skill](skills/setup-customer-desk/SKILL.md), or the [setup guide](docs/setup-support.md) by hand. You store the helpdesk credentials yourself, never in chat. The first runs are dry runs: the desk records exactly what it would write until you set `DESK_HELPDESK_MODE: live` and `DESK_HELPDESK_DRAFTS: true`.

## Make it yours

The files you will edit, and what each one changes:

```text
customer-desk/
├── AGENTS.md                      the desk assistant in chat
├── agents/<station>/AGENTS.md     classifier, resolver, reviewer and the other stations, one page each
├── knowledge/
│   ├── support/                   your approved support articles, with their sources
│   ├── desk-policy.md             settings enforced in code, and numbered rules the desk cites
│   ├── customer-messages.md       your reply style: three to five of your best past replies and a template per outcome
│   └── company.md                 who you are: contacts, hours, teams
├── connectors/erpnext.yaml        the read-only ERPNext connection
├── channels/                      a support mailbox or WhatsApp number, from the .example files
└── work-items.yaml                how replies leave: off, draft or approve
```

`./desk policy validate` lists every problem in your policy with its line. Import who speaks for which customer with `./desk bindings import --file contacts.csv --dry-run`. To connect your ERPNext, run `scripts/setup_support.py` with `--erp`, set `connectors/erpnext.yaml` to `backend: frappe_rest` with a read-only API key, then apply it with `./desk erp-configure`.

To save a rule from chat, tell the desk *"Never give customers exact stock numbers. Say in stock, limited or out of stock, with limited meaning fewer than 20 units."* It proposes the policy change as a reviewed Hub change. A hub manager applies it, and the next reply follows it, also after a restart. [Policy authoring](docs/policy-authoring.md)

## Safety

- **The desk never sends, closes or assigns a ticket in your helpdesk.** Your team sends the reply there. `./desk stop-writes on` blocks every helpdesk write at once.
- **The desk never writes to ERPNext.** Its connection is read only, and `hubzoid hub doctor` fails if writes are switched on. Each reply reads only the bound customer's own records.
- **Messages are data, never instructions.** Customers never sign in and can never approve anything. A reply the reviewer did not pass stays on the desk until a person edits it.

Approved sending through a Hubzoid channel is off by default. When you turn it on, Hubzoid sends a text reply only after the person who asked approves the exact reply and recipients, and rereads every fact just before it goes out. If anything changed, it refuses and drafts a new revision. A reply with an attachment is sent by a person. [ERP permissions](docs/erp-permissions.md)

## Host it for your team

The desk runs on a server the same way any Hubzoid hub does: one image built from this repository, one durable folder at `/data`, sign-in on, and one public address. Three things are specific to the desk:

- **`HUBZOID_SCHEDULES=1`**, so triage and case work run in the background.
- **`HUBZOID_PUBLIC_URL`**, your hub's HTTPS address. The Freshdesk app signs in to Hubzoid through it, with Hubzoid's MCP sign-in on.
- **The desk roles.** Grant each person only what they do: desk operator, editor, delivery team, complaints team, exception decisions and sender bindings, in **Settings, Agents, Customer Desk, Access, Restricted tools**.

[Operator guide](docs/operator-guide.md) covers running the desk day to day. [Hubzoid deployment](https://github.com/hubzoid/hubzoid/blob/main/docs/deploy/README.md) lists the hosting options and which are verified.

## Go further

| Next step | Guide |
|---|---|
| Set up from your own material | [Setup](docs/setup-support.md) |
| Connect Zoho Desk or Freshdesk | [Zoho Desk](docs/helpdesk-zoho.md), [Freshdesk](docs/helpdesk-freshdesk.md) |
| Write your policy | [Policy authoring](docs/policy-authoring.md) |
| Connect ERPNext read only | [ERP permissions](docs/erp-permissions.md) |
| Map senders to customers | [Bindings](docs/bindings.md) |
| Run the desk day to day | [Operator guide](docs/operator-guide.md) |
| Behaviour checks | [Evals](docs/evals.md) |
| Look up an error or a measure | [Errors](docs/errors.md), [Metrics](docs/metrics.md) |
| How a message becomes a case | [Architecture](ARCHITECTURE.md) |

Questions go to [GitHub Discussions](https://github.com/hubzoid/hubzoid/discussions). Bugs in the desk go to [this repository's issues](https://github.com/hubzoid/customer-desk-hub/issues).

The Customer Desk is **Apache-2.0**. ERPNext is a separate GPL-3.0 application, and none of its code is in this hub. Built on [Hubzoid](https://github.com/hubzoid/hubzoid). Need it running for your team? [Build with us](https://hubzoid.com/build-with-us).
