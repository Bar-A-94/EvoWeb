"""One sampling policy for every harness, enforced at the proxy.

pin_sampling lives only in the openhands harness, so bash / mini_swe_agent / claude_code
sampled however their own clients felt like — a harness comparison was also a sampling
comparison. The capture proxy is the single seam all four pass through, so the pin lives
there: HARNESS_SAMPLING_PIN="<ceiling>:<budget>", Anthropic upstreams only.
"""

import importlib.util
import json
import re
import sys
from pathlib import Path

import pytest

CAPTURE = Path(__file__).resolve().parents[2] / "harness" / "generators" / "capture.py"


def load():
    spec = importlib.util.spec_from_file_location("_capture_pin", CAPTURE)
    m = importlib.util.module_from_spec(spec)
    sys.modules["_capture_pin"] = m
    spec.loader.exec_module(m)
    return m


capture = load()


def body(**kw):
    base = {"messages": [{"role": "user", "content": "hi"}], "max_tokens": 8000}
    base.update(kw)
    return json.dumps(base).encode()


def test_a_harness_asking_for_a_smaller_ceiling_is_raised_to_the_pinned_one():
    out, changed = capture.pin_anthropic_sampling(body(), 64000, 16000)
    sent = json.loads(out)
    assert changed
    assert sent["max_tokens"] == 64000
    assert sent["thinking"] == {"type": "enabled", "budget_tokens": 16000}


def test_every_harness_lands_on_the_identical_policy_whatever_it_asked_for():
    """The whole point: three different client requests, one wire policy."""
    variants = [
        body(),
        body(max_tokens=4096),
        body(max_tokens=64000, thinking={"type": "enabled", "budget_tokens": 1024}),
    ]
    seen = set()
    for v in variants:
        out, _ = capture.pin_anthropic_sampling(v, 64000, 16000)
        sent = json.loads(out)
        seen.add((sent["max_tokens"], json.dumps(sent["thinking"], sort_keys=True)))
    assert len(seen) == 1, f"harnesses still diverge: {seen}"


def test_an_already_pinned_request_is_not_rewritten_twice():
    pinned = json.dumps(
        {
            "messages": [{"role": "user", "content": "hi"}],
            "max_tokens": 64000,
            "thinking": {"type": "enabled", "budget_tokens": 16000},
        }
    ).encode()
    _, changed = capture.pin_anthropic_sampling(pinned, 64000, 16000)
    assert not changed


def test_a_forced_tool_choice_is_left_alone_because_the_api_rejects_the_pair():
    out, changed = capture.pin_anthropic_sampling(
        body(tool_choice={"type": "tool", "name": "x"}), 64000, 16000
    )
    assert not changed and json.loads(out)["max_tokens"] == 8000


def test_the_budget_never_exceeds_half_the_ceiling():
    """A budget that eats the whole allowance produces a reply with no visible text."""
    sent = json.loads(capture.pin_anthropic_sampling(body(), 4000, 16000)[0])
    assert sent["thinking"]["budget_tokens"] <= 4000 // 2


@pytest.mark.parametrize(
    "upstream,expected",
    [
        ("https://api.anthropic.com", True),
        ("https://openrouter.ai/api", False),
        ("https://api.z.ai/api/paas/v4", False),
    ],
)
def test_the_pin_is_anthropic_only(monkeypatch, upstream, expected):
    """`thinking` is Anthropic-shaped; injecting it into other routes is a 400 or a no-op."""
    monkeypatch.setenv("HARNESS_SAMPLING_PIN", "64000:16000")
    monkeypatch.delenv("HARNESS_THINKING", raising=False)
    proxy = capture.Capture(upstream)
    assert (proxy.sampling_pin is not None) is expected


def test_a_malformed_pin_aborts_instead_of_running_an_unpinned_arm(monkeypatch):
    monkeypatch.setenv("HARNESS_SAMPLING_PIN", "64000")
    proxy_cls = capture.Capture
    with pytest.raises(SystemExit):
        proxy_cls("https://api.anthropic.com")


def test_every_harness_reads_the_same_per_call_timeout_knob():
    """A harness comparison must not be a timeout comparison.

    openhands pinned 1200s while bash used 300s and mini_swe_agent inherited litellm's 300s
    default — so calls openhands would let finish were killed in the other two. Measured
    2026-08-30: sonnet at a 16k thinking budget hit bash's 300s at turn 4 (104 prior
    messages), retried 4x, and the ladder died.
    """
    root = CAPTURE.parents[1] / "generators" / "harnesses"
    for rel in ("bash/program.py", "mini_swe_agent/entry.py", "openhands/entry.py"):
        src = (root / rel).read_text()
        assert "HARNESS_LLM_TIMEOUT" in src, f"{rel} does not read the shared timeout knob"


