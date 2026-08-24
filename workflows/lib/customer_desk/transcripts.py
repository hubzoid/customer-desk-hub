"""Meeting and call transcripts: one internal case per customer request found,
each citing the transcript lines it came from. The uploader names the
customer. The model only finds the requests, never the customer."""
from __future__ import annotations

import hashlib
import re
from pathlib import Path

from . import actions, cases, envelopes, store

MAX_BYTES = 2 * 1024 * 1024
MAX_SEGMENTS = 20


def numbered(text: str) -> list[str]:
    """Plain text, WebVTT or SRT, as numbered speaker lines."""
    lines = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line == "WEBVTT" or line.isdigit() or re.match(r"^\d\d:\d\d[:.,\d]* --> ", line):
            continue
        lines.append(line)
    return [f"[{n}] {line}" for n, line in enumerate(lines, start=1)]


def import_transcript(hub_dir: Path, actor: actions.Actor, *, customer_id: str, text: str, name: str, start) -> dict:
    actions.require(actor, "desk_operator")
    if len(text.encode()) > MAX_BYTES:
        raise actions.ActionError("payload_too_large", "A transcript is at most 2 MiB.", 413)
    actions._customer(hub_dir, customer_id)
    digest = hashlib.sha256(text.encode()).hexdigest()[:16]
    item = start("customer_desk_intake", key=f"transcript:{customer_id}:{digest}", route="triage",
                 input={"kind": "transcript", "customer_id": customer_id, "name": name, "lines": numbered(text),
                        "opened_by": actor.email, "digest": digest}, requester=actor.email)
    return {"state": "reading", "work_item_id": item["id"], "lines": len(numbered(text))}


def split(hub_dir: Path, inp: dict, runner) -> list[dict]:
    """Inside the transcript work item: find the requests, open a case for each."""
    body = "\n".join(inp["lines"])
    result = runner.station("desk-transcript-reader", stage="transcript", revision=1,
                            message=f"<customer_message>\n{body}\n</customer_message>")
    opened = []
    for n, seg in enumerate((result.get("segments") or [])[:MAX_SEGMENTS], start=1):
        lo, hi = int(seg["line_from"]), int(seg["line_to"])
        if not (1 <= lo <= hi <= len(inp["lines"])):
            continue
        cited = "\n".join(inp["lines"][lo - 1:hi])
        text = (f"From the transcript {inp['name']}, lines {lo} to {hi}:\n{cited}")
        env = envelopes.internal(surface="transcript", customer_id=inp["customer_id"], text=text,
                                 opened_by=inp["opened_by"], source_ref=f"{inp['digest']}:{lo}-{hi}")
        opened.append(runner.checkpoint(f"transcript-case-{n}", lambda env=env: cases.intake(hub_dir, env)))
    return opened
