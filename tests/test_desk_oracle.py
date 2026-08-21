"""The twenty labelled sample requests reach the stated outcomes with the
scripted stations: the rules, facts, owner items and checks, without a model."""
from __future__ import annotations

import json

from conftest import load_sample, triage_envelope
from customer_desk import store


def test_twenty_requests_match_oracle(bound):
    hub = bound
    expected = json.loads((hub / "evals" / "expected" / "customer-desk-20.json").read_text())
    problems = []
    for env in load_sample(hub):
        exp = expected[env["provider_event_id"]]
        opened, result, _ = triage_envelope(hub, env)
        conn = store.connect(hub)
        case = store.get_case(conn, opened["case_id"])
        res = store.get_resolution(conn, case["id"], case["current_resolution"])
        reply = store.get_reply(conn, case["id"], case["current_reply"])
        got = [o["outcome"] for o in res["requests"]]
        cats = [o["category"] for o in res["requests"]]
        label = f"{case['number']} {env['provider_event_id']}"
        if case["number"] != exp["case_number"]:
            problems.append(f"{label}: number {case['number']}")
        if case["customer_id"] != exp["customer"]:
            problems.append(f"{label}: customer {case['customer_id']}")
        if cats != exp["categories"] or got != exp["outcomes"]:
            problems.append(f"{label}: {cats} {got} != {exp['categories']} {exp['outcomes']}")
        if case["queue"] != exp["queue"]:
            problems.append(f"{label}: queue {case['queue']} != {exp['queue']}")
        if not reply["checks"]["passed"]:
            problems.append(f"{label}: checks failed {[c for c in reply['checks']['results'] if c['status'] == 'fail']}")
        for text in exp.get("must_include", []):
            if text not in reply["rendered"]:
                problems.append(f"{label}: missing {text!r} in reply")
        for text in exp.get("must_not_include", []):
            if text.lower() in reply["rendered"].lower():
                problems.append(f"{label}: forbidden {text!r} in reply")
        names = [a["name"] for a in reply["attachments"]]
        if names != exp.get("attachments", []):
            problems.append(f"{label}: attachments {names}")
        tickets = store.case_tickets(conn, case["id"])
        if [t["owner_role"] for t in tickets] != [t["owner_role"] for t in exp.get("tickets", [])]:
            problems.append(f"{label}: tickets {[t['owner_role'] for t in tickets]}")
        props = store.case_proposals(conn, case["id"])
        if [(p["sales_order"], p["requested_date"]) for p in props] != [
                (p["sales_order"], p["requested_date"]) for p in exp.get("proposals", [])]:
            problems.append(f"{label}: proposals {props}")
        decs = store.case_decisions(conn, case["id"])
        if [(d["kind"], d["state"]) for d in decs] != [(d["kind"], d["state"]) for d in exp.get("decisions", [])]:
            problems.append(f"{label}: decisions {decs}")
    assert not problems, "\n".join(problems)
