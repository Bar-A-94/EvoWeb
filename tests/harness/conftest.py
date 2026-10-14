"""Put PKG/harness on sys.path so the copied worker tests import the shipped code, not the internal repo."""

import sys
from pathlib import Path

PKG = Path(__file__).resolve().parents[2]
HARNESS = PKG / "harness"
if str(HARNESS) not in sys.path:
    sys.path.insert(0, str(HARNESS))
