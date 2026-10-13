"""Run a harness as a WebGen-Bench generation backend.

One contract for every harness: instruction -> built Vite/React app
dir, so the rest of run_single_sample.py stays generator-agnostic. The harness works
directly in <workspaces>/sample_<idx>/, which we hand to start_app.

Per sample it writes, under <output_dir>/generation/:
  trajectory.jsonl  every event: tool calls with their arguments, diffs, statuses
  summary.json      wall clock, tool histogram, files touched and written, final reply
  tools.json        the tools the harness ships with, and the ones it actually used
  agent.log         the harness's own stderr
  model_calls.jsonl every model request: model, tokens, latency, status
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import time
from pathlib import Path

from . import capture, events, langfuse, session
from .harnesses import MODULES, build
from .pricing import cost_usd

# The build guidance every harness gets: appended to its system prompt where it has one, and
# prepended to the task where it does not. The task text itself stays verbatim.
APP_SYSTEM_PROMPT = """You are building a web app in the current directory, which already \
contains a minimal Vite + React + Tailwind project: `src/App.jsx` holds the nav and the \
routes, `src/pages/Home.jsx` is the one starter page, and `@/` aliases `src/`. Extend it in \
place and keep it simple: add a page as `src/pages/<Name>.jsx`, then register it by editing \
`src/App.jsx` to add one `<Route>` for it. Do not scaffold a new project, do not change the \
build tooling, and do not add \
a UI component library. Style with Tailwind classes. There is no \
backend, so hold data in React state and persist it to localStorage if the app needs it to \
survive a reload. IMPORTANT: whenever the app shows a list of things (products, tasks, \
listings, contacts, records, entries), define 2-3 realistic example items as a constant in \
the source and use them as the initial data, so the app looks populated the first time it \
is opened with no setup. Never ship a list that starts empty waiting for the user to add \
the first item. `npm run build` must succeed when you are done. NEVER run a dev server or any \
command that does not exit (`npm run dev`, `vite`, `npm start`, watchers): it blocks this \
session until it is killed. Verify with `npm run build` instead. When you are finished, \
reply with a one-line summary."""

# Page-registration sentence of the guidance, in its two historical versions. The paper's
# Anthropic runs (image multi_turn-6601fa42: Haiku/Sonnet/Opus r1-r3, Fable r1-r2) were told to
# add a nav <Link> for every page; every later image (Fable r3, GPT-5.6, GLM, Kimi, DeepSeek,
# Qwen) was not (commits 2687895b + b2451cff, merged 2026-08-20). The WebVoyager judge reaches
# pages by clicking, so the sentence moves scores: without it a full local Haiku run scored
# Grade 0.304 against the paper's 0.377. WEBGEN_NAV_GUIDANCE=on|off picks the version; the
# default is "on", the paper's Anthropic rows. evoweb/arms.py records the setting of every arm.
_REGISTER_WITHOUT_NAV = "`src/App.jsx` to add one `<Route>` for it."
_REGISTER_WITH_NAV = (
    "`src/App.jsx` to add one `<Route>` and one `<Link>` in the nav, so every page is reachable "
    "by clicking."
)
_TEMPLATE_COMMENT_WITHOUT_NAV = (
    "// Add a page: create src/pages/<Name>.jsx, import it here, and add one <Route>.\n"
)
_TEMPLATE_COMMENT_WITH_NAV = (
    "// Add a page: create src/pages/<Name>.jsx, import it here, and add one <Route>\n"
    "// plus one <Link> in the nav so it is reachable by clicking.\n"
)


def nav_guidance() -> bool:
    """WEBGEN_NAV_GUIDANCE, default "on" (the paper's Anthropic image)."""
    value = os.environ.get("WEBGEN_NAV_GUIDANCE", "on").strip().lower()
    if value not in ("on", "off"):
        raise ValueError(f"WEBGEN_NAV_GUIDANCE must be 'on' or 'off', got {value!r}")
    return value == "on"


def app_system_prompt() -> str:
    """APP_SYSTEM_PROMPT in the version WEBGEN_NAV_GUIDANCE selects."""
    if not nav_guidance():
        return APP_SYSTEM_PROMPT
    assert APP_SYSTEM_PROMPT.count(_REGISTER_WITHOUT_NAV) == 1
    return APP_SYSTEM_PROMPT.replace(_REGISTER_WITHOUT_NAV, _REGISTER_WITH_NAV)


def apply_template_nav_comment(workspace: Path) -> None:
    """Give a freshly copied template the scaffold comment WEBGEN_NAV_GUIDANCE selects."""
    if not nav_guidance():
        return
    app = workspace / "src" / "App.jsx"
    text = app.read_text()
    if _TEMPLATE_COMMENT_WITHOUT_NAV in text:
        app.write_text(text.replace(_TEMPLATE_COMMENT_WITHOUT_NAV, _TEMPLATE_COMMENT_WITH_NAV))


# Call-efficiency nudge (2026-08-19, replaces the explicit turn-budget notice): pushes the
# model toward fewer, denser turns WITHOUT naming the cap, so behavior is not anchored to a
# specific number and stays comparable across cap experiments (15/20/30).
EFFICIENCY_NOTICE = (
    "CRITICAL: Write multiple files or sections of files doing parallel tool calls "
    "when possible, it is MUCH more efficient"
)


def with_turn_budget(system_prompt: str | None, max_steps: int) -> str | None:
    """Append the efficiency nudge to `system_prompt` (or make it the whole prompt).

    Applied only when a turn budget is actually enforced (max_steps > 0), same seam as the
    old budget notice — the nudge exists because a cap exists. WEBGEN_EFFICIENCY_NUDGE=off
    drops it (prompt-ablation runs); default on.
    """
    if max_steps <= 0 or os.environ.get("WEBGEN_EFFICIENCY_NUDGE", "on").lower() == "off":
        return system_prompt
    return f"{system_prompt}\n\n{EFFICIENCY_NOTICE}" if system_prompt else EFFICIENCY_NOTICE


HARNESS_DEFAULT = "<harness-default>"
"""`system_prompt` sentinel: deliver APP_SYSTEM_PROMPT the way the harness allows.

Some harnesses have no seam for an appended prompt (mini-swe-agent builds its
own; OpenHands takes its from stored settings), so they get the same text as a prefix on the
task instead. Dropping it for them would leave them without the template layout or the
dev-server ban that hangs a rollout, and would make their scores incomparable.
"""

TEMPLATE = Path(__file__).resolve().parent / "template"
"""Minimal Vite + React + Tailwind scaffold, 9 files. Routes live in `src/App.jsx`, so
there is no extensionless config file for a `.jsx` sibling to shadow."""


# Turn budget for ONE USER REQUEST: a turn is one LLM request to the API, and an agent takes many
# of them to satisfy one dataset prompt. Every harness gets the same budget so a comparison is not
# secretly a comparison of budgets; one that cannot enforce it says so in its own module.
# Fallback only: run_sample.sh and the Kubernetes job template always pass AGENT_MAX_TURNS.
DEFAULT_MAX_STEPS = 20
# Must match acp/client.py's BUDGET_MARKER: the client is a separate process, so the two cannot
# share an import. A request that spends its turn budget returns this instead of a reply.
BUDGET_MARKER = "[turn budget exhausted]"


def agent_calls(model_calls: list[dict]) -> list[dict]:
    """The agent's own calls, dropping a harness's interleaved helpers.

    Selection is by modal tool count, tie-broken toward the HIGHER count: openhands' history
    condenser sends no tools, so a plain `key=tools.count` resolves an even split by set-iteration
    order and picks the condenser, reporting a healthy request as a lost conversation.
    """
    tools = [call.get("tools") or 0 for call in model_calls]
    if not tools:
        return []
    busiest = max(set(tools), key=lambda n: (tools.count(n), n))
    return [model_calls[i] for i, count in enumerate(tools) if count == busiest]


def agent_first(model_calls: list[dict]) -> dict:
    """The agent's first call, or the request's first if it made none."""
    return (agent_calls(model_calls) or model_calls)[0]


def budget_exhausted(reply: str, max_steps: int, model_calls: list[dict]) -> bool:
    """Did this request stop because it ran out of turns rather than because it finished?

    Only the ACP path reports a spent budget, and it is the minority case: over 774 requests of the
    first wave, 6 carried the marker while 109 had actually stopped at the cap. So the call count
    is the reliable signal, or a truncated request reads as a finished one in every non-ACP harness.

    Counts the AGENT's calls, not everything that crossed the proxy: the cap each harness enforces
    is on its own iterations, so a harness that interleaves helper calls (openhands runs a history
    condenser on long contexts) would otherwise report a request that finished on its own as
    truncated. Not reproduced in the short runs here, where the condenser never fires.
    """
    spent = len(agent_calls(model_calls))
    return reply.strip() == BUDGET_MARKER or (max_steps > 0 and spent >= max_steps)


def resume_lost_history(
    history: list[dict] | None, model_calls: list[dict]
) -> tuple[bool, int, int]:
    """Did the agent start this request without the conversation it was given?

    Returns (lost, context seen on the agent's first call, context the history implies).

    The test is whether the history ARRIVED, measured in tokens, because harnesses disagree on
    how to carry it: some send one message per turn, others inline the whole trace into a single
    message. Counting messages calls the second kind a loss on every request.
    """
    if not history or not model_calls:
        return False, 0, 0
    usage = agent_first(model_calls).get("usage") or {}
    first_ctx = sum(
        int(usage.get(key) or 0)
        for key in ("input_tokens", "cache_read_input_tokens", "cache_creation_input_tokens")
    )
    # ~4 chars per token is coarse, which is why the threshold below is half rather than tight.
    want_ctx = len(json.dumps(history)) // 4
    return first_ctx * 2 < want_ctx, first_ctx, want_ctx


def _cost(totals: dict, model: str) -> float | None:
    """None, not 0, when the price catalog has no entry: a zero would read as a free arm."""
    try:
        return cost_usd(totals, model)
    except Exception as err:  # a pricing lookup must never fail a build
        _log(f"WARNING could not price {model}: {err}")
        return None


def _log(msg: str) -> None:
    print(f"[generators.backend] {msg}", file=sys.stderr, flush=True)


def shadowed_configs(workspace: Path) -> list[str]:
    """Extensionless imports that now resolve to the wrong file.

    A harness that writes `pages.config.jsx` beside the template's `pages.config.js` gets a
    green build and an app where every added page 404s, because Vite resolves `.js` first.
    Recording it is the only cheap signal: nothing else in the pipeline notices.
    """
    clashes = []
    for path in sorted((workspace / "src").glob("*.js")):
        sibling = path.with_suffix(".jsx")
        if sibling.exists():
            clashes.append(f"{path.name} shadows {sibling.name}")
    return clashes


def _publish_failure(
    harness, index, task_id, model, base_url, gen_dir, workspaces, recorder, wall, error, max_steps
) -> None:
    """Keep the evidence from a run that raised: the calls it made and why it stopped."""
    calls = recorder.calls
    (gen_dir / "model_calls.jsonl").write_text("".join(json.dumps(call) + "\n" for call in calls))
    summary = {
        "harness": harness,
        "index": index,
        "task_id": task_id,
        "model": model,
        "base_url": base_url,
        "wall_clock_s": wall,
        "error": f"{type(error).__name__}: {error}",
        "max_steps": max_steps,
        **recorder.totals(),
        "cost_usd": _cost(recorder.totals(), model),
    }
    (gen_dir / "summary.json").write_text(json.dumps(summary, indent=2))
    langfuse.publish(
        summary,
        [],
        instruction="",
        # Same session as the success path: a request that raised is the one you most want to read
        # next to the rest of the ladder, and a per-request id filed it on its own.
        session_id=os.environ.get("LANGFUSE_SESSION_ID") or workspaces.parent.name,
        model_calls=calls,
    )
    _log(f"sample {index}: {summary['error']} after {wall}s, {len(calls)} model calls recorded")


def generate(
    *,
    harness: str,
    index: int,
    instruction: str,
    model: str,
    api_key: str,
    output_dir: Path,
    workspaces: Path,
    base_url: str = "https://api.anthropic.com",
    api: str = "anthropic-messages",
    template: Path | None = TEMPLATE,
    system_prompt: str | None = HARNESS_DEFAULT,
    exclude_tools: list[str] | None = None,
    pkgs: Path | None = None,
    # Whole-request wall clock. Env-overridable because two sonnet EvoWeb requests (2@R7, 3@R9)
    # deterministically outlive 2700s once the per-call ceiling was lifted — a repair pod
    # sets WEBGEN_TURN_TIMEOUT rather than needing a code change per experiment.
    timeout: int | None = None,
    task_id: str | None = None,
    history: list[dict] | None = None,
    session_file: Path | None = None,
    max_steps: int = DEFAULT_MAX_STEPS,
) -> dict:
    """Build one sample's app with `harness`. Returns {"app_dir", "start_action", "reply"}.

    On a multi-request ladder the caller passes the accumulated `history` and a per-sample
    `session_file`, and appends the returned `reply` before the next request. `reply` is in the
    result so the conversation can grow without the caller re-reading the trajectory.
    """
    workspace = workspaces / f"sample_{index:06d}"
    # A ladder on a harness that cannot continue a conversation is not multi-request, it is N
    # one-shot builds sharing a directory — and it looks like a valid result. Refuse instead.
    # Default False so a harness that never declares it fails here rather than silently.
    if history and not MODULES[harness].SUPPORTS_RESUME:
        raise RuntimeError(
            f"harness {harness!r} was given {len(history)} messages of history but does not "
            "support resuming a conversation; it would ignore them and rebuild from the files "
            "on disk. Set SUPPORTS_RESUME once a continuation path is wired and verified."
        )
    gen_dir = Path(output_dir) / "generation"
    gen_dir.mkdir(parents=True, exist_ok=True)
    if template and not workspace.exists():
        shutil.copytree(
            template, workspace, ignore=shutil.ignore_patterns("node_modules", "dist", ".git")
        )
        apply_template_nav_comment(workspace)
    workspace.mkdir(parents=True, exist_ok=True)

    if system_prompt == HARNESS_DEFAULT:
        system_prompt = app_system_prompt()
    # Attach the turn-budget notice HERE, before the delivery split below, so it reaches
    # every harness the same way the rest of the guidance does (appended or folded).
    system_prompt = with_turn_budget(system_prompt, max_steps)
    # A harness that cannot take an
    # appended system prompt gets the text prepended to the task instead, so none builds
    # without the template layout and the dev-server ban.
    prompt, folded = instruction, bool(system_prompt) and not MODULES[harness].APPENDS_SYSTEM_PROMPT
    if folded:
        _log(f"{harness} takes no appended system prompt; prepending it to the task")
        prompt, system_prompt = f"{system_prompt}\n\n{instruction}", None

    prefix = Path(pkgs or workspaces.parent / "acp-packages") / harness
    # Hand the harness a local endpoint that forwards to the real one, so every model call
    # it makes is recorded. Agents get their base_url from us, so this is the only point
    # all of them pass through, whatever SDK they use internally.
    with capture.Capture(base_url) as recorder:
        launch = build(
            harness,
            prefix=prefix,
            workspace=workspace,
            model=model,
            base_url=recorder.base_url,
            api=api,
            api_key=api_key,
            system_prompt=system_prompt,
            exclude_tools=exclude_tools,
            # Only a program harness uses these: it takes the task through its own argv and
            # writes its trajectory next to our artifacts.
            instruction=prompt,
            out=gen_dir,
            max_steps=max_steps,
        )

        _log(f"sample {index}: running {harness} ({model}) in {workspace}")
        start = time.time()
        try:
            reply, trajectory = session.run(
                launch,
                prompt=prompt,
                workspace=workspace,
                out=gen_dir,
                timeout=timeout
                if timeout is not None
                else int(os.environ.get("WEBGEN_TURN_TIMEOUT") or 2700),
                history=history,
                session_path=session_file,
            )
        except Exception as error:
            wall = round(time.time() - start, 1)
            _publish_failure(
                harness,
                index,
                task_id,
                model,
                base_url,
                gen_dir,
                workspaces,
                recorder,
                wall,
                error,
                max_steps,
            )
            raise
        wall = round(time.time() - start, 1)
    model_calls = recorder.calls
    # What the arms actually sampled at. openhands runs 64k with thinking on, our bash agent
    # 16k with none — a real difference that nothing recorded, so a cross-harness score gap
    # looked like harness quality. Derived from the calls themselves, not from what we asked
    # for, since a harness sets these inside its own client.
    # Every distinct value, not just the first: setdefault kept the earliest non-None and a
    # harness that varies max_tokens mid-request was then under-reported by the very field whose
    # job is recording what the arm sampled at. Collapses to the scalar when it never varied.
    sampled = {}
    for key in ("max_tokens", "temperature", "thinking"):
        seen = []
        for call in model_calls:
            value = call.get(key)
            if value is not None and value not in seen:
                seen.append(value)
        if seen:
            sampled[key] = seen[0] if len(seen) == 1 else seen
    # Not `usage.thinking_tokens` — that key does not exist on the wire (observed keys:
    # input_tokens, output_tokens, output_tokens_details, cache_*): it is nested as
    # output_tokens_details.thinking_tokens. The flat key reported 0 while the
    # calls plainly carried thinking, which is worse than not reporting it at all.
    sampled["thinking_tokens_total"] = sum(
        int(((c.get("usage") or {}).get("output_tokens_details") or {}).get("thinking_tokens") or 0)
        for c in model_calls
    )
    # A resumed request is trusted on file existence alone: the ACP client sets is_new from
    # session_path.exists(), so when the agent no longer holds that conversation the request runs
    # on the instruction alone and still reports success. Record it rather than hide it.
    #
    # Judged on CONTEXT, not message count. A count alone misfires on any harness that inlines
    # the whole trace into one message: measured over the v3 runs, 13 requests tripped the
    # count-only rule and 10 of them carried 13,500-32,100 tokens on that single message, i.e.
    # the history was plainly there. Only 3 (~1,500-1,900 tokens) had genuinely started fresh.
    history_lost, first_ctx, want_ctx = resume_lost_history(history, model_calls)
    if history_lost:
        _log(
            f"warning: sample {index}: resume lost the conversation, this request ran without "
            f"history ({first_ctx:,} tokens of context on the first call, expected around "
            f"{want_ctx:,} from the history handed over)"
        )
    (gen_dir / "model_calls.jsonl").write_text(
        "".join(json.dumps(call) + "\n" for call in model_calls)
    )
    # One writer for the artifact: the ACP client streams it live, a program harness converts
    # it at the end, and either way the file downstream reads is written here.
    (gen_dir / "trajectory.jsonl").write_text(
        "".join(json.dumps(event) + "\n" for event in trajectory)
    )

    detail = events.summarize(trajectory, workspace)
    module = MODULES[harness]
    (gen_dir / "tools.json").write_text(
        json.dumps(
            {
                "harness": harness,
                # Only pi can enumerate its real tool set, off its installed package. Report
                # what the run actually had: excluded tools are not shipped for this sample.
                "shipped": sorted(
                    set(
                        module.shipped_tools(prefix)
                        if hasattr(module, "shipped_tools")
                        else module.TOOLS
                    )
                    - set(launch["excluded"])
                ),
                "excluded": launch["excluded"],
                "used": sorted(detail["tools_used"]),
                "edit_tool": module.EDIT_TOOL,
                "version": module.VERSION,
            },
            indent=2,
        )
    )
    clashes = shadowed_configs(workspace)
    if clashes:
        _log(f"sample {index}: WARNING shadowed module resolution: {'; '.join(clashes)}")
    totals = recorder.totals()
    summary = {
        "harness": harness,
        # The pin, which npm.py installs with --save-exact: a caret pin once silently ran
        # two different pi versions across one experiment.
        "version": module.VERSION,
        "shadowed_configs": clashes,
        "max_steps": max_steps,
        "max_steps_enforced": launch.get("max_steps_enforced", False),
        "index": index,
        "task_id": task_id,
        "model": model,
        "base_url": base_url,
        "wall_clock_s": wall,
        "events": len(trajectory),
        # Observed on the wire, so a cross-harness comparison has to state it: openhands
        # samples 64k with thinking on, our bash agent 16k with none.
        "sampled": sampled,
        **totals,
        # Priced off the proxy's own token counts, so it is the same measurement for every
        # harness rather than each agent's self-reported spend.
        "cost_usd": _cost(totals, model),
        "reply": reply.strip(),
        "system_prompt_appended": bool(system_prompt),
        "history_messages_sent": len(history or []),
        "history_lost": history_lost,
        "turn_budget_exhausted": budget_exhausted(reply, max_steps, model_calls),
        "system_prompt_in_task": folded,
        **{
            key: detail[key]
            for key in (
                "tool_calls",
                "tools_used",
                "tool_kinds",
                "failed_tool_calls",
                "files_touched",
                "files_written",
            )
        },
    }
    # Tracing is opt-in (LANGFUSE_* env) and best-effort: one trace per app, one span per
    # tool call, so a run is readable next to every other traced harness we run.
    trace_id = langfuse.publish(
        summary,
        detail["calls"],
        instruction=instruction,
        session_id=os.environ.get("LANGFUSE_SESSION_ID") or workspaces.parent.name,
        model_calls=model_calls,
    )
    if trace_id:
        summary["langfuse_trace_id"] = trace_id
    (gen_dir / "summary.json").write_text(
        json.dumps({**summary, "calls": detail["calls"]}, indent=2)
    )

    try:
        shutil.copytree(
            workspace,
            gen_dir / "workspace",
            # .claude-config is written beside the workspace now, not inside it, so this entry
            # matches nothing today. Kept because what it excludes is a credential fragment.
            ignore=shutil.ignore_patterns("node_modules", "dist", ".git", ".claude-config"),
        )
    except Exception as error:  # best-effort: the copy is for debugging only
        _log(f"warning: could not copy workspace for S3: {error}")

    # After the copy, not before: a harness that scaffolds into a subdirectory instead of the
    # workspace root is exactly the run whose files you need to see, and raising first left nothing
    # in S3 to look at. The summary is already written above, so the artifact survives too.
    if not (workspace / "package.json").exists():
        raise RuntimeError(f"{harness} produced no app at {workspace} (missing package.json)")

    _log(
        f"sample {index}: done in {wall}s, {summary['tool_calls']} tool calls {summary['tools_used']}"
    )
    return {
        "app_dir": str(workspace),
        "start_action": "npm run dev",
        "reply": reply,
        "history_lost": history_lost,
    }
