#!/usr/bin/env python3
"""Does the DAG's structure add difficulty? Request score vs DAG depth / in-degree, T8-T10.

For every app and every follow-up request t, the dependency_graph gives two structural
measures of how much earlier work the request leans on:
    depth      longest dependency chain ending at T{t} (T1 = 0; a request with no incoming
               edge also has depth 0), i.e. the node's depth in the DAG
    in-degree  number of incoming edges (how many earlier features T{t} must compose with)
The request score is the ungated grade of that request: mean verdict weight (yes 1,
partial 0.5, no 0) over its five checks, for the runs in which it was judged. Restricting to
requests 8, 9 and 10 holds the context length roughly fixed, so what is left of the trend is
the graph, not the position in the ladder.

Same arms as dag_slot.py (the paper setup); each model a colour, each request a marker
shape, one panel per x-axis. A point is the mean over the apps (and runs) that share that
x value for that model and request; marker area scales with the number of apps behind it.
The dashed line is the per-model least-squares fit over all its points, weighted by count,
drawn over that model's observed x range (no extrapolation). Figure 4 of the paper is the
four Anthropic models of this figure.

Usage (from anywhere):
    python3 ablations/dag/dag_depth_score.py     # ARTIFACTS/dag_depth_score.png + slope table
                                                 # + dag_depth_score_by_request.png (one row per
                                                 #   request 8, 9, 10 and a pooled 8-10 row)
                                                 # + dag_indegree_t10_fits.png (request 10 vs
                                                 #   in-degree, weighted fit lines only)
                                                 # + dag_depth_score.json (the plotted data)
"""

from __future__ import annotations

import argparse
import json
import os
import statistics as st
import sys
from collections import defaultdict

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.lines import Line2D  # noqa: E402

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.abspath(os.path.join(_HERE, "..", "..")))
sys.path.insert(0, _HERE)
import dag_slot as d  # noqa: E402

from evoweb import metrics  # noqa: E402
from evoweb.metrics import benchmark_rows, structure, wls  # noqa: E402
from evoweb.paths import ARTIFACTS  # noqa: E402

REQUESTS = (8, 9, 10)
MARKER = {8: "s", 9: "^", 10: "o"}
# Okabe-Ito, colour-blind safe, fixed order = TABLE_MODELS order
PALETTE = ["#D55E00", "#0072B2", "#009E73", "#CC79A7", "#E69F00", "#56B4E9", "#000000", "#F0E442"]
X_MAX = 10


def _runs(model):
    """The model's Table 4 runs."""
    return list(d.ARMS[model])


def request_scores(model):
    """{(app_index, turn): [score per run in which the turn was judged]}."""
    return metrics.request_scores(_runs(model), REQUESTS)


def points(model, struct, axis):
    """{turn: {x: (mean score, n apps)}} for one model on one structural axis.

    `struct` is accepted for the callers' convenience; `metrics.dag_points` derives the same
    structure from the dataset rows."""
    return metrics.dag_points(_runs(model), axis)


