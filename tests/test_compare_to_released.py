"""evoweb.compare_to_released on the shipped Haiku re-run (examples_artifacts/reproductions/haiku-4.5-rerun).

The tool scores a run exactly like the paper and compares it with the released runs of the same
model. Here it must reproduce the published re-run numbers (examples_artifacts/reproductions/haiku-4.5-rerun_compare.json)
and leave traces/ untouched.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUN = ROOT / "examples_artifacts" / "reproductions" / "haiku-4.5-rerun"


def test_compare_haiku_rerun_with_the_released_runs(tmp_path):
    from evoweb.paths import TRACES, ensure_traces

    ensure_traces()
    before = sorted(p.name for p in TRACES.iterdir())
    out = tmp_path / "compare.json"
    r = subprocess.run(
        [
            sys.executable,
            "-m",
            "evoweb.compare_to_released",
            "Haiku 4.5",
            str(RUN),
            "--json",
            str(out),
        ],
        capture_output=True,
        text=True,
        cwd=ROOT,
    )
    assert r.returncode == 0, r.stdout[-2000:] + r.stderr[-2000:]
    d = json.loads(out.read_text())

    fresh = d["scalars"][RUN.name]
    assert round(fresh["grade"], 3) == 0.372
    assert round(fresh["survival"], 2) == 4.34
    assert round(fresh["turns_per_request"], 1) == 12.4
    # the released Haiku runs give the paper's row: 0.377 +- 0.014
    assert round(d["released_grade"]["mean"], 3) == 0.377
    assert round(d["released_grade"]["std"], 3) == 0.014
    # within two standard deviations of the paper's mean, with no errored request
    assert abs(fresh["grade"] - d["released_grade"]["mean"]) <= 2 * d["released_grade"]["std"]
    assert d["errors"] == []
    assert len(d["per_app"]) == 32
    # the tool links the run into traces/ only while it runs
    assert sorted(p.name for p in TRACES.iterdir()) == before
