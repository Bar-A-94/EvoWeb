#!/usr/bin/env python3
"""Run generation + evaluation for a single EvoWeb app ladder (one sample).

This script is the core "doer" — designed to run inside a Docker container
as one independent unit of work.  Give it a sample index and an API
endpoint, and for every user request of the ladder it will:

  1. Run the coding-agent harness (default: openhands) on the shared workspace
  2. npm install, compile-check, start the app
  3. Run the WebVoyager UI judge against that request's checks
  4. Record the per-request verdicts, cost and error class
and finally print a JSON result to stdout, write result.json + artifacts to
OUTPUT_DIR/<index:06d>/ and, only if an S3 bucket is configured, upload them.

The generators are the harnesses under generators/harnesses/ (openhands / bash /
mini_swe_agent / claude_code), selected with --generator; the paper's numbers come from
openhands on this code path.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import traceback

# timezone.utc, NOT datetime.UTC (ruff UP017): the worker image runs python 3.10, where
# datetime.UTC does not exist. A blind `ruff --fix` rewrote this once and broke every pod.
from datetime import datetime, timezone
from pathlib import Path
from typing import IO

import checkpoint
from generators.backend import DEFAULT_MAX_STEPS, generate
from generators.backend import TEMPLATE as WEBSITE_TEMPLATE
from generators.harnesses import MODULES as HARNESSES

# Shared error taxonomy — classify at failure time so results are trustable without log forensics.
from scoring import INFRA_CLASSES, classify_error, parse_verdict, scan_log
from webvoyager.recording import start_session_recording


def _utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d_%H-%M")  # noqa: UP017


# A request must reach this score for the ladder to continue. -1 disables score gating
# entirely (every score passes, 0 included): every surviving ladder runs all its requests and
# per-request scores are directly comparable with no survivor bias. History: >0 originally,
# 0.5 for the 2026-08 EvoWeb runs, -1 since 2026-08-18. NOTE: an errored request (status !=
# "success") still ends the ladder — there is no coherent workspace to build on.
TURN_GATE_THRESHOLD = -1


def ladder_continues(request_status: str, request_score: float) -> tuple[bool, str]:
    """A request under TURN_GATE_THRESHOLD ends the ladder; at -1 nothing does (score-wise)."""
    passed = request_status == "success" and request_score >= TURN_GATE_THRESHOLD
    reason = (
        "previous_turn_below_threshold"
        if request_status == "success"
        else "previous_turn_did_not_complete"
    )
    return passed, reason


# One video per pod process (see run_evaluation docstring).
_RECORDED_THIS_PROCESS = False

SCRIPT_DIR = Path(__file__).resolve().parent
WEBVOYAGER_DIR = SCRIPT_DIR / "webvoyager"
# Open-source layout: the dataset directory is a sibling of harness/ (PKG/data). The default is
# the 32-app x 10-request EvoWeb set, evoweb_benchmark.jsonl.
DEFAULT_TEST_DATA = SCRIPT_DIR.parent / "data" / "evoweb_benchmark.jsonl"
# Resolved at runtime in main() — defaults to the bundled evoweb_benchmark.jsonl but can be
# overridden via --jsonl-path.
TEST_DATA = DEFAULT_TEST_DATA

# An ACP agent needs the wire format, not just the URL: Anthropic-native for the Anthropic
# API, OpenAI-compatible for anything we front with LiteLLM.
ACP_APIS = {"Anthropic": "anthropic-messages"}
DEFAULT_ACP_BASE_URL = "https://api.anthropic.com"

APP_PORT_BASE = 5200  # generated app runs here


def _kill_port(port: int) -> None:
    """Kill all processes listening on *port* using /proc/net/tcp.

    Works without fuser/lsof (not installed in the worker image).
    Parses /proc/net/tcp to find the inode, then walks /proc/*/fd to
    find the owning PID(s) and sends SIGKILL.
    """
    hex_port = f"{port:04X}"
    target_inodes: set[str] = set()
    try:
        with open("/proc/net/tcp") as f:
            for line in f:
                parts = line.split()
                if len(parts) < 10:
                    continue
                local = parts[1]  # e.g. "00000000:1450"
                if local.endswith(f":{hex_port}"):
                    target_inodes.add(parts[9])
        if not target_inodes:
            return
        # Walk /proc/*/fd to find PIDs owning these inodes
        for pid_dir in Path("/proc").iterdir():
            if not pid_dir.name.isdigit():
                continue
            try:
                for fd in (pid_dir / "fd").iterdir():
                    try:
                        link = os.readlink(str(fd))
                    except OSError:
                        continue
                    for inode in target_inodes:
                        if f"socket:[{inode}]" in link:
                            os.kill(int(pid_dir.name), 9)
                            raise StopIteration
            except (PermissionError, StopIteration, ProcessLookupError):
                continue
    except Exception:
        pass


def log(msg: str) -> None:
    print(f"[run_single_sample] {msg}", file=sys.stderr, flush=True)


def log_pod_info() -> None:
    """Log pod resource limits + host info. Helps diagnose concurrency/resource issues.

    Reads cgroup v2 files (used by AL2023). Falls back silently if files are absent
    (e.g., running outside a container).
    """
    info: dict[str, object] = {
        "hostname": os.uname().nodename,
        "pid": os.getpid(),
        "cpu_count": os.cpu_count(),
    }
    for key, path in (
        ("cpu.max", "/sys/fs/cgroup/cpu.max"),
        ("memory.max", "/sys/fs/cgroup/memory.max"),
        ("memory.current", "/sys/fs/cgroup/memory.current"),
    ):
        try:
            with open(path) as f:
                info[key] = f.read().strip()
        except OSError:
            pass
    log(f"pod-info {info}")


class _TeeStream:
    """File-like wrapper that mirrors every write to two underlying streams.

    Used to fork ``sys.stderr`` so progress logs and drain-pipe output from
    npm install / vite / generation also land in a per-sample
    ``logs/worker.log``. That log gets uploaded to S3 in the finally block
    of main() so failure diagnostics (Python tracebacks, the
    ``[run_single_sample] FATAL: ...`` line, etc.) survive even when the
    pod exits non-zero. Without this the only place the traceback lives is
    the container's ephemeral stdout, which requires kubectl pod-log RBAC
    to read after the fact.

    Secondary-stream failures (disk full, file closed) silently degrade so
    the primary stderr keeps working.
    """

    def __init__(self, primary, secondary):
        self.primary = primary
        self.secondary = secondary

    def write(self, data):
        n = self.primary.write(data)
        try:
            self.secondary.write(data)
        except Exception:
            pass
        return n

    def flush(self):
        try:
            self.primary.flush()
        finally:
            try:
                self.secondary.flush()
            except Exception:
                pass

    def isatty(self):
        try:
            return self.primary.isatty()
        except Exception:
            return False


def _open_stage_log(output_dir: Path, stage: str) -> IO[str]:
    """Open a per-stage append-mode logfile under output_dir/logs/."""
    logs_dir = output_dir / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    return open(logs_dir / f"{stage}.log", "a", encoding="utf-8", buffering=1)


def _classify_request_failure(request_err):
    """-> (request_status, error_class, error_detail) for a failed request.

    Classifying here — with the exception in hand — is what makes a run auditable. Recovering the cause
    by grepping agent logs after the fact is unreliable: a degenerate repetition loop arrives wrapped in
    APIConnectionError, so it reads as infrastructure unless inspected carefully.
    """
    cls = classify_error(f"{request_err}")
    status = "context_exceeded" if cls == "context_exceeded" else "error"
    detail = " ".join(str(request_err).split())[:300]
    return status, cls, detail


