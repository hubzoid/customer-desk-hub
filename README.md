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
  <a href="docs/setup-support.md">Setup guide</a> ·
  <a href="docs/helpdesk-zoho.md">Zoho Desk</a> ·
  <a href="docs/helpdesk-freshdesk.md">Freshdesk</a> ·
  <a href="https://github.com/hubzoid/hubzoid">Hubzoid</a>
</p>
<p align="center">
  <a href="https://github.com/hubzoid/hubzoid"><img src="https://img.shields.io/badge/Built%20on-Hubzoid-B5471F" alt="Built on Hubzoid"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/License-Apache%202.0-0B0B0C" alt="Apache License 2.0"></a>
</p>

**The Customer Desk is a ready-to-use Hubzoid hub for your customer care team.
It reads each customer request in your helpdesk, finds the answer in your
approved company knowledge, the ticket's conversation and relevant resolved
answers, and prepares a reply your team reviews and sends.** Connect Zoho Desk
or Freshdesk. Add a read-only ERPNext connection to answer order, invoice,
statement, price and delivery questions from your own records.

<p align="center">
  <a href="https://youtu.be/uJ6QdNVSFHM"><img alt="Watch: customer replies, drafted from your systems" src="https://img.youtube.com/vi/uJ6QdNVSFHM/maxresdefault.jpg" width="640"></a>
</p>

## How it works for you

| A customer asks | The desk does |
|---|---|
| A question your knowledge answers | Prepares the reply from your approved support articles, citing each source. |
| Where is my order | Reads the order from ERPNext: status, delivery date, what is delivered. A late order opens a ticket for the delivery team. |
| An invoice copy | Attaches the official ERPNext print of the customer's own submitted invoice. |
| An account statement | Lists the customer's open invoices and credit notes, with a CSV. |
| A price or availability | Quotes the customer's own price list, and stock as your policy allows: exact, in bands, or not at all. |
| A delivery date change | Checks the notice period and proposes the change to the delivery team. It confirms only after ERPNext shows the new date. |
| A complaint or refund | Opens a ticket. A refund outside your policy waits for a named person to decide. |

Every case shows its facts with the record and field they came from, the policy
rules it used, its checks and the reviewer's verdict.

## Inside your helpdesk

- **Zoho Desk:** the desk tags the ticket, adds a private note with the facts and
  their sources, and leaves the reply as an unsent draft after reading it back.
- **Freshdesk:** tags and source evidence are written to the ticket, and the
  checked reply appears in the Customer Desk app inside the ticket. The agent
  inserts it into the editor with one explicit confirmation.

Your team sends the reply in the helpdesk. The desk never sends, closes or
assigns a ticket. `./desk stop-writes on` blocks every helpdesk write at once.

## Get your first useful result

You need Python 3.11 or 3.12, Git, and Claude Code or Codex signed in on this
machine.

```bash
git clone https://github.com/hubzoid/customer-desk-hub customer-desk
cd customer-desk
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
export DESK_PYTHON="$PWD/.venv/bin/python"
```

The desk runs on Claude Code by default. For Codex, set `MODEL=codex-local` in
the hub's `.env`. Keep the folder name lowercase.

Give yourself the desk roles, with your own Hubzoid account (or in Settings,
Agents, Customer Desk, Access, Restricted tools):

```bash
for role in desk_operator desk_exceptions desk_delivery desk_complaints desk_bindings; do
  python -m hubzoid grant you@company.example $role .
done
```

Connect your helpdesk. Preview the configuration, then repeat with `--apply`
after reviewing the diff:

```bash
python scripts/setup_support.py --provider freshdesk --company 'Your Company' \
  --department 123 --api-base https://company.freshdesk.com/api/v2
```

Zoho uses `--provider zoho_desk` and its regional API base. Add your approved
articles under `knowledge/support/`, store the helpdesk credentials with
`python -m hubzoid secrets set . --name NAME --stdin`, then run the desk on one
real ticket:

```bash
python -m hubzoid hub doctor .
HUBZOID_SCHEDULES=1 python -m hubzoid run .
```

If port 8000 is already in use, add `--bridge-port 8722`.

In a second terminal, with the same environment activated:

```bash
./desk ticket TICKET_ID
./desk list
```

The first runs are dry-run: the desk records exactly what it would write. When
you are ready, set `DESK_HELPDESK_MODE: live` and `DESK_HELPDESK_DRAFTS: true`.
Freshdesk also needs its app from `freshdesk-app/` installed and each agent
linked; see the [Freshdesk guide](docs/helpdesk-freshdesk.md).
[Full setup →](docs/setup-support.md)

<details>
<summary>Try the labelled sample with ERPNext data</summary>

Twenty customer requests to a fictional distributor, Synthetic Meridian
Distribution, answered from a sample ERPNext. Paste into Claude Code or Codex:

```text
Follow skills/setup-customer-desk/SKILL.md to set up the Customer Desk from this
folder on the synthetic distributor. Install Hubzoid, run the hub doctor, load
the twenty sample customer requests, and show me what the desk proposes for
each and why. Stop before anything is sent.
```

