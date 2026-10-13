"""One way to run a harness: start it in the workspace, collect its reply and its events.

Harnesses differ only in how they report progress. The ones that speak ACP (the JSON-RPC
protocol these CLIs use with editors) are driven through the vendored client in `acp/`,
which streams every tool call as it happens; the rest are plain programs whose module
converts whatever they left behind into the same events. Both end up here, so the process
group, the timeout, the stderr log and the failure message are written once.

Upstream has no ACP adapter for mini-swe-agent, and our own `bash` harness is a
batch program, so wrapping them in a fake ACP server would invent protocol events from
batch output rather than observe them.
"""

from __future__ import annotations

import json
import os
import signal
import subprocess
from contextlib import suppress
from pathlib import Path

CLIENT = Path(__file__).resolve().parent / "acp" / "client.py"
TAIL_CHARS = 4_000


def _seed_history_file(launch: dict, history: list[dict] | None) -> None:
    """Give a program harness its conversation back when only the workspace was restored.

    The program arms keep their conversation in a file beside the workspace, and
    `checkpoint.save_checkpoint` tars the workspace alone, so a pod evicted mid-ladder came back
    with the files but no history: those two arms silently rebuilt from scratch for the rest of the
    run while still reporting SUPPORTS_RESUME. `turn_history` IS checkpointed, so write it out when
    the file is missing. Never overwrite a file the harness already has: it is richer than
    turn_history, carrying tool calls and their results.
    """
    path = launch.get("history_file")
    if not path or not history:
        return
    target = Path(path)
    if target.exists():
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(history))


def run(
    launch: dict,
    *,
    prompt: str,
    workspace: Path,
    out: Path,
    timeout: int,
    history: list[dict] | None = None,
    session_path: Path | None = None,
) -> tuple[str, list[dict]]:
    """Run the harness once in `workspace`. Returns its final text and every event.

    Raises `subprocess.TimeoutExpired` on timeout, having killed the whole process group so
    the harness's own children (its ACP server, its shells) die with it, and `RuntimeError`
    if it exits non-zero.
    """
    trajectory = out / "trajectory.jsonl"
    command, env = launch["command"], {**os.environ, **launch["env"]}
    _seed_history_file(launch, history)
    if acp := launch.get("acp"):
        config = _acp_config(launch, acp, prompt, out, history=history, session_path=session_path)
        # The client unlinks the config once it has read it, so record what we sent in a file
        # that survives. On a ladder this is the only evidence of whether the conversation
        # actually grew, and whether a resume was attempted or a fresh session opened.
        (out / "acp_sent.json").write_text(
            json.dumps(
                {
                    "resume_attempted": bool(session_path and Path(session_path).exists()),
                    "session_path": str(session_path) if session_path else None,
                    "messages": [
                        {"role": m.get("role"), "chars": len(str(m.get("content") or ""))}
                        for m in [*(history or []), {"role": "user", "content": prompt}]
                    ],
                },
                indent=2,
            )
        )
        command = ["uv", "run", "--script", str(CLIENT), "once", str(config)]
        # The client is a self-contained script that resolves its own dependency, and it
        # writes the trajectory itself as events arrive.
        env |= {"ACP_TRAJECTORY_PATH": str(trajectory), "UV_FROZEN": "false"}
    log = out / "agent.log"
    with open(log, "w") as errlog:
        process = subprocess.Popen(
            command,
            cwd=workspace,
            env=env,
            # No stdin: a harness that asks a question headless must hit EOF, not block
            # forever. mini-swe-agent's first-run setup hung a whole run this way.
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=errlog,
            text=True,
            start_new_session=True,
        )
        try:
            stdout, _ = process.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            with suppress(OSError):
                os.killpg(os.getpgid(process.pid), signal.SIGKILL)
            process.communicate()
            raise

    if launch.get("events"):
        # The caller persists the trajectory for every harness, so there is one writer.
        events = launch["events"](out)
    else:
        events = (
            [json.loads(line) for line in trajectory.read_text().splitlines()]
            if trajectory.exists()
            else []
        )
    if process.returncode != 0:
        raise RuntimeError(
            f"{'ACP client' if acp else 'harness'} exited {process.returncode}; "
            f"last of {log.name}: {log.read_text(errors='replace')[-TAIL_CHARS:]}"
        )
    # A harness whose stdout is progress chatter supplies its own final text instead.
    reply = launch["reply"](out) if launch.get("reply") else None
    return (reply if reply is not None else (stdout or "")).strip(), events


def _acp_config(
    launch: dict,
    acp: dict,
    prompt: str,
    out: Path,
    *,
    history: list[dict] | None = None,
    session_path: Path | None = None,
) -> Path:
    config = out / "acp_config.json"
    # Multi-turn: `history` is the accumulated [user, assistant, ...] of the earlier turns and
    # `session_path` persists the ACP session id across them. The client uses whichever the
    # agent supports — it resumes and sends only the new tail when the agent advertises
    # resume, and otherwise opens a new session and replays the whole role-tagged transcript.
    # Single-turn callers pass neither and get the previous one-message behaviour.
    config.write_text(
        json.dumps(
            {
                "command": launch["command"],
                "messages": [*(history or []), {"role": "user", "content": prompt}],
                # No MCP and no skills: an app build needs files plus bash, nothing else.
                "mcp_urls": {},
                # Harnesses take a system prompt through their own config, not the ACP prompt.
                "system_prompt": "",
                "session_path": str(session_path) if session_path else None,
                "session_meta": acp.get("session_meta", {}),
                "allow_empty_tool_reply": acp.get("allow_empty_tool_reply", False),
            }
        )
    )
    return config
