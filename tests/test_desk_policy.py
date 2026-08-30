"""The policy file: schema, rule ids, gaps."""
from __future__ import annotations

import pytest

from customer_desk import policy


def test_policy_schema_and_rule_ids(hub):
    pol = policy.load(hub)
    assert pol.rules["R6"].startswith("We send a copy")
    assert pol.category("delivery_change")["min_notice_days"] == 2
    assert pol.digest.startswith("sha256:")


@pytest.mark.parametrize("edit, key", [
    ("within_days: 30", "within_days: 99999"),
    ("disclosure: exact, limited_below: null", "disclosure: band, limited_below: null"),
    ("overdue_action: ticket", "overdue_action: shout"),
])
def test_policy_rejects_bad_values_with_line(hub, edit, key):
    path = hub / "knowledge" / "desk-policy.md"
    path.write_text(path.read_text().replace(edit, key))
    with pytest.raises(policy.PolicyError) as exc:
        policy.load(hub)
    assert exc.value.problems[0]["line"]
    assert exc.value.code == "desk_policy_invalid"


def test_duplicate_rule_id_and_unknown_key(hub):
    path = hub / "knowledge" / "desk-policy.md"
    text = path.read_text().replace("- [R7]", "- [R6]").replace("version: 1\n", "version: 1\ncolour: blue\n", 1)
    path.write_text(text)
    with pytest.raises(policy.PolicyError) as exc:
        policy.load(hub)
    reasons = " ".join(p["reason"] for p in exc.value.problems)
    assert "Unknown key" in reasons and "Rule number used twice" in reasons


def test_policy_gaps_reported():
    text = "---\nversion: 1\nname: mine\ncategories:\n  order_status: {enabled: true}\n---\n- [R1] Be kind.\n"
    gaps = {g["key"]: g for g in policy.gaps(policy.parse(text))}
    assert "categories.delivery_change.min_notice_days" in gaps
    assert gaps["categories.delivery_change.min_notice_days"]["message"] == (
        "Your files do not say how many days notice a delivery change needs.")
    assert "reply.never_say" in gaps


def test_id_patterns_must_be_re2_compatible():
    text = "---\nversion: 1\nfacts:\n  id_patterns: ['(?<=x)SYN']\n---\n- [R1] x\n"
    with pytest.raises(policy.PolicyError):
        policy.parse(text)
