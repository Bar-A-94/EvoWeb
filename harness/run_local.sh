#!/usr/bin/env bash
# Run N EvoWeb app ladders in parallel, one Docker container each.
#
#   harness/run_local.sh <run-id> <samples> <parallelism>
#
#   <run-id>       name of the run; output lands in $EVOWEB_OUT/<run-id>/<sample:06d>/result.json
#   <samples>      comma list ("1,4,6,11") or range ("1-32") of 1-based dataset rows
#   <parallelism>  how many containers run at once
#
# Environment:
#   EVOWEB_OUT    [./runs]                 output root (the container gets -v $EVOWEB_OUT/<run-id>:/output)
#   EVOWEB_IMAGE  [evoweb-harness:latest]  image built from harness/Dockerfile
#   passed through to the container when set:
#     API_KEY (required) MODEL PROVIDER API_URL
#     EVAL_API_KEY EVAL_MODEL EVAL_API_URL EVAL_PROVIDER
#     JSONL_FILE GENERATOR MAX_TOKENS
#     AGENT_MAX_TURNS AGENT_MAX_OUTPUT_TOKENS AGENT_THINKING_BUDGET OPENHANDS_REASONING_EFFORT
#     HARNESS_SAMPLING_PIN HARNESS_THINKING HARNESS_THINKING_BUDGET HARNESS_REASONING_EFFORT
#     HARNESS_ANTHROPIC_EFFORT MINI_MODEL_CLASS
#     WEBGEN_EFFICIENCY_NUDGE WEBGEN_NAV_GUIDANCE WEBGEN_TURN_TIMEOUT HARNESS_LLM_TIMEOUT WEBGEN_PROXY_TIMEOUT
#     UV_EXCLUDE_NEWER EXTENSIONS_REF WEBGEN_RECORD_VIDEO SKIP_UI_EVAL
#   Unset variables fall back to the paper defaults inside run_sample.sh (see README.md).
#
# Example (Claude Sonnet 4.6 as model and judge, 32 ladders, 8 at a time):
#   API_KEY=sk-ant-... EVAL_API_KEY=sk-ant-... harness/run_local.sh sonnet-r1 1-32 8
#
# Example (an OpenRouter model, judge on Anthropic):
#   API_KEY=sk-or-... PROVIDER=OpenRouter API_URL=https://openrouter.ai/api \
#   MODEL=openai/<model> EVAL_API_KEY=sk-ant-... harness/run_local.sh my-run 1,4,6 3

set -euo pipefail

