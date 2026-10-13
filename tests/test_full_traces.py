"""The full-trace run unpacks to the released verdicts and scores identically."""

import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUN = "fable-5-run1"
ZIP = ROOT / "examples_artifacts" / "full_traces" / f"{RUN}.zip"


def test_zip_under_github_limit_holds_all_apps_and_no_images():
    assert ZIP.stat().st_size < 100_000_000
    with zipfile.ZipFile(ZIP) as z:
        names = z.namelist()
    assert all(n.startswith(RUN + "/") for n in names)
    assert not any(n.endswith(".png") or n.endswith("eval_report.html") for n in names)
    apps = {n.split("/")[1] for n in names if n.count("/") >= 2}
    assert len(apps) == 32
    for app in apps:
        assert f"{RUN}/{app}/result.json" in names
        for t in range(1, 11):
            turn = f"{RUN}/{app}/" + ("" if t == 1 else f"turn{t}/")
            assert (
                f"{turn}generation/trajectory.jsonl" in names
                or f"{turn}checkpoint/state.json" in names
            ), turn
        assert f"{RUN}/{app}/turn10/eval/tasks.jsonl" in names


def test_score_zip_matches_released(tmp_path):
    r = subprocess.run(
        [sys.executable, "-m", "evoweb.score_zip", RUN, "--into", str(tmp_path)],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert r.returncode == 0, r.stdout + r.stderr
    rows = [line for line in r.stdout.splitlines() if line.startswith(f"| {RUN}")]
    assert len(rows) == 2
    cells = [row.split("|")[2:6] for row in rows]
    assert cells[0] == cells[1], rows