# ---------------------------------------------------------------------------
# App startup + evaluation
# ---------------------------------------------------------------------------


def _run_with_drain(
    cmd: str, cwd: str, log_path: Path, prefix: str, env: dict | None = None
) -> int:
    """Run a shell command; tee combined stdout/stderr to `log_path` AND to
    our stderr (prefixed). Returns the exit code.

    Append-mode so repeated calls (e.g. npm install + --force retry) collect
    into one file.
    """
    log_path.parent.mkdir(parents=True, exist_ok=True)
    proc = subprocess.Popen(
        cmd,
        shell=True,
        cwd=cwd,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        bufsize=0,
    )
    # Inline tee: keep it simple, no thread needed because we wait below.
    with open(log_path, "ab") as f:
        for raw in iter(proc.stdout.readline, b""):
            f.write(raw)
            f.flush()
            try:
                text = raw.decode("utf-8", errors="replace").rstrip()
            except Exception:
                continue
            if text:
                print(f"[{prefix}] {text}", file=sys.stderr, flush=True)
    return proc.wait()


def _strip_cd_prefix(cmd: str) -> str:
    """Drop a leading `cd /home/project &&` from a shell/start command.

    /home/project is the in-browser WebContainer project root that models trained
    on StackBlitz-style prompts assume. It does not exist in the eval environment,
    and we already run every command with cwd=app_dir (the project root), so the
    prefix is both wrong and redundant: without stripping it the command dies with
    "cd: can't cd to /home/project" and the app never starts. Only this exact
    WebContainer-root prefix is removed; a legitimate relative `cd <subdir> && ...`
    is left untouched.
    """
    return re.sub(r"^\s*cd\s+/home/project/?\s*&&\s*", "", cmd)


def _force_vite_port(app_dir: str, port: int) -> None:
    """Pin vite's dev-server port to `port` in the app's vite config.

    Full-stack apps run vite via ``concurrently "node server.js" "vite"``, which
    swallows the ``-- --port`` flag we append, and they usually hardcode
    ``server.port: 5173`` in vite.config — so vite binds 5173, the eval polls
    `port`, finds nothing, and marks every task start_failed even though the app
    is fine. Pinning the port (+ strictPort/host) in the config survives both the
    concurrently wrapper and the hardcoded value. No-op for apps without a vite
    config (frontend-only apps take the ``--port`` flag directly).
    """
    inject = f"port: {port}, strictPort: true, host: true"
    for name in ("vite.config.js", "vite.config.ts", "vite.config.mjs", "vite.config.cjs"):
        cfg = Path(app_dir) / name
        if not cfg.is_file():
            continue
        text = cfg.read_text()
        if "strictPort: true, host: true" in text:
            return  # already pinned on a previous start — re-injecting duplicated the clause
        orig = text
        if re.search(r"\bport\s*:\s*\d+", text):
            # Pin the existing server.port (first port: is the dev port; proxies
            # use target URLs, not a bare `port:`).
            text = re.sub(r"\bport\s*:\s*\d+", inject, text, count=1)
        elif re.search(r"server\s*:\s*\{", text):
            text = re.sub(r"server\s*:\s*\{", "server: { " + inject + ",", text, count=1)
        elif re.search(r"defineConfig\s*\(\s*\{", text):
            text = re.sub(
                r"defineConfig\s*\(\s*\{",
                "defineConfig({ server: { " + inject + " },",
                text,
                count=1,
            )
        if text != orig:
            cfg.write_text(text)
            log(f"Pinned vite dev port -> {port} in {name}")
        return


RUNTIME_ERROR = re.compile(
    r"Uncaught (?:Error|TypeError|ReferenceError|RangeError)"
    r"|Maximum update depth exceeded|Too many re-renders"
    r"|Cannot read properties of|Cannot access '[^']+' before initialization"
)


def request_spend(request_dir: Path) -> dict:
    """This request's own agent spend, from the summary the generator wrote for it.

    Never raises: it is read while building the request record, outside the per-request try, so an
    evicted pod's half-written summary would otherwise discard every scored request in the sample.
    """
    path = request_dir / "generation" / "summary.json"
    try:
        return _read_spend(path)
    except (OSError, ValueError):
        return {"generation_usd": None, "cost_error": f"unreadable {path.name}"}


def _read_spend(path: Path) -> dict:
    if not path.is_file():
        return {
            "generation_usd": None,
            "model_calls": None,
            "input_tokens_total": None,
            "output_tokens": None,
        }
    summary = json.loads(path.read_text())
    return {
        "generation_usd": summary.get("cost_usd"),
        "model_calls": summary.get("model_calls"),
        "input_tokens_total": summary.get("input_tokens_total"),
        "output_tokens": summary.get("output_tokens"),
    }


def judge_cost(request_dir: Path) -> float | None:
    """What the judge spent on this request, summed over its per-check agent logs.

    WebVoyager prints its own running total ("Total cost: 0.4498") as the last such line of each
    check's agent.log, so the judge is priced by its own accounting rather than ours: its calls
    do not pass through the capture proxy.
    """
    logs = sorted((request_dir / "eval" / "results").glob("*/agent.log"))
    if not logs:
        return None
    total = 0.0
    priced = 0
    for log in logs:
        try:
            text = log.read_text(errors="replace")
        except OSError:
            continue
        # NOT anchored to line start: the judge writes through logging, so every line begins with
        # a timestamp. Anchoring here silently returned $0.00 for a whole wave. The number pattern,
        # not the anchor, is what stops "Total cost: 12.00." capturing the full stop.
        matches = re.findall(r"Total cost:\s*([0-9]+(?:\.[0-9]+)?)", text)
        if matches:
            priced += 1
            total += float(matches[-1])
    # A partial sum reported as a total makes an arm with judge trouble look cheaper, so say how
    # many of its checks were actually priced.
    if priced and priced < len(logs):
        log_warn = f"judge cost covers {priced} of {len(logs)} checks"
        print(f"[run_single_sample] WARNING: {log_warn}", flush=True)
    return round(total, 4) if priced else None


def runtime_errors(request_dir: Path) -> dict:
    """Uncaught JS the judge's own browser saw this request, read back off its console capture.

    `npm run build` structurally cannot see these. app000028 built clean ("built in 1.65s")
    while every route rendered blank, because a ReferenceError throws at runtime inside the
    context provider that wraps the app. Its last three requests scored 0/0/20 and all three
    still reported success, so a dead app was published as model quality. Flagged, never
    used to drop a request: dropping a model's worst outcomes is the censoring trap.
    """
    messages: dict[str, int] = {}
    affected = 0
    for path in sorted(request_dir.glob("eval/results/task*/console_errors.json")):
        try:
            entries = json.loads(path.read_text())
        except (OSError, ValueError):
            continue
        hits = {
            (entry.get("message") or "")[:200]
            for entry in entries
            if RUNTIME_ERROR.search(entry.get("message") or "")
        }
        if hits:
            affected += 1
            for hit in hits:
                messages[hit] = messages.get(hit, 0) + 1
    if not messages:
        return {}
    top = sorted(messages, key=lambda m: -messages[m])[:3]
    return {"checks_affected": affected, "errors": top}


