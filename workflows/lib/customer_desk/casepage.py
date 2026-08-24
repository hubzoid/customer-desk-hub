"""One case as a static page for Hubzoid's artifact viewer: the conversation,
each request with its outcome, the facts with their ERPNext sources, the
proposed reply with every check, the reviewer's verdict and the owner items.

Everything is escaped. The page has no scripts and loads nothing.
"""
from __future__ import annotations

import hashlib
import html
import json

CSS = """
:root{--ink:#1d2330;--muted:#5d6675;--line:#e3e6ec;--bg:#f6f7f9;--card:#fff;--ok:#1f7a4d;--bad:#b3261e;--warn:#8a5a00;
--accent:#2f5bd3}
@media (prefers-color-scheme: dark){:root{--ink:#e7e9ee;--muted:#a3abb9;--line:#2c3240;--bg:#141821;--card:#1b2030;
--ok:#5ccf95;--bad:#ff8a80;--warn:#f0c060;--accent:#8fb0ff}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.5 system-ui,-apple-system,
Segoe UI,sans-serif}main{max-width:1100px;margin:0 auto;padding:20px 16px 40px}h1{font-size:22px;margin:0 0 4px}
h2{font-size:16px;margin:24px 0 8px}.sub{color:var(--muted);margin:0 0 12px}.badge{display:inline-block;padding:1px 9px;
border-radius:10px;border:1px solid var(--line);font-size:12px;margin-right:6px;background:var(--card)}
.syn{border-color:var(--warn);color:var(--warn)}.card{background:var(--card);border:1px solid var(--line);
border-radius:8px;padding:12px 14px;margin:8px 0}table{width:100%;border-collapse:collapse;background:var(--card);
border:1px solid var(--line);border-radius:8px;overflow:hidden;font-size:14px}th,td{text-align:left;padding:7px 9px;
border-bottom:1px solid var(--line);vertical-align:top}th{color:var(--muted);font-weight:600}pre{white-space:pre-wrap;
margin:0;font:14px/1.5 ui-monospace,SFMono-Regular,Menlo,monospace}.pass{color:var(--ok)}.fail{color:var(--bad)}
.warn{color:var(--warn)}.grid{display:grid;grid-template-columns:1fr;gap:12px}@media(min-width:900px){
.grid{grid-template-columns:1fr 1fr}}code{font-size:13px}
"""


def _e(v) -> str:
    return html.escape("" if v is None else str(v))


def digest(view: dict) -> str:
    c = view["case"]
    body = {"state": c["state"], "revision": c["revision"], "reply": (view.get("reply") or {}).get("digest"),
            "tickets": [(t["number"], t["state"]) for t in view["tickets"]],
            "proposals": [(p["id"], p["state"]) for p in view["proposals"]],
            "decisions": [(d["id"], d["state"]) for d in view["decisions"]]}
    return "sha256:" + hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()


