# ERPNext permissions

DRAFT for review.

The desk only reads ERPNext. Create a dedicated integration user with an API key and give it exactly this:

| DocType | Read | Print | Write, create, submit, delete |
|---|---|---|---|
| Customer | yes | no | no |
| Item | yes | no | no |
| Item Price | yes | no | no |
| Bin | yes | no | no |
| Sales Order | yes | no | no |
| Sales Invoice | yes | yes, with `DESK_INVOICE_PRINT_FORMAT` | no |

Restrict the user to your company and the warehouses the desk may report. Then:

```yaml
# connectors/erpnext.yaml
version: 1
backend: frappe_rest
site_url: https://erp.your-company.example
credential_ref: secret:hub/customer-desk/erpnext-reader
company: Your Company Ltd
currency: USD
warehouses: [Main Warehouse - YC]
selling_price_list: Standard Selling
writes_enabled: false
timeout_seconds: 20
read_attempts: 3
page_size: 50
```

The API key is entered by a person, never in a file or a chat:

```bash
hubzoid secrets set . --name erpnext-reader --stdin
```

Then set `DESK_MODE: live` and `DESK_CLOCK: system` in `hub.settings.yaml` and run `hubzoid hub doctor .`. Doctor fails with `erp_not_read_only` if `writes_enabled` is true, `erp_company_mismatch` if the company differs from `DESK_COMPANY`, and names each DocType it cannot read.

The desk reads with the case's bound customer as its scope. A record of any other customer reads as not found, whether it exists or not.
