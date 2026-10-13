#!/usr/bin/env bash
# Run one EvoWeb app ladder (one sample: 1 build request + 9 follow-up requests) end-to-end.
#
# Usage (Docker, see run_local.sh for N ladders in parallel):
#   docker run --rm -e SAMPLE_INDEX=1 -e API_KEY=sk-... -e EVAL_API_KEY=sk-ant-... \
#       -v $PWD/runs/my-run:/output evoweb-harness:latest
#
# Usage (bare metal, see run_bare_metal.md):
#   SAMPLE_INDEX=1 API_KEY=sk-... EVAL_API_KEY=sk-ant-... OUTPUT_DIR=$PWD/runs/my-run bash run_sample.sh
#
# Environment variables (paper defaults in brackets; see README.md for the full table):
#   SAMPLE_INDEX  (required)  1-based row of the dataset (1-32 for evoweb_benchmark.jsonl)
#   API_KEY       (required)  API key for the model under test
#   MODEL         [anthropic/claude-sonnet-4-6]   generation model id (Anthropic: anthropic/claude-...; OpenRouter/OpenAILike: openai/<id>)
#   PROVIDER      [Anthropic]           Anthropic | OpenAILike | OpenRouter
#   API_URL       []                    base URL for OpenAI-compatible endpoints (OpenAILike/OpenRouter); empty = Anthropic API
#   EVAL_API_KEY  [API_KEY]             judge API key (the paper's judge is Claude Sonnet 4.6 on the Anthropic API)
#   EVAL_MODEL    [claude-sonnet-4-6]   judge model
#   EVAL_API_URL  [https://api.anthropic.com]
#   EVAL_PROVIDER []                    openai | anthropic; empty = inferred from EVAL_API_URL
#   JSONL_FILE    [evoweb_benchmark.jsonl]     dataset: a file under ../data/ or ../tests/smoke_sets/, or a path
#   GENERATOR     [openhands]           openhands | bash | mini_swe_agent | claude_code
#   MAX_TOKENS    [64000]
#   AGENT_MAX_TURNS           [20]      agent turn budget per user request
#   AGENT_MAX_OUTPUT_TOKENS   [64000]   openhands sampling pin: output ceiling (Anthropic routes)
#   AGENT_THINKING_BUDGET     [16000]   openhands sampling pin: thinking budget (Anthropic routes)
#   OPENHANDS_REASONING_EFFORT [high]   effort pin for adaptive-only Claude models and reasoning routes
#   HARNESS_SAMPLING_PIN      [64000:16000] capture-proxy pin for Anthropic upstreams (all harnesses)
#   HARNESS_THINKING          []        "" = pass-through (pins authoritative) | off | force
#   WEBGEN_EFFICIENCY_NUDGE   [on]
#   WEBGEN_NAV_GUIDANCE       [on]   page-registration guidance: on = the paper's Anthropic
#                                    image (add a nav <Link> per page), off = later images
#   WEBGEN_TURN_TIMEOUT       [10800]   wall-clock kill switch per user request (s)
#   HARNESS_LLM_TIMEOUT       [1200]    per-call client deadline (s); must stay below WEBGEN_PROXY_TIMEOUT
#   WEBGEN_PROXY_TIMEOUT      [1800]
#   UV_EXCLUDE_NEWER          [2026-08-20T11:00:00Z] the harness venv resolution horizon (the paper's main runs)
#   EXTENSIONS_REF            [v0.17.0]  OpenHands public-skills registry release (the paper's main runs)
#   OUTPUT_DIR    [/output]             artifacts: $OUTPUT_DIR/<SAMPLE_INDEX:06d>/result.json, turn<N>/...
#   S3_BUCKET     [none]                optional upload + checkpoint bucket; "none"/empty = disabled
#   RUN_ID        []                    only used for the S3 prefix
#
# Output layout under $OUTPUT_DIR (same as the released traces):
#   <SAMPLE_INDEX:06d>/result.json                   per-request verdicts, cost, error class, ladder status
#   <SAMPLE_INDEX:06d>/generation/model_calls.jsonl  request 1: every model call off the wire
#   <SAMPLE_INDEX:06d>/turn<N>/generation/...        request N>=2
#   <SAMPLE_INDEX:06d>/eval/, turn<N>/eval/          judge screenshots + logs
#   acp-workspaces/sample_<SAMPLE_INDEX:06d>/        the app being built (shared across requests)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="${DATA_DIR:-$(cd "${SCRIPT_DIR}/.." && pwd)/data}"

