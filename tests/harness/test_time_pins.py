"""The agent's two run-time-fetched inputs are pinned to the paper's runs.

OpenHands resolves its venv with uv at container start and clones its public skills registry
(github.com/OpenHands/extensions) at `main` into the agent's system prompt. Left floating, a
re-run uses a different agent than the paper's.
"""

from __future__ import annotations

import re
from pathlib import Path

HARNESS = Path(__file__).resolve().parents[2] / "harness"


def _default(name: str) -> str:
    sh = (HARNESS / "run_sample.sh").read_text()
    m = re.search(rf'^export {name}="\$\{{{name}:-([^}}]*)\}}"', sh, re.M)
    assert m, f"run_sample.sh must export {name} with a default"
    return m.group(1)


def test_skills_registry_pinned_to_a_tag():
    ref = _default("EXTENSIONS_REF")
    assert ref == "v0.17.0"
    # `git clone --depth 1 --branch <ref>` rejects a commit hash and the agent would silently
    # run without public skills.
    assert not re.fullmatch(r"[0-9a-f]{7,40}", ref)


def test_dependency_horizon_is_the_paper_date():
    assert _default("UV_EXCLUDE_NEWER") == "2026-08-20T11:00:00Z"


def test_run_local_passes_both_through():
    sh = (HARNESS / "run_local.sh").read_text()
    assert "EXTENSIONS_REF" in sh and "UV_EXCLUDE_NEWER" in sh
