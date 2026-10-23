# Errors

DRAFT for review. Every refusal has a stable code, a safe message and the next step. No message body or credential appears in an error.

| Code | What it means | What to do |
|---|---|---|
| `desk_setting_invalid` | A setting has a value it cannot take, or live mode lacks what it needs. | Fix `hub.settings.yaml`, then `hubzoid hub configure . --check`. |
| `desk_policy_invalid` | The policy has a problem at the file, line and key shown. | Fix it and run `./desk policy validate`. The last valid policy stays active. |
| `desk_policy_gap` | The policy leaves a setting to its default. | Add it, or confirm the default in a reviewed change. |
| `desk_vocabulary_invalid` | The request kinds or reply style file is wrong. | Fix the file named. |
| `erp_not_read_only` | `connectors/erpnext.yaml` allows writes, or names a submit credential. | Set `writes_enabled: false` and `submit_credential_ref: null`, then `./desk erp-configure`. The desk never needs ERP writes. |
| `sample_only` | `desk sample erp-set` or `desk sample reset` ran while the connector is not the sample backend. | These commands change only the sample ERP. Switch back with `backend: sample` and `./desk erp-configure`. |
| `erp_company_mismatch` | `DESK_COMPANY` differs from the connector company. | Make them equal. |
| `erp_print_unavailable` | The integration user cannot print the invoice with the configured format. | Ask the ERP administrator for print permission on that format. |
| `erp_unavailable`, `erp_rate_limited` | ERPNext did not answer. Nothing was sent. | Rerun the case later. |
| `erp_auth_failed`, `erp_permission_denied` | ERPNext refused the integration user. | Check the API key and the read permissions. |
| `not_found` | No such case, ticket or record for this customer. | Check the number. |
| `binding_required` | The sender is not bound to exactly one customer. | A binding admin binds the sender. |
| `binding_conflict` | A binding names a disabled customer, another company, or one ERPNext does not have. | Correct the row shown. |
| `binding_invalid` | The sender is not a valid address or E.164 number. | Correct it. |
| `permission_denied` | You do not hold the desk role this needs. | Ask the agent's manager. |
| `claim_required`, `claim_conflict` | The case is not yours, or someone else holds it (shown with since when). | Claim it, or ask them. |
| `revision_conflict`, `state_conflict` | The case changed since you loaded it, or someone applied another ERP configuration at the same time. | Reload, or run `./desk erp-configure` again. |
| `reply_stale` | Facts, policy, style, the sender's binding or the thread changed after the draft. Nothing was sent. | Review the new revision. |
| `claim_lost`, `role_lost` | By the time you approved, you no longer held the case or the desk operator role. Nothing was sent. | Claim the case again and ask to send. |
| `recipient_changed` | The helpdesk ticket's contact is no longer the case's bound sender. No draft was written. | Check the ticket in the helpdesk. |
| `request_failed` | A send or draft request did not reach Hubzoid. Nothing was sent. | Ask again. |
| `checks_failed` | The reply fails a check. | Edit it or rerun. |
| `review_hold` | The reviewer asked for changes, so the reply cannot leave the desk: no helpdesk draft, editor suggestion, mailbox draft or send. | Edit the reply. Your edit is a new revision with its own checks. |
| `plan_required` | An escalated case needs a reviewed plan before a send. | Share a plan for the complaints team. |
| `plan_stale` | The plan waiting for review is not the version you read. | Read the current plan on the case and review that one. |
| `write_mode_off`, `write_mode_draft` | The channel's reply mode does not allow this. | Change `customer_reply.send` in `work-items.yaml`. |
| `mode_unsupported` | WhatsApp has no drafts, an internal case has no recipient, or a helpdesk reply is sent in the helpdesk. | Use the path the message names. |
| `human_action_required` | A send waits for you to approve the exact reply. | Open the Work items page. |
| `ambiguous` | The reply may have been sent. | Check, then say done, retry or abandon on the Work items page. Never resend blindly. |
| `model_auth_required` | A station cannot reach the installed Claude Code or Codex login. | Sign in again, then rerun. Setup is otherwise complete. |
| `channel_not_desk` | A listed channel does not route to `customer_desk_intake`. | Fix and apply the channel file. |
| `loopback_only` | A fake test setup tried to reach a real Zoho data centre. | Point the Zoho settings at the fake server, or unset `DESK_LOOPBACK_ONLY`. |
