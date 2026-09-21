"""The ten deterministic checks every reply revision runs (HUB-8 section 6.4),
plus non-blocking style notes.

A model-written revision runs all ten. A person's edit runs checks 1, 2, 3,
6, 7 and 9, and any value they typed that could be a fact is listed so the
approval card shows it as "typed by a person, not checked against ERPNext".
"""
from __future__ import annotations

import re
import unicodedata

from .render import NAMED, model_text, placeholders

CURRENCY_SYMBOLS = "$€£¥₹₩₽₺₫₪₱฿₴₦"
ISO_CURRENCIES = {"USD", "EUR", "GBP", "JPY", "INR", "AUD", "CAD", "CHF", "CNY", "SGD", "AED", "SAR", "NZD", "ZAR",
                  "SEK", "NOK", "DKK", "HKD", "MXN", "BRL"}
PERSON_CHECKS = ("binding_ok", "facts_owned", "placeholders_resolve", "never_say", "limits", "foreign_ids")
ALL = ("binding_ok", "facts_owned", "placeholders_resolve", "no_literal_facts", "policy_actions", "never_say",
       "limits", "language", "foreign_ids", "freshness")
MAX_ATTACHMENTS = 10
MAX_TOTAL_BYTES = 20 * 1024 * 1024
MAX_PDF_BYTES = 5 * 1024 * 1024


def _fold(text: str) -> str:
    return unicodedata.normalize("NFKC", text or "").casefold()


LIST_MARKER = re.compile(r"^\s*\d{1,2}[.)]\s", re.M)


def literal_values(text: str, id_patterns: list[str]) -> list[str]:
    """Anything in `text` that could be a fact: any number, even one digit
    ("7 units", "2 days"), a currency symbol or code, or a document id. Only a
    Markdown list marker at the start of a line is not a value."""
    text = LIST_MARKER.sub(" ", model_text(text or ""))
    found = re.findall(r"\d(?:[\d,.]*\d)?", text)
    found += [ch for ch in text if ch in CURRENCY_SYMBOLS]
    found += [w for w in re.findall(r"\b[A-Z]{3}\b", text) if w in ISO_CURRENCIES]
    for pat in id_patterns:
        found += [m.group(0) for m in re.finditer(pat, text)]
    out = []
    for f in found:
        if f not in out:
            out.append(f)
    return out


def _fact_strings(facts: dict) -> set[str]:
    vals = set()
    for f in facts.values():
        v = f["value"]
        for item in (v if isinstance(v, list) else [v]):
            vals.add(str(item).upper())
        vals.add(f["display"].upper())
        src = f.get("source") or {}
        for name in str(src.get("name") or "").split(","):
            vals.add(name.upper())
    return vals


