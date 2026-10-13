#!/usr/bin/env python3
"""Output tokens per agent step: model x step 1..20, mean +- std (EvoWeb, paper arms).

Every request lets the OpenHands agent take up to 20 steps, one model call each. The
capture proxy recorded each call in <sample>/turnN/generation/model_calls.jsonl (request 1 at
the sample root), one file per request; the released traces keep {ts, duration_s, status,
model, tools, usage} of every record. Step k of a request is its k-th successful (HTTP 200)
call. Output tokens are the provider's completion count, which includes reasoning/thinking
tokens on every wire schema we ran:
    Anthropic /v1/messages         usage.output_tokens (thinking inside)
    OpenAI-style /v1/responses      usage.output_tokens (reasoning inside)
    chat/completions (z.ai, vLLM)   usage.completion_tokens (reasoning inside)

Same runs as dag_slot.py (the paper setup). A cell pools every request of every run of the model that reached that
step, so later columns rest on fewer requests; the count table says how many. Figure 3c of
the paper is the cumulative version of these means.

Usage (from anywhere):
    python3 ablations/dag/output_tokens_by_step.py          # mean +- std table, count table
    python3 ablations/dag/output_tokens_by_step.py --json ARTIFACTS/output_tokens_by_step.json
    python3 ablations/dag/output_tokens_by_step.py --png ARTIFACTS/output_tokens_by_step.png
        # mean output tokens (thousands) vs step, one line per model; hollow markers mark
        # cells resting on fewer than MIN_N requests
"""

from __future__ import annotations

import argparse
import json
import os
import statistics as st
import sys
from collections import defaultdict

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.abspath(os.path.join(_HERE, "..", "..")))
sys.path.insert(0, _HERE)
import dag_slot as d  # noqa: E402

from evoweb.metrics import iter_requests, output_tokens  # noqa: E402

MAX_STEPS = 20
MIN_N = 5  # cells with fewer requests are drawn hollow in the figure
MODELS = d.TABLE_MODELS
JSON_MODELS = MODELS
# Okabe-Ito, same model -> colour mapping as dag_depth_score.py
PALETTE = [
    "#D55E00",
    "#0072B2",
    "#009E73",
    "#CC79A7",
    "#E69F00",
    "#56B4E9",
    "#000000",
    "#F0E442",
    "#8C8C8C",
]


def collect(model):
    """{step: [output tokens]} pooled over runs, apps and requests; plus #requests seen."""
    per = defaultdict(list)
    n_requests = 0
    for rid in d.ARMS[model]:
        for _, _, calls in iter_requests(rid):
            toks = [t for t in (output_tokens(c) for c in calls) if t is not None]
            if not toks:
                continue
            n_requests += 1
            for k, t in enumerate(toks, start=1):
                per[k].append(t)
    return per, n_requests


def figure(data, models, out):
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(11, 6))
    for m, col in zip(models, PALETTE):
        per = data[m][0]
        xs = [k for k in range(1, MAX_STEPS + 1) if per.get(k)]
        ys = [st.mean(per[k]) / 1000 for k in xs]
        ax.plot(xs, ys, color=col, lw=2, label=m, zorder=3)
        solid = [(x, y) for x, y in zip(xs, ys) if len(per[x]) >= MIN_N]
        hollow = [(x, y) for x, y in zip(xs, ys) if len(per[x]) < MIN_N]
        if solid:
            ax.scatter(*zip(*solid), color=col, s=28, zorder=4)
        if hollow:
            ax.scatter(
                *zip(*hollow), facecolor="white", edgecolor=col, s=28, zorder=4, linewidth=1.4
            )
    ax.set_xticks(range(1, MAX_STEPS + 1))
    ax.set_xlim(0.5, MAX_STEPS + 0.5)
    ax.set_ylim(0)
    ax.set_xlabel("agent step within a request (model call index)")
    ax.set_ylabel("mean output tokens per call, thousands")
    ax.set_title(
        "Output tokens per agent step (EvoWeb, paper arms; hollow = fewer than "
        f"{MIN_N} requests reached the step)",
        fontsize=11,
        loc="left",
    )
    ax.grid(alpha=0.25)
    ax.set_axisbelow(True)
    ax.legend(frameon=False, fontsize=9, ncol=2)
    fig.tight_layout()
    fig.savefig(out, dpi=160)
    print("wrote", out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", help="also write the per-cell mean/std/n here")
    ap.add_argument("--png", help="also draw mean tokens (thousands) vs step, one line per model")
    a = ap.parse_args()

    data = {m: collect(m) for m in JSON_MODELS}
    steps = list(range(1, MAX_STEPS + 1))

    print("\n== output tokens per agent step: mean +- std (pooled over runs, apps, requests) ==\n")
    print("| model | " + " | ".join(str(k) for k in steps) + " |")
    print("|---|" + "---|" * len(steps))
    for m in JSON_MODELS:
        per, _ = data[m]
        cells = []
        for k in steps:
            v = per.get(k, [])
            if not v:
                cells.append("--")
            elif len(v) == 1:
                cells.append(f"{v[0]:.0f}")
            else:
                cells.append(f"{st.mean(v):.0f} +- {st.pstdev(v):.0f}")
        print(f"| {m} | " + " | ".join(cells) + " |")

    print("\n== requests reaching each step (n behind each cell) ==\n")
    print("| model | requests | " + " | ".join(str(k) for k in steps) + " |")
    print("|---|---|" + "---|" * len(steps))
    for m in JSON_MODELS:
        per, n_req = data[m]
        print(f"| {m} | {n_req} | " + " | ".join(str(len(per.get(k, []))) for k in steps) + " |")
    beyond = {m: sum(len(v) for k, v in data[m][0].items() if k > MAX_STEPS) for m in JSON_MODELS}
    print("\ncalls beyond step 20 (not tabulated):", beyond)

    if a.png:
        figure(data, MODELS, a.png)
    if a.json:
        out = {
            m: {
                str(k): {
                    "mean": st.mean(v),
                    "std": st.pstdev(v) if len(v) > 1 else 0.0,
                    "n": len(v),
                }
                for k, v in sorted(data[m][0].items())
            }
            for m in JSON_MODELS
        }
        with open(a.json, "w") as fh:
            json.dump(out, fh, indent=1)
            fh.write("\n")
        print("wrote", a.json)


if __name__ == "__main__":
    main()
