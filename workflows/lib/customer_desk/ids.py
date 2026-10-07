"""Document ids and customer references in text, by the policy's id patterns.

Patterns overlap: `ORD-2000` is inside `SAL-ORD-2000-00001`, and `CUST-001`
inside `SYN-CUST-001`. Only the longest match at each place counts, so the
rules never look up a fragment and the checks never call a fragment foreign.
The patterns themselves stay RE2 compatible (no lookaround).
"""
from __future__ import annotations

import re


def find(text: str, patterns: list[str]) -> list[str]:
    """Each id in `text`, in order of appearance, without overlaps or repeats."""
    spans = []
    for pat in patterns or []:
        for m in re.finditer(pat, text or "", re.I):
            if m.end() > m.start():
                spans.append((m.start(), m.end()))
    spans.sort(key=lambda s: (-(s[1] - s[0]), s[0]))
    kept: list[tuple[int, int]] = []
    for start, end in spans:
        if all(end <= a or start >= b for a, b in kept):
            kept.append((start, end))
    out = []
    for start, end in sorted(kept):
        value = (text or "")[start:end].upper()
        if value not in out:
            out.append(value)
    return out
