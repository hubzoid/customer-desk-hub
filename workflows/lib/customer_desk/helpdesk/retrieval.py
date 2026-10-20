"""Read-only native search. Evidence is data, never a grant or current fact."""
from __future__ import annotations

import hashlib
import html
import re
from collections import Counter
from pathlib import Path

import yaml

from .. import masking

STOP = set("about after again also been could from have help hello just please that their there these this what when where which with would your thanks".split())


def plain(raw: str) -> str:
    return html.unescape(re.sub(r"<[^>]*>", " ", raw or ""))


def clean(raw: str, names=()) -> str:
    text = plain(raw).split("\nOn ")[0].split("-----Original Message-----")[0]
    text = re.split(r"(?im)^\s*(regards|best regards|kind regards|sincerely|thanks and regards)\b", text)[0]
    return masking.mask(text, names=list(names), id_patterns=[])[:4000]


def contact_names(ticket: dict) -> list[str]:
    contact = ticket.get("contact") or {}
    return [value for key in ("firstName", "lastName", "name")
            if isinstance(value := contact.get(key), str) and value.strip()]


def precedent_text(reader, ticket_id: str, thread_id: str) -> tuple[dict, dict, str]:
    """One masking contract for gathering and later source revalidation."""
    ticket = reader.ticket(ticket_id)
    full = reader.thread(ticket_id, thread_id)
    return ticket, full, clean(full.get("plainText") or full.get("content") or "", contact_names(ticket))


def keywords(text: str) -> list[str]:
    return [w for w, _ in Counter(re.findall(r"[a-z]{3,30}", plain(text).lower())).most_common(30) if w not in STOP][:6]


def permitted(ticket: dict, values: dict) -> bool:
    dept = values.get("FRESHDESK_GROUP_ID") if values.get("DESK_HELPDESK") == "freshdesk" else values.get("ZOHO_DESK_DEPARTMENT_ID")
    if dept and str(ticket.get("departmentId") or "") != str(dept):
        return False
    product = str(values.get("DESK_SUPPORT_PRODUCT") or "")
    if product and str(ticket.get("productId") or "") != product:
        return False
    return True


def articles(hub_dir: Path, values: dict, query: str) -> list[dict]:
    root = Path(hub_dir).resolve()
    folder = (root / values["DESK_KNOWLEDGE_DIR"]).resolve()
    if not folder.is_relative_to(root):
        raise ValueError("DESK_KNOWLEDGE_DIR must stay inside the hub")
    terms = set(keywords(query))
    out = []
    for path in sorted(folder.glob("*.md")):
        if not path.resolve().is_relative_to(root):
            raise ValueError("Knowledge symlinks cannot escape the hub")
        data = path.read_bytes()
        raw = data.decode("utf-8").replace("\r\n", "\n").replace("\r", "\n")
        m = re.match(r"\A---\n(.*?)\n---\n(.*)", raw, re.S)
        if not m:
            continue
        meta, body = yaml.safe_load(m[1]) or {}, m[2]
        if meta.get("status") != "approved" or meta.get("audience") != values["DESK_SUPPORT_AUDIENCE"]:
            continue
        if meta.get("company") != values["DESK_COMPANY"]:
            continue
        if meta.get("language", "en") != values["DESK_SUPPORT_LANGUAGE"]:
            continue
        if meta.get("product") and str(meta["product"]) != str(values.get("DESK_SUPPORT_PRODUCT")):
            continue
        score = len(terms & set(keywords(body + " " + str(meta.get("title", "")))))
        if score:
            out.append({"ref": f"kb:{path.relative_to(root)}", "text": body[:6000], "title": meta.get("title", path.stem),
                        "revision": "sha256:" + hashlib.sha256(data).hexdigest(), "scope": meta,
                        "kind": "approved_knowledge", "score": score})
    return sorted(out, key=lambda r: (-r["score"], r["ref"]))[:8]


