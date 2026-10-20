"""Preview/apply file configuration for support. Run on a trusted builder host.

Does not connect providers, grant permissions or set secrets. OAuth/credential
entry and runtime approvals retain their existing human handoffs.
"""
from __future__ import annotations

import argparse
import difflib
import json
from pathlib import Path

import yaml


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--hub", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--provider", choices=("zoho_desk", "freshdesk"), required=True)
    parser.add_argument("--company", required=True)
    parser.add_argument("--department", required=True, help="Exact Zoho department or Freshdesk group id")
    parser.add_argument("--api-base", required=True)
    parser.add_argument("--erp", action="store_true", help="Explicitly enable the existing read-only ERP jobs")
    parser.add_argument("--apply", action="store_true", help="Apply after reviewing the preview on this trusted host")
    args = parser.parse_args()
    path = args.hub.resolve() / "hub.settings.yaml"
    before = path.read_text()
    data = yaml.safe_load(before)
    values = data.setdefault("values", {})
    values.update({"DESK_MODE": "live", "DESK_COMPANY": args.company, "DESK_CLOCK": "system",
                   "DESK_SUPPORT_ENABLED": True, "DESK_ERP_ENABLED": args.erp,
                   "DESK_HELPDESK": args.provider})
    # Select the supplied general vocabulary only when the existing choice is
    # still a stock file. Preserve an owner's custom category file.
    if values.get("DESK_KINDS_FILE", "knowledge/request-kinds.md") in (
            "knowledge/request-kinds.md", "knowledge/support-kinds.md"):
        values["DESK_KINDS_FILE"] = "knowledge/request-kinds.md" if args.erp else "knowledge/support-kinds.md"
    # Preserve existing live/shadow choices, user edits, secrets and grants.
    values.setdefault("DESK_HELPDESK_MODE", "dry-run")
    values.setdefault("DESK_HELPDESK_DRAFTS", False)
    if args.provider == "freshdesk":
        values.update({"FRESHDESK_API_BASE": args.api_base, "FRESHDESK_GROUP_ID": args.department})
    else:
        values.update({"ZOHO_DESK_API_BASE": args.api_base, "ZOHO_DESK_DEPARTMENT_ID": args.department})
    after = yaml.safe_dump(data, sort_keys=False)
    print("".join(difflib.unified_diff(before.splitlines(True), after.splitlines(True), fromfile=str(path), tofile=str(path))), end="")
    if args.apply and after != before:
        tmp = path.with_suffix(".yaml.tmp")
        tmp.write_text(after)
        tmp.replace(path)
    print(json.dumps({"applied": args.apply, "changed": before != after,
                      "next": "Add approved company articles, set provider secrets securely, run hub doctor, then desk ticket ID in dry-run."}))


if __name__ == "__main__":
    main()
