# DAG ablation scripts

The scripts behind Section 5.1 of the paper: does the dependency DAG make requests harder,
and which checks carry that difficulty. They read the released traces
(`examples_artifacts/traces.zip`, the paper's runs of the four Anthropic models, unpacked to
`examples_artifacts/traces/` on first use; override with `EVOWEB_TRACES`) and
[the benchmark](https://huggingface.co/datasets/TD-Labs/EvoWeb) from Hugging Face, take their runs from `evoweb/arms.py` (`DAG_TABLE`: the first two
runs of each of the four models) and write into `artifacts/` (override with `EVOWEB_ARTIFACTS`).
Four ladders of Sonnet 4.6's two runs were re-run after an infrastructure error once Table 4
had been made, so the Sonnet 4.6 row these scripts print differs slightly from the paper's
Table 4; the other rows match it. Run them from the repository root; `dag_depth_score.py` and
the figure options need `matplotlib` (`pip install -r requirements.txt`).

| Command | Produces | Paper element |
|---|---|---|
| `python3 ablations/dag/dag_global_rule_checks.py [--json]` | The 18 follow-up requests with no incoming DAG edge, whose slot-3 "integration" check is really a global-rule check (`--json` also writes `artifacts/global_rule_checks.json`) | The exclusion noted in Table 4's caption |
| `python3 ablations/dag/dag_slot.py --four-group` | Grade per check type (functional / integration / global_rule / backward, x100) with the shared gate, plus the ungated RAW version | **Table 4** (via `evoweb.metrics.grade_by_type`) |
| `python3 ablations/dag/dag_slot.py --three-group` | The same without the global-rule split | An earlier form of Table 4 |
| `python3 ablations/dag/dag_slot.py [--figures]` | Integration slot vs the other four checks: RAW and NORM@55 per request, pairwise separations; `--figures` adds `slot_vs_rest.png`, `slot_auc_shared.png`, `slot_auc.png` | Sec. 5.1 discussion |
| `python3 ablations/dag/dag_depth_score.py` | Request score of requests 8-10 vs DAG depth and in-degree, one colour per model: `dag_depth_score.png`, `dag_depth_score_by_request.png`, `dag_indegree_r10_fits.png`, `dag_depth_score.json` and a slope table | **Figure 4** |
| `python3 ablations/dag/output_tokens_by_step.py [--json PATH] [--png PATH]` | Output tokens per agent step (mean +- std, request counts) from the released per-request `model_calls.jsonl` | **Figure 3c** is the cumulative version |
| `python3 ablations/dag/judge_steps_dag.py --logs-root DIR [--by-verdict]` | Judge iterations per check, by check type, from the judge transcripts (`<run-id>/<app>/turnN/eval/results/task*/agent.log`) | Sec. 5.1 / App. D discussion |

The judge transcripts are released for Fable 5's first run only (`examples_artifacts/full_traces/`).
`python3 -m evoweb.score_zip fable-5-run1` unpacks them into `runs/fable-5-run1/`, after which
`python3 ablations/dag/judge_steps_dag.py --logs-root runs` prints the Fable 5 row; the other
models print `--`.

## Check types

Every follow-up request (R2-R10) carries five judge checks, by slot (`task_idx`):

| slot | type | what it tests |
|---|---|---|
| 0-2 | functional | the request's own feature (exact values, behaviour) |
| 3 | integration | the DAG's own check: the new feature composed with an earlier request's |
| 4 | backward | a check copied from an earlier request, re-testing its feature |

When a request has no incoming DAG edge, slot 3 has nothing to integrate with and checks one of
the app's global rules instead; `dag_global_rule_checks.py` lists those 18 requests and every
table here scores them as `global_rule`, never as integration.

## Gate replay

Runs execute ungated (every request is judged). The tables replay the tolerance gate offline
with the SHARED five-check request accuracy: at threshold t the ladder dies at the first request
scoring below t (that request still counts, later ones score 0), and every check type is
averaged over exactly the (request, type) cells the dataset gives it. Grade per type is the
trapezoid AUC over t = 0..100 % of that per-type curve, /100 -- the same integral as Table 2's
Grade, restricted to one check type.

## Not in this package

Table 2's two error columns (build-error and runtime-error % per request, Sec. 5.2) come from a
scan of the judge and browser-console logs; that scan is not part of this package, and those logs
are released only for Fable 5's first run.
