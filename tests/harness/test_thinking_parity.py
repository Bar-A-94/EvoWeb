"""Every model must sample identically, or a model comparison is a sampling comparison.

openhands 1.16.0 decides extended thinking from EXTENDED_THINKING_MODELS, a hardcoded
substring list holding only sonnet-4-5/4-6 and haiku-4-5. claude-opus-4-8 misses it, so
opus took litellm's reasoning_effort path instead and went out as {"type": "adaptive"} at
max_tokens 128000, while sonnet and haiku went out as {"enabled", 63999} at 64000 — over
1,800 recorded requests, zero exceptions. These tests pin the fix and its two guards.
"""

from __future__ import annotations

import importlib.util
import re
import sys
import types
from pathlib import Path

import pytest

HARNESS = Path(__file__).resolve().parents[2] / "harness"
ENTRY = HARNESS / "generators" / "harnesses" / "openhands" / "entry.py"


def load_entry(monkeypatch, models: list[str]):
    """Import entry.py with the openhands packages stubbed, plus a fake feature registry."""
    features = types.ModuleType("openhands.sdk.llm.utils.model_features")
    features.EXTENDED_THINKING_MODELS = list(models)
    features.PROMPT_CACHE_MODELS = list(models)
    features.model_matches = lambda model, patterns: any(
        p.lower() in (model or "").lower() for p in patterns
    )
    for name, mod in {
        "openhands": types.ModuleType("openhands"),
        "openhands.sdk": types.ModuleType("openhands.sdk"),
        "openhands.sdk.llm": types.ModuleType("openhands.sdk.llm"),
        "openhands.sdk.llm.utils": types.ModuleType("openhands.sdk.llm.utils"),
        "openhands.sdk.llm.utils.model_features": features,
        "openhands_cli": types.ModuleType("openhands_cli"),
        "openhands_cli.entrypoint": types.ModuleType("openhands_cli.entrypoint"),
        "openhands_cli.locations": types.ModuleType("openhands_cli.locations"),
        "openhands_cli.stores": types.ModuleType("openhands_cli.stores"),
        "openhands_cli.stores.agent_store": types.ModuleType("openhands_cli.stores.agent_store"),
    }.items():
        monkeypatch.setitem(sys.modules, name, mod)
    sys.modules["openhands.sdk.llm.utils"].model_features = features
    sys.modules["openhands_cli.entrypoint"].main = lambda: None
    sys.modules["openhands_cli.locations"].AGENT_SETTINGS_PATH = "agent_settings.json"
    sys.modules["openhands_cli.locations"].get_persistence_dir = lambda: "/tmp"
    sys.modules["openhands_cli.stores.agent_store"].AgentStore = object

    spec = importlib.util.spec_from_file_location("_entry_under_test", ENTRY)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module, features


def spec_with_condenser() -> dict:
    return {"llm": {"timeout": 1200}, "condenser": {"llm": {"timeout": 1200}}}


@pytest.fixture
def pinned(monkeypatch):
    monkeypatch.setenv("OPENHANDS_MAX_OUTPUT_TOKENS", "64000")
    monkeypatch.setenv("OPENHANDS_THINKING_BUDGET", "63999")
    monkeypatch.delenv("HARNESS_THINKING", raising=False)


def test_a_model_the_registry_never_heard_of_still_gets_the_pinned_budget(monkeypatch, pinned):
    """An unregistered model that SUPPORTS enabled-thinking gets registered and budgeted."""
    monkeypatch.setenv("LLM_MODEL", "anthropic/claude-sonnet-4-2")
    entry, features = load_entry(monkeypatch, ["claude-sonnet-4-6", "claude-haiku-4-5"])
    settings = spec_with_condenser()
    entry.pin_sampling(settings)
    assert features.model_matches("anthropic/claude-sonnet-4-2", features.EXTENDED_THINKING_MODELS)
    for llm in (settings["llm"], settings["condenser"]["llm"]):
        assert llm["max_output_tokens"] == 64000
        assert llm["extended_thinking_budget"] == 63999