def compile_check(app_dir: Path, output_dir: Path) -> dict:
    """`npm run build` once, recorded. This pipeline only ever ran `npm install` + `npm run
    dev`, and vite dev compiles per module on request, so a module that does not build
    surfaced only if the judge happened to open that page — and the console capture is a
    load-time snapshot, so nothing watched for it. A request is FLAGGED, never dropped:
    skipping never-built apps deletes a model's worst outcomes.
    """
    log = output_dir / "logs" / "build.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    try:
        proc = subprocess.run(
            ["npm", "run", "build"], cwd=str(app_dir), capture_output=True, text=True, timeout=600
        )
        out = (proc.stdout or "") + (proc.stderr or "")
        log.write_text(out)
        ok = proc.returncode == 0
    except (subprocess.TimeoutExpired, OSError) as error:
        log.write_text(f"{type(error).__name__}: {error}")
        return {"ok": False, "error": type(error).__name__}
    if not ok:
        log_tail = out.strip().splitlines()[-3:]
        log_msg = " | ".join(line.strip() for line in log_tail)
        log_fn = globals().get("log")
        if callable(log_fn):
            log_fn(f"WARNING: npm run build FAILED — the app ships anyway, flagged: {log_msg}")
    return {"ok": ok}


def _npm_install(app_dir: Path, shell_actions: list[str], output_dir: Path | None = None) -> None:
    """Run install shell actions in app_dir, teeing to logs/install.log.

    `npm run dev/start` is stripped so only install commands run; a failed
    `npm install` is retried with --force.
    """
    install_log = (output_dir / "logs" / "install.log") if output_dir else None
    # Ensure log directory exists up-front so the file shows up even on a
    # no-op (e.g. shell_actions is empty after the filter).
    if install_log is not None:
        install_log.parent.mkdir(parents=True, exist_ok=True)
        install_log.touch()

    for cmd in shell_actions:
        cmd = _strip_cd_prefix(cmd)
        # Strip npm run dev from install commands
        clean_cmd = " && ".join(
            p.strip()
            for p in cmd.split("&&")
            if p.strip() not in ("npm run dev", "npm run start", "npm start")
        )
        if not clean_cmd:
            continue
        log(f"Running: {clean_cmd}")
        if install_log is not None:
            rc = _run_with_drain(clean_cmd, str(app_dir), install_log, "npm-install")
        else:
            rc = subprocess.run(
                clean_cmd, shell=True, cwd=str(app_dir), capture_output=True, text=True
            ).returncode
        if rc != 0:
            # Try with --force
            force_cmd = clean_cmd.replace("npm install", "npm install --force")
            log(f"Retrying with --force: {force_cmd}")
            if install_log is not None:
                _run_with_drain(force_cmd, str(app_dir), install_log, "npm-install")
            else:
                subprocess.run(
                    force_cmd, shell=True, cwd=str(app_dir), capture_output=True, text=True
                )


def _drain_pipe_to_file(stream, prefix: str, log_path: Path) -> threading.Thread:
    """Background-drain a Popen stream, teeing to stderr (prefixed) AND a file.

    Tees to stderr (prefixed) and to a log file. Used for the generated app so
    we capture errors that fire AFTER the readiness poll
    succeeds (e.g. esbuild errors triggered when WebVoyager requests a
    broken module).
    """

    def _drain():
        try:
            with open(log_path, "ab") as f:
                for raw in iter(stream.readline, b""):
                    f.write(raw)
                    f.flush()
                    try:
                        text = raw.decode("utf-8", errors="replace").rstrip()
                    except Exception:
                        continue
                    if text:
                        print(f"[{prefix}] {text}", file=sys.stderr, flush=True)
        except Exception:
            pass

    t = threading.Thread(target=_drain, daemon=True, name=f"drain-{prefix}")
    t.start()
    return t


def start_app(
    app_dir: str, start_action: str, port: int, output_dir: Path | None = None
) -> subprocess.Popen:
    """Start the generated app on a specific port.

    If `output_dir` is given, the dev server's stdout/stderr is teed to
    `output_dir/logs/app_start.log` via a background thread that keeps
    running for the lifetime of the process. Vite/esbuild errors that fire
    after the initial readiness poll succeeds (e.g. when the browser
    requests a broken module) are still captured.
    """
    # Kill any stale process on the target port BEFORE starting.
    # Vite spawns child processes (esbuild) that survive SIGTERM on
    # the parent and hold the port; without this the new app silently
    # binds a different port.
    # Use pkill -9 to match any process with our port in its args,
    # plus the proc-based kill as backup.
    subprocess.run(
        ["pkill", "-9", "-f", f"port {port}"],
        capture_output=True,
    )
    _kill_port(port)
    time.sleep(2)

    env = os.environ.copy()
    env["PORT"] = str(port)

    # Pin vite's port in the config so full-stack apps (concurrently + hardcoded
    # server.port) still serve on the port the eval polls — see _force_vite_port.
    _force_vite_port(app_dir, port)

    # Try to inject the port into the start command
    cmd = _strip_cd_prefix(start_action)
    if "vite" in cmd.lower() or "dev" in cmd:
        cmd = f"{cmd} -- --port {port}"

    log(f"Starting generated app on port {port}: {cmd}")
    proc = subprocess.Popen(
        cmd,
        shell=True,
        cwd=app_dir,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        bufsize=0,
    )

    if output_dir is not None:
        app_log = output_dir / "logs" / "app_start.log"
        app_log.parent.mkdir(parents=True, exist_ok=True)
        _drain_pipe_to_file(proc.stdout, "app", app_log)

    # Wait for it to become ready
    import urllib.request

    for i in range(60):
        if proc.poll() is not None:
            log(f"App exited with code {proc.returncode}")
            return proc
        try:
            urllib.request.urlopen(f"http://localhost:{port}/", timeout=2)
            log(f"App ready on port {port} after {i + 1}s")
            return proc
        except Exception:
            pass
        time.sleep(1)

    log(f"Warning: app may not be ready on port {port}")
    return proc


