"""`./desk`: the Customer Desk command line, for builders, operators and admins.

Every command takes the hub folder with `--hub` (default: this folder) and
`--json`. Exit codes follow Hubzoid: 0 done, 1 failed, 2 invalid input,
3 denied, 4 conflict, 5 unavailable, 6 waiting for a person.

Commands act as the machine's local owner (`admin@localhost`) when sign-in is
off, or as `--as EMAIL` with that person's grants. Decisions (exceptions,
plans, delivery declines) ask the person at the terminal to retype a code, so
no script or agent settles them on its own.
"""
from __future__ import annotations

import argparse
import json
import os
import secrets
import sys
import time
from pathlib import Path

from . import actions, bindings, cases, config, envelopes, pipeline, policy as policy_lib, store, views
from .erpnext import config as erp_config
from .erpnext.contract import ERPContext, ERPError

EXIT = {"permission_denied": 3, "claim_conflict": 4, "revision_conflict": 4, "state_conflict": 4, "reply_stale": 4,
        "erp_mismatch": 4, "erp_unavailable": 5, "unavailable": 5, "not_found": 2, "validation_failed": 2,
        "binding_conflict": 2, "binding_invalid": 2, "human_action_required": 6}


def out(args, data, text: str | None = None, code: int = 0):
    if args.json:
        print(json.dumps(data, indent=2, default=str))
    else:
        print(text if text is not None else json.dumps(data, indent=2, default=str))
    return code


def fail(args, code: str, message: str, **extra):
    data = {"error": code, "message": message, **extra}
    if args.json:
        print(json.dumps(data, indent=2, default=str))
    else:
        print(f"{code}: {message}", file=sys.stderr)
    return EXIT.get(code, 1)


def local_actor(hub_dir: Path, email: str | None) -> actions.Actor:
    who = (email or os.environ.get("HUBZOID_LOCAL_OWNER") or "admin@localhost").lower()
    try:
        from hubzoid.access import store_for

        st = store_for(hub_dir)
        key = hub_dir.name.lower()
        return actions.Actor(who, lambda role: st.can(who, key, role))
    except Exception:  # noqa: BLE001 - without the access store only the local owner acts
        return actions.Actor(who, lambda role: who == "admin@localhost")


def confirm(args, what: str) -> bool:
    """A person at this terminal retypes a code. Never satisfied by a pipe."""
    if not sys.stdin.isatty():
        print("This is a decision. Run it in your own terminal, where it asks you to retype a code.", file=sys.stderr)
        return False
    code = secrets.token_hex(2).upper()
    print(f"{what}\nType {code} to confirm: ", end="", flush=True)
    return sys.stdin.readline().strip().upper() == code


def starter(hub_dir: Path):
    from .flows import start_work

    return start_work(hub_dir)


def _erp(hub_dir):
    cfg = erp_config.load(hub_dir)
    return cfg, erp_config.backend(hub_dir, cfg)


# -- sample ---------------------------------------------------------------------------------

DATASET = "distributor-v1"
#: The four requests the sample routes through the fake Zoho Desk with --via-helpdesk.
DEMO_HELPDESK = {"CD-011", "CD-016", "CD-018", "CD-020"}


def dataset_file(hub_dir: Path, *parts: str) -> Path:
    """A file of the vendored distributor-v1 dataset (workflows/lib/erp, VENDORED)."""
    return erp_config.dataset_dir(hub_dir, DATASET).joinpath(*parts)


