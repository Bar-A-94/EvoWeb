"""EvoWeb generation backends built on off-the-shelf coding CLIs.

"generator" is EvoWeb's word for what builds the app, the thing `--generator` selects.
Every backend in this package is a harness: a thin adapter that
installs one CLI, points it at a model endpoint, and starts it.

    generators/
        harnesses/      one package per harness, each exporting launch()
        session.py      the one runner: process group, timeout, reply and events
    acp/            the vendored ACP client, for the harnesses that speak it
        capture.py      forwarding proxy that records every model call it makes
        langfuse.py     one trace per sample: spans per tool call, generations per call
        npm.py          node installs for the harness CLIs
        template/       the Vite + React + Tailwind scaffold the harness extends
        backend.py      generate(): the --generator entry point
"""
