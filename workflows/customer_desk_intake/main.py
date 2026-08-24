"""Triage: every customer message, and every rerun a person asks for,
becomes a case that is ready for a person. Unattended, never sends."""
import sys
from pathlib import Path

_LIB = Path(__file__).resolve().parents[1] / "lib"
if str(_LIB) not in sys.path:
    sys.path.insert(0, str(_LIB))

from hubzoid import workflow  # noqa: E402
from customer_desk import flows  # noqa: E402
from customer_desk.routes import TRIAGE  # noqa: E402


@workflow(work_items={"triage": TRIAGE}, timeout="30m")
def customer_desk_intake():
    """Read one customer message, bind it to a customer, read ERPNext and prepare a checked reply."""
    return flows.triage_item()
