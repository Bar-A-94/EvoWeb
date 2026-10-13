"""Where the package finds its inputs. Every script imports from here instead of hardcoding.

ROOT       this package (the repository root)
DATA       datasets (the 32-app EvoWeb set, the ablation set, the WebGen-Bench base apps)
EXAMPLES   examples_artifacts/: the released traces, the full-trace archive, the example app and
           our reproductions
MULTILINGUAL  the translated benchmark, one file per language
TRACES     released run traces (the paper's runs of the four Anthropic models, three each, plus
           the multilingual Sonnet 4.6 and Haiku 4.5 runs; see arms.py): <run-id>/<sample:06d>/
           result.json plus the compact per-request model_calls.jsonl. Ships as
           EXAMPLES/traces.zip and is unpacked there on first use (ensure_traces). Override with
           EVOWEB_TRACES to score your own runs.
ARTIFACTS  where tables, figures and JSON outputs are written
"""

from __future__ import annotations

import os
import shutil
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
EXAMPLES = ROOT / "examples_artifacts"
TRACES = Path(os.environ.get("EVOWEB_TRACES") or EXAMPLES / "traces")
ARTIFACTS = Path(os.environ.get("EVOWEB_ARTIFACTS") or ROOT / "artifacts")

# The benchmark: 32 apps x 10 requests, one row per app, row order = sample index (1-based).
BENCHMARK = DATA / "evoweb_benchmark.jsonl"
# The benchmark with the requests translated: evoweb_benchmark_<lang>.jsonl, same row order.
MULTILINGUAL = DATA / "multilingual"


def ensure_traces() -> Path:
    """TRACES, unpacking EXAMPLES/traces.zip in place the first time it is needed."""
    zp = EXAMPLES / "traces.zip"
    if not TRACES.is_dir() and TRACES == EXAMPLES / "traces" and zp.is_file():
        tmp = EXAMPLES / "traces.unpacking"
        shutil.rmtree(tmp, ignore_errors=True)
        with zipfile.ZipFile(zp) as z:
            z.extractall(tmp)
        (tmp / "traces").rename(TRACES)
        tmp.rmdir()
    return TRACES


def run_dir(run_id: str) -> Path:
    """Directory of one run (arm replicate) under TRACES; fails loudly if it is missing."""
    d = ensure_traces() / run_id
    if not d.is_dir():
        raise FileNotFoundError(
            f"run {run_id!r} not found under {TRACES} (set EVOWEB_TRACES to a directory holding "
            f"<run-id>/<sample>/result.json)"
        )
    return d
