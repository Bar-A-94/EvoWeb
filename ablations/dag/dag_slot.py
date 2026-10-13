#!/usr/bin/env python3
"""DAG integration check (slot 3) vs the other four checks; Grade by test type (Table 4).

Every follow-up request (T2-T10) carries exactly one `integration` check at task_idx 3 (the
DAG check -- combine features built in earlier requests) and one `regression` (backward) check
at task_idx 4; slots 0-2 are feature / exact-value (functional). Scoring the integration slot
and the other checks separately WITHIN the same runs cancels run luck in the contrast.

Raw = (yes + 0.5*partial) / judged over judged tasks only; errored turns drop whole turns
from both groups equally. Turn 1 is excluded from the contrast (different task structure,
no kind labels) but participates in gate replays.

Usage (from anywhere):
    python3 ablations/dag/dag_slot.py               # the tables (RAW, per-kind, separation)
    python3 ablations/dag/dag_slot.py --figures     # also render the three PNGs into ARTIFACTS
    python3 ablations/dag/dag_slot.py --three-group # functional / integration / backward AUC
    python3 ablations/dag/dag_slot.py --four-group  # Table 4: slot-3 checks on requests with
                                                    # NO incoming DAG edge scored as "global
                                                    # rule" instead of integration

Figures:
    slot_vs_rest.png     per-turn RAW (ungated) and NORM (gate@55 replayed on the
                         overall turn score)
    slot_auc_shared.png  gate-threshold sweeps 0-100 with the SHARED all-five-check gate
                         (both groups die on the same turn; only the norm is per-group).
                         This is the fair contrast -- see replay() for why.
    slot_auc.png         the same sweeps where each group's OWN score gates progression.
                         A counterfactual, NOT a difficulty measurement: a 1-check group
                         and a 4-check group are not gate-comparable at equal thresholds.

Data: paths.TRACES/<run-id>/*/result.json. The arms are the paper setup of evoweb.arms
(DAG_TABLE: the first two runs of each model).
"""

from __future__ import annotations

import argparse
import json
import os
import statistics as st
import sys
from collections import defaultdict

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))
from evoweb import arms, metrics  # noqa: E402
from evoweb.metrics import global_rule_turns  # noqa: E402
from evoweb.paths import ARTIFACTS, run_dir  # noqa: E402

# PAPER SETUP (Table 4's runs): the DAG_TABLE runs, then every other Table 2 model on its
# Table 2 runs. Sonnet 4.6's two runs are read after four of their ladders were re-run following
# an infrastructure error, so its printed row differs slightly from the paper's Table 4.
ARMS = {
    **{m: list(r) for m, r in arms.DAG_TABLE.items()},
    **{m: list(r) for m, r in arms.TABLE2.items() if m not in arms.DAG_TABLE},
}

CLAUDE_MODELS = ("Fable 5", "Opus 4.8", "Sonnet 4.6", "Haiku 4.5")
FIG_MODELS = CLAUDE_MODELS
# The paper's Table 4 rows, in paper order.
TABLE_MODELS = tuple(m for m in arms.DAG_TABLE if m in ARMS)

VERDICT_W = {"yes": 1.0, "partial": 0.5, "no": 0.0}
FOLLOW_UPS = list(range(2, 11))
THRESHOLDS = list(range(0, 101))
GATE_T = 55  # replayed gate threshold for the NORM row of the slot_vs_rest figure, %

COL = {"slot": "#B45309", "rest": "#0F766E"}
LBL = {"slot": "integration check (the DAG's own, 1 of 5)", "rest": "the other four checks"}


def results(rd):
    return sorted(rd.glob("*/result.json"))


