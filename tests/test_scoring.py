"""Unit tests of the verbatim scoring module and the metric arithmetic built on it."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from evoweb import metrics, scoring  # noqa: E402
from evoweb.paths import BENCHMARK  # noqa: E402


def request(t, yes, partial, no, status="success"):
    return {
        "turn": t,
        "status": status,
        "yes": yes,
        "partial": partial,
        "no": no,
        "total": yes + partial + no,
    }


def test_request_score():
    assert scoring.request_score(request(1, 4, 1, 2)) == pytest.approx(4.5 / 7 * 100)
    assert scoring.request_score(request(2, 5, 0, 0)) == 100.0
    assert scoring.request_score(request(2, 0, 0, 5)) == 0.0
    assert scoring.request_score(None) is None
    assert scoring.request_score({"turn": 3, "status": "error", "total": 0}) is None


def test_parse_verdict():
    reasoned = "Thought: ... - YES ... - NO\nAction: ANSWER; PARTIAL"
    assert scoring.parse_verdict(reasoned) == "partial"
    assert scoring.parse_verdict("Action: ANSWER: **YES**") == "yes"
    assert scoring.parse_verdict("the page shows YES\n\nNO") == "no"
    assert scoring.parse_verdict("nothing conclusive") == "no"
    assert scoring.parse_verdict("") == "no"


def test_score_ladders_synthetic():
    # Two ladders, three requests. Sample 2's request 3 errored (no verdict).
    ladders = {
        1: {1: request(1, 5, 0, 0), 2: request(2, 4, 0, 1), 3: request(3, 2, 2, 1)},
        2: {
            1: request(1, 3, 0, 2),
            2: request(2, 5, 0, 0),
            3: {"turn": 3, "status": "error", "total": 0},
        },
    }
    expected = {1: {1: 5, 2: 5, 3: 5}, 2: {1: 5, 2: 5, 3: 5}}
    s = scoring.score_ladders(ladders, (1, 2, 3), expected_by_sample=expected)
    assert s["turns"][1]["raw"] == pytest.approx(80.0)
    assert s["turns"][2]["raw"] == pytest.approx(90.0)
    # request 3: only sample 1 judged -> raw 60 over its 5 tests, norm 60 * 1/2 samples
    assert s["turns"][3]["raw"] == pytest.approx(60.0)
    assert s["turns"][3]["norm"] == pytest.approx(30.0)
    assert s["turns"][3]["errored"] == 1
    assert s["avg_raw"] == pytest.approx((80 + 90 + 60) / 3)
    assert s["avg_norm"] == pytest.approx((80 + 90 + 30) / 3)


def test_gate_and_survival():
    by_request = {t: request(t, 5, 0, 0) for t in range(1, 11)}
    by_request[4] = request(4, 2, 1, 2)  # 50 %
    assert metrics.requests_before_gate(by_request, 0) == 10
    assert metrics.requests_before_gate(by_request, 50) == 10
    assert metrics.requests_before_gate(by_request, 51) == 3
    gated = metrics.gate({1: by_request}, 51)[1]
    assert gated[4]["total"] == 5  # the failing request still counts
    assert gated[5]["status"] == "skipped" and gated[5]["total"] == 0
    # S(t) of a perfect ladder is 10 at every threshold -> Survival 10
    perfect = {1: {t: request(t, 5, 0, 0) for t in range(1, 11)}}
    assert metrics.auc(metrics.survival_sweep(perfect)) == pytest.approx(10.0)


def test_load_expected_tasks_evoweb():
    if not BENCHMARK.is_file():
        pytest.skip(f"{BENCHMARK} missing")
    expected = scoring.load_expected_tasks(str(BENCHMARK))
    assert sorted(expected) == list(range(1, 33))
    for per_request in expected.values():
        assert sorted(per_request) == list(range(1, 11))
        assert all(per_request[t] == 5 for t in range(2, 11))
        assert per_request[1] >= 4


def test_global_rule_requests_evoweb():
    if not BENCHMARK.is_file():
        pytest.skip(f"{BENCHMARK} missing")
    assert len(metrics.global_rule_requests()) == 18
