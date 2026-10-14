# `data/data_gen/` — how the EvoWeb datasets were generated

The follow-up requests and their checks were written by LLM agents running a **Claude Code
Workflow** (the `.js` scripts), then audited and assembled by small deterministic Python scripts.
The datasets themselves are in `data/` (the benchmark is downloaded from Hugging Face). A generation run writes one part file per app
into a parts directory under `data/` (not committed: the assembled dataset carries every field of
every part), then the deterministic steps audit and assemble them.

```
nine-hard-v5-chained.js             the benchmark's generator (dependency DAG + real-website grounding)
                                    -> data/evoweb_main_dataset/<idx:06d>.json -> data/evoweb_benchmark.jsonl
nine-hard-v5_no_grounding_fable.js  the same without the real-website corpus (App. C.1)
                                    -> data/ablation_dataset_no_grounding/<idx:06d>.json -> data/ablation_no_grounding.jsonl
audit_parts.py                      the mechanical rules: check template, banned controls, verbatim backward
                                    checks, exact-value coverage, counter cap, archetype mix, DAG shape and
                                    depth (on a parts directory or an assembled dataset)
assemble_dataset.py                 parts -> the dataset (one row per clean app, in app order)
paper_terms.py                      old-name -> paper-name conversion, applied by audit_parts.py and
                                    assemble_dataset.py (see below)
multilingual/                       the translation parts and scripts (own README)
```

The `.js` prompts are kept exactly as run, so they still emit the pre-paper names (`turn` for
request, `regression` for the backward check: `copied_from_turn`, `introduced_in_turn`, kind
`regression`, graph ids `T1`..`T10`); `paper_terms.py` converts them to the dataset's names
(`copied_from_request`, `introduced_in_request`, kind `backward`, `R1`..`R10`).

## The generator workflows

The `.js` files are scripts for Claude Code's **Workflow tool**, which runs each `agent()` call as a
full Claude Code session with file tools. A workflow spawns one agent per app; the agent reads the
app's build prompt (line `idx` of `data/legacy_webgen_bench_apps.jsonl`) and, for the benchmark, the
app's real similar websites (`data/similar_websites.json`), designs the grown app and its dependency
DAG, writes the 9 follow-up requests with 5 checks each, and saves the part file. A second agent
verifies the part and repairs it once on failure; the no-grounding script also has a repair-only mode
that re-verifies and repairs existing parts for a few more rounds (its arguments are described in
the comment at the top of the script). A full run takes hours. The workflow then calls
`assemble_dataset.py` on the clean parts.

To run one: open Claude Code, invoke the Workflow tool with the script, and pass
`{data: "/abs/path/to/data"}` as args (the path of this repo's `data/`); `{samples: [1, 14]}` runs
a pilot on a few apps and skips assembly. The app list a full run generates is the `FULL` constant
at the top of each script: in `nine-hard-v5_no_grounding_fable.js` it is the 32 benchmark apps; in
`nine-hard-v5-chained.js` it is a 20-app list, four of which (7, 57, 59, 64) are not in the
benchmark, so a full run of the shipped script does not produce `evoweb_benchmark.jsonl` without
first setting `FULL` to the 32 ids of `data/evoweb_benchmark.jsonl` (in row order).

## Auditing the committed files

```bash
python3 data/data_gen/audit_parts.py data/evoweb_benchmark.jsonl --quiet       # CLEAN / DIRTY / WARN lists
python3 data/data_gen/audit_parts.py data/ablation_no_grounding.jsonl --quiet
```

Without `--quiet` the script also prints every violation and warning per app. The benchmark audits
31 clean (app 48 predates the exact-value rule and ships as is); the no-grounding set audits all 30
clean (apps 41 and 93 failed review and were left out). `tests/test_datasets.py` asserts both
verdicts. After a new generation run,

```bash
python3 data/data_gen/assemble_dataset.py --parts data/evoweb_main_dataset --out <out.jsonl> --clean <ids>
```

(or `--clean-from-audit` to take the audit's clean list) writes the dataset; `--base` defaults to
`data/legacy_webgen_bench_apps.jsonl`.
