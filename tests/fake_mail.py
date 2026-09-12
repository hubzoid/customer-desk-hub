"""A fake SMTP server for engine tests of the Hubzoid email channel. The engine
child process installs it when DESK_TEST_FAKE_MAIL names a folder: every
message the channel sends is written there, so the test can read it."""
from __future__ import annotations

import json
import os
import time
from pathlib import Path


class FakeSmtp:
    def __init__(self, folder: Path):
        self.folder = folder

    def sendmail(self, frm, to, raw):
        n = len(list(self.folder.glob("sent-*.json"))) + 1
        (self.folder / f"sent-{n:03d}.json").write_text(json.dumps({"from": frm, "to": list(to),
                                                                     "raw": raw.decode("utf-8", "replace"),
                                                                     "at": time.time()}))

    def noop(self):
        return (250, b"ok")

    def quit(self):
        pass


def install() -> None:
    folder = os.environ.get("DESK_TEST_FAKE_MAIL")
    if not folder:
        return
    from hubzoid.channels.email import transports

    path = Path(folder)
    path.mkdir(parents=True, exist_ok=True)
    transports._smtp_connect = lambda conn: FakeSmtp(path)
