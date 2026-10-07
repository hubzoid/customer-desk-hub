"""The desk policy file: validated frontmatter the code enforces, and numbered
rules in prose the stations cite.

`load` returns a `Policy` or raises `PolicyError` listing every problem with
its file, line and key. `gaps` names the settings a policy leaves to defaults,
so an owner who brings their own rules sees what their files did not say.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path

import yaml

CATEGORIES = ("order_status", "invoice_copy", "account_statement", "price_availability", "delivery_change",
              "complaint")
FLAGS = ("legal_threat", "safety_issue", "personal_data_request", "other_customer_data")
RULE_RE = re.compile(r"^\s*[-*]\s+\[(R\d+)\]\s+(.*)$")
FRONT_RE = re.compile(r"\A---\n(.*?)\n---\n", re.S)

#: The full key set with defaults. A policy may leave any of these out; `gaps` reports which.
DEFAULTS = {
    "reply": {"default_language": "en", "languages": ["en"], "max_chars": 3000, "signature": "",
              "never_say": [], "composition": "fluid"},
    "facts": {"id_patterns": []},
    "categories": {
        "order_status": {"enabled": True, "max_orders": 5, "overdue_action": "ticket"},
        "invoice_copy": {"enabled": True, "max_age_days": 730},
        "account_statement": {"enabled": True, "max_range_days": 366},
        "price_availability": {"enabled": True, "price_source": "customer_price_list",
                               "availability": {"disclosure": "exact", "limited_below": None}},
        "delivery_change": {"enabled": True, "min_notice_days": 2},
        "complaint": {"enabled": True, "default_severity": "normal"},
    },
    "refunds": {"basis": "invoice_date", "within_days": 30, "max_amount": None, "outside_action": "decision"},
    "escalate_on": list(FLAGS),
    "escalation": {"plan_review": "required"},
}

GAP_TEXT = {
    "categories.delivery_change.min_notice_days": "Your files do not say how many days notice a delivery change needs.",
    "refunds.within_days": "Your files do not say how many days after the invoice a refund is still within policy.",
    "categories.price_availability.availability": "Your files do not say whether customers may see exact stock numbers.",
    "categories.invoice_copy.max_age_days": "Your files do not say how old an invoice may be for a copy.",
    "categories.account_statement.max_range_days": "Your files do not say the longest period a statement may cover.",
    "categories.order_status.overdue_action": "Your files do not say what happens when an order is late.",
    "reply.signature": "Your files do not give a signature for replies.",
    "reply.never_say": "Your files do not list phrases replies must never use.",
    "escalate_on": "Your files do not say which messages must be escalated.",
}


class PolicyError(Exception):
    def __init__(self, problems: list[dict]):
        super().__init__("; ".join(f"{p['file']}:{p.get('line') or '?'} {p['key']}: {p['reason']}" for p in problems))
        self.problems = problems
        self.code = "desk_policy_invalid"


@dataclass(frozen=True)
class Policy:
    data: dict
    rules: dict[str, str]
    body: str
    digest: str
    path: str
    present: frozenset

    def get(self, dotted: str, default=None):
        node = self.data
        for part in dotted.split("."):
            if not isinstance(node, dict) or part not in node:
                return default
            node = node[part]
        return node

    def category(self, name: str) -> dict:
        return self.data["categories"][name]

    def to_json(self) -> dict:
        return {"path": self.path, "digest": self.digest, "settings": self.data, "rules": self.rules}


def _merge(defaults: dict, given: dict) -> dict:
    out = {}
    for key, value in defaults.items():
        if isinstance(value, dict) and isinstance(given.get(key), dict):
            out[key] = _merge(value, given[key])
        elif key in given:
            out[key] = given[key]
        else:
            out[key] = value
    return out


def _paths(node, prefix="") -> set[str]:
    out = set()
    if isinstance(node, dict):
        for k, v in node.items():
            p = f"{prefix}{k}"
            out.add(p)
            out |= _paths(v, p + ".")
    return out


def _line_of(front: str, key: str) -> int | None:
    leaf = key.split(".")[-1]
    for n, line in enumerate(front.splitlines(), start=2):
        if re.match(rf"\s*{re.escape(leaf)}\s*:", line) or re.search(rf"[{{,]\s*{re.escape(leaf)}\s*:", line):
            return n
    return None


def parse(text: str, path: str = "knowledge/desk-policy.md") -> Policy:
    problems: list[dict] = []

    def bad(key, reason, line=None):
        problems.append({"file": path, "line": line or _line_of(front, key), "key": key, "reason": reason})

    m = FRONT_RE.match(text)
    front = m.group(1) if m else ""
    if not m:
        raise PolicyError([{"file": path, "line": 1, "key": "frontmatter",
                            "reason": "The policy must start with YAML frontmatter between --- lines."}])
    try:
        given = yaml.safe_load(front) or {}
    except yaml.YAMLError as exc:
        mark = getattr(exc, "problem_mark", None)
        raise PolicyError([{"file": path, "line": (mark.line + 2) if mark else None, "key": "frontmatter",
                            "reason": f"Not valid YAML: {getattr(exc, 'problem', exc)}"}]) from None
    if not isinstance(given, dict):
        raise PolicyError([{"file": path, "line": 2, "key": "frontmatter", "reason": "Frontmatter must be a mapping."}])
    allowed_top = {"version", "name", "company"} | set(DEFAULTS)
    for key in sorted(set(given) - allowed_top):
        bad(key, f"Unknown key. Allowed: {', '.join(sorted(allowed_top))}.")
    if given.get("version") != 1:
        bad("version", "version must be 1.")
    for section in ("reply", "facts", "refunds", "escalation"):
        if section in given and isinstance(given[section], dict):
            for key in sorted(set(given[section]) - set(DEFAULTS[section])):
                bad(f"{section}.{key}", f"Unknown key. Allowed: {', '.join(sorted(DEFAULTS[section]))}.")
    cats = given.get("categories") or {}
    if not isinstance(cats, dict):
        bad("categories", "categories must be a mapping.")
        cats = {}
    for name, cfg in cats.items():
        if name not in CATEGORIES:
            bad(f"categories.{name}", f"Unknown category. Allowed: {', '.join(CATEGORIES)}.")
        elif isinstance(cfg, dict):
            for key in sorted(set(cfg) - set(DEFAULTS["categories"][name])):
                bad(f"categories.{name}.{key}", f"Unknown key. Allowed: {', '.join(sorted(DEFAULTS['categories'][name]))}.")
    data = _merge(DEFAULTS, given)

    def integer(key, lo, hi, *, nullable=False):
        value = data_get(data, key)
        if value is None and nullable:
            return
        if isinstance(value, bool) or not isinstance(value, int) or not lo <= value <= hi:
            bad(key, f"Must be a whole number from {lo} to {hi}, not {value!r}.")

    def choice(key, options):
        value = data_get(data, key)
        if value not in options:
            bad(key, f"Must be one of {', '.join(map(str, options))}, not {value!r}.")

    r = data["reply"]
    if not isinstance(r.get("languages"), list) or not r["languages"]:
        bad("reply.languages", "languages is a non-empty list of language codes.")
    elif r.get("default_language") not in r["languages"]:
        bad("reply.default_language", "default_language must be one of languages.")
    integer("reply.max_chars", 100, 10000)
    if not isinstance(r.get("never_say"), list) or not all(isinstance(x, str) and x.strip() for x in r["never_say"]):
        bad("reply.never_say", "never_say is a list of phrases.")
    choice("reply.composition", ("fluid", "templates"))
    if not isinstance(r.get("signature"), str):
        bad("reply.signature", "signature is text.")
    pats = data["facts"]["id_patterns"]
    if not isinstance(pats, list) or len(pats) > 10:
        bad("facts.id_patterns", "id_patterns is a list of at most 10 patterns.")
    else:
        for pat in pats:
            if not isinstance(pat, str) or len(pat) >= 100:
                bad("facts.id_patterns", "Each pattern is text under 100 characters.")
                continue
            if re.search(r"\(\?[=!<]|\\[1-9]", pat):
                bad("facts.id_patterns", f"{pat!r} uses lookaround or backreferences, which RE2 does not allow.")
            try:
                re.compile(pat)
            except re.error as exc:
                bad("facts.id_patterns", f"{pat!r} is not a valid pattern: {exc}")
    for name in CATEGORIES:
        if not isinstance(data["categories"][name].get("enabled"), bool):
            bad(f"categories.{name}.enabled", "enabled is true or false.")
    integer("categories.order_status.max_orders", 1, 20)
    choice("categories.order_status.overdue_action", ("ticket", "reply_only"))
    integer("categories.invoice_copy.max_age_days", 1, 3650)
    integer("categories.account_statement.max_range_days", 1, 3660)
    choice("categories.price_availability.price_source", ("customer_price_list", "none"))
    choice("categories.price_availability.availability.disclosure", ("exact", "band", "none"))
    if data_get(data, "categories.price_availability.availability.disclosure") == "band":
        integer("categories.price_availability.availability.limited_below", 1, 100000)
    integer("categories.delivery_change.min_notice_days", 0, 60)
    choice("categories.complaint.default_severity", ("low", "normal", "high", "critical"))
    choice("refunds.basis", ("invoice_date",))
    integer("refunds.within_days", 0, 3650)
    cap = data_get(data, "refunds.max_amount")
    if cap is not None and (isinstance(cap, bool) or not isinstance(cap, (int, float)) or cap <= 0):
        bad("refunds.max_amount", f"max_amount is a positive amount in the invoice currency, or null, not {cap!r}.")
    choice("refunds.outside_action", ("decision",))
    esc = data["escalate_on"]
    if not isinstance(esc, list) or any(f not in FLAGS for f in esc):
        bad("escalate_on", f"escalate_on is a subset of {', '.join(FLAGS)}.")
    choice("escalation.plan_review", ("required", "none"))

    body = text[m.end():]
    rules: dict[str, str] = {}
    offset = text[:m.end()].count("\n")
    for n, line in enumerate(body.splitlines(), start=offset + 1):
        rm = RULE_RE.match(line)
        if rm:
            if rm.group(1) in rules:
                problems.append({"file": path, "line": n, "key": rm.group(1), "reason": "Rule number used twice."})
            rules[rm.group(1)] = rm.group(2).strip()
    if not rules:
        problems.append({"file": path, "line": offset + 1, "key": "rules",
                         "reason": "No rules found. Write each rule as a list item starting [R1]."})
    if problems:
        raise PolicyError(problems)
    digest = "sha256:" + hashlib.sha256(text.encode()).hexdigest()
    return Policy(data=data, rules=rules, body=body, digest=digest, path=path, present=frozenset(_paths(given)))


def data_get(data: dict, dotted: str):
    node = data
    for part in dotted.split("."):
        if not isinstance(node, dict):
            return None
        node = node.get(part)
    return node


def load(hub_dir: Path, rel: str = "knowledge/desk-policy.md") -> Policy:
    path = Path(hub_dir) / rel
    if not path.is_file():
        raise PolicyError([{"file": rel, "line": None, "key": "file", "reason": "The policy file is missing."}])
    return parse(path.read_text(), rel)


def gaps(policy: Policy) -> list[dict]:
    """Settings the owner's file did not state, so a default applies."""
    out = []
    for key, text in GAP_TEXT.items():
        if key not in policy.present:
            out.append({"code": "desk_policy_gap", "key": key, "default": data_get(DEFAULTS, key), "message": text})
    return out
