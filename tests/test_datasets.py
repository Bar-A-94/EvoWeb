"""The datasets and the tooling that (re)generates them.

    /usr/bin/python3 -m pytest tests/test_datasets.py -q          # ~2 min; add -m "not slow" to skip the gate

Every "byte-identical" claim in data/README.md and data/data_gen/README.md is asserted here, against the
files downloaded from Hugging Face, writing only into pytest's tmp_path.
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
from evoweb.paths import BENCHMARK, DATA, LANGS, MULTILINGUAL  # noqa: E402

DS = PKG / "data" / "data_gen"
ML = DS / "multilingual"
PY = sys.executable


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


# ───────────────────────────────────────────── row schema ────────────────────────────────────
def test_every_evoweb_row_has_9_follow_ups_with_5_checks_in_the_slot_template():
    for row in rows(BENCHMARK):
        fus = row["follow_ups"]
        assert len(fus) == 9
        assert {n["id"] for n in row["dependency_graph"]["nodes"]} == {
            f"R{i}" for i in range(1, 11)
        }
        assert len(row["global_rules"]) == 3
        assert row["pinned_seed"]["introduced_in_request"] in (2, 3)
        for k, fu in enumerate(fus, start=2):
            tasks = fu["ui_instruct"]
            assert len(tasks) == 5, (row["id"], k)
            kinds = [t["kind"] for t in tasks]
            assert all(x in ("exact-value", "feature") for x in kinds[:3]), (row["id"], k, kinds)
            assert kinds[3] == "integration" and kinds[4] == "backward", (row["id"], k, kinds)
            assert "difficulty" not in fu  # dropped: it was "hard" on every follow-up
            assert fu["archetype"] in (
                "derived-state",
                "multi-surface-workflow",
                "interactive-tool",
                "design-restyle",
            )
            src = tasks[4]["copied_from_request"]
            assert 1 <= src < k
            if src >= 2:  # verbatim from the cited request (request-1 backward checks are authored)
                pool = {(t["task"], t["expected_result"]) for t in fus[src - 2]["ui_instruct"]}
                assert (tasks[4]["task"], tasks[4]["expected_result"]) in pool


def test_exactly_18_global_rule_requests_have_no_incoming_dag_edge():
    """Table 4's 'integration excluding the 18 global-rule checks'."""
    no_incoming = 0
    for row in rows(BENCHMARK):
        targets = {e["to"] for e in row["dependency_graph"]["edges"]}
        for e in row["dependency_graph"]["edges"]:
            assert int(e["from"][1:]) < int(e["to"][1:]), (row["id"], e)
        no_incoming += sum(1 for k in range(2, 11) if f"R{k}" not in targets)
    assert no_incoming == 18


def test_request_1_is_byte_identical_across_arms():
    ctl = {r["id"]: r for r in rows(BENCHMARK)}
    for fn in ("ablation_no_grounding.jsonl",):
        for r in rows(DATA / fn):
            if r.get("follow_ups"):
                assert (r["instruction"], r["ui_instruct"]) == (
                    ctl[r["id"]]["instruction"],
                    ctl[r["id"]]["ui_instruct"],
                )


# ───────────────────────────────────────────── audit ─────────────────────────────────────────
def test_shipped_sets_already_use_the_paper_terms():
    """paper_terms() (applied by assemble_dataset.py) is a no-op on every shipped row."""
    sys.path.insert(0, str(DS))
    from paper_terms import paper_terms  # noqa: E402

    for path in (BENCHMARK, DATA / "ablation_no_grounding.jsonl"):
        for r in rows(path):
            assert paper_terms(r) == r, (path.name, r["id"])


def test_generator_output_with_the_old_terms_audits_and_assembles_to_the_shipped_set(tmp_path):
    """The .js generators still write the old terms; audit + assemble must give the shipped set.

    Parts are rebuilt from ablation_no_grounding.jsonl in the generator's own vocabulary
    (copied_from_turn, kind "regression", T1..T10), then audited and assembled from scratch.
    """
    import re

    sys.path.insert(0, str(DS))
    from assemble_dataset import META_FIELDS  # noqa: E402
    from paper_terms import KEYS, TEXT_FIELDS, VALUES  # noqa: E402

    old_keys = {v: k for k, v in KEYS.items()}
    old_values = {v: k for k, v in VALUES.items()}
    graph_id = re.compile(r"\bR(10|[1-9])\b")
    text = [
        (re.compile(r"\brequest(s?) (?=\d)"), r"turn\1 "),
        (re.compile(r"\b(four|nine|later|late) request(s?)\b"), r"\1 turn\2"),
    ]

    def old_terms(o, key=None):
        if isinstance(o, dict):
            return {old_keys.get(k, k): old_terms(v, k) for k, v in o.items()}
        if isinstance(o, list):
            return [old_terms(x, key) for x in o]
        if not isinstance(o, str):
            return o
        if key in ("kind", "subcategories"):
            return old_values.get(o, o)
        if key in ("id", "from", "to"):
            return graph_id.sub(r"T\1", o)
        if key in TEXT_FIELDS:
            o = graph_id.sub(r"T\1", o)
            for pat, rep in text:
                o = pat.sub(rep, o)
        return o

    shipped = DATA / "ablation_no_grounding.jsonl"
    parts = tmp_path / "ablation_dataset_no_grounding"
    parts.mkdir()
    for r in rows(shipped):
        part = {"app_idx": int(r["id"]), "follow_ups": r["follow_ups"]}
        part |= {k: r[k] for k in META_FIELDS if k in r}
        part = old_terms(part)
        assert "copied_from_turn" in json.dumps(part)  # really the generator's vocabulary
        (parts / f"{r['id']}.json").write_text(json.dumps(part, indent=1))

    audit = run(DS / "audit_parts.py", parts, "--variant", "nogrounding", "--quiet")
    assert "DIRTY 0" in audit.stdout, audit.stdout[-1000:]
    out = tmp_path / "out.jsonl"
    ids = ",".join(str(int(r["id"])) for r in rows(shipped))  # the workflows' own assembly command
    r = run(DS / "assemble_dataset.py", "--parts", parts, "--out", out, "--clean", ids)
    assert r.returncode == 0, r.stdout[-1000:] + r.stderr[-1000:]
    assert out.read_bytes() == shipped.read_bytes()


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
    for lang in LANGS:
        name = f"evoweb_benchmark_{lang}.jsonl"
        assert filecmp.cmp(tmp_path / name, MULTILINGUAL / name, shallow=False), (
            f"{name} not byte-identical"
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