def test_the_shared_timeout_stays_below_the_proxy_deadline():
    """The client must give up before the proxy, or a stall is reported as our 502."""
    src = (CAPTURE.parents[1] / "generators" / "harnesses" / "bash" / "program.py").read_text()
    m = re.search(r'HARNESS_LLM_TIMEOUT"\)\s*or\s*(\d+)', src)
    assert m and int(m.group(1)) < capture.FORWARD_TIMEOUT


# ---------------------------------------------------------------- OpenAI effort pin


def test_effort_pin_rewrites_a_responses_body():
    body, changed = capture.pin_openai_effort(
        json.dumps(
            {"model": "gpt-5.6-terra", "input": [], "reasoning": {"summary": "auto"}}
        ).encode(),
        "high",
    )
    assert changed
    sent = json.loads(body)
    assert sent["reasoning"] == {"summary": "auto", "effort": "high"}


def test_effort_pin_rewrites_a_chat_completions_body():
    body, changed = capture.pin_openai_effort(
        json.dumps({"model": "gpt-5.6-terra", "messages": []}).encode(), "high"
    )
    assert changed
    assert json.loads(body)["reasoning_effort"] == "high"


def test_effort_pin_is_idempotent_on_an_already_pinned_body():
    body = json.dumps({"model": "m", "input": [], "reasoning": {"effort": "high"}}).encode()
    assert capture.pin_openai_effort(body, "high") == (body, False)


@pytest.mark.parametrize(
    "upstream,expected",
    [
        ("https://api.openai.com", True),
        ("https://openrouter.ai/api", True),
        ("https://api.anthropic.com", False),  # Anthropic's effort knob is the thinking block
    ],
)
def test_the_effort_pin_skips_anthropic_upstreams(monkeypatch, upstream, expected):
    monkeypatch.setenv("HARNESS_REASONING_EFFORT", "high")
    monkeypatch.delenv("HARNESS_SAMPLING_PIN", raising=False)
    monkeypatch.delenv("HARNESS_THINKING", raising=False)
    assert bool(capture.Capture(upstream).effort_pin) is expected


def test_a_malformed_effort_aborts_instead_of_running_an_unpinned_arm(monkeypatch):
    monkeypatch.setenv("HARNESS_REASONING_EFFORT", "max")  # not in the SDK enum
    with pytest.raises(SystemExit):
        capture.Capture("https://api.openai.com")


# ---------------------------------------------------------------- Anthropic effort ladder pin


def test_anthropic_effort_pin_rewrites_thinking_and_effort():
    body, changed = capture.pin_anthropic_effort(
        json.dumps(
            {
                "model": "claude-sonnet-4-6",
                "messages": [],
                "max_tokens": 32000,
                "thinking": {"type": "enabled", "budget_tokens": 16000},
            }
        ).encode(),
        "low",
        64000,
    )
    assert changed
    sent = json.loads(body)
    assert sent["thinking"] == {"type": "adaptive"}
    assert sent["output_config"] == {"effort": "low"}
    assert sent["max_tokens"] == 64000


def test_anthropic_effort_pin_conflicts_with_the_sampling_pin(monkeypatch):
    """One arm has ONE thinking policy; both pins set is a config error, not a precedence rule."""
    monkeypatch.setenv("HARNESS_SAMPLING_PIN", "64000:16000")
    monkeypatch.setenv("HARNESS_ANTHROPIC_EFFORT", "low:64000")
    monkeypatch.delenv("HARNESS_THINKING", raising=False)
    with pytest.raises(SystemExit):
        capture.Capture("https://api.anthropic.com")


@pytest.mark.parametrize(
    "upstream,expected",
    [
        ("https://api.anthropic.com", True),
        ("https://api.openai.com", False),
    ],
)
def test_the_anthropic_effort_pin_is_anthropic_only(monkeypatch, upstream, expected):
    monkeypatch.setenv("HARNESS_ANTHROPIC_EFFORT", "medium:64000")
    monkeypatch.delenv("HARNESS_SAMPLING_PIN", raising=False)
    monkeypatch.delenv("HARNESS_THINKING", raising=False)
    assert (capture.Capture(upstream).anthropic_effort_pin is not None) is expected


def test_a_malformed_anthropic_effort_aborts(monkeypatch):
    monkeypatch.setenv("HARNESS_ANTHROPIC_EFFORT", "xhigh:64000")  # sonnet-4-6 has no xhigh
    monkeypatch.delenv("HARNESS_SAMPLING_PIN", raising=False)
    with pytest.raises(SystemExit):
        capture.Capture("https://api.anthropic.com")
