"""Score gating is disabled (threshold -1): only a non-success request ends the ladder."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

SOURCE = Path(__file__).resolve().parents[2] / "harness" / "run_single_sample.py"


@pytest.fixture(scope="module")
def gate():
    spec = importlib.util.spec_from_file_location("rss", SOURCE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.ladder_continues


@pytest.mark.parametrize(
    "status,score,expected",
    [
        ("success", 1.0, True),
        ("success", 0.5, True),
        ("success", 0.0, True),  # score gating is off: even a zero continues the ladder
        ("gen_failed", 1.0, False),  # a high score on a failed request still stops the ladder
        ("error", 1.0, False),
    ],
)
def test_only_a_non_success_request_ends_the_ladder(gate, status, score, expected):
    assert gate(status, score)[0] is expected


@pytest.mark.parametrize(
    "status,expected",
    [
        ("success", "previous_turn_below_threshold"),
        ("gen_failed", "previous_turn_did_not_complete"),
    ],
)
def test_the_skip_reason_names_the_cause_that_fired(gate, status, expected):
    """A low score and an infrastructure failure are different outcomes and must be told apart."""
    assert gate(status, 0.0)[1] == expected
