"""The paper's arithmetic, lifted verbatim from the study scripts that produced the tables.

Everything takes run ids (directories under `paths.TRACES`) or ladders ({sample: {request:
request dict}}) and returns plain numbers. No I/O outside `paths`.

Sec. 3.4 of the paper, in the code's terms:
    accuracy a_r        scoring.request_score(request) / 100 (mean verdict weight over the tests)
    Q(t)                score_ladders(gate(ladders, t))["avg_norm"]  (delivered functionality, %)
    S(t)                mean over ladders of requests_before_gate(ladder, t)
    Grade               trapezoid AUC of Q(t) over t = 0..100 %, /100 (auc_norm), then /100 again
                        to report on [0, 1]
    Survival            trapezoid AUC of S(t) over t = 0..100 %, /100 (auc_turns)
    turns / request     successful (HTTP 200) model calls per request, mean over requests
    $ / sample          generation cost of the run / 32 (judge cost excluded)
A model row is the mean over its runs; the population std (statistics.pstdev) where n > 1.

Table 4 (Grade by test type) and Figure 4 (request score vs DAG depth / in-degree) live at the
bottom; they split the five checks of a follow-up request by their slot (task_idx) and read the
dependency graph of each app from `paths.BENCHMARK`.
"""

from __future__ import annotations

import copy
import json
import statistics as st
from collections import defaultdict
from pathlib import Path

from .paths import BENCHMARK, ensure_data, run_dir
from .scoring import ladder_from_result, load_expected_tasks, request_score, score_ladders

REQUESTS = list(range(1, 11))
FOLLOW_UPS = list(range(2, 11))
THRESHOLDS = list(range(0, 101))  # gate threshold, percent
N_SAMPLES = 32

# ---------------------------------------------------------------- prices ($ / MTok)
# Anthropic: published first-party rates, retrieved 2026-08-25 from
# https://platform.claude.com/docs/en/about-claude/pricing (Model pricing table), as
# (input, cache read, 5m cache write, 1h cache write, output). Every cache write in these runs
# was 5-minute tier. Key = model-id prefix.
ANTHROPIC_PRICES = {
    "claude-haiku-4-5": (1.00, 0.10, 1.25, 2.00, 5.00),
    "claude-sonnet-4-6": (3.00, 0.30, 3.75, 6.00, 15.00),
    "claude-opus-4-8": (5.00, 0.50, 6.25, 10.00, 25.00),
    "claude-fable-5": (10.00, 1.00, 12.50, 20.00, 50.00),
}
# OpenAI-direct (api.openai.com) usage carries token details but no billed cost. Rates derived
# from the OpenRouter arms' billed cost_details on the SAME models (exact round-number fits), as
# (input, cached input, output). Key = substring of the model id.
OPENAI_PRICES = {
    "gpt-5.6-sol": (2.50, 0.20, 10.00),
    "gpt-5.6-terra": (2.50, 0.20, 12.00),
    "gpt-5.6-luna": (0.25, 0.02, 1.20),
}
# z.ai official (api.z.ai) returns no billed cost; published sheet retrieved 2026-08-26 from
# https://docs.z.ai/guides/overview/pricing, as (input, cached input, output).
ZAI_PRICES = {
    "glm-5.2": (1.40, 0.26, 4.40),
    "glm-5.3": (1.40, 0.26, 4.40),
}
# OpenRouter arms (model ids like "openai/gpt-5.6-sol") carry `usage.cost`, the billed USD of
# the call, in every status-200 record; that is summed directly, no price sheet involved.
# A model served on your own GPUs has no billed cost and no price sheet here, so `run_cost`
# returns None for its runs.


# ---------------------------------------------------------------- ladders and gates


def load_ladders(run_id: str, expect: int | None = N_SAMPLES) -> dict[int, dict]:
    """{sample index: {request: request dict}} from every <sample>/result.json of a run."""
    ladders = {}
    for f in sorted(run_dir(run_id).glob("*/result.json")):
        r = json.loads(f.read_text())
        ladders[int(r["index"])] = ladder_from_result(r)
    if expect is not None and len(ladders) != expect:
        raise ValueError(f"{run_id}: expected {expect} results, found {len(ladders)}")
    return ladders


