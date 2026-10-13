"""EvoWeb turn scoring: the metric arithmetic and the error classification behind it.

This module is the single definition of the arithmetic. The harness (`harness/scoring.py`, a
byte-identical copy that it imports at run time) and the analysis code in `evoweb/` both use it, so
a run and a re-score of its traces cannot disagree. Do not re-implement any of it elsewhere.

THE CONVENTION
--------------
A turn's score is always ``(yes + 0.5*partial) / tasks``. What differs between metrics is only which
turns are counted and what a non-scoring turn contributes.

``raw`` -- **survivor**: mean over turns that actually produced a verdict. Errored and gated turns are
    excluded, not zeroed. Answers *"when it ran, how good was it?"*.

``delivered`` -- **normalised**: an errored **or** gated turn contributes **0**, over the full expected
    denominator (``samples * tasks_per_turn``). Answers *"how much of the expected work actually
    shipped?"*. Gate-faithful by construction: once a ladder dies its later turns are absent and
    therefore score 0.

``norm`` -- the same quantity written as ``raw * evaluated / samples``, where ``evaluated`` counts the
    turns that produced a verdict (errored turns are NOT evaluated: they delivered nothing). With a
    uniform task count this is algebraically identical to ``delivered``. ``norm`` is the number the
    paper's Q(t) reads (``score_ladders(...)["avg_norm"]`` in `evoweb/metrics.py`); ``legacy_norm``
    keeps an older definition that counted errored turns as evaluated, for reconciling old logs only.

Infra censoring (``censor_infra=True``): a turn that failed for infrastructure reasons (connection
    reset, read timeout, provider rate limit) is not evidence about the model, so it is dropped from
    every metric -- as are that ladder's later turns, which the model never got to attempt. Callers
    may supply the classification via ``infra_turns``; by default it is read from each turn's recorded
    ``error_class`` (see the error classification section).

VARIABLE TASK COUNTS
--------------------
Follow-up turns (T2+) carry exactly 5 validation tasks each, but **turn 1 (the original WebGen-Bench
build) does not**: observed counts range 4-11 per app (mode 6, mean ~6.4). So ``delivered`` must
never use ``samples * 5``; it takes an explicit ``expected_tasks`` denominator. A gated or errored
turn logged no task count, so the aggregator infers the missing ones from the median observed count
for that turn unless the caller supplies ``tasks_per_turn`` (safe only for T2+) or ``expected_tasks``
(always preferred -- e.g. from the dataset's ``ui_instruct`` lengths via ``load_expected_tasks``).
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable
from pathlib import Path

# ---------------------------------------------------------------------------
# Status vocabulary
# ---------------------------------------------------------------------------

# Turn status values that mean "this turn was never attempted": the harness writes "skipped" for
# the turns after a ladder died, and the offline gate replay (evoweb/metrics.py) writes the same.
GATED_STATUSES = ("skipped",)

# Validation tasks per follow-up turn; the fallback when nothing observed can tell us.
DEFAULT_TASKS_PER_TURN = 5

# ---------------------------------------------------------------------------
# Error classification
# ---------------------------------------------------------------------------
# A turn that failed tells you nothing about the model unless you know WHY it failed. The harness
# classifies at failure time, with the exception in hand, and records the class in result.json as
# `error_class`; grepping logs afterwards is the fallback for runs that predate that. INFRA_CLASSES
# are censored from metrics; MODEL_CLASSES count as real failures.
INFRA_CLASSES = (
    "provider_overloaded",  # HTTP 529 / "Overloaded"
    "provider_rate_limit",  # HTTP 429 / RateLimitError
    "provider_connection",  # peer closed mid-stream, read timeout, connection reset
    "provider_payment",  # HTTP 402 / exhausted balance
    "provider_not_found",  # route missing / wrong backend model name
    "provider_auth",  # expired or incorrect API key, expired signed dataset URL
    "harness",  # an orchestration bug on the benchmark's own side
)
MODEL_CLASSES = (
    "model_repetition",  # degenerate repetition loop (the detector aborts the stream)
    "model_bad_tool_json",  # malformed tool-call arguments
    "context_exceeded",  # the model's own context growth blew the window
)

# Retry policy hinges on this split, so it is part of the data model rather than the caller's guess.
# FATAL: no number of retries can succeed -- the credential, route or budget is wrong. Retrying a
# fatal failure is expensive and hides the cause; the right response is to abort loudly.
# TRANSIENT: the provider was momentarily unwilling; a retry after a cooldown is legitimate.
# `harness` is fatal: an orchestration bug does not fix itself on the next attempt.
FATAL_INFRA = ("provider_auth", "provider_payment", "provider_not_found", "harness")
TRANSIENT_INFRA = ("provider_overloaded", "provider_rate_limit", "provider_connection")

# Matched against the lowercased exception text or log line; order matters (first hit wins).
# Needles must not be words an app spec, a prompt or a judge transcript could plausibly contain:
# a false infra hit censors the turn, which deletes a real model failure and inflates the score.
_ERROR_PATTERNS = (
    ("model_repetition", ("repeating the same chunk",)),
    (
        "model_bad_tool_json",
        (
            "unterminated string",
            "input validation error",
            "expecting ',' delimiter",
            "invalid control character",
        ),
    ),
    (
        "context_exceeded",
        (
            "contextwindowexceeded",
            "context_length_exceeded",
            "prompt is too long",
            "maximum context length",
        ),
    ),
    # Auth before payment and rate_limit: an expired key can surface as a 401/403 alongside other
    # numbers in the same traceback, and mistaking it for a rate limit would prescribe a retry.
    (
        "provider_auth",
        (
            "token expired or incorrect",
            "authenticationerror",
            "expiredtoken",
            "invalid api key",
            "incorrect api key",
            "401",
            "403",
            "permissionerror",
            "the security token included in the request",
        ),
    ),
    # Payment before rate_limit on purpose: some providers wrap an EMPTY-BALANCE failure in HTTP 429
    # (e.g. "429 - {'code': ..., 'message': 'Insufficient balance or no resource package. Please
    # recharge.'}"). Read as a rate limit it prescribes "lower parallelism and retry", which can
    # never succeed. NOT "insufficient balance" alone: that is banking-app product vocabulary
    # ("the system refuses if insufficient balance" has appeared in a generated app spec); the
    # empty-balance message is still caught by "no resource package" and "please recharge".
    (
        "provider_payment",
        (
            "402",
            "payment required",
            "insufficient credit",
            "no resource package",
            "please recharge",
        ),
    ),
    # NOT the bare phrase "does not exist": the judge narrates missing pages in the app it is
    # grading ("the instant-quote page does not exist - it returns a 404 error"), which would
    # classify a perfectly healthy run as a dead provider route.
    (
        "provider_not_found",
        ("notfounderror", "model not found", "no such model", "received model group"),
    ),
    ("provider_rate_limit", ("rate limit", "ratelimiterror", "429", "too many requests")),
    # "capacity" alone is NOT usable: the agent log echoes the request text, and a task about
    # "arrival capacity" would read as a provider overload.
    ("provider_overloaded", ("overloaded", "529", "at capacity", "service unavailable")),
    # "idle timeout exceeded" / "midstreamfallbackerror" / "litellm.timeout" are a gateway's
    # mid-stream stall ("Upstream idle timeout exceeded"), which none of the generic needles match
    # ("timed out" never appears in that text). Deliberately NOT the bare word "timeout": app specs
    # say things like "show a timeout error toast".
    (
        "provider_connection",
        (
            "peer closed",
            "readtimeout",
            "read timeout",
            "timed out",
            "idle timeout exceeded",
            "midstreamfallbackerror",
            "litellm.timeout",
            "connection error",
            "connection reset",
            "apiconnectionerror",
            # A network outage on the agent's host mid-generation, seen as
            # "[Errno 101] Network is unreachable". Unclassified errors already censor correctly
            # (unknown is treated as infra), so this needle only improves the audit tables, where
            # "unknown" reads like an unexplained failure rather than a known transient. ONLY the
            # errno: bare "network is unreachable" is a phrase an app spec can plausibly contain
            # ("show a network is unreachable banner"). A miss is harmless; a false positive is not.
            "errno 101",
        ),
    ),
    # Orchestration-level signatures. These appear in a launcher's own output rather than in an
    # agent log, and they matter because a mass failure can leave NO per-cause evidence anywhere
    # the launcher looks (a dead API key, for example, surfaces only inside each container).
    # NOT "no results found": that is a stock UI phrase ("Zero results: clear 'No Results Found'
    # message") which the agent writes into its build plans, and it would flag a known-good run as
    # a harness failure. The zero-success shape below still catches every launcher-level mass
    # failure on its own.
    ("harness", ("aggregation failed for", "one or more model aggregations failed")),
)

# A batch where NOTHING succeeded is a launch failure, not a bad model -- checked separately because
# it is a shape ("0/32 succeeded"), not a phrase.
_ZERO_SUCCESS = re.compile(r"\b0/(\d+) succeeded")

# Lines carrying MODEL OR JUDGE PROSE, which must never be read as infrastructure events. The agent
# and the judge both dump their message transcripts into the log, and they describe app failures in
# exactly the vocabulary providers use: "the page does not exist", "it returns a 404 error", "the
# request failed". Their prose is data about the app under test, not about the infrastructure.
_TRANSCRIPT_MARKERS = (
    "'role': 'assistant'",
    '"role": "assistant"',
    "'role': 'user'",
    '"role": "user"',
    "'role': 'system'",
    '"role": "system"',
    "thought:",
    "action:",
    "observation:",
)

# A bare HTTP code only counts on a line that also reads like a failure. Scanning whole logs (not
# short exception strings) means naked digits collide constantly, and every collision seen so far
# was on a HEALTHY line:
#   `elapsed=529s`                        -> 529  "overloaded"
#   `cost=0.402`                          -> 402  "payment required"
#   `exception_mapping_utils.py, line 402`-> 402  (a traceback line number, on every container)
#   `22:24:53,401 - INFO - Iter: 3`       -> 401  (log timestamp milliseconds, on a CLEAN run)
# That last one reports a healthy run as a fatal auth failure, which is the worst direction of
# error: a false infra hit censors the turn, deleting a real model failure and inflating the
# model's score. Textual needles ("payment required", "rate limit", "too many requests",
# "overloaded") already carry every real case, so the numeric codes are pure backup and are allowed
# to be conservative.
# NOT "status": tool results can be JSON like {"status": "ok", ..., "bytes_written": 401}, which
# puts failure-ish vocabulary and a colliding number on the same healthy line. Context words must
# themselves signal FAILURE; "status" doesn't.
_ERR_CONTEXT = (
    "error",
    "exception",
    "failed",
    "failure",
    "http",
    "denied",
    "unauthor",
    "forbidden",
    "refus",
    "reject",
    "limit",
    "expired",
    "invalid",
)


def classify_error(text: str | None) -> str:
    """Map an exception message (or short log tail) to one of INFRA_CLASSES / MODEL_CLASSES.

    Returns "unknown" for empty text or no match. Checked model-first: a repetition loop surfaces
    wrapped in APIConnectionError, so matching the connection pattern first would misfile real
    model failures as infrastructure. For a whole log file use `classify_from_log`.
    """
    if not text:
        return "unknown"
    low = text.lower()
    for cls, needles in _ERROR_PATTERNS:
        if any(n in low for n in needles):
            return cls
    return "unknown"


def classify_from_log(text: str | None) -> str:
    """Attribute a turn's failure from its full log, for runs that predate `error_class` recording.

    NOT the same as classify_error(text): a raw log holds prompt echoes, UI specs and judge
    transcripts, so it must go through scan_log's line filters (transcript markers, numeric-context
    guards); feeding a whole log to classify_error would trip on exactly the prose false positives
    the scanner guards against. Precedence over the surviving hits is the SCORING one: model first,
    so a provider wrapper cannot let a bad model off the hook; then fatal infra (it explains every
    failure around it); then transient. Returns an error class or "unknown".
    """
    hits = scan_log(text)
    for group in (MODEL_CLASSES, FATAL_INFRA, TRANSIENT_INFRA):
        found = [c for c in group if c in hits]
        if found:
            return max(found, key=lambda c: hits[c]["count"])
    return "unknown"


def is_infra(error_class: str | None) -> bool:
    """Unknown counts as infra: safer to censor an unexplained failure than to blame the model."""
    return error_class in INFRA_CLASSES or error_class in (None, "", "unknown")


def _needle_hit(needle: str, low: str) -> bool:
    """Substring match, except a bare numeric code must be a standalone token on a failure line.

    Numeric needles are rejected when preceded by ``line ``, a word char, or ``. , = : -``, when
    followed by a word char or ``.``, or when the line carries no failure vocabulary at all. See
    ``_ERR_CONTEXT`` above for why each guard exists.
    """
    if needle.isdigit():
        if not any(c in low for c in _ERR_CONTEXT):
            return False
        return re.search(rf"(?<![\w.,=:-])(?<!line ){needle}(?![\w.])", low) is not None
    return needle in low


def scan_log(text: str | None) -> dict[str, dict]:
    """Classify every failure line in a log.

    Returns ``{error_class: {"count": n, "sample": first matching line}}``; empty for a clean log.
    Line-oriented on purpose: a single traceback carries both the real cause ("repeating the same
    chunk") and a wrapper ("APIConnectionError") on separate lines, and classifying the whole blob
    at once would collapse them to whichever pattern happened to be checked first. Per line,
    classify_error's model-first ordering still applies, so the wrapper cannot steal a model
    failure. This is the one log-to-cause mechanism; the harness's judge-log audit and the
    `classify_from_log` / `triage` helpers all build on it.
    """
    hits: dict[str, dict] = {}
    if not text:
        return hits
    zero = _ZERO_SUCCESS.search(text)
    if zero and zero.group(1) != "0":
        hits["harness"] = {
            "count": 1,
            "sample": f"wave finished with 0/{zero.group(1)} samples succeeded -- launch failure, not model behaviour",
        }
    for raw in text.splitlines():
        low = raw.lower()
        if not low.strip():
            continue
        if any(m in low for m in _TRANSCRIPT_MARKERS):
            continue  # model/judge prose, not an infrastructure event -- see _TRANSCRIPT_MARKERS
        for cls, needles in _ERROR_PATTERNS:
            if any(_needle_hit(n, low) for n in needles):
                e = hits.setdefault(cls, {"count": 0, "sample": raw.strip()[:300]})
                e["count"] += 1
                break
    return hits


def triage(hits: dict[str, dict]) -> tuple[str, str | None]:
    """Operational verdict for a scanned log (the output of `scan_log`): what should a launcher do?

    Returns (verdict, dominant_class) where verdict is:
        "fatal"     -- abort; retrying cannot succeed
        "model"     -- a real result; must NOT be retried or it gets silently re-rolled
        "transient" -- provider wobble; a bounded retry after a cooldown is legitimate
        "clean"     -- nothing found (dominant_class is None)

    Precedence here is deliberately NOT the same as classify_from_log's. That one answers a
    scoring question -- "who is to blame for this turn?" -- and puts model first so a wrapper
    exception cannot let a bad model off the hook. triage answers an operations question -- "is it
    worth launching more?" -- and puts fatal first, because a dead key blocks every sample
    regardless of how any one of them happened to fail.
    """
    if not hits:
        return "clean", None
    for cls in FATAL_INFRA:
        if cls in hits:
            return "fatal", cls
    model = [c for c in MODEL_CLASSES if c in hits]
    if model:
        return "model", max(model, key=lambda c: hits[c]["count"])
    transient = [c for c in TRANSIENT_INFRA if c in hits]
    if transient:
        return "transient", max(transient, key=lambda c: hits[c]["count"])
    # Never report clean while hits exist: a class in INFRA_CLASSES but in neither FATAL_INFRA nor
    # TRANSIENT_INFRA must not read as "nothing to do".
    return "fatal", max(hits, key=lambda c: hits[c]["count"])


# ---------------------------------------------------------------------------
# Expected task counts
# ---------------------------------------------------------------------------


def load_expected_tasks(jsonl_path: str | Path) -> dict[int, dict[int, int]]:
    """Exact validation-task counts from a dataset jsonl -> {sample_index: {turn: n_tasks}}.

    The sample index is the 1-based line number of the row (that is how runs name their apps).
    Turn 1 is ``len(ui_instruct)`` (VARIABLE: 4-11 observed) and turn k+1 is
    ``len(follow_ups[k-1]["ui_instruct"])``. Prefer this over any inferred denominator: a gated
    or errored turn records no task count of its own, and guessing one biases `delivered`.
    """
    expected: dict[int, dict[int, int]] = {}
    with open(jsonl_path) as fh:
        for idx, line in enumerate(fh, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except Exception:
                continue
            per_turn = {1: len(row.get("ui_instruct") or [])}
            for k, fu in enumerate(row.get("follow_ups") or [], start=2):
                per_turn[k] = len(fu.get("ui_instruct") or [])
            expected[idx] = per_turn
    return expected


# ---------------------------------------------------------------------------
# Per-turn arithmetic
# ---------------------------------------------------------------------------


def raw_pct(yes: float, partial: float, tasks: int) -> float:
    """Survivor score (percent) over the tasks that were actually judged; 0 when none were."""
    return (yes + 0.5 * partial) / tasks * 100.0 if tasks else 0.0


def delivered_pct(yes: float, partial: float, expected_tasks: float) -> float:
    """Normalised score (percent): errored and gated turns contribute 0.

    `expected_tasks` is the number of validation tasks the turn *should* have produced across all
    samples -- NOT samples * 5. Turn 1 has a variable number of tasks per app (observed 4-11,
    mode 6), so a fixed multiplier is wrong there. Follow-up turns (T2+) happen to be uniformly 5,
    but callers must still pass the expected count.
    """
    return (yes + 0.5 * partial) / expected_tasks * 100.0 if expected_tasks else 0.0


def norm_pct(raw: float, evaluated: int, n_samples: int) -> float:
    """``raw`` scaled by the share of samples that produced a verdict: ``raw * evaluated / n``.

    Equal to `delivered_pct` when every sample has the same task count. `aggregate_turn` passes
    ``evaluated = scored`` (errored turns excluded); passing ``scored + errored`` instead gives the
    older ``legacy_norm``, which flatters error-prone models.
    """
    return raw * evaluated / n_samples if n_samples else 0.0


def turn_score(turn: dict | None) -> float | None:
    """Score (percent) for one turn dict, or None if it produced no verdict.

    None covers gated turns, errored turns and pre-eval failures -- anything without tasks.
    """
    if not turn:
        return None
    if (turn.get("total") or 0) <= 0:
        return None
    return (turn.get("yes", 0) + 0.5 * turn.get("partial", 0)) / turn["total"] * 100.0


def classify_turn(turn: dict | None) -> str:
    """Kind of one turn dict: 'scored' | 'gated' | 'errored' | 'absent' (None or empty)."""
    if not turn:
        return "absent"
    status = turn.get("status", "success")
    if status in GATED_STATUSES:
        return "gated"
    if (turn.get("total") or 0) > 0:
        return "scored"
    return "errored"


# ---------------------------------------------------------------------------
# Aggregation over samples
# ---------------------------------------------------------------------------


def aggregate_turn(
    entries: Iterable[dict | None],
    tasks_per_turn: int | None = None,
    n_samples: int | None = None,
    expected_tasks: float | None = None,
) -> dict:
    """Aggregate one turn across samples.

    entries : per-sample turn dicts (or None where the sample has no such turn)
    n_samples : denominator for `norm`; defaults to len(entries)
    expected_tasks : total tasks the turn should have produced. If omitted it is inferred as
        observed_tasks + missing_turns * (median observed tasks per sample) -- necessary because a
        gated/errored turn records no task count, and turn 1 task counts are VARIABLE (4-11).
        Pass `tasks_per_turn` only for turns known to be uniform (T2+ are all 5).

    Returns a dict with the counts ("samples", "scored", "gated", "errored", "evaluated", "yes",
    "partial", "no", "tasks", "expected_tasks") and the percentages ("raw", "delivered", "norm",
    "legacy_norm").
    """
    entries = list(entries)
    n = n_samples if n_samples is not None else len(entries)

    yes = partial = no = tasks = 0
    scored = gated = errored = 0
    for e in entries:
        kind = classify_turn(e)
        if kind == "absent":
            continue
        if kind == "gated":
            gated += 1
            continue
        if kind == "errored":
            errored += 1
            continue
        scored += 1
        yes += e.get("yes", 0)
        partial += e.get("partial", 0)
        no += e.get("no", 0)
        tasks += e.get("total", 0) or 0

    # An errored turn delivered nothing, so it is NOT `evaluated`. legacy_norm keeps the older
    # value that counted it, so old logs can still be reconciled.
    evaluated = scored
    raw = raw_pct(yes, partial, tasks)

    # Expected-task denominator. A gated/errored turn logs no task count, and turn 1 counts vary per
    # sample, so infer the missing ones from the observed median rather than assuming a constant.
    missing = gated + errored
    if expected_tasks is None:
        if tasks_per_turn is not None:
            expected_tasks = (scored + missing) * tasks_per_turn
        else:
            per_sample = sorted(
                e.get("total", 0) or 0 for e in entries if classify_turn(e) == "scored"
            )
            med = per_sample[len(per_sample) // 2] if per_sample else DEFAULT_TASKS_PER_TURN
            expected_tasks = tasks + missing * med
    delivered = delivered_pct(yes, partial, expected_tasks)
    norm = norm_pct(raw, evaluated, n) if tasks else 0.0
    legacy_norm = norm_pct(raw, scored + errored, n) if tasks else 0.0

    return {
        "samples": scored + gated + errored,
        "scored": scored,
        "gated": gated,
        "errored": errored,
        "evaluated": evaluated,
        "yes": yes,
        "partial": partial,
        "no": no,
        "tasks": tasks,
        "expected_tasks": expected_tasks,
        "raw": raw,
        "delivered": delivered,
        "norm": norm,
        "legacy_norm": legacy_norm,
    }


def score_ladders(
    ladders: dict,
    turns: Iterable[int],
    tasks_per_turn: int | None = None,
    infra_turns: set[tuple] | None = None,
    censor_infra: bool = False,
    expected_by_sample: dict | None = None,
) -> dict:
    """Score a whole run.

    ladders : {sample_id: {turn_number: turn_dict}}
    turns   : ordered turn numbers to report (e.g. (2, 3, 4) or range(2, 11))
    infra_turns : set of (sample_id, turn_number) whose failure was infrastructure-caused. Omit it
        and they are derived from each turn's recorded ``error_class`` (falling back to
        classify_error on its ``error`` / ``error_detail`` text).
    censor_infra : drop those turns AND that ladder's later turns from every metric
    expected_by_sample : {sample_id: {turn: n_tasks}} from load_expected_tasks() -- EXACT
        denominators for `delivered`. Strongly preferred: without it a gated/errored turn's task
        count has to be inferred, which is wrong wherever counts vary per sample (turn 1: 4-11).

    Returns {"total_samples", "turns": {t: aggregate_turn(...)}, "censored_turns",
             "error_classes": {class: n}, "infra_errors", "model_errors",
             "avg_raw", "avg_delivered", "avg_norm"} (the averages are means over `turns`).
    """
    turns = list(turns)
    censored = 0
    if infra_turns is None:
        # Prefer the classification recorded at failure time; fall back to any error text present.
        infra_turns = set()
        for sid, by_turn in ladders.items():
            for t in turns:
                e = by_turn.get(t) or {}
                if classify_turn(e) != "errored":
                    continue
                cls = e.get("error_class") or classify_error(
                    e.get("error") or e.get("error_detail")
                )
                if is_infra(cls):
                    infra_turns.add((sid, t))

    per_sample = {}
    for sid, by_turn in ladders.items():
        censor_from = None
        if censor_infra:
            for t in turns:
                if (sid, t) in infra_turns and classify_turn(by_turn.get(t)) == "errored":
                    censor_from = t
                    break
        kept = {}
        for t in turns:
            if censor_from is not None and t >= censor_from:
                censored += 1
                continue
            kept[t] = by_turn.get(t)
        per_sample[sid] = kept

    # a censored ladder must not inflate the delivered/norm denominator either
    n_by_turn = {t: sum(1 for v in per_sample.values() if t in v) for t in turns}

    out, raws, delivs, norms = {}, [], [], []
    for t in turns:
        exp_total = None
        if expected_by_sample:
            counts = [
                expected_by_sample.get(sid, {}).get(t) for sid, v in per_sample.items() if t in v
            ]
            if any(c is not None for c in counts):
                exp_total = sum(c for c in counts if c is not None)
        agg = aggregate_turn(
            [v.get(t) for v in per_sample.values() if t in v],
            tasks_per_turn=tasks_per_turn,
            n_samples=n_by_turn[t],
            expected_tasks=exp_total,
        )
        out[t] = agg
        raws.append(agg["raw"])
        delivs.append(agg["delivered"])
        norms.append(agg["norm"])

    mean = lambda xs: sum(xs) / len(xs) if xs else 0.0  # noqa: E731
    error_classes: dict[str, int] = {}
    for by_turn in ladders.values():
        for t in turns:
            e = by_turn.get(t) or {}
            if classify_turn(e) != "errored":
                continue
            cls = e.get("error_class") or classify_error(e.get("error") or e.get("error_detail"))
            error_classes[cls] = error_classes.get(cls, 0) + 1
    infra_n = sum(v for k, v in error_classes.items() if is_infra(k))
    model_n = sum(v for k, v in error_classes.items() if not is_infra(k))
    return {
        "total_samples": len(ladders),
        "turns": out,
        "censored_turns": censored,
        "error_classes": error_classes,
        "infra_errors": infra_n,
        "model_errors": model_n,
        "avg_raw": mean(raws),
        "avg_delivered": mean(delivs),
        "avg_norm": mean(norms),
    }


# ---------------------------------------------------------------------------
# Reading result.json and judge output
# ---------------------------------------------------------------------------


def ladder_from_result(result: dict) -> dict:
    """Normalise a sample's result.json into {turn_number: turn_dict}, whichever shape it uses.

    Two shapes exist:
      * multi-turn samples put per-turn dicts in ``result["turns"]``
      * SINGLE-TURN samples (a dataset row with no ``follow_ups``) leave ``turns`` empty and put the
        verdict at the ROOT (``yes``/``partial``/``no``/``total``/``accuracy``), with a flat
        ``generation/`` + ``eval/`` artifact layout instead of ``turn1/...``.
    Without this, every single-turn sample scores as absent -- silently dropping the original
    WebGen-Bench (turn-1-only) numbers from any aggregate. Returns {} when neither shape is present.
    """
    turns = {t.get("turn"): t for t in (result.get("turns") or []) if t.get("turn") is not None}
    if turns:
        return turns
    if (result.get("total") or 0) > 0:
        return {
            1: {
                "turn": 1,
                "status": result.get("status", "success"),
                "yes": result.get("yes", 0),
                "partial": result.get("partial", 0),
                "no": result.get("no", 0),
                "total": result.get("total", 0),
            }
        }
    return {}


def parse_verdict(text: str) -> str:
    """The judge's verdict ("yes" | "no" | "partial") from the text of its final reply.

    A substring test is wrong: the judge reasons check by check ("... - YES ... - NO") before
    stating "Action: ANSWER; PARTIAL". No ANSWER line means "no": guessing from the prose scores
    an unparseable reply up.
    """
    body = text or ""
    stated = re.findall(r"ANSWER\s*\**\s*[;:]\s*\**\s*\[?\s*(YES|NO|PARTIAL)", body, re.I)
    if stated:
        return stated[-1].lower()
    # At the interaction cap the judge is asked for a bare verdict, with no Thought/Action
    # format, so a standalone token is a real answer. Take the LAST one by position, never the
    # first YES anywhere in the prose.
    bare = re.findall(r"(?:^|\n)\s*\**\s*(YES|NO|PARTIAL)\b", body, re.I)
    return bare[-1].lower() if bare else "no"