: "${SAMPLE_INDEX:?SAMPLE_INDEX is required (1-based row of the dataset)}"

# One inspection video per RUN: only the first pod (Indexed-Job completion
# index 0, injected by k8s) records; local runs (no JOB_COMPLETION_INDEX)
# are unaffected. In-process, run_single_sample also records only its first
# eval — together: exactly one video per run.
if [ -n "${JOB_COMPLETION_INDEX:-}" ] && [ "${JOB_COMPLETION_INDEX}" != "0" ]; then
  export WEBGEN_RECORD_VIDEO=0
fi

# Prefer an explicit override over a key mounted by the environment.
if [ -n "${API_KEY_OVERRIDE:-}" ]; then
    API_KEY="$API_KEY_OVERRIDE"
fi
: "${API_KEY:?API_KEY is required (the key for the model under test)}"
# Keys reach run_single_sample.py through the environment only: a command-line argument is
# visible to every user on the host in `ps`.
export API_KEY
[ -n "${EVAL_API_KEY:-}" ] && export EVAL_API_KEY

# The benchmark (and JSONL_FILE) from Hugging Face, plus the smoke sets, where this script reads them.
export EVOWEB_DATA="$DATA_DIR" SMOKE_DIR="${SMOKE_DIR:-$(cd "${SCRIPT_DIR}/.." && pwd)/tests/smoke_sets}"
python3 "${SCRIPT_DIR}/make_tasksets.py" ${JSONL_FILE:+"$JSONL_FILE"}

MODEL="${MODEL:-anthropic/claude-sonnet-4-6}"
PROVIDER="${PROVIDER:-Anthropic}"
MAX_TOKENS="${MAX_TOKENS:-64000}"
OUTPUT_DIR="${OUTPUT_DIR:-/output}"
GENERATOR="${GENERATOR:-openhands}"
EVAL_MODEL="${EVAL_MODEL:-claude-sonnet-4-6}"
EVAL_API_URL="${EVAL_API_URL:-https://api.anthropic.com}"
JSONL_FILE="${JSONL_FILE:-evoweb_benchmark.jsonl}"
S3_BUCKET="${S3_BUCKET:-none}"
# Judge wire format, inferred from the judge URL exactly as the paper's runs did (so an
# OpenRouter/OpenAILike model judged by Claude on api.anthropic.com works without extra flags).
if [ -z "${EVAL_PROVIDER:-}" ]; then
    case "$EVAL_API_URL" in
        *anthropic.com*) EVAL_PROVIDER="anthropic" ;;
        *)               EVAL_PROVIDER="openai" ;;
    esac
fi

