# Call script: the Customer Desk in ten minutes

DRAFT for review. For a founder or a delivery partner showing the desk on a call. Everything on screen is labelled synthetic data for Synthetic Meridian Distribution. Nothing reaches a customer.

## Before the call (five minutes, off camera)

1. `demo/reset --files`, then start the hub: `.venv/bin/hubzoid run . --port 8721`.
2. `.venv/bin/python desk sample load --wait 900` and wait for "All 20 cases ready".
3. Open the web app at http://127.0.0.1:8721 in one tab and the Work items page in another.

## On the call

**1. The problem (30 seconds).** "Your support team answers the same questions all day: where is my order, send me that invoice, what do I owe, do you have this in stock. Every answer means looking it up in ERPNext. The desk does the looking up, and a person stays in charge of every reply."

**2. Twenty requests (1 minute).** In chat: "What is waiting on the desk?" Point at the queue: twenty requests by email and WhatsApp, each with its kind, its state and the first line of a ready reply.

**3. One case, end to end (2 minutes).** "Show CD-000007." Walk through:

- the customer's message
- the facts the desk read from ERPNext, each with its record and field, for example the invoice and its total
- the reply, which is built from those facts, never typed by the model
- the ten checks and the reviewer's verdict
- the invoice PDF attached

Say: "The model never types a number. Every value comes from ERPNext and you can click through to where."

**4. What a person decides (2 minutes).**

- "Show the decisions queue." One refund is outside policy and waits for the exception team. "The desk does not promise money back. It asks the person who can decide."
- "Show the complaints queue." A damaged delivery is a ticket with an owner.
- Optional: `desk sample load --adversarial` adds a request from Alpine Hardware for Harbor Foods' invoice. The desk answers "not found", the same as a missing invoice, so it never leaks that the invoice exists. An unknown sender waits for a person to bind it, and nothing is read until then.

**5. Make it yours: one correction (2 minutes).** In chat: "Never give exact stock numbers. Say in stock, limited or out of stock."

- The desk proposes a change to the policy file as a hub change card. Approve it as the manager.
- "Rerun CD-000013." The reply now says the bolts are in stock, with no count.
- Say: "That rule is in your policy file, in Git, not in someone's head. Restart the hub and it still holds."

**6. Sending, if they ask (1 minute).** "Today every reply is a draft. When you are ready, one setting lets a person approve the exact reply and the desk sends it. Only the person who asked can approve it, and only after rechecking ERPNext."

If they want to see it: switch the sample email channel to approve mode (`work-items.yaml`, show the diff first), claim CD-000007, ask to send, and approve it yourself on the Work items page. It lands in the sample outbox, never in a real mailbox.

**7. Next step (30 seconds).** "Try it on your own ERPNext, read only, with your own policy. Or we run it for you."

## After the call

`demo/reset --files` restores the policy and write modes, so the next call starts the same way.
