"""Upkeep: keep cases in step with send work people decided on the Work items page, and case pages
shared with exactly the people who hold a desk role now."""
import sys
from pathlib import Path

_LIB = Path(__file__).resolve().parents[1] / "lib"
if str(_LIB) not in sys.path:
    sys.path.insert(0, str(_LIB))

from hubzoid import workflow  # noqa: E402

from customer_desk import flows, sync  # noqa: E402


@workflow("every 1 minute")
def desk_sync():
    """Move cases whose send was rejected, cancelled or left uncertain to the right state, reshare case
    pages when desk roles change, and republish a case page after its case changed."""
    from hubzoid.workflows.context import _ctx

    hub_dir = Path(_ctx().hub_dir)
    return {"changed": sync.sync_sends(hub_dir),
            "pages": flows.refresh_pages_if_readers_changed(hub_dir, flows.start_work(hub_dir)),
            "changed_pages": flows.refresh_changed_pages(hub_dir, flows.start_work(hub_dir))}
