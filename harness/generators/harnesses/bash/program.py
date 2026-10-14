"""A minimal shell-and-edit coding agent, run as a program by the `bash` generator.

It talks to the Anthropic Messages API directly, which is the same endpoint the other
generators use, and writes each tool call to a trajectory file in the shared event shape.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

API_VERSION = "2023-06-01"
# Bounded, so a genuinely broken key still fails fast rather than burning the turn budget.
RETRIES = 4
RETRY_STATUS = (408, 429, 500, 502, 503, 504, 529)
BACKOFF = 2.0
# HARNESS_LLM_TIMEOUT is the ONE knob for every harness's per-call deadline, so a harness
# comparison is not secretly a timeout comparison. 300s (the old value, and litellm's default
# that openhands explicitly overrides) is too short for a thinking model on a large context:
# measured 2026-08-30, sonnet at a 16k thinking budget blew through it at request 4 with 104
# prior messages, retried 4x, and the ladder died. Stays below the proxy's forward timeout so
# a genuinely stuck call still surfaces client-side first.
REQUEST_TIMEOUT = int(os.environ.get("HARNESS_LLM_TIMEOUT") or 1200)
# Overridable so arms can be aligned: this ceiling is arbitrary, unlike thinking, which is
# a genuine harness choice. openhands runs 64k with thinking on; ours ran 16k with none,
# and nothing recorded the difference.
MAX_TOKENS = int(os.environ.get("HARNESS_MAX_TOKENS") or 16_000)
OUTPUT_LIMIT = 20_000

BASH_TOOL = {
    "name": "bash",
    "description": "Run a bash command in the working directory and return its combined output.",
    "input_schema": {
        "type": "object",
        "properties": {"command": {"type": "string", "description": "The command to run."}},
        "required": ["command"],
    },
}
EDIT_TOOL = {
    "name": "edit",
    "description": "Replace a unique string in a file. old_str must appear exactly once.",
    "input_schema": {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "File path, relative or absolute."},
            "old_str": {"type": "string", "description": "Exact text to find; must be unique."},
            "new_str": {"type": "string", "description": "Replacement text."},
        },
        "required": ["path", "old_str", "new_str"],
    },
}


def run_bash(command: str, timeout: int) -> tuple[str, bool]:
    """Run one command, and make the timeout actually end it.

    subprocess.run's timeout kills only the shell it started, then waits for EOF on the pipes. A
    surviving grandchild still holds them, so a command like `npm run dev` (which the system prompt
    bans precisely because it never exits) blocks past this timeout until the session-level 2700s
    SIGKILL takes the whole user request with it. Own process group, then kill the group.
    """
    with subprocess.Popen(  # noqa: S602 - the agent's command is the point of this tool
        command,
        shell=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        start_new_session=True,
    ) as proc:
        try:
            output = proc.communicate(timeout=timeout)[0]
        except subprocess.TimeoutExpired:
            with contextlib.suppress(ProcessLookupError):
                os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            proc.wait()
            return f"error: command exceeded {timeout}s and its process group was killed", True
        failed = proc.returncode != 0
    return (output or "")[:OUTPUT_LIMIT] or "(no output)", failed


def run_edit(path: str, old: str, new: str) -> tuple[str, bool]:
    if not old:
        # '' matches everywhere, so this would insert rather than replace.
        return "error: old_str must be a non-empty string", True
    target = Path(path)
    if not target.is_file():
        return f"error: {path} not found", True
    text = target.read_text(errors="replace")
    found = text.count(old)
    if found != 1:
        return f"error: old_str must appear exactly once in {path} (found {found})", True
    target.write_text(text.replace(old, new, 1))
    return f"Edited {path}", False


def call_model(url: str, key: str, body: dict) -> dict:
    request = urllib.request.Request(
        f"{url.rstrip('/')}/v1/messages",
        data=json.dumps(body).encode(),
        headers={
            "x-api-key": key,
            "anthropic-version": API_VERSION,
            "content-type": "application/json",
        },
        method="POST",
    )
    # Retry transient failures. The other three arms retry inside their own clients (litellm, the
    # Agent SDK, openhands' retry_decorator), so without this one 429 or 529 ends the request, and
    # skip-on-failure then discards every later user request in the ladder: an arm asymmetry in a
    # comparison meant to differ only by scaffold. Honour retry-after when the server sends it.
    for attempt in range(RETRIES):
        try:
            with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT) as response:
                return json.loads(response.read())
        except urllib.error.HTTPError as error:
            body_text = error.read()[:500].decode(errors="replace")
            if error.code not in RETRY_STATUS or attempt == RETRIES - 1:
                raise RuntimeError(f"model call failed {error.code}: {body_text}") from error
            delay = float((error.headers or {}).get("retry-after") or 0) or BACKOFF * (2**attempt)
            print(
                f"  {error.code}, retrying in {delay:.0f}s ({attempt + 1}/{RETRIES})",
                file=sys.stderr,
            )
        except (TimeoutError, urllib.error.URLError, OSError) as error:
            if attempt == RETRIES - 1:
                raise
            delay = BACKOFF * (2**attempt)
            print(
                f"  {type(error).__name__}, retrying in {delay:.0f}s ({attempt + 1}/{RETRIES})",
                file=sys.stderr,
            )
        time.sleep(delay)
    raise RuntimeError("unreachable: the loop either returns or raises")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", required=True)
    parser.add_argument("--base-url", default="https://api.anthropic.com")
    parser.add_argument("--key-var", default="BASH_AGENT_API_KEY")
    parser.add_argument("--task-file", required=True)
    # Multi-request: the accumulated conversation of the earlier requests, tool results included.
    # Read before the new task and rewritten after, so request N starts where request N-1 stopped
    # rather than re-deriving the app from the files on disk.
    parser.add_argument("--history-file")
    parser.add_argument("--system-file")
    parser.add_argument("--trajectory", required=True)
    parser.add_argument("--max-steps", type=int, default=60)
    parser.add_argument("--command-timeout", type=int, default=300)
    args = parser.parse_args()

    key = os.environ.get(args.key_var)
    if not key:
        print(f"{args.key_var} is not set", file=sys.stderr)
        return 2
    trajectory = open(args.trajectory, "w")  # noqa: SIM115 - closed at the end of the run

    def record(
        call_id: str,
        kind: str,
        title: str,
        status: str,
        args_: dict | None = None,
        output: str | None = None,
    ) -> None:
        update = {"tool_call_id": call_id, "kind": kind, "title": title, "status": status}
        if args_ is not None:
            update["raw_input"] = args_
        # The result, so a failed call in the trace says WHY and not just "failed".
        if output is not None:
            update["raw_output"] = output[:4000]
        event = {
            "ts": time.time(),
            "kind": "session_update",
            "type": "ToolCallStart" if status == "pending" else "ToolCallProgress",
            "update": update,
        }
        trajectory.write(json.dumps(event) + "\n")
        trajectory.flush()

    prior: list[dict] = []
    if args.history_file and Path(args.history_file).exists():
        prior = json.loads(Path(args.history_file).read_text())
        print(f"resuming with {len(prior)} prior messages", file=sys.stderr)
    messages: list[dict] = [*prior, {"role": "user", "content": Path(args.task_file).read_text()}]
    body: dict = {
        "model": args.model,
        "max_tokens": MAX_TOKENS,
        "tools": [BASH_TOOL, EDIT_TOOL],
        # Top-level cache_control puts the breakpoint on the last cacheable block, so each
        # turn re-reads the conversation so far from cache instead of paying for it again.
        # Without it this agent sent a quarter of a million uncached input tokens per app.
        "cache_control": {"type": "ephemeral"},
    }
    if args.system_file:
        body["system"] = Path(args.system_file).read_text()

    reply = ""
    for _ in range(args.max_steps):
        response = call_model(args.base_url, key, {**body, "messages": messages})
        blocks = response.get("content") or []
        messages.append({"role": "assistant", "content": blocks})
        reply = (
            "\n".join(b.get("text", "") for b in blocks if b.get("type") == "text").strip() or reply
        )
        calls = [b for b in blocks if b.get("type") == "tool_use"]
        if not calls:
            break
        results = []
        for call in calls:
            name, arguments = call.get("name"), call.get("input") or {}
            kind = "execute" if name == "bash" else "edit"
            title = (
                str(arguments.get("command", ""))
                if name == "bash"
                else f"{name} {arguments.get('path', '')}"
            )
            record(call["id"], kind, title, "pending", arguments)
            if name == "bash":
                output, failed = run_bash(arguments.get("command", ""), args.command_timeout)
            elif name == "edit":
                output, failed = run_edit(
                    arguments.get("path", ""),
                    arguments.get("old_str", ""),
                    arguments.get("new_str", ""),
                )
            else:
                output, failed = f"error: unknown tool {name!r}", True
            record(call["id"], kind, title, "failed" if failed else "completed", output=output)
            results.append({"type": "tool_result", "tool_use_id": call["id"], "content": output})
        messages.append({"role": "user", "content": results})

    trajectory.close()
    if args.history_file:
        Path(args.history_file).write_text(json.dumps(messages))
        print(f"persisted {len(messages)} messages", file=sys.stderr)
    print(reply)
    return 0


if __name__ == "__main__":
    sys.exit(main())