if [ $# -ne 3 ]; then
    echo "usage: $0 <run-id> <samples: '1,4,6' or '1-32'> <parallelism>" >&2
    exit 2
fi
RUN_ID="$1"
SAMPLES_SPEC="$2"
PAR="$3"
: "${API_KEY:?API_KEY is required (the key for the model under test)}"

EVOWEB_OUT="${EVOWEB_OUT:-./runs}"
EVOWEB_IMAGE="${EVOWEB_IMAGE:-evoweb-harness:latest}"
mkdir -p "${EVOWEB_OUT}/${RUN_ID}"
OUT_ABS="$(cd "${EVOWEB_OUT}/${RUN_ID}" && pwd)"

# Expand the sample spec into one index per line.
SAMPLES=()
if [[ "$SAMPLES_SPEC" =~ ^[0-9]+-[0-9]+$ ]]; then
    lo="${SAMPLES_SPEC%-*}"; hi="${SAMPLES_SPEC#*-}"
    for ((i = lo; i <= hi; i++)); do SAMPLES+=("$i"); done
else
    IFS=',' read -ra SAMPLES <<< "$SAMPLES_SPEC"
fi
if [ "${#SAMPLES[@]}" -eq 0 ]; then
    echo "no samples in '$SAMPLES_SPEC'" >&2
    exit 2
fi

# A server on this host (localhost) is host.docker.internal inside the containers.
h=//host.docker.internal
for v in API_URL EVAL_API_URL; do
    if [ -n "${!v:-}" ]; then
        u="${!v/\/\/localhost/$h}"
        export "$v=${u/\/\/127.0.0.1/$h}"
    fi
done

# Environment passthrough: only variables that are set reach the container, so run_sample.sh's
# paper defaults apply to everything the user did not override.
PASS=(
    API_KEY MODEL PROVIDER API_URL
    EVAL_API_KEY EVAL_MODEL EVAL_API_URL EVAL_PROVIDER
    JSONL_FILE GENERATOR MAX_TOKENS
    AGENT_MAX_TURNS AGENT_MAX_OUTPUT_TOKENS AGENT_THINKING_BUDGET OPENHANDS_REASONING_EFFORT
    HARNESS_SAMPLING_PIN HARNESS_THINKING HARNESS_THINKING_BUDGET HARNESS_REASONING_EFFORT
    HARNESS_ANTHROPIC_EFFORT MINI_MODEL_CLASS
    WEBGEN_EFFICIENCY_NUDGE WEBGEN_NAV_GUIDANCE WEBGEN_TURN_TIMEOUT HARNESS_LLM_TIMEOUT WEBGEN_PROXY_TIMEOUT
    UV_EXCLUDE_NEWER EXTENSIONS_REF WEBGEN_RECORD_VIDEO SKIP_UI_EVAL
)
ENV_ARGS=()
for v in "${PASS[@]}"; do
    # `-e NAME` (no value) makes docker copy the variable from this shell, so secrets never
    # appear in the process list or in the echoed command below.
    if [ -n "${!v+x}" ]; then ENV_ARGS+=(-e "$v"); fi
done

# Every container shares the run directory as /output (results land at /output/<sample>/), but
# the agent's scratch lives one level up: /output/acp-packages (the harness venv + settings
# store) and /output/acp-workspaces (the app being built). On the cluster each pod had its own
# /output; locally, parallel containers sharing the host directory raced on those two paths
# and three of four ladders died at request 1 with an empty settings file. Anonymous volumes
# make them private per container (removed with --rm).
PRIVATE=(-v /output/acp-packages -v /output/acp-workspaces)
DOCKER_CMD=(docker run --rm --add-host=host.docker.internal:host-gateway "${ENV_ARGS[@]}" -e RUN_ID="$RUN_ID" -v "${OUT_ABS}:/output" "${PRIVATE[@]}" "$EVOWEB_IMAGE")
echo "[run_local] run=${RUN_ID} samples=${SAMPLES[*]} parallelism=${PAR} out=${OUT_ABS}"
echo "[run_local] docker command (per sample, SAMPLE_INDEX added):"
echo "  ${DOCKER_CMD[*]} <-e SAMPLE_INDEX=N>"

export OUT_ABS RUN_ID EVOWEB_IMAGE
export ENV_ARGS_STR="${ENV_ARGS[*]}"
printf '%s\n' "${SAMPLES[@]}" | xargs -P "$PAR" -I{} bash -c '
    idx="$1"
    log="${OUT_ABS}/launcher_$(printf "%06d" "$idx").log"
    # shellcheck disable=SC2086
    docker run --rm --add-host=host.docker.internal:host-gateway $ENV_ARGS_STR -e RUN_ID="$RUN_ID" -e SAMPLE_INDEX="$idx" \
        -v "${OUT_ABS}:/output" -v /output/acp-packages -v /output/acp-workspaces \
        "$EVOWEB_IMAGE" > "$log" 2>&1
    rc=$?
    echo "[run_local] sample $idx exit=$rc (log: $log)"
    exit 0
' _ {}

echo "[run_local] done. results: ${OUT_ABS}/<sample:06d>/result.json"
n_ok=$(ls "${OUT_ABS}"/*/result.json 2>/dev/null | wc -l)
echo "[run_local] ${n_ok}/${#SAMPLES[@]} result.json files present"
