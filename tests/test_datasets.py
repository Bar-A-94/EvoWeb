"""The datasets and the tooling that (re)generates them.

    /usr/bin/python3 -m pytest tests/test_datasets.py -q          # ~2 min; add -m "not slow" to skip the gate

Every "byte-identical" claim in data/README.md and data/data_gen/README.md is asserted here, against the
committed files, writing only into pytest's tmp_path.
"""

from __future__ import annotations

import filecmp
import json
import subprocess
import sys
from pathlib import Path

import pytest

PKG = Path(__file__).resolve().parents[1]
if str(PKG) not in sys.path:
    sys.path.insert(0, str(PKG))
from evoweb.paths import BENCHMARK, DATA, MULTILINGUAL  # noqa: E402

DS = PKG / "data" / "data_gen"
ML = DS / "multilingual"
PY = sys.executable
LANGS = ["es", "zh", "he", "hi", "sw", "de", "fr"]


def rows(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.open(encoding="utf-8") if line.strip()]


def run(*argv, **kw):
    return subprocess.run([PY, *map(str, argv)], capture_output=True, text=True, **kw)


# ───────────────────────────────────────────── make_tasksets ─────────────────────────────────
def test_benchmark_rows_are_the_wave_in_order():
    sys.path.insert(0, str(PKG / "harness"))
    import make_tasksets as mt  # noqa: E402

    assert mt.SMOKE_DIR == PKG / "tests" / "smoke_sets"

    # row order == the WAVE list == 1-based sample index; every row is populated
    assert [r["id"] for r in rows(BENCHMARK)] == mt.WAVE and len(mt.WAVE) == 32
    assert all(r["follow_ups"] for r in rows(BENCHMARK))
    # the smoke sets are rows of BENCHMARK with the follow-ups trimmed, same serialisation
    full = {json.loads(line)["id"]: line for line in BENCHMARK.open(encoding="utf-8")}
    assert mt.taskset(full, len(mt.WAVE), None) == BENCHMARK.read_text(encoding="utf-8")


def test_manifest_parent_hash_matches_evoweb():
    import hashlib

    manifest = json.loads((ML / "manifest_enui.json").read_text())
    assert manifest["parent"] == BENCHMARK.name
    assert hashlib.sha256(BENCHMARK.read_bytes()).hexdigest() == manifest["parent_sha256"]


# ───────────────────────────────────────────── row schema ────────────────────────────────────
def test_every_evoweb_row_has_9_follow_ups_with_5_checks_in_the_slot_template():
    for row in rows(BENCHMARK):
        fus = row["follow_ups"]
        assert len(fus) == 9
        assert {n["id"] for n in row["dependency_graph"]["nodes"]} == {
            f"T{i}" for i in range(1, 11)
        }
        assert len(row["global_rules"]) == 3
        assert row["pinned_seed"]["introduced_in_turn"] in (2, 3)
        for k, fu in enumerate(fus, start=2):
            tasks = fu["ui_instruct"]
            assert len(tasks) == 5, (row["id"], k)
            kinds = [t["kind"] for t in tasks]
            assert all(x in ("exact-value", "feature") for x in kinds[:3]), (row["id"], k, kinds)
            assert kinds[3] == "integration" and kinds[4] == "regression", (row["id"], k, kinds)
            assert "difficulty" not in fu  # dropped: it was "hard" on every follow-up
            assert fu["archetype"] in (
                "derived-state",
                "multi-surface-workflow",
                "interactive-tool",
                "design-restyle",
            )
            src = tasks[4]["copied_from_turn"]
            assert 1 <= src < k
            if src >= 2:  # verbatim from the cited turn (turn 1 regressions are authored)
                pool = {(t["task"], t["expected_result"]) for t in fus[src - 2]["ui_instruct"]}
                assert (tasks[4]["task"], tasks[4]["expected_result"]) in pool


