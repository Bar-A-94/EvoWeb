# /// script
# requires-python = "==3.12.*"
# dependencies = ["openhands=={version}"]
# ///
"""Entry point for the OpenHands CLI, pinned by the generator.

Do not name this file after a package it imports: the script's own directory leads
sys.path, so openhands_cli.py would shadow the installed openhands_cli.

`openhands acp` parses --override-with-envs but never forwards it to the ACP server, and
that server treats "settings exist on disk" as being authenticated, so it rejects
session/new with "Authentication required". Seeding the store from the same env vars is
the supported way in: after this, its own loader finds a configured agent.
"""

import json
import os
from pathlib import Path

from openhands_cli.entrypoint import main
from openhands_cli.locations import AGENT_SETTINGS_PATH, get_persistence_dir
from openhands_cli.stores.agent_store import AgentStore


def _cap_iterations() -> None:
    """Cap the turns spent on one user request (LocalConversation.max_iteration_per_run).

    Patch __init__, not the factory: Conversation.__new__ forwards max_iteration_per_run
    explicitly, so a default-argument override is ignored on the fresh and resume paths.
    A cap hit emits no session update; the only trace is stderr.
    """
    limit = int(os.environ.get("OPENHANDS_MAX_STEPS") or 0)
    if limit <= 0:
        # Upstream's default is 500. Returning quietly would run this arm uncapped while the
        # others obey a budget.
        raise SystemExit(f"OPENHANDS_MAX_STEPS must be a positive turn budget, got {limit!r}")
    from openhands.sdk import LocalConversation

    original = LocalConversation.__init__

    def capped(self, *args, **kwargs):
        kwargs["max_iteration_per_run"] = limit
        return original(self, *args, **kwargs)

    LocalConversation.__init__ = capped


def _tolerate_missing_security_risk() -> None:
    """Treat a tool call without `security_risk` as risk UNKNOWN instead of a failed call.

    The ACP server attaches an LLMSecurityAnalyzer even with --always-approve (NeverConfirm), so
    the field is required but its value is never used. A call that omits it was rejected, and a
    first response of 3+ such calls tripped the stuck detector, ending the request after one model
    call with an empty reply (request 1 then scored 0 on the bare template; Qwen 3.5 397B and
    GPT-5.6 Luna, up to a third of apps). The tool schema always carries the field, so the
    prompt is unchanged; a call that does set it is handled as before.

    This is the upstream fix backported: openhands-sdk 1.22.0 made the field optional in exactly
    this way, but openhands 1.16.0 (the latest CLI) pins openhands-sdk==1.21.0, and taking 1.22.0
    would also bring ~1.8k lines of unrelated agent changes.
    """
    from openhands.sdk.agent.agent import Agent
    from openhands.sdk.security.risk import SecurityRisk

    original = Agent._extract_security_risk

    def tolerant(self, arguments, tool_name, read_only_tool, security_analyzer=None):
        if arguments.get("security_risk") is None:
            arguments.pop("security_risk", None)
            return SecurityRisk.UNKNOWN
        return original(self, arguments, tool_name, read_only_tool, security_analyzer)

    Agent._extract_security_risk = tolerant


def _sort_skill_discovery() -> None:
    """List public skills in path order on every filesystem.

    The SDK finds skills with Path.iterdir() / rglob() and does not sort, so the order of the
    skills block in the agent's system prompt follows the filesystem. The paper's pods (XFS
    nodes) returned the git checkout's path order; ext4 Docker hosts return hash order, giving
    the same skills in a different order. Sorting reproduces the paper's order everywhere.
    """
    from openhands.sdk.skills import skill as skill_mod

    for name in ("find_skill_md_directories", "find_regular_md_files"):
        original = getattr(skill_mod, name, None)
        if original is None:
            print(f"_sort_skill_discovery: openhands has no {name}; skill order unpinned")
            continue

        def sorted_version(*args, _original=original, **kwargs):
            return sorted(_original(*args, **kwargs), key=str)

        setattr(skill_mod, name, sorted_version)


