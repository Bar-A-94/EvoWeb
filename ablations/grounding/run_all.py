#!/usr/bin/env python3
"""Recompute the grounding-ablation numbers (paper App. C.1) from the dataset files alone.

    python3 run_all.py            # every stage, writing into evoweb/paths.ARTIFACTS
    python3 run_all.py --check    # recompute into a scratch dir and diff against golden/
    python3 run_all.py --list     # the stage table

One stage, pure-python stdlib, seeded, reading only `data/`:

  ngram      invented_ngram_overlap.py  invented n-gram overlap, n=1..8     -> invented_ngram_overlap.json

The paper quotes n=4: grounding reduces the overlap between unrelated apps by 29%.

`--check` is the regression gate: it writes ONLY into a scratch directory and compares against the
committed golden/ files -- exactly, since every stage is seeded. Integer counts must always match
exactly (an off-by-one in "23/30 apps" is a bug, not noise). A --check failure means a change moved a
published number: revert it, do not re-baseline.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
PKG = os.path.abspath(os.path.join(HERE, "..", ".."))
if PKG not in sys.path:
    sys.path.insert(0, PKG)
from evoweb.paths import ARTIFACTS  # noqa: E402

GOLDEN = os.path.join(HERE, "golden")
ART = str(ARTIFACTS)
PY3 = sys.executable


class Stage:
    """One reproducible step. `out_flag` is how the script is told where to write, which is what
    makes --check able to redirect it away from the repo."""

    def __init__(self, name, argv, out, out_flag, note, tol="exact"):
        self.name, self.argv, self.out, self.out_flag, self.note, self.tol = (
            name,
            argv,
            out,
            out_flag,
            note,
            tol,
        )


STAGES = [
    Stage(
        "ngram",
        ["invented_ngram_overlap.py"],
        "invented_ngram_overlap.json",
        "--json",
        "invented n-gram overlap, n=1..8 (App. C.1 quotes n=4)",
    ),
]


def _load(p):
    with open(p) as fh:
        return json.load(fh)


def _diff(a, b, path="", tol=None, out=None):
    """Recursive compare. Ints must match exactly even under a float tolerance -- they are counts
    (apps, n, K) where an off-by-one is a real bug, not numerical noise."""
    out = [] if out is None else out
    if isinstance(a, dict) and isinstance(b, dict):
        for k in sorted(set(a) | set(b)):
            if k not in a or k not in b:
                out.append(f"{path}/{k}: {'missing in new' if k not in a else 'missing in old'}")
            else:
                _diff(a[k], b[k], f"{path}/{k}", tol, out)
    elif isinstance(a, list) and isinstance(b, list):
        if len(a) != len(b):
            out.append(f"{path}: length {len(a)} vs {len(b)}")
        else:
            for i, (x, y) in enumerate(zip(a, b)):
                _diff(x, y, f"{path}[{i}]", tol, out)
    elif isinstance(a, bool) or isinstance(b, bool) or isinstance(a, int) and isinstance(b, int):
        if a != b:
            out.append(f"{path}: {a} vs {b}")
    elif isinstance(a, (int, float)) and isinstance(b, (int, float)):
        if a != a and b != b:
            return out  # NaN == NaN for our purposes
        lim = 0.0 if tol in (None, "exact") else tol
        if not math.isclose(a, b, rel_tol=lim, abs_tol=lim):
            out.append(f"{path}: {a} vs {b}")
    elif a != b:
        out.append(f"{path}: {a!r} vs {b!r}")
    return out


def run(stage, check_dir=None):
    """Execute one stage. In check mode its output is redirected into check_dir and diffed vs golden/."""
    out_dir = check_dir or ART
    os.makedirs(out_dir, exist_ok=True)
    target = os.path.join(out_dir, stage.out)
    r = subprocess.run(
        [PY3] + list(stage.argv) + [stage.out_flag, target],
        cwd=HERE,
        capture_output=True,
        text=True,
    )
    if r.returncode != 0:
        tail = (r.stderr or r.stdout).strip().splitlines()[-3:]
        return False, "\n      ".join(tail)
    if check_dir:
        golden = os.path.join(GOLDEN, stage.out)
        if not os.path.exists(golden):
            return True, "no golden baseline (new artifact)"
        diffs = _diff(_load(target), _load(golden), tol=stage.tol)
        if diffs:
            return False, f"{len(diffs)} value(s) differ:\n      " + "\n      ".join(diffs[:6])
        return (
            True,
            f"matches golden/{stage.out} ({'exact' if stage.tol == 'exact' else stage.tol})",
        )
    return True, f"wrote {target}"


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument(
        "--check", action="store_true", help="recompute into a scratch dir and diff vs golden/"
    )
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--only", help="comma-separated stage names")
    a = ap.parse_args()

    sel = STAGES
    if a.only:
        want = {x.strip() for x in a.only.split(",")}
        sel = [s for s in sel if s.name in want]

    if a.list:
        print(f"{'stage':11}{'writes':34}notes")
        print("-" * 90)
        for s in STAGES:
            print(f"{s.name:11}{s.out:34}{s.note}")
        print(
            f"\nall stages: {PY3}, stdlib only. Outputs go to {ART}; --check compares with {GOLDEN}."
        )
        return 0

    check_dir = tempfile.mkdtemp(prefix="evoweb-grounding-check-") if a.check else None
    if a.check:
        print(f"--check: recomputing into {check_dir} (nothing under the package is written to)\n")

    ran = failed = 0
    for s in sel:
        ok, msg = run(s, check_dir)
        print(f"{'ok  ' if ok else 'FAIL'}  {s.name:11} {msg}")
        ran += ok
        failed += not ok
    if check_dir:
        shutil.rmtree(check_dir, ignore_errors=True)

    print(f"\nran {ran} · failed {failed}")
    if failed:
        print(
            "A --check failure means a change moved a published number. Revert it; do not re-baseline."
        )
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
