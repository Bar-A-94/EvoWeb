#!/usr/bin/env bash
# Start one vLLM server in Docker and wait until it answers, or adopt one that already does.
#
#   harness/vllm_serve.sh up <hf-model>      starts the server; prints the container name on
#                                            stdout, or "-" when a server already answered on PORT
#   harness/vllm_serve.sh down <container>   stops a container `up` started ("-" is a no-op)
#
# Environment (all optional, defaults in brackets):
#   GPUS           [all]              GPU ids, e.g. 4,5,6,7
#   TP             [number of GPUS]   tensor parallel size
#   PORT           [8003]             port on the host
#   SERVED_NAME    [<hf-model>]       model name the API answers to
#   VLLM_IMAGE     [vllm/vllm-openai:v0.27.0]
#   HF_CACHE       [~/.cache/huggingface]  mounted into the container; weights download here on
#                                     first use unless HF_HUB_OFFLINE=1 is in VLLM_DOCKER_ARGS
#   MAX_MODEL_LEN  [262144]
#   TOOL_PARSER    [qwen3_coder]      vLLM --tool-call-parser (the agent needs tool calls)
#   REASONING_PARSER [qwen3]          vLLM --reasoning-parser; empty = none
#   IMAGES         []                 max images per prompt (a judge needs this); empty = vLLM's
#                                     default of one, and no image check
#   VLLM_ARGS      []                 extra vLLM arguments, e.g. "--kv-cache-dtype fp8"
#   VLLM_DOCKER_ARGS []               extra docker run arguments, e.g. "-e NCCL_IB_DISABLE=1"
#   READY_TIMEOUT  [3600]             seconds to wait (a 400 GB model takes 5-30 min)
#
# Progress goes to stderr. `up` ends with one real completion, and with one image question when
# IMAGES is set, so a server that answers the health check but not a request is caught here.

set -euo pipefail

log() { echo "[vllm_serve] $*" >&2; }

PORT="${PORT:-8003}"
cmd="${1:-}"

if [ "$cmd" = down ]; then
    [ "${2:-}" = "-" ] || [ -z "${2:-}" ] || { log "stopping ${2}"; docker stop "$2" > /dev/null 2>&1 || true; }
    exit 0
fi
if [ "$cmd" != up ] || [ -z "${2:-}" ]; then
    echo "usage: $0 up <hf-model> | down <container>" >&2
    exit 2
fi
HF_MODEL="$2"
SERVED_NAME="${SERVED_NAME:-$HF_MODEL}"

check_served_name() {
    if ! curl -sf "http://localhost:${PORT}/v1/models" | grep -q "\"id\": *\"${SERVED_NAME}\""; then
        log "the server on :${PORT} does not serve '${SERVED_NAME}'; it serves:"
        curl -sf "http://localhost:${PORT}/v1/models" | grep -o '"id": *"[^"]*"' >&2 || true
        exit 1
    fi
}

if curl -sf "http://localhost:${PORT}/health" > /dev/null 2>&1; then
    check_served_name
    log "a server already answers on :${PORT} and serves '${SERVED_NAME}'; using it"
    echo "-"
    exit 0
fi

GPUS="${GPUS:-all}"
if [ "$GPUS" = all ]; then
    N_GPU=$(nvidia-smi --query-gpu=index --format=csv,noheader | wc -l)
    DEVICE_ARG="all"
else
    N_GPU=$(tr ',' '\n' <<< "$GPUS" | grep -c .)
    DEVICE_ARG="\"device=${GPUS}\""
fi
TP="${TP:-$N_GPU}"
VLLM_IMAGE="${VLLM_IMAGE:-vllm/vllm-openai:v0.27.0}"
HF_CACHE="${HF_CACHE:-$HOME/.cache/huggingface}"
MAX_MODEL_LEN="${MAX_MODEL_LEN:-262144}"
TOOL_PARSER="${TOOL_PARSER:-qwen3_coder}"
REASONING_PARSER="${REASONING_PARSER-qwen3}"
READY_TIMEOUT="${READY_TIMEOUT:-3600}"
CONTAINER="evoweb-vllm-${PORT}"

