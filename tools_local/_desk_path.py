"""Put the desk library on the import path. Files starting with _ are not tool files."""
import sys
from pathlib import Path

HUB = Path(__file__).resolve().parents[1]
LIB = HUB / "workflows" / "lib"
if str(LIB) not in sys.path:
    sys.path.insert(0, str(LIB))