def run_evaluation(
    index: int,
    app_port: int,
    eval_provider: str,
    eval_api_url: str,
    eval_api_key: str,
    eval_model: str,
    python_path: str,
    output_dir: Path,
    ui_instruct_override: list | None = None,
    record_video: bool = False,
) -> dict:
    """Run WebVoyager evaluation for one sample.

    ``ui_instruct_override`` (multi-request use): if provided, these tasks are
    evaluated instead of the sample's top-level ui_instruct. The per-request
    orchestrator passes request N's follow_ups[N-1].ui_instruct here so each
    request is graded against its own task list against its own running app.
    Default (None) preserves single-request behaviour exactly.

    record_video records the judge session (Xvfb+ffmpeg) to output_dir/videos/.
    Only the FIRST eval in the process records — one inspection video per pod
    is enough; per-request/per-retry videos would multiply S3 weight nobody watches.
    """
    # Load the test data to get UI tasks for this index
    with open(TEST_DATA, encoding="utf-8") as f:
        lines = f.readlines()
    sample = json.loads(lines[index - 1])  # 1-based index
    ui_tasks = ui_instruct_override if ui_instruct_override is not None else sample["ui_instruct"]

    # Create tasks file
    eval_dir = output_dir / "eval"
    eval_dir.mkdir(parents=True, exist_ok=True)
    results_dir = eval_dir / "results"
    results_dir.mkdir(exist_ok=True)

    ui_prompt_template = (
        "\nTask: {task}\n\n"
        "Expected Result: {expected_result}\n\n"
        "Instructions:\n"
        "- Attempt the task as a user would, using the UI elements available.\n"
        "- Make multiple attempts if needed to try and achieve the expected result.\n"
        "- Observe whether the expected result is fully, partially, or not at all achieved.\n"
        "- IMPORTANT: You can at most interact with the website 15 times. If the limit is reached, directly output your answer.\n\n"
        "At the end of your testing, answer only with one of the following:\n"
        "- YES: if the expected result was fully achieved.\n"
        "- NO: if the expected result could not be achieved at all.\n"
        "- PARTIAL: if only some aspects of the expected result were achieved.\n\n"
        "Grade strictly: if you are unsure between YES and PARTIAL, answer PARTIAL; if you are unsure "
        "between PARTIAL and NO, answer NO. Always prefer the harsher verdict.\n"
    )

    tasks = []
    app_name = f"{index:06d}"
    for ui_idx, ui_instruct in enumerate(ui_tasks):
        instruction = ui_prompt_template.format(
            task=ui_instruct["task"],
            expected_result=ui_instruct["expected_result"],
        )
        tasks.append(
            {
                "web_name": sample["id"],
                "id": f"{app_name}_{ui_idx}",
                "ques": instruction,
                "web": f"http://localhost:{app_port}/",
                "expected_result": ui_instruct["expected_result"],
                "task": ui_instruct["task"],
            }
        )

    tasks_file = eval_dir / "tasks.jsonl"
    with open(tasks_file, "w") as f:
        for t in tasks:
            f.write(json.dumps(t, ensure_ascii=False) + "\n")

    log(f"Created {len(tasks)} eval tasks for sample {index}")

    # Run WebVoyager
    cmd = [
        python_path,
        "-u",
        str(WEBVOYAGER_DIR / "run.py"),
        "--test_file",
        str(tasks_file),
        "--api_key",
        eval_api_key,
        "--api_base_url",
        eval_api_url,
        "--api_model",
        eval_model,
        "--api_provider",
        eval_provider,
        "--headless",
        "--max_iter",
        "20",
        "--max_attached_imgs",
        "3",
        "--temperature",
        "1",
        "--fix_box_color",
        "--seed",
        "42",
        "--output_dir",
        str(results_dir),
        "--download_dir",
        str(eval_dir / "downloads"),
        "--num_workers",
        "1",
        # Judge viewport: default 1024px clipped right-side nav items on grown apps (T10s
        # unreachable — the judge has no horizontal scroll). 1280 fits 10+ items.
        "--window_width",
        "1280",
    ]

    env = os.environ.copy()
    env["PYTHONPATH"] = str(WEBVOYAGER_DIR) + os.pathsep + env.get("PYTHONPATH", "")
    env["PYTHONUNBUFFERED"] = "1"

    # Headful Chrome on a private Xvfb display, ffmpeg recording the whole eval
    # (webvoyager/recording.py). None = tools missing, run headless unrecorded.
    global _RECORDED_THIS_PROCESS
    recording = None
    if record_video and not _RECORDED_THIS_PROCESS:
        recording = start_session_recording(output_dir, log=log)
        if recording:
            _RECORDED_THIS_PROCESS = True
    if recording:
        env["DISPLAY"] = recording.display
        cmd.remove("--headless")

    log("Running WebVoyager evaluation...")
    result = subprocess.run(cmd, env=env, capture_output=True, text=True)
    if result.stdout:
        print(result.stdout, file=sys.stderr, end="")
    if result.stderr:
        print(result.stderr, file=sys.stderr, end="")
    # Persist the WebVoyager output to S3-uploadable per-stage log so failures
    # and partial runs are debuggable without scraping K8s pod logs.
    with _open_stage_log(output_dir, "ui_eval") as f:
        if result.stdout:
            f.write(result.stdout)
        if result.stderr:
            f.write(result.stderr)
    # Finalize the mp4 before any raise so the evidence survives a dead judge.
    video = recording.finalize() if recording else None
    if result.returncode != 0:
        # A dead judge must error the sample, not be parsed into an all-NO 0%.
        raise RuntimeError(
            f"WebVoyager eval process exited {result.returncode} — refusing to score a dead judge"
        )

    # Parse results — pass through the same tasks list we evaluated so
    # parse_eval_results scores against request-specific ui_instruct when an
    # override was used.
    parse_sample = dict(sample)
    parse_sample["ui_instruct"] = ui_tasks
    eval_results = parse_eval_results(results_dir, parse_sample, index)
    if video:
        eval_results["videos"] = [str(video.relative_to(output_dir))]
    return eval_results


def _judge_infra_errors(task_dir: Path) -> dict:
    """Provider-error counts from one judge task's agent.log — {error_class: count}, infra only.

    A judge failure does not raise anywhere the harness can see it: the task simply has no
    interact_messages.json and scores `start_failed` (0). That is exactly how an OpenRouter judge
    credit outage once turned working apps into a page of false zeros. Recording what the judge's own
    log says at verdict-parse time makes those zeros distinguishable from real ones without any
    after-the-fact log forensics.
    """
    log_file = task_dir / "agent.log"
    if not log_file.exists():
        return {}
    try:
        hits = scan_log(log_file.read_text(errors="replace"))
    except OSError:
        return {}
    return {cls: info["count"] for cls, info in hits.items() if cls in INFRA_CLASSES}


def parse_eval_results(results_dir: Path, sample: dict, index: int) -> dict:
    """Parse WebVoyager results for one sample."""
    app_name = f"{index:06d}"
    yes_count = 0
    partial_count = 0
    no_count = 0
    task_results = []
    judge_rollup: dict = {}
    judge_tasks_touched = 0

    for ui_idx, ui_instruct in enumerate(sample["ui_instruct"]):
        task_id = f"task{app_name}_{ui_idx}"
        task_dir = results_dir / task_id
        msg_file = task_dir / "interact_messages.json"

        verdict = "start_failed"
        if msg_file.exists():
            try:
                with open(msg_file) as f:
                    messages = json.load(f)
                # Find last assistant message
                for msg in reversed(messages):
                    if msg["role"] == "assistant":
                        text = msg["content"]
                        verdict = parse_verdict(text)
                        if verdict == "yes":
                            yes_count += 1
                        elif verdict == "partial":
                            partial_count += 1
                        else:
                            no_count += 1
                        break
            except Exception:
                verdict = "error"

        judge_errors = _judge_infra_errors(task_dir)
        if judge_errors:
            judge_tasks_touched += 1
            for cls, n in judge_errors.items():
                judge_rollup[cls] = judge_rollup.get(cls, 0) + n

        task_results.append(
            {
                "task_idx": ui_idx,
                "task": ui_instruct["task"],
                "expected": ui_instruct["expected_result"],
                "verdict": verdict,
                # provider errors seen in THIS task's judge log. A recovered blip still delivers a
                # verdict; a task with errors AND verdict start_failed is a judge-infra false zero.
                **({"judge_errors": judge_errors} if judge_errors else {}),
            }
        )

    total = len(sample["ui_instruct"])
    score = yes_count + 0.5 * partial_count
    accuracy = score / total * 100 if total > 0 else 0

    return {
        "yes": yes_count,
        "partial": partial_count,
        "no": no_count,
        "total": total,
        "accuracy": round(accuracy, 1),
        "tasks": task_results,
        **(
            {"judge_errors": judge_rollup, "judge_error_tasks": judge_tasks_touched}
            if judge_rollup
            else {}
        ),
    }


# ---------------------------------------------------------------------------
# Appearance grading (VLM)
# ---------------------------------------------------------------------------


