# Customer Desk evidence and remaining qualification

Build checkout: base `35068825` (abbreviated). SDK inspected/used for completed focused tests: `c4bf1dbeaf0e498c364bfa1b1b97f10c7ae3c60c`. Runtime Python: the existing Customer Desk virtualenv interpreter, Python 3.12.6. No new environment, container or paid resource was created.

Completed before the laptop RAM restriction: 28 focused policy, binding and Zoho HTTP tests passed. The first sandboxed run had 9 loopback-bind errors, then the identical focused set passed with local synthetic-server permission. These are synthetic HTTP tests, not real-tenant/model proof. Compilation succeeded before later light edits. No further test/browser/model process is launched while the coordinating parent serializes checks.

The coordinating parent subsequently ran the pre-review build: 121 full offline tests passed with no skips, then four final ACL-cycle/polling checks passed. Independent Claude Opus 5.5 reviewed commit `e98b7a1`. See REVIEW-2026-10-20.md for dispositions. Necessary review fixes passed 50 focused checks and the Node app harness, then 142 broader checks. After the final ERP mirror, 143 tests passed with no skips against the exact c4bf1dbe SDK source (116.70 s). Hub doctor reports ok with the expected missing-role warning. Initial runs used the additive f99a224 SDK checkout; the final exact-pin run closes that difference.

## Implemented scope

- General support without ERP, approved scoped articles, conversation evidence and bounded resolved-answer retrieval, cited drafting and independent applicability review.
- Existing six ERP jobs and sample defaults retained, with explicit support/ERP switches.
- Zoho unsent draft creation with readback and conservative preflight. Freshdesk reads, namespaced tags/private evidence notes and native-editor app using existing MCP OAuth+PKCE and scoped verified account links.
- Freshdesk operator-confirmed replacement, atomic placement claims, protected existing-case PDF download/manual attach, human CLI reconciliation and explicit uncertain/pending states. No automatic app-open insertion, send endpoint or invented persistence proof.
- Per-case ACL refresh state and immediate retirement of all stale case artifact copies, including beyond one refresh batch. Canonical coordinated ERP data-root/initialization updates, inherited station runtime and interpreter-aware launcher.
- Trusted-host assistant setup, existing SDK Hub-change corrections and builder-checkout redeployment for read-only source.

## Required qualification matrix

Both real Zoho and Freshdesk are required on every row, for ERP-free support and optional scoped ERP enrichment under the approved build proposals. All real rows remain **not run**, because live customer connections and paid provider resources were not authorized for this build.

| Host | Sole runtime | Authoring setup | Real provider result |
|---|---|---|---|
| Local | Claude | Claude Code and Cowork separately | Not run |
| Local | Codex | Codex | Not run |
| Railway | Claude | Claude Code | Not run |
| Railway | Codex | Codex | Not run |
| Maritime | Claude | Cowork | Not run |
| Maritime | Codex | Codex | Not run |

Record exact SDK/hub commit, tagged SDK release for promotion, provider edition/scopes, runtime/model/auth method, costs/limits, own-data result, teammate allowed/denied access, callbacks, restart/custom-data-root persistence, scheduler/recovery, sleep/wake, backup/restore and upgrades. Local subscription sign-in establishes no hosted/shared/unattended compatibility claim.

The native Freshdesk App SDK documents editor insertion but no persistence readback. This implementation reports `awaiting_provider_editor`, an in-progress claimed placement or `awaiting_provider_confirmation`. Persisted native-draft acceptance is unmet until real provider evidence verifies it. An interrupted claim never expires/replays automatically. Inspect the provider before any replacement. This is a documented required qualification gap, not a passing draft check.

No FDK packaging, real browser/provider installation, real model, Railway or Maritime journey has run. Synthetic checks cannot establish those combinations. Review resources sequentially to respect laptop memory limits.

## Explicit optional deferrals

The monthly proposed-improvement schedule is omitted. Explicit owner corrections and approved knowledge edits deliver the primary first/repeat-use journey. A generic non-delegable setup credential and new approval platform are deferred. The current concrete path trusts the local host owner and reuses existing SDK approvals/access. No new Cowork helper, vector store, shared package or alternate chat application is introduced.

## Reproduce offline verification

Run from a correctly installed checkout, one process at a time:

```sh
python -m pytest tests/test_support.py tests/test_freshdesk_support.py tests/test_support_safety.py -q
node tests/freshdesk_app_harness.cjs
```

Then one full hub regression with local synthetic-server permission:

```sh
python -m pytest -m "" -q
```

Engine/real-model tests must be inspected individually for prerequisites and actual execution. A critical skip or timeout is not a pass. The coordinating parent runs the independent Claude review and owns commits/PR handoff.
