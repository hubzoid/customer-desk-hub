"""Deterministic stand-in stations for tests and scripted evals.

They are keyword-driven and know nothing the real stations do not get in
their messages. Scripted runs prove the plumbing, the rules, the checks and
the write boundaries. They never stand in for real-model evidence, and every
report labels them "scripted".
"""
from __future__ import annotations

import datetime as dt
import json
import re

MONTHS = {m: i for i, m in enumerate(["january", "february", "march", "april", "may", "june", "july", "august",
                                      "september", "october", "november", "december"], start=1)}
#: The sample policy's id patterns (knowledge/desk-policy.md), so references are read the same way.
PATTERNS = [r"SAL-ORD-[0-9]{4}-[0-9]{5}", r"ACC-SINV-[0-9]{4}-[0-9]{5}", r"SYN-[A-Z]+-[0-9]+", r"\b[A-Z]{2,4}-[0-9]{3,5}\b"]


def _message(text: str) -> str:
    m = re.search(r"<customer_message>\n(.*?)\n</customer_message>", text, re.S)
    body = m.group(1) if m else text
    # Attachments are data. The stand-in reads only what the customer wrote.
    return re.sub(r"\[attachment [^\]]*\][^\n]*\n?(?:(?!\[(?:message|attachment|a note)).*\n?)*", "", body)


def _today(text: str) -> dt.date:
    m = re.search(r"Today's date for the desk: (\d{4}-\d{2}-\d{2})", text)
    return dt.date.fromisoformat(m.group(1)) if m else dt.date(2000, 1, 15)


def _dates(body: str, today: dt.date) -> list[str]:
    out = re.findall(r"\b(\d{4}-\d{2}-\d{2})\b", body)
    for mon, day in re.findall(r"\b(" + "|".join(MONTHS) + r")\s+(\d{1,2})\b", body, re.I):
        out.append(dt.date(today.year, MONTHS[mon.lower()], int(day)).isoformat())
    if re.search(r"\ba week later\b", body, re.I):
        out.append("")
    return out


CATS = [
    ("complaint", r"damaged|broken|complain|wrong item|charged twice|refund|money back|unhappy|lawyer|legal action|"
                  r"leak|\blate\b|ran out"),
    ("delivery_change", r"move (the )?deliver|reschedul|deliver(y)? .*(later|earlier|instead)|change the delivery|"
                        r"push (the )?delivery|bring .* forward|new delivery date|come on .* instead"),
    ("account_statement", r"statement|open invoices|everything we (still )?owe|unpaid invoices|what (do )?we owe|"
                          r"still open"),
    ("invoice_copy", r"copy of (the )?invoice|invoice copy|resend .*invoice|pdf of|send .*invoice"),
    ("price_availability", r"price|in stock|availability|how much|do you have|stock|\bcost"),
    ("order_status", r"where is|status|has (.* )?shipped|when will|arrive|track|update on (my|our) order|check .*order|"
                     r"news on (my |our )?order|i mean order|what happened to"),
]
FLAGS = [("legal_threat", r"lawyer|legal action|court|sue\b"), ("safety_issue", r"injur|unsafe|hurt"),
         ("personal_data_request", r"delete (my|our) (personal )?data|personal data"),
         ("other_customer_data", r"another customer|other customer|their invoices|someone else's|every customer")]


INJECTION = re.compile(r"ignore (?:(?:all|your|previous|my) )+(?:instructions|rules)|you are now|"
                       r"approve (?:this|the) refund|mark every refund|system prompt|system notice|reveal|"
                       r"as the administrator|administrator mode|^\s*system:|you are approved", re.I | re.M)


def classify(message: str) -> dict:
    body = _message(message)
    original = body.lower()
    today = _today(message)
    injection = bool(INJECTION.search(body))
    # Instructions to the desk are not requests: drop those sentences, as the real classifier is told to.
    body = " ".join(s for s in re.split(r"(?<=[.?!])\s+", body) if not INJECTION.search(s)) if injection else body
    low = body.lower()
    sentences = [s for s in re.split(r"(?<=[.?!])\s+|\n+", body) if s.strip()]
    requests = []
    for cat, pat in CATS:
        if re.search(pat, low):
            if cat == "invoice_copy" and re.search(r"refund|charged twice", low):
                continue
            if cat == "price_availability" and cat != "complaint" and re.search(r"refund", low):
                continue
            if cat == "order_status" and any(r["category"] in ("delivery_change", "complaint") for r in requests):
                continue
            if cat == "invoice_copy" and any(r["category"] == "account_statement" for r in requests):
                continue
            relevant = " ".join(s for s in sentences if re.search(pat, s.lower())) or body
            requests.append(_request(cat, body if cat in ("complaint", "delivery_change") else relevant, today))
    # One request per thing asked, in the order the customer asked them.
    def first_hit(r):
        pat = dict(CATS)[r["category"]]
        m = re.search(pat, low)
        return m.start() if m else len(low)

    requests.sort(key=first_hit)
    if not requests:
        requests.append(_request("other", body, today))
    # Risk flags only add: read on the whole message, injected instructions included.
    flags = [f for f, pat in FLAGS if re.search(pat, original)]
    return {"language": "en", "summary": "A customer request.", "escalation_flags": flags,
            "needs_clarification": False, "questions": [], "confidence": 0.9 if requests[0]["category"] != "other" else 0.5,
            "injection_detected": injection, "requests": requests[:5]}