def expected_tasks(dataset: Path = BENCHMARK) -> dict[int, dict[int, int]]:
    """{sample index: {request: number of judge tests}} -- the exact denominators of Q(t)."""
    ensure_data(Path(dataset))
    return load_expected_tasks(str(dataset))


def gate(ladders: dict, threshold: float) -> dict:
    """Replay a tolerance gate offline: the first request scoring below `threshold` (percent)
    or producing no verdict still counts, every later request is 'skipped' (contributes zero)."""
    out = {}
    for sid, by_request in ladders.items():
        gated, kept = False, {}
        for t in REQUESTS:
            request = by_request.get(t)
            if gated:
                kept[t] = {"turn": t, "status": "skipped", "total": 0}
                continue
            kept[t] = copy.deepcopy(request) if request else request
            score = request_score(request)
            if score is None or score < threshold:
                gated = True
        out[sid] = kept
    return out


def requests_before_gate(by_request: dict, threshold: float) -> int:
    """Consecutive requests from the first whose accuracy is at least `threshold` (S(t))."""
    n = 0
    for t in REQUESTS:
        score = request_score(by_request.get(t))
        if score is None or score < threshold:
            break
        n += 1
    return n


def auc(curve: list[float]) -> float:
    """Trapezoid rule over the 1%-step threshold grid, divided by 100 (the grid width)."""
    return sum((curve[i] + curve[i + 1]) / 2 for i in range(len(curve) - 1)) / 100


def quality_sweep(ladders: dict, expected: dict) -> list[float]:
    """Q(t) in percent for every threshold in THRESHOLDS."""
    return [
        score_ladders(gate(ladders, t), REQUESTS, expected_by_sample=expected)["avg_norm"]
        for t in THRESHOLDS
    ]


def survival_sweep(ladders: dict) -> list[float]:
    """S(t), mean requests survived, for every threshold in THRESHOLDS."""
    return [
        sum(requests_before_gate(b, t) for b in ladders.values()) / len(ladders) for t in THRESHOLDS
    ]


def run_scores(ladders: dict, expected: dict) -> dict:
    """raw / norm (ungated), grade (= auc_norm / 100), survival (= auc_turns), and both sweeps."""
    sc = score_ladders(ladders, REQUESTS, expected_by_sample=expected)
    q, s = quality_sweep(ladders, expected), survival_sweep(ladders)
    return {
        "raw": sc["avg_raw"],
        "norm": sc["avg_norm"],
        "auc_norm": auc(q),
        "auc_turns": auc(s),
        "grade": auc(q) / 100,
        "survival": auc(s),
        "q_sweep": q,
        "s_sweep": s,
    }


# ---------------------------------------------------------------- model calls (the wire log)


def iter_requests(run_id: str):
    """Yield (sample index, request, [status-200 call records sorted by ts]) per request.

    Request 1's log sits at <sample>/generation/model_calls.jsonl, request N >= 2 at
    <sample>/turnN/generation/. Requests whose wire log was lost (a pod restart before upload)
    are absent, as they were in the paper's numbers. Only the released fields are read:
    ts, duration_s, status, model, tools, usage.
    """
    for sample in sorted(run_dir(run_id).glob("[0-9]" * 6)):
        idx = int(sample.name)
        for tn in REQUESTS:
            f = (sample if tn == 1 else sample / f"turn{tn}") / "generation" / "model_calls.jsonl"
            if not f.is_file():
                continue
            calls = []
            for line in f.open(errors="replace"):
                try:
                    c = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if c.get("status") == 200:
                    calls.append(c)
            calls.sort(key=lambda c: c.get("ts") or 0)
            yield idx, tn, calls


def output_tokens(call: dict) -> int | None:
    """Provider completion count (reasoning included): usage.output_tokens or completion_tokens."""
    u = call.get("usage")
    if not isinstance(u, dict):
        return None
    v = u.get("output_tokens", u.get("completion_tokens"))
    return int(v) if isinstance(v, (int, float)) else None


def run_call_counts(run_id: str) -> list[int]:
    """Successful model calls per request (the 'turns / request' column, before averaging)."""
    return [len(calls) for _, _, calls in iter_requests(run_id)]