def load_kind_map():
    """(run_sample_index, turn, task_idx) -> (kind, task, expected) from the dataset.

    Run sample index N is the 1-based ROW position in the jsonl (row ids like '000004'
    are non-contiguous pool ids -- do not use them). Mapping verified by exact text
    equality of every judged task against the dataset (see the assert in score_run).
    """
    from evoweb.metrics import benchmark_rows

    kinds = {}
    for row_idx, row in enumerate(benchmark_rows()):
        for fu_i, fu in enumerate(row["follow_ups"]):
            for task_idx, t in enumerate(fu["ui_instruct"]):
                kinds[(row_idx + 1, fu_i + 2, task_idx)] = (
                    t["kind"],
                    t["task"],
                    t["expected_result"],
                )
    return kinds


def score_run(rd, kinds):
    """Return {group: [sum_weight, judged_count]} for one run (groups: slot/rest/kind:*)."""
    acc = defaultdict(lambda: [0.0, 0])
    for f in results(rd):
        r = json.load(open(f))
        idx = int(r["index"])
        for turn in r.get("turns", []):
            tn = turn.get("turn")
            if not tn or tn < 2:
                continue
            for t in turn.get("tasks", []):
                v = VERDICT_W.get(t.get("verdict"))
                if v is None:
                    continue
                ti = t.get("task_idx")
                group = "slot" if ti == 3 else "rest"
                acc[group][0] += v
                acc[group][1] += 1
                kind, task_txt, expected_txt = kinds[(idx, tn, ti)]
                assert (t["task"], t["expected"]) == (task_txt, expected_txt), (
                    f"dataset/run task text mismatch at index={idx} turn={tn} task_idx={ti}"
                )
                acc[f"kind:{kind}"][0] += v
                acc[f"kind:{kind}"][1] += 1
    return acc


def pct(pair):
    s, n = pair
    return s / n * 100.0 if n else float("nan")


def per_app_turn(rd):
    """app -> {"grp": turn -> (slot, rest), "all": turn -> overall raw, "reached": set}.

    "all" includes T1 (needed to replay the gate); "grp" starts at T2. A turn absent from
    "all" was never judged (errored) and kills the replayed ladder like a sub-threshold one.
    "reached" is the set of turns surviving the gate@GATE_T replay (failing turn included).
    """
    out = {}
    for f in results(rd):
        r = json.load(open(f))
        idx = int(r["index"])
        for turn in r.get("turns", []):
            tn = turn.get("turn")
            if not tn:
                continue
            cell = {"slot": [0.0, 0], "rest": [0.0, 0]}
            for t in turn.get("tasks", []):
                v = VERDICT_W.get(t.get("verdict"))
                if v is None:
                    continue
                g = "slot" if tn >= 2 and t.get("task_idx") == 3 else "rest"
                cell[g][0] += v
                cell[g][1] += 1
            judged = cell["slot"][1] + cell["rest"][1]
            if not judged:
                continue
            app = out.setdefault(idx, {"grp": {}, "all": {}})
            app["all"][tn] = (cell["slot"][0] + cell["rest"][0]) / judged
            if tn >= 2:
                app["grp"][tn] = (
                    cell["slot"][0] / cell["slot"][1] if cell["slot"][1] else None,
                    cell["rest"][0] / cell["rest"][1] if cell["rest"][1] else None,
                )
    for app in out.values():
        alive, reached = True, set()
        for t in range(1, 11):
            if alive:
                reached.add(t)
                sc = app["all"].get(t)
                if sc is None or sc * 100 < GATE_T:
                    alive = False
        app["reached"] = reached
    return out


# ---------------------------------------------------------------- tables


