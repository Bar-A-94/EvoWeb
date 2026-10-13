#!/usr/bin/env python3
"""Merge translation parts into data/multilingual/evoweb_benchmark_<lang>.jsonl.

Starts from the EN row and swaps ONLY the 10 instructions plus the listed task edits,
so metadata and untouched tasks are byte-identical to the EN set by construction.
Row order (and therefore --start-idx / sample index) matches evoweb_benchmark.jsonl exactly.
Refuses to write a language whose parts fail validate_parts.py.

Usage: python3 assemble.py [--enui] [--out-dir DIR] [lang ...]
"""

import copy
import hashlib
import json
import subprocess
import sys
from datetime import date
from pathlib import Path

ML = Path(__file__).resolve().parent
_PKG = ML.parents[2]
if str(_PKG) not in sys.path:
    sys.path.insert(0, str(_PKG))
from evoweb.paths import BENCHMARK, MULTILINGUAL  # noqa: E402

LANGS = ["es", "zh", "he", "hi", "sw", "de", "fr"]


def apply(row: dict, part: dict) -> dict:
    out = copy.deepcopy(row)
    out["instruction"] = part["instructions"]["1"]
    for i, f in enumerate(out.get("follow_ups", []), start=2):
        f["instruction"] = part["instructions"][str(i)]
    for e in part.get("task_edits", []):
        tasks = (
            out["ui_instruct"]
            if e["turn"] == 1
            else out["follow_ups"][e["turn"] - 2]["ui_instruct"]
        )
        tasks[e["task_index"]]["task"] = e["task"]
        tasks[e["task_index"]]["expected_result"] = e["expected_result"]
    return out


if __name__ == "__main__":
    argv = sys.argv[1:]
    # --enui: the English-UI variant (translated instructions, EN anchors, untouched
    # tasks) -> evoweb_benchmark_<lang>.jsonl + manifest_enui.json
    enui = True  # only the English-UI variant ships; --enui is accepted and implied
    # --out-dir <dir>: write the jsonl files and the manifest there instead of data/multilingual / this directory
    # (so a reproduction check never touches the committed copies).
    out_dir = Path(argv[argv.index("--out-dir") + 1]) if "--out-dir" in argv else None
    if out_dir is not None:
        del argv[argv.index("--out-dir") : argv.index("--out-dir") + 2]
        out_dir.mkdir(parents=True, exist_ok=True)
    langs = [a for a in argv if a != "--enui"] or LANGS
    suffix = "_enui" if enui else ""
    src = BENCHMARK
    rows = [json.loads(line) for line in src.open()]
    check = [sys.executable, str(ML / "validate_parts.py")] + (["--enui"] if enui else [])
    if subprocess.run(check).returncode:
        sys.exit("validate_parts.py failed; not assembling")
    manifest = {
        "parent": src.name,
        "parent_sha256": hashlib.sha256(src.read_bytes()).hexdigest(),
        "date": date.today().isoformat(),
        "translator": "claude-opus (workflow evoweb-translate" + ("-enui)" if enui else ")"),
        "files": {},
    }
    for lang in langs:
        out = (out_dir or MULTILINGUAL) / f"evoweb_benchmark_{lang}.jsonl"
        lines = []
        for row in rows:
            part = json.loads((ML / "parts" / row["id"] / f"{lang}{suffix}.json").read_text())
            lines.append(json.dumps(apply(row, part), ensure_ascii=False))
        out.write_text("\n".join(lines) + "\n")
        manifest["files"][out.name] = {
            "sha256": hashlib.sha256(out.read_bytes()).hexdigest(),
            "rows": len(lines),
        }
        print("wrote", out)
    mpath = (out_dir or ML) / f"manifest{suffix}.json"
    mpath.write_text(json.dumps(manifest, indent=1) + "\n")
    print("wrote", mpath)
