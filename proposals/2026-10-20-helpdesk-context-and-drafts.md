# Customer Desk: company context, helpdesk tags and reviewed drafts

Status: Draft, pending human approval. No implementation is authorized.
Proposed destination: `customer-desk-hub/proposals/2026-10-20-helpdesk-context-and-drafts.md`.
Companion: [Ready-to-use hubs common contract](2026-10-20-ready-hubs-common-contract.md).

## Problem

Customer Desk should help staff answer customers in their existing helpdesk. Currently `vocab.py` and `gather.py` require six ERP jobs: order status, invoice copy, account statement, price/availability, delivery change and complaint. ERP binding gates triage. Policy, style, case history and ERP facts exist. Similar resolved-ticket retrieval and Freshdesk do not. Zoho tag, note and draft code exists.

Product/service support cannot immediately use company knowledge and previous answers without ERP assumptions. The reported `35068825` baseline has 91 passing synthetic checks, not live provider/runtime proof.

## Why now

Own-data value and a saved correction are required. B029 governs drafts/approvals, B037 single-runtime defaults, B038 SDK reuse and B042 repository ownership and complete delivery. Resolve support behaviour before extending ERP-only code.

## What should happen

### Connect, personalize and prove value

A builder uses Claude Code, Cowork or Codex authoring to configure Customer Desk and select company material/scopes. No manual Hubzoid UI setup is required. Consent, login and secure secret entry remain human handoffs. Delegated setup cannot widen grants, read/administer secret values, activate shared context or approve actions. Protected acts use existing SDK confirmation in a separate non-delegated human session, bound to principal, action/resource, digest and time. Missing separation is an SDK prerequisite, not a new approval platform. Setup conversation requires an approved saved change to become shared context.

The assistant proposes knowledge, category/tag mappings, style and rules from selected material, preserving originals and provenance. The owner reviews the diff, conflicts and inferred defaults. A correction from chat, helpdesk or MCP becomes a proposed-change record in the SDK data root with evidence and an exact diff. An authorized human approves activation through the supported builder/update workspace, including when hosted sources are read-only. Chat tools never write outside `<hub>/output/<session>/`. Run a real ticket, show its tags and editable unsent reply, activate one correction and prove its effect. General support needs no ERP.

### One support core, optional factual jobs

Owner-defined categories map to tags and reviewed behaviours: answer, clarify, human review or an enabled factual job. Categories cannot introduce executable actions or tool grants. New actions need reviewed implementation and grants. Preserve all six ERP jobs, safeguards and tool names/schemas/outputs. Private ERP reads still require company/customer binding. Unbound general questions can use permitted support material.

Drafts distinguish approved rules/knowledge, current conversation, relevant resolved-ticket answers and optional live facts. Record source identifiers, timestamps, scope, rule/configuration revisions and claim citations. Show staff evidence without leaking other customers' identifiers or private citations into replies.

Use native lexical/facet search following generic SupportHub patterns, filtered by authorized tenant, department, product, language and audience. Select meaningful human-sent resolved answers, excluding acknowledgements/drafts and masking names, signatures and unnecessary personal data. Copy no private data, domain rules or unverified licensed material. No vector database or full backfill is required.

History is precedent, never today's status, refund approval, price or delivery promise. Current company rules govern behaviour and verified records govern live facts. Distinguish conflicts, stale evidence, denied lookups and missing records. Hold unsafe claims or ask supported clarifications. Invent no progress/promises. Tickets, attachments and retrieval are untrusted data.

### Complete provider draft experience

Automatic processing rereads a ticket after authenticated intake, applies only enabled namespaced tags, and prepares an unsent reply for a staff member to edit and send in that provider. Never overwrite a human draft, remove unrelated tags, send, close, assign or change priority implicitly. Recheck the latest customer message, human response, draft ownership and ticket state immediately before writing. Key writes by tenant, ticket, message version and draft/configuration revision, with reconciliation after ambiguous timeouts.

Qualify capabilities separately for each provider: scoped reads/search, tags, private evidence annotation, unsent editable reply placement, attachments if promised, concurrent-editor safety and draft readback. Zoho implementation presence is not acceptance evidence.

