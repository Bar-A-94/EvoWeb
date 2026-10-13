# `examples_artifacts/` — the paper's runs and ours

| | what | how to use it |
|---|---|---|
| `traces.zip` | the paper's runs of the four Anthropic models (Fable 5, Opus 4.8, Sonnet 4.6, Haiku 4.5), three runs each, plus the multilingual runs of Sonnet 4.6 and Haiku 4.5; the paper's other models' runs are not released. Each run is `<run-id>/<app>/result.json` (the judge's verdicts) and the per-request token logs (`generation/model_calls.jsonl`, `turn<N>/generation/model_calls.jsonl`) | unpacked here into `traces/` the first time anything scores (`evoweb.paths.ensure_traces`); `traces/MANIFEST.json` lists the runs, `evoweb/arms.py` maps them to the paper's tables |
| `full_traces/fable-5-run1.zip` | Fable 5's first run complete, no screenshots: the agent's conversations, the code after every request, every judge session, the logs | `python3 -m evoweb.score_zip fable-5-run1`; see `full_traces/README.md` |
| `examples.zip` | one Opus 4.8 app (`opus-4.8-run1`, app `000001`) with everything, screenshots included | unzip anywhere; it unpacks to `opus-4.8-run1-app000001/`, whose README describes the layout |
| `reproductions/haiku-4.5-rerun/` | our re-run of Haiku 4.5 on all 32 apps, in the `traces.zip` layout (verdicts and token logs) | `python3 -m evoweb.score_run examples_artifacts/reproductions/haiku-4.5-rerun` |
| `reproductions/haiku-4.5-rerun_compare.json` | that re-run next to the paper's three Haiku 4.5 runs: Table 2 scalars, Grade per app, accuracy per request index | regenerate with `python3 -m evoweb.compare_to_released "Haiku 4.5" examples_artifacts/reproductions/haiku-4.5-rerun --json <out>` |
