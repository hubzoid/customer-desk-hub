# What has been run, and what has not

This page records what the Customer Desk has been run against, on what, and with what result. A row that has not been run is not a support claim.

## Run so far

| Date | Setup | Data | Result |
|---|---|---|---|
| 23 October 2026 | Local Mac, Hubzoid 2.0.1 from PyPI, installed from this README. Claude Code sign-in (`claude-local`), a real model. | The labelled synthetic distributor and the sample ERP backend. | All twenty sample requests matched `evals/expected/customer-desk-20.json` in one run (load to twenty cases ready in 3 minutes 19 seconds). All six adversarial messages handled safely. A policy correction applied as a Hub change changed the next reply, also after a restart. An approved send to the sample outbox was refused as stale after the policy changed, redrafted and sent after approval. |
| 23 October 2026 | Same | Same | Bugs found and fixed in this release: `demo/reset` failed, a reviewer's "revise" verdict did not stop a reply, sample replies showed the read date instead of the sample date, and decline was shown as "approve: false". |

Every change also passes the offline tests (`python -m pytest -q`) with scripted stations, a fake mailbox and local fake Zoho and Freshdesk servers. They prove the desk's logic, not a provider.

## Not run yet

| Host | Runtime | Helpdesk | Status |
|---|---|---|---|
| Local | Claude | Zoho Desk trial | Not run |
| Local | Claude | Freshdesk trial (needs a public HTTPS address for the app) | Not run |
| Local | Codex | Any | Not run |
| Railway | Claude or Codex | Any | Not run |
| Maritime (the second hosting provider Hubzoid documents, next to Railway) | Claude or Codex | Any | Not run |
| Any | Any | A real ERPNext, read only | Not run |

The pass^k evals (`tests/customer_eval.py --runs 4`) have not been recorded on Hubzoid 2.0.2 yet.

## Known gaps

- Freshdesk's app SDK can insert a reply into the agent's editor but cannot confirm it was saved. The desk reports `awaiting_provider_editor` or `awaiting_provider_confirmation` and never assumes a save. An interrupted placement is never replayed automatically. Check the ticket before replacing it.
- Approved sending through a Hubzoid channel sends text only. An invoice copy or other attachment is sent by a person.

## What a row needs before it counts

The hub and Hubzoid versions, the helpdesk edition and scopes, the runtime and how it signs in, cost and limits seen, a useful result on the operator's own material, a teammate allowed and a teammate denied, the callback URLs, a restart with the data kept, scheduled polling and recovery, and for hosted rows sleep and wake, backup and restore, and an upgrade.

## Run the offline checks

One process at a time:

```sh
python -m pytest -q
node tests/freshdesk_app_harness.cjs
```
