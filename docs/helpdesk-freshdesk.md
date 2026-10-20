# Freshdesk native editor

The REST adapter reads tickets/conversations, fetches documented resolved-status/group facets and ranks bounded candidates lexically. It adds namespaced tags and private evidence notes. It has no send endpoint. Notes are never drafts.

A Freshdesk administrator packages freshdesk-app/ with supported Freshworks custom-app tooling and installs the ticket-sidebar app. Configure the trusted Hubzoid HTTPS hostname and MCP path. Enable the SDK's existing OAuth MCP surface/canonical public URL. The app uses public-client PKCE sign-in and Freshworks request templates, with no static browser service credential or cached payload response. The person consents in the Hubzoid popup. Every request checks the verified account link, current grants and provider ticket scope.

Open the ticket, sign in and choose **Show current suggestion**. App opening never changes editor text. Choose **Replace editor with this suggestion** only when wanted. Its confirmation explicitly warns that existing text, including a human draft, will be lost. Cancel preserves it. Recheck ticket/message, link, grants, source revisions and digest at the click. Review/edit/send personally in Freshdesk. Placement is acknowledged as awaiting_provider_confirmation and never reinserted automatically.

The documented App SDK provides insertion but no editor/draft persistence readback. This build never calls placement draft_saved. Browser restart, concurrency and persistence need real-tenant acceptance. Persisted native-draft support remains unqualified without provider evidence.

For an invoice copy, the app shows an authenticated **Download PDF, then attach in Freshdesk** action. It reads only the checked current reply's stored PDF through the same ticket/link/grant/evidence checks and verifies its digest. It creates no new file store or provider upload. Download and attach personally in the native reply editor before sending. Body placement stays `requires_manual_attachment`, with attachment delivery and persistence unverified. Zoho retains its existing native attachment path.

Placement is claimed atomically at the confirmed button click. Another operator receives no insertion payload while a claim exists. The acknowledgement requires its opaque claim token and actor. A crash or unknown outcome never expires/replays automatically. After inspecting the actual provider editor, an administrator runs `./desk editor-reconcile TICKET_ID not_inserted` or `placed` in their own terminal and confirms. Neither decision claims provider persistence or attachment upload.

Revoked/unlinked callers receive no payload. The server rereads the Freshdesk agent and enforces ticket_scope/group/assignment alongside Hubzoid grants. Local machine ownership remains the SDK's trusted administration boundary.

Sources checked 20 October 2026: [REST](https://developers.freshdesk.com/api/), [interface methods](https://developers.freshworks.com/docs/app-sdk/v3.0/support_ticket/front-end-apps/interface-methods/), [data methods](https://developers.freshworks.com/docs/app-sdk/v3.0/support_ticket/front-end-apps/data-method/), [request methods](https://developers.freshworks.com/docs/app-sdk/v3.0/support_email/advanced-interfaces/request-method/). API documentation does not establish tenant qualification.
