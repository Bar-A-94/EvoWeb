# Grounding ablation: blind realism judge (paper Table 7)

Does an LLM judge prefer follow-up requests written from real websites over ones written without
them? Arms: `data/evoweb_benchmark.jsonl` (grounded) vs `data/ablation_no_grounding.jsonl`
(no grounding), the 30 apps in both, same author model.

```text
run.py         one judge call per app, question and label order; appends to calls.jsonl, resumes
analyze.py     win rate per condition with a bootstrap interval over apps; `analyze.py A B` = paired test
calls.jsonl    every verdict we collected        results.json   every condition with its interval
```

Reproduce Table 7 from the released verdicts, or collect new ones (judges called through
OpenRouter; `run.py` needs `pip install requests`):

```bash
python3 ablations/grounding/judge/analyze.py           # from calls.jsonl; rewrites results.json

export OPENROUTER_API_KEY=...
JUDGE_MODEL=x-ai/grok-4.6 python3 ablations/grounding/judge/run.py 0 2   # all apps x 2 repeats x both label orders
```

`run.py LIMIT REPS` judges the first LIMIT apps (0 = all) REPS times per label order.
Environment variables select the condition: `JUDGE_MODEL` (OpenRouter model id), `QUESTIONS`
(comma-separated keys of `run.py`'s question list, default `realism`), `FOCUS` (`early`, `mid`,
`late` or `tail3`: judge only that window of requests), `DROP` (follow-up archetypes to remove
before judging, e.g. `design-restyle`), `OUT` (default `calls.jsonl`), `WORKERS` (default 16).

`analyze.py` prints every condition present in `calls.jsonl`, numbered, and writes them to
`results.json`. Besides the three Table 7 rows (`realism / all requests` for Grok 4.6,
GPT 5.6 Sol and Gemini 3.1 Pro) the file holds the side conditions we collected: the same
question restricted to a window of requests or with the restyle requests dropped, the other
questions (`quality`, `choice`, `diversity_coverage`, `diversity_repetition`), and two further
judges (GPT 5.6 Luna, Qwen 3.8 Max). `analyze.py A B` with two row numbers from that listing
tests whether two conditions differ (paired over apps).

## Table 7

Win rate of the grounded requests on the realism question, both label orders, 95% bootstrap
interval over apps:

| judge | grounded win rate (%) | 95% interval |
|---|---|---|
| Grok 4.6 | 74.2 | [60.8, 86.7] |
| GPT 5.6 Sol | 69.6 | [55.0, 82.5] |
| Gemini 3.1 Pro | 69.2 | [56.7, 80.8] |

## Method

The judge sees the app's build prompt and the two sets of follow-up requests, request text only
(the arms' other fields differ, so they would identify them), with the rubric in `run.py`'s
system prompt (App. C.1 of the paper). Each pair is judged in both label orders, because judges
favour whichever set comes first. Scores are averaged per app; the interval is a bootstrap over
apps.