def run_appearance_grade(
    *,
    index: int,
    app_port: int,
    api_base_url: str,
    api_key: str,
    api_model: str,
    max_shots: int,
    viewport_height: int,
    pause: float,
    output_dir: Path,
) -> dict:
    """Capture scroll screenshots from the live app and VLM-grade them.

    Reuses the app already running on `app_port` (started in step 5 of main),
    so we skip the host-side capture+pm2 dance done in
    grade_appearance/eval_appearance.py and just call the screenshotter +
    grader directly.

    Returns a dict with `grade` (int 1-5), `model_output` (raw VLM text),
    or `error`. Also writes `appearance_result.json` under output_dir for
    the host-side aggregator to pick up.
    """
    # grade_appearance/ ships in the worker image; add to sys.path so its
    # internal `from prompt import appearance_prompt` style imports resolve.
    grade_dir = SCRIPT_DIR / "grade_appearance"
    if str(grade_dir) not in sys.path:
        sys.path.insert(0, str(grade_dir))
    from get_screenshots import capture_scroll_screenshots  # type: ignore[import-not-found]
    from vlm_eval import get_score_result  # type: ignore[import-not-found]

    with open(TEST_DATA, encoding="utf-8") as f:
        sample = json.loads([line for line in f][index - 1])  # 1-based
    instruction = sample["instruction"]

    shots_dir = output_dir / "appearance" / "shots"
    shots_dir.mkdir(parents=True, exist_ok=True)
    log_f = _open_stage_log(output_dir, "appearance_grade")
    try:
        log_f.write(f"[capture] url=http://localhost:{app_port}/ max_shots={max_shots}\n")
        capture_scroll_screenshots(
            url=f"http://localhost:{app_port}/",
            out_dir=str(shots_dir),
            max_shots=max_shots,
            pause=pause,
            viewport_height=viewport_height,
        )
        images = sorted(str(p) for p in shots_dir.glob("*.png"))
        if not images:
            log_f.write("[capture] no screenshots produced\n")
            return {"error": "no screenshots produced"}

        log_f.write(f"[grade] images={len(images)} model={api_model}\n")
        model_output = get_score_result(
            images,
            instruction,
            api_base_url=api_base_url,
            api_key=api_key,
            api_model=api_model,
        )
        # `Grade: <n>` extraction — same regex as compute_grade.py
        m = re.search(r"Grade.*?(\d)", model_output, flags=re.IGNORECASE | re.DOTALL)
        grade = int(m.group(1)) if m else 0

        appearance_result = {
            "grade": grade,
            "model": api_model,
            "model_output": model_output,
            "num_shots": len(images),
        }
        with open(output_dir / "appearance_result.json", "w", encoding="utf-8") as f:
            json.dump(appearance_result, f, indent=2, ensure_ascii=False)
        log_f.write(f"[grade] grade={grade}\n")
        return appearance_result
    finally:
        try:
            log_f.close()
        except Exception:
            pass


# ---------------------------------------------------------------------------
# API health check
# ---------------------------------------------------------------------------


def check_api_endpoint(api_url: str | None, api_key: str, provider: str) -> None:
    """Verify the LLM API endpoint is reachable before starting work."""
    import urllib.request

    if provider == "OpenAILike" and api_url:
        # Try multiple endpoints: /health, /v1/models, and a minimal chat completion
        health_url = api_url.rstrip("/").replace("/v1", "") + "/health"
        models_url = api_url.rstrip("/") + "/models"
        chat_url = api_url.rstrip("/") + "/chat/completions"

        for url in [health_url, models_url]:
            try:
                req = urllib.request.Request(url, headers={"Authorization": f"Bearer {api_key}"})
                urllib.request.urlopen(req, timeout=10)
                log(f"API endpoint reachable: {url}")
                return
            except Exception:
                continue

        # Fallback: try a minimal chat completion (works for LiteLLM and other proxies)
        try:
            req = urllib.request.Request(
                chat_url,
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                data=b'{"model":"test","messages":[{"role":"user","content":"hi"}],"max_tokens":1}',
            )
            urllib.request.urlopen(req, timeout=15)
            log(f"API endpoint reachable: {chat_url}")
            return
        except urllib.error.HTTPError as e:
            # 400/401/404 = server is reachable, just wrong model/auth
            if e.code in (400, 401, 404, 422):
                log(f"API endpoint reachable (HTTP {e.code}): {chat_url}")
                return
        except Exception:
            pass

        raise ConnectionError(
            f"Cannot reach API endpoint at {api_url}. Check the URL and ensure the server is running."
        )
    elif provider == "Anthropic":
        try:
            req = urllib.request.Request(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": api_key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                data=b'{"model":"claude-haiku-4-5-20251001","max_tokens":1,"messages":[{"role":"user","content":"hi"}]}',
            )
            urllib.request.urlopen(req, timeout=15)
            log("Anthropic API reachable")
        except urllib.error.HTTPError as e:
            if e.code in (400, 401, 403):
                raise ConnectionError(
                    f"Anthropic API auth failed (HTTP {e.code}). Check API_KEY."
                ) from e
            # 429, 500, etc. = API is reachable, just rate limited or busy
            log(f"Anthropic API reachable (HTTP {e.code})")
        except Exception as e:
            raise ConnectionError(f"Cannot reach Anthropic API: {e}") from e


# ---------------------------------------------------------------------------
# S3 upload
# ---------------------------------------------------------------------------

# No default bucket: uploads and checkpoint restore only happen when the user passes
# --s3-bucket / S3_BUCKET.
S3_BUCKET_DEFAULT = ""


def upload_to_s3(output_dir: Path, s3_bucket: str, run_id: str, index: int) -> str:
    """Upload output_dir contents to S3.

    S3 structure: s3://{bucket}/{run_id}/{index:06d}/
    """
    s3_path = f"s3://{s3_bucket}/{run_id}/{index:06d}/"
    log(f"Uploading to {s3_path}")
    cmd = ["aws", "s3", "sync", str(output_dir), s3_path, "--quiet"]
    subprocess.run(cmd, check=True)
    log("S3 upload complete")
    return s3_path


# ---------------------------------------------------------------------------
# Screenshots collection
# ---------------------------------------------------------------------------


