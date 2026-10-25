# Freshdesk

With Freshdesk connected, the desk reads each ticket, adds tags and a private note with the facts and their sources, and shows the checked reply in a Customer Desk app inside the ticket. An agent inserts it into the reply editor with one explicit confirmation and sends it from Freshdesk. The desk never sends, closes or assigns a ticket.

## Set it up

1. **Configure the hub.** Preview, then repeat with `--apply` after reading the diff:

   ```sh
   python scripts/setup_support.py --provider freshdesk --company 'Your Company' \
     --department 123 --api-base https://company.freshdesk.com/api/v2
   ```

2. **Store the API key.** Create a dedicated, restricted Freshdesk integration agent. A person enters its key, never in chat or a file:

   ```sh
   python -m hubzoid secrets set . --name FRESHDESK_API_KEY --stdin
   ```

3. **Give the hub a public HTTPS address.** The app signs in to Hubzoid from the agent's browser, so the hub needs `HUBZOID_PUBLIC_URL` set to an HTTPS address Freshdesk can reach, with Hubzoid's MCP sign-in turned on.

4. **Grant the operator and link their Freshdesk agent.** Use the operator's real Hubzoid account and their Freshdesk agent id:

   ```sh
   python -m hubzoid grant operator@company.example desk_operator .
   python -m hubzoid grant operator@company.example desk_editor .
   ./desk editor-link --agent-id 456 --principal operator@company.example
   ```

5. **Install the app.** A Freshdesk administrator packages `freshdesk-app/` with Freshworks' app tooling (`fdk pack`) and installs it as a ticket sidebar app. In its settings, enter the hub's HTTPS hostname (no scheme or path) and the MCP path, `/mcp` or `/b/<hub>/mcp`.

6. **Try one ticket in dry-run.** Start the hub with `HUBZOID_SCHEDULES=1 python -m hubzoid run .`, then run `./desk ticket TICKET_ID` and read `./desk ledger`: it lists what the desk would write.

7. **Go live when you are ready.** Set `DESK_HELPDESK_MODE: live` and `DESK_HELPDESK_DRAFTS: true` in `hub.settings.yaml` and restart. Keep `customer_reply.send: draft`. `./desk stop-writes on` blocks every Freshdesk write at once.

## Using it on a ticket

1. Open the ticket and the Customer Desk app, sign in and choose **Show current suggestion**. Opening the app never changes the editor.
2. Choose **Replace editor with this suggestion**. The app warns that the editor's current text, including a draft a person wrote, will be replaced. Cancel keeps it.
3. The desk rechecks the ticket, your link, your access and the reply at the click, then places the reply.
4. For an invoice copy, choose **Download PDF, then attach in Freshdesk** and attach it yourself before sending.
5. Read, edit and send in Freshdesk.

## How it works, and its limits

- **Reading.** The REST adapter reads tickets and conversations and ranks a small set of resolved tickets as precedent. It writes only namespaced tags and private notes. It has no send endpoint.
- **Sign-in.** The app uses a public OAuth client with PKCE. Access and refresh tokens stay in memory. Only the public client id is kept in browser storage. Expired requests share one refresh. A 401 or 403 is shown as a sign-in or access message.
- **Placement.** The app uses Freshworks' documented `click` with `id: reply`, which replaces the editor text, and sends escaped HTML (paragraphs, lists and tables). Freshworks gives no way to read back whether the editor content was saved, so the desk reports `awaiting_provider_confirmation` and never claims the draft was saved.
- **One placement at a time.** Placement is claimed at the click. Another operator gets nothing to insert while a claim exists. A crash or an unknown outcome is never replayed. After looking at the ticket, an administrator runs `./desk editor-reconcile TICKET_ID not_inserted` or `placed`.
- **Tags.** Freshdesk replaces the whole tag list on update. The desk keeps tags it saw in two reads, but a person's edit between its last read and its write can be lost.
- **Intake.** Polling is the default. An optional webhook posts to `/webhooks/HUB_SLUG/freshdesk` with `X-Webhook-Secret` set to `WEBHOOK_SECRET_FRESHDESK` and a JSON body such as `{"ticket_id":42,"event":"ticket_updated","fired_at":"2026-10-20T12:00:00Z"}`. The desk ignores any ticket text in the body and rereads the API.

## Check on your own tenant

Popup and iframe behaviour, consent cookies, the callback origin, token refresh after expiry, request-template limits, replacing an existing draft, the signed-in agent matching the linked agent, rate limits and webhooks depend on your Freshdesk tenant and its settings. Check them on a trial or sandbox tenant before your team relies on the app.

Sources checked 20 October 2026: [REST](https://developers.freshdesk.com/api/), [interface methods](https://developers.freshworks.com/docs/app-sdk/v3.0/support_ticket/front-end-apps/interface-methods/), [data methods](https://developers.freshworks.com/docs/app-sdk/v3.0/support_ticket/front-end-apps/data-method/), [request methods](https://developers.freshworks.com/docs/app-sdk/v3.0/support_email/advanced-interfaces/request-method/).
