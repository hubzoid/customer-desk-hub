# Zoho Desk

What has been run against a real Zoho Desk is in [provider-qualification.md](provider-qualification.md). Freshdesk has its own guide, [helpdesk-freshdesk.md](helpdesk-freshdesk.md). Zendesk is not supported.

With Zoho Desk connected, tickets live in Zoho Desk and your team sends from there. For each new customer message the desk:

1. rereads the ticket and its threads through the API (a webhook only names the ticket)
2. uses approved general support sources when enabled. Optional ERP jobs bind the contact to one ERP customer before private ERP reads
3. prepares the case as usual
4. writes back: the request kind tags, a private note with the case number, outcomes, ERP facts and their sources, the case number in one custom field if you name it, and the proposed reply as an unsent draft with the invoice PDF attached

It never sends, closes, assigns or changes the status or priority of a ticket. Just before writing the draft it rereads the ticket, and writes nothing if the ticket was closed, an agent already replied, a newer customer message arrived, or someone else has a draft open. An older desk draft is never edited.

## Modes

| `DESK_HELPDESK_MODE` | Writes |
|---|---|
| `dry-run` (default) | Nothing. Every intended write is recorded in `./desk ledger`. |
| `shadow` | Tags only, with a `shadow-` prefix. Notes and drafts stay previews. |
| `live` | Tags, notes and the case field. Drafts also need `DESK_HELPDESK_DRAFTS: true`. |

Stop all helpdesk writes at once with `./desk stop-writes on`, or `DESK_STOP_WRITES=1`. Both are read at the moment of each write, including by work already running.

## Setup

1. In Zoho's API console (api-console.zoho.com), create two self clients: one with `Desk.tickets.READ` and `Desk.basic.READ`, and one for writing with `Desk.tickets.READ`, `Desk.tickets.CREATE` and `Desk.tickets.UPDATE`. Generate a refresh token for each. Zoho's UPDATE scope also allows sending replies, so the desk's code, not the scope, is what keeps sending out.
2. A person enters the six values:

```bash
hubzoid secrets set . --name ZOHO_DESK_CLIENT_ID --stdin
```

(and the same for `ZOHO_DESK_CLIENT_SECRET`, `ZOHO_DESK_REFRESH_TOKEN`, `ZOHO_DESK_WRITE_CLIENT_ID`, `ZOHO_DESK_WRITE_CLIENT_SECRET`, `ZOHO_DESK_WRITE_REFRESH_TOKEN`).

3. In `hub.settings.yaml`: `DESK_HELPDESK: zoho_desk`, `ZOHO_DESK_API_BASE` for your data centre (for example `https://desk.zoho.eu/api/v1`), `ZOHO_DESK_ACCOUNTS_BASE` (`https://accounts.zoho.eu`), `ZOHO_DESK_FROM_ADDRESS`, and optionally `ZOHO_DESK_DEPARTMENT_ID` and `ZOHO_DESK_CASE_FIELD`.
4. In `work-items.yaml`, keep `customer_reply.send: draft` for `zoho_desk`. Doctor refuses `approve` for the helpdesk.
5. Webhook: set `WEBHOOK_SECRET_ZOHO_DESK` in `.env`. Zoho Desk's built-in webhooks send an array signed with a JWT that Hubzoid does not verify, so create a workflow rule with a custom function on ticket create and on customer reply that POSTs `{"ticketId": ..., "event": ..., "firedAt": ...}` to `https://<your hub>/webhooks/<hub>/zoho-desk` with the secret in `X-Webhook-Secret`. The desk also polls modified tickets every minute, with a 15 minute overlap, so a missed webhook is caught.
6. Start in `dry-run`, read `./desk ledger`, move to `shadow`, then `live`.

## Testing without Zoho

`python workflows/lib/customer_desk/helpdesk/fake_zoho.py --port 8724` runs a fake Zoho Desk on this machine, with a page at http://127.0.0.1:8724 that shows each ticket's threads, unsent drafts, private notes, tags and fields. It is a test double, not Zoho. Evidence from it is labelled fake.
