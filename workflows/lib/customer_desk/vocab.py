"""The request-kind vocabulary (`knowledge/request-kinds.md`) and the reply
style (`knowledge/customer-messages.md`): the only sources of categories,
helpdesk tags and approved reply templates."""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path

import yaml

from .policy import FLAGS, FRONT_RE

KINDS = ("order_status", "invoice_copy", "account_statement", "price_availability", "delivery_change", "complaint",
         "other")
TAG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{1,48}[a-z0-9]$")


class VocabularyError(Exception):
    def __init__(self, problems: list[str], path: str):
        super().__init__(f"{path}: " + "; ".join(problems))
        self.problems, self.path, self.code = problems, path, "desk_vocabulary_invalid"


@dataclass(frozen=True)
class Vocabulary:
    kinds: dict
    boundaries: list
    risk_flags: dict
    tag_prefix: str
    digest: str

    def tag(self, kind: str) -> str:
        return self.kinds[kind]["tag"]

    def prompt(self) -> str:
        """The vocabulary as the classifier reads it."""
        lines = ["Request kinds (choose only from these):"]
        for key, k in self.kinds.items():
            lines.append(f"- {key}: {k['label']}. {k['guidance']}")
            for ex in k.get("examples") or []:
                lines.append(f"    example: {ex}")
        lines.append("Boundary rules:")
        lines += [f"- {b}" for b in self.boundaries]
        lines.append("Risk flags (flag only what the message raises):")
        lines += [f"- {k}: {v}" for k, v in self.risk_flags.items()]
        return "\n".join(lines)


def _front(text: str, path: str) -> dict:
    m = FRONT_RE.match(text)
    if not m:
        raise VocabularyError(["missing YAML frontmatter"], path)
    try:
        return yaml.safe_load(m.group(1)) or {}
    except yaml.YAMLError as exc:
        raise VocabularyError([f"not valid YAML: {exc}"], path) from None


def load_kinds(hub_dir: Path, rel: str = "knowledge/request-kinds.md") -> Vocabulary:
    text = (Path(hub_dir) / rel).read_text()
    data = _front(text, rel)
    problems = []
    kinds = data.get("kinds") or {}
    prefix = data.get("tag_prefix") or ""
    if not isinstance(kinds, dict) or not kinds or "other" not in kinds:
        raise VocabularyError(["kinds must be a mapping including other"], rel)
    tags = set()
    for key, k in kinds.items():
        if not re.fullmatch(r"[a-z][a-z0-9_]{0,63}", key) or not isinstance(k, dict):
            raise VocabularyError([f"invalid category {key!r}"], rel)
        if k.get("behavior", "erp" if key in KINDS[:-1] else "answer") not in (
                "answer", "clarify", "review", "erp"):
            problems.append(f"{key}.behavior must be answer, clarify, review or erp")
        if k.get("behavior") == "erp" and key not in KINDS[:-1]:
            problems.append(f"{key} has no implemented ERP job")
        for field in ("tag", "label", "guidance"):
            if not isinstance(k.get(field), str) or not k[field].strip():
                problems.append(f"{key}.{field} is required")
        tag = k.get("tag") or ""
        if not TAG_RE.match(tag) or not tag.startswith(prefix):
            problems.append(f"{key}.tag {tag!r} must match {TAG_RE.pattern} and start with {prefix!r}")
        if tag in tags:
            problems.append(f"{key}.tag {tag!r} is used twice")
        tags.add(tag)
    flags = data.get("risk_flags") or {}
    if set(flags) != set(FLAGS):
        problems.append(f"risk_flags must be exactly {', '.join(FLAGS)}")
    if problems:
        raise VocabularyError(problems, rel)
    return Vocabulary(kinds=kinds, boundaries=list(data.get("boundaries") or []),
                      risk_flags=flags, tag_prefix=prefix,
                      digest="sha256:" + hashlib.sha256(text.encode()).hexdigest())


@dataclass(frozen=True)
class Style:
    greeting: str
    closing: str
    templates: dict
    body: str
    digest: str

    def prompt(self) -> str:
        lines = [self.body.strip(), "", f"Greeting: {self.greeting}", f"Closing: {self.closing}",
                 "Approved templates by outcome:"]
        for key, value in self.templates.items():
            lines.append(f"- {key}: {value.strip()}")
        return "\n".join(lines)


def load_style(hub_dir: Path, rel: str = "knowledge/customer-messages.md") -> Style:
    text = (Path(hub_dir) / rel).read_text()
    data = _front(text, rel)
    m = FRONT_RE.match(text)
    problems = [f"{k} is required" for k in ("greeting", "closing") if not isinstance(data.get(k), str)]
    if problems:
        raise VocabularyError(problems, rel)
    return Style(greeting=data["greeting"], closing=data["closing"], templates=dict(data.get("templates") or {}),
                 body=text[m.end():], digest="sha256:" + hashlib.sha256(text.encode()).hexdigest())
