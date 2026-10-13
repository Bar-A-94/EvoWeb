"""Claude Code over @agentclientprotocol/claude-agent-acp."""

from __future__ import annotations

import json
from pathlib import Path

from ...npm import install

# The CLI and its ACP adapter are pinned together; bump both or neither.
VERSION, ACP_VERSION = "2.1.232", "0.67.0"

# Claude Code's documented tool set (the CLI owns the registry; not read off disk).
TOOLS = [
    "Bash",
    "BashOutput",
    "Edit",
    "Glob",
    "Grep",
    "KillShell",
    "NotebookEdit",
    "Read",
    "SlashCommand",
    "Task",
    "TodoWrite",
    "WebFetch",
    "WebSearch",
    "Write",
]
EDIT_TOOL = "Edit / Write / MultiEdit"
# Trim to files plus bash. These names are Claude Code's own.
DEFAULT_EXCLUDE = ["Task", "WebFetch", "WebSearch", "TodoWrite", "NotebookEdit"]
APPENDS_SYSTEM_PROMPT = True
# Verified on the wire (messages 1 -> 39 -> 59), not taken on trust. Re-check `history_lost`
# in summary.json after any ACP client change.
SUPPORTS_RESUME = True
# The adapter spreads `_meta.claudeCode.options` into the SDK query, so any Agent SDK option
# reaches the agent loop, `maxTurns` included: turns per user request.
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
    # ignore_scripts=False: Claude Code's postinstall downloads its native binary, and
    # without it every session dies with "claude native binary not installed".
    node_bin = install(
        prefix,
        [
            f"@anthropic-ai/claude-code@{VERSION}",
            f"@agentclientprotocol/claude-agent-acp@{ACP_VERSION}",
        ],
        ["claude", "claude-agent-acp"],
        ignore_scripts=False,
    )
    # Beside the workspace, never inside it: `backend.generate` returns the workspace as `app_dir`
    # and the judge serves it with `npm run dev`, and vite's fs.deny covers only .env and certs,
    # so a config dir in there is fetchable. Verified: GET /.claude-config/.claude.json returned
    # 200 with the file, while /.env returned 403. The file holds the last 20 characters of the
    # API key, and the workspace is also uploaded to S3 as the run's artifact.
    config_dir = workspace.parent / f".claude-config-{workspace.name}"
    config_dir.mkdir(parents=True, exist_ok=True)
    # Claude Code will not use an API key it has not been told to trust: headless it
    # fails the first prompt with "Authentication required". Pre-approve this key (it
    # records the last 20 characters) and skip first-run onboarding.
    (config_dir / ".claude.json").write_text(
        json.dumps(
            {
                "hasCompletedOnboarding": True,
                "customApiKeyResponses": {"approved": [api_key[-20:]], "rejected": []},
            }
        )
    )
    session_meta: dict = {
        "claudeCode": {
            "options": {
                "strictMcpConfig": True,
                "disallowedTools": exclude_tools,
                # Agent SDK option, forwarded verbatim by the adapter. Hitting it ends the turn
                # with result subtype error_max_turns rather than killing the session.
                "maxTurns": max_steps,
            }
        }
    }
    if system_prompt:
        session_meta["systemPrompt"] = {"append": system_prompt}
    return {
        "command": ["node", str(node_bin / "claude-agent-acp")],
        "env": {
            # Claude appends /v1/messages itself, so hand it the API root.
            "ANTHROPIC_BASE_URL": base_url.removesuffix("/v1"),
            "ANTHROPIC_API_KEY": api_key,
            "ANTHROPIC_MODEL": model,
            "CLAUDE_CODE_EXECUTABLE": str(node_bin / "claude"),
            "CLAUDE_CONFIG_DIR": str(config_dir),
            "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1",
            "DISABLE_AUTOUPDATER": "1",
            "IS_SANDBOX": "1",
        },
        "acp": {"session_meta": session_meta, "allow_empty_tool_reply": False},
    }