def collect_screenshots(results_dir: Path, output_dir: Path) -> list[str]:
    """Copy first screenshot from each task to output for easy viewing."""
    screenshots = []
    screenshots_dir = output_dir / "screenshots"
    screenshots_dir.mkdir(exist_ok=True)

    for task_dir in sorted(results_dir.iterdir()):
        if not task_dir.is_dir():
            continue
        ss1 = task_dir / "screenshot1.png"
        if ss1.exists():
            dest = screenshots_dir / f"{task_dir.name}.png"
            shutil.copy2(ss1, dest)
            screenshots.append(str(dest))
    return screenshots


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main():
    parser = argparse.ArgumentParser(description="Run one WebGen-Bench sample end-to-end")
    parser.add_argument("--index", type=int, required=True, help="Sample index (1-based, 1-101)")
    parser.add_argument(
        "--api-url",
        type=str,
        default=None,
        help="API base URL (for OpenAILike: http://host:port/v1, for Anthropic: leave empty)",
    )
    parser.add_argument(
        "--api-key", type=str, default=None, help="API key (or set API_KEY env var)"
    )
    parser.add_argument(
        "--model", type=str, default="claude-sonnet-4-6", help="Model for generation"
    )
    parser.add_argument(
        "--provider",
        type=str,
        default="Anthropic",
        help="Wire format of the model endpoint: Anthropic (anthropic-messages) or anything "
        "else, e.g. OpenAILike / OpenRouter (openai-completions); also picks the judge's default",
    )
    parser.add_argument(
        "--eval-model", type=str, default=None, help="Model for eval (default: same as --model)"
    )
    parser.add_argument(
        "--record-video",
        action="store_true",
        default=os.environ.get("WEBGEN_RECORD_VIDEO") == "1",
        help="Record each WebVoyager eval session to videos/*.mp4 via Xvfb+ffmpeg "
        "(also settable via WEBGEN_RECORD_VIDEO=1)",
    )
    parser.add_argument(
        "--eval-provider",
        type=str,
        default=None,
        help="Eval API provider: openai or anthropic (default: inferred from --provider)",
    )
    parser.add_argument(
        "--eval-api-url", type=str, default=None, help="Eval API URL (default: same as --api-url)"
    )
    parser.add_argument(
        "--eval-api-key", type=str, default=None, help="Eval API key (default: same as --api-key)"
    )
    parser.add_argument(
        "--max-tokens",
        type=int,
        default=64000,
        help="Accepted for run_sample.sh compatibility; not read on the harness path, where "
        "sampling is pinned by AGENT_MAX_OUTPUT_TOKENS / HARNESS_SAMPLING_PIN.",
    )
    parser.add_argument(
        "--output-dir", type=str, default="/output", help="Where to write artifacts"
    )
    parser.add_argument(
        "--s3-bucket",
        type=str,
        default=None,
        help="Optional S3 bucket for uploading results + per-request checkpoints (default env S3_BUCKET; "
        "empty or 'none' = disabled, everything stays under --output-dir)",
    )
    parser.add_argument(
        "--run-id",
        type=str,
        default=None,
        help="Run ID for S3 folder structure (default: {model}_{timestamp})",
    )
    parser.add_argument(
        "--python-path", type=str, default=sys.executable, help="Python interpreter path"
    )
    parser.add_argument(
        "--generator",
        choices=sorted(HARNESSES),
        default="openhands",
        help="Coding-agent harness (default: openhands, the one the paper used).",
    )
    parser.add_argument(
        "--website-template",
        type=str,
        default=os.environ.get("WEBSITE_TEMPLATE", ""),
        help="Vite + React project a harness extends into the website, copied into the "
        "workspace before it starts (default: the scaffold bundled with the harnesses)",
    )
    # Appearance grading (uses the already-running generated app). Skipped when
    # --appearance-api-model is empty/unset.
    parser.add_argument(
        "--appearance-api-model",
        type=str,
        default=None,
        help="VLM model for screenshot grading (e.g. openai/gpt-4o). Empty = skip.",
    )
    parser.add_argument(
        "--appearance-api-url",
        type=str,
        default=None,
        help="Appearance API base URL (default: --eval-api-url)",
    )
    parser.add_argument(
        "--appearance-api-key",
        type=str,
        default=None,
        help="Appearance API key (default: --eval-api-key)",
    )
    parser.add_argument("--appearance-max-shots", type=int, default=1)
    parser.add_argument("--appearance-viewport-height", type=int, default=768)
    parser.add_argument("--appearance-pause", type=float, default=0.4)
    parser.add_argument(
        "--jsonl-path",
        type=str,
        default=None,
        help="Override the default dataset (data/evoweb_benchmark.jsonl beside harness/).",
    )
    parser.add_argument(
        "--skip-ui-eval",
        action="store_true",
        help="Skip the WebVoyager UI eval only — generation, npm install, build and "
        "start_app still run.",
    )
    args = parser.parse_args()

    # Honor --jsonl-path before anything reads TEST_DATA (validate_index,
    # generation, eval, appearance all look at the module global).
    global TEST_DATA
    if args.jsonl_path:
        override = Path(args.jsonl_path).resolve()
        if not override.is_file():
            print(f"Error: --jsonl-path {override} does not exist", file=sys.stderr)
            sys.exit(1)
        TEST_DATA = override
        log(f"Using JSONL: {TEST_DATA}")

    # Resolve defaults
    api_key = args.api_key or os.environ.get("API_KEY", "")
    if not api_key:
        print("Error: --api-key or API_KEY env var required", file=sys.stderr)
        sys.exit(1)

    eval_model = args.eval_model or args.model
    eval_api_key = args.eval_api_key or os.environ.get("EVAL_API_KEY") or api_key
    eval_api_url = args.eval_api_url or args.api_url or "https://api.anthropic.com"

    if args.eval_provider:
        eval_provider = args.eval_provider
    elif args.provider == "Anthropic":
        eval_provider = "anthropic"
    else:
        eval_provider = "openai"

    output_dir = Path(args.output_dir) / f"{args.index:06d}"
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "logs").mkdir(parents=True, exist_ok=True)

    # Validate index + load the sample row eagerly so we can detect multi-request
    # (follow_ups present) before kicking off the rest of the pipeline.
    with open(TEST_DATA, encoding="utf-8") as f:
        all_lines = f.readlines()
    total_samples = len(all_lines)
    if args.index < 1 or args.index > total_samples:
        print(f"Error: index must be 1-{total_samples}, got {args.index}", file=sys.stderr)
        sys.exit(1)
    sample_row = json.loads(all_lines[args.index - 1])
    follow_ups = sample_row.get("follow_ups") or []
    n_requests = 1 + len(follow_ups)
    if n_requests > 1:
        log(
            f"Multi-request sample detected: {n_requests} requests (1 initial + {len(follow_ups)} follow-ups)"
        )

    # S3 config ("none" disables upload)
    s3_bucket = args.s3_bucket or os.environ.get("S3_BUCKET") or S3_BUCKET_DEFAULT
    if s3_bucket.lower() == "none":
        s3_bucket = ""
    run_id = args.run_id or os.environ.get("RUN_ID") or f"{args.model}_{_utc_stamp()}"

    result = {"index": args.index, "status": "error"}
    # Kept in result.json for parity with the released traces: a harness ladder never resumes
    # from a pre-built base, so this is a constant.
    base_trajectory = {"source": "none", "messages": 0}
    appearance_api_model = (
        args.appearance_api_model or os.environ.get("APPEARANCE_API_MODEL", "")
    ).strip()
    appearance_api_url = (
        args.appearance_api_url or os.environ.get("APPEARANCE_API_URL", "") or eval_api_url
    ).strip()
    appearance_api_key = (
        args.appearance_api_key or os.environ.get("APPEARANCE_API_KEY", "") or eval_api_key
    )

    # Tee our stderr to logs/worker.log so progress + drain-pipe output
    # land on disk (and ultimately in S3, via the upload in finally). When
    # a pod crashes mid-run the resulting traceback is the only way to
    # diagnose without kubectl pods/log RBAC, which our CI runner lacks.
    (output_dir / "logs").mkdir(parents=True, exist_ok=True)
    worker_log_path = output_dir / "logs" / "worker.log"
    worker_log_f = open(worker_log_path, "a", encoding="utf-8")
    original_stderr = sys.stderr
    sys.stderr = _TeeStream(original_stderr, worker_log_f)

    try:
        # Log pod-level resource info up front so we can correlate failures
        # with concurrency / resource pressure across pods.
        log_pod_info()

        # 0. Health check: verify API endpoint is reachable
        log("Checking API endpoint...")
        check_api_endpoint(args.api_url, api_key, args.provider)

        result["base_trajectory"] = base_trajectory

        # 1-4+6. The ladder: generation and eval interleaved per request.
        result_requests = None  # set by the ladder loop

        if n_requests == 1:
            # A ladder needs at least two requests (the build plus one follow-up).
            raise RuntimeError(
                f"--generator {args.generator} needs a multi-request dataset; "
                f"this row has no follow_ups. Use a ladder taskset (data/ or tests/smoke_sets/)."
            )
        # Each request edits the same workspace AND carries the conversation forward via
        # history + session_file. A harness that cannot resume is refused in
        # backend.generate rather than run as N one-shot builds.
        ui_instruct_per_request = [sample_row["ui_instruct"]] + [
            fu.get("ui_instruct", []) for fu in follow_ups
        ]
        request_results: list[dict] = []
        request_history: list[dict] = []
        eval_results: dict | None = None
        app_info = None
        prev_request_passed = True
        prev_fail_reason = "previous_turn_did_not_complete"
        zip_path = None
        # Where the app under test lives across the whole ladder; checkpoint/restore
        # follows it.
        ws_root = output_dir.parent / "acp-workspaces"
        ws_dir = ws_root / f"sample_{args.index:06d}"

        # Resume from the last completed request if a checkpoint exists (a prior
        # pod attempt was evicted mid-ladder). Falls back to a fresh start on
        # any checkpoint failure, so this can never worsen a run.
        start_request = 1
        if s3_bucket:
            k = checkpoint.latest_checkpoint(s3_bucket, run_id, args.index)
            if k:
                got = checkpoint.restore_checkpoint(
                    s3_bucket, run_id, args.index, k, ws_dir, output_dir
                )
                if got:
                    (
                        _,
                        request_results,
                        prev_request_passed,
                        request_history,
                        prev_fail_reason,
                    ) = got
                    app_info = {"app_dir": str(ws_dir), "start_action": "npm run dev"}
                    start_request = k + 1
                    log(
                        f"RESUME: checkpoint at request {k} — continuing from request {start_request}"
                    )
                else:
                    log(f"Checkpoint at request {k} unreadable — starting fresh from request 1")

        for n in range(start_request, n_requests + 1):
            request_label = f"request {n}/{n_requests}"
            log(f"=== {request_label} ===")

            if n > 1 and not prev_request_passed:
                log(f"  {request_label} skipped: {prev_fail_reason.replace('_', ' ')}")
                request_results.append(
                    {
                        "turn": n,
                        "status": "skipped",
                        "skip_reason": prev_fail_reason,
                        "tasks": [],
                        "yes": 0,
                        "partial": 0,
                        "no": 0,
                        "total": 0,
                        "accuracy": 0,
                    }
                )
                continue

            instruction = sample_row["instruction"] if n == 1 else follow_ups[n - 2]["instruction"]
            request_dir = output_dir if n == 1 else (output_dir / f"turn{n}")
            request_dir.mkdir(parents=True, exist_ok=True)
            (request_dir / "logs").mkdir(parents=True, exist_ok=True)

            request_status = "success"
            request_build: dict | None = None
            request_runtime: dict = {}
            request_error_class = None
            request_error_detail = None
            request_eval: dict | None = None
            request_app_proc = None
            # A harness resumes through its own session/history, so every request after
            # the first is a resumed conversation. (The flag says we ASKED to resume;
            # history_lost below says whether it arrived.)
            request_resumed = n > 1
            try:
                # The harness edits the same workspace every request and carries the
                # conversation forward: `history` is the accumulated [user, assistant]
                # of the earlier requests and `session_file` lets an ACP agent resume its
                # own session instead of replaying. Without both, request N would open a
                # blank session and see only the files on disk, which is a sequence of
                # one-shot builds wearing a multi-request label.
                template = (
                    Path(args.website_template) if args.website_template else WEBSITE_TEMPLATE
                )
                app_info = generate(
                    harness=args.generator,
                    index=args.index,
                    instruction=instruction,
                    model=args.model,
                    api_key=api_key,
                    output_dir=request_dir,
                    workspaces=output_dir.parent / "acp-workspaces",
                    base_url=args.api_url or DEFAULT_ACP_BASE_URL,
                    api=ACP_APIS.get(args.provider, "openai-completions"),
                    template=template,
                    task_id=sample_row.get("id"),
                    history=list(request_history),
                    session_file=output_dir / "acp_session.txt",
                    # One step budget for every harness (AGENT_MAX_TURNS), so a harness
                    # comparison is not secretly a comparison of step budgets.
                    max_steps=int(os.environ.get("AGENT_MAX_TURNS") or DEFAULT_MAX_STEPS),
                )
                request_history.append({"role": "user", "content": instruction})
                request_history.append(
                    {"role": "assistant", "content": app_info.get("reply") or ""}
                )

                _npm_install(Path(app_info["app_dir"]), ["npm install"], request_dir)
                request_build = compile_check(Path(app_info["app_dir"]), request_dir)
                request_app_proc = start_app(
                    app_info["app_dir"],
                    app_info["start_action"],
                    APP_PORT_BASE,
                    request_dir,
                )
                if not args.skip_ui_eval:
                    request_eval = run_evaluation(
                        args.index,
                        APP_PORT_BASE,
                        eval_provider,
                        eval_api_url,
                        eval_api_key,
                        eval_model,
                        args.python_path,
                        request_dir,
                        ui_instruct_override=ui_instruct_per_request[n - 1],
                        record_video=args.record_video,
                    )
                else:
                    log(f"  --skip-ui-eval set: skipping WebVoyager UI eval for {request_label}")
            except Exception as request_err:
                log(f"  {request_label} failed: {request_err}")
                if request_status == "success":
                    # Classify WHY the request failed and record it, so infra-caused losses can be
                    # censored from metrics without after-the-fact log forensics.
                    request_status, request_error_class, request_error_detail = (
                        _classify_request_failure(request_err)
                    )
                    log(f"  {request_label} error_class={request_error_class}")
                log(traceback.format_exc())
            finally:
                if request_app_proc and request_app_proc.poll() is None:
                    request_app_proc.terminate()
                    try:
                        request_app_proc.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        request_app_proc.kill()
                subprocess.run(
                    "pm2 delete all 2>/dev/null",
                    shell=True,
                    capture_output=True,
                )
                _kill_port(APP_PORT_BASE)
                time.sleep(1)

            request_yes = (request_eval or {}).get("yes", 0)
            request_partial = (request_eval or {}).get("partial", 0)
            request_total = (request_eval or {}).get("total", 0)
            request_score = (
                (request_yes + 0.5 * request_partial) / request_total if request_total > 0 else 0
            )
            prev_request_passed, prev_fail_reason = ladder_continues(request_status, request_score)
            request_runtime = runtime_errors(request_dir)

            request_results.append(
                {
                    "turn": n,
                    "status": request_status,
                    # Did it compile? compile_check runs at the top of this block.
                    # Flagged, never used to drop a request.
                    **({"build": request_build} if request_build else {}),
                    # Built and served fine, rendered blank: the compile gate cannot see a runtime
                    # throw. Recorded on BOTH record sites — adding "build" to only one is how it
                    # silently never appeared in any result.json.
                    **({"runtime": request_runtime} if request_runtime else {}),
                    # WHY it failed — consumed by scoring.py to censor infra-caused losses
                    **({"error_class": request_error_class} if request_error_class else {}),
                    **({"error_detail": request_error_detail} if request_error_detail else {}),
                    "resumed_trajectory": request_resumed,
                    # resumed_trajectory only says we ASKED to resume. This says whether the
                    # conversation actually arrived: the harness discards the history before
                    # it knows the agent still has the session, so a lost one runs the request on
                    # the instruction alone and still reports success.
                    **({"history_lost": True} if (app_info or {}).get("history_lost") else {}),
                    "tasks": (request_eval or {}).get("tasks", []),
                    **(
                        {
                            "judge_errors": request_eval["judge_errors"],
                            "judge_error_tasks": request_eval.get("judge_error_tasks", 0),
                        }
                        if (request_eval or {}).get("judge_errors")
                        else {}
                    ),
                    "yes": request_yes,
                    "partial": (request_eval or {}).get("partial", 0),
                    "no": (request_eval or {}).get("no", 0),
                    "total": request_total,
                    "accuracy": (request_eval or {}).get("accuracy", 0),
                    # From THIS request's summary.json: app_info is loop-carried, so a failed
                    # request used to republish the previous request's spend.
                    "cost": {**request_spend(request_dir), "judge_usd": judge_cost(request_dir)},
                }
            )

            # Checkpoint this request so a future eviction resumes here instead
            # of restarting at request 1. Best-effort: never let it abort the run.
            if s3_bucket and ws_dir.exists():
                try:
                    checkpoint.save_checkpoint(
                        s3_bucket,
                        run_id,
                        args.index,
                        n,
                        ws_dir,
                        request_results,
                        prev_request_passed,
                        request_history,
                        prev_fail_reason,
                    )
                    log(f"  {request_label} checkpointed")
                except Exception as ckpt_err:
                    log(f"  {request_label} checkpoint failed (non-fatal): {ckpt_err}")

        scored_requests = [t for t in request_results if t.get("total", 0) > 0]
        if scored_requests:
            agg_yes = sum(t["yes"] for t in scored_requests)
            agg_partial = sum(t.get("partial", 0) for t in scored_requests)
            agg_no = sum(t.get("no", 0) for t in scored_requests)
            agg_total = sum(t["total"] for t in scored_requests)
            eval_results = {
                "yes": agg_yes,
                "partial": agg_partial,
                "no": agg_no,
                "total": agg_total,
                "accuracy": round((agg_yes + 0.5 * agg_partial) / agg_total * 100, 1)
                if agg_total
                else 0,
                "tasks": scored_requests[0].get("tasks", []),
            }
        result_requests = request_results

        # 6.5. Appearance grading (reuses the still-running app on APP_PORT_BASE).
        # Skipped silently when no model is configured so non-VLM eval models
        # don't break the pipeline. Also skipped for multi-request samples since
        # the per-request apps are already stopped by this point (re-starting
        # would double the per-request wall time for a feature most multi-request
        # runs don't request).
        appearance_grade_result = None
        if appearance_api_model and n_requests > 1:
            log("Skipping appearance grading on multi-request sample (apps already stopped)")
            appearance_api_model = ""  # disable the path below uniformly
        if appearance_api_model:
            try:
                appearance_grade_result = run_appearance_grade(
                    index=args.index,
                    app_port=APP_PORT_BASE,
                    api_base_url=appearance_api_url,
                    api_key=appearance_api_key,
                    api_model=appearance_api_model,
                    max_shots=args.appearance_max_shots,
                    viewport_height=args.appearance_viewport_height,
                    pause=args.appearance_pause,
                    output_dir=output_dir,
                )
            except Exception as e:
                log(f"Appearance grading failed (continuing): {e}")
                appearance_grade_result = {"error": str(e)}
        else:
            log("Skipping appearance grading (APPEARANCE_API_MODEL unset)")

        # 7. Collect screenshots (only if UI eval produced any)
        screenshots = []
        if eval_results is not None:
            eval_results_dir = output_dir / "eval" / "results"
            if not eval_results_dir.is_dir() and result_requests:
                for tr in reversed(result_requests):
                    request_n = tr.get("turn", 0)
                    cand = (
                        (output_dir / f"turn{request_n}" / "eval" / "results")
                        if request_n > 1
                        else eval_results_dir
                    )
                    if cand.is_dir():
                        eval_results_dir = cand
                        break
            if eval_results_dir.is_dir():
                screenshots = collect_screenshots(eval_results_dir, output_dir)

        # 8. Build final result
        result = {
            "index": args.index,
            "status": "success",
            "model": args.model,
            "generator": args.generator,
            "base_trajectory": base_trajectory,
            "artifacts": {
                "zip": str(zip_path) if zip_path else None,
                "run_json": None,
                "generator": args.generator,
                "screenshots": screenshots,
                "output_dir": str(output_dir),
            },
        }
        # A ladder that stopped early still reported status=success with an accuracy computed
        # over however many checks it managed (34-42 vs 49-52 for a complete one), so the
        # shortfall was invisible and the mean silently mixed complete and truncated ladders.
        # Name it: complete/truncated, where it stopped and why.
        if result_requests:
            done = [t for t in result_requests if t.get("status") == "success"]
            stop = next(
                (t for t in result_requests if t.get("status") not in ("success", "skipped")), None
            )
            result["ladder"] = {
                "turns_expected": len(result_requests),
                "turns_completed": len(done),
                "complete": len(done) == len(result_requests),
                **(
                    {"stopped_at_turn": stop.get("turn"), "stopped_because": stop.get("status")}
                    if stop
                    else {}
                ),
            }
        if eval_results is not None:
            result["eval_model"] = eval_model
            result["accuracy"] = eval_results["accuracy"]
            result["yes"] = eval_results["yes"]
            result["partial"] = eval_results["partial"]
            result["no"] = eval_results["no"]
            result["total"] = eval_results["total"]
            result["tasks"] = eval_results["tasks"]
            # session recording (one per run) — surface the mp4 path for the report
            if eval_results.get("videos"):
                result["videos"] = eval_results["videos"]
        if appearance_grade_result is not None:
            result["appearance"] = appearance_grade_result
        # Multi-request: attach the per-request array. Aggregator detects this and
        # produces the per-request breakdown; single-request samples never set it.
        # The key stays "turns" (and each entry's "turn") to match the released traces.
        if n_requests > 1:
            result["turns"] = result_requests

    except Exception as e:
        # Log the full traceback to our (teed) stderr so it lands in
        # logs/worker.log and ends up in S3 even when the pod crashes
        # before reaching the explicit upload below.
        log(f"FATAL: {e}")
        log(traceback.format_exc())
        result = {
            "index": args.index,
            "status": "error",
            "error": str(e),
            "traceback": traceback.format_exc(),
            "base_trajectory": base_trajectory,
        }
    finally:
        # Cleanup running subprocesses BEFORE writing result/uploading
        # so the drain threads have flushed everything to logs/*.log first.
        subprocess.run("pm2 delete all 2>/dev/null", shell=True, capture_output=True)

        # Flush our worker log so the S3 sync below picks up the final
        # FATAL/traceback lines we just emitted.
        try:
            worker_log_f.flush()
        except Exception:
            pass

        # Always persist result.json so failed runs leave a debuggable record
        # (the success path used to write this only after success — failures
        # produced no artifact at all).
        try:
            result_path = output_dir / "result.json"
            with open(result_path, "w") as f:
                json.dump(result, f, indent=2, ensure_ascii=False)
            log(f"Results written to {result_path}")
        except Exception as e:
            log(f"Failed to write result.json: {e}")

        # Always upload whatever we have (logs/, generation/, eval/, partial
        # extracts, etc.) so failures are diagnosable from S3 without scraping
        # K8s pod logs (which expire).
        if s3_bucket:
            try:
                s3_path = upload_to_s3(output_dir, s3_bucket, run_id, args.index)
                result["s3_path"] = s3_path
            except Exception as e:
                log(f"S3 upload failed: {e}")
                result["s3_error"] = str(e)

        # Restore original stderr and close the tee file last, AFTER the
        # last log() call above has fired.
        try:
            sys.stderr = original_stderr
            worker_log_f.close()
        except Exception:
            pass

    # Print JSON result to stdout (the primary output for K8s jobs)
    print(json.dumps(result, indent=2, ensure_ascii=False))
    sys.exit(0 if result.get("status") == "success" else 1)


if __name__ == "__main__":
    main()
