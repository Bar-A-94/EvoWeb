"""The released runs behind the paper's numbers: which run ids make up each table.

A *run* is one full pass of one model over the 32 apps. Its id is a directory name under
`paths.TRACES` (examples_artifacts/traces/, unpacked from traces.zip on first use):

    <run-id>/<app:06d>/result.json                   the judge's verdicts, request by request
    <run-id>/<app:06d>/generation/model_calls.jsonl  the first request's compact token log
    <run-id>/<app:06d>/turn<k>/generation/...        the same for follow-up request k

Run ids are `<model>-run<k>` for the main runs and `multilingual-<model>-<lang>` for the
language runs. `evoweb.metrics.load_ladders(run_id)` reads one; `compare_to_released`, the
live reproduction test and the ablation scripts take the run ids from the three tables below.

The released traces are the paper's runs of the four Anthropic models (Fable 5, Opus 4.8,
Sonnet 4.6, Haiku 4.5), three runs each, plus the multilingual runs of Sonnet 4.6 and Haiku 4.5
in five languages. The paper's other models' runs are not released.

TABLE2        Table 2 / App. F / Figure 3: model -> its three runs. A model row averages its
              runs (mean, and population std where n > 1).
DAG_TABLE     Table 4 (Grade by test type) and Figure 4 (score vs DAG depth / in-degree):
              model -> the first two of its TABLE2 runs.
MULTILINGUAL  Table 3: model -> language -> one run. The English column of Table 3 is the
              model's TABLE2 row.

`all_run_ids()` lists every released run once; `nav_guidance(run_id)` gives the build-guidance
setting a run was made with, for re-running it under the same conditions.
"""

from __future__ import annotations

from .paths import LANGS  # noqa: F401  (Table 3's languages, re-exported)

# ---------------------------------------------------------------- Table 2 / App. F / Figure 3
TABLE2: dict[str, list[str]] = {
    "Fable 5": [
        "fable-5-run1",
        "fable-5-run2",
        "fable-5-run3",
    ],
    "Opus 4.8": [
        "opus-4.8-run1",
        "opus-4.8-run2",
        "opus-4.8-run3",
    ],
    "Sonnet 4.6": [
        "sonnet-4.6-run1",
        "sonnet-4.6-run2",
        "sonnet-4.6-run3",
    ],
    "Haiku 4.5": [
        "haiku-4.5-run1",
        "haiku-4.5-run2",
        "haiku-4.5-run3",
    ],
}
# Paper order of the model rows.
MODELS: tuple[str, ...] = tuple(TABLE2)

# ---------------------------------------------------------------- Table 4 / Figure 4
DAG_TABLE: dict[str, list[str]] = {m: runs[:2] for m, runs in TABLE2.items()}

# ---------------------------------------------------------------- Table 3 (language)
# The user writes in another language and the app stays in English: the request text is
# translated (data/multilingual/evoweb_benchmark_<lang>.jsonl); the judge tasks are the English
# originals.
LANG_NAMES: dict[str, str] = {
    "en": "English",
    "fr": "French",
    "de": "German",
    "zh": "Chinese",
    "hi": "Hindi",
    "he": "Hebrew",
}
# model -> language -> run id.
MULTILINGUAL: dict[str, dict[str, str]] = {
    "Sonnet 4.6": {
        "fr": "multilingual-sonnet-4.6-fr",
        "de": "multilingual-sonnet-4.6-de",
        "zh": "multilingual-sonnet-4.6-zh",
        "hi": "multilingual-sonnet-4.6-hi",
        "he": "multilingual-sonnet-4.6-he",
    },
    "Haiku 4.5": {
        "fr": "multilingual-haiku-4.5-fr",
        "de": "multilingual-haiku-4.5-de",
        "zh": "multilingual-haiku-4.5-zh",
        "hi": "multilingual-haiku-4.5-hi",
        "he": "multilingual-haiku-4.5-he",
    },
}

# ---------------------------------------------------------------- run conditions
# Build guidance the agent received (harness variable WEBGEN_NAV_GUIDANCE, see harness/README.md).
# "on": the build prompt tells the agent to add a nav <Link> for every page it creates; "off"
# drops that sentence. The judge navigates by clicking, so the setting moves scores. Every
# released run was made with it on except Fable 5's third run, which was made with it off. A
# re-run meant to be compared with a released run must use that run's setting. The registry
# records no exception for the multilingual runs, so nav_guidance() reports "on" for them.
NAV_GUIDANCE: dict[str, str] = {rid: "on" for runs in TABLE2.values() for rid in runs}
NAV_GUIDANCE["fable-5-run3"] = "off"


def nav_guidance(run_id: str) -> str:
    """WEBGEN_NAV_GUIDANCE setting of a released run: "on" or "off" ("on" for any unlisted run)."""
    return NAV_GUIDANCE.get(run_id, "on")


def all_run_ids() -> list[str]:
    """Every released run id once: TABLE2's runs (which include DAG_TABLE's), then MULTILINGUAL's."""
    ids: list[str] = []
    for m in MODELS:
        ids += TABLE2[m]
    for langs in MULTILINGUAL.values():
        ids += list(langs.values())
    return list(dict.fromkeys(ids))
