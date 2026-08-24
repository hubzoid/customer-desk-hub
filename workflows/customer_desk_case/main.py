"""Attended work on one case: save the exact reply as a real draft, or send
it after the person who asked approves it on the Work items page."""
import sys
from pathlib import Path

_LIB = Path(__file__).resolve().parents[1] / "lib"
if str(_LIB) not in sys.path:
    sys.path.insert(0, str(_LIB))

from hubzoid import workflow  # noqa: E402
from customer_desk import flows  # noqa: E402
from customer_desk.routes import DRAFT, SEND  # noqa: E402


@workflow(work_items={"send": SEND, "draft": DRAFT})
def customer_desk_case():
    """Save a reply draft, or send a reply its requester approved."""
    return flows.case_item()