mkdir -p "$HF_CACHE"
# shellcheck disable=SC2206
EXTRA_DOCKER=(${VLLM_DOCKER_ARGS:-})
# shellcheck disable=SC2206
EXTRA_VLLM=(${VLLM_ARGS:-})
PARSERS=(--tool-call-parser "$TOOL_PARSER" --enable-auto-tool-choice)
[ -n "$REASONING_PARSER" ] && PARSERS+=(--reasoning-parser "$REASONING_PARSER")
if [ -n "${IMAGES:-}" ] && [[ " ${VLLM_ARGS:-} " != *"--limit-mm-per-prompt"* ]]; then
    EXTRA_VLLM+=(--limit-mm-per-prompt "{\"image\":${IMAGES}}")
fi

log "starting ${HF_MODEL} as '${SERVED_NAME}' on :${PORT}, TP${TP} on GPUs ${GPUS} (${VLLM_IMAGE})"
docker run -d --name "$CONTAINER" --rm --gpus "$DEVICE_ARG" --ipc=host --network=host \
    -e VLLM_WORKER_MULTIPROC_METHOD=spawn -e VLLM_ENGINE_READY_TIMEOUT_S="$READY_TIMEOUT" \
    -v "${HF_CACHE}:/root/.cache/huggingface" "${EXTRA_DOCKER[@]}" \
    "$VLLM_IMAGE" "$HF_MODEL" --served-model-name "$SERVED_NAME" \
    --tensor-parallel-size "$TP" --dtype auto --gpu-memory-utilization 0.92 \
    --max-model-len "$MAX_MODEL_LEN" --max-num-batched-tokens 16384 \
    "${PARSERS[@]}" "${EXTRA_VLLM[@]}" --host 0.0.0.0 --port "$PORT" > /dev/null

# From here on, any failure stops the container this script started.
trap 'rc=$?; [ "$rc" = 0 ] || { log "failed (exit $rc); stopping ${CONTAINER}"; docker stop "$CONTAINER" > /dev/null 2>&1 || true; }' EXIT
log "waiting for http://localhost:${PORT}/health (up to ${READY_TIMEOUT}s; logs: docker logs -f ${CONTAINER})"
t0=$(date +%s)
until curl -sf "http://localhost:${PORT}/health" > /dev/null; do
    if ! docker ps -q -f "name=^${CONTAINER}$" | grep -q .; then
        log "container exited; last log lines:"
        docker logs --tail 30 "$CONTAINER" >&2 || true
        exit 1
    fi
    if [ $(( $(date +%s) - t0 )) -ge "$READY_TIMEOUT" ]; then
        log "not ready after ${READY_TIMEOUT}s"
        exit 1
    fi
    sleep 15
done
log "up after $(( $(date +%s) - t0 ))s"
check_served_name

# One real completion, and one image question when the server is meant to see screenshots.
# A reasoning model answers empty with a small max_tokens, hence the generous budget.
python3 - "$PORT" "$SERVED_NAME" "${IMAGES:-}" >&2 <<'EOF'
import base64, json, struct, sys, urllib.request, zlib
port, name, images = sys.argv[1], sys.argv[2], sys.argv[3]

def ask(content):
    body = {"model": name, "max_tokens": 1024, "temperature": 0,
            "messages": [{"role": "user", "content": content}]}
    req = urllib.request.Request(f"http://localhost:{port}/v1/chat/completions",
                                 json.dumps(body).encode(), {"Content-Type": "application/json"})
    msg = json.load(urllib.request.urlopen(req, timeout=600))["choices"][0]["message"]
    return (msg.get("content") or "").strip()

print("[vllm_serve] test reply:", ask("Say hello in one word.")[:80] or "(empty)")
if images:
    raw = b"".join(b"\x00" + b"\xff\x00\x00" * 2 for _ in range(2))
    def chunk(t, d):
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)
    png = (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 2, 2, 8, 2, 0, 0, 0))
           + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))
    reply = ask([{"type": "text", "text": "What color is this image? Answer in one word."},
                 {"type": "image_url", "image_url": {"url": "data:image/png;base64," + base64.b64encode(png).decode()}}])
    print("[vllm_serve] image reply (a red square):", reply[:80] or "(empty)")
    if "red" not in reply.lower():
        print("[vllm_serve] the server did not read the image; a judge needs a vision model", file=sys.stderr)
        sys.exit(1)
EOF
echo "$CONTAINER"
