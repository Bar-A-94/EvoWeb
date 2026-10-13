"""The `bash` generator: a shell-and-edit agent with no CLI to install.

Its agent is `program.py` in this package, so there is nothing to download and the only
requirement is a Python interpreter. That also makes it the control arm for the others:
same model, same endpoint, same task, minimal scaffold.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

VERSION = "1"  # ours, versioned with the repo
TOOLS = ["bash", "edit"]
EDIT_TOOL = "edit (path, old_str, new_str), single-occurrence replacement"
DEFAULT_EXCLUDE: list[str] = []
APPENDS_SYSTEM_PROMPT = True
# --history-file reloads the prior messages, tool results included.
SUPPORTS_RESUME = True
SUPPORTS_MAX_STEPS = True  # --max-steps bounds program.py's own loop: turns per user request

PROGRAM = Path(__file__).resolve().parent / "program.py"
TRAJECTORY = "trajectory.jsonl"
KEY_VAR = "BASH_AGENT_API_KEY"


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
        raise ValueError(f"{__package__} ships only bash and edit; nothing to exclude")
    if api != "anthropic-messages":
        raise ValueError(f"the bash agent speaks the Anthropic Messages API, not {api!r}")
    prefix.mkdir(parents=True, exist_ok=True)
    task_file = prefix / "task.txt"
    task_file.write_text(instruction)
    command = [
        sys.executable,
        str(PROGRAM),
        "--model",
        model,
        "--base-url",
        base_url,
        "--key-var",
        KEY_VAR,
        "--task-file",
        str(task_file),
        "--trajectory",
        str(out / TRAJECTORY),
        # Beside the workspace, not inside it: the conversation has to survive every turn of a
        # ladder, and anything written into the workspace becomes part of the app under test.
        "--history-file",
        str(workspace.parent / f"history_{workspace.name}.json"),
        "--max-steps",
        str(max_steps),
    ]
    if system_prompt:
        system_file = prefix / "system.txt"
        system_file.write_text(system_prompt)
        command += ["--system-file", str(system_file)]
    return {
        "command": command,
        "env": {KEY_VAR: api_key},
        # Declared so session.run can seed it from the passed history when a restored checkpoint
        # has the workspace but not this file (it lives outside the tarball).
        "history_file": str(workspace.parent / f"history_{workspace.name}.json"),
        "events": events,
    }


def events(out: Path) -> list[dict]:
    """The agent writes the shared event shape as it goes, so this only reads it back."""
    path = out / TRAJECTORY
    if not path.is_file():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
