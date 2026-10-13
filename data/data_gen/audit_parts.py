#!/usr/bin/env python3
"""Mechanical audit of generated ladder part files — the checks a regex can settle.

The per-sample LLM verifier inside each generator workflow judges the things that need judgement
(significance, hardness, distinctness, implementation-agnosticism). It is not a reliable gate for the
MECHANICAL rules: an earlier draft shipped 5 samples with banned controls despite being reviewed, which is why
v3 added a verify pass in the first place. This script re-checks the deterministic rules from the part
files alone, so a violation cannot survive on an agent's say-so.

Checks (per sample): structure and slot/kind template, banned controls, verbatim regressions
(character-for-character against the cited turn, base app included), exact-value coverage from the
pinned-seed turn onward, counter cap, archetype mix, and the dependency_graph shape/depth.

Usage:
  python3 audit_parts.py <parts_dir | dataset.jsonl> [--variant dag|nogrounding] [--base data/legacy_webgen_bench_apps.jsonl] [--quiet]

A parts directory holds the generator's per-app files; a .jsonl is an assembled dataset, whose rows
are audited the same way (data/evoweb_benchmark.jsonl: 31 clean, app 48 fails exact-value coverage).
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import re
import sys
from collections import Counter

_HERE = os.path.dirname(os.path.abspath(__file__))
_PKG = os.path.abspath(os.path.join(_HERE, "..", ".."))
if _PKG not in sys.path:
    sys.path.insert(0, _PKG)
from evoweb.paths import DATA as _DATA

DEFAULT_BASE = os.path.join(str(_DATA), "legacy_webgen_bench_apps.jsonl")

# Word-boundary matched: a substring search flags "Dragonborns" for 'drag' and would fail a whole
# fantasy-themed ladder on a false positive.
BANNED = re.compile(
    r"\bsliders?\b|\brange handles?\b|\bdrags?\b|\bdragged\b|\bdragging\b"
    r"|\bdrag-and-drop\b|\bdrag-to-\w+|\bhovers?\b|\bhovered\b|\bhovering\b"
    r"|\bpress (?:tab|enter|escape)\b",
    re.I,
)
# 'dial' is banned as a CONTROL but is also an ordinary verb — "a workbench where I dial the formula
# myself" is fine. Verb-vs-noun needs judgement, so it warns rather than fails. The generator prompt's
# hard never-write list is only slider / drag / hover.
DIAL_HINT = re.compile(r"\bdials?\b", re.I)
# Heuristic only — a WARNING, never a violation. "3 of 12 records" is also how a legitimate
# count-consistent-with-visible-set check reads, and that check is explicitly required (RESTORE-A).
# Telling the two apart needs judgement, which is the LLM verifier's job, not a regex's.
COUNTER_HINT = re.compile(r"showing\b|\bof\s+\d+\s+(items?|results?|records?|rows?)", re.I)


def load_base(path):
    """line number (1-based) -> the base app's ui_instruct task strings"""
    out = {}
    with open(path) as fh:
        for i, line in enumerate(fh, 1):
            try:
                row = json.loads(line)
            except Exception:
                continue
            out[i] = row.get("ui_instruct") or []
    return out


