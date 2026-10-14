#!/usr/bin/env python3
"""Score the request-language runs of Table 3 (Sonnet 4.6 and Haiku 4.5 x 5 languages).

The user writes in another language, the app stays in English: each arm ran on
data/multilingual/evoweb_benchmark_<lang>.jsonl (translated request text, English UI mandate, the untouched
English judge tasks) with the model's Table 2 sampling. Scored with the shared `evoweb.scoring` module -- the same avg_raw / avg_norm and the
two 1%-step gate sweeps (Grade = norm AUC / 100, Survival = requests-survived AUC) as Table 2. n=1 per
arm; the English reference is the model's Table 2 row.

Usage (from anywhere):
    python3 ablations/multilingual/score_arms.py [--json out.json] [model ...]
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))
from evoweb import arms, metrics  # noqa: E402
from evoweb.paths import MULTILINGUAL  # noqa: E402


def score_arm(ladders, expected):
    s = metrics.run_scores(ladders, expected)
    return {
        "raw": s["raw"],
        "norm": s["norm"],
        "auc_norm": s["auc_norm"],
        "auc_turns": s["auc_turns"],
        "grade": s["grade"],
        "mean_depth": sum(metrics.requests_before_gate(b, 0.0001) for b in ladders.values())
        / len(ladders),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("models", nargs="*", help="Table 3 model names (default: all)")
    ap.add_argument("--json", help="write every arm's metrics here")
    a = ap.parse_args()
    models = a.models or list(arms.MULTILINGUAL)
    expected_en = metrics.expected_tasks()
    results = {}
    for model in models:
        print(f"| {model} | raw | norm | Grade | Survival |")
        print("|---|---|---|---|---|")
        en = metrics.arm_metrics(arms.TABLE2[model], expected_en)
        results[f"{model}-en"] = {
            "raw": en["raw"][0],
            "norm": en["norm"][0],
            "auc_norm": en["auc_norm"][0],
            "auc_turns": en["auc_turns"][0],
            "grade": en["grade"][0],
        }
        print(
            f"| en (Table 2, n={en['grade'][2]}) | {en['raw'][0]:.1f} | {en['norm'][0]:.1f} | "
            f"{en['grade'][0]:.3f} | {en['survival'][0]:.2f} |"
        )
        for lang in arms.LANGS:
            expected = metrics.expected_tasks(MULTILINGUAL / f"evoweb_benchmark_{lang}.jsonl")
            m = score_arm(metrics.load_ladders(arms.MULTILINGUAL[model][lang]), expected)
            results[f"{model}-{lang}"] = m
            print(
                f"| {arms.LANG_NAMES[lang]} | {m['raw']:.1f} | {m['norm']:.1f} | "
                f"{m['grade']:.3f} | {m['auc_turns']:.2f} |"
            )
        print()
    if a.json:
        Path(a.json).write_text(json.dumps(results, indent=1) + "\n")
        print("wrote", a.json)


if __name__ == "__main__":
    main()
