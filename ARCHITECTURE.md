# Customer Desk architecture

The desk is a Hubzoid hub folder. It adds no code to the Hubzoid SDK and runs only on SDK surfaces: work items, isolated agents (stations), intake, write modes, cards, restricted tools, HITL cards, artifacts, named webhooks and doctor checks.

## The folder

| Path | What it is |
|---|---|
| `AGENTS.md` | The chat assistant teammates talk to. |
| `knowledge/desk-policy.md` | The policy: settings the code enforces, rules the stations cite as `[R1]` to `[R18]`. |
| `knowledge/request-kinds.md` | The only list of request kinds, their helpdesk tags, boundary rules and risk flags. |
| `knowledge/customer-messages.md` | Reply style and the approved template for each outcome. |
| `knowledge/support/`, `knowledge/support-kinds.md` | Support mode: approved company articles, and the request categories used without ERP. |
| `agents/desk-*` | Seven stations: classifier, second opinion, resolver, reviewer and transcript reader, and for support mode a support drafter and a support reviewer. |
| `workflows/customer_desk_intake` | Triage, unattended. |
| `workflows/customer_desk_case` | A person's send or draft, attended. |
| `workflows/zoho_desk` | The Zoho Desk webhook and the modified-ticket poll. |
| `workflows/freshdesk` | Freshdesk ticket intake. |
| `workflows/lib/customer_desk/helpdesk` | The Zoho Desk and Freshdesk clients, the Freshdesk editor payload, and read-only search of resolved answers. |
| `freshdesk-app/` | The Freshdesk ticket-sidebar app that offers the checked reply to the agent. |
| `scripts/setup_support.py` | Writes the support-mode settings for Zoho Desk or Freshdesk, with ERP off unless `--erp`. |
| `workflows/desk_upkeep` | Keeps cases in step with sends people decided. |
| `workflows/lib/customer_desk` | The desk library. Under `workflows/` so a code change stops in-flight work instead of running it on new code. |
| `tools_local/`, `restricted/` | Chat tools. Each `restricted/desk_<role>.py` is visible only to people holding that role. |
| `connectors/erpnext.yaml` | The read-only ERPNext connection. |
| `work-items.yaml` | Write modes for replies. |
| `hitl.yaml` | Which chat tools always show the exact action and wait for the person. |
| `cards/`, `mcp-apps.yaml` | The queue, case, metrics and approval cards. |
| `doctor/checks.py`, `hub.manifest.yaml` | Setup checks. |
| `workflows/lib/erp` | The ERP module, an exact copy of the read parts of the Order & Invoice Desk's canonical module (see `erp/VENDORED.md`), with its `distributor-v1` dataset: the synthetic distributor's ERPNext records, the twenty Customer Desk requests, six adversarial ones and the sender bindings. |
| `workflows/lib/customer_desk/erpnext` | The desk's read-only adapter over that module. |
| `evals/` | Personas, conversations, safety cases and the expected outcomes. |
| `desk` | The command line. |

## From message to ready case

```
message (sample channel, Hubzoid email or WhatsApp channel, Zoho Desk ticket, chat, transcript)
  -> intake: one case per thread. A follow-up appends and makes every unsent reply stale.
  -> bind: exactly one active sender binding, or binding_required. Nothing is read and no model runs.
  -> classify (station): kinds from the closed list, references, risk flags, a confidence.
     second opinion (station, a different model) only when unsure. Disagreement marks the case for a person. Risk flags only add.
  -> gather (code): the category rules read the bound customer's records only (party scope), register every
     value as a fact with its source, decide each outcome, and create tickets, delivery proposals and
     exception decisions.
  -> resolve (station): words the reply with placeholders such as [[F3]]. It may look up more facts with its
     read tools, which take their case from the running work item, never from the model.
  -> render and check (code): the ten checks. A failure goes back to the resolver.
  -> review (station): an independent check of every claim. "revise" goes back to the resolver.
     At most two revisions. If the model cannot produce a draft that passes every check, the approved templates,
     written from the decided outcomes, are used.
  -> ready: needs_owner in the operators, delivery, complaints or decisions queue, with a case page that only
     desk role holders can open. A triage overtaken by a newer message or triage publishes nothing.
  -> helpdesk write-back (Zoho Desk cases): tags, private note, case field, unsent draft.
```

Unattended triage never waits for an approval and never sends. Every station call, stage and helpdesk write is a saved step of the work item, so a crash resumes where it stopped and repeats nothing that finished.

## The ten checks

On every reply revision: `binding_ok`, `facts_owned`, `placeholders_resolve`, `no_literal_facts`, `policy_actions`, `never_say`, `limits`, `language`, `foreign_ids`, `freshness`. A person's edit runs 1, 2, 3, 6, 7 and 9, and every value they typed is flagged for the approver.

## Leaving the desk

| Mode (`work-items.yaml`, `customer_reply.send`) | Sample email | Sample WhatsApp | Zoho Desk | Hubzoid email channel |
|---|---|---|---|---|
| `off` | nothing | nothing | nothing | nothing |
| `draft` | sample mailbox draft | refused (no drafts) | unsent draft reply | mailbox draft (after `hubzoid channels email rehearse-draft`) |
| `approve` | sample outbox after the requester approves | sample outbox after approval, held outside the 24 hour window | refused (a person sends in the helpdesk) | reply on the stored thread after approval, text only |

