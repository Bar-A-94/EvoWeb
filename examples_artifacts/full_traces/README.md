# Full traces: Fable 5's first run, complete

`fable-5-run1.zip` holds everything Fable 5's first run produced on all 32 apps, except
screenshots: the agent's full conversations (prompt, thinking, tool calls, tool output), the
app's source code after every request, every judge session's conversation and browser console,
and the install, build and runner logs. `../traces.zip` keeps only the verdicts and token counts
this archive contains; the scores are the same. This run is one of the three behind the Fable 5
row of Table 2 and one of its two runs in Table 4. No other run is published in full; the
verdicts and token counts of the other three Anthropic models' runs are in `../traces.zip`.

Unpack and score it, checking it against the released verdicts:

```bash
python3 -m evoweb.score_zip fable-5-run1
```

This unpacks into `runs/fable-5-run1/` (an existing directory of that name is used as is, so
delete a partial one first) and prints its Grade and Survival next to the released copy; the
script exits with an error if the two differ. `--into <dir>` unpacks elsewhere. The layout
inside is the one `../examples.zip`'s README describes, one folder per app:

```
fable-5-run1/<app>/
  result.json, acp_session.txt      request 1 at the top level, turn2/ .. turn10/ below
  generation/                       trajectory.jsonl, model_calls.jsonl, summary.json, workspace/ ...
  eval/results/task<id>_<k>/        one judge session per check (no screenshot PNGs)
  logs/                             install, build, app start, judge and worker logs
  turn<N>/                          generation/, eval/, logs/ for request N
```

## Requests whose conversations were not kept

The runner checkpointed each app after every request, and when a pod was evicted a new pod
resumed from the last checkpoint. The evicted pod's conversations for the requests it had
finished were never uploaded. For those requests the archive holds the checkpoint instead,
`checkpoint/state.json` (the judge's verdicts, the same as in `result.json`) and
`checkpoint/workspace.tgz` (the app's code after the request), in place of `generation/` and
`eval/`. The agent then continued without its conversation history, from the code alone
(`logs/worker.log` records it).

| App | Requests without conversations |
|---|---|
| 000008 | 1-2 |
| 000009 | 1-2 |
| 000013 | 1-3 |
| 000014 | 1-3 |
| 000022 | 1 |
| 000026 | 1-2 |

Three strings were replaced so the files carry no infrastructure details: the pods' private
IPs read `POD_IP`, the internal run name reads `fable-5-run1`, and the storage upload line reads
`Uploading results`.
