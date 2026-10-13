"""A forwarding proxy that records every model call an agent makes.

Agents get their model endpoint from us, so pointing that at a local proxy is the one
place every client passes: the ACP agents talk to their own SDKs, mini-swe-agent goes
through litellm, and our bash agent posts directly. Without it a run's token usage, cost
and request count are invisible, and Langfuse gets tool calls with no model calls.

Usage extraction is the part worth getting right: non-streaming responses carry `usage` on
the body, while a stream splits it across `message_start` (input) and `message_delta`
(output). Adapted from the judge bake-off's capture proxy, which learned both of those the
hard way, plus the path fix below.
"""

from __future__ import annotations

import json
import os
import re
import socketserver
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from http.server import BaseHTTPRequestHandler
from typing import cast

STREAM_CHUNK = 8192
# The API floor for budget_tokens, and the smallest max_tokens worth injecting into.
THINKING_MIN = 1024
# One budget for every arm when thinking is forced on, so "on" is comparable across harnesses
# rather than each client's own choice. Override with HARNESS_THINKING_BUDGET.
THINKING_BUDGET = 4096
# The proxy must NEVER be the component that gives up first: it sits between the harness and
# the provider, so a proxy deadline shorter than the client's turns a slow-but-valid call into
# a 502 the client then retries until the ladder dies. At 900s it did exactly that — sonnet's
# app-3 request 9 issued five calls, each cut at 900.1s with status 502, killing the ladder twice
# in a row (2026-08-27), and the same bug is behind the historical "sonnet 502 retries" noise.
# It biases against whichever model thinks longest per call, which is the opposite of what a
# model comparison wants. Keep this strictly ABOVE OPENHANDS_LLM_TIMEOUT (1200s, pinned in
# openhands/entry.py) so the client owns the deadline; the test in tests/test_capture_paths.py
# pins the ordering.
FORWARD_TIMEOUT = int(os.environ.get("WEBGEN_PROXY_TIMEOUT", "1800"))


PREVIEW_CHARS = 2_000
SYSTEM_CHARS = 20_000


def _text_of(blocks: object) -> str:
    """Anthropic content blocks as text, tool calls included.

    A harness turn is often nothing but a tool call, so skipping `tool_use` left the preview
    empty on 8 of 10 turns: the assistant's action IS its message.
    """
    if isinstance(blocks, str):
        return blocks
    if not isinstance(blocks, list):
        return ""
    parts = []
    for block in blocks:
        if not isinstance(block, dict):
            continue
        if block.get("type") == "tool_use":
            parts.append(f"[{block.get('name')}] {json.dumps(block.get('input'))[:600]}")
        elif block.get("type") in (None, "text", "thinking", "tool_result"):
            parts.append(
                str(block.get("text") or block.get("thinking") or block.get("content") or "")
            )
    return "\n".join(part for part in parts if part)


def request_preview(sent: dict) -> str:
    """The last message in the request: what this turn was actually asked to do.

    Clipped, and only the last message: the full prompt is most of a run's tokens (a cached
    call can carry 200k), and Langfuse would hold a copy of every one.
    """
    messages = sent.get("messages") or []
    last = messages[-1] if messages else {}
    text = _text_of(last.get("content") if isinstance(last, dict) else last)
    return text[:PREVIEW_CHARS]


def reply_preview(raw: bytes, content_type: str) -> str:
    """The assistant's own words from the response, streaming or not."""
    if "event-stream" not in (content_type or ""):
        try:
            return _text_of(json.loads(raw).get("content"))[:PREVIEW_CHARS]
        except (ValueError, AttributeError):
            return ""
    chunks = []
    for line in raw.decode("utf-8", "replace").splitlines():
        if not line.startswith("data:"):
            continue
        try:
            event = json.loads(line[5:].strip())
        except ValueError:
            continue
        if event.get("type") == "content_block_delta":
            delta = event.get("delta") or {}
            chunks.append(str(delta.get("text") or delta.get("thinking") or ""))
    return "".join(chunks)[:PREVIEW_CHARS]


