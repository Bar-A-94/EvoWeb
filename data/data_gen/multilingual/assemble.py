#!/usr/bin/env python3
"""Merge translation parts into data/multilingual/evoweb_benchmark_<lang>.jsonl.

Starts from the EN row and swaps ONLY the 10 instructions plus the listed task edits,
so metadata and untouched tasks are byte-identical to the EN set by construction.
Row order (and therefore --start-idx / sample index) matches evoweb_benchmark.jsonl exactly.
Refuses to write a language whose parts fail validate_parts.py.

Usage: python3 assemble.py [--enui] [--out-dir DIR] [lang ...]
"""

import copy
import json
import subprocess
import sys
from pathlib import Path

ML = Path(__file__).resolve().parent
_PKG = ML.parents[2]
if str(_PKG) not in sys.path:
    sys.path.insert(0, str(_PKG))
from evoweb.paths import BENCHMARK, LANGS, MULTILINGUAL, ensure_data  # noqa: E402


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
    # tasks) -> evoweb_benchmark_<lang>.jsonl
    enui = True  # only the English-UI variant ships; --enui is accepted and implied
    # --out-dir <dir>: write the jsonl files there instead of data/multilingual
    # (so a reproduction check never touches the committed copies).
    out_dir = Path(argv[argv.index("--out-dir") + 1]) if "--out-dir" in argv else None
    if out_dir is not None:
        del argv[argv.index("--out-dir") : argv.index("--out-dir") + 2]
        out_dir.mkdir(parents=True, exist_ok=True)
    langs = [a for a in argv if a != "--enui"] or LANGS
    suffix = "_enui" if enui else ""
    ensure_data(BENCHMARK)
    src = BENCHMARK
    rows = [json.loads(line) for line in src.open(encoding="utf-8")]
    check = [sys.executable, str(ML / "validate_parts.py")] + (["--enui"] if enui else [])
    if subprocess.run(check).returncode:
        sys.exit("validate_parts.py failed; not assembling")
    for lang in langs:
        out = (out_dir or MULTILINGUAL) / f"evoweb_benchmark_{lang}.jsonl"
        lines = []
        for row in rows:
            part = json.loads(
                (ML / "parts" / row["id"] / f"{lang}{suffix}.json").read_text(encoding="utf-8")
            )
            lines.append(json.dumps(apply(row, part), ensure_ascii=False))
        out.write_text("\n".join(lines) + "\n", encoding="utf-8")
        print("wrote", out)
