"""Live reproduction: generate fresh traces for a few apps and check they land in the paper's
run-to-run envelope. Costs API money and hours; OFF unless EVOWEB_LIVE=1.

    EVOWEB_LIVE=1 ANTHROPIC_API_KEY=... \
    EVOWEB_LIVE_APPS=1,4,6,11 EVOWEB_LIVE_MODELS=haiku,sonnet \
    /usr/bin/python3 -m pytest tests/test_live_reproduction.py -q -s

What it does, per model: runs `harness/run_local.sh` on the chosen apps (all 10 requests of
each, exactly the paper's recipe), scores the produced ladders with `evoweb.scoring` on the
SAME apps, and compares Grade with the released replicates of that model restricted to those
apps. The check passes when the fresh Grade is within `EVOWEB_LIVE_K` (default 2) population
standard deviations of the replicate mean, with a floor of 0.05 Grade because a handful of
apps is noisier than the 32-app number.

Set EVOWEB_LIVE_SKIP_RUN=1 to skip generation and only score an existing output directory
(`EVOWEB_LIVE_OUT`), e.g. to re-check a run that finished after the test timed out.
"""

from __future__ import annotations

import json
import os
import statistics as st
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from evoweb import arms, metrics, paths  # noqa: E402
from evoweb.scoring import ladder_from_result, load_expected_tasks  # noqa: E402

pytestmark = pytest.mark.skipif(
    os.environ.get("EVOWEB_LIVE") != "1", reason="live reproduction is opt-in: set EVOWEB_LIVE=1"
)

TURNS = metrics.TURNS

# model key -> (paper row, generator model id, provider, API_URL, key env var)
MODELS = {
    "haiku": (
        "Haiku 4.5",
        "anthropic/claude-haiku-4-5-20251001",
        "Anthropic",
        "",
        "ANTHROPIC_API_KEY",
    ),
    "sonnet": ("Sonnet 4.6", "anthropic/claude-sonnet-4-6", "Anthropic", "", "ANTHROPIC_API_KEY"),
}


def _env_list(name, default):
    return [x.strip() for x in os.environ.get(name, default).split(",") if x.strip()]


def grade(ladders, expected):
    """Paper Grade (Sec. 3.4), the same function every table uses."""
    return metrics.run_scores(ladders, expected)["grade"]


def load_run(run_dir: Path, apps: list[int]) -> dict:
    ladders = {}
    for idx in apps:
        f = run_dir / f"{idx:06d}" / "result.json"
        if f.is_file():
            r = json.load(open(f))
            ladders[int(r["index"])] = ladder_from_result(r)
    return ladders


@pytest.fixture(scope="module")
def apps():
    return [int(x) for x in _env_list("EVOWEB_LIVE_APPS", "1,4,6,11")]


@pytest.fixture(scope="module")
def out_root(tmp_path_factory):
    return Path(os.environ.get("EVOWEB_LIVE_OUT") or tmp_path_factory.mktemp("evoweb-live"))


@pytest.mark.parametrize("key", _env_list("EVOWEB_LIVE_MODELS", "haiku,sonnet"))
def test_fresh_run_within_replicate_envelope(key, apps, out_root):
    row, model_id, provider, api_url, key_env = MODELS[key]
    api_key = os.environ.get(key_env)
    eval_key = os.environ.get("EVAL_API_KEY") or os.environ.get("ANTHROPIC_API_KEY")
    if not api_key or not eval_key:
        pytest.skip(f"{key_env} and an Anthropic key for the judge are required")
    run_id = f"live-{key}"
    run_dir = out_root / run_id
    if os.environ.get("EVOWEB_LIVE_SKIP_RUN") != "1":
        env = dict(
            os.environ,
            API_KEY=api_key,
            EVAL_API_KEY=eval_key,
            MODEL=model_id,
            PROVIDER=provider,
            API_URL=api_url,
            EVAL_MODEL="claude-sonnet-4-6",
            EVAL_API_URL="https://api.anthropic.com",
            JSONL_FILE="evoweb_benchmark.jsonl",
            # Re-run with the build guidance the model's released runs had (arms.NAV_GUIDANCE).
            WEBGEN_NAV_GUIDANCE=arms.nav_guidance(arms.TABLE2[row][0]),
        )
        cmd = [
            "bash",
            str(ROOT / "harness" / "run_local.sh"),
            run_id,
            ",".join(str(a) for a in apps),
            os.environ.get("EVOWEB_LIVE_PARALLELISM", str(len(apps))),
        ]
        env["EVOWEB_OUT"] = str(out_root)
        print(f"\n[{key}] running {len(apps)} ladders -> {run_dir}", flush=True)
        subprocess.run(
            cmd, env=env, check=True, timeout=int(os.environ.get("EVOWEB_LIVE_TIMEOUT", 6 * 3600))
        )

    expected = load_expected_tasks(paths.BENCHMARK)
    fresh = load_run(run_dir, apps)
    assert len(fresh) == len(apps), (
        f"{key}: {len(fresh)}/{len(apps)} ladders produced a result.json"
    )
    infra = [
        (sid, t)
        for sid, b in fresh.items()
        for t in TURNS
        if (b.get(t) or {}).get("status") == "error"
    ]
    assert not infra, (
        f"{key}: infrastructure-errored turns {infra}; repair (re-run those apps) before judging"
    )
    g_fresh = grade(fresh, expected)

    refs = []
    for rid in arms.TABLE2[row]:
        ref = load_run(paths.run_dir(rid), apps)
        assert len(ref) == len(apps), f"released run {rid} lacks apps {apps}"
        refs.append(grade(ref, expected))
    mean, std = st.mean(refs), (st.pstdev(refs) if len(refs) > 1 else 0.0)
    k = float(os.environ.get("EVOWEB_LIVE_K", "2"))
    tol = max(k * std, 0.05)
    print(
        f"[{key}] apps={apps} fresh Grade={g_fresh:.3f}  released={[round(r, 3) for r in refs]} "
        f"mean={mean:.3f} std={std:.3f} tolerance=±{tol:.3f}",
        flush=True,
    )
    assert abs(g_fresh - mean) <= tol, (
        f"{key}: fresh Grade {g_fresh:.3f} is outside {mean:.3f}±{tol:.3f} "
        f"(released replicates {refs}) — the trace generation may have drifted"
    )