def print_tables():
    kinds = load_kind_map()
    per_arm = {}
    for arm, run_ids in ARMS.items():
        series = defaultdict(list)
        for rid in run_ids:
            rd = run_dir(rid)
            n_results = len(results(rd))
            if n_results != 32:
                sys.exit(f"{rid}: expected 32 results, found {n_results}")
            acc = score_run(rd, kinds)
            for g, pair in acc.items():
                series[g].append((pct(pair), pair[1]))
        per_arm[arm] = series

    def cell(arm, group):
        vals = [v for v, _ in per_arm[arm].get(group, [])]
        return st.mean(vals) if vals else float("nan")

    print("== integration slot (task_idx 3) vs the other four checks -- raw %, T2-T10 ==")
    print(f"{'model':18} {'rest(4/5)':>10} {'integration':>12} {'penalty':>9}  judged(slot/run)")
    for arm in ARMS:
        rest, slot = cell(arm, "rest"), cell(arm, "slot")
        nj = per_arm[arm]["slot"][0][1]
        runs_txt = " / ".join(f"{v:.1f}" for v, _ in per_arm[arm]["slot"])
        print(f"{arm:18} {rest:10.1f} {slot:12.1f} {slot - rest:+9.1f}  n={nj} [{runs_txt}]")

    print("\n== per-kind raw % (T2-T10) ==")
    kinds_order = ["exact-value", "feature", "regression", "integration"]
    print(f"{'model':18} " + " ".join(f"{k:>12}" for k in kinds_order))
    for arm in ARMS:
        print(f"{arm:18} " + " ".join(f"{cell(arm, 'kind:' + k):12.1f}" for k in kinds_order))

    print("\n== pairwise separation: |A-B| on the slot vs on the rest ==")
    pairs = [
        ("Sonnet 4.6", "Haiku 4.5"),
        ("Fable 5", "Haiku 4.5"),
        ("Opus 4.8", "Haiku 4.5"),
        ("Fable 5", "Sonnet 4.6"),
        ("Opus 4.8", "Sonnet 4.6"),
        ("Fable 5", "Opus 4.8"),
    ]
    print(f"{'pair':30} {'rest':>7} {'slot':>7} {'advantage':>10}")
    for a, b in pairs:
        sep_rest = abs(cell(a, "rest") - cell(b, "rest"))
        sep_slot = abs(cell(a, "slot") - cell(b, "slot"))
        print(f"{a + ' vs ' + b:30} {sep_rest:7.1f} {sep_slot:7.1f} {sep_slot - sep_rest:+10.1f}")

    sep_rest = abs(cell("Sonnet 4.6", "rest") - cell("Haiku 4.5", "rest"))
    sep_slot = abs(cell("Sonnet 4.6", "slot") - cell("Haiku 4.5", "slot"))
    print(f"\nheadline ratio (Sonnet-Haiku): slot/rest separation = {sep_slot / sep_rest:.2f}x")

    print(f"\n== NORM@{GATE_T} per group (shared all-five-check gate replayed, T2-T10) ==")
    print(f"{'model':18} {'rest(4/5)':>10} {'integration':>12} {'penalty':>9}")
    for arm in ARMS:
        runs = [per_app_turn(run_dir(rid)) for rid in ARMS[arm]]
        apps = sorted(set().union(*[set(r) for r in runs]))
        cur = {g: curve(runs, apps, gi, "norm") for g, gi in (("slot", 0), ("rest", 1))}
        m = {g: st.mean([cur[g][t][0] for t in FOLLOW_UPS if t in cur[g]]) for g in cur}
        print(f"{arm:18} {m['rest']:10.1f} {m['slot']:12.1f} {m['slot'] - m['rest']:+9.1f}")


# ---------------------------------------------------------------- slot_vs_rest figure


def curve(runs, apps, gi, metric):
    """turn -> (mean across runs, std across runs). metric 'norm' replays gate@GATE_T."""
    out = {}
    for t in FOLLOW_UPS:
        per_run = []
        for r in runs:
            if metric == "norm":
                vals = []
                for app in apps:
                    a = r.get(app)
                    cell = a["grp"].get(t) if a and t in a["reached"] else None
                    vals.append(cell[gi] if cell and cell[gi] is not None else 0.0)
            else:
                vals = [
                    r[app]["grp"][t][gi]
                    for app in apps
                    if app in r and t in r[app]["grp"] and r[app]["grp"][t][gi] is not None
                ]
            if vals:
                per_run.append(st.mean(vals) * 100)
        if per_run:
            out[t] = (st.mean(per_run), st.pstdev(per_run) if len(per_run) > 1 else 0.0)
    return out


