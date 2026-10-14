"""WEBGEN_NAV_GUIDANCE reproduces the build guidance of the paper's runs byte for byte.

"on"  = image multi_turn-6601fa42 (the paper's Anthropic runs, except Fable r3)
"off" = every later image (Fable r3, GPT-5.6, GLM, Kimi, DeepSeek, Qwen)
The fixture holds the texts extracted from that commit.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
from generators import backend

FIXTURE = json.loads((Path(__file__).with_name("fixtures_6601fa42.json")).read_text())


def test_on_is_the_anthropic_image_prompt(monkeypatch):
    monkeypatch.setenv("WEBGEN_NAV_GUIDANCE", "on")
    assert backend.app_system_prompt() == FIXTURE["APP_SYSTEM_PROMPT"]


def test_default_is_on(monkeypatch):
    monkeypatch.delenv("WEBGEN_NAV_GUIDANCE", raising=False)
    assert backend.app_system_prompt() == FIXTURE["APP_SYSTEM_PROMPT"]


def test_off_drops_the_nav_sentence(monkeypatch):
    monkeypatch.setenv("WEBGEN_NAV_GUIDANCE", "off")
    text = backend.app_system_prompt()
    assert "<Link>" not in text
    assert text == backend.APP_SYSTEM_PROMPT


def test_bad_value_is_refused(monkeypatch):
    monkeypatch.setenv("WEBGEN_NAV_GUIDANCE", "yes")
    with pytest.raises(ValueError):
        backend.app_system_prompt()


@pytest.mark.parametrize("mode", ["on", "off"])
def test_template_comment(monkeypatch, tmp_path, mode):
    monkeypatch.setenv("WEBGEN_NAV_GUIDANCE", mode)
    ws = tmp_path / "ws"
    shutil.copytree(backend.TEMPLATE, ws)
    backend.apply_template_nav_comment(ws)
    app = (ws / "src" / "App.jsx").read_text()
    if mode == "on":
        assert app == FIXTURE["template_App.jsx"]
    else:
        assert app == (backend.TEMPLATE / "src" / "App.jsx").read_text()
        assert "<Link> in the nav" not in app