def test_an_adaptive_only_model_is_never_forced_into_an_enabled_budget(monkeypatch, pinned):
    """The API rejects thinking.type=enabled for opus-4-8/opus-5/fable ('use adaptive and
    output_config.effort') — forcing the budget 400s every call and killed 64/64 ladders on
    2026-08-20. These models get the output ceiling only."""
    for model in ("anthropic/claude-opus-4-8", "anthropic/claude-fable-5"):
        monkeypatch.setenv("LLM_MODEL", model)
        entry, features = load_entry(monkeypatch, ["claude-sonnet-4-6", "claude-haiku-4-5"])
        settings = spec_with_condenser()
        entry.pin_sampling(settings)
        assert not features.model_matches(model, features.EXTENDED_THINKING_MODELS)
        for llm in (settings["llm"], settings["condenser"]["llm"]):
            assert llm["max_output_tokens"] == 64000
            assert "extended_thinking_budget" not in llm
            assert llm["reasoning_effort"] == "high"


def test_every_anthropic_route_is_registered_for_prompt_caching(monkeypatch, pinned):
    """claude-fable-5 on openhands 1.16.0 missed PROMPT_CACHE_MODELS and paid the full
    input rate on 119.9M history tokens per run (2026-08-25 audit) — caching is always
    wanted, for adaptive-only and enabled-thinking models alike."""
    for model in ("anthropic/claude-fable-5", "anthropic/claude-sonnet-4-2"):
        monkeypatch.setenv("LLM_MODEL", model)
        entry, features = load_entry(monkeypatch, ["claude-sonnet-4-6", "claude-haiku-4-5"])
        entry.pin_sampling(spec_with_condenser())
        assert features.model_matches(model, features.PROMPT_CACHE_MODELS)


def test_a_cache_registered_model_is_not_added_twice(monkeypatch, pinned):
    monkeypatch.setenv("LLM_MODEL", "anthropic/claude-sonnet-4-6")
    entry, features = load_entry(monkeypatch, ["claude-sonnet-4-6"])
    entry.pin_sampling(spec_with_condenser())
    assert features.PROMPT_CACHE_MODELS == ["claude-sonnet-4-6"]


def test_a_model_already_in_the_registry_is_pinned_without_being_added_twice(monkeypatch, pinned):
    monkeypatch.setenv("LLM_MODEL", "anthropic/claude-sonnet-4-6")
    entry, features = load_entry(monkeypatch, ["claude-sonnet-4-6", "claude-haiku-4-5"])
    settings = spec_with_condenser()
    entry.pin_sampling(settings)
    assert features.EXTENDED_THINKING_MODELS == ["claude-sonnet-4-6", "claude-haiku-4-5"]
    assert settings["llm"]["extended_thinking_budget"] == 63999


def test_a_non_anthropic_route_is_left_alone(monkeypatch, pinned):
    """An Anthropic-shaped thinking block on an OpenAI-compatible route is a 400, not parity.

    glm-5.2 used to be the example here; it moved into REASONING_EFFORT_ROUTES on 2026-08-24,
    so the untouched example is now a non-reasoning route.
    """
    monkeypatch.setenv("LLM_MODEL", "openai/gpt-4o")
    entry, features = load_entry(monkeypatch, ["claude-sonnet-4-6"])
    settings = spec_with_condenser()
    entry.pin_sampling(settings)
    assert features.EXTENDED_THINKING_MODELS == ["claude-sonnet-4-6"]
    assert settings["llm"] == {"timeout": 1200}


def test_the_proxy_wins_when_it_is_stripping_thinking(monkeypatch, pinned):
    """Pinning a budget the capture proxy then deletes would report a setting we never sent."""
    monkeypatch.setenv("LLM_MODEL", "anthropic/claude-opus-4-8")
    monkeypatch.setenv("HARNESS_THINKING", "off")
    entry, features = load_entry(monkeypatch, ["claude-sonnet-4-6"])
    settings = spec_with_condenser()
    entry.pin_sampling(settings)
    assert features.EXTENDED_THINKING_MODELS == ["claude-sonnet-4-6"]
    assert settings["llm"] == {"timeout": 1200}