def fig_slot_vs_rest(plt, out_path):
    models = ("Sonnet 4.6", "Haiku 4.5")
    fig, axes = plt.subplots(2, 2, figsize=(15.0, 9.8), sharex=True)
    means = {}
    for col, model in enumerate(models):
        runs = [per_app_turn(run_dir(rid)) for rid in ARMS[model]]
        apps = sorted(set().union(*[set(r) for r in runs]))
        for row, metric in enumerate(("raw", "norm")):
            ax = axes[row][col]
            cur = {g: curve(runs, apps, gi, metric) for g, gi in (("slot", 0), ("rest", 1))}
            for grp in ("rest", "slot"):
                ts = [t for t in FOLLOW_UPS if t in cur[grp]]
                ys = [cur[grp][t][0] for t in ts]
                sd = [cur[grp][t][1] for t in ts]
                ax.plot(
                    ts,
                    ys,
                    "--s" if grp == "slot" else "-o",
                    color=COL[grp],
                    linewidth=2,
                    markersize=6,
                    label=f"{LBL[grp]}  (n={len(runs)} runs)",
                )
                ax.fill_between(
                    ts,
                    [y - s for y, s in zip(ys, sd)],
                    [y + s for y, s in zip(ys, sd)],
                    color=COL[grp],
                    alpha=0.15,
                    linewidth=0,
                )
            ms = st.mean([cur["slot"][t][0] for t in FOLLOW_UPS if t in cur["slot"]])
            mr = st.mean([cur["rest"][t][0] for t in FOLLOW_UPS if t in cur["rest"]])
            means[(model, metric)] = (ms, mr)
            ttl = "RAW (ungated)" if metric == "raw" else f"NORM (gate@{GATE_T} replayed)"
            ax.set_title(f"{model} -- {ttl}   (EvoWeb, n={len(runs)})", fontsize=11.5)
            ax.set_ylabel(f"{metric.upper()} %")
            ax.grid(alpha=0.25)
            ax.legend(loc="upper right", fontsize=8.2)
            ax.text(
                0.98,
                0.06,
                f"mean T2-T10\n  integration {ms:5.1f}\n  other four  {mr:5.1f}\n"
                f"  difference  {ms - mr:+5.1f}",
                transform=ax.transAxes,
                ha="right",
                va="bottom",
                fontsize=9,
                family="monospace",
                bbox=dict(boxstyle="round,pad=0.45", facecolor="#f8fafc", edgecolor="#cbd5e1"),
            )
    for ax in axes[1]:
        ax.set_xlabel("turn")
        ax.set_xticks(FOLLOW_UPS)
        ax.set_xticklabels([f"T{t}" for t in FOLLOW_UPS])

    adv = {}
    for metric in ("raw", "norm"):
        gs = means[("Sonnet 4.6", metric)][0] - means[("Haiku 4.5", metric)][0]
        gr = means[("Sonnet 4.6", metric)][1] - means[("Haiku 4.5", metric)][1]
        adv[metric] = (gs, gr, gs - gr)
    fig.suptitle(
        f"The DAG's own check against its four neighbours -- gate@{GATE_T} replayed on NORM\n"
        f"Sonnet-Haiku separation:  RAW {adv['raw'][0]:.1f} vs {adv['raw'][1]:.1f} "
        f"(advantage {adv['raw'][2]:+.1f}, {adv['raw'][0] / adv['raw'][1]:.2f}x)   .   "
        f"NORM {adv['norm'][0]:.1f} vs {adv['norm'][1]:.1f} "
        f"(advantage {adv['norm'][2]:+.1f}, {adv['norm'][0] / adv['norm'][1]:.2f}x)",
        fontsize=12.5,
    )
    note = (
        "RAW counts only judged turns. NORM replays the 55% gate offline (runs execute "
        "ungated, "
        "every turn judged): the first turn below 55% overall -- T1 included -- kills the "
        "ladder; "
        "the failing turn still counts, later turns score 0.\n"
        "Both curves come from the same runs, so run luck cancels in the contrast. Turn 1 is "
        "the "
        "base build and has no typed checks. Judge: Sonnet 4.6."
    )
    fig.text(0.008, 0.012, note, fontsize=8.2, color="#4a5568")
    plt.tight_layout(rect=[0, 0.085, 1, 0.925])
    plt.savefig(out_path, dpi=150)
    plt.close(fig)
    print(f"saved {out_path}")