def cmd_sample_load(args, hub_dir):
    values = config.settings(hub_dir)
    if config.namespace(values) != "sample":
        return fail(args, "desk_setting_invalid", "The sample loads only in DESK_MODE: sample.")
    if not values["DESK_INTAKE_ENABLED"]:
        return fail(args, "desk_setting_invalid", "DESK_INTAKE_ENABLED is false.")
    actor = local_actor(hub_dir, args.as_)
    plan = import_bindings(hub_dir, dataset_file(hub_dir, "bindings.csv").read_text(), dry_run=False,
                           synthetic=True, actor=actor)
    source = (hub_dir / args.file) if args.file else dataset_file(
        hub_dir, "messages", "customer-desk-adversarial.jsonl" if args.adversarial else "customer-desk.jsonl")
    lines = [json.loads(x) for x in source.read_text().splitlines() if x.strip()]
    if args.only:
        lines = [x for x in lines if x["provider_event_id"] in args.only.split(",")]
    began = time.time()
    start = starter(hub_dir)
    via = args.via_helpdesk and values["DESK_HELPDESK"] == "zoho_desk"
    fake = fake_zoho_base(values) if via else None
    rows = []
    for env in lines:
        if via and (env.get("demo_route") == "helpdesk" or env["provider_event_id"] in DEMO_HELPDESK):
            opened = helpdesk_ticket(hub_dir, fake, env)
            rows.append({"event": env["provider_event_id"], "case": opened["number"], "via": "zoho_desk"})
            continue
        opened = cases.intake(hub_dir, envelopes.from_envelope(env))
        if opened["action"] == "duplicate":
            rows.append({"event": env["provider_event_id"], "case": opened["number"], "via": "duplicate"})
            continue
        item = start("customer_desk_intake", key=f"sample:{env['provider_event_id']}:{opened['case_id']}",
                     route="triage", input={"kind": "case", "case_id": opened["case_id"], "seq": opened["seq"]},
                     requester="")
        rows.append({"event": env["provider_event_id"], "case": opened["number"], "via": env["channel_id"],
                     "work_item": item["id"]})
    settled = None
    if args.wait:
        settled = wait_settled(hub_dir, timeout=args.wait)
    took = round(time.time() - began)
    text = "\n".join(f"{r['case']}  {r['event']}  {r['via']}" for r in rows)
    if args.wait:
        text += (f"\nAll {len(rows)} cases ready in {took // 60}m {took % 60:02d}s." if settled else
                 f"\nStill working after {took // 60}m {took % 60:02d}s. Run desk list to follow.")
    return out(args, {"bindings": {k: len(v) for k, v in plan.items()}, "loaded": rows, "seconds": took,
                      "settled": settled},
               f"SYNTHETIC DATA. Bindings added {len(plan['adds'])}, conflicts {len(plan['conflicts'])}.\n{text}")


def fake_zoho_base(values) -> str:
    base = values["ZOHO_DESK_API_BASE"]
    if not ("127.0.0.1" in base or "localhost" in base):
        raise SystemExit("The sample routes tickets only through a local fake Zoho Desk.")
    return base.removesuffix("/api/v1")


def helpdesk_ticket(hub_dir: Path, fake: str, env: dict) -> dict:
    import httpx

    first, _, last = (env["sender"].get("display_name") or "").partition(" ")
    subject, text = envelopes.split_subject(env["text"], env.get("subject"))
    t = httpx.post(f"{fake}/_fake/tickets", json={"subject": subject or "Customer request", "text": text,
                                                  "email": env["sender"]["external_id"], "first": first,
                                                  "last": last}, timeout=10).json()
    deadline = time.time() + 120
    while time.time() < deadline:
        row = store.connect(hub_dir).execute("SELECT case_id FROM helpdesk_tickets WHERE ticket_id=?",
                                             (str(t["id"]),)).fetchone()
        if row and row["case_id"]:
            c = store.get_case(store.connect(hub_dir), row["case_id"])
            return {"case_id": c["id"], "number": c["number"], "ticket": t["id"]}
        time.sleep(0.5)
    raise SystemExit(f"Zoho ticket {t['id']} did not reach the desk within 120 seconds. Is the webhook set?")


