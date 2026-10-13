"""One package per harness. Adding a harness is a package plus a line in `MODULES`.

Each package exports `launch()` and declares:

    VERSION                the pinned version, installed exactly and reported per sample
    TOOLS, EDIT_TOOL       the tools it ships with, and how it edits a file
    DEFAULT_EXCLUDE        tools to turn off; an app build needs files plus bash, and
                           every extra tool is context the harness must ignore
    APPENDS_SYSTEM_PROMPT  whether it can take our build guidance as a system prompt
    SUPPORTS_RESUME        whether it can continue an earlier conversation
    SUPPORTS_MAX_STEPS     whether it can cap the turns it spends on one user request

Every `launch()` takes the same keyword arguments and returns `command` and `env`. A harness
that speaks ACP adds `acp` (its `session_meta` and whether it may end a turn with no closing
text); one that does not adds an `events` converter, and may add a `reply` when its stdout is
progress chatter. Optional `shipped_tools(prefix)` reports the tools actually installed, where
only that harness can know them.
"""

from __future__ import annotations

import os
import sys

from .bash import harness as bash
from .claude_code import harness as claude_code
from .mini_swe_agent import harness as mini_swe_agent
from .openhands import harness as openhands

MODULES = {
    "claude_code": claude_code,
    "openhands": openhands,
    "mini_swe_agent": mini_swe_agent,
    "bash": bash,
}


def build(harness: str, **kwargs) -> dict:
    """The harness's launch spec: command, env, transport, and per-transport extras.

    Keys only one transport needs are dropped for the other, so every harness module takes
    the same call.
    """
    if harness not in MODULES:
        raise ValueError(f"unknown harness {harness!r}; known: {sorted(MODULES)}")
    module = MODULES[harness]
    if kwargs.get("exclude_tools") is None:
        kwargs["exclude_tools"] = list(module.DEFAULT_EXCLUDE)
    # Refuse rather than drop it: a harness that ignores the appended prompt builds a
    # different app, and a summary claiming the prompt was applied would be a lie.
    if kwargs.get("system_prompt") and not module.APPENDS_SYSTEM_PROMPT:
        raise ValueError(
            f"{harness} cannot append a system prompt; pass system_prompt=None to run it on the task alone"
        )
    # A non-positive budget means four different things across the four arms: bash runs zero steps
    # and returns an empty reply, mini_swe_agent reads 0 as UNLIMITED, openhands exits, and the
    # turn-budget notice is silently dropped. An unbuilt app would then be scored, so refuse here
    # instead of letting each arm interpret it.
    if int(kwargs.get("max_steps") or 0) <= 0:
        raise ValueError(
            f"max_steps must be a positive turn budget, got {kwargs.get('max_steps')!r}"
        )
    # A turn budget this harness cannot honour must not be reported as if it had. Say so and
    # record it, rather than refusing to run or claiming a cap that is not there.
    capped = bool(module.SUPPORTS_MAX_STEPS and kwargs.get("max_steps"))
    if kwargs.get("max_steps") and not module.SUPPORTS_MAX_STEPS:
        print(
            f"[harnesses] WARNING {harness} runs UNCAPPED: it cannot honour max_steps",
            file=sys.stderr,
        )
    launch = module.launch(**kwargs)
    # The resolved list, so the caller reports what the run actually had rather than the
    # `None` that means "use this harness's default".
    launch["excluded"] = sorted(kwargs["exclude_tools"])
    launch["max_steps_enforced"] = capped
    launch["env"].setdefault("PATH", os.environ.get("PATH", ""))
    return launch