# ---------------------------------------------------------------- sweep-AUC figure


def replay(app, gi, th, gate="shared"):
    """(avg group-NORM over T2..T10, follow-up turns survived) for one app at threshold th.

    gate="shared" -- the OVERALL five-check turn score gates progression, so both groups die
    on exactly the same turn and only the norm is group-specific. This is the fair contrast.
    A 1-check group and a 4-check group are NOT gate-comparable at equal thresholds: one
    check scores only 0/50/100, so every threshold above 50 demands a perfect verdict each
    turn, while four checks can absorb a failure (3 yes + 1 no = 75 still passes 55). Gating
    each group on itself therefore charges the integration slot for its coarse granularity on
    top of its difficulty, and the two are inseparable in the result.

    gate="own" -- the group's own score both gates and norms. Keep it as the counterfactual
    "what if the benchmark were only this check group", not as a difficulty measurement.

    Either way T1 (no typed checks) gates the first step on the overall score for both groups,
    the failing turn still counts, and an unjudged turn kills the ladder.
    """
    t1 = app["all"].get(1)
    if t1 is None or t1 * 100 < th:
        return 0.0, 0
    kept, survived, alive = [], 0, True
    for t in FOLLOW_UPS:
        if not alive:
            kept.append(0.0)
            continue
        cell = app["grp"].get(t)
        s = cell[gi] if cell else None
        overall = app["all"].get(t)
        judge = overall if gate == "shared" else s
        if judge is None:
            kept.append(0.0)
            alive = False
            continue
        # A group with no judged task in a turn the shared gate kept alive would otherwise
        # sink that group alone; audited as never happening on these runs (0/4023 turns).
        kept.append(s if s is not None else 0.0)  # the failing turn itself still counts
        if judge * 100 < th:
            alive = False
        else:
            survived += 1
    return st.mean(kept) * 100, survived


def sweep(runs, gi, gate="shared"):
    norm_runs, surv_runs = [], []
    for r in runs:
        norms, survs = [], []
        for th in THRESHOLDS:
            vals = [replay(app, gi, th, gate) for app in r.values()]
            norms.append(st.mean([v[0] for v in vals]))
            survs.append(st.mean([v[1] for v in vals]))
        norm_runs.append(norms)
        surv_runs.append(survs)
    return norm_runs, surv_runs


def auc(curve_pts):
    return sum((a + b) / 2 for a, b in zip(curve_pts, curve_pts[1:])) / 100.0


def auc_table(gate):
    """{(model, group): [AUC per run]} plus {model: turns-survived AUC} for one gate mode."""
    aucs, surv = {}, {}
    for model in FIG_MODELS:
        runs = [per_app_turn(run_dir(rid)) for rid in ARMS[model]]
        for grp, gi in (("rest", 1), ("slot", 0)):
            norm_runs, surv_runs = sweep(runs, gi, gate)
            aucs[(model, grp)] = [auc(c) for c in norm_runs]
            aucs[(model, grp, "curves")] = norm_runs
            surv[(model, grp)] = st.mean([auc(c) for c in surv_runs])
    return aucs, surv


