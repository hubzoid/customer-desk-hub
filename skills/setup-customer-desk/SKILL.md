---
name: setup-customer-desk
description: Set up, check and make your own the Customer Desk hub. Use when a builder asks Claude Code or Codex to install the desk, run it on the sample, connect a helpdesk, ERPNext or a mailbox, change the policy or knowledge, give teammates access, or run the evals.
---

# Setting up the Customer Desk

You are helping a builder set up the Customer Desk from this hub folder, in Claude Code or Codex. Work in small steps, show what you ran and what it printed, and stop before anything could reach a customer.

## Never

- Never put a secret in a file, a command line or the chat. A person enters secrets with `python -m hubzoid secrets set . --name NAME --stdin`.
- Never set `writes_enabled: true` in `connectors/erpnext.yaml`. The desk only reads ERPNext.
- Never approve a send, decide an exception, verify a delivery or grant access for the builder. Those are a person's own steps, on the Work items page, in a confirmation card or with their own `hubzoid grant`.
- Never switch `customer_reply.send` to `approve` unless the builder asks for approved sending in so many words.
- Never claim a provider, host or runtime works because the offline tests pass.

## 1. Install and choose the runtime

1. `python3.12 -m venv .venv` (3.11 also works), `source .venv/bin/activate`, `python -m pip install -r requirements.txt`, then `export DESK_PYTHON="$PWD/.venv/bin/python"`.
2. Ask which assistant runs the desk's stations: Claude Code (the default) or Codex. For Codex, put `MODEL=codex-local` in the hub's `.env`. The chosen tool must be signed in on this machine.
3. Keep the folder name lowercase (for example `customer-desk`).

## 2. First result on the sample

1. `python -m hubzoid hub doctor .` Every check passes except `desk-roles`, which warns until people hold the desk roles. Say "Sample mode. ERPNext backend sample, read only. Replies go to the sample outbox only."
2. Give the builder the desk roles. They run it themselves, with their own Hubzoid account:

   ```sh
   python -m hubzoid grant you@company.example desk_operator .
   python -m hubzoid grant you@company.example desk_exceptions .
   python -m hubzoid grant you@company.example desk_delivery .
   python -m hubzoid grant you@company.example desk_complaints .
   python -m hubzoid grant you@company.example desk_bindings .
   ```

   Or in the web app: Settings, Agents, Customer Desk, Access, Restricted tools.
3. Start the hub: `HUBZOID_SCHEDULES=1 python -m hubzoid run . --port 8721`. If port 8000 is taken, add `--bridge-port 8722`.
4. `./desk sample load --wait 900` loads the twenty synthetic requests. If a station cannot reach the model, cases wait at `triaging` with `model_auth_required`: sign in to the runtime and rerun.
5. `./desk list`, then `./desk show CD-000007`. Present the queue as a table with case, customer, channel, request kinds, outcome and the first line of the reply. For one case show the facts with their ERPNext sources, the rules cited, the reply, the checks and the reviewer's verdict.
6. Compare with the expected spread: six order status answers (three on track, one late order with a delivery ticket, one draft order not confirmed, one cancelled), four invoice copies with the PDF, two statements, three price and availability answers, two delivery changes and three complaints (one refund above the policy amount waiting for the exception team). The exact outcome per request is `evals/expected/customer-desk-20.json`.
7. `demo/reset` starts the sample again. It refuses in live mode.

Nothing is sent. Email replies are at most drafts in the sample mailbox, and WhatsApp replies are off.

## 3. First approved send (only when asked)

"Take the order status case, enable approved sending for the sample outbox, and let me approve it myself."

1. Show the diff to `work-items.yaml` setting `customer_reply.send: approve`, and apply it only after the builder says yes.
2. `./desk claim CD-000001`, then `./desk send-request CD-000001 --reply N --digest sha256:...` with the values from `./desk show CD-000001`.
3. It prints `human_action_required`. Stop and tell the builder to open the Work items page and approve the exact reply. You cannot approve it.
4. When they say done, `./desk show CD-000001` reads "Sample outbox accepted the reply. No customer delivery." with the receipt.

Approved sending through a Hubzoid channel sends text only. The sample outbox accepts attachments only so the approval checks can be exercised. A real invoice copy is attached and sent by a person.

## 4. Your own helpdesk and knowledge

1. Ask for the company name, the helpdesk (Zoho Desk or Freshdesk) and which material to use. Never ask for credentials.
2. Preview `python scripts/setup_support.py --provider freshdesk --company 'Your Company' --department 123 --api-base https://company.freshdesk.com/api/v2` (Zoho: `--provider zoho_desk` and its regional API base), show the diff, then repeat with `--apply` when the builder agrees. ERP stays off unless they pass `--erp`.
3. Copy their originals unchanged into `knowledge/sources/`. Write approved articles under `knowledge/support/` with `status: approved`, `company`, `audience: customer`, `language: en`, a title and the `source`. Add no rule their files do not state, and list any conflict or default you inferred for them to decide.
4. A person stores the helpdesk secrets (`docs/helpdesk-zoho.md`, `docs/helpdesk-freshdesk.md`).
5. `python -m hubzoid hub doctor .`, start the hub, then `./desk ticket TICKET_ID` on one real ticket in dry-run, and show `./desk show CASE` and `./desk ledger`.
6. Live drafts only when the builder says so: `DESK_HELPDESK_MODE: live` and `DESK_HELPDESK_DRAFTS: true`. Keep `customer_reply.send: draft` for the helpdesk.

## 5. Make it yours

"Replace the sample policy with our rules from ./ours/returns.pdf, and our reply style from ./ours/replies/."

1. Copy the originals unchanged into `knowledge/sources/`.
2. Edit `knowledge/desk-policy.md` and `knowledge/customer-messages.md`.
3. `./desk policy validate`, and tell them each gap it lists, in its own words.
4. Rerun one case and show the difference.

A correction from chat ("Never give exact stock numbers, say in stock, limited or out of stock") becomes a Hub change that a manager applies. Then rerun the case, restart the hub, and rerun again to show the rule came from the file. When the hub runs from read-only source, make the change in the builder's checkout, review it and redeploy.

## 6. Live connections

- ERPNext: `docs/erp-permissions.md`. Keep `writes_enabled: false`. A person enters the API key.
- A mailbox: `channels/support-email.yaml.example` and Hubzoid's channel commands. A real mailbox also performs `email.send`. For approved replies, add `email.send: approve` for that channel under `write_mode_overrides` in `work-items.yaml` (for drafts, `email.send: draft`), never as a global default. `hubzoid hub doctor .` shows each channel's effective mode.
- Senders: `./desk bindings import --file contacts.csv --dry-run`, show the conflicts, then import.

## 7. Evals

`.venv/bin/python tests/customer_eval.py --runtime claude-local --runs 4` (or `--runtime codex-local`) and report the pass^k table as it prints. Say plainly that these are release gates on synthetic data, not quality claims.