def render(view: dict) -> str:
    from .views import STATE_TEXT

    c = view["case"]
    res = view.get("resolution") or {}
    reply = view.get("reply") or {}
    parts = [f"<!doctype html><html lang=en><meta charset=utf-8><meta name=viewport content='width=device-width,"
             f"initial-scale=1'><title>Case {_e(c['number'])}</title><style>{CSS}</style><main>"]
    syn = "<span class='badge syn'>SYNTHETIC DATA</span>" if c.get("synthetic") else ""
    parts.append(f"<h1>Case {_e(c['number'])}</h1><p class=sub>{syn}<span class=badge>{_e(c['state'])}</span>"
                 f"<span class=badge>queue {_e(c.get('queue') or '-')}</span><span class=badge>{_e(c['channel_id'] or c['surface'])}"
                 f"</span><span class=badge>customer {_e(c.get('customer_id') or 'not bound')}</span></p>"
                 f"<p>{_e(STATE_TEXT.get(c['state'], c['state']))}</p>")
    if c.get("note"):
        parts.append(f"<div class=card><b>Desk notes.</b> {_e(c['note'])}</div>")
    parts.append("<h2>Conversation</h2>")
    for ev in view["events"]:
        who = "Customer" if ev["author_kind"] == "customer" else "Teammate"
        parts.append(f"<div class=card><small>{who} &middot; {_e(ev['received_at'])}"
                     f"{' &middot; ' + _e(ev['subject']) if ev.get('subject') else ''}</small><pre>{_e(ev['text'])}</pre></div>")
    if c["state"] == "binding_required":
        parts.append("<div class=card>We could not match this sender to a customer, so no customer data was read. "
                     "A binding admin binds the sender first.</div></main></html>")
        return "".join(parts)
    if res:
        cls = res.get("classifier") or {}
        parts.append("<h2>Requests</h2><table><tr><th>#</th><th>Kind</th><th>Outcome</th><th>Rules</th><th>Notes</th></tr>")
        for o in res.get("requests") or []:
            parts.append(f"<tr><td>{o['request_no']}</td><td>{_e(o['category'])}</td><td><b>{_e(o['outcome'])}</b></td>"
                         f"<td>{_e(', '.join(o['rule_refs']))}</td><td>{_e(' '.join(o['notes']))}</td></tr>")
        parts.append("</table>")
        flags = ", ".join(cls.get("escalation_flags") or []) or "none"
        parts.append(f"<p class=sub>Classification: {_e(cls.get('agreement'))}"
                     f"{', low confidence' if cls.get('low_confidence') else ''}. Risk flags: {_e(flags)}."
                     f"{' The message held instructions to the desk, which were ignored.' if cls.get('injection_detected') else ''}"
                     "</p>")
    parts.append("<h2>Facts read</h2><table><tr><th>Id</th><th>Value</th><th>Source</th><th>Observed</th></tr>")
    for f in view["facts"]:
        s = f["source"]
        where = f"{s.get('doctype')} {s.get('name')}.{s.get('field')}" + (f" row {s['row_id']}" if s.get("row_id") else "")
        parts.append(f"<tr><td><code>{_e(f['fact_id'])}</code></td><td><pre>{_e(f['display'])}</pre></td>"
                     f"<td>{_e(s.get('backend'))}: {_e(where)}</td><td>{_e(f['observed_at'])}</td></tr>")
    parts.append("</table>")
    if reply:
        chk = reply.get("checks") or {}
        parts.append(f"<h2>Proposed reply, revision {reply['revision']}</h2><div class=grid><div class=card>"
                     f"<small>{_e(reply['author_kind'])} &middot; {_e(reply['state'])} &middot; to "
                     f"{_e(', '.join(reply.get('recipients') or []) or 'no external recipient')}"
                     f"{' &middot; ' + _e(reply['subject']) if reply.get('subject') else ''}</small>"
                     f"<pre>{_e(reply['rendered'])}</pre>")
        if reply.get("attachments"):
            parts.append("<p>" + "".join(f"<span class=badge>{_e(a['name'])} {_e(a['sha256'][:19])}</span>"
                                         for a in reply["attachments"]) + "</p>")
        if reply.get("typed_values"):
            parts.append(f"<p class=warn>Typed by a person, not checked against ERPNext: "
                         f"{_e(', '.join(reply['typed_values']))}</p>")
        parts.append(f"<p><small>Digest <code>{_e(reply['digest'])}</code></small></p></div><div class=card>"
                     "<b>Checks</b><ul>")
        for x in chk.get("results", []):
            parts.append(f"<li class={_e(x['status'])}>{_e(x['id'])}: {_e(x['status'])}. {_e(x['detail'])}</li>")
        parts.append("</ul>")
        for n in chk.get("style") or []:
            parts.append(f"<p class=warn>{_e(n)}</p>")
        rv = res.get("reviewer") or {}
        if rv:
            parts.append(f"<b>Reviewer</b>: {_e(rv.get('verdict'))}<ul>" + "".join(
                f"<li>{_e(x.get('rule_ref'))}: {_e(x.get('problem'))} {_e(x.get('suggestion'))}</li>"
                for x in rv.get("findings") or []) + "</ul>")
        parts.append("</div></div>")
    if view["tickets"] or view["proposals"] or view["decisions"]:
        parts.append("<h2>Owner items</h2>")
        for t in view["tickets"]:
            parts.append(f"<div class=card><b>Ticket {_e(t['number'])}</b> &middot; {_e(t['severity'])} &middot; "
                         f"{_e(t['owner_role'])} &middot; {_e(t['state'])}<br>{_e(t['summary'])}</div>")
        for p in view["proposals"]:
            parts.append(f"<div class=card><b>Delivery proposal</b> {_e(p['sales_order'])}: move to "
                         f"{_e(p['requested_date'])} &middot; {_e(p['state'])}{' &middot; ' + _e(p['note']) if p.get('note') else ''}</div>")
        for d in view["decisions"]:
            parts.append(f"<div class=card><b>Exception decision</b> {_e(d['kind'])} &middot; {_e(d['state'])}"
                         f"{' by ' + _e(d['decided_by']) if d.get('decided_by') else ''}<br><small>"
                         f"{_e(json.dumps(d['inputs']))}</small></div>")
    if view["sends"]:
        parts.append("<h2>Drafts and sends</h2><table><tr><th>Reply</th><th>Mode</th><th>Status</th><th>Receipt</th></tr>")
        for s in view["sends"]:
            parts.append(f"<tr><td>{s['reply_revision']}</td><td>{_e(s['mode'])}</td><td>{_e(s['status'])}</td>"
                         f"<td>{_e(json.dumps(s.get('receipt')))[:300]}</td></tr>")
        parts.append("</table>")
    parts.append("</main></html>")
    return "".join(parts)
