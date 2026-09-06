"""Run this hub on the real Hubzoid workflow engine in a child process, the
way the bridge does, with the scripted stations. The test process drives it
through the same service calls the chat tools and the CLI use."""
from __future__ import annotations

import os
import signal
import subprocess
import sys
import textwrap
import time
from pathlib import Path

OWNER = "admin@localhost"

ENGINE = textwrap.dedent('''
    import sys, time
    from pathlib import Path
    from hubzoid.workflows import runtime
    runtime.init(sys.argv[1], hub_name=Path(sys.argv[1]).name)
    runtime.load_workflows(sys.argv[1])
    runtime.launch()
    runtime._OWNER.heartbeat(runtime.ready_record())
    print("READY", flush=True)
    stop = Path(sys.argv[2])
    beat = time.time()
    while not stop.exists():
        time.sleep(0.2)
        if time.time() - beat > 5:
            runtime._OWNER.heartbeat(runtime.ready_record())
            beat = time.time()
    runtime.shutdown()
''')


class Engine:
    def __init__(self, hub: Path, tmp: Path, env: dict | None = None):
        self.hub, self.stop = hub, tmp / f"stop-{time.time_ns()}"
        script = tmp / "engine.py"
        script.write_text(ENGINE)
        self.log = tmp / f"engine-{time.time_ns()}.log"
        self.out = self.log.open("w")
        full = {**os.environ, "DESK_SCRIPTED_STATIONS": "1", **(env or {})}
        self.proc = subprocess.Popen([sys.executable, str(script), str(hub), str(self.stop)], stdout=subprocess.PIPE,
                                     stderr=self.out, text=True, env=full)
        deadline = time.time() + 90
        while time.time() < deadline:
            line = self.proc.stdout.readline()
            if line.startswith("READY"):
                return
            if not line and self.proc.poll() is not None:
                break
        raise RuntimeError("the engine did not start: " + self.log.read_text()[-3000:])

    def kill(self):
        self.proc.send_signal(signal.SIGKILL)
        self.proc.wait(10)

    def close(self):
        self.stop.write_text("1")
        try:
            self.proc.wait(30)
        except subprocess.TimeoutExpired:
            self.kill()
        self.out.close()


def wait_item(hub, item_id, states, timeout=90):
    from hubzoid.work_items import store

    deadline = time.time() + timeout
    while time.time() < deadline:
        item = store.get_item(hub, item_id)
        if item["state"] in states:
            return item
        time.sleep(0.3)
    raise AssertionError(f"work item stayed {store.get_item(hub, item_id)['state']}: "
                         f"{store.get_item(hub, item_id).get('reason')}")


def wait_case(hub, number, states, timeout=90):
    from customer_desk import store, sync

    deadline = time.time() + timeout
    while time.time() < deadline:
        sync.sync_sends(hub)
        c = store.get_case(store.connect(hub), number)
        if c and c["state"] in states:
            return c
        time.sleep(0.3)
    c = store.get_case(store.connect(hub), number)
    raise AssertionError(f"{number} stayed {c and c['state']}: {c and c.get('note')}")


def waiting_op(hub, item_id, timeout=60):
    from hubzoid.work_items import store

    deadline = time.time() + timeout
    while time.time() < deadline:
        ops = [o for o in store.list_ops(hub, Path(hub).name.lower(), item_id=item_id)
               if o["state"] == "awaiting_approval"]
        if ops:
            return ops[0]
        time.sleep(0.3)
    raise AssertionError("no operation waiting for approval")
