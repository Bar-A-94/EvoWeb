#!/usr/bin/env python3
"""Loaders and statistics for the grounding ablation (paper App. C.1).

`WORD_ALNUM` is the raw-token tokenizer the invented n-gram overlap uses:

    "Show 8 stocks with P/E 31.4"  ->  show 8 stocks with p e 31 4
"""

from __future__ import annotations

import functools
import glob
import json
import math
import os
import random
import re
import statistics as st
import sys
from pathlib import Path

_HERE = os.path.dirname(os.path.abspath(__file__))
_PKG = os.path.abspath(os.path.join(_HERE, "..", ".."))
if _PKG not in sys.path:
    sys.path.insert(0, _PKG)
from evoweb.paths import ARTIFACTS as _ARTIFACTS  # noqa: E402
from evoweb.paths import DATA as _DATA  # noqa: E402
from evoweb.paths import ensure_data  # noqa: E402

DATA = str(_DATA)
ARTIFACTS = str(_ARTIFACTS)

# The two datasets App. C.1 compares, both written by the same author model.
ARMS = {
    "control": "evoweb_benchmark.jsonl",
    "no_grounding_fable": "ablation_no_grounding.jsonl",
}
LABEL = {"control": "grounded", "no_grounding_fable": "no grounding"}

WORD_ALNUM = re.compile(r"[a-z0-9']+")


def words(text, *, alnum=True):
    return WORD_ALNUM.findall(text.lower())


def ngrams_in_order(text, n, *, alnum=True):
    """n-grams in order of FIRST APPEARANCE, deduplicated.

    Order matters wherever a fixed-size prefix is taken: the earliest items are domain spillover
    common to every arm, and the arms diverge in the tail.
    """
    w = words(text, alnum=alnum)
    seen, out = set(), []
    for i in range(len(w) - n + 1):
        g = " ".join(w[i : i + n])
        if g not in seen:
            seen.add(g)
            out.append(g)
    return out


def _norm(o):
    """Parts files carry `app_idx`; assembled rows carry `id`."""
    o["id"] = o.get("id") or o["app_idx"]
    return o


def rows(arm_or_path):
    """Populated rows of an arm (by ARMS key) or of an explicit jsonl path / parts dir."""
    target = ARMS.get(arm_or_path, arm_or_path)
    path = target if os.path.isabs(target) else os.path.join(DATA, target)
    ensure_data(Path(path))
    if os.path.isdir(path):
        out = []
        for f in sorted(glob.glob(os.path.join(path, "*.json"))):
            o = json.load(open(f))
            if o.get("follow_ups"):
                out.append(_norm(o))
        return out
    return [
        _norm(o)
        for o in (json.loads(x) for x in open(path, encoding="utf-8"))
        if o.get("follow_ups")
    ]


def instructions(arm_or_path):
    """app id -> its 9 follow-up instructions, in request order."""
    return {int(r["id"]): [f["instruction"] for f in r["follow_ups"]] for r in rows(arm_or_path)}


@functools.cache
def base_prompts():
    """app id -> its base-app (build) prompt."""
    out = {}
    for i, line in enumerate(open(os.path.join(DATA, "legacy_webgen_bench_apps.jsonl")), 1):
        try:
            out[i] = json.loads(line).get("instruction", "")
        except Exception:  # noqa: BLE001 - a malformed line must not take the whole run down
            out[i] = ""
    return out


def sign_test(diffs):
    """Exact two-sided binomial sign test over paired differences. Ties and NaN dropped.

    Returns `(up, n, p)` where `up` is the raw count of POSITIVE differences.
    """
    d = [x for x in diffs if x == x and x != 0]
    n = len(d)
    if not n:
        return 0, 0, 1.0
    up = sum(1 for x in d if x > 0)
    k = min(up, n - up)
    return up, n, min(1.0, 2 * sum(math.comb(n, i) for i in range(k + 1)) / 2**n)


def bootstrap_ci(values, iters=4000, seed=0, alpha=0.05, rnd=None):
    """Percentile CI of the MEAN, resampling with replacement. `rnd` shares one generator."""
    rnd = rnd or random.Random(seed)
    b = sorted(st.mean(rnd.choices(values, k=len(values))) for _ in range(iters))
    return b[int(alpha / 2 * iters)], b[int((1 - alpha / 2) * iters)]
