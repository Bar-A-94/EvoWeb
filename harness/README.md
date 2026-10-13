# EvoWeb harness — generate traces for one app ladder, locally

This directory is the worker that produced every run in the paper. It runs from a clone of
this repository alone: no cloud storage, no Kubernetes. One container (or one bare-metal process) runs **one app ladder**: the agent
builds the app for request 1, then edits it for requests 2-10; after every request the app is
`npm install`ed, compile-checked, served, and judged by WebVoyager against that request's checks.

What is in here:

| File | Role |
|---|---|
| `run_single_sample.py` | The ladder loop: agent -> build -> serve -> judge, per request; writes `result.json` |
| `run_sample.sh` | Env-var front end for one ladder (Docker entrypoint and bare-metal launcher); holds the paper defaults |
| `run_local.sh` | N ladders in parallel with Docker, one container each |
| `vllm_serve.sh` | Starts one vLLM server in Docker and waits until it answers a completion (and an image question for a judge) |
| `serve_and_run.sh`, `configs/` | vLLM for the model under test with the judge on the API, or, given a config file, two vLLM servers and no API at all |
| `generators/` | The agent harnesses (`openhands`, the paper's; `bash`, `mini_swe_agent` and `claude_code` ship too but were not used in the paper), the capture proxy that records every model call, the Vite+React template the agent starts from; see `generators/README.md` |
| `webvoyager/` | The judge: drives the served app in headless Chrome and returns YES / PARTIAL / NO per check |
| `scoring.py` | Error taxonomy + verdict parsing; **byte-identical** to `../evoweb/scoring.py` (enforced by a test) |
| `checkpoint.py` | Per-request checkpoint/restore for the Kubernetes path (`../infra/`); only active with `S3_BUCKET`, off by default |
| `make_tasksets.py` | Derives the smoke sets in `../tests/smoke_sets/` from `../data/evoweb_benchmark.jsonl` (32 apps x 10 requests) |
| `setup_instance.sh`, `Dockerfile`, `requirements.txt` | Environment: Chrome + chromedriver, Node 22, Python 3, uv |

## Quick start (Docker)

```bash
# 1. build, from the package root (the parent of harness/ and data/)
docker build -f harness/Dockerfile -t evoweb-harness:latest .

# 2. run 32 ladders, 8 at a time, Claude Sonnet 4.6 as the model and as the judge
API_KEY=sk-ant-... EVAL_API_KEY=sk-ant-... harness/run_local.sh sonnet-r1 1-32 8

# 3. results
ls runs/sonnet-r1/000001/result.json runs/sonnet-r1/000001/turn2/generation/model_calls.jsonl
```

An OpenAI-compatible model (here via OpenRouter), judge still on Anthropic:

```bash
API_KEY=sk-or-... PROVIDER=OpenRouter API_URL=https://openrouter.ai/api MODEL=openai/<model> \
EVAL_API_KEY=sk-ant-... harness/run_local.sh my-run 1,4,6 3
```

Any OpenAI-compatible endpoint: `PROVIDER=OpenAILike API_URL=https://host/v1 MODEL=openai/<served-name>`.
For Anthropic, `MODEL` is `anthropic/<id>` (`anthropic/claude-sonnet-4-6`,
`anthropic/claude-haiku-4-5-20251001`, ...), the form the paper's runs used.

### Open-weights models on your own GPUs: `serve_and_run.sh`

One command starts vLLM in Docker, waits until the server answers a completion, runs the
benchmark against it with Sonnet as the judge, and stops the server at the end:

```bash
EVAL_API_KEY=sk-ant-... GPUS=0,1,2,3 VLLM_ARGS="--kv-cache-dtype fp8" \
  harness/serve_and_run.sh Qwen/Qwen3.5-397B-A17B-FP8 qwen397b-r1 1-32 8
```

The first argument is the Hugging Face repo of the weights, downloaded into `HF_CACHE`
(default `~/.cache/huggingface`) on first use; the rest are `run_local.sh`'s arguments. Knobs,
all optional: `GPUS` (default all), `TP` (default the number of GPUs), `PORT` (8003),
`SERVED_NAME` (the name the API answers to; default the repo), `VLLM_IMAGE`
(`vllm/vllm-openai:v0.27.0`), `MAX_MODEL_LEN` (262144), `TOOL_PARSER` and `REASONING_PARSER`
(vLLM's `qwen3_coder` and `qwen3`; change them for another model family), `READY_TIMEOUT`
(3600 s to wait for the server), `VLLM_ARGS` and `VLLM_DOCKER_ARGS` for anything else,
`KEEP_SERVER=1` to leave vLLM up.
The benchmark containers reach the server through the host's first IP (`API_HOST` overrides).
If a server already answers on `PORT`, it is used as is.

### No API at all: `serve_and_run.sh` with a config file

Given a config file instead of a model, the same launcher starts two vLLM servers, one for the
agent and one for the judge:

```bash
harness/serve_and_run.sh harness/configs/b300-qwen397b.env qwen-both-r1 1-32 8
```

The config is a plain shell file with `AGENT_*` and `JUDGE_*` variables: `MODEL` (Hugging Face
repo) and optionally `SERVED_NAME`, `GPUS`, `TP`, `PORT`, `VLLM_ARGS`, `TOOL_PARSER`,
`REASONING_PARSER`, `MAX_MODEL_LEN`; shared `VLLM_IMAGE`, `HF_CACHE`, `VLLM_DOCKER_ARGS`,
`READY_TIMEOUT`.
The judge's server gets `--limit-mm-per-prompt` from `JUDGE_IMAGES` (default 4) and must answer
an image question before the run starts, so a text-only judge fails early. The shipped config
puts Qwen3.5 397B (FP8) on GPUs 0-3 as the agent and on GPUs 4-7 as the judge. Servers that
already answer on a role's port are used as is and left running; servers the script started are
stopped at the end unless `KEEP_SERVER=1`. `vllm_serve.sh` starts each server and holds every
server knob.

### `run_local.sh` contract

```
harness/run_local.sh <run-id> <samples> <parallelism>
```

* `<samples>`: a comma list (`1,4,6,11`) or a range (`1-32`) of 1-based dataset rows.
* Output root: `$EVOWEB_OUT` (default `./runs`). The container gets `-v $EVOWEB_OUT/<run-id>:/output`,
  so results land at `$EVOWEB_OUT/<run-id>/<sample:06d>/result.json` (+ `turn<N>/` dirs).
* Image: `$EVOWEB_IMAGE` (default `evoweb-harness:latest`).
* Env passthrough (only variables that are set reach the container; everything else takes the
  paper default from `run_sample.sh`): `API_KEY MODEL PROVIDER API_URL EVAL_API_KEY EVAL_MODEL
  EVAL_API_URL EVAL_PROVIDER JSONL_FILE GENERATOR MAX_TOKENS AGENT_MAX_TURNS
  AGENT_MAX_OUTPUT_TOKENS AGENT_THINKING_BUDGET OPENHANDS_REASONING_EFFORT HARNESS_SAMPLING_PIN
  HARNESS_THINKING HARNESS_THINKING_BUDGET HARNESS_REASONING_EFFORT HARNESS_ANTHROPIC_EFFORT
  MINI_MODEL_CLASS WEBGEN_EFFICIENCY_NUDGE WEBGEN_NAV_GUIDANCE WEBGEN_TURN_TIMEOUT
  HARNESS_LLM_TIMEOUT WEBGEN_PROXY_TIMEOUT UV_EXCLUDE_NEWER EXTENSIONS_REF WEBGEN_RECORD_VIDEO
  SKIP_UI_EVAL`.
* The docker command is printed once before launching (secrets are passed as `-e NAME`, copied
  from the shell, never on the command line). Each container's stdout/stderr goes to
  `$EVOWEB_OUT/<run-id>/launcher_<sample:06d>.log`.

Without Docker: see `run_bare_metal.md`.

## Resolved defaults (the paper's recipe)

`run_sample.sh` sets these defaults, which are the values every paper run used, so an unset
variable reproduces the paper.

| Variable | Default | Read by | Meaning |
|---|---|---|---|
| `SAMPLE_INDEX` | required | `run_sample.sh` | 1-based row of the dataset (1-32) |
| `API_KEY` | required | everything | key for the model under test |
| `MODEL` | `anthropic/claude-sonnet-4-6` | agent | model id (`anthropic/<id>` for Anthropic; `openai/<id>` for OpenRouter/OpenAILike) |
| `PROVIDER` | `Anthropic` | `run_single_sample.py` | `Anthropic` (anthropic-messages wire) or `OpenAILike` / `OpenRouter` (openai-completions wire) |
| `API_URL` | empty (= `https://api.anthropic.com`) | agent, capture proxy | base URL for OpenAI-compatible endpoints (`https://openrouter.ai/api`, `https://host/v1`) |
| `EVAL_API_KEY` | `API_KEY` | judge | key for the judge model |
| `EVAL_MODEL` | `claude-sonnet-4-6` | judge | the paper's judge |
| `EVAL_API_URL` | `https://api.anthropic.com` | judge | |
| `EVAL_PROVIDER` | inferred from `EVAL_API_URL` (`anthropic` if it contains `anthropic.com`, else `openai`) | judge | judge wire format |
| `JSONL_FILE` | `evoweb_benchmark.jsonl` | `run_sample.sh` | a file under `../data/` (the benchmark, `multilingual/*.jsonl`, `ablation_no_grounding.jsonl`) or `../tests/smoke_sets/`, or a path; the image carries both |
| `GENERATOR` | `openhands` | `run_single_sample.py` | `openhands` (the paper) \| `bash` \| `mini_swe_agent` \| `claude_code` (shipped, not used in the paper; see `generators/README.md`) |
| `MAX_TOKENS` | `64000` | `--max-tokens` | not read on the harness path; sampling is pinned by the rows below |
| `AGENT_MAX_TURNS` | `20` | `generators/backend.py` (`max_steps`) | agent turn budget **per user request** (ladder length comes from the dataset) |
| `AGENT_MAX_OUTPUT_TOKENS` -> `OPENHANDS_MAX_OUTPUT_TOKENS` | `64000` | `openhands/entry.py pin_sampling` | output ceiling; Anthropic routes and listed reasoning routes |
| `AGENT_THINKING_BUDGET` -> `OPENHANDS_THINKING_BUDGET` | `16000` | `openhands/entry.py pin_sampling` | thinking budget (haiku / sonnet: `thinking.enabled@16000`); Claude models that only take adaptive thinking (matched by name inside `pin_sampling`: `opus-4-8`, `opus-5`, `fable`) get `reasoning_effort` instead |
| `OPENHANDS_REASONING_EFFORT` | `high` | `openhands/entry.py pin_sampling` | effort pin for adaptive-only Claude models and for `openai/` model ids matching `gpt-5`, `glm-5`, `deepseek-v4`, `qwen3.5-397b` (the reasoning routes `pin_sampling` lists) |
| `HARNESS_SAMPLING_PIN` | `64000:16000` | `generators/capture.py` | proxy-level `<ceiling>:<budget>` for **Anthropic upstreams only**, so bash / mini / claude_code sample like openhands. Set it to `""` for adaptive-only Claude models, which reject `thinking.type=enabled` (`HARNESS_SAMPLING_PIN= harness/run_local.sh ...`; `run_sample.sh` says the same) |
| `HARNESS_THINKING` | empty (pass-through) | capture proxy, `pin_sampling` | `off` strips thinking (ablation), `force` injects `HARNESS_THINKING_BUDGET` uniformly |
| `HARNESS_THINKING_BUDGET` | empty | capture proxy | only read with `HARNESS_THINKING=force` |
| `HARNESS_REASONING_EFFORT` | empty | capture proxy | effort pin for non-Anthropic upstreams under non-openhands harnesses |
| `HARNESS_ANTHROPIC_EFFORT` | empty | capture proxy | `<effort>:<ceiling>` adaptive-thinking ladder; mutually exclusive with `HARNESS_SAMPLING_PIN` |
| `MINI_MODEL_CLASS` | empty | `mini_swe_agent` | `litellm_response` for Responses-API-only models |
| `WEBGEN_EFFICIENCY_NUDGE` | `on` | `generators/backend.py` | appends the parallel-tool-calls nudge to the system prompt |
| `WEBGEN_TURN_TIMEOUT` | `10800` | `generators/backend.py` | wall-clock kill switch per user request (s) |
| `HARNESS_LLM_TIMEOUT` | `1200` | every harness | per-call client deadline (s) |
| `WEBGEN_PROXY_TIMEOUT` | `1800` | capture proxy | forward deadline; must stay above `HARNESS_LLM_TIMEOUT` |
| `UV_EXCLUDE_NEWER` | `2026-08-20T11:00:00Z` | uv | the harness venvs resolve at container start; this freezes them to the paper's Anthropic runs (openhands-agent-server 1.42.1, litellm 1.97.0; a later horizon resolves newer releases and is not the paper's agent) |
| `WEBGEN_NAV_GUIDANCE` | `on` | backend.py | `on`: the build guidance and template comment the paper's runs used, telling the agent to add one nav `<Link>` per page; `off` drops that sentence. The judge navigates by clicking, so this moves scores; `evoweb/arms.py` `NAV_GUIDANCE` has each released run's setting |
| `EXTENSIONS_REF` | `v0.17.0` | OpenHands | release of the public skills registry (github.com/OpenHands/extensions) that OpenHands clones and puts in the agent's system prompt; upstream default `main` drifts daily. Must be a tag or branch, not a SHA |
| `OUTPUT_DIR` | `/output` | `run_single_sample.py` | artifacts root |
| `S3_BUCKET`, `RUN_ID` | `none`, empty | `run_single_sample.py`, `checkpoint.py` | opt-in upload and per-request checkpoint restore, used by the Kubernetes launcher in `../infra/`; off locally |
| `WEBGEN_RECORD_VIDEO` | unset | judge | `1` records the first judge session to `videos/*.mp4` (needs Xvfb + ffmpeg, in the image) |
| `SKIP_UI_EVAL` | `0` | | `1` skips the judge (build + serve still run) |
| `TURN_GATE_THRESHOLD` | `-1` (constant in `run_single_sample.py`) | ladder loop | no score gating: only an errored request ends a ladder |

Not settable, fixed in code, and part of the recipe: judge `max_iter=20`, `max_attached_imgs=3`,
`temperature=1`, `seed=42`, viewport width 1280 (`run_single_sample.run_evaluation`).

## Output layout

Identical to the released traces (`examples_artifacts/traces.zip`, `<run-id>/...`):

```
$EVOWEB_OUT/<run-id>/
  000001/
    result.json                        the scored object: turns[] (one per user request) with
                                       status, yes/partial/no, tasks[], error_class, cost, build/runtime flags
    generation/model_calls.jsonl       request 1: every model call off the wire (tokens, latency, body)
    generation/summary.json            request 1: wall clock, tokens, cost_usd, turn_budget_exhausted, ...
    generation/workspace/              request 1: the app's source after this request (node_modules excluded)
    eval/results/<task>/               request 1: judge screenshots + agent.log per check
    logs/worker.log, logs/*.log        the worker's own stderr and per-stage logs
    turn2/ ... turn10/                 same tree for requests 2-10 (generation/, eval/, logs/)
  acp-workspaces/sample_000001/        the live workspace the agent edits across requests
  acp-packages/<harness>/              the harness's uv environment (resolved on first use, reused)
  launcher_000001.log                  container stdout/stderr (run_local.sh only)
```

`acp-workspaces/` and `acp-packages/` are on the host only on bare metal; `run_local.sh` makes
them private, anonymous volumes per container (removed with the container), so under Docker the
code is the per-request `generation/workspace/` copy.

`result.json`'s `turns[]` and the `turnN/` directories are one entry per **user request**, not per
agent turn (naming shared with the released traces). `../evoweb/scoring.py` consumes exactly this
file; `python3 -m evoweb.score_run runs/<run-id>`, from the repository root, scores a run (it
sets `EVOWEB_TRACES` for you).

Costs in `summary.json` are priced from OpenRouter's public catalog (`generators/pricing.py`,
fetched once a day into `$WEBGEN_PRICE_CACHE`, default `/tmp/webgen_price_catalog.json`); `null`
when a model is not listed.

## Tests

```bash
python3 -m pytest tests/harness -q        # from the package root
```

`tests/harness/` holds the tests of what determines a score on the OpenHands path: the turn gate
and turn budget, the sampling pins and thinking parity, the build guidance, the capture proxy's
path rewriting, the pinned run-time inputs, plus `test_scoring_verbatim.py`, which asserts
`harness/scoring.py == evoweb/scoring.py` byte for byte.
