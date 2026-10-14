"""The turn-cap default exists in two shipped entry points; they must never drift apart.

run_sample.sh exports AGENT_MAX_TURNS (what the container runs with) and backend.DEFAULT_MAX_STEPS
serves a direct `run_single_sample.py` launch. A drift would make one launch silently incomparable
to the other. (The internal repo also checked the GitHub workflow and the k8s launcher, which the
open-source package does not ship.)
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

HARNESS = Path(__file__).resolve().parents[2] / "harness"
sys.path.insert(0, str(HARNESS))

from generators.backend import DEFAULT_MAX_STEPS  # noqa: E402


def test_the_shipped_defaults_agree():
    launcher = (HARNESS / "run_sample.sh").read_text()
    m = re.search(r'^export AGENT_MAX_TURNS="\$\{AGENT_MAX_TURNS:-(\d+)\}"', launcher, re.M)
    assert m, "AGENT_MAX_TURNS default not found in run_sample.sh"
    launcher_default = int(m.group(1))

    assert launcher_default == DEFAULT_MAX_STEPS == 20
