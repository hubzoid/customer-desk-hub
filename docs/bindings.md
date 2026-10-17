# Sender bindings

DRAFT for review.

A binding says which ERP customer an email address or phone number speaks for. A case is read only when its sender matches exactly one active binding. Until then it waits as `binding_required`: nothing about any customer is read and no model sees the message. A name, company or account number written in a message proves nothing.

Bindings are personal data, so they live in the desk's store, never in Git.

## The CSV

```
company,channel_kind,sender,customer_id,source_ref
Synthetic Meridian Distribution,email,purchasing@harbor-foods.example,SYN-CUST-001,erp-contact:SYN-CONT-0001
Synthetic Meridian Distribution,whatsapp,+12025550102,SYN-CUST-002,erp-contact:SYN-CONT-0002
```

The desk also reads the shared format of the ERP module's datasets, `company,channel_kind,sender,party_type,party_id,source_ref`, as the sample does. Rows whose `party_type` is not `Customer` (supplier contacts, which belong to the Order & Invoice Desk) are listed as rejected and never imported.

`channel_kind` is `email`, `whatsapp` or `helpdesk`. Email domains are lowercased and IDNA encoded, local parts kept as written. Phone numbers are E.164. A helpdesk contact also matches the email bindings for the same address.

## Commands

```bash
./desk bindings import --file contacts.csv --dry-run
```

```bash
./desk bindings import --file contacts.csv
```

```bash
./desk bindings list
```

```bash
./desk bindings export
```

```bash
./desk bindings revoke --id 1a2b3c4d
```

A dry run shows what would be added, what is unchanged, and every conflict: a row for another company, a customer ERPNext does not have, a disabled customer, or one sender listed for two customers. At most 10,000 rows per import.

Revoking a binding sends the sender's open cases back to `binding_required` and makes their unsent replies stale.

## A real mailbox

Hubzoid's email channel quarantines any sender not on its allowed list before the desk sees them. Put the bound addresses on that list (`./desk bindings export`), and release a quarantined message in Console, Agents, the agent, Intake once its sender is bound.