# --- Paper sampling policy (what the k8s pod template exported; see README.md table) ---
# Agent turn budget per user request; read as max_steps in run_single_sample / generators/backend.py.
export AGENT_MAX_TURNS="${AGENT_MAX_TURNS:-20}"
# openhands/entry.py pin_sampling: registers the served model and pins BOTH numbers so every
# Anthropic model sends the same output ceiling and thinking budget (adaptive-only models get
# OPENHANDS_REASONING_EFFORT instead — decided inside pin_sampling, never hand-tuned).
export OPENHANDS_MAX_OUTPUT_TOKENS="${OPENHANDS_MAX_OUTPUT_TOKENS:-${AGENT_MAX_OUTPUT_TOKENS:-64000}}"
export OPENHANDS_THINKING_BUDGET="${OPENHANDS_THINKING_BUDGET:-${AGENT_THINKING_BUDGET:-16000}}"
export OPENHANDS_REASONING_EFFORT="${OPENHANDS_REASONING_EFFORT:-high}"
# Capture-proxy pins (generators/capture.py), the seam every harness passes through.
# HARNESS_THINKING: "" = pass-through (the pins above are authoritative), "off" = strip thinking,
# "force" = uniform proxy injection of HARNESS_THINKING_BUDGET.
export HARNESS_THINKING="${HARNESS_THINKING:-}"
export HARNESS_THINKING_BUDGET="${HARNESS_THINKING_BUDGET:-}"
# "<ceiling>:<budget>" for ANTHROPIC upstreams only (ignored elsewhere). Set to "" for
# adaptive-only Claude models (opus-4-8 / opus-5 / fable), which reject {"type": "enabled"}.
export HARNESS_SAMPLING_PIN="${HARNESS_SAMPLING_PIN-64000:16000}"
export HARNESS_REASONING_EFFORT="${HARNESS_REASONING_EFFORT:-}"
export HARNESS_ANTHROPIC_EFFORT="${HARNESS_ANTHROPIC_EFFORT:-}"
export MINI_MODEL_CLASS="${MINI_MODEL_CLASS:-}"
export WEBGEN_EFFICIENCY_NUDGE="${WEBGEN_EFFICIENCY_NUDGE:-on}"
export WEBGEN_NAV_GUIDANCE="${WEBGEN_NAV_GUIDANCE:-on}"
export WEBGEN_TURN_TIMEOUT="${WEBGEN_TURN_TIMEOUT:-10800}"
export HARNESS_LLM_TIMEOUT="${HARNESS_LLM_TIMEOUT:-1200}"
export WEBGEN_PROXY_TIMEOUT="${WEBGEN_PROXY_TIMEOUT:-1800}"
# The harness venvs are resolved by uv at start; freeze the horizon so a new PyPI release
# cannot change what the agent runs on.
# Two inputs of the agent are fetched at run time, not pinned by any package: the venv that
# `uv` resolves for OpenHands at container start (openhands==1.16.0 pins the SDK, not its server
# or litellm), and the public skills registry github.com/OpenHands/extensions, which OpenHands
# clones at `main` and injects into the agent's system prompt. Left floating, both drift with the
# calendar and a re-run is not the paper's agent. Pinned to their state at the paper's
# Anthropic runs (2026-08-20): registry release v0.17.0, packages as of 2026-08-20 11:00 UTC.
# EXTENSIONS_REF must be a branch or TAG: the clone is `git clone --depth 1 --branch <ref>`, so a
# commit hash fails and the agent silently runs with no public skills at all.
export UV_EXCLUDE_NEWER="${UV_EXCLUDE_NEWER:-2026-08-20T11:00:00Z}"
export EXTENSIONS_REF="${EXTENSIONS_REF:-v0.17.0}"

# Find the right Python: harness venv > PYTHON_PATH env > system python3
if [ -n "${PYTHON_PATH:-}" ]; then
    PYTHON="$PYTHON_PATH"
elif [ -x "${SCRIPT_DIR}/.venv/bin/python" ]; then
    PYTHON="${SCRIPT_DIR}/.venv/bin/python"
else
    PYTHON="python3"
fi

# Auto-detect chromedriver if not set
if [ -z "${CHROMEDRIVER_BIN:-}" ] && [ -f "${SCRIPT_DIR}/.chromedriver_path" ]; then
    export CHROMEDRIVER_BIN="$(cat "${SCRIPT_DIR}/.chromedriver_path")"
fi

