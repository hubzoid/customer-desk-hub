"""Install this hub's files into a hub folder, for example a copy of a test hub.

    python scripts/install.py TARGET [--replace-agents]

It copies the hub files (not .git, .venv, tests or runtime state), keeps the
target's .env, and refuses to replace an existing AGENTS.md unless asked.
"""
from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FILES = ["scripts", "skills", "freshdesk-app", "AGENTS.md", "settings.yaml", "hub.settings.yaml", "hub.manifest.yaml", "work-items.yaml", "hitl.yaml",
         "mcp-apps.yaml", "desk", "knowledge", "agents", "workflows", "tools_local", "restricted", "connectors",
         "cards", "identity", "doctor", "evals", ".claude", "channels", "docs", "requirements.txt", "requirements-sdk.txt", "ARCHITECTURE.md", "LICENSE", "NOTICE", "README.md"]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("target")
    ap.add_argument("--replace-agents", action="store_true")
    args = ap.parse_args()
    target = Path(args.target).resolve()
    target.mkdir(parents=True, exist_ok=True)
    if (target / "AGENTS.md").exists() and not args.replace_agents:
        print("The target already has AGENTS.md. Pass --replace-agents to install the Customer Desk over it.")
        return 2
    for name in FILES:
        src = ROOT / name
        if not src.exists():
            continue
        dst = target / name
        if src.is_dir():
            shutil.copytree(src, dst, dirs_exist_ok=True, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        else:
            shutil.copy2(src, dst)
    print(f"Installed the Customer Desk into {target}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
