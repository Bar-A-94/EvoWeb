"""`evoweb run`: run the benchmark on a model, judged by another, via harness/run_local.sh.

A model (or judge) is a name plus where it is served:
  --model-port 8000 [--model-host H]   a vLLM / OpenAI-compatible server at http://H:8000/v1
  --model-url https://<host>/v1        any other OpenAI-compatible API, key in MODEL_API_KEY
                                       (JUDGE_API_KEY for the judge)
  neither                              an API model, `provider/model`, keyed by the provider's
                                       usual variable (ANTHROPIC_API_KEY, OPENAI_API_KEY, ...)
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import urllib.request

from evoweb.paths import ROOT

# provider prefix -> (harness PROVIDER, base URL, key variable)
APIS = {
    "anthropic": ("Anthropic", "https://api.anthropic.com", "ANTHROPIC_API_KEY"),
    "openai": ("OpenAILike", "https://api.openai.com/v1", "OPENAI_API_KEY"),
    "openrouter": ("OpenRouter", "https://openrouter.ai/api/v1", "OPENROUTER_API_KEY"),
}


def check(url: str, name: str, key: str) -> None:
    """Exit unless the server at url answers and serves name."""
    req = urllib.request.Request(f"{url}/models", headers={"Authorization": f"Bearer {key}"})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            served = [m["id"] for m in json.load(r)["data"]]
    except Exception as e:  # noqa: BLE001 - any failure means the server is not usable
        sys.exit(f"{url}: no answer on /models ({e}); is the server up?")
    if name not in served:
        sys.exit(f"{url} serves {', '.join(served)}, not {name}")


def endpoint(a: argparse.Namespace, role: str) -> tuple:
    """(provider, base URL, model id without provider prefix, key) for --model or --judge."""
    name, host, port, url = (getattr(a, f"{role}{s}") for s in ("", "_host", "_port", "_url"))
    if host and not port:
        sys.exit(f"--{role}-host needs --{role}-port")
    if port or url:
        url = url or f"http://{host or 'localhost'}:{port}/v1"
        key = os.environ.get(f"{role.upper()}_API_KEY", "local")
        check(url, name, key)
        return "OpenAILike", url, name, key
    prefix, _, model = name.partition("/")
    if prefix not in APIS or not model:
        sys.exit(f"{name}: give a port or URL, or a model prefixed with one of {', '.join(APIS)}")
    provider, base, var = APIS[prefix]
    if not os.environ.get(var):
        sys.exit(f"{name}: {var} is not set")
    return provider, base, model, os.environ[var]


def run(a: argparse.Namespace) -> int:
    script = ROOT / "harness" / "run_local.sh"
    if not script.is_file():
        sys.exit(
            f"{script} not found: install from a clone of the repository with `pip install -e .`"
        )
    provider, url, model, key = endpoint(a, "model")
    env = {
        "PROVIDER": provider,
        "API_KEY": key,
        # The agent takes Anthropic models as anthropic/<id> and everything else as openai/<id>.
        "MODEL": f"anthropic/{model}" if provider == "Anthropic" else f"openai/{model}",
    }
    if provider == "Anthropic":
        os.environ.pop("API_URL", None)
    else:
        # OpenRouter's agent base has no /v1 (the capture proxy adds it).
        env["API_URL"] = url.removesuffix("/v1") if provider == "OpenRouter" else url
    judge, env["EVAL_API_URL"], env["EVAL_MODEL"], env["EVAL_API_KEY"] = endpoint(a, "judge")
    env["EVAL_PROVIDER"] = "anthropic" if judge == "Anthropic" else "openai"
    os.environ.update(env)
    return subprocess.call([str(script), a.name, a.apps, str(a.parallel)])


def main() -> None:
    p = argparse.ArgumentParser(prog="evoweb")
    sub = p.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="run the benchmark; results go to runs/<name>/")
    r.add_argument("--name", required=True, help="run name; results go to runs/<name>/")
    for role, default in (("model", None), ("judge", "anthropic/claude-sonnet-4-6")):
        r.add_argument(
            f"--{role}",
            required=default is None,
            default=default,
            help="served name, or provider/model for an API",
        )
        r.add_argument(f"--{role}-port", type=int, help="port of a vLLM / OpenAI-compatible server")
        r.add_argument(f"--{role}-host", help="host of that server (default localhost)")
        r.add_argument(f"--{role}-url", help="full base URL instead of host + port")
    r.add_argument("--apps", default="1-32", help="subset, e.g. 1,4,6")
    r.add_argument("--parallel", type=int, default=8, help="apps run at once")
    sys.exit(run(p.parse_args()))


if __name__ == "__main__":
    main()
