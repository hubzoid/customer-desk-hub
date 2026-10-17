# The one prompt

DRAFT for review. Paste this into Claude Code or Codex, opened in this folder. It works the same in both.

> Set up the Customer Desk from this folder on the synthetic distributor. Install Hubzoid, run the hub doctor, load the twenty sample customer requests, and show me what the desk proposes for each and why. Stop before anything is sent.

The agent follows `.claude/skills/setup-customer-desk/SKILL.md`. It never enters a secret, never turns on ERP writes and never approves anything for you.

## The same steps by hand

```bash
python -m venv .venv && .venv/bin/pip install "hubzoid @ git+https://github.com/hubzoid/hubzoid@main" -r requirements.txt
```

```bash
.venv/bin/hubzoid hub doctor .
```

```bash
echo "HUBZOID_SCHEDULES=1" >> .env && .venv/bin/hubzoid run . --port 8721
```

In a second terminal:

```bash
.venv/bin/python desk sample load --wait 900
```

```bash
.venv/bin/python desk list
```

## What you should see

Twenty cases for Synthetic Meridian Distribution, all labelled synthetic:

| Requests | Kind | What the desk does |
|---|---|---|
| 6 | order status | answers from the order: three on track, one late order opens a delivery ticket, one draft order is not confirmed yet, one order was cancelled |
| 4 | invoice copy | attaches the ERPNext print, one found from the customer's own order number |
| 2 | statement | lists open invoices with a CSV |
| 3 | price and availability | the customer's contract price, an item out of stock in the main warehouse, a disabled item not quoted |
| 2 | delivery change | one proposal for the delivery team, one explained as already delivered |
| 3 | complaint | tickets, one refund above the policy amount waits for the exception team |

The exact expected outcome per request is `evals/expected/customer-desk-20.json`. For the six adversarial messages, run `.venv/bin/python desk sample load --adversarial --wait 900`.

## Time it

`desk sample load --wait` prints when the last case is ready. Note the time from the prompt to that line, and which agent ran it (Claude Code or Codex). The measured runs are in the hub's proof page.

## Start again

```bash
demo/reset
```

It refuses live mode, clears the sample cases, tickets, decisions and sample outbox, and undoes the sample ERP edits. `demo/reset --files` also restores the policy, reply style and write modes from Git, which undoes a Make it yours change or the call script's correction.
