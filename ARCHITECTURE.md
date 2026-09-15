# Customer Desk architecture

DRAFT for review.

The desk is a Hubzoid hub folder. It adds no code to the Hubzoid SDK and runs only on SDK surfaces: work items, isolated agents (stations), intake, write modes, cards, restricted tools, HITL cards, artifacts, named webhooks and doctor checks.

## The folder

| Path | What it is |
|---|---|
| `AGENTS.md` | The chat assistant teammates talk to. |
| `knowledge/desk-policy.md` | The policy: settings the code enforces, rules the stations cite as `[R1]` to `[R18]`. |
| `knowledge/request-kinds.md` | The only list of request kinds, their helpdesk tags, boundary rules and risk flags. |
| `knowledge/customer-messages.md` | Reply style and the approved template for each outcome. |
| `agents/desk-*` | Five stations: classifier, second opinion, resolver, reviewer, transcript reader. |
| `workflows/customer_desk_intake` | Triage, unattended. |
| `workflows/customer_desk_case` | A person's send or draft, attended. |
| `workflows/zoho_desk` | The Zoho Desk webhook and the modified-ticket poll. |
| `workflows/desk_upkeep` | Keeps cases in step with sends people decided. |
| `workflows/lib/customer_desk` | The desk library. Under `workflows/` so a code change stops in-flight work instead of running it on new code. |
| `tools_local/`, `restricted/` | Chat tools. Each `restricted/desk_<role>.py` is visible only to people holding that role. |
| `connectors/erpnext.yaml` | The read-only ERPNext connection. |
| `work-items.yaml` | Write modes for replies. |
| `hitl.yaml` | Which chat tools always show the exact action and wait for the person. |
| `cards/`, `mcp-apps.yaml` | The queue, case, metrics and approval cards. |
| `doctor/checks.py`, `hub.manifest.yaml` | Setup checks. |
| `fixtures/` | The synthetic distributor's ERP data, the twenty requests, sender bindings. |
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
     At most two revisions. If the model cannot produce a safe draft, the approved templates are used.
  -> ready: needs_owner in the operators, delivery, complaints or decisions queue, with a case page.
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

An approved send is one Hubzoid operation. Before it leaves, the dispatch rereads every ERPNext fact the reply uses and checks the reply is still current and the policy and style are unchanged. Any difference refuses the send and drafts a new revision. A send whose outcome is unknown becomes `ambiguous` and waits for the requester to say done, retry or abandon. It is never resent on its own.

## The helpdesk

`helpdesk/zoho.py` has a read client that only sends GET and a write client whose one request method allows exactly five calls: prefixed tags, private notes carrying the desk marker, one configured case field, an unsent draft reply carrying the marker, and uploads for that draft. The stop switch (`./desk stop-writes on` or `DESK_STOP_WRITES=1`) and the mode are read at the moment of each write. Webhook bodies only name a ticket. The desk rereads it, handles each inbound message once, and ignores the ticket changes its own writes cause.

## Identity and roles

Teammates sign in to Hubzoid. Desk roles are capabilities granted per person: `desk_operator`, `desk_delivery`, `desk_complaints`, `desk_exceptions`, `desk_bindings`. Customers never sign in and can never approve anything. A sender is who the channel verified, matched to one ERP customer by a binding a person made.

## Data

The desk's own records live in `.hubzoid/data/customer-desk.sqlite` in the hub's data folder, which Hubzoid backups include: cases, events, resolutions, facts, reply revisions with their checks, sends, tickets, proposals, decisions, plans, bindings, the helpdesk write ledger and the sample outbox. Resolutions, facts and reply revisions are never changed after they are written. Sample and live cases are kept in separate namespaces.

## ERPNext

`workflows/lib/customer_desk/erpnext/` is an interim read layer written to the HUB-108 contract: sample, fake REST and live Frappe backends, read only. It is replaced by a vendored copy of the read parts of the Order & Invoice Desk's canonical module, marked with its source commit, when that lands.

## What the SDK does not have yet (the later list)

See the proof page. In short: hub-local API routes and Console screens (the desk uses chat, cards, Work items and Intake instead), a public API for a tool to start a work item, a sender directory hook for channel admission, groups that grant permissions, attachments on channel replies, a hub eval kind for workflows with pass^k, and a synthetic intake import.
