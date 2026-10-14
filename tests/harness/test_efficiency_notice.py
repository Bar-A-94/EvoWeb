"""The efficiency nudge replaces the explicit turn-budget notice: no cap number in prompts."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "harness"))

from generators.backend import APP_SYSTEM_PROMPT, EFFICIENCY_NOTICE, with_turn_budget  # noqa: E402


def test_the_nudge_is_appended_when_a_cap_is_enforced():
    out = with_turn_budget(APP_SYSTEM_PROMPT, 15)
    assert out.startswith(APP_SYSTEM_PROMPT)
    assert EFFICIENCY_NOTICE in out


def test_the_prompt_never_names_the_cap():
    """Behavior must not anchor to a specific number, so cap experiments stay comparable."""
    for cap in (15, 20, 30):
        out = with_turn_budget(APP_SYSTEM_PROMPT, cap)
        assert str(cap) not in out.replace(APP_SYSTEM_PROMPT, "")
    assert "agentic turns" not in with_turn_budget(APP_SYSTEM_PROMPT, 20)


def test_no_system_prompt_still_gets_the_nudge():
    assert with_turn_budget(None, 15) == EFFICIENCY_NOTICE


def test_an_unenforced_budget_adds_no_nudge():
    assert with_turn_budget(APP_SYSTEM_PROMPT, 0) == APP_SYSTEM_PROMPT
    assert with_turn_budget(None, 0) is None


def test_the_nudge_can_be_disabled_by_env(monkeypatch):
    monkeypatch.setenv("WEBGEN_EFFICIENCY_NUDGE", "off")
    assert with_turn_budget(APP_SYSTEM_PROMPT, 15) == APP_SYSTEM_PROMPT
    monkeypatch.setenv("WEBGEN_EFFICIENCY_NUDGE", "on")
    assert EFFICIENCY_NOTICE in with_turn_budget(APP_SYSTEM_PROMPT, 15)
