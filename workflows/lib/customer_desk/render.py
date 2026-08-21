"""Fill a reply's placeholders from the fact sheet, and compute the digest
that an approval binds to."""
from __future__ import annotations

import hashlib
import json
import re

PLACEHOLDER = re.compile(r"\[\[([A-Za-z_][A-Za-z0-9_]*)\]\]")
NAMED = ("sender_name", "observed")


class RenderError(Exception):
    def __init__(self, missing: list[str]):
        super().__init__(f"Unknown placeholders: {', '.join(missing)}")
        self.missing = missing


def placeholders(source: str) -> list[str]:
    return PLACEHOLDER.findall(source or "")


def render(source: str, facts: dict[str, dict], *, sender_name: str, observed: str, strict: bool = True) -> str:
    missing = []

    def sub(m):
        key = m.group(1)
        if key == "sender_name":
            return sender_name
        if key == "observed":
            return observed
        fact = facts.get(key)
        if fact is None:
            missing.append(key)
            return m.group(0)
        return fact["display"]

    out = PLACEHOLDER.sub(sub, source or "")
    if missing and strict:
        raise RenderError(sorted(set(missing)))
    return out


def model_text(source: str) -> str:
    """What the author typed: the source with every placeholder removed."""
    return PLACEHOLDER.sub(" ", source or "")


def safe_name(display: str | None) -> str:
    """A sanitised display name for the greeting: letters, spaces, apostrophes
    and hyphens only, at most 60 characters, else a neutral greeting."""
    text = re.sub(r"[^\w '\-]", "", (display or "").split("<")[0], flags=re.UNICODE).strip()
    text = re.sub(r"\d", "", text).strip()
    return text[:60] if len(text) >= 2 else "there"


def digest(*, case_id: str, reply_revision: int, body: str, subject: str | None, recipients: list,
           attachments: list[dict], policy_digest: str, fact_sheet_digest: str, origin: dict | None = None) -> str:
    canon = {"case_id": case_id, "reply_revision": reply_revision, "body": body, "subject": subject or "",
             "recipients": sorted(recipients or []),
             "attachments": sorted((a.get("name"), a.get("sha256")) for a in attachments or []),
             "policy_digest": policy_digest, "fact_sheet_digest": fact_sheet_digest, "origin": origin or {}}
    return "sha256:" + hashlib.sha256(json.dumps(canon, sort_keys=True).encode()).hexdigest()
