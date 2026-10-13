"""examples_artifacts/examples.zip: one app's complete output, matching the released scores, every request present."""

import json
import zipfile
from pathlib import Path

from evoweb.paths import ensure_traces

ROOT = Path(__file__).resolve().parents[1]
APP = "opus-4.8-run1-app000001"


def names_and_result():
    with zipfile.ZipFile(ROOT / "examples_artifacts" / "examples.zip") as z:
        return z.namelist(), json.loads(z.read(f"{APP}/result.json"))


def test_result_matches_released_trace():
    _, result = names_and_result()
    released = ensure_traces() / "opus-4.8-run1" / "000001" / "result.json"
    assert result == json.loads(released.read_text())


def test_every_request_has_generation_and_judge_artifacts():
    names, _ = names_and_result()
    assert f"{APP}/README.md" in names
    for t in range(1, 11):
        turn = f"{APP}/" + ("" if t == 1 else f"turn{t}/")
        assert f"{turn}generation/trajectory.jsonl" in names, turn
        assert f"{turn}generation/workspace/package.json" in names, turn
        sessions = {n.split("/")[-2] for n in names if n.startswith(f"{turn}eval/results/")}
        assert sessions, turn
        for s in sessions:
            assert f"{turn}eval/results/{s}/interact_messages.json" in names, s
            assert any(n.startswith(f"{turn}eval/results/{s}/screenshot") for n in names), s