Freshdesk's [REST reference](https://developers.freshdesk.com/api/) documents replies and notes, not an assumed unsent-draft endpoint. Its [App SDK](https://developers.freshworks.com/docs/app-sdk/v3.0/support_ticket/front-end-apps/interface-methods/) documents editor text insertion, which does not establish persistence. A private note is never a reply draft. Pending approval, this scope includes a narrow owned editor app in this repository when native APIs cannot meet the outcome. A Freshdesk administrator installs it through the supported custom-app mechanism, with the required public URL/authentication configuration documented.

Each app request authenticates a Hubzoid principal through a verified link to the Freshdesk agent. Check current ticket scope, draft grant and revocation before returning payloads. Unlinked or revoked callers receive none. Never embed a static browser service credential. Before insertion, verify current message and human-editor state without replacing or appending to a human draft automatically. Work remains `awaiting_provider_editor` until placement, then `awaiting_provider_confirmation` without persistence evidence. Never claim `draft_saved` without verified provider persistence/readback. Inability to prove persistence is unmet acceptance and returns for a scope decision, never a note-only substitute.

### Shared context, customization and authority

Chat, workflows and MCP call common domain services returning permission decisions, rule/source revisions and evidence references. Hub instructions/style apply where Hubzoid runs the agent, including delegated-agent MCP tools. Raw MCP tools cannot enforce an external client's generation. Live retrieval records policy revision and evidence snapshot, not an identical-result promise.

One authority owns each setting. File-authoritative instructions, rules, tool/action policies, role bundles, connector definitions and design settings change through reviewed revisions in the hub folder. Runtime-authoritative identities, verified account links, member assignments, secrets and approvals live in the SDK store with CLI/API inspection, safe export and backup. Secret values remain protected. No setting has two writable authorities.

Customize model, harness, webapp theme/layout, connectors, knowledge and policy through supported files/extensions, preserving the single webapp and tool interfaces. Arbitrary compatibility is not promised. The common contract covers all seven priorities, including finished pages and explicit source/tool/action access.

| Actor | Context and configuration | Tools and actions |
|---|---|---|
| Builder with grants | Propose file changes and inspect permitted evidence | Delegated setup cannot widen grants, administer secret values, activate shared context or approve actions |
| Member/operator | Read authorized evidence and edit permitted drafts | Provider sends use current provider authority. Hubzoid sends require current case/send grants, configured sender, enabled mode and exact human approval |
| Administrator/owner | Review and activate shared changes, scope sources and manage membership | Grant tools/actions, connect providers and enable modes. Admin status alone does not invent business approval |
| Workflow/MCP caller | Same tenant, user/service identity and source scope checks | Explicit grants and action modes. An unattended run cannot impersonate an approver |

Unconnected writes are `off`. Connected inert drafts default to `draft`. Explicitly enabled `approve` requires a verified internal human with approval grant and resource scope approving the exact content, recipients, attachments and digest. External customers and services never approve. An authorized owner may self-approve, without a mandatory two-person rule. Before dispatch, recheck current grants, sender, mode and provider state, then recompute under current rule/source revisions. Lost authority always blocks. A changed digest voids approval and requires a fresh preview and human approval. An identical digest records both revisions. Context activation and business-action approval stay separate. No automatic sends or ERP submissions are introduced.

An optional monthly schedule proposes cited knowledge/category/rule diffs from authorized outcomes for owner review, never activation. Flag conflicts, weak samples and sensitive material. History is not autonomous memory.

## Scope and non-goals

Change hub-owned knowledge/policy and bootstrap instructions, vocabulary and generic support routing, retrieval/evidence handling, Zoho/Freshdesk adapters, existing pages/cards/tools, runtime selection, diagnostics, tests and operations documentation. Keep read-only ERP code as the marked copy owned by Order & Invoice Desk under B042. No fourth repository or shared package is created.

Reuse installed-runtime adapters and existing workflow, intake, secret, identity, access and webapp infrastructure. Demonstrated generic gaps alone become must-have SDK proposals/PRs, including proposed-change storage/activation if missing. Test immutable SDK pins and promote only against a tagged SDK release. Do not rebuild a harness or merge SDK PRs automatically. Product code remains Apache-2.0 without feature gates.

