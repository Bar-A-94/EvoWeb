#!/usr/bin/env bash
# Serve an open-weights model with vLLM on local GPUs and run EvoWeb against it.
#
#   harness/serve_and_run.sh <hf-model | config.env> <run-id> <samples> <parallelism>
#
# Two forms:
#
#   1. <hf-model>: one server for the agent, the judge (Claude Sonnet 4.6) on the Anthropic API.
#      Needs EVAL_API_KEY. The server knobs come from the environment (GPUS, TP, PORT,
#      SERVED_NAME, VLLM_ARGS, ...; the full list is in harness/vllm_serve.sh):
#
#        EVAL_API_KEY=sk-ant-... GPUS=0,1,2,3 VLLM_ARGS="--kv-cache-dtype fp8" \
#        harness/serve_and_run.sh Qwen/Qwen3.5-397B-A17B-FP8 qwen397b-r1 1-32 8
#
#   2. <config.env>: a shell file setting AGENT_MODEL and the agent's knobs as AGENT_<knob>,
#      and, for a judge served by vLLM too (no API at all), JUDGE_MODEL and JUDGE_<knob>.
#      Shared knobs (VLLM_IMAGE, HF_CACHE, VLLM_DOCKER_ARGS, READY_TIMEOUT) are plain names.
#      See harness/configs/b300-qwen397b.env:
#
#        harness/serve_and_run.sh harness/configs/b300-qwen397b.env qwen-both-r1 1-32 8
#
#   <run-id> <samples> <parallelism>   as in harness/run_local.sh ("1-32" = all apps)
#
# A judge server is started with images enabled (JUDGE_IMAGES, default 4 per prompt) and must
# answer an image question, since WebVoyager sends a screenshot on every step. A server that
# already answers on a role's port is used as is and left running; servers this script started
# are stopped at the end unless KEEP_SERVER=1. The benchmark containers reach the servers
# through the host's first IP (API_HOST overrides). Everything run_local.sh reads (EVAL_MODEL,
# AGENT_MAX_TURNS, ...) passes through unchanged.

set -euo pipefail

if [ $# -ne 4 ]; then
    echo "usage: $0 <hf-model | config.env> <run-id> <samples: '1,4,6' or '1-32'> <parallelism>" >&2
    exit 2
fi
TARGET="$1"; RUN_ID="$2"; SAMPLES="$3"; PAR="$4"
HERE="$(cd "$(dirname "$0")" && pwd)"
KNOBS=(SERVED_NAME GPUS TP PORT VLLM_ARGS TOOL_PARSER REASONING_PARSER MAX_MODEL_LEN IMAGES)

if [ -f "$TARGET" ]; then
    # shellcheck disable=SC1090
    set -a; source "$TARGET"; set +a   # exported: the shared knobs reach vllm_serve.sh
    : "${AGENT_MODEL:?${TARGET} must set AGENT_MODEL}"
else
    AGENT_MODEL="$TARGET"
    for v in "${KNOBS[@]}"; do   # the environment's knobs are the agent's
        [ -n "${!v+x}" ] && declare "AGENT_${v}=${!v}"
    done
fi
unset "${KNOBS[@]}"   # plain knobs were the agent's; they must not leak into the judge's server
AGENT_PORT="${AGENT_PORT:-8003}"; AGENT_SERVED_NAME="${AGENT_SERVED_NAME:-$AGENT_MODEL}"
if [ -n "${JUDGE_MODEL:-}" ]; then
    JUDGE_PORT="${JUDGE_PORT:-8004}"; JUDGE_SERVED_NAME="${JUDGE_SERVED_NAME:-$JUDGE_MODEL}"
    JUDGE_IMAGES="${JUDGE_IMAGES:-4}"
    if [ "$AGENT_PORT" = "$JUDGE_PORT" ]; then
        echo "AGENT_PORT and JUDGE_PORT must differ (two servers)" >&2
        exit 2
    fi
else
    : "${EVAL_API_KEY:?EVAL_API_KEY is required (Anthropic key for the judge), or set JUDGE_MODEL}"
fi
API_HOST="${API_HOST:-$(hostname -I | cut -d' ' -f1)}"

# Start a role's server with that role's knobs mapped onto vllm_serve.sh's names.
serve() {  # serve AGENT|JUDGE -> container name, or "-" when a server was already up
    local r="$1" v n model
    model="${r}_MODEL"
    local -a vars=()
    for v in "${KNOBS[@]}"; do
        n="${r}_${v}"
        [ -n "${!n+x}" ] && vars+=("${v}=${!n}")
    done
    env ${vars[@]+"${vars[@]}"} "${HERE}/vllm_serve.sh" up "${!model}"
}

AGENT_CONTAINER=-; JUDGE_CONTAINER=-
trap '[ "${KEEP_SERVER:-0}" = 1 ] || { "${HERE}/vllm_serve.sh" down "$AGENT_CONTAINER"; "${HERE}/vllm_serve.sh" down "$JUDGE_CONTAINER"; }' EXIT
AGENT_CONTAINER="$(serve AGENT)"
export API_KEY=local PROVIDER=OpenAILike API_URL="http://${API_HOST}:${AGENT_PORT}/v1" MODEL="openai/${AGENT_SERVED_NAME}"
if [ -n "${JUDGE_MODEL:-}" ]; then
    JUDGE_CONTAINER="$(serve JUDGE)"
    export EVAL_API_KEY=local EVAL_PROVIDER=openai EVAL_API_URL="http://${API_HOST}:${JUDGE_PORT}/v1" EVAL_MODEL="${JUDGE_SERVED_NAME}"
fi
echo "[serve_and_run] benchmark: MODEL=${MODEL} API_URL=${API_URL} judge=${EVAL_MODEL:-claude-sonnet-4-6} EVAL_API_URL=${EVAL_API_URL:-https://api.anthropic.com}"
"${HERE}/run_local.sh" "$RUN_ID" "$SAMPLES" "$PAR"
