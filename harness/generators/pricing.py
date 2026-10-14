"""What a run cost, in dollars, for any provider.

Token counts come from the capture proxy, so costs are comparable across harnesses in a way
each agent's self-reported spend is not. Rates come from OpenRouter's public catalog
(https://openrouter.ai/api/v1/models, no key needed), which prices ~400 models including cache
reads and writes, so one code path covers every provider. Cost is None, never 0, when a model
is not listed: a zero reads as a free arm.
"""

from __future__ import annotations

import json
import os
import time
import urllib.request
from pathlib import Path

CATALOG_URL = "https://openrouter.ai/api/v1/models"
CACHE_PATH = Path(os.environ.get("WEBGEN_PRICE_CACHE") or "/tmp/webgen_price_catalog.json")
CACHE_TTL_S = 24 * 3600


def _normalise(model: str) -> str:
    """A key that matches across id styles: Anthropic sends claude-haiku-4-5-20251001, the
    catalog lists anthropic/claude-haiku-4.5."""
    name = model.split("/")[-1].lower()
    parts = name.split("-")
    # Trailing 8-digit date, as Anthropic's API ids carry.
    if parts and len(parts[-1]) == 8 and parts[-1].isdigit():
        parts = parts[:-1]
    return "-".join(parts).replace(".", "-")


def _fetch_catalog() -> list[dict]:
    with urllib.request.urlopen(CATALOG_URL, timeout=30) as response:
        return json.loads(response.read())["data"]


def load_catalog(refresh: bool = False) -> list[dict]:
    """The model catalog, from disk cache when it is fresh enough."""
    if (
        not refresh
        and CACHE_PATH.is_file()
        and time.time() - CACHE_PATH.stat().st_mtime < CACHE_TTL_S
    ):
        try:
            return json.loads(CACHE_PATH.read_text())
        except ValueError:
            pass
    try:
        catalog = _fetch_catalog()
    except Exception:
        # Stale beats absent: a day-old price is still a usable cost, no price at all is not.
        if CACHE_PATH.is_file():
            return json.loads(CACHE_PATH.read_text())
        raise
    CACHE_PATH.write_text(json.dumps(catalog))
    return catalog


def rates_for(model: str) -> dict[str, float] | None:
    """Per-token USD rates for `model`, or None if the catalog does not list it.

    Returns keys: prompt, completion, cache_read, cache_write.
    """
    try:
        catalog = load_catalog()
    except Exception:
        return None
    want = _normalise(model)
    # Exact normalised match first; a `:batch` or `:free` variant is a different product and must
    # not be picked up by a prefix match on the base name.
    candidates = [
        entry for entry in catalog if ":" not in entry["id"] and _normalise(entry["id"]) == want
    ]
    if not candidates:
        return None
    pricing = candidates[0].get("pricing") or {}
    _anthropic = candidates[0]["id"].startswith("anthropic/")

    def number(key: str, fallback: float = 0.0) -> float:
        try:
            return float(pricing.get(key))
        except (TypeError, ValueError):
            return fallback

    prompt = number("prompt")
    # Router entries such as openrouter/auto list "-1" for "depends where it lands".
    if prompt < 0 or number("completion") < 0:
        return None
    if not prompt and not number("completion"):
        # Listed but unpriced. Returning zeros here is the free-arm bug one level down.
        return None
    return {
        "prompt": prompt,
        "completion": number("completion"),
        # The 0.1x / 1.25x defaults are Anthropic's. A provider that publishes no cache price
        # may not cache at all, so assume full prompt price rather than a 10x discount.
        "cache_read": number("input_cache_read", prompt * 0.10 if _anthropic else prompt),
        "cache_write": number("input_cache_write", prompt * 1.25 if _anthropic else prompt),
        "id": candidates[0]["id"],
    }


def cost_usd(totals: dict, model: str) -> float | None:
    """Dollar cost of one run's token totals, as recorded by `Capture.totals()`."""
    rates = rates_for(model)
    if rates is None:
        return None
    # Calls were made but no tokens parsed: usage_from only understands the Anthropic shapes, so
    # an OpenAI-wire run would otherwise price at 0.0 and read as a free arm.
    token_keys = (
        "input_tokens",
        "output_tokens",
        "cache_read_input_tokens",
        "cache_creation_input_tokens",
    )
    if totals.get("model_calls") and not any(totals.get(key) for key in token_keys):
        return None
    dollars = (
        totals.get("input_tokens", 0) * rates["prompt"]
        + totals.get("cache_read_input_tokens", 0) * rates["cache_read"]
        + totals.get("cache_creation_input_tokens", 0) * rates["cache_write"]
        + totals.get("output_tokens", 0) * rates["completion"]
    )
    return round(dollars, 6)