def wait_settled(hub_dir: Path, timeout: int) -> bool:
    """True once no case is still being read, False at the timeout."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        n = store.connect(hub_dir).execute("SELECT COUNT(*) AS n FROM cases WHERE state IN ('received','triaging')"
                                           ).fetchone()["n"]
        if n == 0:
            return True
        time.sleep(2)
    return False


def cmd_sample_erp_set(args, hub_dir):
    """Stand in for a person editing ERPNext during a sample demo."""
    values = config.settings(hub_dir)
    cfg = erp_config.load(hub_dir)
    if config.namespace(values) != "sample" or cfg.backend != "sample":
        return fail(args, "desk_setting_invalid", "erp-set changes only the sample ERP, in sample mode.")
    value = json.loads(args.value) if args.value[:1] in "[{\"" or args.value in ("true", "false", "null") else args.value
    data = erp_config.sample_edit(hub_dir, args.resource, args.record, args.field, value)
    return out(args, data, f"SAMPLE ERP: {args.resource} {args.record}.{args.field} is now {args.value} "
                           "(as if a person changed it in ERPNext).")


def cmd_sample_reset(args, hub_dir):
    values = config.settings(hub_dir)
    if config.namespace(values) != "sample":
        return fail(args, "desk_setting_invalid", "Reset works only in sample mode. It never touches live cases.")
    if erp_config.load(hub_dir).backend == "sample":
        erp_config.sample_reset(hub_dir)
    with store.tx(hub_dir) as conn:
        counts = store.reset_namespace(conn, "sample")
    for f in store.db_path(hub_dir).parent.glob("fault-*.used"):
        f.unlink()
    return out(args, counts, "Sample namespace reset: " + ", ".join(f"{k} {v}" for k, v in counts.items()))


def cmd_erp_configure(args, hub_dir):
    """Apply connectors/erpnext.yaml as the next ERP configuration revision.
    The file is validated by the ERP module and must be read only. Until it is
    applied, the last applied revision stays in force (doctor reports drift)."""
    applied = erp_config.apply_file(hub_dir, actor=local_actor(hub_dir, args.as_).email)
    return out(args, {"revision": applied.revision, "digest": applied.digest},
               f"ERP configuration revision {applied.revision} applied ({applied.config.backend}, read only).")


# -- bindings -------------------------------------------------------------------------------

def import_bindings(hub_dir: Path, text: str, *, dry_run: bool, synthetic: bool, actor: actions.Actor) -> dict:
    values = config.settings(hub_dir)
    cfg, erp = _erp(hub_dir)
    ctx = ERPContext(hub_id=hub_dir.name.lower(), company=cfg.company)

    def lookup(cid):
        try:
            return erp.get_record("customers", cid, ctx)
        except ERPError:
            return None

    plan = bindings.plan_import(store.connect(hub_dir), text, company=values["DESK_COMPANY"], customer_lookup=lookup)
    if not dry_run:
        actions.require(actor, "desk_bindings")
        with store.tx(hub_dir) as conn:
            for a in plan["adds"]:
                bindings.add(conn, company=a["company"], channel_kind=a["channel_kind"], sender=a["sender"],
                             customer_id=a["customer_id"], actor=actor.email, source_ref=a["source_ref"],
                             synthetic=synthetic)
    return plan


def cmd_bindings(args, hub_dir):
    actor = local_actor(hub_dir, args.as_)
    conn = store.connect(hub_dir)
    company = config.settings(hub_dir)["DESK_COMPANY"]
    if args.verb == "list":
        rows = bindings.list_bindings(conn, company=company, include_revoked=args.all)
        return out(args, rows, "\n".join(f"{b['id'][:8]}  {b['state']:8} {b['channel_kind']:9} {b['sender_key']:40} "
                                         f"{b['customer_id']}" for b in rows) or "No bindings.")
    if args.verb == "import":
        plan = import_bindings(hub_dir, Path(args.file).read_text(), dry_run=args.dry_run, synthetic=args.synthetic,
                               actor=actor)
        verb = "Would add" if args.dry_run else "Added"
        text = [f"{verb} {len(plan['adds'])}, unchanged {len(plan['unchanged'])}, conflicts {len(plan['conflicts'])}, "
                f"rejected {len(plan['rejects'])}."]
        text += [f"  line {c['line']}: {c['code']} {c['reason']}" for c in plan["conflicts"]]
        text += [f"  line {r['line']}: rejected, {r['reason']}" for r in plan["rejects"]]
        return out(args, plan, "\n".join(text))
    if args.verb == "export":
        return out(args, {"csv": bindings.export_csv(conn, company)}, bindings.export_csv(conn, company))
    if args.verb == "add":
        return out(args, actions.bind_sender(hub_dir, actor, channel_kind=args.kind, sender=args.sender,
                                             customer_id=args.customer))
    if args.verb == "revoke":
        return out(args, actions.revoke_binding(hub_dir, actor, args.id))
    return 2


# -- cases ------------------------------------------------------------------------------------

def cmd_list(args, hub_dir):
    q = views.queue(hub_dir, tab=args.tab, viewer=local_actor(hub_dir, args.as_).email, limit=args.limit)
    lines = [f"{r['case']}  {r['customer']:13} {r['channel']:16} {r['state']:18} {r['queue']:10} {r['categories']}"
             for r in q["rows"]]
    return out(args, q, f"{q['total']} cases ({q['namespace']}, {q['tab']})\n" + "\n".join(lines))


def cmd_show(args, hub_dir):
    view = views.case(hub_dir, args.case)
    if view is None:
        return fail(args, "not_found", f"No case {args.case}.")
    cv = views.compact(view)
    if args.json:
        return out(args, cv)
    lines = [f"{cv['case']}  {cv['state']}  queue {cv['queue']}  customer {cv['customer']}  channel {cv['channel']}",
             cv["state_text"]]
    for r in cv["requests"]:
        lines.append(f"  request {r['no']}: {r['category']} -> {r['outcome']} (rules {', '.join(r['rules'])})")
    lines.append("Facts:")
    lines += [f"  {f['id']:4} {f['value'][:70]:70}  {f['source']}  {f['observed_at']}" for f in cv["facts"]]
    if cv["reply"]:
        lines += [f"Reply {cv['reply']['revision']} ({cv['reply']['author']}, {cv['reply']['state']}), digest "
                  f"{cv['reply']['digest']}", cv["reply"]["text"], "Checks: " + ", ".join(cv["reply"]["checks"])]
    if cv["reviewer"]:
        lines.append(f"Reviewer: {cv['reviewer'].get('verdict')}")
    for t in cv["tickets"]:
        lines.append(f"Ticket {t['number']} {t['severity']} {t['owner']} {t['state']}: {t['summary']}")
    for p in cv["delivery_proposals"]:
        lines.append(f"Delivery proposal {p['id']} {p['order']} -> {p['requested']} {p['state']}")
    for d in cv["decisions"]:
        lines.append(f"Decision {d['id']} {d['kind']} {d['state']}")
    for s in cv["sends"]:
        lines.append(f"Send reply {s['reply']} {s['mode']} {s['status']}")
    return out(args, cv, "\n".join(lines))


def cmd_act(args, hub_dir):
    actor = local_actor(hub_dir, args.as_)
    start = starter(hub_dir)
    v = args.verb
    if v == "claim":
        r = actions.claim(hub_dir, args.case, actor, expected_revision=args.expected_revision)
    elif v == "release":
        r = actions.release(hub_dir, args.case, actor)
    elif v == "edit-reply":
        r = actions.edit_reply(hub_dir, args.case, actor, Path(args.file).read_text(),
                               keep_attachments=not args.no_attachments)
    elif v == "rerun":
        r = actions.rerun(hub_dir, args.case, actor, instruction=args.instruction, start=start)
        if args.wait:
            wait_settled(hub_dir, args.wait)
    elif v == "send-request":
        r = actions.request_send(hub_dir, args.case, actor, reply_revision=args.reply, digest=args.digest,
                                 expected_revision=args.expected_revision, start=start)
        return out(args, r, f"human_action_required: {r['message']} Work item {r['work_item_id']}.", 6)
    elif v == "mailbox-draft":
        r = actions.save_draft(hub_dir, args.case, actor, reply_revision=args.reply, digest=args.digest, start=start)
    elif v in ("resolve", "reopen", "cancel"):
        to = {"resolve": "resolved", "reopen": "needs_owner", "cancel": "cancelled"}[v]
        if v == "cancel" and not confirm(args, f"Cancel {args.case}?"):
            return fail(args, "permission_denied", "Not confirmed.")
        r = actions.set_state(hub_dir, args.case, actor, to=to, reason=args.reason or "")
    elif v == "bind":
        r = actions.bind_case(hub_dir, args.case, actor, args.customer, start=start)
    elif v == "plan-share":
        r = actions.share_plan(hub_dir, args.case, actor, Path(args.file).read_text())
    elif v == "plan-review":
        case = store.get_case(store.connect(hub_dir), args.case)
        plan = case and store.connect(hub_dir).execute(
            "SELECT * FROM plans WHERE case_id=? AND state='pending' ORDER BY version DESC LIMIT 1",
            (case["id"],)).fetchone()
        if not plan:
            return fail(args, "not_found", f"{args.case} has no plan waiting for review.")
        print(f"Plan version {plan['version']} by {plan['author']}:\n{plan['body']}\n")
        if not confirm(args, f"{'Approve' if args.approve else 'Request changes to'} plan version {plan['version']} "
                             f"for {args.case}?"):
            return fail(args, "permission_denied", "Not confirmed.")
        r = actions.review_plan(hub_dir, args.case, actor, plan_version=plan["version"], plan_digest=plan["digest"],
                                approve=args.approve, note=args.note or "")
    else:
        return 2
    return out(args, r)


def cmd_owner(args, hub_dir):
    actor = local_actor(hub_dir, args.as_)
    start = starter(hub_dir)
    if args.area == "delivery":
        if args.verb == "verify":
            return out(args, actions.verify_delivery(hub_dir, args.id, actor, start=start))
        if not confirm(args, f"Decline delivery proposal {args.id}?"):
            return fail(args, "permission_denied", "Not confirmed.")
        return out(args, actions.decline_delivery(hub_dir, args.id, actor, note=args.note or "", start=start))
    if args.area == "exception":
        if not confirm(args, f"{'Approve' if args.approve else 'Decline'} exception {args.id}?"):
            return fail(args, "permission_denied", "Not confirmed.")
        return out(args, actions.decide_exception(hub_dir, args.id, actor, approve=args.approve, note=args.note or "",
                                                  start=start))
    if args.area == "tickets":
        if args.verb == "list":
            rows = store.rows(store.connect(hub_dir).execute("SELECT * FROM tickets ORDER BY number"))
            return out(args, rows, "\n".join(f"{t['number']} {t['severity']:8} {t['owner_role']:10} {t['state']:11} "
                                             f"{t['summary']}" for t in rows) or "No tickets.")
        return out(args, actions.update_ticket(hub_dir, args.id, actor, state=args.state, assignee=args.assignee,
                                               note=args.note))
    return 2


# -- policy, preview, measures ---------------------------------------------------------------------

def cmd_policy(args, hub_dir):
    rel = args.file or config.settings(hub_dir)["DESK_POLICY_FILE"]
    try:
        pol = policy_lib.load(hub_dir, rel)
    except policy_lib.PolicyError as exc:
        return fail(args, "desk_policy_invalid", str(exc), problems=exc.problems)
    gaps = policy_lib.gaps(pol)
    if args.verb == "show":
        return out(args, pol.to_json(), "\n".join(f"[{k}] {v}" for k, v in pol.rules.items()))
    text = f"Valid. {len(pol.rules)} rules, digest {pol.digest}." + "".join(f"\n  gap: {g['message']}" for g in gaps)
    return out(args, {"valid": True, "digest": pol.digest, "rules": len(pol.rules), "policy_gaps": gaps}, text)


def cmd_metrics(args, hub_dir):
    m = views.metrics(hub_dir)
    return out(args, m, "\n".join(f"{k}: {v}" for k, v in m.items()))


def cmd_outbox(args, hub_dir):
    from . import replies

    rows = replies.outbox_rows(hub_dir)
    return out(args, rows, "\n".join(f"{r['id']}  {r['case_id'][:8]} reply {r['reply_revision']}  {r['channel_id']}  "
                                     f"{'draft' if r['idem_key'].endswith(':draft') else 'sent'}  to "
                                     f"{', '.join(r['recipients'])}  {r['accepted_at']}" for r in rows)
               or "The sample outbox is empty.")


def cmd_ledger(args, hub_dir):
    from .helpdesk import desk

    rows = desk.ledger(hub_dir)
    return out(args, rows, "\n".join(f"{r['mode']:8} {r['kind']:6} ticket {r['ticket_id']:6} {r['status']:9} "
                                     f"{r['idem_key']}" for r in rows) or "No helpdesk writes recorded.")


def cmd_stop(args, hub_dir):
    flag = store.db_path(hub_dir).parent / "STOP_WRITES"
    if args.state == "on":
        flag.write_text(f"stopped {time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}\n")
    elif flag.exists():
        flag.unlink()
    return out(args, {"stop_writes": flag.exists()}, f"Helpdesk writes {'stopped' if flag.exists() else 'allowed'}.")


def cmd_preview(args, hub_dir):
    actor = local_actor(hub_dir, args.as_)
    text = Path(args.text_file).read_text()
    started = actions.preview(hub_dir, actor, customer_id=args.customer, text=text, start=starter(hub_dir))
    wait_settled(hub_dir, args.wait)
    r = actions.preview_result(hub_dir, started["case_id"])
    lines = [r["note"], ""] + [f"request {q['no']}: {q['category']} -> {q['outcome']}" for q in r["requests"]]
    if r["reply"]:
        lines += ["", r["reply"]["text"], "", "Checks: " + ", ".join(r["reply"]["checks"])]
    lines += [""] + [f"policy gap: {g['message']}" for g in r["policy_gaps"]]
    return out(args, r, "\n".join(lines))


def cmd_transcript(args, hub_dir):
    actor = local_actor(hub_dir, args.as_)
    text = Path(args.file).read_text()
    from .transcripts import import_transcript

    return out(args, import_transcript(hub_dir, actor, customer_id=args.customer, text=text, name=Path(args.file).name,
                                       start=starter(hub_dir)))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="desk", description="The Customer Desk command line.")
    ap.add_argument("--hub", default=os.environ.get("DESK_HUB", "."))
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--as", dest="as_", default=None, help="act as this person (local mode)")
    sub = ap.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("sample", help="load or reset the synthetic sample")
    s.add_argument("verb", choices=["load", "reset", "erp-set"])
    s.add_argument("resource", nargs="?")
    s.add_argument("record", nargs="?")
    s.add_argument("field", nargs="?")
    s.add_argument("value", nargs="?")
    s.add_argument("--file", default=None, help="an IntakeEnvelope v1 file (default: the dataset's twenty requests)")
    s.add_argument("--adversarial", action="store_true", help="load the dataset's six adversarial requests instead")
    s.add_argument("--only", default=None, help="comma separated provider event ids")
    s.add_argument("--via-helpdesk", action="store_true", help="send the helpdesk-routed requests through the fake Zoho Desk")
    s.add_argument("--wait", type=int, default=0, help="seconds to wait for triage to settle")

    sub.add_parser("erp-configure", help="apply connectors/erpnext.yaml (read only)")

    b = sub.add_parser("bindings", help="sender bindings")
    b.add_argument("verb", choices=["list", "import", "export", "add", "revoke"])
    b.add_argument("--file")
    b.add_argument("--dry-run", action="store_true")
    b.add_argument("--synthetic", action="store_true")
    b.add_argument("--all", action="store_true")
    b.add_argument("--kind", choices=bindings.KINDS)
    b.add_argument("--sender")
    b.add_argument("--customer")
    b.add_argument("--id")

    lst = sub.add_parser("list", help="the queue")
    lst.add_argument("--tab", default="all")
    lst.add_argument("--limit", type=int, default=100)
    sh = sub.add_parser("show", help="one case in full")
    sh.add_argument("case")

    for verb in ("claim", "release", "edit-reply", "rerun", "send-request", "mailbox-draft", "resolve", "reopen",
                 "cancel", "bind", "plan-share", "plan-review"):
        p = sub.add_parser(verb)
        p.add_argument("case")
        p.add_argument("--expected-revision", type=int, default=None)
        p.add_argument("--reply", type=int)
        p.add_argument("--digest")
        p.add_argument("--file")
        p.add_argument("--instruction")
        p.add_argument("--reason")
        p.add_argument("--customer")
        p.add_argument("--approve", action="store_true")
        p.add_argument("--note")
        p.add_argument("--wait", type=int, default=0)
        p.add_argument("--no-attachments", action="store_true")
        p.set_defaults(handler=cmd_act, verb=verb)

    for area, verbs in (("delivery", ["verify", "decline"]), ("exception", ["decide"]), ("tickets", ["list", "update"])):
        p = sub.add_parser(area)
        p.add_argument("verb", choices=verbs)
        p.add_argument("id", nargs="?")
        p.add_argument("--note")
        p.add_argument("--approve", action="store_true")
        p.add_argument("--state")
        p.add_argument("--assignee")
        p.set_defaults(handler=cmd_owner, area=area)

    pol = sub.add_parser("policy")
    pol.add_argument("verb", choices=["validate", "show"])
    pol.add_argument("--file")
    sub.add_parser("metrics")
    sub.add_parser("outbox", help="the sample outbox and sample mailbox drafts")
    sub.add_parser("ledger", help="helpdesk writes, including dry-run and shadow previews")
    st = sub.add_parser("stop-writes", help="the helpdesk stop switch, read at the moment of each write")
    st.add_argument("state", choices=["on", "off"])
    pv = sub.add_parser("preview", help="a reply to a pasted message, without a case or a send")
    pv.add_argument("--customer", required=True)
    pv.add_argument("--text-file", required=True)
    pv.add_argument("--wait", type=int, default=300)
    tr = sub.add_parser("transcript")
    tr.add_argument("verb", choices=["import"])
    tr.add_argument("--file", required=True)
    tr.add_argument("--customer", required=True)

    args = ap.parse_args(argv)
    hub_dir = Path(args.hub).resolve()
    if not (hub_dir / "AGENTS.md").is_file():
        print(f"{hub_dir} is not a hub folder.", file=sys.stderr)
        return 2
    handlers = {"sample": lambda a, h: {"load": cmd_sample_load, "reset": cmd_sample_reset,
                                        "erp-set": cmd_sample_erp_set}[a.verb](a, h),
                "bindings": cmd_bindings, "list": cmd_list, "show": cmd_show, "policy": cmd_policy,
                "metrics": cmd_metrics, "outbox": cmd_outbox, "ledger": cmd_ledger, "stop-writes": cmd_stop,
                "transcript": cmd_transcript, "preview": cmd_preview, "erp-configure": cmd_erp_configure}
    handler = getattr(args, "handler", None) or handlers[args.cmd]
    try:
        return handler(args, hub_dir) or 0
    except actions.ActionError as exc:
        return fail(args, exc.code, exc.message, **exc.fields)
    except store.Conflict as exc:
        return fail(args, exc.code, exc.message)
    except (bindings.BindingError, cases.IntakeError) as exc:
        return fail(args, exc.code, exc.message)
    except ERPError as exc:
        return fail(args, exc.code, exc.message)
