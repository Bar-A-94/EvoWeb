#!/usr/bin/env python3
"""Split evoweb/paths.BENCHMARK (data/evoweb_benchmark.jsonl) into per-app parts for the translation workflow.

Each app gets parts/<id>/en.json (the full EN row, pretty-printed). The translation
agents write anchors.json + <lang>.json next to it; assemble.py merges them back.
"""

import json
import sys
from pathlib import Path

ML = Path(__file__).resolve().parent
_PKG = ML.parents[2]
if str(_PKG) not in sys.path:
    sys.path.insert(0, str(_PKG))
from evoweb.paths import BENCHMARK as DATA  # noqa: E402

if __name__ == "__main__":
    for line in DATA.open():
        row = json.loads(line)
        d = ML / "parts" / row["id"]
        d.mkdir(parents=True, exist_ok=True)
        (d / "en.json").write_text(json.dumps(row, indent=1, ensure_ascii=False) + "\n")
        print("wrote", d / "en.json")
