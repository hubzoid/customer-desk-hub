"""Mask personal data before any model sees a message.

Document references that match the policy's id patterns stay readable, since
the classifier must copy them. Everything else that identifies a person is
replaced: email addresses, phone numbers, card-like numbers, the sender's own
name, and URL paths and queries.
"""
from __future__ import annotations

import re

EMAIL = re.compile(r"[\w.+'-]+@[\w-]+(?:\.[\w-]+)+")
URL = re.compile(r"\bhttps?://([^\s/]+)[^\s]*", re.I)
CARD = re.compile(r"\b(?:\d[ -]?){13,19}\b")
PHONE = re.compile(r"(?<![\w-])\+?\d[\d ().-]{7,}\d(?![\w-])")


DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$|^\d{1,2}[/.-]\d{1,2}[/.-]\d{2,4}$")


def _phone(m: re.Match) -> str:
    text = m.group(0)
    digits = sum(ch.isdigit() for ch in text)
    if digits < 9 or DATE.match(text.strip()):
        return text
    return "[phone]"


def mask(text: str, *, names: list[str] | None = None, id_patterns: list[str] | None = None) -> str:
    if not text:
        return ""
    keep: dict[str, str] = {}
    out = text
    for n, pat in enumerate(id_patterns or []):
        def stash(m, n=n):
            token = f"\x00{len(keep)}\x00"
            keep[token] = m.group(0)
            return token
        out = re.sub(pat, stash, out)
    out = URL.sub(lambda m: f"https://{m.group(1)}/[link]", out)
    out = EMAIL.sub("[email]", out)
    out = CARD.sub("[card number]", out)
    out = PHONE.sub(_phone, out)
    for name in names or []:
        for token in re.findall(r"[A-Za-z][A-Za-z'-]{2,}", name or ""):
            if token.casefold() in {"synthetic", "the", "and", "team", "accounts", "orders", "desk"}:
                continue
            out = re.sub(rf"\b{re.escape(token)}\b", "[name]", out, flags=re.I)
    for token, original in keep.items():
        out = out.replace(token, original)
    return out