def grid_figure(struct, models, color, out):
    """4 rows (request 8, 9, 10, pooled 8-10) x 2 panels (depth, in-degree)."""
    fig, axes = plt.subplots(4, 2, figsize=(14, 19), sharey=True)
    rows = [((t,), f"request {t}") for t in REQUESTS] + [(REQUESTS, "requests 8-10 pooled")]
    for r, (turns, label) in enumerate(rows):
        for c, (axis, xlabel) in enumerate((("depth", "DAG depth"), ("indeg", "in-degree"))):
            ax = axes[r][c]
            for m in models:
                pts = points(m, struct, axis)
                bucket = defaultdict(list)  # x -> per-(app, request) means, pooled over turns
                for t in turns:
                    for x, (y, n) in pts[t].items():
                        bucket[x].extend([y] * n)
                pooled = {x: (st.mean(v), len(v)) for x, v in bucket.items()}
                for x, (y, n) in sorted(pooled.items()):
                    ax.scatter(
                        x,
                        y,
                        s=18 + 10 * n,
                        marker=MARKER[turns[0]] if len(turns) == 1 else "D",
                        color=color[m],
                        alpha=0.75,
                        edgecolor="white",
                        linewidth=0.6,
                        zorder=3,
                    )
                slope, icpt, (x0, x1) = wls({0: pooled})
                ax.plot(
                    [x0, x1],
                    [icpt + slope * x0, icpt + slope * x1],
                    "--",
                    color=color[m],
                    lw=1.1,
                    alpha=0.8,
                )
            ax.set_xlim(-0.5, X_MAX + 0.5)
            ax.set_xticks(range(0, X_MAX + 1))
            ax.set_ylim(0, 102)
            ax.set_title(f"{label} -- {xlabel}", fontsize=11, loc="left")
            ax.grid(alpha=0.25)
            ax.set_axisbelow(True)
            if r == 3:
                ax.set_xlabel(xlabel)
        axes[r][0].set_ylabel("request score, %")
    handles = [Line2D([], [], color=color[m], marker="o", ls="", ms=7, label=m) for m in models]
    fig.legend(
        handles=handles,
        loc="lower center",
        ncol=8,
        fontsize=9,
        frameon=False,
        bbox_to_anchor=(0.5, -0.005),
    )
    fig.suptitle(
        "Request score vs DAG structure, per request (EvoWeb, paper arms; point area = "
        "number of apps; dashed = weighted fit over observed range)",
        fontsize=12,
    )
    fig.tight_layout(rect=(0, 0.02, 1, 0.98))
    fig.savefig(out, dpi=140)
    print("wrote", out)


def export_json(struct, models, out):
    """Everything the figures draw: sections "depth" and "indeg", then model -> request ->
    x value -> {mean, n, apps: {app index: score}}; plus the per-app structure and the
    weighted slopes. Scores are per-app means over runs, in %."""
    data = {
        "setup": "EvoWeb paper arms: " + ", ".join(f"{m}={d.ARMS[m]}" for m in models),
        "score": "request grade, %: mean verdict weight (yes 1, partial 0.5, no 0) over "
        "the request's five checks, averaged over the runs in which it was judged",
        "structure": {
            str(i): {
                "depth": {str(t): v for t, v in dep.items()},
                "indeg": {str(t): v for t, v in ind.items()},
            }
            for i, (dep, ind) in struct.items()
        },
        "depth": {},
        "indeg": {},
        "slopes": {},
    }
    for m in models:
        scores = request_scores(m)
        for axis in ("depth", "indeg"):
            sec = data[axis].setdefault(m, {})
            for tn in REQUESTS:
                per_x = defaultdict(dict)
                for (idx, t), per_run in scores.items():
                    if t == tn:
                        x = struct[idx][0 if axis == "depth" else 1][tn]
                        per_x[x][str(idx)] = round(st.mean(per_run), 2)
                sec[str(tn)] = {
                    str(x): {"mean": round(st.mean(v.values()), 2), "n": len(v), "apps": v}
                    for x, v in sorted(per_x.items())
                }
            pts = points(m, struct, axis)
            data["slopes"].setdefault(m, {})[axis] = {
                **{str(tn): round(wls({tn: pts[tn]})[0], 3) for tn in REQUESTS},
                "pooled": round(wls(pts)[0], 3),
            }
    with open(out, "w") as fh:
        json.dump(data, fh, indent=1)
        fh.write("\n")
    print("wrote", out)


