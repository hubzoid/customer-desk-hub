---
name: setup-customer-desk
description: Set up, check and make your own the Customer Desk hub. Use when a builder asks Claude Code or Codex to install the desk, run it on the sample, connect ERPNext, a mailbox or Zoho Desk, change the policy, or run the evals.
---

# Setting up the Customer Desk

You are helping a builder set up the Customer Desk from this hub folder. Work in small steps, show what you ran and what it printed, and stop before anything could reach a customer.

## Never

- Never put a secret in a file, a command line or the chat. A person enters secrets with `hubzoid secrets set . --name NAME --stdin`.
- Never set `writes_enabled: true` in `connectors/erpnext.yaml`. The desk only reads ERPNext.
- Never approve a send, decide an exception or verify a delivery for the builder. Those are a person's own steps on the Work items page or in a confirmation card.
- Never switch `customer_reply.send` to `approve` unless the builder asks for approved sending in so many words.

## First result on the sample (about ten minutes)

1. `python -m venv .venv`, then `.venv/bin/pip install "hubzoid @ git+https://github.com/hubzoid/hubzoid@main" -r requirements.txt`.
2. `.venv/bin/hubzoid hub doctor .` Every check should pass except `desk-roles`, which warns until people hold the desk roles. Say "Sample mode. ERPNext backend sample, read only. Replies go to the sample outbox only."
3. Add `HUBZOID_SCHEDULES=1` to `.env` and start the hub: `.venv/bin/hubzoid run . --port 8721`.
4. `.venv/bin/python desk sample load --wait 900` loads the twenty synthetic requests. If a station cannot reach the model, cases wait at `triaging` with `model_auth_required`: sign in to Claude Code or Codex and rerun.
5. `.venv/bin/python desk list`, then `.venv/bin/python desk show CD-000007`. Present the queue as a table with case, customer, channel, request kinds, outcome and the first line of the reply. For one case show the facts with their ERPNext sources, the rules cited, the reply, the checks and the reviewer's verdict.
6. Compare with the expected spread: six order status answers (three on track, one late order with a delivery ticket, one draft order not confirmed, one cancelled), four invoice copies with the PDF, two statements, three price and availability answers (a contract price, an item out of stock in the main warehouse, a disabled item not quoted), two delivery changes (one proposal, one already delivered) and three complaints (one refund above the policy amount waiting for the exception team). The exact outcome per request is `evals/expected/customer-desk-20.json`.

Nothing is sent. Email replies are at most drafts in the sample mailbox, and WhatsApp replies are off.

## First approved send (only when asked)

"Take the invoice copy case, enable approved sending for the sample outbox, and let me approve it myself."

1. Show the diff to `work-items.yaml` setting `customer_reply.send: approve`, and apply it only after the builder says yes.
2. `.venv/bin/python desk claim CD-000007`, then `.venv/bin/python desk send-request CD-000007 --reply N --digest sha256:...` with the values from `desk show`.
3. It prints `human_action_required`. Stop and tell the builder to open the Work items page and approve the exact reply. You cannot approve it.
4. When they say done, `desk show CD-000007` reads "Sample outbox accepted the reply. No customer delivery." with the receipt.

## Make it yours

"Replace the sample policy with our rules from ./ours/returns.pdf, and our reply style from ./ours/replies/."

1. Copy the originals unchanged into `knowledge/sources/`.
2. Edit `knowledge/desk-policy.md` and `knowledge/customer-messages.md`. Do not add any rule their files do not state.
3. `.venv/bin/python desk policy validate`, and tell them each gap it lists, in its own words.
4. Rerun one case and show the difference.

A correction from chat ("Never give exact stock numbers, say in stock, limited or out of stock") becomes a hub change proposal that a manager applies. Then rerun the case, restart the hub, and rerun again to show the rule came from the file.

## Live connections

- ERPNext: `docs/erp-permissions.md`. Keep `writes_enabled: false`. A person enters the API key.
- A mailbox: `channels/support-email.yaml.example` and Hubzoid's channel commands.
- Zoho Desk: `docs/helpdesk-zoho.md`. Start in `dry-run`, read `desk ledger`, then `shadow`, then `live`.
- Senders: `desk bindings import --file contacts.csv --dry-run`, show the conflicts, then import.

## Evals

`.venv/bin/python tests/customer_eval.py --runtime claude-local --runs 4` and report the pass^k table as it prints. Say plainly that these are release gates on synthetic data, not quality claims.
