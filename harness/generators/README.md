# Harnesses

Run a coding agent over an EvoWeb app ladder. One folder per agent under `harnesses/`; the
pipeline never learns which one it is. The paper's runs all use `openhands`.

## Vocabulary

- **user request** — one prompt from the dataset. The 32-app set has 10 per app: the first builds
  the site, the other nine each edit what the previous one produced.
- **turn** — one LLM request to the API, i.e. one model call plus the tool executions it asks for.
  An agent takes many turns to satisfy one user request.

`AGENT_MAX_TURNS` (default 20) is the turn budget **for a single user request**. Ladder length
comes from the dataset's `follow_ups` and is never set by that knob.

Caveat for anyone reading artifacts: `result.json`'s `turns[]` and the `turnN/` directories are
one entry per USER REQUEST, not per turn. That naming predates this vocabulary and is left alone
because it is baked into the released traces.

## The harnesses

| `GENERATOR` | What runs | Pinned version | Notes |
|---|---|---|---|
| `openhands` | OpenHands over its own ACP server (`openhands acp`) | `openhands==1.16.0`, resolved by `uv` at start | **The paper's agent.** `entry.py` caps the turns per user request and pins sampling (`pin_sampling`) |
| `bash` | `bash/program.py`, a shell-and-edit agent of ours | with the repo | Not used in the paper. Speaks the Anthropic Messages API only (`PROVIDER=Anthropic`); nothing to install |
| `mini_swe_agent` | mini-swe-agent, bash-only, via litellm | 2.4.6 | Not used in the paper. `MINI_MODEL_CLASS=litellm_response` for Responses-API-only models |
| `claude_code` | Claude Code CLI over `@agentclientprotocol/claude-agent-acp` | 2.1.232 / adapter 0.67.0, installed with npm | Not used in the paper |

## What is in here

```
harnesses/      one package per harness, each exporting launch(); __init__.py holds MODULES and build()
backend.py      generate(): the --generator entry point; copies template/, launches, records artifacts
capture.py      forwarding proxy every model call passes through; records tokens, latency, bodies
session.py      the one runner: process group, timeout, reply and events
acp/            the vendored ACP client, for the harnesses that speak it
events.py       the event shape every harness produces, and how a run is summarised from it
pricing.py      cost in dollars from the proxy's token counts (OpenRouter's public catalog)
npm.py          node installs for the harness CLIs (claude_code)
langfuse.py     opt-in tracing (LANGFUSE_* env); off unless credentials are present
template/       the Vite + React + Tailwind scaffold the agent extends
```

## The contract

`harnesses/<name>/harness.py` exports `launch()` plus a few constants:

```python
VERSION, TOOLS, EDIT_TOOL, DEFAULT_EXCLUDE   # what it is, what it can do
APPENDS_SYSTEM_PROMPT                        # can it take our build guidance as a system prompt?
SUPPORTS_RESUME                              # can it continue an earlier conversation?
SUPPORTS_MAX_STEPS                           # can it cap the turns spent on one user request?
```

`launch()` takes the same keyword arguments for every harness and returns `command` and `env`,
plus `acp` (session metadata) for an ACP harness or an `events` converter for a program harness.
Register the module in `harnesses/__init__.py`'s `MODULES` and it is selectable everywhere.
`build()` refuses a system prompt the harness cannot append and a non-positive turn budget; a
budget the harness cannot honour is run uncapped with a warning and recorded as
`max_steps_enforced: false` in `summary.json`. All four shipped harnesses honour it.

## Two transports

- **ACP** (`claude_code`, `openhands`) — Agent Client Protocol, JSON-RPC over stdio. The agent runs
  as a server, we drive it with `acp/client.py`, and it streams structured events. Session resume
  is part of the protocol.
- **Program** (`bash`, `mini_swe_agent`) — a plain subprocess. It supplies an `events()` function
  that converts its own trajectory file into the same event shape, so nothing downstream cares.

## Wiring

```
run_local.sh / run_sample.sh
  GENERATOR=openhands               -> --generator, picks the module
  AGENT_MAX_TURNS=20                -> max_steps (turns per user request)
      |
  run_single_sample.py              per user request: generate -> build -> serve -> judge
      |
  generators/backend.py             template -> launch() -> record artifacts
      |
  generators/capture.py             a proxy every model call passes through
```

`capture.py` is why cost and multi-turn are measurable at all: it is the one point all four
harnesses cross, so tokens are counted the same way for each. It also applies the
`HARNESS_*` sampling pins listed in `../README.md`.

## Per user request, on disk

Under `generation/` (request 1) or `turn<N>/generation/` (requests 2-10):
`summary.json` (wall clock, tokens, `cost_usd`, `max_steps_enforced`, `turn_budget_exhausted`,
`history_lost`), `model_calls.jsonl` (every call, off the wire), `trajectory.jsonl` (every event),
`tools.json` (the tools the harness ships with and the ones it used), `agent.log` (its stderr).

## Tasksets

`data/evoweb_benchmark.jsonl` (32 apps x 10 user requests) is committed. The smoke sets under
`tests/smoke_sets/` are rows of it with the follow-ups trimmed, written by
`harness/make_tasksets.py` (the Dockerfile runs it during the build; run it yourself on bare
metal), so they are not committed: `evoweb_smoke_2apps_3requests.jsonl`,
`evoweb_smoke_3apps_2requests.jsonl` and `evoweb_2requests.jsonl` (all 32 apps, 2 requests each).
A set needs at least 2 requests per app: the harnesses reject a single-request row.
