"""Customer Desk setup checks, run by `hubzoid hub doctor` and `hubzoid doctor`.

Each check returns {status: ok|warn|fail, summary, recovery}. They read files
and the desk store only. None of them writes anything or calls a model.
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
from pathlib import Path


def _lib(context) -> Path:
    hub = Path(context["hub_dir"])
    lib = hub / "workflows" / "lib"
    if str(lib) not in sys.path:
        sys.path.insert(0, str(lib))
    return hub


def _ok(summary):
    return {"status": "ok", "summary": summary}


def _fail(summary, recovery):
    return {"status": "fail", "summary": summary, "recovery": recovery}


def _warn(summary, recovery=None):
    out = {"status": "warn", "summary": summary}
    if recovery:
        out["recovery"] = recovery
    return out


def erp_read_only(context):
    hub = _lib(context)
    import yaml

    from customer_desk.erpnext import config as erp_config

    path = hub / "connectors" / "erpnext.yaml"
    if not path.is_file():
        return _fail("connectors/erpnext.yaml is missing.", "Copy the sample connector file from the README.")
    problems = erp_config.problems(yaml.safe_load(path.read_text()) or {})
    if any(p["code"] == "erp_not_read_only" for p in problems):
        return _fail("erp_not_read_only: connectors/erpnext.yaml allows ERP writes. The Customer Desk only reads "
                     "ERPNext and mounts no ERP write tool.", "Set writes_enabled: false and remove "
                     "submit_credential_ref.")
    if problems:
        p = problems[0]
        return _fail(f"config_invalid: {p['field']}: {p['message']}", "Fix connectors/erpnext.yaml.")
    return _ok("ERPNext connection is read only.")


def erp_company(context):
    hub = _lib(context)
    from customer_desk.erpnext import config as erp_config

    cfg = erp_config.load(hub)
    company = context["settings"].get("DESK_COMPANY")
    if company != cfg.company:
        return _fail(f"erp_company_mismatch: DESK_COMPANY is {company!r}, the connector says {cfg.company!r}.",
                     "Make DESK_COMPANY in hub.settings.yaml equal company in connectors/erpnext.yaml.")
    return _ok(f"Company {company}.")


def erp_reads(context):
    hub = _lib(context)
    from customer_desk.erpnext import config as erp_config
    from customer_desk.erpnext.contract import ERPContext, ERPError

    try:
        cfg = erp_config.load(hub)
        backend = erp_config.backend(hub, cfg)
        rows = backend.doctor(ERPContext(hub_id=hub.name.lower(), company=cfg.company))
    except ERPError as exc:
        return _fail(f"{exc.code}: {exc.message}", "Check the connector, the credential reference and that ERPNext "
                     "is reachable.")
    bad = [r for r in rows if r["status"] == "fail"]
    label = {"sample": "Sample mode. ERPNext backend sample, read only. Replies go to the sample outbox only.",
             "fake_rest": "Fake REST ERPNext (synthetic data, loopback only), read only.",
             "frappe_rest": "Live ERPNext, read only."}[cfg.backend]
    if bad:
        return _fail(f"{label} {len(bad)} read checks failed: " + "; ".join(r["summary"] for r in bad[:3]),
                     "Give the integration user read access to Customer, Item, Item Price, Bin, Sales Order and "
                     "Sales Invoice, and print access to Sales Invoice.")
    return _ok(label)


def sample_data(context):
    hub = _lib(context)
    from customer_desk.erpnext import config as erp_config

    cfg = erp_config.load(hub)
    if cfg.backend == "frappe_rest":
        return _ok("Live ERPNext. No sample dataset in use.")
    folder = erp_config.dataset_dir(hub, cfg.dataset)
    manifest = folder / "manifest.json"
    if not manifest.is_file():
        return _fail(f"The {cfg.dataset} dataset is missing at {folder}.", "Restore fixtures/erp from the hub repo.")
    data = json.loads(manifest.read_text())
    changed = [name for name, digest in data.get("files", {}).items()
               if not (folder / name).is_file()
               or "sha256:" + hashlib.sha256((folder / name).read_bytes()).hexdigest() != digest]
    if changed:
        return _fail(f"sample_modified: {', '.join(changed)} differ from the dataset manifest.",
                     "Restore the files from the hub repo. Sample data is never edited in place.")
    return _ok(f"SYNTHETIC DATA: {cfg.dataset} ({data.get('variant', 'canonical')}), clock {data.get('clock')}.")


def policy(context):
    hub = _lib(context)
    from customer_desk import policy as policy_lib

    rel = context["settings"].get("DESK_POLICY_FILE") or "knowledge/desk-policy.md"
    try:
        pol = policy_lib.load(hub, rel)
    except policy_lib.PolicyError as exc:
        first = exc.problems[0]
        return _fail(f"desk_policy_invalid: {first['file']}:{first.get('line') or '?'} {first['key']}: {first['reason']}"
                     + (f" (and {len(exc.problems) - 1} more)" if len(exc.problems) > 1 else ""),
                     "Fix the policy file and run ./desk policy validate. The last valid policy stays active.")
    gaps = policy_lib.gaps(pol)
    if gaps:
        return _warn(f"{len(pol.rules)} rules. desk_policy_gap: {len(gaps)} settings left to defaults, for example: "
                     f"{gaps[0]['message']}", "Add them to the policy, or confirm the defaults in a reviewed change.")
    return _ok(f"{len(pol.rules)} rules, digest {pol.digest[:19]}.")


def vocabulary(context):
    hub = _lib(context)
    from customer_desk import vocab

    try:
        k = vocab.load_kinds(hub, context["settings"].get("DESK_KINDS_FILE") or "knowledge/request-kinds.md")
        vocab.load_style(hub, context["settings"].get("DESK_STYLE_FILE") or "knowledge/customer-messages.md")
    except vocab.VocabularyError as exc:
        return _fail(f"desk_vocabulary_invalid: {exc}", "Fix the file named.")
    except FileNotFoundError as exc:
        return _fail(f"Missing file: {exc}", "Restore it from the hub repo.")
    return _ok(f"{len(k.kinds)} request kinds, tags {k.tag_prefix}*.")


def write_modes(context):
    hub = _lib(context)
    from hubzoid.work_items import config as wi_config

    try:
        cfg = wi_config.load(hub)
    except Exception as exc:  # noqa: BLE001
        return _fail(f"work-items.yaml is invalid: {exc}", "Run hubzoid work-items validate .")
    channels = list(context["settings"].get("DESK_EXTERNAL_CHANNELS") or [])
    if context["settings"].get("DESK_HELPDESK") == "zoho_desk":
        channels.append("zoho_desk")
    problems, shown = [], []
    for ch in channels:
        mode = wi_config.mode_for(cfg, ["customer_reply.send"], ch)
        shown.append(f"{ch} {mode}")
        if "whatsapp" in ch and mode == "draft":
            problems.append(f"{ch} is in draft mode, but WhatsApp has no drafts")
        if ch == "zoho_desk" and mode == "approve":
            problems.append("zoho_desk is in approve mode, but the desk never sends from the helpdesk")
    if problems:
        return _fail("; ".join(problems) + ".", "In work-items.yaml set WhatsApp channels to off or approve, and the "
                     "helpdesk to off or draft, under write_mode_overrides.")
    return _ok("Replies: " + ", ".join(shown) + ". Nothing is sent without the requester's approval.")


def channels(context):
    hub = _lib(context)
    want = [c for c in context["settings"].get("DESK_EXTERNAL_CHANNELS") or [] if not c.startswith("sample-")]
    if not want:
        return _ok("Sample channels only.")
    try:
        from hubzoid.channels import config as ch_config

        missing = []
        for cid in want:
            conn = ch_config.active(hub, cid)
            if conn is None or getattr(conn.config, "workflow", None) != "customer_desk_intake":
                missing.append(cid)
    except Exception as exc:  # noqa: BLE001
        return _warn(f"Could not read channel configuration: {type(exc).__name__}.")
    if missing:
        return _fail(f"channel_not_desk: {', '.join(missing)} is not an active channel routed to "
                     "customer_desk_intake.", "Apply channels/<id>.yaml with workflow: customer_desk_intake "
                     "(hubzoid channels apply).")
    return _ok(f"{len(want)} channels route to the desk.")


def helpdesk(context):
    _lib(context)
    s = context["settings"]
    if s.get("DESK_HELPDESK") != "zoho_desk":
        return _ok("No helpdesk connected.")
    avail = context.get("available") or {}
    need = ["ZOHO_DESK_CLIENT_ID", "ZOHO_DESK_CLIENT_SECRET", "ZOHO_DESK_REFRESH_TOKEN"]
    if s.get("DESK_HELPDESK_MODE") in ("shadow", "live"):
        need += ["ZOHO_DESK_WRITE_CLIENT_ID", "ZOHO_DESK_WRITE_CLIENT_SECRET", "ZOHO_DESK_WRITE_REFRESH_TOKEN"]
    missing = [n for n in need if not avail.get(n)]
    if missing:
        return _fail(f"Zoho Desk credentials missing: {', '.join(missing)}.",
                     "A person with the values runs: hubzoid secrets set . --name <NAME> --stdin")
    base = s.get("ZOHO_DESK_API_BASE") or ""
    fake = "127.0.0.1" in base or "localhost" in base
    drafts = bool(s.get("DESK_HELPDESK_DRAFTS"))
    return (_warn if fake else _ok)(f"Zoho Desk {'(FAKE test server) ' if fake else ''}in {s.get('DESK_HELPDESK_MODE')} "
                                    f"mode, drafts {'on' if drafts else 'off'}. The desk never sends, closes or "
                                    "assigns tickets.")


def roles(context):
    hub = _lib(context)
    try:
        from hubzoid.access import store_for

        st = store_for(hub)
        from sqlalchemy import text

        with st._engine.connect() as conn:
            rows = conn.execute(text("SELECT permission, COUNT(*) FROM hz_grants WHERE permission LIKE 'desk_%' "
                                     "GROUP BY permission")).fetchall()
        held = {r[0]: r[1] for r in rows}
    except Exception as exc:  # noqa: BLE001
        return _warn(f"Could not read grants: {type(exc).__name__}.")
    from customer_desk.config import ROLES

    empty = [r for r in ROLES if not held.get(r)]
    if empty:
        return _warn(f"Nobody holds {', '.join(empty)} yet.", "Grant the roles in Settings, Agents, this agent, "
                     "Access, or with: hubzoid grant EMAIL desk_operator --hub HUB .")
    return _ok("Every desk role has at least one person: " + ", ".join(f"{k} {v}" for k, v in sorted(held.items())))


def test_switches(context):
    s = context["settings"]
    on = [n for n in ("DESK_SCRIPTED_STATIONS", "DESK_SAMPLE_FAULT", "DESK_STOP_WRITES") if os.environ.get(n)]
    live = s.get("DESK_MODE") == "live"
    if not on:
        return _ok("No test switches set.")
    if live and any(n != "DESK_STOP_WRITES" for n in on):
        return _fail(f"Test switches are set in live mode: {', '.join(on)}.", "Remove them from the environment.")
    return _warn(f"Test switches set: {', '.join(on)}. Results are labelled scripted or fault injection.")


def live_mode(context):
    hub = _lib(context)
    s = context["settings"]
    if s.get("DESK_MODE") != "live":
        return _ok("Sample mode. Cases stay in the sample namespace.")
    from customer_desk.erpnext import config as erp_config

    cfg = erp_config.load(hub)
    problems = []
    if cfg.backend != "frappe_rest":
        problems.append("live mode needs backend: frappe_rest")
    if s.get("DESK_CLOCK") != "system":
        problems.append("live mode needs DESK_CLOCK: system")
    if problems:
        return _fail("desk_setting_invalid: " + "; ".join(problems) + ".", "Fix hub.settings.yaml and "
                     "connectors/erpnext.yaml, then rerun hubzoid hub configure . --check.")
    return _ok("Live mode against ERPNext, read only.")
