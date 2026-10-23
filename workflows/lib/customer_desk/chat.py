"""The bodies of the desk's chat tools. The tool files in `tools_local/` and
`restricted/` are thin wrappers around these.

Results are JSON in the shape of Hubzoid's built-in cards (table, report,
progress, approval), so native chat shows a card and every other host shows
the same content as text.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from . import actions, config, facts as facts_lib, policy as policy_lib, store, views
from .erpnext import config as erp_config
from .erpnext.contract import ERPContext, ERPError

VIEW_ROLES = ("desk_operator", "desk_delivery", "desk_complaints", "desk_exceptions", "desk_bindings",
              actions.ADMIN)


def _money_safe(value):
    """Escape dollar signs in Markdown, so the chat never reads two amounts in
    one paragraph ("$1,250.00 ... $1,250.00") as a math formula."""
    if isinstance(value, dict):
        return {k: (_escape(v) if k == "markdown" and isinstance(v, str) else _money_safe(v)) for k, v in value.items()}
    if isinstance(value, list):
        return [_money_safe(v) for v in value]
    return value


def _escape(text: str) -> str:
    return re.sub(r"(?<!\\)\$", r"\\$", text)


def _json(obj) -> str:
    # A report card shows its sections as plain text, so a \$ would show as is.
    if isinstance(obj, dict) and obj.get("kind") == "report":
        return json.dumps(obj, default=str)
    return json.dumps(_money_safe(obj), default=str)


def _plain(md: str) -> str:
    """Reply Markdown as the report card shows it: no emphasis marks, and a
    table as one "- " line per row ("Invoice: SINV-1, Due: 15 Jan 2000")."""
    out, header = [], None
    for line in (md or "").splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")] if line.strip().startswith("|") else None
        if cells is None:
            header = None
            out.append(re.sub(r"(\*\*|__)(.+?)\1", r"\2", line))
        elif all(re.fullmatch(r":?-{2,}:?", c) for c in cells if c):
            continue
        elif header is None:
            header = cells
            out.append("")
        else:
            out.append("- " + ", ".join(f"{h}: {v}" if h else v for h, v in zip(header, cells)))
    return re.sub(r"\n{3,}", "\n\n", "\n".join(out)).strip()


def actor(hub_dir: Path) -> actions.Actor:
    from hubzoid import current_user

    user = current_user(hub_dir)
    if user is None:
        return actions.Actor("", lambda role: False)
    return actions.Actor(user.email, user.can)


def guard(fn):
    """Turn desk errors into a readable refusal instead of a stack trace."""
    import functools

    @functools.wraps(fn)
    def wrapper(*a, **kw):
        try:
            return fn(*a, **kw)
        except actions.ActionError as exc:
            return _json(exc.to_json())
        except store.Conflict as exc:
            return _json({"error": exc.code, "message": exc.message, **exc.fields})
        except ERPError as exc:
            return _json({"error": exc.code, "message": exc.message})
        except policy_lib.PolicyError as exc:
            return _json({"error": exc.code, "message": str(exc)})
    return wrapper


def can_view(a: actions.Actor) -> None:
    if not a.any(*VIEW_ROLES):
        raise actions.ActionError("permission_denied", "You need a desk role to see customer cases. Ask the agent's "
                                  "manager to grant one in Settings, Access.", 403)


# -- views -----------------------------------------------------------------------------------

def queue(hub_dir: Path, tab: str, cursor: str | None, customer: str | None) -> str:
    a = actor(hub_dir)
    can_view(a)
    offset = int(cursor) if cursor and str(cursor).isdigit() else 0
    q = views.queue(hub_dir, tab=tab or "open", viewer=a.email, offset=offset, customer=customer or None)
    if not q["rows"] and offset == 0:
        return _json({"kind": "report", "title": "Customer Desk queue", "sections": [{
            "heading": "No customer requests yet",
            "markdown": "Nothing is waiting in this tab. In sample mode, load the sample requests with "
                        "`./desk sample load`. Admins can connect a channel."}], "sources": []})
    waiting = ", ".join(f"{k} {v}" for k, v in sorted(q["counts"].items()) if v)
    return _json({"kind": "table", "title": f"Customer Desk: {q['tab']} ({q['total']})"
                  + (f". Open by queue: {waiting}" if waiting else ""),
                  "columns": [{"key": "case", "label": "Case", "type": "string"},
                              {"key": "customer", "label": "Customer", "type": "string"},
                              {"key": "channel", "label": "Channel", "type": "string"},
                              {"key": "categories", "label": "Requests", "type": "string"},
                              {"key": "state_text", "label": "State", "type": "string"},
                              {"key": "queue", "label": "Queue", "type": "string"},
                              {"key": "assignee", "label": "Claimed by", "type": "string"},
                              {"key": "first_line", "label": "Reply starts", "type": "string"}],
                  "rows": [{k: v for k, v in r.items() if k not in ("review_hold", "state")} for r in q["rows"]],
                  "page": {"next_cursor": str(q["next_offset"]) if q["next_offset"] else None,
                                              "total_rows": q["total"]},
                  "sources": [{"label": f"{q['namespace']} cases in the desk store"}]})


def show(hub_dir: Path, case_ref: str) -> str:
    a = actor(hub_dir)
    can_view(a)
    view = views.case(hub_dir, case_ref)
    if view is None:
        raise actions.ActionError("not_found", f"No case {case_ref}.", 404)
    c = view["case"]
    cv = views.compact(view)
    sections = [{"heading": f"{c['number']}: {c['state']}", "markdown": view["state_text"] + (
        f"\n\nDesk notes: {c['note']}" if c.get("note") else "") + (
        f"\n\nCase page (desk roles only): {c['page_url']}" if c.get("page_url") else "")}]
    page = [{"label": f"{c['number']} case page (desk roles only)", "url": c["page_url"]}] if c.get("page_url") else []
    if c["state"] == "binding_required":
        # No model reads an unbound message, the assistant included: only who
        # wrote and when. People read the text on the case page or in Intake.
        lines = "\n".join(f"- {m['from']} {m['at']}: {len(m['text'] or '')} characters" for m in cv["messages"])
        sections.append({"heading": "Conversation", "markdown": (lines or "No messages.") +
                         "\n\nThe message text stays hidden from the assistant until the sender is bound. Read it "
                         "on the case page" + (f" ({c['page_url']})" if c.get("page_url") else "") + "."})
        sections.append({"heading": "Sender not recognised", "markdown":
                         f"We could not match this sender to a customer. Sender: {c['sender_key']}. No customer "
                         "data was read. A binding admin can bind it to one customer, or reject the message."})
        return _json({"kind": "report", "title": f"Case {c['number']}", "sections": sections, "sources": []})
    msgs = "\n".join(f"- {m['from']} {m['at']}: {m['text'][:600]}" for m in cv["messages"])
    sections.append({"heading": "Conversation", "markdown": msgs or "No messages."})
    if cv["requests"]:
        sections.append({"heading": "Requests and outcomes", "markdown": "\n".join(
            f"- {r['no']}. {r['category']}: {r['outcome']} (rules {', '.join(r['rules'])})"
            + (f" {' '.join(r['notes'])}" if r["notes"] else "") for r in cv["requests"])})
    if cv["facts"]:
        sections.append({"heading": "Source evidence", "markdown": "\n".join(
            f"- {f['id']} {' '.join(f['value'][:160].split())} ({f['source']}, read {f['observed_at']})"
            for f in cv["facts"])})
    r = cv["reply"]
    if r:
        sections.append({"heading": f"Proposed reply, revision {r['revision']} ({r['author']}, {r['state']})",
                         "markdown": _plain(r["text"] or "") + (f"\n\nAttachments: {', '.join(r['attachments'])}"
                                                          if r["attachments"] else "")
                         + (f"\n\nTyped by a person, not checked against ERPNext: {', '.join(r['typed_by_person'])}"
                            if r["typed_by_person"] else "")})
        sections.append({"heading": "Checks", "markdown": "\n".join(f"- {x}" for x in r["checks"]) +
                         f"\n\nDigest: {r['digest']}"})
    for pl in cv["plans"][-2:]:
        sections.append({"heading": f"Escalation plan, version {pl['version']} ({pl['state']})", "markdown":
                         pl["body"] + f"\n\nBy {pl['author']}. Digest: {pl['digest']}"
                         + (f"\n\nReviewed by {pl['reviewer']}: {pl['note']}" if pl["reviewer"] else "")})
    rv = cv.get("reviewer")
    if rv:
        sections.append({"heading": f"Reviewer: {rv.get('verdict')}", "markdown": "\n".join(
            f"- {x.get('rule_ref')}: {x.get('problem')}" for x in rv.get("findings") or []) or "No findings."})
    items = [f"- Ticket {t['number']}: {t['severity']}, {t['owner']}, {t['state']}. {t['summary']}" for t in cv["tickets"]]
    items += [f"- Delivery proposal {p['id']}: {p['order']} to {p['requested']}, {p['state']}" for p in
              cv["delivery_proposals"]]
    latest = cv.get("latest_customer_message")
    items += [f"- Decision {d['id']}: {d['kind'].replace('_', ' ')}, {d['state']}"
              + (f", amount asked {d['inputs']['amount_text']}" if (d.get("inputs") or {}).get("amount_text") else "")
              + (f" by {d['decided_by']}" if d["decided_by"] else "")
              + (f". To decide, pass customer_message {latest}" if d["state"] == "pending" and latest else "")
              for d in cv["decisions"]]
    if items:
        sections.append({"heading": "Owner items", "markdown": "\n".join(items)})
    if cv["sends"]:
        sections.append({"heading": "Drafts and sends", "markdown": "\n".join(
            f"- reply {s['reply']}: {s['mode']} {s['status']}" + (f" ({(s['receipt'] or {}).get('note')})"
                                                                 if isinstance(s.get("receipt"), dict) and
                                                                 s["receipt"].get("note") else "")
            for s in cv["sends"])})
    sections.append({"heading": "What you can do", "markdown": next_steps(hub_dir, view)})
    return _json({"kind": "report", "title": f"Case {c['number']}", "sections": sections,
                  "sources": page + [{"label": "Desk store and ERPNext reads"}]})


def next_steps(hub_dir: Path, view: dict) -> str:
    from . import replies

    c = view["case"]
    out = []
    if c["state"] == "needs_owner":
        out.append(f"Claim it: `desk_claim {c['number']}`.")
    if c["state"] in ("in_review", "needs_owner") and view.get("reply"):
        mode = actions._mode(hub_dir, c["channel_id"]) if c["origin_kind"] == "external" else "internal"
        if c["origin_kind"] == "internal":
            out.append("Internal case: copy the reply and deliver it yourself.")
        elif c["channel_id"] == "freshdesk":
            out.append("Open the ticket in Freshdesk and use the Customer Desk app to show and, if wanted, replace the editor text. No saved draft or send is claimed; review and send personally there.")
        elif replies.channel_kind(c["channel_id"]) == "helpdesk":
            out.append("Check the ticket in the helpdesk. A saved unsent draft is confirmed only when the case reports helpdesk_draft_saved.")
        elif mode == "approve":
            out.append("Ask to send: you approve the exact reply on the Work items page.")
        elif mode == "draft":
            out.append("Save it as a draft in the mailbox, then finish it there.")
        else:
            out.append("Replies are off for this channel.")
        out.append("Edit the reply, or rerun with an instruction.")
    if c["state"] == "held":
        out.append("Wait for the customer to write again, or send an approved WhatsApp template.")
    if c["state"] == "ambiguous":
        out.append("Reconcile on the Work items page. Never resend blindly.")
    return " ".join(out) or "Nothing to do right now."


def lookup(hub_dir: Path, customer_id: str, kind: str, ref: str | None) -> str:
    """Internal chat lookups for a named customer. Read only, scoped to that customer."""
    a = actor(hub_dir)
    can_view(a)
    cfg = erp_config.load(hub_dir)
    erp = erp_config.backend(hub_dir, cfg)
    ctx = ERPContext(hub_id=Path(hub_dir).name.lower(), company=cfg.company, party_scope=customer_id,
                     principal=a.email, warehouses=cfg.warehouses)
    resource = {"order": "sales_orders", "orders": "sales_orders", "invoice": "sales_invoices",
                "invoices": "sales_invoices"}.get(kind)
    if resource is None:
        raise actions.ActionError("validation_failed", "kind is order, orders, invoice or invoices.", 422)
    if ref:
        recs = [erp.get_record(resource, ref, ctx)]
    else:
        recs = erp.list_records(resource, {"docstatus": 1, "limit": 20}, ctx)
    rows = []
    for r in recs:
        f = r["fields"]
        rows.append({"id": r["id"], "date": f.get("transaction_date") or f.get("posting_date"),
                     "status": facts_lib.display("order_status", f.get("status")) if resource == "sales_orders"
                     else f.get("status"), "total": facts_lib.display("grand_total", f.get("grand_total"),
                                                                      currency=f.get("currency")),
                     "source": f"{r['source']['doctype']} {r['id']} ({r['backend']}, read {r['observed_at']})"})
    return _json({"kind": "table", "title": f"{customer_id} {resource.replace('_', ' ')}",
                  "columns": [{"key": "id", "label": "Id", "type": "string"},
                              {"key": "date", "label": "Date", "type": "string"},
                              {"key": "status", "label": "Status", "type": "string"},
                              {"key": "total", "label": "Total", "type": "string"},
                              {"key": "source", "label": "Source", "type": "string"}],
                  "rows": rows, "page": {"next_cursor": None, "total_rows": len(rows)}, "sources": []})


def metrics(hub_dir: Path) -> str:
    a = actor(hub_dir)
    can_view(a)
    m = views.metrics(hub_dir)
    lines = [f"- {k.replace('_', ' ')}: {v}" for k, v in m.items() if k not in ("label", "by_state")]
    lines.append("- cases by state: " + ", ".join(f"{k} {v}" for k, v in sorted(m["by_state"].items())))
    return _json({"kind": "report", "title": "Customer Desk measures", "sections": [
        {"heading": m["label"], "markdown": "\n".join(lines)}], "sources": []})


def health(hub_dir: Path) -> str:
    """Queue health, channels and write modes, for admins."""
    a = actor(hub_dir)
    can_view(a)
    from hubzoid.work_items import config as wi_config

    from . import replies
    from .helpdesk import desk

    values = config.settings(hub_dir)
    wcfg = wi_config.load(hub_dir)
    lines = [f"- mode: {values['DESK_MODE']} (cases in the {config.namespace(values)} namespace)",
             f"- intake: {'on' if values['DESK_INTAKE_ENABLED'] else 'paused'}"]
    for ch in list(values["DESK_EXTERNAL_CHANNELS"]) + (["zoho_desk"] if values["DESK_HELPDESK"] == "zoho_desk" else []):
        mode = wi_config.mode_for(wcfg, ["customer_reply.send"], ch)
        lines.append(f"- channel {ch} ({replies.channel_kind(ch)}): replies {mode}")
    m = views.metrics(hub_dir)
    q = {t: views.queue(hub_dir, tab=t)["total"] for t in ("operators", "delivery", "complaints", "decisions",
                                                            "bindings", "held")}
    lines.append("- waiting: " + ", ".join(f"{k} {v}" for k, v in q.items()))
    lines.append(f"- uncertain sends: {m['uncertain']}, held: {m['held']}")
    if values["DESK_HELPDESK"] == "zoho_desk":
        h = desk.health(hub_dir)
        lines.append(f"- helpdesk {values['DESK_HELPDESK_MODE']}: {h['tickets_seen']} tickets seen, writes {h['writes']}, "
                     f"stop switch {h['stop_switch'] or 'off'}")
    return _json({"kind": "report", "title": "Customer Desk health", "sections": [
        {"heading": "Channels, modes and queues", "markdown": "\n".join(lines)}], "sources": []})


def progress(item: dict, summary: str) -> str:
    return _json({"kind": "progress", "work_item_id": item["work_item_id"], "summary": summary, **item})


def pending_approval(hub_dir: Path, case_ref: str) -> str:
    a = actor(hub_dir)
    can_view(a)
    c = store.get_case(store.connect(hub_dir), case_ref)
    if c is None:
        raise actions.ActionError("not_found", f"No case {case_ref}.", 404)
    from hubzoid.work_items import store as wi_store

    send = next((s for s in store.case_sends(store.connect(hub_dir), c["id"]) if s["status"] == "waiting_approval"), None)
    if send is None or not send.get("work_item_id"):
        raise actions.ActionError("not_found", f"{c['number']} has no reply waiting for approval.", 404)
    ops = [o for o in wi_store.list_ops(hub_dir, Path(hub_dir).name.lower(), item_id=send["work_item_id"])
           if o["state"] == "awaiting_approval"]
    if not ops:
        return progress({"work_item_id": send["work_item_id"], "case": c["number"]},
                        "The send is being prepared. It will wait for your approval on the Work items page.")
    op = ops[0]
    return _json({"kind": "approval", "operation_id": op["id"], "digest": op["args_digest"],
                  "summary": f"Reply {send['reply_revision']} for {c['number']} waits for {send['requested_by']} to "
                             "approve the exact content on the Work items page."})


def policy_summary(hub_dir: Path) -> str:
    a = actor(hub_dir)
    can_view(a)
    values = config.settings(hub_dir)
    pol = policy_lib.load(hub_dir, values["DESK_POLICY_FILE"])
    rules = "\n".join(f"- [{k}] {v}" for k, v in pol.rules.items())
    gaps = "\n".join(f"- {g['message']} Default: {g['default']}" for g in policy_lib.gaps(pol)) or "None."
    import yaml

    # The settings block is what the code enforces, so a correction is checked against it, not the rule text.
    settings = yaml.safe_dump(pol.data, sort_keys=False, default_flow_style=None, width=100).strip()
    return _json({"kind": "report", "title": "Desk policy", "sections": [
        {"heading": "Settings in force (enforced in code)", "markdown": f"```yaml\n{settings}\n```"},
        {"heading": f"{pol.path} {pol.digest[:19]}", "markdown": rules},
        {"heading": "Settings left to defaults", "markdown": gaps}], "sources": [{"label": pol.path}]})
