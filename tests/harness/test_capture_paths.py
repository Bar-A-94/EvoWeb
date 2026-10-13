"""The proxy's path normalization must fit every provider base we actually use.

Blindly prepending /v1 to bare client paths made api.z.ai/api/paas/v4 unreachable
(/v4/v1/chat/completions is a 404), while removing it entirely would break
api.anthropic.com (clients that treat the base as carrying /v1 post bare paths).
"""

import importlib.util
import re
import sys
from pathlib import Path

CAPTURE = Path(__file__).resolve().parents[2] / "harness" / "generators" / "capture.py"


def _load():
    spec = importlib.util.spec_from_file_location("_capture_under_test", CAPTURE)
    module = importlib.util.module_from_spec(spec)
    sys.modules["_capture_under_test"] = module
    spec.loader.exec_module(module)
    return module


capture = _load()


def test_anthropic_style_base_gets_v1_prepended_on_bare_paths():
    assert capture.normalize_path("https://api.anthropic.com", "/messages") == "/v1/messages"


def test_a_path_already_carrying_v1_is_left_alone():
    assert capture.normalize_path("https://api.anthropic.com", "/v1/messages") == "/v1/messages"


def test_openrouter_base_gets_v1_prepended():
    assert (
        capture.normalize_path("https://openrouter.ai/api", "/chat/completions")
        == "/v1/chat/completions"
    )


def test_a_self_versioned_base_receives_the_bare_path_verbatim():
    """z.ai's base already ends in /v4; /v4/v1/... is a 404 (verified live 2026-08-25)."""
    assert (
        capture.normalize_path("https://api.z.ai/api/paas/v4", "/chat/completions")
        == "/chat/completions"
    )


def test_a_self_versioned_base_does_not_strip_an_explicit_v1_path():
    assert capture.normalize_path("https://api.z.ai/api/paas/v4", "/v1/models") == "/v1/models"


def test_the_proxy_deadline_is_above_the_client_deadline():
    """The proxy must not be the first component to give up.

    At FORWARD_TIMEOUT=900 with the harness's 1200s client timeout, any call needing 15-20
    minutes came back as a 502 the client retried until the ladder died — measured on
    sonnet's app-3 turn 9 (five calls, each exactly 900.1s, status 502, twice in a row).
    """
    entry = (CAPTURE.parents[1] / "generators" / "harnesses" / "openhands" / "entry.py").read_text()
    m = re.search(r'OPENHANDS_LLM_TIMEOUT["\']?\s*[,:=]\s*["\']?(\d+)', entry)
    client = int(m.group(1)) if m else 1200
    assert capture.FORWARD_TIMEOUT > client, (
        f"proxy timeout {capture.FORWARD_TIMEOUT}s must exceed the client's {client}s"
    )