def fig_auc(plt, out_path, gate="shared"):
    """One panel: avg-NORM gate sweep for every figure model (dashed = integration,
    solid = the other four), with the AUC table right under the plot."""
    model_col = {
        "Fable 5": "#c53030",
        "Opus 4.8": "#6b46c1",
        "Sonnet 4.6": "#2f855a",
        "Haiku 4.5": "#b7791f",
    }
    fig, (ax, axt) = plt.subplots(
        2, 1, figsize=(11.5, 11.0), gridspec_kw={"height_ratios": [3.0, 1.05]}
    )
    aucs, surv = auc_table(gate)
    for model in FIG_MODELS:
        for grp, ls in (("rest", "-"), ("slot", "--")):
            norm_runs = aucs[(model, grp, "curves")]
            means = [st.mean(v) for v in zip(*norm_runs)]
            stds = [st.pstdev(v) for v in zip(*norm_runs)]
            ax.plot(THRESHOLDS, means, ls, color=model_col[model], lw=2.2)
            if len(norm_runs) > 1:
                ax.fill_between(
                    THRESHOLDS,
                    [m - s for m, s in zip(means, stds)],
                    [m + s for m, s in zip(means, stds)],
                    color=model_col[model],
                    alpha=0.10,
                    linewidth=0,
                )
    from matplotlib.lines import Line2D

    handles = [Line2D([], [], color=model_col[m], lw=2.6, label=m) for m in FIG_MODELS]
    handles += [
        Line2D([], [], color="#444", lw=2.2, ls="-", label="the other four checks"),
        Line2D([], [], color="#444", lw=2.2, ls="--", label="integration check (the DAG's own)"),
    ]
    ax.legend(handles=handles, loc="upper right", fontsize=9.5, ncol=2)
    drives = (
        "the SHARED all-five-check turn score drives the gate (fair contrast)"
        if gate == "shared"
        else "each check group's OWN score drives the gate (counterfactual)"
    )
    ax.set_title(
        f"avg NORM vs gate threshold -- {drives}\n"
        "(EvoWeb; Claude n=2 runs, others n=1, all high effort)",
        fontsize=12.5,
    )
    ax.set_xlabel("gate threshold (%)")
    ax.set_ylabel("avg NORM (%), T2-T10")
    ax.set_ylim(0, 100)
    ax.grid(alpha=0.25)

    axt.axis("off")
    surv_hdr = "turns survived" if gate == "shared" else "survived s/r"
    tbl = [
        f"NORM sweep AUC (trapezoid over thresholds 0-100, /100) -- {gate} gate",
        "",
        f"model          integration   other four    diff   {surv_hdr}",
        "-" * 66,
    ]
    for model in FIG_MODELS:
        n_s, n_r = st.mean(aucs[(model, "slot")]), st.mean(aucs[(model, "rest")])
        sv = (
            f"{surv[(model, 'slot')]:11.2f}"
            if gate == "shared"
            else f"{surv[(model, 'slot')]:5.2f}/{surv[(model, 'rest')]:.2f}"
        )
        tbl.append(f"{model:13s}  {n_s:11.1f}  {n_r:11.1f}  {n_s - n_r:+6.1f}  {sv}")
    tbl.append("-" * 66)
    rat = []
    for a_, b_ in (
        ("Fable 5", "Haiku 4.5"),
        ("Opus 4.8", "Haiku 4.5"),
        ("Sonnet 4.6", "Haiku 4.5"),
    ):
        gs = st.mean(aucs[(a_, "slot")]) - st.mean(aucs[(b_, "slot")])
        gr = st.mean(aucs[(a_, "rest")]) - st.mean(aucs[(b_, "rest")])
        rat.append(f"{a_.split()[-1]}-{b_.split()[-1]} {gs / gr:.2f}x")
    tbl.append("separation ratios (slot/rest): " + ", ".join(rat))
    axt.text(
        0.5,
        0.92,
        "\n".join(tbl),
        transform=axt.transAxes,
        va="top",
        ha="center",
        fontsize=11,
        family="monospace",
        bbox=dict(boxstyle="round,pad=0.7", facecolor="#f8fafc", edgecolor="#cbd5e1"),
    )
    if gate == "shared":
        note = (
            "Both groups ride the SAME ladder: progression is gated on the overall five-check "
            "turn "
            "score, so slot and rest die on the same turn and only the norm differs. This is "
            "the\n"
            "like-for-like comparison. Gating each group on itself instead (slot_auc.png) "
            "charges the integration slot for granularity as well as difficulty: one check "
            "scores\n"
            "only 0/50/100, so any threshold above 50 demands a perfect verdict every turn, "
            "while "
            "four checks can absorb one failure.\n"
            "T1 (no typed checks) gates the first step identically. Failing turn still counts; "
            "unjudged turn kills the ladder. Turns-survived is set by the shared gate, so it "
            "is\n"
            "identical for both groups and reported once. Judge: Sonnet 4.6."
        )
    else:
        note = (
            "COUNTERFACTUAL, not a difficulty measurement: every ladder is replayed as if "
            "scored "
            "by one check group alone -- the group's per-turn score gates progression AND is "
            "the "
            "norm.\n"
            "The integration group holds ONE check (0/50/100 only), so above threshold 50 its "
            "gate demands a perfect verdict every turn while the four-check group can absorb a "
            "failure. The gap below therefore mixes difficulty with granularity -- use "
            "slot_auc_shared.png for the fair contrast.\n"
            "T1 (no typed checks) gates the first step identically for both groups. Failing "
            "turn "
            "still counts; unjudged turn kills the ladder. Judge: Sonnet 4.6."
        )
    fig.text(0.02, 0.012, note, fontsize=8.2, color="#4a5568")
    plt.tight_layout(rect=[0, 0.075 if gate == "shared" else 0.045, 1, 1])
    plt.savefig(out_path, dpi=150)
    plt.close(fig)
    print(f"saved {out_path}")
    for model in FIG_MODELS:
        n_s, n_r = st.mean(aucs[(model, "slot")]), st.mean(aucs[(model, "rest")])
        sd_s, sd_r = st.pstdev(aucs[(model, "slot")]), st.pstdev(aucs[(model, "rest")])
        print(
            f"  [{gate:6s}] NORM sweep AUC {model:13s} integration {n_s:5.1f}+-{sd_s:.1f}  "
            f"other four {n_r:5.1f}+-{sd_r:.1f}  diff {n_s - n_r:+5.1f}  "
            f"turns survived {surv[(model, 'slot')]:.2f}/{surv[(model, 'rest')]:.2f}"
        )