An approved send is one Hubzoid operation. Before it leaves, the dispatch rereads every ERPNext fact the reply uses (a statement relists its period, so a payment or a new invoice counts) and checks that the reply is still current, the sender still resolves to the same customer, the requester still holds the case and the desk operator role, and the policy and style are unchanged. Any difference refuses the send and drafts a new revision. `hub.thread.post` takes no dispatch hook, so for a Hubzoid channel the same check runs right before the post, both on the first run and when the work resumes after the approval, and a failed check abandons the approved post. The post names `customer_reply.send` as well as the channel's own action, so the stricter mode applies. Unattended helpdesk triage writes a draft only when `customer_reply.send` is `draft` for `zoho_desk`, so it never parks. A send whose outcome is unknown becomes `ambiguous` and waits for the requester to say done, retry or abandon. It is never resent on its own.

## The helpdesk

`helpdesk/zoho.py` has a read client that only sends GET and a write client whose one request method allows exactly five calls: prefixed tags, private notes carrying the desk marker, one configured case field, an unsent draft reply carrying the marker, and uploads for that draft. The stop switch (`./desk stop-writes on` or `DESK_STOP_WRITES=1`) is read at the moment of each write, and is the instant control. The mode and the draft switch are checked at each write too, against the settings in force (Hubzoid reads hub settings when the process starts, so a mode change applies after a restart). A recovery check counts a write as not made only when it read the ticket's whole listing. Webhook bodies only name a ticket. The desk rereads it, handles each inbound message once, and ignores the ticket changes its own writes cause.

`helpdesk/freshdesk.py` reads Freshdesk v2 with GET and writes only namespaced tags and private notes. It has no send API. The checked reply reaches the agent through the Freshdesk app in `freshdesk-app/`, as an authenticated editor payload (`helpdesk/editor.py`) that the agent inserts with an explicit confirmation. Placing text in the editor is never recorded as a saved draft. In support mode, `helpdesk/retrieval.py` searches resolved answers read-only; that evidence is data, never a grant or a current fact.

## Identity and roles

Teammates sign in to Hubzoid. Desk roles are capabilities granted per person: `desk_operator`, `desk_delivery`, `desk_complaints`, `desk_exceptions`, `desk_bindings`. Customers never sign in and can never approve anything. A sender is who the channel verified, matched to one ERP customer by a binding a person made. The binding is resolved again on every triage, every station read and every send (`scope.py`): a revoked or contested binding stops every read at once, and a case never reads under a customer id it stored earlier. Another sender on the same thread or ticket gets a case of their own.

## Data

The desk's own records live in `.hubzoid/data/customer-desk.sqlite` in the hub's data folder, which Hubzoid backups include: cases, events, resolutions, facts, reply revisions with their checks, sends, tickets, proposals, decisions, plans, bindings, the helpdesk write ledger and the sample outbox. A triage reserves its resolution number when it starts and fills it once. Facts and reply revisions are never changed after they are written. Sample and live cases are kept in separate namespaces, and case and ticket numbers are one sequence across them.

## ERPNext

The ERP code is the Order & Invoice Desk's canonical module (decision B042). `workflows/lib/erp/` is a byte-for-byte copy of its read parts and its `distributor-v1` dataset, taken from an order-desk-hub commit. `erp/VENDORED.md` names the commit, lists what was left out (`write.py`, `digest.py`, `bootstrap.py`) and holds a sha256 for every file. `tests/test_vendored_erp.py` fails if any byte differs, if the dataset no longer matches its own manifest, or if the write contract comes back. `scripts/check_vendored_erp.py` compares the copy with the canonical commit itself. A bug found in the copy is fixed once in the canonical module and copied again, never patched here.

The desk reaches the module only through `workflows/lib/customer_desk/erpnext/`:

- `config.load` takes the configuration in force from the module (`connectors/erpnext.yaml`, applied as a numbered revision with `./desk erp-configure`) and refuses it with `erp_not_read_only` if `writes_enabled` is true or a submit credential is set. Doctor runs the same check on the file and reports an edit not yet applied as drift.
- `adapter.DeskERP` has read methods only: get a record, list records, the official invoice print, and the doctor reads. Every read carries the case's bound customer as `party_scope`, so another customer's record reads as `not_found`, and only six resources are allowed: customers, items, prices, availability, sales orders and sales invoices. Stock counts only the configured warehouses.
- The vendored backends keep their own `insert` and `submit` methods, because the files are unchanged. Nothing in the desk calls them, asks the module for a writer or imports a write module, and a test walks every desk source file to keep it that way.

Backends: `sample` (the dataset plus a local state file, no network), `fake_rest` (the real REST client against the module's fake Frappe server on loopback) and `frappe_rest` (a live site, read only). The sample's state file is also where `./desk sample erp-set` records a person's stand-in ERP change for a demo, as a newer copy of one document. The dataset files never change.

## What the SDK does not have yet (the later list)

See the proof page. In short: hub-local API routes and Console screens (the desk uses chat, cards, Work items and Intake instead), a public API for a tool to start a work item, a sender directory hook for channel admission, groups that grant permissions, attachments on channel replies, a hub eval kind for workflows with pass^k, and a synthetic intake import.