def pin_sampling(spec: dict) -> None:
    """Force every model to sample identically, so a score gap is a model gap.

    openhands 1.16.0 decides extended thinking from EXTENDED_THINKING_MODELS, a hardcoded
    substring list holding only sonnet-4-5/4-6 and haiku-4-5. claude-opus-4-8 misses it, so
    `supports_extended_thinking` is False and chat_options skips the whole block: opus fell
    through to litellm's reasoning_effort path and went out as {"type": "adaptive"} at
    max_tokens 128000 with no interleaved-thinking header, while sonnet and haiku went out as
    {"enabled", 63999} at 64000. Measured over 1,800 recorded requests of the cap-15 and
    cap-20 study: zero exceptions, so every opus-vs-sonnet number there compared sampling
    configs, not models.

    max_output_tokens has to be pinned in the same breath. Left as None it is resolved per
    model from litellm's model info (128000 for opus, 64000 for sonnet) and the budget follows
    it through min(budget, max_output_tokens - 1), so registering the model alone would just
    move the divergence from the thinking type into the thinking budget.

    Anthropic routes only. Registering a non-Anthropic model would make openhands attach an
    Anthropic-shaped thinking block and the interleaved-thinking beta header to an
    OpenAI-compatible endpoint, which is a 400 rather than parity.
    """
    ceiling = os.environ.get("OPENHANDS_MAX_OUTPUT_TOKENS", "").strip()
    budget = os.environ.get("OPENHANDS_THINKING_BUDGET", "").strip()
    if not ceiling and not budget:
        return  # neither set: keep upstream's per-model defaults, whatever they are
    if not ceiling or not budget:
        raise SystemExit(
            "OPENHANDS_MAX_OUTPUT_TOKENS and OPENHANDS_THINKING_BUDGET must be set together "
            f"(got {ceiling!r} and {budget!r}); half a pin is the divergence this prevents"
        )
    if not (ceiling.isdigit() and budget.isdigit()):
        raise SystemExit(
            f"OPENHANDS_MAX_OUTPUT_TOKENS/OPENHANDS_THINKING_BUDGET must be integers, got {ceiling!r}/{budget!r}"
        )
    ceiling, budget = int(ceiling), int(budget)
    if budget <= 0 or ceiling <= 0 or budget >= ceiling:
        # chat_options silently clamps with min(budget, ceiling - 1), which would hand every
        # model a different budget again without ever saying so.
        raise SystemExit(
            f"need 0 < OPENHANDS_THINKING_BUDGET < OPENHANDS_MAX_OUTPUT_TOKENS, got {budget} < {ceiling}"
        )
    if os.environ.get("HARNESS_THINKING", "").lower() == "off":
        # The capture proxy deletes the thinking field on its way out. Pinning underneath it
        # would record a budget that never reached the wire.
        print("pin_sampling: HARNESS_THINKING=off, leaving sampling to the capture proxy")
        return
    model = os.environ["LLM_MODEL"]
    if not model.startswith("anthropic/"):
        # Non-Anthropic reasoning models via OpenRouter have no Anthropic thinking field;
        # their knob is reasoning_effort, which litellm forwards for these routes. Pin it
        # plus the output ceiling so each arm is a fixed policy like the others. Routes are
        # listed explicitly: OpenRouter's catalog says gpt-5*/glm-5*/deepseek-v4* support
        # reasoning_effort; qwen3.5-397b lists only reasoning on/off, but OpenRouter
        # normalizes effort into the reasoning block (canary-verified before the full run).
        REASONING_EFFORT_ROUTES = ("gpt-5", "glm-5", "deepseek-v4", "qwen3.5-397b")
        if any(tag in model for tag in REASONING_EFFORT_ROUTES):
            effort = os.environ.get("OPENHANDS_REASONING_EFFORT", "high")
            for llm_spec in (spec.get("llm"), (spec.get("condenser") or {}).get("llm")):
                if isinstance(llm_spec, dict):
                    llm_spec["max_output_tokens"] = ceiling
                    llm_spec["reasoning_effort"] = effort
            print(
                f"pin_sampling: {model} pinned to max_output_tokens={ceiling} "
                f"reasoning_effort={effort} (OpenRouter reasoning route)"
            )
            return
        print(f"pin_sampling: {model} is not an Anthropic route, leaving its sampling untouched")
        return
    # Prompt caching is ALWAYS wanted on Anthropic routes. The SDK gates cache_control on
    # PROMPT_CACHE_MODELS, another hardcoded registry like EXTENDED_THINKING_MODELS; a model
    # it never heard of (claude-fable-5 on openhands 1.16.0) silently pays the full input
    # rate on every history resend — measured 2026-08-25: fable's runs billed 119.9M
    # uncached input tokens per run ($1,199 vs ~$220 with opus-like caching, ~4x the arm's
    # true cost). Register the served model unconditionally, exactly like the thinking fix.
    from openhands.sdk.llm.utils import model_features

    cache_models = getattr(model_features, "PROMPT_CACHE_MODELS", None)
    if cache_models is None:
        print(
            "pin_sampling: WARNING — this openhands has no PROMPT_CACHE_MODELS registry; "
            "verify caching some other way"
        )
    elif not model_features.model_matches(model, cache_models):
        cache_models.append(model)
        print(f"pin_sampling: {model} registered for prompt caching")

    # The API itself refuses {"type": "enabled"} for the adaptive-only generation
    # (opus-4-8, opus-5, fable-5): 'thinking.type.enabled is not supported for this model.
    # Use thinking.type.adaptive and output_config.effort'. Forcing the budget on them
    # 400s every call (killed 64/64 ladders on 2026-08-20). For these models only the
    # output ceiling can be pinned; a numeric thinking budget has no API equivalent.
    ADAPTIVE_ONLY = ("opus-4-8", "opus-5", "fable")
    if any(tag in model for tag in ADAPTIVE_ONLY):
        # No numeric budget exists for these models; the API's only thinking knob is
        # output_config.effort, reached through the SDK's reasoning_effort field. Pinned to
        # "high" (2026-08-20: at "medium" opus thought ~27 tokens/call vs ~250 under its own
        # adaptive default, and fable ~0 — medium under-thinks these models).
        effort = os.environ.get("OPENHANDS_REASONING_EFFORT", "high")
        for llm_spec in (spec.get("llm"), (spec.get("condenser") or {}).get("llm")):
            if isinstance(llm_spec, dict):
                llm_spec["max_output_tokens"] = ceiling
                llm_spec["reasoning_effort"] = effort
        print(
            f"pin_sampling: {model} is adaptive-only thinking (API constraint); pinned "
            f"max_output_tokens={ceiling}, reasoning_effort={effort}"
        )
        return
    from openhands.sdk.llm.utils import model_features

    # get_features() is uncached and reads this module global per call, so appending in place
    # is enough; it must happen before the agent builds its first request.
    if not model_features.model_matches(model, model_features.EXTENDED_THINKING_MODELS):
        model_features.EXTENDED_THINKING_MODELS.append(model)
    for llm_spec in (spec.get("llm"), (spec.get("condenser") or {}).get("llm")):
        if isinstance(llm_spec, dict):
            llm_spec["max_output_tokens"] = ceiling
            llm_spec["extended_thinking_budget"] = budget
    print(f"pin_sampling: {model} pinned to max_output_tokens={ceiling} thinking budget={budget}")