def run(*, case: dict, source: str, rendered: str, facts: dict, policy, author_kind: str, outcomes: list[dict],
        resolver_outcomes: list[dict] | None, attachments: list[dict], language: str, current_digests: dict,
        used_digests: dict, decisions: list[dict] | None = None) -> dict:
    """{"checks": [...], "passed": bool, "typed_values": [...]}."""
    which = ALL if author_kind != "person" else PERSON_CHECKS
    pats = policy.data["facts"]["id_patterns"]
    results = []

    def add(cid, ok, detail, *, warn=False):
        results.append({"id": cid, "status": "pass" if ok else ("warn" if warn else "fail"), "detail": detail})

    if "binding_ok" in which:
        ok = bool(case.get("customer_id")) and (case.get("origin_kind") == "internal" or bool(case.get("binding_id")))
        add("binding_ok", ok, "Bound to exactly one customer." if ok else "The case has no single bound customer.")
    if "facts_owned" in which:
        bad = [f["fact_id"] for f in facts.values()
               if (f.get("source") or {}).get("party") not in (None, case.get("customer_id"))]
        add("facts_owned", not bad, "Every customer fact belongs to the bound customer." if not bad else
            f"Facts from another customer: {', '.join(bad)}.")
    if "placeholders_resolve" in which:
        missing = [p for p in placeholders(source) if p not in facts and p not in NAMED]
        add("placeholders_resolve", not missing, "Every placeholder has a fact." if not missing else
            f"Unknown placeholders: {', '.join(sorted(set(missing)))}.")
    if "no_literal_facts" in which:
        typed = literal_values(model_text(source), pats)
        add("no_literal_facts", not typed, "The model typed no facts." if not typed else
            f"Typed values that must be placeholders: {', '.join(typed[:8])}.")
    if "policy_actions" in which:
        problems = []
        for o in outcomes:
            if o["outcome"] not in o["allowed"]:
                problems.append(f"request {o['request_no']} outcome {o['outcome']} is not allowed")
            cat = o["category"]
            if cat != "other" and not policy.category(cat)["enabled"] and o["outcome"] != "acknowledge":
                problems.append(f"{cat} is switched off")
        decided = {o["request_no"]: o["outcome"] for o in outcomes}
        for r in resolver_outcomes or []:
            if r.get("request_no") in decided and r.get("outcome") != decided[r["request_no"]]:
                problems.append(f"request {r['request_no']} was answered as {r.get('outcome')}, "
                                f"but the rules decided {decided[r['request_no']]}")
        approved = any(d["state"] == "approved" for d in decisions or [])
        if not approved and re.search(r"\b(will|shall) (be )?(refund|credit|reimburs)", _fold(rendered)):
            problems.append("the reply promises money back without a recorded decision")
        add("policy_actions", not problems, "Every outcome is allowed by the policy." if not problems else
            "; ".join(problems) + ".")
    if "never_say" in which:
        folded = _fold(rendered)
        hits = [p for p in policy.data["reply"]["never_say"] if _fold(p) in folded]
        add("never_say", not hits, "No forbidden phrase." if not hits else f"Forbidden: {', '.join(hits)}.")
    if "limits" in which:
        cap = min(policy.data["reply"]["max_chars"], 10000)
        problems = []
        if len(rendered) > cap:
            problems.append(f"{len(rendered)} characters, over {cap}")
        if len(attachments) > MAX_ATTACHMENTS:
            problems.append(f"{len(attachments)} attachments, over {MAX_ATTACHMENTS}")
        total = sum(int(a.get("bytes") or 0) for a in attachments)
        if total > MAX_TOTAL_BYTES:
            problems.append("attachments over 20 MiB")
        if any(a.get("media_type") == "application/pdf" and int(a.get("bytes") or 0) > MAX_PDF_BYTES
               for a in attachments):
            problems.append("a PDF over 5 MiB")
        if not rendered.strip():
            problems.append("the reply is empty")
        add("limits", not problems, f"{len(rendered)} characters, {len(attachments)} attachments." if not problems
            else "; ".join(problems) + ".")
    if "language" in which:
        langs = policy.data["reply"]["languages"]
        ok = language in langs
        add("language", True, f"Reply in {language}." if ok else
            f"The customer wrote in {language}, which the policy does not list. The reply uses "
            f"{policy.data['reply']['default_language']}. An operator should check.", warn=not ok)
        if not ok:
            results[-1]["status"] = "warn"
    if "foreign_ids" in which:
        known = _fact_strings(facts)
        foreign = []
        for pat in pats:
            for m in re.finditer(pat, rendered):
                if m.group(0).upper() not in known:
                    foreign.append(m.group(0))
        add("foreign_ids", not foreign, "Every document id is in the fact sheet." if not foreign else
            f"Document ids not in the fact sheet: {', '.join(sorted(set(foreign)))}.")
    if "freshness" in which:
        stale = [k for k, v in used_digests.items() if current_digests.get(k) and current_digests[k] != v]
        add("freshness", not stale, "Policy and style are current." if not stale else
            f"Changed since drafting: {', '.join(stale)}.")
    typed = literal_values(model_text(source), pats) if author_kind == "person" else []
    passed = all(r["status"] != "fail" for r in results)
    return {"checks": results, "passed": passed, "typed_values": typed}


def style_notes(rendered: str, style) -> list[str]:
    """Non-blocking notes, shown to the person reviewing."""
    notes = []
    greet = style.greeting.split("[[")[0].strip()
    if greet and not rendered.lstrip().startswith(greet):
        notes.append(f"The reply does not open with the house greeting ({greet}).")
    if style.closing and style.closing not in rendered:
        notes.append(f"The reply does not use the house closing ({style.closing}).")
    if "—" in rendered or "–" in rendered:
        notes.append("The reply uses a long dash.")
    return notes
