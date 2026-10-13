# `data/data_gen/multilingual/` — the translated benchmark (Table 3)

The translated sets ([HF](https://huggingface.co/datasets/TD-Labs/EvoWeb), `multilingual` config: `fr de zh hi he`) are the benchmark with the
10 user requests of every app translated. The app's UI labels and seeded strings stay in their
exact English form, and the judge's checks are the English originals, so only the language the user
writes in changes. Every $-amount, decimal, percentage and signed odds figure, and every kept anchor
(brands, teams, tickers, URLs) is byte-identical in every language, machine-enforced by
`validate_parts.py`; CSS colour keywords are checked the same way but only warn.

## Layout

```
parts/<app id>/
  en.json            the EN row (written by split_parts.py)
  anchors.json       {anchors: [{en, class: translate|keep, kind, turns, translations{lang}}]}
                     the app's anchor inventory: the UI labels and seeded strings kept across requests
  <lang>_enui.json   {app, lang, variant, instructions{"1".."10"}}: the translated requests
split_parts.py       evoweb_benchmark.jsonl -> parts/*/en.json
validate_parts.py    the deterministic contract (see below); 32 x PASS on the shipped parts
assemble.py          parts -> data/multilingual/evoweb_benchmark_<lang>.jsonl;
                     refuses to write if validate_parts.py fails
make_viewer.py       viewer_enui.html: EN and translations side by side for human review (RTL-aware,
                     anchors highlighted), written next to this README
```

`validate_parts.py` checks, per app and language: the 10 instructions are present and not
suspiciously short; every numeric literal of the English request survives verbatim; every anchor
used in that request appears in its exact English form; no native translation of a UI label slipped
in (warning); no bidi control characters; the text is really in the target language (share of
target-script letters for zh/he/hi, stopwords for the others); and no task edits, since the judge's
checks are untouched.

## How the translations were made

A Claude Code Workflow (not included here), one agent per app translating every language at
once. Each agent first derives the app's **anchor glossary** (`anchors.json`), then writes the
translated requests and iterates until `validate_parts.py` passes with zero errors. All 32 apps
pass.

## Reproducing the 7 files

```bash
python3 data/data_gen/multilingual/validate_parts.py          # 32 x PASS
python3 data/data_gen/multilingual/assemble.py --out-dir /tmp/ml
```

`assemble.py` starts from each English row and swaps only the 10 requests, so metadata and checks
are byte-identical to the English set and row order (= sample index) is that of `evoweb_benchmark.jsonl`.
Every output file is byte-identical to the copy downloaded from Hugging Face into `data/multilingual/`
(`tests/test_datasets.py` asserts it); without `--out-dir` the
script overwrites the downloaded copies. A language list (`assemble.py --out-dir /tmp/ml de fr`)
restricts the run.
