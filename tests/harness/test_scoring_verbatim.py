"""The harness scores with the exact scoring.py the released numbers were computed with.

harness/scoring.py (used at run time by run_single_sample.py) and evoweb/scoring.py (used by the
re-score tier) must be byte-identical, or a re-run and a re-score could disagree.
"""

from pathlib import Path

PKG = Path(__file__).resolve().parents[2]


def test_harness_scoring_is_byte_identical_to_the_package_scoring():
    a = (PKG / "harness" / "scoring.py").read_bytes()
    b = (PKG / "evoweb" / "scoring.py").read_bytes()
    assert a == b, "harness/scoring.py drifted from evoweb/scoring.py"
