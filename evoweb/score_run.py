#!/usr/bin/env python3
"""Score one or more of your runs exactly like the paper.

    python3 -m evoweb.score_run runs/<run-id> [runs/<other-run> ...]

Prints Grade, Survival and turns per request, with the number of apps the run holds: a smoke
run of a few apps is scored over those apps alone. To compare a full run with the paper's
released runs of the same model, use evoweb.compare_to_released.
"""

from __future__ import annotations

import argparse
import os
import statistics as st
import tempfile
from pathlib import Path


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument(
        "runs", nargs="+", type=Path, help="run directories: <run>/<sample>/result.json"
    )
    a = ap.parse_args()
    # metrics looks runs up under TRACES; point it at a directory of links to the given runs.
    with tempfile.TemporaryDirectory() as tmp:
        os.environ["EVOWEB_TRACES"] = tmp
        for r in a.runs:
            (Path(tmp) / r.name).symlink_to(r.resolve(), target_is_directory=True)
        from evoweb import metrics

        expected = metrics.expected_tasks()
        print("| run | apps | Grade | Survival | Turns / request |")
        print("|---|---|---|---|---|")
        for r in a.runs:
            ladders = metrics.load_ladders(r.name, expect=None)
            sc = metrics.run_scores(ladders, {app: expected[app] for app in ladders})
            calls = metrics.run_call_counts(r.name)
            turns = st.mean(calls) if calls else 0.0
            print(
                f"| {r.name} | {len(ladders)} | {sc['grade']:.3f} | {sc['survival']:.2f} | "
                f"{turns:.1f} |"
            )


if __name__ == "__main__":
    main()