def _request(cat: str, text: str, today: dt.date) -> dict:
    from .ids import find

    found = find(text, PATTERNS)
    invoices = [i for i in found if i.startswith("ACC-SINV-")]
    items = [{"text": i, "quantity": None} for i in found if i.startswith("SYN-ITEM-")]
    # Orders by ERPNext id or by the customer's own order number.
    orders = [i for i in found if i.startswith("SAL-ORD-") or not i.startswith(("ACC-SINV-", "SYN-"))]
    if cat == "price_availability" and not items:
        m = re.search(r"(?:price for|price of|cost of|much are|much is|do you have|have any) (?:the |your |any |our )?"
                      r"([a-z][a-z ,-]{2,40}?)(?: for us| in stock|,|\?|\.| and|$)", text.lower())
        if m:
            items = [{"text": m.group(1).strip(), "quantity": None}]
    dates = _dates(text, today)
    dated = {"requested_delivery": None, "from": None, "to": None}
    if cat == "delivery_change" and dates:
        dated["requested_delivery"] = dates[-1] or None
    if cat == "account_statement" and len(dates) >= 2:
        dated["from"], dated["to"] = sorted(d for d in dates[:2] if d)[:2] if all(dates[:2]) else (None, None)
    refund = bool(re.search(r"refund|money back|reimburse", text.lower()))
    amount = re.search(r"\$\s?[\d,]+(?:\.\d\d)?", text)
    return {"category": cat, "summary": f"A {cat.replace('_', ' ')} request.",
            "references": {"orders": orders, "invoices": invoices, "items": items, "dates": dated},
            "refund_requested": refund and cat == "complaint", "amount_text": amount.group(0) if amount else None}


def second_opinion(message: str) -> dict:
    first = classify(message)
    return {"categories": [r["category"] for r in first["requests"]], "escalation_flags": first["escalation_flags"],
            "unsure": first["requests"][0]["category"] == "other", "reason": "Keyword read."}


def parse_outcomes(message: str) -> list[dict]:
    """The decided outcomes as the resolver message states them."""
    dec = json.JSONDecoder()
    out = []
    for m in re.finditer(r"^- Request (\d+) \((\w+)\): decided outcome `(\w+)`\..*?Slots: ", message, re.M):
        slots, end = dec.raw_decode(message, m.end())
        rest = message[m.end() + end:].split("\n", 1)[0]
        ask = re.search(r"Ask: (.*)$", rest)
        out.append({"request_no": int(m.group(1)), "category": m.group(2), "outcome": m.group(3), "slots": slots,
                    "questions": [ask.group(1)] if ask else [], "allowed": [m.group(3)], "rule_refs": []})
    return out


def resolve(message: str, loaded) -> dict:
    """Word the reply from the approved templates, exactly as the
    deterministic formatter does, so scripted runs exercise the checks."""
    from .pipeline import format_reply

    outcomes = parse_outcomes(message)
    return {"reply_markdown": format_reply(loaded, outcomes),
            "requests": [{"request_no": o["request_no"], "outcome": o["outcome"], "rule_refs": []} for o in outcomes],
            "questions": [], "operator_note": None, "suggested_policy_note": None}


def review(message: str) -> dict:
    reply = re.search(r"<proposed_reply>\n(.*?)\n</proposed_reply>", message, re.S)
    text = (reply.group(1) if reply else "").lower()
    findings = []
    for bad in ("refund approved", "guaranteed delivery", "compensation agreed"):
        if bad in text:
            findings.append({"rule_ref": "R15", "problem": f"The reply says '{bad}'.", "suggestion": "Remove it."})
    return {"verdict": "revise" if findings else "pass", "findings": findings, "unsupported_claims": []}


class ScriptedStations:
    """Answers `Runner.station` calls without a model."""

    def __init__(self, loaded_fn):
        self.loaded_fn = loaded_fn
        self.calls: list[tuple[str, str, int]] = []

    def __call__(self, agent: str, *, stage: str, revision: int, message: str) -> dict:
        self.calls.append((agent, stage, revision))
        if agent == "desk-classifier":
            return classify(message)
        if agent == "desk-second-opinion":
            return second_opinion(message)
        if agent == "desk-resolver":
            return resolve(message, self.loaded_fn())
        if agent == "desk-reviewer":
            return review(message)
        if agent == "desk-transcript-reader":
            return split_transcript(message)
        raise KeyError(agent)


def split_transcript(message: str) -> dict:
    body = _message(message)
    segments = []
    for m in re.finditer(r"^\[(\d+)\] (?:Customer|Caller)[^:]*: (.+)$", body, re.M | re.I):
        line, text = int(m.group(1)), m.group(2)
        if classify(f"<customer_message>\n{text}\n</customer_message>")["requests"][0]["category"] != "other":
            segments.append({"line_from": line, "line_to": line, "request_text": text})
    return {"segments": segments[:20]}
