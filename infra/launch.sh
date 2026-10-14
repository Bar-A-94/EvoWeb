#!/usr/bin/env bash
# Run one EvoWeb run (32 app ladders) on Kubernetes, then fetch and score the results.
#
#   infra/launch.sh <run-id> <model> <provider> [api-url]
#
#   IMAGE=<registry>/evoweb-harness:<tag> S3_BUCKET=<bucket> \
#     infra/launch.sh haiku-r1 anthropic/claude-haiku-4-5-20251001 Anthropic
#
# Environment (defaults in brackets):
#   IMAGE            (required) the harness image, pushed to a registry the cluster can pull from
#   S3_BUCKET        (required) bucket for results and checkpoints: s3://$S3_BUCKET/<run-id>/
#   NAMESPACE        [evoweb]   SERVICE_ACCOUNT [evoweb]   SECRET_NAME [evoweb-keys]
#   PARALLELISM      [32]       NUM_APPS [32]              START_APP [1]
#   NAV_GUIDANCE     [on]       see harness/README.md (on for the paper's Anthropic rows)
#   DRY_RUN=1        print the rendered Job and exit
#
# The secret holds two keys: model-api-key (the model under test) and anthropic-api-key (judge).
set -euo pipefail

RUN_ID=${1:?run id}; MODEL=${2:?model}; PROVIDER=${3:?provider}; API_URL=${4:-}
: "${IMAGE:?set IMAGE to the pushed harness image}"
: "${S3_BUCKET:?set S3_BUCKET to your results bucket}"
NAMESPACE=${NAMESPACE:-evoweb}; SERVICE_ACCOUNT=${SERVICE_ACCOUNT:-evoweb}
SECRET_NAME=${SECRET_NAME:-evoweb-keys}; PARALLELISM=${PARALLELISM:-32}
NUM_APPS=${NUM_APPS:-32}; START_APP=${START_APP:-1}; NAV_GUIDANCE=${NAV_GUIDANCE:-on}
JOB_NAME="evoweb-$(echo "$RUN_ID" | tr '[:upper:]_.' '[:lower:]--' | cut -c1-50)"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/.." && pwd)"

export RUN_ID MODEL PROVIDER API_URL IMAGE S3_BUCKET NAMESPACE SERVICE_ACCOUNT SECRET_NAME \
       PARALLELISM NUM_APPS START_APP NAV_GUIDANCE JOB_NAME
# Substitute only our variables: the pod command's own $((JOB_COMPLETION_INDEX + ...)) stays.
VARS='${RUN_ID}${MODEL}${PROVIDER}${API_URL}${IMAGE}${S3_BUCKET}${NAMESPACE}${SERVICE_ACCOUNT}'
VARS+='${SECRET_NAME}${PARALLELISM}${NUM_APPS}${START_APP}${NAV_GUIDANCE}${JOB_NAME}'
JOB=$(envsubst "$VARS" < "$HERE/job-template.yaml")

if [ "${DRY_RUN:-0}" = 1 ]; then echo "$JOB"; exit 0; fi

echo "[launch] job $JOB_NAME: $NUM_APPS ladders of $MODEL ($PROVIDER), $PARALLELISM at a time"
echo "$JOB" | kubectl apply -f -
echo "[launch] waiting (a full run takes hours; Ctrl-C leaves the job running)"
until kubectl -n "$NAMESPACE" get job "$JOB_NAME" \
      -o jsonpath='{.status.conditions[?(@.status=="True")].type}' | grep -qE 'Complete|Failed'; do
    S=$(kubectl -n "$NAMESPACE" get job "$JOB_NAME" -o jsonpath='{.status.succeeded}')
    echo "[launch] $(date -u +%H:%M) ladders finished: ${S:-0}/$NUM_APPS"
    sleep 300
done

OUT="$ROOT/runs/$RUN_ID"
mkdir -p "$OUT"
aws s3 sync "s3://$S3_BUCKET/$RUN_ID/" "$OUT/" --exclude '*' \
    --include '*/result.json' --include '*generation/model_calls.jsonl' --exclude '*/_ckpt/*'
echo "[launch] $(ls "$OUT"/*/result.json 2>/dev/null | wc -l)/$NUM_APPS results in $OUT"
echo "[launch] score it:  cd $ROOT && python3 -m evoweb.compare_to_released \"<paper model row>\" $OUT"
