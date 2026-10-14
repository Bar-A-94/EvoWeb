#!/usr/bin/env python3
"""How many steps the WebVoyager judge took per check, by model and check type.

NEEDS THE RAW JUDGE LOGS, which are NOT part of the released traces: pass --logs-root pointing
at a tree that holds, per run,
    <logs-root>/<run-id>/<sample>/turnN/eval/results/task<sample>_<task_idx>/agent.log
(the layout of the original S3 bucket). The verdicts themselves come from the released
result.json files under paths.TRACES.

Companion to dag_slot.py: same arms (the paper setup that reproduces Table 4), same
four-way check split (functional / integration / global_rule / backward). For every judged
follow-up check (R2-R10) it counts the `Iter: k` lines of the judge transcript. One iteration
= one judge LLM call = one browser action, except the last one, which is normally the ANSWER.
The judge runs with --max_iter 20; on the 20th iteration it is forced to answer, so "hit the
cap" means 20 iterations. Its prompt tells it a softer budget of 15 interactions, so the share
of checks that went past 15 is reported too.

Usage (from anywhere):
    python3 ablations/dag/judge_steps_dag.py --logs-root /path/to/raw/logs
    python3 ablations/dag/judge_steps_dag.py --logs-root ... --by-verdict   # split the mean / %cap
                                                              # tables by the check's verdict
"""

from __future__ import annotations

import argparse
import json
import os
import re
import statistics as st
import sys
from collections import defaultdict
from pathlib import Path

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.abspath(os.path.join(_HERE, "..", "..")))
sys.path.insert(0, _HERE)
import dag_slot as d  # noqa: E402

from evoweb.metrics import check_group  # noqa: E402

MAX_ITER = 20  # --max_iter passed to webvoyager/run.py
SOFT_LIMIT = 15  # what the judge prompt tells it
ITER_RE = re.compile(r"^\S+ \S+ - INFO - Iter: (\d+)$", re.M)
GROUPS = d.G4


def iterations(log_path):
    """Number of judge iterations in one agent.log, or None if the file is missing."""
    if not log_path.is_file():
        return None
    hits = ITER_RE.findall(log_path.read_text(errors="replace"))
    return len(hits) if hits else None


def collect(model, logs_root: Path):
    """{group: [(iterations, verdict) per judged check]}, plus (judged, with_log) coverage."""
    per = defaultdict(list)
    judged = with_log = 0
    for rid in d.ARMS[model]:
        tree = logs_root / rid
        for f in d.results(d.run_dir(rid)):
            r = json.load(open(f))
            idx = int(r["index"])
            sample = tree / f"{idx:06d}"
            for req in r.get("turns", []):  # result.json keeps the key "turns" (one per request)
                rn = req.get("turn")
                if not rn or rn < 2:
                    continue
                for t in req.get("tasks", []):
                    if t.get("verdict") not in d.VERDICT_W:
                        continue
                    g = check_group(idx, rn, t.get("task_idx"), d.GLOBAL_RULE_REQUESTS)
                    if g is None:
                        continue
                    judged += 1
                    n = iterations(
                        sample
                        / f"turn{rn}"  # log directories keep the turnN name
                        / "eval"
                        / "results"
                        / f"task{idx:06d}_{t['task_idx']}"
                        / "agent.log"
                    )
                    if n is None:
                        continue
                    with_log += 1
                    per[g].append((n, t["verdict"]))
    return per, judged, with_log


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--logs-root",
        required=True,
        type=Path,
        help="tree holding <run-id>/<sample>/turnN/eval/results/*/agent.log",
    )
    ap.add_argument(
        "--by-verdict",
        action="store_true",
        help="split the mean / %%cap table by verdict (no / yes / partial)",
    )
    a = ap.parse_args()
    if not a.logs_root.is_dir():
        sys.exit(f"--logs-root {a.logs_root} is not a directory")

    rows = {m: collect(m, a.logs_root) for m in d.TABLE_MODELS}
    if not any(r[2] for r in rows.values()):
        sys.exit(f"no agent.log found under {a.logs_root}; this script needs the raw judge logs")

    def table(title, fn, fmt, verdicts=None):
        """One markdown table; `verdicts` restricts to checks with those verdicts."""
        print(f"\n== {title} ==\n")
        print("| model | " + " | ".join(GROUPS) + " | all |")
        print("|---|" + "---|" * (len(GROUPS) + 1))
        col = defaultdict(list)
        for m in d.TABLE_MODELS:
            per = rows[m][0]
            cells = []
            for g in GROUPS + ("all",):
                pairs = per[g] if g != "all" else [x for g2 in GROUPS for x in per[g2]]
                v = [n for n, vd in pairs if verdicts is None or vd in verdicts]
                if not v:
                    cells.append("--")
                    continue
                val = fn(v)
                col[g].append(val)
                cells.append(fmt(val))
            print(f"| {m} | " + " | ".join(cells) + " |")

        def avg(vals):  # plain numbers or tuples (component-wise)
            if isinstance(vals[0], tuple):
                return tuple(st.mean(c) for c in zip(*vals))
            return st.mean(vals)

        print(
            "| **AVG** | "
            + " | ".join(f"**{fmt(avg(col[g]))}**" if col[g] else "--" for g in GROUPS + ("all",))
            + " |"
        )

    if a.by_verdict:

        def cap(v):
            return sum(x >= MAX_ITER for x in v) / len(v) * 100

        for label, vds in (
            ("verdict NO (score 0)", ("no",)),
            ("verdict YES (score 1)", ("yes",)),
            ("verdict PARTIAL (score 0.5)", ("partial",)),
        ):
            table(
                f"{label}: mean iterations / % at the hard cap ({MAX_ITER})",
                lambda v: (st.mean(v), cap(v)),
                lambda t: f"{t[0]:.1f} / {t[1]:.1f}%",
                verdicts=vds,
            )
            table(f"{label}: number of checks", len, lambda v: f"{v:.0f}", verdicts=vds)
        return

    table(
        "mean judge iterations per check (LLM calls; the last is normally the ANSWER)",
        st.mean,
        lambda v: f"{v:.2f}",
    )
    table(
        f"% of checks that hit the hard cap ({MAX_ITER} iterations, forced verdict)",
        lambda v: sum(x >= MAX_ITER for x in v) / len(v) * 100,
        lambda v: f"{v:.1f}",
    )
    table(
        f"% of checks that went past the {SOFT_LIMIT}-interaction budget the prompt states "
        f"(> {SOFT_LIMIT + 1} iterations)",
        lambda v: sum(x > SOFT_LIMIT + 1 for x in v) / len(v) * 100,
        lambda v: f"{v:.1f}",
    )

    print("\n== coverage: judged follow-up checks with a judge log ==\n")
    print("| model | judged | with log | % |")
    print("|---|---|---|---|")
    for m in d.TABLE_MODELS:
        _, judged, with_log = rows[m]
        print(f"| {m} | {judged} | {with_log} | {with_log / judged * 100:.1f} |")


if __name__ == "__main__":
    main()
