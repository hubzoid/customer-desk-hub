# Support from your own material

From this hub folder, use Python 3.11/3.12 and Git to create the environment and install the exact SDK development pin plus the hub dependency:

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
export DESK_PYTHON="$PWD/.venv/bin/python"
```

`requirements.txt` installs Hubzoid 2.0 or later and the desk's one library. Use `python -m hubzoid` rather than a relocated virtualenv entry-point shebang. `./desk` uses the actual interpreter specified above.

Claude Code/Cowork or Codex can perform file/CLI setup where their actual capabilities allow. No Hubzoid UI setup is required. Provider consent, secure credential entry and human approvals remain personal actions. The current SDK does not supply a new non-delegable setup identity. The operating-system owner remains trusted.

1. Preview configuration, then repeat with `--apply` after reviewing the diff:

   ```sh
   python scripts/setup_support.py --provider freshdesk --company 'Your Company' --department 123 --api-base https://company.freshdesk.com/api/v2
   ```

   Zoho uses `--provider zoho_desk` and its regional API base. ERP stays off unless `--erp` is explicit. Existing installations retain legacy defaults until explicitly changed.

2. Preserve originals in knowledge/sources/ only when intentionally shared as Hub content. Prepare articles under knowledge/support/ with frontmatter `status: approved`, exact `company`, `audience: customer`, `language: en`, title, provenance `source` and optional exact provider `product` id. Review content and replace the labelled synthetic sample. Setup selects knowledge/support-kinds.md without ERP, or the existing ERP vocabulary with `--erp`, preserving a custom file choice. Categories use `behavior: answer`, `clarify` or `review`. `erp` is restricted to the existing six jobs. Inferred rules/conflicts need owner decisions, never executable actions.

3. A person runs `python -m hubzoid secrets set . --name NAME --stdin`. Freshdesk uses FRESHDESK_API_KEY from a dedicated restricted integration account. Zoho uses ZOHO_DESK_CLIENT_ID, ZOHO_DESK_CLIENT_SECRET, ZOHO_DESK_REFRESH_TOKEN and their ZOHO_DESK_WRITE_ equivalents. Set Zoho organization, region and support sender in hub.settings.yaml. Never put values in Git/chat. Explicit secret references must name the actual hub key, never a copied example. Operator environment values retain precedence.

4. Use existing CLI/API grants for the internal operator. For Freshdesk, grant desk_operator and desk_editor, then verify the matching provider agent through an administrator:

   ```sh
   python -m hubzoid grant operator@company.example desk_operator .
   python -m hubzoid grant operator@company.example desk_editor .
   ./desk editor-link --agent-id 456 --principal operator@company.example
   ```

   Replace the example email with the internal operator's real account. These verified SDK commands default the grant domain to this hub folder's actual key. Agent/principal emails must match. This grants nothing to external senders.

5. Run `python -m hubzoid hub doctor .`, then `HUBZOID_SCHEDULES=1 python -m hubzoid run .` to start the bridge, workflow engine and scheduler. In another activated terminal run `./desk ticket TICKET_ID`. Inspect `./desk list`, `./desk --json show CASE` and `./desk ledger`. Dry-run records intended writes. Use the configured installed runtime. No second subscription or silent paid fallback is required. Hosted/unattended authentication needs exact-combination evidence.

6. Propose the saved correction using existing SDK Hub changes, with edits in the format documented by its CLI help:

   ```sh
   python -m hubzoid hub-changes propose . --title 'Correct support guidance' --edits /path/to/edits.json
   python -m hubzoid hub-changes decide . CHANGE_ID
   ```

   The owner reviews the exact diff in their terminal/existing approval interface. Read-only hosting uses reviewed builder-checkout changes and redeploy. Rerun the case and verify a new source revision and changed answer. Proposed records are not active knowledge.

7. Only when authorized, set DESK_HELPDESK_MODE: live and DESK_HELPDESK_DRAFTS: true. Keep customer_reply.send: draft. Zoho uses an unsent reply. Freshdesk requires its app. People send personally in the provider. `./desk stop-writes on` immediately blocks writes/editor payloads.

Model/harness inherit the hub's MODEL and station files. Knowledge, rules, connectors, appearance and action policies remain normal supported files/settings. Report provider/model costs, limits and auth rather than implying free hosted operation. Retention and monetary caps remain opt-in.

Back up the SDK data root and source revisions. Before starting restored code, keep `DESK_INTAKE_ENABLED: false` and run `./desk stop-writes on`. Compare `./desk ledger` and `./desk --json show CASE` with every provider ticket touched since the backup, including provider-side drafts/notes created after it; local absence is not proof nothing happened. In Freshdesk inspect the native editor personally; for a recorded interrupted claim use `./desk editor-reconcile TICKET_ID not_inserted` or `placed` only after that inspection. For Zoho inspect the unique desk marker and existing draft; the normal operation reconciliation reuses a matching provider draft instead of reposting. If backup loss removed the corresponding case/reply identities, leave intake/writes off and recover those records from a newer compatible backup or obtain a reviewed manual reconciliation; no tool can safely infer lost identity. Preserve unrelated edits/tags/drafts. Restore compatible code/schema and data-root contents, then explicitly resume intake and `./desk stop-writes off` after reconciliation. Never replay accepted effects blindly.
