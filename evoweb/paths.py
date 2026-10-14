"""Where the package finds its inputs. Every script imports from here instead of hardcoding.

ROOT       this package (the repository root)
DATA       datasets (the 32-app EvoWeb set, the ablation set, the WebGen-Bench base apps)
EXAMPLES   examples_artifacts/: the released traces, the full-trace archive, the example app and
           our reproductions
MULTILINGUAL  the translated benchmark, one file per language
           (BENCHMARK and MULTILINGUAL are downloaded from Hugging Face by ensure_data;
           EVOWEB_DATA overrides DATA)
TRACES     released run traces (the paper's runs of the four Anthropic models, three each, plus
           the multilingual Sonnet 4.6 and Haiku 4.5 runs; see arms.py): <run-id>/<sample:06d>/
           result.json plus the compact per-request model_calls.jsonl. Ships as
           EXAMPLES/traces.zip and is unpacked there on first use (ensure_traces). Override with
           EVOWEB_TRACES to score your own runs.
ARTIFACTS  where tables, figures and JSON outputs are written
"""

from __future__ import annotations

import http.client
import json
import os
import shutil
import sys
import tempfile
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = Path(os.environ.get("EVOWEB_DATA") or ROOT / "data")
EXAMPLES = ROOT / "examples_artifacts"
TRACES = Path(os.environ.get("EVOWEB_TRACES") or EXAMPLES / "traces")
ARTIFACTS = Path(os.environ.get("EVOWEB_ARTIFACTS") or ROOT / "artifacts")

# The benchmark: 32 apps x 10 requests, one row per app, row order = sample index (1-based).
BENCHMARK = DATA / "evoweb_benchmark.jsonl"
# The benchmark with the requests translated: evoweb_benchmark_<lang>.jsonl, same row order.
MULTILINGUAL = DATA / "multilingual"
# Table 3's languages, in the paper's order.
LANGS: tuple[str, ...] = ("fr", "de", "zh", "hi", "he")

# BENCHMARK and MULTILINGUAL live on Hugging Face, not in git. ensure_data downloads revision
# EVOWEB_HF_REVISION (default "main", the latest); run_local.sh resolves "main" to one commit so
# every ladder of a run reads the same data. EVOWEB_NO_DOWNLOAD=1 keeps the local files.
HF_REPO = "https://huggingface.co/datasets/TD-Labs/EvoWeb"
HF_FILES = [BENCHMARK] + [MULTILINGUAL / f"evoweb_benchmark_{lang}.jsonl" for lang in LANGS]
_fetched: set[Path] = set()


def latest_revision() -> str:
    """The commit of the Hugging Face dataset's main branch."""
    url = HF_REPO.replace("/datasets/", "/api/datasets/") + "/revision/main"
    with urllib.request.urlopen(url, timeout=30) as r:
        return json.load(r)["sha"]


def ensure_data(*files: Path) -> None:
    """Download HF_FILES (default: all; other paths are ignored), each once per process."""
    rev = os.environ.get("EVOWEB_HF_REVISION") or "main"
    for f in [Path(f) for f in files] or HF_FILES:
        if f not in HF_FILES or f in _fetched:
            continue
        _fetched.add(f)
        if os.environ.get("EVOWEB_NO_DOWNLOAD") == "1" and f.is_file():
            continue
        f.parent.mkdir(parents=True, exist_ok=True)
        url = (
            f"{HF_REPO}/resolve/{urllib.parse.quote(rev, safe='')}/{f.relative_to(DATA).as_posix()}"
        )
        # A temp file of its own: two processes downloading into one checkout must not share it.
        fd, tmp = tempfile.mkstemp(dir=f.parent, prefix=f".{f.name}.", suffix=".download")
        try:
            with urllib.request.urlopen(url, timeout=60) as r, os.fdopen(fd, "wb") as out:
                shutil.copyfileobj(r, out)
        except (OSError, http.client.HTTPException) as e:
            Path(tmp).unlink(missing_ok=True)
            if not f.is_file():
                raise
            print(
                f"[evoweb] {f.name}: download failed ({e}); using the local copy", file=sys.stderr
            )
            continue
        os.replace(tmp, f)  # readers never see a half-written file


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


if __name__ == "__main__":
    # python3 -m evoweb.paths            download the data
    # python3 -m evoweb.paths revision   print the latest HF commit
    print(latest_revision()) if sys.argv[1:] == ["revision"] else ensure_data()
