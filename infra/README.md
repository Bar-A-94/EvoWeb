# Running EvoWeb on Kubernetes (optional)

You do not need a cluster: `harness/run_local.sh` runs everything on one machine with Docker.
A run is 32 app ladders of 10 requests each, and a ladder takes hours, so for many models or
replicates it pays to run one pod per ladder on Kubernetes. This is how the paper's runs were
produced. `launch.sh` renders `job-template.yaml` into one Indexed Job per run, waits for it,
and syncs the results back.

## What you need

| | what | notes |
|---|---|---|
| cluster | any Kubernetes cluster | each pod requests 6 vCPU / 16 GiB and is limited to 24 GiB: it runs Chrome (the judge), Vite and the agent's `npm run build`. `karpenter.yaml` is an optional AWS node pool (m5, on-demand or spot); see below |
| image | `harness/Dockerfile`, built and pushed to a registry the cluster pulls from | `docker build -f harness/Dockerfile -t <registry>/evoweb-harness:<tag> . && docker push <registry>/evoweb-harness:<tag>`. A private registry needs `imagePullSecrets` added to the pod spec in `job-template.yaml` |
| storage | an S3 bucket the pods can write to | the template mounts no volume: results go to `s3://<bucket>/<run-id>/<app>/` and per-request checkpoints to `.../<app>/_ckpt/turn<N>/`, which let an evicted pod resume instead of restarting its ladder. For another store, mount a volume in the template, set `OUTPUT_DIR` on it, and replace the `aws s3 sync` step and the `S3_BUCKET` check in `launch.sh` |
| identity | a namespace and a service account the pods run as, with write access to the bucket | `kubectl create namespace evoweb && kubectl -n evoweb create serviceaccount evoweb`; grant `s3:PutObject`, `s3:GetObject`, `s3:ListBucket` on the bucket (on EKS, IRSA or Pod Identity) |
| keys | a secret with `model-api-key` (the model under test) and `anthropic-api-key` (the judge) | `kubectl -n evoweb create secret generic evoweb-keys --from-literal=model-api-key=... --from-literal=anthropic-api-key=...` |
| tools | `kubectl`, `aws`, `envsubst` on the machine you launch from | |

The names above are the launcher's defaults; `NAMESPACE`, `SERVICE_ACCOUNT` and `SECRET_NAME`
override them.

## Run a model

```bash
export IMAGE=<registry>/evoweb-harness:<tag> S3_BUCKET=<bucket>
infra/launch.sh haiku-r1 anthropic/claude-haiku-4-5-20251001 Anthropic
```

```
infra/launch.sh <run-id> <model> <provider> [api-url]
```

An OpenAI-compatible endpoint passes its URL as the fourth argument, with the model as
`openai/<model>`:

```bash
infra/launch.sh my-model-r1 openai/<model> OpenAILike https://<host>/v1
```

The launcher submits one Indexed Job of `NUM_APPS` pods (32, `PARALLELISM` of them at a time,
32 by default; `START_APP` picks the first app), polls it every five minutes, then syncs
`result.json` and `model_calls.jsonl` of every app to `runs/<run-id>/` and prints the command
that scores them (`python3 -m evoweb.compare_to_released`, or `python3 -m evoweb.score_run` for a model not in
the paper). Conversations, judge sessions and logs stay in the bucket. `DRY_RUN=1` prints the
rendered Job instead of submitting it. Ctrl-C leaves the job running; re-run the sync line from
`launch.sh` later. A pod that dies mid-ladder is retried up to twice (`backoffLimitPerIndex`)
and resumes from its last checkpoint.

`NAV_GUIDANCE` (default `on`) is the build guidance the paper's runs used; `evoweb/arms.py`
records each released run's setting.

The pod gets only `RUN_ID`, `MODEL`, `PROVIDER`, `API_URL`, `WEBGEN_NAV_GUIDANCE`, `S3_BUCKET`
and the two keys; every other harness variable takes the paper's default from
`harness/run_sample.sh` (the judge is Claude Sonnet 4.6 on the Anthropic API). To change any of
them, for example the judge (`EVAL_MODEL`, `EVAL_API_URL`) or `HARNESS_SAMPLING_PIN` for a model
that rejects a fixed thinking budget, add an `env` entry to `job-template.yaml`;
`harness/README.md` lists them all.

### Node pool (AWS, optional)

`karpenter.yaml` defines an EC2NodeClass and a NodePool of m5 instances (4xlarge to 12xlarge,
on-demand or spot) tainted `evoweb=true`. Replace `<your-cluster>` in it, apply it, and add to
the pod spec in `job-template.yaml`:

```yaml
nodeSelector: {karpenter.sh/nodepool: evoweb}
tolerations: [{key: evoweb, operator: Equal, value: "true", effect: NoSchedule}]
```

## Lessons from the paper's runs

- **Repair only infrastructure failures.** A ladder killed by the provider (429/5xx, lost
  connection) or by the cluster is re-run alone with `NUM_APPS=1 START_APP=<n>` and a new run id,
  and its `result.json` replaces the dead one. A model that loops, emits bad tool calls or runs
  out of context has produced its result. `evoweb.scoring.classify_error` tells them apart.
- **Canary first.** Run one ladder before a 32-way run with a new provider: an exhausted balance
  shows up as a judge that answers NO to everything under a request marked successful.
- **Concurrency is what the provider sees.** 32 pods of one model and 4 models with 8 pods each
  hit the same rate limit; run models one after another at high parallelism.
- **The judge is Claude Sonnet 4.6 on the Anthropic API.** Every number in the paper is on that
  judge's scale.