# ---------------------------------------------------------------- three-/four-way split table
# Splits the five follow-up checks by task_idx instead of two ways:
#   functional  = task_idx {0,1,2}  (exact-value + feature, three checks)
#   integration = task_idx == 3     (the DAG's own check, one check)
#   backward    = task_idx == 4     (the regression / backward-compatibility check, one check)
# and, in the four-way split, the slot-3 check of a request with NO incoming DAG edge is
#   global_rule                     (it verifies one of the app's global_rules, not a
#                                    dependency -- dag_global_rule_checks.py lists them)
# Everything below uses the SHARED all-five-check gate (the fair contrast, see replay()):
# progression is decided by the overall turn score, so turns-survived is one number per model,
# not one per group. The cells and the replay are evoweb.metrics' (the Table 4 code), keyed
# by task_idx rather than the kind map. Table 4 of the paper is the four-way split.
G3 = ("functional", "integration", "backward")
G4 = ("functional", "integration", "global_rule", "backward")
GLOBAL_RULE_TURNS = global_rule_turns()  # {(run index, turn)}


def group_table(groups, gr_turns, models, header):
    """Print the shared-gate per-group AUC table as GitHub-flavoured markdown.

    The per-(turn, group) cells and the gate replay are `evoweb.metrics.per_app_turn_groups`
    and `replay_group`. `gr_turns` is the set
    of (app, turn) whose slot-3 check is a global-rule check; pass an empty set for the
    three-way split, where every slot-3 check counts as integration.
    """
    aucn = {}  # (model, group) -> [AUC-NORM per run]
    raw = {}  # (model, group) -> [RAW % per run]: mean over judged cells, no gate
    survm = {}  # model -> AUC-Survival (shared gate, one per model)
    for model in models:
        runs = [metrics.per_app_turn_groups(rid, gr_turns) for rid in ARMS[model]]
        for g in groups:
            raw[(model, g)] = [
                st.mean(
                    [c[g] for app in r.values() for c in app["grp"].values() if c[g] is not None]
                )
                * 100
                for r in runs
            ]
            per_run = []
            for r in runs:
                curve = []
                for th in THRESHOLDS:
                    cells = [c for app in r.values() for c in metrics.replay_group(app, g, th)[0]]
                    curve.append(st.mean(cells) * 100)
                per_run.append(metrics.auc(curve))
            aucn[(model, g)] = per_run
        surv_runs = []
        for r in runs:
            curve = [
                st.mean([metrics.replay_group(app, groups[0], th)[1] for app in r.values()])
                for th in THRESHOLDS
            ]
            surv_runs.append(metrics.auc(curve))
        survm[model] = st.mean(surv_runs)

    def cellstr(v):
        return f"{st.mean(v):.1f} +-{st.pstdev(v):.1f}" if len(v) > 1 else f"{st.mean(v):.1f}"

    print(f"\n== {header} ==\n")
    print("| model | " + " | ".join(groups) + " | AUC-Survival |")
    print("|---|" + "---|" * (len(groups) + 1))
    col = {g: [] for g in groups}
    surv_all = []
    for model in models:
        for g in groups:
            col[g].append(st.mean(aucn[(model, g)]))
        surv_all.append(survm[model])
        cells = " | ".join(cellstr(aucn[(model, g)]) for g in groups)
        print(f"| {model} | {cells} | {survm[model]:.2f} |")
    avg = " | ".join(f"**{st.mean(col[g]):.1f}**" for g in groups)
    print(f"| **AVG** | {avg} | **{st.mean(surv_all):.2f}** |")

    print("\n== same groups, RAW % (ungated; mean over judged checks of the group) ==\n")
    print("| model | " + " | ".join(groups) + " |")
    print("|---|" + "---|" * len(groups))
    col = {g: [] for g in groups}
    for model in models:
        for g in groups:
            col[g].append(st.mean(raw[(model, g)]))
        print(f"| {model} | " + " | ".join(cellstr(raw[(model, g)]) for g in groups) + " |")
    print("| **AVG** | " + " | ".join(f"**{st.mean(col[g]):.1f}**" for g in groups) + " |")