def test_exactly_18_global_rule_turns_have_no_incoming_dag_edge():
    """Table 4's 'integration excluding the 18 global-rule checks'."""
    no_incoming = 0
    for row in rows(BENCHMARK):
        targets = {e["to"] for e in row["dependency_graph"]["edges"]}
        for e in row["dependency_graph"]["edges"]:
            assert int(e["from"][1:]) < int(e["to"][1:]), (row["id"], e)
        no_incoming += sum(1 for k in range(2, 11) if f"T{k}" not in targets)
    assert no_incoming == 18


def test_turn_1_is_byte_identical_across_arms():
    ctl = {r["id"]: r for r in rows(BENCHMARK)}
    for fn in ("ablation_no_grounding.jsonl",):
        for r in rows(DATA / fn):
            if r.get("follow_ups"):
                assert (r["instruction"], r["ui_instruct"]) == (
                    ctl[r["id"]]["instruction"],
                    ctl[r["id"]]["ui_instruct"],
                )


# ───────────────────────────────────────────── audit ─────────────────────────────────────────
def test_audit_parts_verdicts_match_the_shipped_sets():
    def clean_dirty(dataset):
        r = run(DS / "audit_parts.py", DATA / dataset, "--quiet")
        lines = r.stdout.splitlines()
        clean = json.loads(lines[1].split(":", 1)[1])
        dirty = [int(x) for x in json.loads(lines[2].split(":", 1)[1].replace("'", '"'))]
        return clean, dirty

    wave = [int(r["id"]) for r in rows(BENCHMARK)]
    clean, dirty = clean_dirty("ablation_no_grounding.jsonl")
    assert clean == [i for i in wave if i not in (41, 93)] and dirty == []
    # the July control predates the audit: app 48 fails exact-value coverage yet ships
    clean, dirty = clean_dirty("evoweb_benchmark.jsonl")
    assert dirty == [48] and set(clean) == set(wave) - {48}


# ───────────────────────────────────────────── multilingual ──────────────────────────────────
def test_validate_parts_passes_for_every_app():
    r = run(ML / "validate_parts.py")
    assert r.returncode == 0, r.stdout[-2000:]
    passes = [line for line in r.stdout.splitlines() if line.startswith("== ") and ": PASS" in line]
    assert len(passes) == 32


def test_multilingual_assemble_reproduces_all_translated_sets(tmp_path):
    r = run(ML / "assemble.py", "--out-dir", tmp_path)
    assert r.returncode == 0, r.stdout[-1000:] + r.stderr[-1000:]
    suffix = "_enui"
    for lang in LANGS:
        name = f"evoweb_benchmark_{lang}.jsonl"
        assert filecmp.cmp(tmp_path / name, MULTILINGUAL / name, shallow=False), (
            f"{name} not byte-identical"
        )
    committed = json.loads((ML / f"manifest{suffix}.json").read_text())
    fresh = json.loads((tmp_path / f"manifest{suffix}.json").read_text())
    assert (
        fresh["files"] == committed["files"]
        and fresh["parent_sha256"] == committed["parent_sha256"]
    )


def test_translated_rows_keep_english_metadata_and_row_order():
    en = rows(BENCHMARK)
    for lang in LANGS:
        for suffix in ("_enui",):
            tr = rows(MULTILINGUAL / f"evoweb_benchmark_{lang}.jsonl")
            assert [r["id"] for r in tr] == [r["id"] for r in en]
            for a, b in zip(tr, en):
                assert a["instruction"] != b["instruction"]
                assert a["dependency_graph"] == b["dependency_graph"]
                assert (
                    a["global_rules"] == b["global_rules"] and a["pinned_seed"] == b["pinned_seed"]
                )
                if suffix:  # judge tasks untouched
                    assert a["ui_instruct"] == b["ui_instruct"]
                    assert [f["ui_instruct"] for f in a["follow_ups"]] == [
                        f["ui_instruct"] for f in b["follow_ups"]
                    ]


# ───────────────────────────────────────────── ablation gates ────────────────────────────────
@pytest.mark.slow
def test_grounding_run_all_check_passes():
    r = run(PKG / "ablations" / "grounding" / "run_all.py", "--check")
    assert r.returncode == 0, r.stdout[-3000:] + r.stderr[-1000:]
    assert "failed 0" in r.stdout