def run_token_triples(run_id: str) -> tuple[list[int], list[int], list[int]]:
    """(text, reasoning, total) output tokens per successful call; three wire schemas aliased."""
    text, think, total = [], [], []
    for _, _, calls in iter_requests(run_id):
        for c in calls:
            u = c.get("usage") or {}
            o = u.get("output_tokens") or u.get("completion_tokens") or 0
            det = u.get("output_tokens_details") or u.get("completion_tokens_details") or {}
            t = det.get("thinking_tokens") or det.get("reasoning_tokens") or 0
            total.append(o)
            think.append(t)
            text.append(o - t)
    return text, think, total


def call_cost(call: dict) -> float | None:
    """USD of one successful call: billed `usage.cost` if present, else token counts x the
    price sheet of its provider. None when the model has no known price (self-hosted)."""
    u = call.get("usage") or {}
    if not u:  # rare empty-usage record (1 seen in g56sol-high) -- tiny undercount
        return 0.0
    if u.get("cost") is not None:
        return float(u["cost"])
    model = call.get("model") or ""
    flat = {**ZAI_PRICES, **OPENAI_PRICES}
    key = next((k for k in flat if k in model), None)
    if key is not None:
        pin_, pcache, pout = flat[key]
        pin = u.get("prompt_tokens") or u.get("input_tokens") or 0
        det = u.get("prompt_tokens_details") or u.get("input_tokens_details") or {}
        cached = det.get("cached_tokens", 0) or 0
        out_t = u.get("completion_tokens") or u.get("output_tokens") or 0
        return ((pin - cached) * pin_ + cached * pcache + out_t * pout) / 1e6
    key = next((k for k in ANTHROPIC_PRICES if model.startswith(k)), None)
    if key is None:
        return None
    inp, cr, cw5, cw1h, out = ANTHROPIC_PRICES[key]
    cc = u.get("cache_creation") or {}
    w5 = cc.get("ephemeral_5m_input_tokens", u.get("cache_creation_input_tokens", 0))
    w1h = cc.get("ephemeral_1h_input_tokens", 0)
    return (
        u.get("input_tokens", 0) * inp
        + u.get("cache_read_input_tokens", 0) * cr
        + w5 * cw5
        + w1h * cw1h
        + u.get("output_tokens", 0) * out
    ) / 1e6


def run_cost(run_id: str) -> float | None:
    """Total generation USD of a run over successful calls; None if any call is unpriceable."""
    total = 0.0
    for _, _, calls in iter_requests(run_id):
        for c in calls:
            v = call_cost(c)
            if v is None:
                return None
            total += v
    return total


def cumulative_tokens_by_step(run_ids: list[str], max_steps: int = 20) -> list[float]:
    """Mean cumulative output tokens per request after agent step k, k = 1..max_steps (Fig. 3c).

    A request that stopped before step k contributes its total from then on, so the last value
    is the mean output tokens per request.
    """
    per_request = []
    for rid in run_ids:
        for _, _, calls in iter_requests(rid):
            toks = [t for t in (output_tokens(c) for c in calls) if t is not None]
            if toks:
                per_request.append(toks)
    out = []
    for k in range(1, max_steps + 1):
        out.append(sum(sum(t[:k]) for t in per_request) / len(per_request))
    return out


# ---------------------------------------------------------------- model rows (Table 2 / App. F)


def mean_std(vals: list[float]) -> tuple[float, float, int]:
    return st.mean(vals), (st.pstdev(vals) if len(vals) > 1 else 0.0), len(vals)


def arm_metrics(run_ids: list[str], expected: dict) -> dict:
    """Per-run scalars, then {metric: (mean, population std, n)} across the replicates.

    Metrics: grade, survival, auc_norm, auc_turns, raw, norm, turns_per_request, cost_per_sample
    (None if a run has no priceable cost). Per-run values are returned under "runs".
    """
    per_run = []
    for rid in run_ids:
        lad = load_ladders(rid)
        sc = run_scores(lad, expected)
        calls = run_call_counts(rid)
        cost = run_cost(rid)
        per_run.append(
            {
                "run": rid,
                "grade": sc["grade"],
                "survival": sc["survival"],
                "auc_norm": sc["auc_norm"],
                "auc_turns": sc["auc_turns"],
                "raw": sc["raw"],
                "norm": sc["norm"],
                "turns_per_request": st.mean(calls) if calls else 0.0,
                "cost_per_sample": cost / N_SAMPLES if cost is not None else None,
                "q_sweep": sc["q_sweep"],
                "s_sweep": sc["s_sweep"],
            }
        )
    out = {"runs": per_run}
    for k in ("grade", "survival", "auc_norm", "auc_turns", "raw", "norm", "turns_per_request"):
        out[k] = mean_std([r[k] for r in per_run])
    costs = [r["cost_per_sample"] for r in per_run]
    out["cost_per_sample"] = None if any(c is None for c in costs) else mean_std(costs)
    return out