def three_group_table(models=TABLE_MODELS):
    group_table(G3, set(), models, "three-way AUC-NORM (shared gate) + AUC-Survival per model")


def four_group_table(models=TABLE_MODELS):
    n = len(GLOBAL_RULE_TURNS)
    group_table(
        G4,
        GLOBAL_RULE_TURNS,
        models,
        f"four-way AUC-NORM (shared gate): slot-3 checks on the {n} requests with no "
        "incoming DAG edge scored as global_rule (Table 4, x100)",
    )


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--figures",
        action="store_true",
        help="also render slot_vs_rest.png, slot_auc_shared.png and slot_auc.png",
    )
    ap.add_argument("--outdir", default=str(ARTIFACTS))
    ap.add_argument(
        "--three-group",
        action="store_true",
        help="only print the shared-gate three-way AUC table (markdown) and exit",
    )
    ap.add_argument(
        "--four-group",
        action="store_true",
        help="only print the four-way table (integration split into real "
        "integration vs global-rule checks) and exit",
    )
    a = ap.parse_args()

    if a.three_group:
        three_group_table()
        return
    if a.four_group:
        four_group_table()
        return

    print_tables()
    if a.figures:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        os.makedirs(a.outdir, exist_ok=True)
        print()
        fig_slot_vs_rest(plt, os.path.join(a.outdir, "slot_vs_rest.png"))
        fig_auc(plt, os.path.join(a.outdir, "slot_auc_shared.png"), gate="shared")
        fig_auc(plt, os.path.join(a.outdir, "slot_auc.png"), gate="own")


if __name__ == "__main__":
    main()
