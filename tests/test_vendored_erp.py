"""The vendored ERP module is an exact copy of the canonical read parts.

Every file matches the SHA-256 recorded in erp/VENDORED.md, every dataset
file matches distributor-v1/manifest.json, nothing extra is there, and the
write contract is absent."""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

import pytest

ERP = Path(__file__).resolve().parents[1] / "workflows" / "lib" / "erp"
DATASET = ERP / "datasets" / "distributor-v1"


def _sha(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def _recorded() -> dict[str, str]:
    rows = re.findall(r"^\| `([^`]+)` \| `(sha256:[0-9a-f]{64})` \|$", (ERP / "VENDORED.md").read_text(), re.M)
    return dict(rows)


def _present() -> set[str]:
    return {p.relative_to(ERP).as_posix() for p in ERP.rglob("*")
            if p.is_file() and p.name != "VENDORED.md" and "__pycache__" not in p.parts}


def test_vendored_md_names_the_source_commit():
    text = (ERP / "VENDORED.md").read_text()
    assert re.search(r"Source commit \| `[0-9a-f]{40}`", text)


def test_every_vendored_byte_matches_the_record():
    recorded = _recorded()
    assert recorded, "VENDORED.md lists no files"
    assert _present() == set(recorded), "files added to or missing from the vendored copy"
    changed = [name for name, digest in recorded.items() if _sha(ERP / name) != digest]
    assert changed == [], f"edited in place: {changed}"


def test_the_dataset_matches_its_manifest():
    manifest = json.loads((DATASET / "manifest.json").read_text())
    files = manifest["files"]
    present = {p.relative_to(DATASET).as_posix() for p in DATASET.rglob("*")
               if p.is_file() and p.name != "manifest.json" and "__pycache__" not in p.parts}
    assert present == set(files)
    assert [n for n, digest in files.items() if _sha(DATASET / n) != digest] == []
    assert manifest["dataset"] == "distributor-v1" and manifest["synthetic"] is True


@pytest.mark.parametrize("name", ["write.py", "digest.py", "bootstrap.py"])
def test_the_write_contract_is_not_vendored(name):
    assert not (ERP / name).exists()


def test_the_read_parts_import_without_the_write_contract():
    import importlib

    for mod in ("erp.service", "erp.read", "erp.config", "erp.backends.sample", "erp.backends.frappe_rest",
                "erp.fake_server", "erp.doctor"):
        importlib.import_module(mod)
