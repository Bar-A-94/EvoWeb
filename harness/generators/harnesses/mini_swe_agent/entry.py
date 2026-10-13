# /// script
# requires-python = ">=3.11"
# dependencies = ["mini-swe-agent=={version}"]
# ///
"""mini-swe-agent, with the conversation carried across requests.

Upstream has no resume path: DefaultAgent.run() does `self.messages = []` and re-seeds
[system, instance] every call, so a follow-up request would rebuild the app from nothing and the
ladder would score a fresh build as a continuation.

The seam is that first seed. run() clears the list and immediately calls add_messages(system,
instance); intercepting that one call lets us restore the prior conversation and append only the
new user request, while every bit of upstream's loop and error handling runs untouched.
"""

import json
import os
from pathlib import Path

import typer
from minisweagent.agents.default import DefaultAgent
from minisweagent.config import get_config_from_spec
from minisweagent.environments import get_environment
from minisweagent.models import get_model
from minisweagent.utils.serialize import UNSET, recursive_merge

app = typer.Typer(add_completion=False, rich_markup_mode=None)

# mini-swe-agent also appends a terminal `exit` message, which is bookkeeping, not conversation:
# replaying it 400s before the first model call.
API_ROLES = {"system", "user", "assistant", "tool"}


def _calls_a_tool(message: dict) -> bool:
    content = message.get("content")
    return bool(message.get("tool_calls")) or (
        isinstance(content, list)
        and any(isinstance(b, dict) and b.get("type") == "tool_use" for b in content)
    )


def _replayable(messages: list[dict]) -> list[dict]:
    """Trim a saved conversation to a prefix a provider accepts.

    A run ends when submit is parsed, so the last tool call has no result and Anthropic rejects
    the dangling tool_use.
    """
    kept = [m for m in messages if m.get("role") in API_ROLES]
    while kept and kept[-1].get("role") == "assistant" and _calls_a_tool(kept[-1]):
        kept.pop()
    return kept


class ResumingAgent(DefaultAgent):
    """DefaultAgent that continues a previous request instead of starting from an empty list."""

    def __init__(self, *args, history_path: Path | None = None, **kwargs):
        super().__init__(*args, **kwargs)
        self._history_path = history_path
        self._prior: list[dict] = []
        if history_path and history_path.exists():
            try:
                self._prior = _replayable(json.loads(history_path.read_text()))
            except (OSError, ValueError):
                self._prior = []
        self._seeded = False

    def add_messages(self, *messages: dict) -> list[dict]:
        # The one call worth intercepting: run() has just emptied self.messages and is seeding
        # [system, instance]. The prior conversation already carries its own system message, so
        # restore it and keep only the new instance (user) request. Every later call passes through.
        if self._prior and not self._seeded:
            self._seeded = True
            self.messages = list(self._prior)
            messages = tuple(m for m in messages if m.get("role") != "system")
            # The prior request ends on an observation, which is role `user`, so the new task would
            # be a second user message in a row. Fold it into that observation rather than betting
            # on the provider tolerating consecutive same-role turns.
            if (
                self.messages
                and messages
                and self.messages[-1].get("role") == messages[0].get("role") == "user"
            ):
                merged = dict(self.messages[-1])
                merged["content"] = (
                    f"{merged.get('content', '')}\n\n{messages[0].get('content', '')}"
                )
                self.messages[-1] = merged
                messages = messages[1:]
        return super().add_messages(*messages)

    def run(self, task: str = "", **kwargs) -> dict:
        try:
            return super().run(task, **kwargs)
        finally:
            # Persist even when the request ends badly: the next request resuming from a partial
            # conversation beats it silently starting over.
            keep = _replayable(self.messages)
            # run() clears self.messages before re-seeding, so an early raise would otherwise
            # replace a good multi-request history with []. Write atomically: a pod killed mid-write
            # leaves truncated JSON that the loader reads as "no prior conversation".
            if self._history_path and len(keep) >= len(self._prior):
                self._history_path.parent.mkdir(parents=True, exist_ok=True)
                temp = self._history_path.with_suffix(".tmp")
                temp.write_text(json.dumps(keep))
                os.replace(temp, self._history_path)


@app.command(help="Run mini-swe-agent on one task, optionally continuing a prior conversation.")
def main(
    task: str = typer.Option(..., "-t", "--task"),
    model_name: str | None = typer.Option(None, "-m", "--model"),
    model_class: str | None = typer.Option(None, "--model-class"),
    environment_class: str | None = typer.Option(None, "--environment-class"),
    agent_class: str | None = typer.Option(None, "--agent-class"),
    config_spec: list[str] = typer.Option([], "-c", "--config"),  # noqa: B008 - typer wants the call in the default
    output: Path | None = typer.Option(None, "-o", "--output"),  # noqa: B008 - typer wants the call in the default
    history_file: Path | None = typer.Option(None, "--history-file"),  # noqa: B008 - typer wants the call in the default
    yolo: bool = typer.Option(False, "--yolo"),
    exit_immediately: bool = typer.Option(False, "--exit-immediately"),
    cost_limit: float | None = typer.Option(None, "--cost-limit"),
    step_limit: int | None = typer.Option(None, "--step-limit"),
) -> None:
    from minisweagent.agents.default import AgentConfig
    from minisweagent.config import builtin_config_dir

    specs = config_spec or [str(builtin_config_dir / "mini.yaml")]
    configs = [get_config_from_spec(s) for s in specs]
    # UNSET, not None: recursive_merge strips UNSET, while None would overwrite a real default.
    configs.append(
        {
            "agent": {
                "cost_limit": cost_limit if cost_limit is not None else UNSET,
                # AgentConfig.step_limit; 0 upstream means unlimited.
                "step_limit": step_limit if step_limit is not None else UNSET,
                "output_path": str(output) if output else UNSET,
            },
            # litellm's default HTTP timeout is 300s, which truncates a thinking model on a
            # large context (the same reason openhands/entry.py pins its own). One shared knob
            # keeps every harness on the same per-call deadline.
            "model": {
                "model_class": model_class or UNSET,
                "model_name": model_name or UNSET,
                "model_kwargs": {
                    "timeout": int(os.environ.get("HARNESS_LLM_TIMEOUT") or 1200),
                    # litellm.responses() (model_class litellm_response) does not read
                    # OPENAI_API_BASE the way completion() does, so the capture-proxy base
                    # has to travel as an explicit kwarg or the run bypasses recording.
                    **(
                        {"api_base": os.environ["OPENAI_API_BASE"]}
                        if os.environ.get("OPENAI_API_BASE")
                        else {}
                    ),
                },
            },
            "environment": {"environment_class": environment_class or UNSET},
        }
    )
    config = recursive_merge(*configs)
    # Keep only what AgentConfig declares: the upstream CLI also injects `mode` and
    # `confirm_exit`, which belong to the interactive agent and would raise here.
    allowed = set(AgentConfig.model_fields)
    agent_cfg = {k: v for k, v in (config.get("agent") or {}).items() if k in allowed}
    agent = ResumingAgent(
        get_model(config=config.get("model", {})),
        get_environment(config.get("environment", {}), default_type="local"),
        history_path=history_file,
        **agent_cfg,
    )
    agent.run(task)


if __name__ == "__main__":
    app()