# ---------------------------------------------------------------- Table 4: Grade by test type
# Every follow-up request (2-10) carries five checks: task_idx 0-2 functional (exact-value +
# feature), 3 integration (the DAG's own check), 4 backward. The slot-3 check of a
# request with NO incoming DAG edge has nothing earlier to integrate with and verifies one of the
# app's global rules instead; it is scored as "global_rule", not integration.

VERDICT_W = {"yes": 1.0, "partial": 0.5, "no": 0.0}
GROUPS = ("functional", "integration", "global_rule", "backward")
TABLE4_GROUPS = ("backward", "functional", "integration")  # paper column order


def benchmark_rows(dataset: Path = BENCHMARK) -> list[dict]:
    """The 32 apps in run-index order (run sample index N == row position N, 1-based)."""
    ensure_data(Path(dataset))
    return [json.loads(line) for line in Path(dataset).open(encoding="utf-8") if line.strip()]


def incoming(row: dict, request: int) -> list[dict]:
    return [e for e in row["dependency_graph"]["edges"] if e["to"] == f"R{request}"]


def global_rule_requests(rows: list[dict] | None = None) -> set[tuple[int, int]]:
    """{(sample index, request)} of follow-up requests whose slot-3 check is a global-rule check."""
    rows = rows or benchmark_rows()
    out = set()
    for i, row in enumerate(rows, start=1):
        for fu_i in range(len(row["follow_ups"])):
            request = fu_i + 2
            if not incoming(row, request):
                out.add((i, request))
    return out


def check_group(idx: int, request: int, task_idx: int, gr_requests: set) -> str | None:
    if task_idx == 3:
        return "global_rule" if (idx, request) in gr_requests else "integration"
    if task_idx == 4:
        return "backward"
    if task_idx in (0, 1, 2):
        return "functional"
    return None


def per_app_request_groups(run_id: str, gr_requests: set) -> dict:
    """app -> {"all": request -> overall accuracy, "grp": request -> {group: accuracy | None},
    "present": request -> groups the dataset gives this request}. Unjudged group scores 0 when
    the dataset has it on the request; a group with no slot on the request is None."""
    out = {}
    for f in sorted(run_dir(run_id).glob("*/result.json")):
        r = json.loads(f.read_text())
        idx = int(r["index"])
        for request in r.get("turns", []):
            tn = request.get("turn")
            if not tn:
                continue
            cell = {g: [0.0, 0] for g in GROUPS}
            tot = [0.0, 0]
            for t in request.get("tasks", []):
                v = VERDICT_W.get(t.get("verdict"))
                if v is None:
                    continue
                tot[0] += v
                tot[1] += 1
                g = check_group(idx, tn, t.get("task_idx"), gr_requests) if tn >= 2 else None
                if g:
                    cell[g][0] += v
                    cell[g][1] += 1
            if not tot[1]:
                continue
            app = out.setdefault(
                idx,
                {
                    "grp": {},
                    "all": {},
                    "present": {
                        t: {check_group(idx, t, ti, gr_requests) for ti in range(5)}
                        for t in FOLLOW_UPS
                    },
                },
            )
            app["all"][tn] = tot[0] / tot[1]
            if tn >= 2:
                present = app["present"][tn]
                app["grp"][tn] = {
                    g: (cell[g][0] / cell[g][1] if cell[g][1] else 0.0 if g in present else None)
                    for g in GROUPS
                }
    return out


def replay_group(app: dict, group: str, th: float) -> tuple[list[float], int]:
    """([group accuracy per follow-up cell carrying the group], follow-up requests survived) under
    the SHARED gate: the overall five-check accuracy decides progression, so every group dies on
    the same request and only the numerator is group-specific. A cell scores 0 once the ladder is
    dead or the request was unjudged."""
    t1 = app["all"].get(1)
    alive = not (t1 is None or t1 * 100 < th)
    cells, survived = [], 0
    for t in FOLLOW_UPS:
        if group not in app["present"][t]:
            continue
        overall = app["all"].get(t)
        s = app["grp"].get(t, {}).get(group)
        cells.append(0.0 if (not alive or overall is None) else s)
        if alive and (overall is None or overall * 100 < th):
            alive = False
        elif alive:
            survived += 1
    return cells, survived