def usage_from(raw: bytes, content_type: str) -> dict:
    """Token usage from a response body, streaming or not."""
    if "event-stream" not in (content_type or ""):
        try:
            return json.loads(raw).get("usage") or {}
        except (ValueError, AttributeError):
            return {}
    usage: dict = {}
    for line in raw.decode("utf-8", "replace").splitlines():
        if not line.startswith("data:"):
            continue
        try:
            event = json.loads(line[5:].strip())
        except ValueError:
            continue
        if event.get("type") == "message_start":
            usage.update((event.get("message") or {}).get("usage") or {})
        elif event.get("type") == "message_delta":
            usage.update(event.get("usage") or {})
    return usage


def with_thinking(body: bytes, budget: int) -> tuple[bytes, bool]:
    """Force `thinking` ON with the same budget for every harness.

    The mirror of `without_thinking`, and it has to INJECT rather than pass through: measured on
    the v3 runs, openhands set thinking on 2 of 86 calls and bash and mini_swe_agent never set it
    at all, so leaving each client alone means "on" is really "whatever each one felt like" and
    the arms are still sampled differently.

    Two requests are left alone rather than injected into, because the API rejects the pair:
    a forced `tool_choice` ({"type": "tool"|"any"}), and a `max_tokens` too small to hold the
    minimum 1,024-token budget. Both are recorded as not-injected so a run cannot quietly be
    half-thinking.
    """
    try:
        sent = json.loads(body)
    except ValueError:
        return body, False
    if not isinstance(sent, dict):
        return body, False
    choice = sent.get("tool_choice")
    if isinstance(choice, dict) and choice.get("type") in ("tool", "any"):
        return body, False
    ceiling = sent.get("max_tokens")
    # Needs room for the floor budget AND a reply. Clamping to ceiling - 1 satisfied the API and
    # produced a turn that spent its whole allowance thinking and returned no visible text, which
    # the ACP client reports as "produced no visible reply" and fails.
    if not isinstance(ceiling, int) or ceiling < THINKING_MIN * 2:
        return body, False
    want = {"type": "enabled", "budget_tokens": max(THINKING_MIN, min(budget, ceiling // 2))}
    if sent.get("thinking") == want:
        return body, False
    sent["thinking"] = want
    return json.dumps(sent).encode(), True


def pin_anthropic_sampling(body: bytes, ceiling: int, budget: int) -> tuple[bytes, bool]:
    """Force ONE sampling policy for every harness on an Anthropic route.

    `with_thinking` alone is not enough for a harness comparison: it clamps the budget to
    max_tokens // 2, so harnesses that ask for different ceilings still think differently.
    Measured 2026-08-30: openhands+sonnet sent max_tokens=64000 / thinking enabled@16000 on
    all 2,951 calls (pin_sampling does that at the spec level), but pin_sampling exists ONLY
    in the openhands harness — bash, mini_swe_agent and claude_code sample however their own
    clients feel like. The proxy is the single seam every harness passes through, so the pin
    belongs here: same ceiling, same budget, one code path, no per-harness edits.

    Left alone (recorded as not pinned, so a run cannot be quietly half-pinned): a forced
    tool_choice, which the API rejects alongside thinking.
    """
    try:
        sent = json.loads(body)
    except ValueError:
        return body, False
    if not isinstance(sent, dict) or "messages" not in sent:
        return body, False
    choice = sent.get("tool_choice")
    if isinstance(choice, dict) and choice.get("type") in ("tool", "any"):
        return body, False
    want_budget = max(THINKING_MIN, min(budget, ceiling // 2))
    want = {"type": "enabled", "budget_tokens": want_budget}
    if sent.get("max_tokens") == ceiling and sent.get("thinking") == want:
        return body, False
    sent["max_tokens"] = ceiling
    sent["thinking"] = want
    return json.dumps(sent).encode(), True


def pin_anthropic_effort(body: bytes, effort: str, ceiling: int) -> tuple[bytes, bool]:
    """Force adaptive thinking + output_config.effort on an Anthropic route.

    The GPT-style effort ladder for Claude models that support it (sonnet-4-6 onward):
    the model decides when and how deeply to think under an effort signal, mirroring the
    reasoning_effort arms exactly — no token budget anywhere. Mutually exclusive with
    pin_anthropic_sampling, which owns the legacy enabled+budget policy.
    """
    try:
        sent = json.loads(body)
    except ValueError:
        return body, False
    if not isinstance(sent, dict) or "messages" not in sent:
        return body, False
    choice = sent.get("tool_choice")
    if isinstance(choice, dict) and choice.get("type") in ("tool", "any"):
        return body, False
    want_th, want_oc = {"type": "adaptive"}, {"effort": effort}
    if (
        sent.get("max_tokens") == ceiling
        and sent.get("thinking") == want_th
        and sent.get("output_config") == want_oc
    ):
        return body, False
    sent["max_tokens"] = ceiling
    sent["thinking"] = want_th
    sent["output_config"] = want_oc
    return json.dumps(sent).encode(), True


def pin_openai_effort(body: bytes, effort: str) -> tuple[bytes, bool]:
    """Force ONE reasoning effort for every harness on an OpenAI-style route.

    The non-Anthropic counterpart of pin_anthropic_sampling, for the same reason: only
    openhands pins reasoning_effort (at its spec level), so under any other harness a GPT
    model samples at the provider default and a harness comparison silently becomes an
    effort comparison. The proxy is the one seam every harness passes through.

    Handles both wire shapes: /v1/responses carries {"reasoning": {"effort": ...}};
    chat/completions carries a top-level "reasoning_effort".
    """
    try:
        sent = json.loads(body)
    except ValueError:
        return body, False
    if not isinstance(sent, dict) or "model" not in sent:
        return body, False
    if "messages" in sent:  # chat/completions shape
        if sent.get("reasoning_effort") == effort:
            return body, False
        sent["reasoning_effort"] = effort
    else:  # responses shape
        reasoning = sent.get("reasoning") if isinstance(sent.get("reasoning"), dict) else {}
        if reasoning.get("effort") == effort:
            return body, False
        sent["reasoning"] = {**reasoning, "effort": effort}
    return json.dumps(sent).encode(), True


def without_thinking(body: bytes) -> tuple[bytes, bool]:
    """Drop the `thinking` field so the turn runs with no reasoning budget.

    Removing the field rather than sending {"type": "disabled"} because omission is the
    model's own default and cannot conflict with another parameter, while an injected
    thinking object is the shape that 400s alongside a forced tool_choice. Verified on
    claude-haiku-4-5: omitted and "disabled" both yield zero thinking tokens, and a
    replayed thinking block in the history is tolerated either way.

    NOT model-neutral: on Claude Opus 5 an omitted field means adaptive thinking is ON.
    Any model swap has to re-check that thinking_tokens is still zero.
    """
    try:
        sent = json.loads(body)
    except ValueError:
        return body, False
    if not isinstance(sent, dict):
        return body, False
    changed = sent.pop("thinking", None) is not None
    # A context-editing strategy that clears thinking blocks needs thinking on: the API rejects
    # the pair with `clear_thinking_20251015 strategy requires thinking to be enabled or
    # adaptive`, which took every claude_code turn to a 400 the first time this shipped. With no
    # thinking there are no thinking blocks to clear, so drop the strategy with it and leave any
    # other strategy (clear_tool_uses, compaction) alone.
    management = sent.get("context_management")
    if isinstance(management, dict) and isinstance(management.get("edits"), list):
        kept = [
            edit
            for edit in management["edits"]
            if not (
                isinstance(edit, dict) and str(edit.get("type", "")).startswith("clear_thinking")
            )
        ]
        if len(kept) != len(management["edits"]):
            changed = True
            if kept:
                sent["context_management"] = {**management, "edits": kept}
            else:
                sent.pop("context_management")
    if not changed:
        return body, False
    return json.dumps(sent).encode(), True


def normalize_path(upstream: str, path: str) -> str:
    """Map a client path onto the upstream base.

    Anthropic/OpenRouter-style bases (api.anthropic.com, openrouter.ai/api) expect /v1/...
    so bare client paths get /v1 prepended. A base that already carries its own versioned
    root (z.ai's /api/paas/v4) must receive the bare path verbatim: appending /v1 there
    produces /v4/v1/chat/completions, a 404 on every provider that versions the base.
    """
    if re.search(r"/v\d+$", urllib.parse.urlparse(upstream).path):
        return path
    return path if path.startswith("/v1/") else "/v1" + path


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, format: str, *args: object) -> None:  # noqa: A002 - stdlib's name
        """Silence per-request logging; the recorded calls are the record."""

    def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler's naming
        """Forward reads (e.g. an SDK probing /v1/models as a health check).

        Without this the handler answers 501 and a client that probes before its first call
        concludes the endpoint is broken. Not recorded: these are not model calls.
        """
        server = cast("_Server", self.server)
        path = normalize_path(server.upstream, self.path)
        headers = {
            key: value
            for key, value in self.headers.items()
            if key.lower() not in ("host", "content-length", "connection", "accept-encoding")
        }
        request = urllib.request.Request(server.upstream + path, headers=headers, method="GET")
        try:
            with urllib.request.urlopen(request, timeout=FORWARD_TIMEOUT) as response:
                raw, status = response.read(), response.status
                content_type = response.headers.get("Content-Type", "application/json")
        except urllib.error.HTTPError as error:
            raw, status, content_type = error.read(), error.code, "application/json"
        except (urllib.error.URLError, OSError) as error:
            raw, status, content_type = str(error).encode(), 502, "text/plain"
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_POST(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler's naming
        body = self.rfile.read(int(self.headers.get("Content-Length") or 0))
        server = cast("_Server", self.server)
        # Before forwarding, never after: rewriting a copy for the log leaves the wire
        # untouched and reads as a working knob. `sent` is re-parsed from this body below,
        # so the recorded call reports what upstream actually received.
        stripped = rewritten = effort_pinned = False
        if server.no_thinking:
            body, stripped = without_thinking(body)
            rewritten = stripped
        elif server.sampling_pin:
            body, rewritten = pin_anthropic_sampling(body, *server.sampling_pin)
        elif server.anthropic_effort_pin:
            body, rewritten = pin_anthropic_effort(body, *server.anthropic_effort_pin)
        elif server.thinking_budget:
            body, rewritten = with_thinking(body, server.thinking_budget)
        if server.effort_pin:
            body, effort_pinned = pin_openai_effort(body, server.effort_pin)
        headers = {
            key: value
            for key, value in self.headers.items()
            if key.lower() not in ("host", "content-length", "connection", "accept-encoding")
        }
        # Ask upstream not to compress, so the recorded body is readable.
        headers["accept-encoding"] = "identity"
        headers["Content-Length"] = str(len(body))

        # Clients that expect the base URL to carry /v1 post to a bare path; forwarding
        # that verbatim gives api.anthropic.com/messages, a 404 with empty usage. This is
        # the only point every client passes, so normalise here rather than per client.
        path = normalize_path(server.upstream, self.path)
        request = urllib.request.Request(
            server.upstream + path, data=body, headers=headers, method="POST"
        )
        started = time.time()
        # Once a status line has gone out we must never write a second response: the client is
        # mid-SSE and a fresh status + headers would arrive as chunk payload, so its SDK sees
        # corrupt framing instead of a clean truncation. Set before the first body byte, not after
        # the relay returns.
        self._committed = False
        self._partial = bytearray()
        raw, status, content_type, passthrough = b"", 502, "", []
        try:
            with urllib.request.urlopen(request, timeout=FORWARD_TIMEOUT) as response:
                status = response.status
                content_type = response.headers.get("Content-Type", "")
                passthrough = [
                    (key, value)
                    for key, value in response.headers.items()
                    if key.lower()
                    not in ("content-length", "transfer-encoding", "connection", "content-encoding")
                ]
                if "text/event-stream" in content_type.lower():
                    # A client that asked to stream must receive events as they arrive.
                    # response.read() here would hold the whole generation first, so a turn
                    # looks like a FORWARD_TIMEOUT-long hang and any idle-timeout or early
                    # cancellation behaves differently through the proxy than against the real
                    # endpoint. Measured: claude_code streams on 100% of its calls, so this is
                    # the live path, not a hypothetical one. Length is unknown until the stream
                    # ends, so frame it chunked rather than with Content-Length.
                    raw = self._relay_stream(response, status, passthrough)
                else:
                    raw = response.read()
        except urllib.error.HTTPError as error:
            # Forward the upstream headers: a 429 carries retry-after and anthropic-ratelimit-*,
            # and every harness's SDK backs off on them. Dropping them turned a typed
            # RateLimitError into a generic APIError with blind exponential backoff, on a key the
            # team shares.
            raw, status = error.read(), error.code
            content_type = error.headers.get("Content-Type", "") if error.headers else ""
            passthrough = [
                (key, value)
                for key, value in (error.headers.items() if error.headers else [])
                if key.lower()
                not in ("content-length", "transfer-encoding", "connection", "content-encoding")
            ]
        except Exception as error:  # noqa: BLE001 - see below
            # Deliberately broad: http.client.IncompleteRead is an HTTPException, not an OSError,
            # so a narrower clause let it escape do_POST entirely and the call never reached
            # server.record() -- it vanished from model_calls.jsonl and from the cost total.
            raw = bytes(self._partial) or str(error).encode()
            status, content_type, passthrough = 502, "", []

        try:
            sent = json.loads(body)
        except ValueError:
            sent = {}
        server.record(
            {
                "ts": started,
                "duration_s": round(time.time() - started, 3),
                "path": path,
                "status": status,
                "model": sent.get("model"),
                "stream": bool(sent.get("stream")),
                "max_tokens": sent.get("max_tokens"),
                # A harness sets these inside its own client, so the wire is the only
                # place they can be observed rather than assumed.
                "temperature": sent.get("temperature"),
                "thinking": sent.get("thinking"),
                "thinking_stripped": stripped,
                # True when we forced thinking ON for this call; False on the calls the API would
                # reject (forced tool_choice, max_tokens too small), so a partly-injected run is
                # visible instead of silent.
                "thinking_injected": rewritten and not stripped,
                # True when pin_openai_effort rewrote this call's reasoning effort; the pinned
                # value itself is visible in request_preview-adjacent fields upstream of us.
                "effort_pinned": effort_pinned,
                "reasoning_effort": (
                    (sent.get("output_config") or {}).get("effort")
                    if isinstance(sent.get("output_config"), dict)
                    else (sent.get("reasoning") or {}).get("effort")
                    if isinstance(sent.get("reasoning"), dict)
                    else sent.get("reasoning_effort")
                ),
                "messages": len(sent.get("messages") or []),
                "tools": len(sent.get("tools") or []),
                "usage": usage_from(raw, content_type),
                "request_preview": request_preview(sent),
                "reply_preview": reply_preview(raw, content_type),
                "system_preview": server.take_system(sent),
            }
        )

        if self._committed:
            return
        self.send_response(status)
        for key, value in passthrough:
            self.send_header(key, value)
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def _relay_stream(
        self, response: object, status: int, passthrough: list[tuple[str, str]]
    ) -> bytes:
        """Forward an SSE body as it arrives, returning the accumulated copy for the record."""
        self.send_response(status)
        for key, value in passthrough:
            self.send_header(key, value)
        self.send_header("Transfer-Encoding", "chunked")
        self.end_headers()
        self._committed = True
        buffered = self._partial
        # read1, not read: HTTPResponse.read(n) blocks until it has all n bytes, so an 8 KB
        # request holds every event until 8 KB has accumulated and the relay stays buffered.
        # read1 returns whatever has arrived. Measured through this proxy: read() delivered all
        # 30 events at once (0.00s spread), read1 spreads them like the direct endpoint.
        read_available = getattr(response, "read1", None) or response.read  # type: ignore[attr-defined]
        while True:
            chunk = read_available(STREAM_CHUNK)
            if not chunk:
                break
            buffered += chunk
            self.wfile.write(b"%x\r\n%s\r\n" % (len(chunk), chunk))
            self.wfile.flush()
        self.wfile.write(b"0\r\n\r\n")
        self.wfile.flush()
        return bytes(buffered)


class _Server(socketserver.ThreadingTCPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(
        self,
        address: tuple[str, int],
        handler: type,
        *,
        upstream: str,
        record: Callable[[dict], None],
        no_thinking: bool = False,
        thinking_budget: int = 0,
        sampling_pin: tuple[int, int] | None = None,
        effort_pin: str = "",
        anthropic_effort_pin: tuple[str, int] | None = None,
    ):
        self.upstream = upstream
        self.record = record
        self.no_thinking = no_thinking
        self.thinking_budget = thinking_budget
        self.sampling_pin = sampling_pin
        self.effort_pin = effort_pin
        self.anthropic_effort_pin = anthropic_effort_pin
        self._system_seen = False
        # daemon_threads means concurrent first-calls; without this both pass the guard below
        # and both record a system prompt.
        self._system_lock = threading.Lock()
        super().__init__(address, handler)

    def take_system(self, sent: dict) -> str:
        """The system prompt, on the first call that carries one and not again."""
        with self._system_lock:
            if self._system_seen:
                return ""
            text = _text_of(sent.get("system"))[:SYSTEM_CHARS]
            self._system_seen = bool(text)
            return text


class Capture:
    """Records every model call made through `base_url` while the context is open."""

    def __init__(self, upstream: str, *, no_thinking: bool | None = None) -> None:
        self.upstream = upstream.rstrip("/")
        # Three modes (2026-08-20 reconciliation of the #328 injection with pin_sampling):
        #   on / unset  PASS-THROUGH. Sampling parity is enforced at the SPEC level by
        #               openhands/entry.py pin_sampling, which is model-aware: it knows
        #               opus-4-8/opus-5/fable reject {"type": "enabled"} and pins effort
        #               instead. The proxy must not override that — a blind injection sent
        #               enabled/4096 to adaptive-only models, which the API 400s.
        #   off         strip the thinking field (ablation runs).
        #   force       #328's uniform injection: one shared budget for every arm
        #               (HARNESS_THINKING_BUDGET, default 4096). For cross-HARNESS studies
        #               where clients disagree and none of the models are adaptive-only.
        mode = os.environ.get("HARNESS_THINKING", "").lower()
        self.no_thinking = (mode == "off") if no_thinking is None else no_thinking
        self.thinking_budget = (
            int(os.environ.get("HARNESS_THINKING_BUDGET") or THINKING_BUDGET)
            if mode == "force" and not self.no_thinking
            else 0
        )
        # HARNESS_SAMPLING_PIN="<ceiling>:<budget>" pins BOTH numbers for every harness on an
        # Anthropic upstream, so a harness comparison is not also a sampling comparison. Only
        # Anthropic routes: `thinking` is Anthropic-shaped and 400s (or is ignored) elsewhere,
        # and the adaptive-only models (opus-4-8/opus-5/fable) reject {"type": "enabled"}
        # entirely — those stay on openhands/entry.py's effort pin, so leave this unset for them.
        self.sampling_pin: tuple[int, int] | None = None
        pin = os.environ.get("HARNESS_SAMPLING_PIN", "").strip()
        if pin and not self.no_thinking and "anthropic.com" in self.upstream:
            try:
                ceiling_s, budget_s = pin.split(":", 1)
                ceiling, budget = int(ceiling_s), int(budget_s)
            except ValueError:
                raise SystemExit(
                    f"HARNESS_SAMPLING_PIN must be '<ceiling>:<budget>', got {pin!r}"
                ) from None
            if not 0 < budget < ceiling:
                raise SystemExit(
                    f"HARNESS_SAMPLING_PIN needs 0 < budget < ceiling, got {ceiling}/{budget}"
                )
            self.sampling_pin = (ceiling, budget)
        # HARNESS_REASONING_EFFORT pins reasoning effort for every harness on a NON-Anthropic
        # upstream (the counterpart of the sampling pin above): only openhands sets
        # reasoning_effort itself, so under any other harness a GPT-family model would sample
        # at the provider default and a harness comparison silently becomes an effort
        # comparison. Anthropic upstreams are excluded — their effort knob is the thinking
        # block, already owned by HARNESS_SAMPLING_PIN.
        effort = os.environ.get("HARNESS_REASONING_EFFORT", "").strip().lower()
        if effort and effort not in ("low", "medium", "high", "xhigh"):
            raise SystemExit(
                f"HARNESS_REASONING_EFFORT must be low|medium|high|xhigh, got {effort!r}"
            )
        self.effort_pin = effort if effort and "anthropic.com" not in self.upstream else ""
        # HARNESS_ANTHROPIC_EFFORT="<effort>:<ceiling>" pins adaptive thinking +
        # output_config.effort for every harness on an Anthropic upstream — the GPT-style
        # effort ladder for Claude models that support it (sonnet-4-6 onward). Mutually
        # exclusive with HARNESS_SAMPLING_PIN: one arm has ONE thinking policy.
        self.anthropic_effort_pin: tuple[str, int] | None = None
        aeff = os.environ.get("HARNESS_ANTHROPIC_EFFORT", "").strip().lower()
        if aeff and "anthropic.com" in self.upstream and not self.no_thinking:
            if self.sampling_pin is not None:
                raise SystemExit(
                    "HARNESS_ANTHROPIC_EFFORT and HARNESS_SAMPLING_PIN are both set; an arm "
                    "has one thinking policy — clear one of them"
                )
            try:
                level, ceiling_s = aeff.split(":", 1)
                ceiling = int(ceiling_s)
            except ValueError:
                raise SystemExit(
                    f"HARNESS_ANTHROPIC_EFFORT must be '<effort>:<ceiling>', got {aeff!r}"
                ) from None
            if level not in ("low", "medium", "high", "max") or ceiling <= 0:
                raise SystemExit(
                    f"HARNESS_ANTHROPIC_EFFORT needs low|medium|high|max and a positive ceiling, got {aeff!r}"
                )
            self.anthropic_effort_pin = (level, ceiling)
        self.calls: list[dict] = []
        self._lock = threading.Lock()
        self._server: _Server | None = None

    def record(self, call: dict) -> None:
        with self._lock:
            self.calls.append(call)

    def __enter__(self) -> Capture:
        server = _Server(
            ("127.0.0.1", 0),
            _Handler,
            upstream=self.upstream,
            record=self.record,
            no_thinking=self.no_thinking,
            thinking_budget=self.thinking_budget,
            sampling_pin=self.sampling_pin,
            effort_pin=self.effort_pin,
            anthropic_effort_pin=self.anthropic_effort_pin,
        )
        self._server = server
        threading.Thread(target=server.serve_forever, daemon=True).start()
        return self

    def __exit__(self, *_) -> None:
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()

    @property
    def base_url(self) -> str:
        assert self._server is not None, "Capture must be entered before use"
        return f"http://127.0.0.1:{self._server.server_address[1]}"

    def totals(self) -> dict:
        """Per-run request and token totals, for the trace's metadata."""
        keys = (
            "input_tokens",
            "output_tokens",
            "cache_read_input_tokens",
            "cache_creation_input_tokens",
        )
        totals = {
            key: sum((call["usage"] or {}).get(key, 0) for call in self.calls) for key in keys
        }
        return {
            "model_calls": len(self.calls),
            "failed_model_calls": sum(1 for call in self.calls if call["status"] >= 400),
            "model_seconds": round(sum(call["duration_s"] for call in self.calls), 1),
            # The whole context the model read. NOT `prompt_tokens`: that name means
            # OpenAI/vLLM-style input tokens everywhere else in this repo, and Anthropic's
            # own `input_tokens` counts only what was not cached.
            "input_tokens_total": totals["input_tokens"]
            + totals["cache_read_input_tokens"]
            + totals["cache_creation_input_tokens"],
            **totals,
        }