def fits_only_figure(struct, models, color, out, turn=10, axis="indeg"):
    """One request, one axis: the per-model weighted fit lines without the points."""
    fig, ax = plt.subplots(figsize=(8, 5.5))
    for m in models:
        pts = points(m, struct, axis)
        slope, icpt, (x0, x1) = wls({turn: pts[turn]})
        n = sum(n for _, n in pts[turn].values())
        ax.plot(
            [x0, x1],
            [icpt + slope * x0, icpt + slope * x1],
            color=color[m],
            lw=2.2,
            label=f"{m}  ({slope:+.1f} pts/edge, {n} apps)",
        )
    ax.set_xlim(-0.5, X_MAX + 0.5)
    ax.set_xticks(range(0, X_MAX + 1))
    ax.set_ylim(0, 102)
    ax.set_xlabel("in-degree of request 10 (incoming DAG edges)")
    ax.set_ylabel("request score, % (weighted least-squares fit)")
    ax.set_title(
        f"Request {turn}: score vs in-degree, fit lines only (EvoWeb, paper arms)",
        fontsize=11,
        loc="left",
    )
    ax.grid(alpha=0.25)
    ax.set_axisbelow(True)
    ax.legend(fontsize=8.5, loc="lower left", frameon=False)
    fig.tight_layout()
    fig.savefig(out, dpi=160)
    print("wrote", out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(ARTIFACTS / "dag_depth_score.png"))
    a = ap.parse_args()
    os.makedirs(os.path.dirname(a.out), exist_ok=True)

    struct = {i: structure(row) for i, row in enumerate(benchmark_rows(), start=1)}
    models = d.TABLE_MODELS
    color = dict(zip(models, PALETTE))

    fig, axes = plt.subplots(1, 2, figsize=(14, 6), sharey=True)
    slopes = {}
    for ax, axis, xlabel in zip(
        axes,
        ("depth", "indeg"),
        (
            "DAG depth of the request (longest dependency chain ending at it)",
            "in-degree of the request (incoming DAG edges)",
        ),
    ):
        for m in models:
            pts = points(m, struct, axis)
            for tn in REQUESTS:
                for x, (y, n) in sorted(pts[tn].items()):
                    ax.scatter(
                        x,
                        y,
                        s=18 + 14 * n,
                        marker=MARKER[tn],
                        color=color[m],
                        alpha=0.75,
                        edgecolor="white",
                        linewidth=0.6,
                        zorder=3,
                    )
            slope, icpt, (x0, x1) = wls(pts)
            slopes[(m, axis)] = slope
            ax.plot(
                [x0, x1],
                [icpt + slope * x0, icpt + slope * x1],
                "--",
                color=color[m],
                lw=1.1,
                alpha=0.8,
            )  # drawn over the model's observed x range only
        ax.set_xlim(-0.5, X_MAX + 0.5)
        ax.set_xticks(range(0, X_MAX + 1))
        ax.set_ylim(0, 102)
        ax.set_xlabel(xlabel)
        ax.grid(alpha=0.25)
        ax.set_axisbelow(True)
    axes[0].set_ylabel("request score, % (mean verdict over the 5 checks, judged requests only)")

    handles = [Line2D([], [], color=color[m], marker="o", ls="", ms=7, label=m) for m in models]
    handles += [
        Line2D([], [], color="#555", marker=MARKER[t], ls="", ms=7, label=f"request {t}")
        for t in REQUESTS
    ]
    fig.legend(
        handles=handles,
        loc="lower center",
        ncol=6,
        fontsize=9,
        frameon=False,
        bbox_to_anchor=(0.5, -0.02),
    )
    fig.suptitle(
        "Requests 8-10: does the DAG's structure make a request harder?  "
        "(EvoWeb, paper arms; point area = number of apps; dashed = weighted fit over "
        "observed range)",
        fontsize=12,
    )
    fig.tight_layout(rect=(0, 0.07, 1, 0.96))
    fig.savefig(a.out, dpi=160)
    print("wrote", a.out)
    grid_figure(struct, models, color, a.out.replace(".png", "_by_request.png"))
    fits_only_figure(
        struct, models, color, os.path.join(os.path.dirname(a.out), "dag_indegree_t10_fits.png")
    )
    export_json(struct, models, a.out.replace(".png", ".json"))

    print("\n| model | slope vs depth (pts / level) | slope vs in-degree (pts / edge) |")
    print("|---|---|---|")
    for m in models:
        print(f"| {m} | {slopes[(m, 'depth')]:+.2f} | {slopes[(m, 'indeg')]:+.2f} |")
    print(
        f"| **AVG** | **{st.mean(slopes[(m, 'depth')] for m in models):+.2f}** "
        f"| **{st.mean(slopes[(m, 'indeg')] for m in models):+.2f}** |"
    )


if __name__ == "__main__":
    main()
