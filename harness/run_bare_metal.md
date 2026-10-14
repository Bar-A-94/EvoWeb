# Running one ladder without Docker

Ubuntu 22.04 (what the image uses; 24.04 works the same). Everything below is what
`harness/Dockerfile` does, by hand.

## 1. Provision the machine

```bash
sudo bash harness/setup_instance.sh
```

Installs: Google Chrome stable + the matching chromedriver (`/usr/bin/chromedriver`), Node.js 22,
pm2, Python 3 + pip with `openai anthropic selenium pillow requests tqdm numpy boto3 awscli
fastapi uvicorn httpx`, and `uv` (the agent harnesses start with `uv run --script`; their own
packages — openhands etc. — are resolved into `$OUTPUT_DIR/acp-packages/` on first use, frozen at
`UV_EXCLUDE_NEWER`). Optional, for `WEBGEN_RECORD_VIDEO=1`: `sudo apt-get install xvfb ffmpeg`.

Tell the judge where Chrome is (the Dockerfile does the same):

```bash
echo /usr/bin/google-chrome > harness/.chrome_path
export CHROME_BIN=/usr/bin/google-chrome CHROMEDRIVER_BIN=/usr/bin/chromedriver
```

## 2. Write the smoke sets (optional)

The benchmark itself, `data/evoweb_benchmark.jsonl`, is downloaded from Hugging Face at the start of
every run. The short sets used for smoke tests are derived from it:

```bash
python3 harness/make_tasksets.py      # writes tests/smoke_sets/*.jsonl
```

## 3. Run one ladder

```bash
export API_KEY=sk-ant-...          # model under test
export EVAL_API_KEY=sk-ant-...     # judge (Claude Sonnet 4.6 on the Anthropic API by default)
export OUTPUT_DIR=$PWD/runs/local-r1
SAMPLE_INDEX=1 bash harness/run_sample.sh
```

`run_sample.sh` runs `harness/.venv/bin/python` if that venv exists, else `$PYTHON_PATH`, else
`python3`.

Ports: the served app uses 5200 (`APP_PORT_BASE` in `run_single_sample.py`), the capture proxy
picks a free port. Two ladders on one machine therefore need two containers (or two machines):
`run_sample.sh` is one ladder per host. Use `run_local.sh` for parallelism.

Result: `$OUTPUT_DIR/000001/result.json`, `$OUTPUT_DIR/000001/turn<N>/...`, the workspace under
`$OUTPUT_DIR/acp-workspaces/sample_000001/`. Every environment variable in the README table applies
unchanged; e.g. an OpenRouter model:

```bash
PROVIDER=OpenRouter API_URL=https://openrouter.ai/api MODEL=openai/<model> \
SAMPLE_INDEX=4 bash harness/run_sample.sh
```

## Smoke test without spending on a full ladder

After step 2: `JSONL_FILE=evoweb_smoke_2apps_3requests.jsonl` (2 apps x 3 requests),
`JSONL_FILE=evoweb_smoke_3apps_2requests.jsonl` (3 apps x 2 requests) or
`JSONL_FILE=evoweb_2requests.jsonl` (all 32 apps, 2 requests each; request 1 is judged exactly as
in the full run). A set needs at least 2 requests per app.