Migrate with dry-run diffs, backup and versioned activation, retaining records and ERP tools. Mark incompatible drafts stale. After restore/rollback, reconcile provider tags and drafts for every case touched since backup before writing. Never duplicate a draft for an already-drafted message version or remove unrelated edits, tags or drafts not attributable to a recorded Hubzoid write. Historical imports are opt-in, scoped, resumable and idempotent. Keep data until deletion unless retention is enabled.

Compare native automation, Zia/Freddy and manual drafting on actual tenant capabilities and effort. Portable company context, factual tools and controlled rules are the proposed value. Measure it. Superiority, savings and pricing are unproven.

## Open questions

Approval must adopt the proposed authority boundary, settings model, conditional Freshdesk app and qualification table. Recommended scope: English first-use/interface, qualified reply languages, approved text/articles and existing ERP invoice attachments. Edition capabilities, least-privilege scopes, audience mappings and policy/recovery owner are deployment inputs, never inferred grants. Freshdesk persistence remains an outcome gate. Set measured performance/quality thresholds before release. No phased scope cut is permitted.

### Required qualification rows

Every row requires real Zoho **and** Freshdesk ERP-free journeys, including the editor app when required. Each provider is independently required, rather than a choice for qualification.

| Host | Runtime | Setup surface | Optional ERPNext |
|---|---|---|---|
| Local | Claude only | Claude Code and Cowork, separately | Scoped enrichment required |
| Local | Codex only | Codex authoring | Scoped enrichment required |
| Railway | Claude only | Claude Code | Scoped enrichment required |
| Railway | Codex only | Codex authoring | Scoped enrichment required |
| Maritime | Claude only | Cowork | Scoped enrichment required |
| Maritime | Codex only | Codex authoring | Scoped enrichment required |

Every row also qualifies the existing optional ERP factual jobs for both helpdesks. ERP-free and ERP-enriched journeys are separate required checks. Hosted rows satisfy common persistence, restart, scheduler, access, backup and recovery acceptance. Other matrix cells receive synthetic coverage only and carry no support claim. Local first use may use the installed runtime's existing sign-in without API spend. Unattended intake, monthly schedules, hosted and teammate use record authentication type and evidence for that exact row. Local login proves none of those combinations. Testing requires separately authorized provider/resource scope.

## Definition of done

- All required rows pass on immutable tested pins and a tagged SDK release for promotion. Record authentication type, versions, provider configuration and costs. No second subscription or cross-vendor review is required by default.
- Both providers prove tags, editable persisted unsent replies, evidence, staff editing and human-controlled send. Test accidental-send prevention, human-draft preservation, reload, deduplication, retries and restore reconciliation. Editor-app tests cover no operator session, first open, concurrent editors, browser restart, unlinked/revoked callers receiving no payload and absent persistence evidence remaining pending. Revoked case/send/sender grants block sends despite earlier approval.
- Bootstrap, proposed correction and authorized activation survive restart/read-only hosting. General support works without ERP and existing ERP jobs remain covered. Fixed fixtures prove identical service decisions, revision/evidence identifiers and allow/deny results across Chat/Workflow/MCP. Live retrieval records snapshots.
- Test cross-tenant/customer denial, malicious retrieval, PII minimization, stale/conflicting rules, invented promises, source revocation, pagination and outages. Reproduce reported ACL/global-cursor leakage, first-doctor race, hardcoded Claude stations, venv-shebang and secret Hub-ID mismatch before declaring current defects or fixes.
- Queue, case, evidence, draft, rule-review, permissions, health and metrics pages act on real state with complete empty/error states. Publish setup, limits, troubleshooting, backup/restore and upgrade/rollback instructions.
- Run focused and one broader regression check. Disclose exclusions, skips, timeouts and provider gaps. Measure first-result time, draft latency, usage, retrieval relevance, staff edits/acceptance, wrong tags and unsupported claims against manual/native work. Report workload/distributions without invented savings or timings.