def grade_by_type(run_ids: list[str], gr_requests: set | None = None) -> dict:
    """{group: (mean, std, n) of the group's Grade over the runs} for one model, plus
    "survival" (shared gate, one per model). Grade on [0, 1]."""
    gr_requests = global_rule_requests() if gr_requests is None else gr_requests
    runs = [per_app_request_groups(rid, gr_requests) for rid in run_ids]
    out = {}
    for g in GROUPS:
        per_run = []
        for r in runs:
            curve = [
                st.mean([c for app in r.values() for c in replay_group(app, g, th)[0]]) * 100
                for th in THRESHOLDS
            ]
            per_run.append(auc(curve) / 100)
        out[g] = mean_std(per_run)
    surv = []
    for r in runs:
        curve = [
            st.mean([replay_group(app, GROUPS[0], th)[1] for app in r.values()])
            for th in THRESHOLDS
        ]
        surv.append(auc(curve))
    out["survival"] = mean_std(surv)
    return out


# ---------------------------------------------------------------- Figure 4: DAG position

FIG4_REQUESTS = (8, 9, 10)


def structure(row: dict) -> tuple[dict[int, int], dict[int, int]]:
    """(depth, in-degree) per request 1..10 from the app's dependency_graph. depth = longest
    dependency chain ending at the request (R1 = 0; no incoming edge = 0)."""
    inc = defaultdict(list)
    for e in row["dependency_graph"]["edges"]:
        inc[int(e["to"][1:])].append(int(e["from"][1:]))
    depth = {1: 0}
    for t in range(2, 11):
        depth[t] = max((depth[p] + 1 for p in inc[t]), default=0)
    return depth, {t: len(inc[t]) for t in range(1, 11)}


def request_scores(run_ids: list[str], requests=FIG4_REQUESTS) -> dict:
    """{(sample index, request): [accuracy % per run in which the request was judged]}."""
    out = defaultdict(list)
    for rid in run_ids:
        for f in sorted(run_dir(rid).glob("*/result.json")):
            r = json.loads(f.read_text())
            idx = int(r["index"])
            for request in r.get("turns", []):
                tn = request.get("turn")
                if tn not in requests:
                    continue
                w = [
                    VERDICT_W[t["verdict"]]
                    for t in request.get("tasks", [])
                    if t.get("verdict") in VERDICT_W
                ]
                if w:
                    out[(idx, tn)].append(st.mean(w) * 100)
    return out


def dag_points(run_ids: list[str], axis: str, rows: list[dict] | None = None) -> dict:
    """{request: {x: (mean accuracy %, n apps)}} on axis "depth" or "indeg"; each app's score is
    first averaged over the runs that judged it."""
    rows = rows or benchmark_rows()
    struct = {i: structure(row) for i, row in enumerate(rows, start=1)}
    bucket = defaultdict(list)
    for (idx, tn), per_run in request_scores(run_ids).items():
        x = struct[idx][0 if axis == "depth" else 1][tn]
        bucket[(tn, x)].append(st.mean(per_run))
    out = defaultdict(dict)
    for (tn, x), vals in bucket.items():
        out[tn][x] = (st.mean(vals), len(vals))
    return out


def wls(pts: dict) -> tuple[float, float, tuple[int, int]]:
    """Weighted least-squares (slope, intercept, (x min, x max)) over {request: {x: (y, n)}}."""
    xs, ys, ws = [], [], []
    for per_request in pts.values():
        for x, (y, n) in per_request.items():
            xs.append(x)
            ys.append(y)
            ws.append(n)
    wsum = sum(ws)
    mx = sum(w * x for w, x in zip(ws, xs)) / wsum
    my = sum(w * y for w, y in zip(ws, ys)) / wsum
    sxx = sum(w * (x - mx) ** 2 for w, x in zip(ws, xs))
    sxy = sum(w * (x - mx) * (y - my) for w, x, y in zip(ws, xs, ys))
    slope = sxy / sxx if sxx else float("nan")
    return slope, my - slope * mx, (min(xs), max(xs))
