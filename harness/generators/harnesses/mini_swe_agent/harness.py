"""mini-swe-agent: a bash-only agent, run as a program rather than an ACP server.

It is deliberately minimal upstream: one shell action per step and no file-edit tool, so every
edit goes through the shell. It also refuses to disable tools, because bash is the only one it
has.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

VERSION = "2.4.6"
TOOLS = ["bash"]
EDIT_TOOL = "none: edits go through shell commands"
DEFAULT_EXCLUDE: list[str] = []
# Upstream takes the task as argv and prepends its own prompt template; there is no seam
# for an appended system prompt.
APPENDS_SYSTEM_PROMPT = False
# Upstream restarts from an empty message list every call; entry.py intercepts that seed.
SUPPORTS_RESUME = True
SUPPORTS_MAX_STEPS = True  # AgentConfig.step_limit via --step-limit: turns per user request

TRAJECTORY = "mini_traj.json"


def launch(
    *,
    prefix: Path,
    workspace: Path,
    model: str,
    base_url: str,
    api: str,
    api_key: str,
    system_prompt: str | None,
    exclude_tools: list[str],
    instruction: str,
    out: Path,
    max_steps: int,
) -> dict:
    if exclude_tools:
        raise ValueError("mini_swe_agent has no named tools to disable")
    prefix.mkdir(parents=True, exist_ok=True)
    script = prefix / "entry.py"
    script.write_text(
        (Path(__file__).resolve().parent / "entry.py").read_text().replace("{version}", VERSION)
    )

    # Its model layer is litellm, so the model string carries the provider and the key
    # comes from that provider's env var.
    key_var = "ANTHROPIC_API_KEY" if "anthropic" in api else "OPENAI_API_KEY"
    env = {
        key_var: api_key,
        # Without this it reads ~/.config/mini-swe-agent/.env, pulling this machine's
        # settings into the run.
        "MSWEA_GLOBAL_CONFIG_DIR": str(prefix / "config"),
        "MSWEA_SILENT_STARTUP": "1",
        # Without this it runs its first-time `setup()`, which prompts for a model and an
        # API key and blocks the run.
        "MSWEA_CONFIGURED": "1",
        "UV_FROZEN": "false",
    }
    # litellm ignores a base URL unless it is in the provider's own env var, so without
    # this the run bypasses our capture proxy and its model calls go unrecorded.
    env["ANTHROPIC_API_BASE" if api.startswith("anthropic") else "OPENAI_API_BASE"] = base_url
    return {
        "command": [
            "uv",
            "run",
            "--script",
            str(script),
            "--model",
            model,
            "--model-class",
            # gpt-5.6-family models reject function tools + reasoning_effort on
            # /v1/chat/completions ("use /v1/responses"); MINI_MODEL_CLASS=litellm_response
            # switches mini to its Responses-API model for those arms. Default unchanged.
            os.environ.get("MINI_MODEL_CLASS") or "litellm",
            "--environment-class",
            "local",
            # `mini` defaults to the interactive agent, which aborts on a non-tty with
            # "Input is not a terminal" even under --yolo. The default agent is the
            # headless one.
            "--agent-class",
            "default",
            "--task",
            instruction,
            "--yolo",  # no interactive confirmation
            "--exit-immediately",  # finish instead of prompting when the agent is done
            "--cost-limit",
            "0",  # steps are the bound, not spend
            # AgentConfig.step_limit; it defaults to 0, meaning unlimited.
            "--step-limit",
            str(max_steps),
            "--output",
            str(out / TRAJECTORY),
            # Beside the workspace, not inside it: the conversation has to survive every request of
            # a ladder, and anything written into the workspace becomes part of the app under test.
            "--history-file",
            str(workspace.parent / f"mswe_history_{workspace.name}.json"),
        ],
        "env": env,
        # Declared so session.run can seed it from the passed history when a restored
        # checkpoint has the workspace but not this file (it lives outside the tarball).
        "history_file": str(workspace.parent / f"mswe_history_{workspace.name}.json"),
        "events": events,
        "reply": reply,
    }


def reply(out: Path) -> str | None:
    """The request's answer: the submission if there is one, else the last assistant prose.

    Not stdout, which is progress chatter. `info.submission` is the answer upstream itself
    considers final, so prefer it -- but only when it is non-empty: on a real run of ours it was
    "", and returning that would hand the ladder an empty assistant turn. The fallback walks back
    for the last assistant message with STRING content because a pure tool-call step has
    content=None (measured: 3 of 30 messages), so the final step is often not prose.
    """
    path = out / TRAJECTORY
    if not path.is_file():
        return None
    trajectory = json.loads(path.read_text())
    submission = ((trajectory.get("info") or {}).get("submission") or "").strip()
    if submission:
        return submission
    for message in reversed(trajectory.get("messages") or []):
        if message.get("role") == "assistant" and isinstance(message.get("content"), str):
            return message["content"].strip()
    return None


def events(out: Path) -> list[dict]:
    """Convert the saved trajectory into the event shape `summarize` reads.

    Shell commands live under an assistant message's `extra.actions`; the `role: tool` messages
    that follow carry the matching timestamp and returncode.
    """
    path = out / TRAJECTORY
    if not path.is_file():
        return []
    messages = json.loads(path.read_text()).get("messages") or []
    events: list[dict] = []
    for index, message in enumerate(messages):
        actions = (message.get("extra") or {}).get("actions") or []
        if not actions:
            continue
        started = (message.get("extra") or {}).get("timestamp")
        # The observations for these actions, in order, are the tool messages that follow.
        observations = [
            later.get("extra") or {}
            for later in messages[index + 1 :]
            if later.get("role") == "tool"
        ][: len(actions)]
        for position, action in enumerate(actions):
            command = action.get("command") if isinstance(action, dict) else str(action)
            observation = observations[position] if position < len(observations) else {}
            failed = bool(observation.get("returncode")) or bool(observation.get("exception_info"))
            common = {
                "tool_call_id": (action.get("tool_call_id") if isinstance(action, dict) else None)
                or f"mini-{index}-{position}",
                "kind": "execute",
                "title": command,
            }
            events.append(
                {
                    "ts": started,
                    "kind": "session_update",
                    "type": "ToolCallStart",
                    "update": {**common, "status": "pending", "raw_input": {"command": command}},
                }
            )
            events.append(
                {
                    "ts": observation.get("timestamp", started),
                    "kind": "session_update",
                    "type": "ToolCallProgress",
                    "update": {**common, "status": "failed" if failed else "completed"},
                }
            )
    return events
