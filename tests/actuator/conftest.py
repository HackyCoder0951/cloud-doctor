import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
for p in (ROOT / "invariants", ROOT / "actuator", ROOT / "policy", ROOT / "tests" / "invariants"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))
