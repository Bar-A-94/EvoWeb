# `ablations/grounding/` — the grounding ablation (paper App. C.1)

The request generator starts every follow-up from a feature of a real similar website
(`data/similar_websites.json`). This ablation withholds that corpus, keeps everything else fixed
(same author model) and compares the two datasets on the 30 apps they share:
[the benchmark](https://huggingface.co/datasets/TD-Labs/EvoWeb) (grounded, 32 apps) against `data/ablation_no_grounding.jsonl`
(no grounding, 30 apps). No benchmark runs are involved; everything else reads only `data/`
(the apps' build prompts come from `data/legacy_webgen_bench_apps.jsonl`).

Two results, as in the paper:

- **Realism (Table 7).** Blind LLM judges from three vendors prefer the grounded requests 69-74% of
  the time, with 95% intervals above 50%. See [`judge/`](judge/).
- **Diversity.** Grounding lowers the invented 4-gram overlap between unrelated apps by 29%
  (`golden/invented_ngram_overlap.json`, n = 4: 0.00351 grounded vs 0.00490 without).

```bash
python3 ablations/grounding/run_all.py           # recompute the overlap into artifacts/ (~1 min)
python3 ablations/grounding/run_all.py --check   # recompute into a scratch dir and compare with golden/ (exact)
python3 ablations/grounding/run_all.py --list    # the stage table
```

`--check` is the regression gate `tests/test_datasets.py` runs: every stage is seeded, so the
output must match `golden/` exactly.

## The overlap metric

For each app, take the 4-grams of its nine follow-up requests in order of first appearance, drop
those that already occur in the app's own build prompt (phrasing inherited from the shared seed
does not count), and keep the first K, where K is the largest count every app can supply. The
overlap is the mean Jaccard similarity of these sets over all pairs of apps; lower means more
diverse. `invented_ngram_overlap.py` computes it for n = 1 to 8 with a paired bootstrap over apps
and an exact sign test; the paper quotes n = 4.

```
invented_ngram_overlap.py   the overlap metric, both datasets, n = 1..8 (--json PATH, --iters N)
ablation_lib.py             loaders, tokenizer, bootstrap and sign test
run_all.py                  runs it; --check compares with golden/invented_ngram_overlap.json
judge/                      the realism judge (Table 7)
```
