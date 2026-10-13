#!/usr/bin/env python3
"""Assemble a ladder dataset from per-sample part files. Deterministic, no agent involved.

The generator workflows delegate assembly to an agent that writes a throwaway Python script. That
step is pure mechanical I/O with nothing to reason about, and making it an agent call means a session
limit or provider blip destroys the output of a completed multi-hour generation run — which is exactly
what happened twice on 2026-08-04. This does the same merge locally and idempotently, so assembly can
be re-run any time from the parts on disk.

Merge rule: for every CLEAN index take that app's row of the base dataset (data/legacy_webgen_bench_apps.jsonl, the
101 WebGen-Bench apps) and copy the part's follow_ups plus its audit metadata onto it. Only those
rows are written, in app order; the row position is the sample index every run and score uses.

Usage:
  python3 assemble_dataset.py --parts <dir> --out <out.jsonl> --clean 4,14,17,... [--base data/legacy_webgen_bench_apps.jsonl]
  python3 assemble_dataset.py --parts <dir> --out <out.jsonl> --clean-from-audit   # trust audit_parts.py
  python3 assemble_dataset.py --parts data/evoweb_main_dataset --out x.jsonl --clean <32 ids>   # = evoweb_benchmark.jsonl
"""

from __future__ import annotations

import argparse
import json
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_PKG = os.path.abspath(os.path.join(_HERE, "..", ".."))
if _PKG not in sys.path:
    sys.path.insert(0, _PKG)
from evoweb.paths import DATA as _DATA

DEFAULT_BASE = os.path.join(str(_DATA), "legacy_webgen_bench_apps.jsonl")
# Audit metadata copied onto each populated row. The harness ignores unknown top-level fields; the
# dataset viewers read them.
META_FIELDS = (
    "target_app_summary",
    "dependency_graph",
    "feature_roster",
    "global_rules",
    "pinned_seed",
)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--parts", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--base", default=DEFAULT_BASE)
    ap.add_argument("--clean", default=None, help="comma-separated indices to include")
    ap.add_argument(
        "--clean-from-audit",
        action="store_true",
        help="include every part that passes audit_parts.py (mechanical rules only)",
    )
    a = ap.parse_args()

    if a.clean_from_audit:
        sys.path.insert(0, _HERE)
        from audit_parts import audit, load_base  # noqa: E402

        variant = "nogrounding" if "no_grounding" in a.parts or "nogrounding" in a.parts else "dag"
        base_tasks = load_base(a.base)
        clean = []
        for f in sorted(os.listdir(a.parts)):
            if not f.endswith(".json"):
                continue
            part = json.load(open(os.path.join(a.parts, f)))
            vv, _ = audit(part, base_tasks, variant)
            if not vv:
                clean.append(part.get("app_idx"))
    elif a.clean:
        clean = [int(x) for x in a.clean.split(",") if x.strip()]
    else:
        ap.error("pass --clean or --clean-from-audit")

    clean = sorted(set(clean))
    rows = [json.loads(line) for line in open(a.base) if line.strip()]
    if len(rows) != 101:
        print(f"WARNING: base has {len(rows)} rows, expected 101")

    written, skipped, bad = [], [], []
    for i, row in enumerate(rows, start=1):
        if i not in clean:
            continue
        p = os.path.join(a.parts, f"{i:06d}.json")
        try:
            part = json.load(open(p))
        except Exception as e:
            bad.append(f"{i} ({e})")
            continue
        fus = part.get("follow_ups") or []
        if len(fus) != 9:
            bad.append(f"{i} (has {len(fus)} follow_ups, expected 9)")
            continue
        row["follow_ups"] = fus
        for k in META_FIELDS:
            if k in part:
                row[k] = part[k]
        written.append(i)

    with open(a.out, "w") as fh:
        for i, row in enumerate(rows, start=1):
            if i in written:
                fh.write(json.dumps(row) + "\n")

    skipped = [i for i in clean if i not in written]
    tasks = [
        len(f["ui_instruct"])
        for i, r in enumerate(rows, 1)
        if r.get("follow_ups")
        for f in r["follow_ups"]
    ]
    print(f"wrote {a.out}")
    print(f"  rows: {len(written)}   requested clean: {len(clean)}")
    print(f"  indices: {written}")
    if skipped:
        print(f"  NOT written (requested but unusable): {skipped}")
    if bad:
        print(f"  problems: {'; '.join(bad)}")
    if tasks:
        print(
            f"  follow-up task counts: min {min(tasks)} max {max(tasks)} "
            f"(expect 5 everywhere: {'OK' if set(tasks) == {5} else 'MISMATCH'})"
        )
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
