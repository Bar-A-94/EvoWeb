"""The event shape every harness produces, and how a run is summarised from it.

The ACP client streams these as session updates; a harness that does not speak ACP builds the
same shape from whatever its CLI left behind, so this module is the definition of that contract.
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path


def call_command(update: dict) -> str | None:
    """The shell command an update carries, if any.

    Hermes truncates its ACP title at ~104 chars (`cd /very/long/path...`) but puts the
    whole command in a content block as `$ <command>`, so the title alone loses what ran.
    """
    for item in update.get("content") or []:
        text = ((item or {}).get("content") or {}).get("text") if isinstance(item, dict) else None
        if isinstance(text, str) and text.startswith("$ "):
            return text[2:].strip()
    args = update.get("raw_input") or {}
    return args.get("command") if isinstance(args, dict) else None


def call_paths(update: dict) -> set[str]:
    """File paths an update mentions, wherever the harness chose to put them."""
    paths = {
        location["path"]
        for location in update.get("locations") or []
        if isinstance(location, dict) and location.get("path")
    }
    args = update.get("raw_input") or {}
    if isinstance(args, dict):
        paths |= {str(args[key]) for key in ("path", "file_path", "notebook_path") if args.get(key)}
    for item in update.get("content") or []:
        if isinstance(item, dict) and item.get("path"):
            paths.add(str(item["path"]))
    return paths


def summarize(events: list[dict], workspace: Path | None = None) -> dict:
    """Tool histogram, files touched and per-call timings from ACP events.

    `workspace` makes every path workspace-relative. Without it the artifacts leak absolute
    paths from the box, and OpenHands titles its calls in prose ("Create Alerts page for SMS
    alert configuration: Editing /data/.../Alerts.jsx"), so every edit became its own
    histogram key.

    Harnesses fill a call in differently: pi puts the title, arguments and locations on the
    opening event, while Claude Code opens with a stub and adds the refined title, the
    locations and the diff on later updates. So every update for a call is folded in, and
    paths are read from locations, arguments and diff content alike.
    """
    calls: dict[str, dict] = {}
    order: list[dict] = []
    files: set[str] = set()
    for event in events:
        if event.get("kind") != "session_update":
            continue
        update = event.get("update") or {}
        call_id = update.get("tool_call_id")
        if not call_id:
            continue
        if call_id not in calls:
            calls[call_id] = {"started": event["ts"], "paths": set()}
            order.append(calls[call_id])
        call = calls[call_id]
        call["kind"] = update.get("kind") or call.get("kind")
        if update.get("title"):
            call["title"] = update["title"]
        if command := call_command(update):
            call["command"] = command
        if update.get("raw_input"):
            call["args"] = update["raw_input"]
        if update.get("status"):
            call["status"] = update["status"]
        # The tool's own result. Without it a failed span says only "tool call failed" and the
        # reason (`cd: /project: No such file or directory`) exists nowhere in the trace.
        if output := _output_of(update):
            call["output"] = output
        call["ended"] = event["ts"]
        found = call_paths(update)
        call["paths"] |= found
        files |= found
    if workspace:
        files = {_relative(path, workspace) for path in files}
    for call in order:
        call["paths"] = (
            {_relative(path, workspace) for path in call["paths"]} if workspace else call["paths"]
        )
        # A shell call is titled with the command itself and an edit may be titled in prose,
        # so the histogram would get one key per call; name both by what they did and keep
        # the harness's own title alongside.
        if call.get("kind") == "execute":
            call["tool"] = "bash"
        elif call.get("kind") == "edit":
            call["tool"] = f"edit {sorted(call['paths'])[0]}" if call["paths"] else "edit"
        else:
            # Everything else by its ACP kind: OpenHands labels each step in prose, which
            # made one histogram key per call and nothing comparable across harnesses.
            call["tool"] = call.get("kind") or call.get("title")
        # pi carries the command as the title, others in a content block; `command` means
        # the same thing for every harness.
        if call.get("kind") == "execute" and not call.get("command") and call.get("title"):
            call["command"] = call["title"]
        call["paths"] = sorted(call["paths"])
        call["duration_s"] = round(call["ended"] - call["started"], 2)
    return {
        "tool_calls": len(order),
        "tools_used": dict(Counter(call["tool"] for call in order if call.get("tool"))),
        "tool_kinds": dict(Counter(call["kind"] for call in order if call.get("kind"))),
        "failed_tool_calls": sum(1 for call in order if call.get("status") == "failed"),
        "files_touched": sorted(files),
        "files_written": sorted(
            {path for call in order if call.get("kind") == "edit" for path in call["paths"]}
        ),
        "calls": order,
    }


def _relative(path: str, workspace: Path) -> str:
    """Workspace-relative where it can be: harnesses report absolute and relative alike."""
    candidate = Path(path)
    return (
        str(candidate.relative_to(workspace))
        if candidate.is_absolute() and candidate.is_relative_to(workspace)
        else path
    )


def _output_of(update: dict) -> str | None:
    """A tool call's result text, wherever the harness put it."""
    if isinstance(update.get("raw_output"), (str, int, float)):
        return str(update["raw_output"])
    if isinstance(update.get("raw_output"), dict):
        return json.dumps(update["raw_output"])[:4000]
    for item in update.get("content") or []:
        text = ((item or {}).get("content") or {}).get("text") if isinstance(item, dict) else None
        if isinstance(text, str) and not text.startswith("$ "):
            return text[:4000]
    return None
