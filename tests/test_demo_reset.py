"""demo/reset runs the desk CLI with the right interpreter, and refuses live mode."""
from __future__ import annotations

import os
import shutil
import subprocess
import sys

from conftest import HUB


def _copy_scripts(hub):
    for name in ("demo", "scripts"):
        shutil.copytree(HUB / name, hub / name, ignore=shutil.ignore_patterns("__pycache__"))
    shutil.copy2(HUB / "desk", hub / "desk")


def _reset(hub):
    env = dict(os.environ, DESK_PYTHON=sys.executable)
    return subprocess.run([str(hub / "demo" / "reset")], cwd=hub, env=env, capture_output=True, text=True,
                          timeout=120)


def test_reset_works_in_sample_mode(hub):
    _copy_scripts(hub)
    done = _reset(hub)
    assert done.returncode == 0, done.stderr
    assert "Sample namespace reset" in done.stdout


def test_reset_refuses_live_mode(hub):
    _copy_scripts(hub)
    settings = hub / "hub.settings.yaml"
    settings.write_text(settings.read_text().replace("DESK_MODE: sample", "DESK_MODE: live"))
    done = _reset(hub)
    assert done.returncode != 0
    assert "only in sample mode" in done.stdout + done.stderr