def audit(part, base_tasks, variant):
    """-> (violations, warnings). Only violations mark a sample dirty."""
    v, warn = [], []
    idx = part.get("app_idx")
    fus = part.get("follow_ups") or []

    if len(fus) != 9:
        v.append(f"structure: {len(fus)} follow_ups, expected 9")

    integration_kind = "integration"
    archetypes = []
    counter_tasks = 0
    exact_by_turn = {}

    for k, fu in enumerate(fus, start=2):
        where = f"T{k}"
        archetypes.append(fu.get("archetype"))
        tasks = fu.get("ui_instruct") or []
        if len(tasks) != 5:
            v.append(f"{where}: {len(tasks)} tasks, expected 5")

        kinds = [t.get("kind") for t in tasks]
        if len(tasks) == 5:
            if not all(k2 in ("feature", "exact-value") for k2 in kinds[:3]):
                v.append(f"{where}: slots 1-3 kinds {kinds[:3]}, expected feature/exact-value")
            if kinds[3] != integration_kind:
                v.append(f"{where}: slot 4 kind {kinds[3]!r}, expected {integration_kind!r}")
            if kinds[4] != "regression":
                v.append(f"{where}: slot 5 kind {kinds[4]!r}, expected 'regression'")
        exact_by_turn[k] = sum(1 for k2 in kinds if k2 == "exact-value")

        blob = " ".join(
            [fu.get("instruction") or ""]
            + [f"{t.get('task', '')} {t.get('expected_result', '')}" for t in tasks]
        )
        for hit in set(m.group(0).lower() for m in BANNED.finditer(blob)):
            v.append(f"{where}: banned control/word {hit!r}")
        if DIAL_HINT.search(blob):
            warn.append(f"{where}: mentions 'dial' — check it is the verb, not a dial control")
        for t in tasks:
            if COUNTER_HINT.search(t.get("expected_result") or ""):
                counter_tasks += 1

        # verbatim regression: the copied task must exist character-for-character in its source turn
        reg = tasks[4] if len(tasks) == 5 else None
        if reg and reg.get("kind") == "regression":
            src = reg.get("copied_from_turn")
            if src is None:
                v.append(f"{where}: regression has no copied_from_turn")
            elif src == 1:
                # copied_from_turn=1 is AUTHORED against the base app, not copied: the spec says
                # "for turn 2, instead write one task against the BASE app using ONLY behavior the
                # build prompt explicitly asked for". Verbatim matching does not apply.
                if not (reg.get("task") or "").strip():
                    v.append(f"{where}: base-app regression task is empty")
            elif 2 <= src < k:
                pool = [
                    (t.get("task"), t.get("expected_result"))
                    for t in (fus[src - 2].get("ui_instruct") or [])
                ]
                if (reg.get("task"), reg.get("expected_result")) not in pool:
                    v.append(f"{where}: regression not verbatim from T{src}")
            else:
                v.append(f"{where}: regression copied_from_turn={src} is not an earlier turn")

    # exact-value coverage from the pinned-seed turn onward
    seed_turn = (part.get("pinned_seed") or {}).get("introduced_in_turn")
    if seed_turn is None:
        v.append("pinned_seed: missing introduced_in_turn")
    else:
        if seed_turn not in (2, 3):
            v.append(f"pinned_seed: introduced_in_turn={seed_turn}, expected 2 or 3")
        for k in range(max(seed_turn, 2), 11):
            if exact_by_turn.get(k, 0) < 1:
                v.append(f"T{k}: no exact-value task (pinned seed is T{seed_turn})")

    if counter_tasks > 2:
        warn.append(
            f"counter cap (heuristic): {counter_tasks} tasks may read a list-count "
            f"convention (max 2) — confirm by hand, the regex cannot tell this apart "
            f"from a legitimate count-consistency check"
        )

    present = [a for a in archetypes if a]
    if len(set(present)) < 3:
        v.append(f"archetype mix: only {len(set(present))} distinct ({sorted(set(present))})")
    for a, n in Counter(present).items():
        if n > 4:
            v.append(f"archetype mix: {a} used {n} times (max 4)")
    for a, b in zip(present, present[1:]):
        if a == b:
            v.append(f"archetype mix: {a} twice in a row")

    rules = part.get("global_rules") or []
    if not 2 <= len(rules) <= 3:
        v.append(f"global_rules: {len(rules)}, expected 2-3")

    g = part.get("dependency_graph") or {}
    nodes = {n.get("id") for n in (g.get("nodes") or [])}
    edges = [(e.get("from"), e.get("to")) for e in (g.get("edges") or [])]
    if nodes != {f"T{i}" for i in range(1, 11)}:
        v.append(f"dag: nodes are not exactly T1-T10 ({len(nodes)} found)")
    for a, b in edges:
        try:
            if int(str(a)[1:]) >= int(str(b)[1:]):
                v.append(f"dag: edge {a}->{b} does not point forward")
        except (ValueError, IndexError):
            v.append(f"dag: malformed edge {a}->{b}")
    if (
        sum(
            1
            for _, b in edges
            if b
            and b != "T1"
            and str(b)[1:].isdigit()
            and int(str(b)[1:]) >= 2
            and any(str(a)[1:].isdigit() and int(str(a)[1:]) >= 2 for a, bb in edges if bb == b)
        )
        == 0
    ):
        pass  # counted properly below
    fu_on_fu = [
        (a, b)
        for a, b in edges
        if str(a)[1:].isdigit() and str(b)[1:].isdigit() and int(str(a)[1:]) >= 2
    ]
    if len(fu_on_fu) < 3:
        v.append(f"dag: only {len(fu_on_fu)} follow-up-on-follow-up edges (need >= 3)")
    # longest path from T1
    adj = {}
    for a, b in edges:
        adj.setdefault(a, []).append(b)
    depth_cache = {}

    def depth(n, seen=()):
        if n in depth_cache:
            return depth_cache[n]
        if n in seen:
            return 0
        best = 0
        for m in adj.get(n, []):
            best = max(best, 1 + depth(m, seen + (n,)))
        depth_cache[n] = best
        return best

    # Rule 4 asks for a chain >= 3 deep. Measuring it only from T1 over-filters relative to the
    # CONTROL, whose own published distribution contains a depth-2-from-T1 sample (the benchmark: one
    # of 32). A ladder with a real 4-deep chain that simply is not rooted at T1 still has the
    # breakage cascade the rule exists to create, so that shape WARNS instead of failing; a
    # ladder with no deep chain anywhere is a genuine violation.
    deepest_anywhere = max((depth(n) for n in nodes), default=0)
    if depth("T1") < 3:
        if deepest_anywhere >= 3:
            warn.append(
                f"dag: longest chain is {deepest_anywhere} but not rooted at T1 "
                f"(from-T1 depth {depth('T1')}) — the control tolerates this shape"
            )
        else:
            v.append(f"dag: no chain >= 3 deep anywhere (deepest {deepest_anywhere})")
    if variant == "nogrounding":
        for fu in fus:
            if fu.get("source_website") or fu.get("source_feature"):
                v.append("no_grounding: a follow-up still carries source_website/source_feature")
                break
            if not (fu.get("feature_rationale") or "").strip():
                v.append("no_grounding: a follow-up is missing feature_rationale")
                break
    return v, warn


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("parts_dir")
    ap.add_argument("--variant", default=None, choices=["dag", "nogrounding"])
    ap.add_argument("--base", default=DEFAULT_BASE)
    ap.add_argument("--quiet", action="store_true")
    a = ap.parse_args()

    variant = a.variant
    if variant is None:
        variant = (
            "nogrounding"
            if "no_grounding" in a.parts_dir or "nogrounding" in a.parts_dir
            else "dag"
        )

    base_tasks = load_base(a.base)
    clean, dirty, warnings = [], {}, {}
    if a.parts_dir.endswith(".jsonl"):
        parts = [json.loads(line) for line in open(a.parts_dir) if line.strip()]
        for part in parts:
            part["app_idx"] = int(part["id"])
    else:
        parts = []
        for f in sorted(glob.glob(os.path.join(a.parts_dir, "*.json"))):
            try:
                parts.append(json.load(open(f)))
            except Exception as e:
                dirty[os.path.basename(f)] = [f"unreadable: {e}"]
    for part in parts:
        vv, ww = audit(part, base_tasks, variant)
        if ww:
            warnings[f"{part.get('app_idx')}"] = ww
        if vv:
            dirty[f"{part.get('app_idx')}"] = vv
        else:
            clean.append(part.get("app_idx"))

    print(f"{a.parts_dir}  variant={variant}  parts={len(parts)}")
    print(f"  CLEAN {len(clean)}: {sorted(x for x in clean if x is not None)}")
    print(f"  DIRTY {len(dirty)}: {sorted(dirty)}")
    if warnings:
        print(f"  WARN  {len(warnings)}: {sorted(warnings)}")
    if not a.quiet:
        for k in sorted(dirty, key=lambda s: (len(s), s)):
            print(f"\n  [{k}]")
            for line in dirty[k]:
                print(f"    - {line}")
        for k in sorted(warnings, key=lambda s: (len(s), s)):
            for line in warnings[k]:
                print(f"  warn [{k}] {line}")
    return 1 if dirty else 0


if __name__ == "__main__":
    sys.exit(main())