@pytest.mark.parametrize(
    "ceiling,budget",
    [("64000", "64000"), ("64000", "70000"), ("64000", ""), ("", "63999"), ("64000", "0")],
)
def test_a_half_set_or_impossible_pin_aborts_instead_of_running_an_odd_arm(
    monkeypatch, ceiling, budget
):
    monkeypatch.setenv("LLM_MODEL", "anthropic/claude-opus-4-8")
    monkeypatch.setenv("OPENHANDS_MAX_OUTPUT_TOKENS", ceiling)
    monkeypatch.setenv("OPENHANDS_THINKING_BUDGET", budget)
    monkeypatch.delenv("HARNESS_THINKING", raising=False)
    entry, _ = load_entry(monkeypatch, ["claude-sonnet-4-6"])
    with pytest.raises(SystemExit):
        entry.pin_sampling(spec_with_condenser())


def test_the_launcher_pins_the_paper_sampling_policy():
    """run_sample.sh must export the paper's pin (64000 ceiling / 16000 budget) and the proxy pin
    must carry the same two numbers, or a local re-run samples differently from the released runs.

    (The internal repo compared the GitHub workflow with the k8s launcher; neither is shipped.)
    """
    launcher = (HARNESS / "run_sample.sh").read_text()
    ceiling = re.search(
        r"OPENHANDS_MAX_OUTPUT_TOKENS:-\$\{AGENT_MAX_OUTPUT_TOKENS:-(\d+)\}", launcher
    )
    budget = re.search(r"OPENHANDS_THINKING_BUDGET:-\$\{AGENT_THINKING_BUDGET:-(\d+)\}", launcher)
    assert ceiling and budget, "sampling-pin defaults not found in run_sample.sh"
    assert (ceiling.group(1), budget.group(1)) == ("64000", "16000")
    proxy = re.search(r'HARNESS_SAMPLING_PIN="\$\{HARNESS_SAMPLING_PIN-(\d+):(\d+)\}"', launcher)
    assert proxy and proxy.groups() == ("64000", "16000"), (
        "proxy pin default disagrees with the openhands pin"
    )


def test_the_pin_is_actually_wired_into_the_launch_path():
    """Guards the call site: every test above would still pass if __main__ stopped calling it."""
    source = ENTRY.read_text()
    body = source.split('if __name__ == "__main__":', 1)[1]
    assert "pin_sampling(spec)" in body, "entry.py defines pin_sampling but never calls it"
    assert body.index("pin_sampling(spec)") < body.index("settings.write_text"), (
        "pin_sampling must mutate the spec before it is written to disk"
    )


@pytest.mark.parametrize("ceiling,budget", [("64k", "63999"), ("64000", "63_999"), ("-1", "10")])
def test_a_non_integer_pin_aborts_cleanly(monkeypatch, ceiling, budget):
    monkeypatch.setenv("LLM_MODEL", "anthropic/claude-opus-4-8")
    monkeypatch.setenv("OPENHANDS_MAX_OUTPUT_TOKENS", ceiling)
    monkeypatch.setenv("OPENHANDS_THINKING_BUDGET", budget)
    monkeypatch.delenv("HARNESS_THINKING", raising=False)
    entry, _ = load_entry(monkeypatch, ["claude-sonnet-4-6"])
    with pytest.raises(SystemExit):
        entry.pin_sampling(spec_with_condenser())


@pytest.mark.parametrize(
    "model",
    [
        "openrouter/openai/gpt-5.6-luna",
        "openrouter/z-ai/glm-5.2",
        "openrouter/deepseek/deepseek-v4-flash",
        "openrouter/qwen/qwen3.5-397b-a17b",
    ],
)
def test_an_openrouter_reasoning_route_gets_effort_and_ceiling_but_no_thinking_budget(
    monkeypatch, pinned, model
):
    """Non-Anthropic reasoning models have no Anthropic thinking field; their pinned policy
    is reasoning_effort + the output ceiling, nothing else."""
    monkeypatch.setenv("LLM_MODEL", model)
    monkeypatch.setenv("OPENHANDS_REASONING_EFFORT", "low")
    entry, features = load_entry(monkeypatch, ["claude-sonnet-4-6"])
    settings = spec_with_condenser()
    entry.pin_sampling(settings)
    assert features.EXTENDED_THINKING_MODELS == ["claude-sonnet-4-6"]
    for llm in (settings["llm"], settings["condenser"]["llm"]):
        assert llm["max_output_tokens"] == 64000
        assert llm["reasoning_effort"] == "low"
        assert "extended_thinking_budget" not in llm
