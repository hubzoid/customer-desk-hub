# Customer Desk implementation and scope disposition

The user approved implementation of necessary fixes and raising unmerged PRs on 20 October 2026. That direct approval supersedes the proposals' draft status and the usual merged-proposal/plan gate. This checkout is isolated; the coordinating review and validation precede the PR handoff. Live customer connections and paid resource use remain outside the authorized scope.

## File-by-file work

1. `config.py`, `settings.yaml`, `doctor/checks.py`, `vocab.py`, station schemas: add explicit general support and optional ERP configuration, reviewed category behaviours and inherited runtime selection. Keep legacy ERP/sample defaults compatible.
2. `support.py`, `helpdesk/retrieval.py`, support drafter/reviewer agent folders: collect approved scoped articles and native helpdesk conversation/resolved answers, retain evidence snapshots, draft with citations, check claims and hold unsupported results. Preserve all six ERP handlers.
3. `helpdesk/freshdesk.py`, helpdesk dispatch/read adapters, `flows.py`, poll/webhook workflow and editor tools/app: implement Freshdesk reads/tags and authenticated native editor placement without pretending notes are drafts. Reuse SDK operations and MCP authentication. Persist pending versus confirmed delivery distinctly.
4. `flows.py`, `store.py`, `erpnext/config.py`, `chat.py`, launcher and credential adapters: reproduce/fix ACL refresh pagination, configuration initialization races, runtime hardcoding, relocated interpreter and canonical Hub-ID resolution without changing the vendored ERP copy.
5. `AGENTS.md`, builder recipe, CLI and docs: actual runtime behaviour, file/CLI/API setup, reviewed correction through SDK `hub_changes`, explicit grants, recovery and compatibility evidence. Reuse SDK identity/access/artifacts/data root.
6. Focused offline HTTP/provider/state/security tests, then full hub regression. Record exact SDK commit, skips and unavailable real-provider/runtime/hosting qualification separately.

## Scope decisions and constraints

- Required: Zoho and Freshdesk, own-data support without ERP, optional existing ERP jobs, editable unsent provider replies, scoped evidence/retrieval, runtime neutrality, useful setup, restore/deduplication safety and necessary review defects.
- Optional monthly improvement schedule is omitted from this build. Explicit owner corrections and approved knowledge updates cover the required first/repeat-use journey without unattended policy promotion.
- No vector database, new shared package/repository, replacement harness or custom approval platform.
- Freshdesk persistence must be verified through provider evidence. Editor placement alone stays pending confirmation. Live qualification needs authorized accounts and resources, which are unavailable in this offline build. It cannot be reported as passing.
- SDK must-haves are reported to the coordinating parent before any workaround. Hub-owned business code remains here. Order Desk remains the vendored ERP authority.

## Validation

Test general support, live-fact fallback, category safety, citations/PII, provider filtering, tags/draft fences, linked/revoked editor callers, immutable pending payloads, ACL refresh beyond 100 cases, initialization concurrency and compatibility with existing ERP tests. Run hub doctor on a clean support-only configuration. Real Zoho/Freshdesk, installed-runtime and hosted rows remain unqualified until actually exercised.

## Build evidence before independent review

- Full offline hub suite, including real local workflow-engine cases: 121 passed, no skips, 110.79 seconds (`pytest -m ""`). No live models/providers were invoked.
- Final ACL grant/revoke/restore and legacy polling checks: 4 passed, 24 deselected, 1.39 seconds. The added ACL-cycle case was run after the broader suite.
- Hub doctor: `ok: true`; sample checks pass and missing operator grants are explicitly warned. This does not establish a connected support provider. JavaScript syntax checks pass for the native app and OAuth callback.
- Independent Claude Opus 5.5 reviewed implementation commit `e98b7a1`. Necessary-fix dispositions are recorded in REVIEW-2026-10-20.md. The review corrections and their added regressions await the coordinating parent's sequential verification; the preceding pass counts describe the earlier build.

## Final author validation

Claude Opus 5.5 reviewed the entire implementation at e98b7a1. Necessary fixes and evidence dispositions are in docs/REVIEW-2026-10-20.md. Final exact-SDK-pin offline suite: 143 passed, no skips, 116.70 seconds, including local workflow-engine tests and legacy ERP identity preservation. Native app Node harness passed without a browser. Final Hub doctor reports ok; operator grants remain an explicit setup step. Canonical ERP provenance is a3c3993135ebffa2c291dac3a7780be46f7bf796 in hubzoid/order-desk-hub. No second independent approval or live qualification is claimed.
