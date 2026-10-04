"""Compare the vendored ERP module with its canonical commit.

    python scripts/check_vendored_erp.py ../order-invoice-desk-hub

Reads the source commit from workflows/lib/erp/VENDORED.md, exports that
commit's erp/ with git, and compares every file byte for byte. Prints each
difference and exits 1 if there is any. The write contract (write.py,
digest.py, bootstrap.py) must be absent here and present there.
"""
from __future__ import annotations

import io
import re
import subprocess
import sys
import tarfile
from pathlib import Path

HUB = Path(__file__).resolve().parents[1]
ERP = HUB / "workflows" / "lib" / "erp"
LEFT_OUT = {"write.py", "digest.py", "bootstrap.py"}


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(__doc__)
        return 2
    source = Path(argv[1]).resolve()
    commit = re.search(r"Source commit \| `([0-9a-f]{40})`", (ERP / "VENDORED.md").read_text()).group(1)
    archive = subprocess.run(["git", "-C", str(source), "archive", commit, "erp"], capture_output=True, check=True)
    canonical = {}
    with tarfile.open(fileobj=io.BytesIO(archive.stdout)) as tar:
        for m in tar.getmembers():
            if m.isfile():
                canonical[m.name.removeprefix("erp/")] = tar.extractfile(m).read()
    ours = {p.relative_to(ERP).as_posix(): p.read_bytes() for p in ERP.rglob("*")
            if p.is_file() and p.name != "VENDORED.md" and "__pycache__" not in p.parts}
    problems = []
    for name in sorted(set(canonical) | set(ours)):
        if name in LEFT_OUT:
            if name in ours:
                problems.append(f"{name}: the write contract must not be vendored")
            continue
        if name not in ours:
            problems.append(f"{name}: missing from the vendored copy")
        elif name not in canonical:
            problems.append(f"{name}: not in the canonical commit")
        elif ours[name] != canonical[name]:
            problems.append(f"{name}: differs from {commit[:7]}")
    for p in problems:
        print(p)
    print(f"{len(ours)} files compared with {commit[:7]}: " + ("identical" if not problems else
                                                              f"{len(problems)} differences"))
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