Or by hand, after the install above:

```bash
.venv/bin/python -m hubzoid hub doctor .
HUBZOID_SCHEDULES=1 .venv/bin/python -m hubzoid run . --port 8721
```

In a second terminal:

```bash
./desk sample load --wait 900
./desk list
```

Open http://127.0.0.1:8721 and ask *"What is waiting on the desk?"* or *"Show
CD-000007"*. You see six order status answers, including a late order with a
delivery ticket, four invoice copies with the ERPNext print attached, two
open-invoice statements, three price and availability answers, two delivery
changes, and three complaints, one a refund above the policy amount waiting for
the exception team. `./desk sample load --adversarial` adds six harder messages:
an unknown sender, another customer's invoice, two attempts to give the desk
instructions, a statement since 1990 and a resent question.

</details>

## How replies leave

- **In your helpdesk**, the reply waits for a person: an unsent draft in Zoho
  Desk, the checked suggestion in Freshdesk. A person sends it there.
- **Approved sending** (`approve` mode, off by default) applies to Hubzoid
  channels: Hubzoid sends a text reply only after the person who asked approves
  the exact reply and recipients on the Work items page. A reply with an
  attachment, such as an invoice copy, is sent by a person. A real mailbox
  also needs `email.send` set for that channel under `write_mode_overrides`
  in `work-items.yaml`, and `hubzoid hub doctor .` shows each channel's
  effective mode.
- **A reply the reviewer did not pass** stays on the desk, marked "Reviewer
  asked for changes", until a person edits it. It never becomes a draft or a
  send.
- **Just before an approved reply goes out**, the desk rereads every fact it
  uses. If anything changed, it refuses and drafts a new revision.
- **The desk never writes to ERPNext.** Its connection is read only, and
  `hubzoid hub doctor` fails if writes are switched on.

## Make it yours

- **Your knowledge:** approved support articles in `knowledge/support/`, with
  their sources.
- **Your policy:** `knowledge/desk-policy.md`. The settings at the top are
  enforced in code, and the numbered rules are cited by the desk.
  `./desk policy validate` lists every problem with its line.
  [Policy authoring →](docs/policy-authoring.md)
- **Your reply style:** `knowledge/customer-messages.md`, with three to five of
  your best past replies and an approved template per outcome.
- **A correction:** in chat, *"Never give customers exact stock numbers. Say in
  stock, limited or out of stock, with limited meaning fewer than 20 units."*
  The desk proposes the policy change as a reviewed Hub change. A hub manager
  applies it, and the next reply follows it, also after a restart.
- **Your ERPNext:** run `scripts/setup_support.py` with `--erp`, set
  `connectors/erpnext.yaml` to `backend: frappe_rest` with a read-only API key,
  then apply it with `./desk erp-configure`.
  [ERP permissions →](docs/erp-permissions.md)
- **Your channels:** a support mailbox or a WhatsApp Business number, from
  `channels/support-email.yaml.example` and
  `channels/support-whatsapp.yaml.example`. Add each channel id to
  `DESK_EXTERNAL_CHANNELS`.
- **Your senders:** import who speaks for which customer with
  `./desk bindings import --file contacts.csv --dry-run`.
  [Bindings →](docs/bindings.md)

## The team

Roles are granted per person in **Settings, Agents, Customer Desk, Access,
Restricted tools**, or with `python -m hubzoid grant EMAIL desk_operator .`:
desk operator, editor, delivery team, complaints team, exception decisions and
sender bindings. Customers never sign in and can never approve anything.
[Operator guide →](docs/operator-guide.md)

## Evals

```bash
python tests/customer_eval.py --runtime claude-local --runs 4
```

Runs the twenty requests, six adversarial messages, twelve multi-turn
conversations and six safety cases, each in a fresh copy of the hub, and reports
pass^1 to pass^4, following Sierra's tau-bench method. These run from the
command line, not from the Quality tab.
[Evals →](docs/evals.md)

## Go further

| Next step | Guide |
|---|---|
| Set up from your own material | [Setup](docs/setup-support.md) |
| Connect Zoho Desk or Freshdesk | [Zoho Desk](docs/helpdesk-zoho.md), [Freshdesk](docs/helpdesk-freshdesk.md) |
| Write your policy | [Policy authoring](docs/policy-authoring.md) |
| Connect ERPNext read only | [ERP permissions](docs/erp-permissions.md) |
| Run the desk day to day | [Operator guide](docs/operator-guide.md) |
| Look up an error or a measure | [Errors](docs/errors.md), [metrics](docs/metrics.md) |
| How a message becomes a case | [Architecture](ARCHITECTURE.md) |

The Customer Desk is **Apache-2.0**. ERPNext is a separate GPL-3.0 application,
and none of its code is in this hub. Built on [Hubzoid](https://github.com/hubzoid/hubzoid).
Need it running for your team? [Build with us](https://hubzoid.com/enterprise).
