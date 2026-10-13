"""OpenHands over its own ACP server (`openhands acp`)."""

from __future__ import annotations

import json
from pathlib import Path

VERSION = "1.16.0"
# The tool-spec names in its settings store, plus the always-on FinishTool and ThinkTool.
TOOLS = ["terminal", "file_editor", "task_tracker", "task_tool_set"]
EDIT_TOOL = "file_editor (command, path, old_str/new_str)"
# task_tool_set carries its skills and subagents, task_tracker its planner. An app build
# needs files plus bash, and it spends a model call each on a design skill and a plan.
# RESOLVED tool names, not spec keys: task_tool_set resolves to a tool called `task`, and
# excluding only the key left the subagent live. Check the "Loaded N tools from spec" line.
DEFAULT_EXCLUDE = ["task_tracker", "task_tool_set", "task"]
APPENDS_SYSTEM_PROMPT = False
# ACP session resume, verified on the wire: turn 2 carried turn 1's full context.
SUPPORTS_RESUME = True
# Upstream's cap (LocalConversation.max_iteration_per_run) is unreachable over ACP: no env var,
# no CLI flag, and the settings store is an Agent spec. entry.py patches the constructor.
# Counts turns per user request.
SUPPORTS_MAX_STEPS = True


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
    prefix.mkdir(parents=True, exist_ok=True)
    script = prefix / "entry.py"
    script.write_text(
        (Path(__file__).resolve().parent / "entry.py").read_text().replace("{version}", VERSION)
    )
    # Its settings store lives under the persistence dir; a fresh one per run means no MCP
    # servers and no model config inherited from ~/.openhands.
    persistence = prefix / "openhands-state"
    # It reaches the model through litellm, which needs the provider in the model string.
    if "/" not in model:
        model = f"{'anthropic' if api.startswith('anthropic') else 'openai'}/{model}"
    return {
        # --always-approve keeps it from asking the client to confirm every action.
        "command": ["uv", "run", "--script", str(script), "acp", "--always-approve"],
        "env": {
            "LLM_MODEL": model,
            "LLM_API_KEY": api_key,
            "LLM_BASE_URL": base_url,
            "OPENHANDS_EXCLUDE_TOOLS": json.dumps(exclude_tools),
            "OPENHANDS_MAX_STEPS": str(max_steps),
            "OPENHANDS_PERSISTENCE_DIR": str(persistence),
            "OPENHANDS_WORK_DIR": str(workspace),
            "UV_FROZEN": "false",
        },
        "acp": {"allow_empty_tool_reply": True},
    }
