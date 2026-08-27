"""Upkeep: keep cases in step with send work people decided on the Work items page."""
import sys
from pathlib import Path

_LIB = Path(__file__).resolve().parents[1] / "lib"
if str(_LIB) not in sys.path:
    sys.path.insert(0, str(_LIB))

from hubzoid import workflow  # noqa: E402

from customer_desk import sync  # noqa: E402


@workflow("every 1 minute")
def desk_sync():
    """Move cases whose send was rejected, cancelled or left uncertain to the right state."""
    from hubzoid.workflows.context import _ctx

    return {"changed": sync.sync_sends(Path(_ctx().hub_dir))}