if __name__ == "__main__":
    store = AgentStore()
    # Rewrite the settings on EVERY launch, not just the first. The store is on disk and
    # survives between user requests, while LLM_BASE_URL is a capture proxy on a fresh port for
    # each one - so a resumed session kept the first request's dead port and every model call
    # died with "[Errno 111] Connection refused", zero calls recorded. The endpoint has to
    # come from this launch, never from disk.
    store.create_and_save_from_settings(
        os.environ["LLM_API_KEY"],
        {"llm_model": os.environ["LLM_MODEL"], "llm_base_url": os.environ["LLM_BASE_URL"]},
    )
    # Tool exclusion goes through `filter_tools_regex`, NOT the stored `tools` list. Editing
    # that list looks like it works and does nothing: AgentStore._apply_runtime_config
    # re-resolves tools from the CLI defaults on every load, so a session opened with two tools
    # in the spec still came back with all four. The regex is applied later, against the
    # resolved list, and survives. Both are written here: the list edit is harmless and keeps
    # the spec honest about intent, the regex is what actually bites.
    excluded = set(json.loads(os.environ.get("OPENHANDS_EXCLUDE_TOOLS", "[]")))
    settings = Path(get_persistence_dir()) / AGENT_SETTINGS_PATH
    spec = json.loads(settings.read_text())
    if excluded:
        spec["tools"] = [tool for tool in spec["tools"] if tool["name"] not in excluded]
        spec["filter_tools_regex"] = f"^(?!{'|'.join(f'{name}$' for name in sorted(excluded))}).*"
    # litellm's default 300s HTTP timeout is too short for a thinking model on a large
    # late-ladder context: sonnet 4.6 deterministically exceeded it on 3/32 EvoWeb ladders
    # (same sample+turn on rerun), killing each ladder. 1200s stays bounded but clears the
    # observed worst case with margin. Applied to the condenser too — it sends the same
    # oversized history.
    timeout = int(
        os.environ.get("OPENHANDS_LLM_TIMEOUT") or os.environ.get("HARNESS_LLM_TIMEOUT") or 1200
    )
    for llm_spec in (spec.get("llm"), (spec.get("condenser") or {}).get("llm")):
        if isinstance(llm_spec, dict):
            llm_spec["timeout"] = timeout
    pin_sampling(spec)
    settings.write_text(json.dumps(spec))
    _cap_iterations()
    _sort_skill_discovery()
    _tolerate_missing_security_risk()
    main()