def ticket_evidence(reader, ticket_id: str, values: dict) -> dict:
    ticket = reader.ticket(ticket_id)
    if not permitted(ticket, values):
        raise ValueError("Ticket is outside the configured support source scope")
    threads, complete = reader.all_threads(ticket_id)
    if not complete:
        raise ValueError("Conversation exceeds complete read limit; review in helpdesk")
    names = contact_names(ticket)
    history = []
    for th in sorted(threads, key=lambda t: t.get("createdTime") or "")[-40:]:
        if th.get("status") == "DRAFT" or th.get("private"):
            continue
        full = reader.thread(ticket_id, th["id"])
        history.append({"ref": f"current:{ticket_id}:{th['id']}", "text": clean(full.get("plainText") or full.get("content") or full.get("summary") or "", names),
                        "kind": "current_conversation", "direction": th.get("direction"), "source_time": th.get("createdTime")})
    return {"ticket": ticket, "history": history, "threads": threads}


def similar_resolved(reader, ticket: dict, query: str, values: dict) -> dict:
    """At most three native searches and six candidate reads. Failures are explicit."""
    candidates, errors = {}, []
    terms = keywords(query)
    # Historical answers need an explicit department/group boundary. A broad
    # integration account alone is not permission to reuse every old answer.
    if not ticket.get("departmentId"):
        return {"answers": [], "errors": ["history_scope_missing"]}
    for term in terms[:3]:
        try:
            for row in reader.search_resolved(term, department_id=str(ticket["departmentId"])):
                if str(row.get("id")) == str(ticket["id"]) or not permitted(row, values):
                    continue
                if str(row.get("departmentId")) != str(ticket["departmentId"]):
                    continue
                if ticket.get("productId") and str(row.get("productId") or "") != str(ticket["productId"]):
                    continue
                if str(row.get("statusType") or row.get("status") or "").lower() not in ("closed", "resolved"):
                    continue
                # A language/product boundary cannot be guessed from text.
                if row.get("language") and row["language"] != values["DESK_SUPPORT_LANGUAGE"]:
                    continue
                score = len(set(terms) & set(keywords(str(row.get("subject", "")) + " " + plain(row.get("description", "")))))
                if score:
                    candidates[str(row["id"])] = (score, row)
        except Exception as exc:  # source outages never become "no results"
            errors.append(type(exc).__name__)
    answers = []
    for _, row in sorted(candidates.values(), key=lambda r: -r[0])[:6]:
        try:
            threads, complete = reader.all_threads(str(row["id"]))
            if not complete:
                continue
            sent = [t for t in threads if t.get("direction") == "out" and t.get("status") != "DRAFT"
                    and not t.get("private") and not t.get("isAutoGenerated")]
            for th in sorted(sent, key=lambda t: t.get("createdTime") or "", reverse=True):
                current, full, answer = precedent_text(reader, str(row["id"]), str(th["id"]))
                if (not permitted(current, values) or str(current.get("departmentId")) != str(ticket["departmentId"])
                        or str(current.get("statusType") or current.get("status")).lower() not in ("closed", "resolved")
                        or (ticket.get("productId") and str(current.get("productId") or "") != str(ticket["productId"]))
                        or (current.get("language") and current["language"] != values["DESK_SUPPORT_LANGUAGE"])
                        or full.get("private") or full.get("status") == "DRAFT"):
                    continue
                if len(answer.split()) < 8 or re.search(r"(?i)automatic reply|automated|received your request", answer):
                    continue
                answers.append({"ref": f"resolved:{row['id']}:{th['id']}", "text": answer,
                                "question": clean(row.get("subject") or "", contact_names(current)),
                                "kind": "historical_precedent", "source_time": th.get("createdTime"),
                                "scope": {"department": current.get("departmentId"), "language": current.get("language"),
                                          "product": current.get("productId")}})
                break
        except Exception as exc:
            errors.append(type(exc).__name__)
        if len(answers) >= 3:
            break
    return {"answers": answers, "errors": errors}
