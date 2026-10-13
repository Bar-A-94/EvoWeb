"""evoweb.score_run scores a run directory like the paper, full or partial."""

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RERUN = ROOT / "examples_artifacts" / "reproductions" / "haiku-4.5-rerun"


def score(run_dir):
    r = subprocess.run(
        [sys.executable, "-m", "evoweb.score_run", str(run_dir)],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert r.returncode == 0, r.stdout + r.stderr
    rows = [line for line in r.stdout.splitlines() if line.startswith(f"| {run_dir.name} ")]
    assert len(rows) == 1, r.stdout
    return [c.strip() for c in rows[0].split("|")[2:6]]


def test_full_run_scores_like_the_paper():
    assert score(RERUN) == ["32", "0.372", "4.34", "12.4"]


def test_partial_run_scores_its_apps_alone(tmp_path):
    part = tmp_path / "two-apps"
    part.mkdir()
    for app in ("000001", "000004"):
        (part / app).symlink_to(RERUN / app, target_is_directory=True)
    apps, grade, survival, turns = score(part)
    assert apps == "2"
    assert 0.0 <= float(grade) <= 1.0 and 0.0 <= float(survival) <= 10.0 and float(turns) > 0