# Dataset: JSONL_FILE takes precedence over TEST_DATA_URL (remote download). It is a file under
# ../data/ (the benchmark and its translations), under ../tests/smoke_sets/ (written by
# make_tasksets.py), or a path. Both end up in --jsonl-path for run_single_sample.py.
SMOKE_DIR="${SMOKE_DIR:-$(cd "${SCRIPT_DIR}/.." && pwd)/tests/smoke_sets}"
JSONL_PATH_ARG=""
if [ -n "${JSONL_FILE:-}" ]; then
    CANDIDATE=""
    for c in "${JSONL_FILE}" "${DATA_DIR}/${JSONL_FILE}" "${SMOKE_DIR}/${JSONL_FILE}"; do
        if [ -f "$c" ]; then CANDIDATE="$c"; break; fi
    done
    if [ -z "$CANDIDATE" ]; then
        echo "[run_sample] ERROR: JSONL_FILE='${JSONL_FILE}' not found under ${DATA_DIR} or ${SMOKE_DIR}" >&2
        echo "[run_sample]        smoke sets: run 'python3 ${SCRIPT_DIR}/make_tasksets.py'" >&2
        exit 1
    fi
    echo "[run_sample] Using JSONL: ${CANDIDATE}"
    JSONL_PATH_ARG="$CANDIDATE"
elif [ -n "${TEST_DATA_URL:-}" ]; then
    DEST="${DATA_DIR}/_remote.jsonl"
    echo "[run_sample] Downloading ${TEST_DATA_URL} -> ${DEST}"
    curl -fsSL "$TEST_DATA_URL" -o "$DEST"
    JSONL_PATH_ARG="$DEST"
fi

echo "[run_sample] sample=${SAMPLE_INDEX} model=${MODEL} provider=${PROVIDER} generator=${GENERATOR} judge=${EVAL_MODEL} output=${OUTPUT_DIR}"

# Build the command
CMD=(
    "$PYTHON" "${SCRIPT_DIR}/run_single_sample.py"
    --index "$SAMPLE_INDEX"
    --model "$MODEL"
    --provider "$PROVIDER"
    --max-tokens "$MAX_TOKENS"
    --output-dir "$OUTPUT_DIR"
    --python-path "$PYTHON"
    --generator "$GENERATOR"
    --eval-model "$EVAL_MODEL"
    --eval-api-url "$EVAL_API_URL"
)

[ -n "${API_URL:-}" ]       && CMD+=(--api-url "$API_URL")
[ -n "${EVAL_PROVIDER:-}" ] && CMD+=(--eval-provider "$EVAL_PROVIDER")
[ -n "${RUN_ID:-}" ]        && CMD+=(--run-id "$RUN_ID")
# Appearance grading is opt-in: only runs when APPEARANCE_API_MODEL is set (and never on
# multi-request ladders). URL/key fall back to EVAL_API_URL/EVAL_API_KEY inside run_single_sample.py.
[ -n "${APPEARANCE_API_MODEL:-}"     ] && CMD+=(--appearance-api-model "$APPEARANCE_API_MODEL")
[ -n "${APPEARANCE_API_URL:-}"       ] && CMD+=(--appearance-api-url "$APPEARANCE_API_URL")
[ -n "${APPEARANCE_API_KEY:-}"       ] && CMD+=(--appearance-api-key "$APPEARANCE_API_KEY")
[ -n "${APPEARANCE_MAX_SHOTS:-}"     ] && CMD+=(--appearance-max-shots "$APPEARANCE_MAX_SHOTS")
[ -n "${APPEARANCE_VIEWPORT_HEIGHT:-}" ] && CMD+=(--appearance-viewport-height "$APPEARANCE_VIEWPORT_HEIGHT")
[ -n "${APPEARANCE_PAUSE:-}"         ] && CMD+=(--appearance-pause "$APPEARANCE_PAUSE")

[ -n "$JSONL_PATH_ARG" ]                && CMD+=(--jsonl-path "$JSONL_PATH_ARG")
[ "${SKIP_UI_EVAL:-0}" = "1" ]          && CMD+=(--skip-ui-eval)

# S3 is opt-in: "none"/empty disables upload and checkpoint restore.
if [ -n "$S3_BUCKET" ] && [ "$S3_BUCKET" != "none" ]; then
    CMD+=(--s3-bucket "$S3_BUCKET")
fi

exec "${CMD[@]}"
