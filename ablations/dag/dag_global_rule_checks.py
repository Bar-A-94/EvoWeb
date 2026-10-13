#!/usr/bin/env python3
"""Which "integration" checks are really global-rule checks -- detected from the DAG.

Every follow-up request (T2-T10) carries one check of kind `integration` at task_idx 3. The
generator writes that check as a cross-request test only when the request has an incoming
edge in the app's `dependency_graph`; a request with NO incoming edge has nothing earlier to
integrate with, and its slot-3 check instead verifies one of the app's `global_rules`
(formatting, badge colours, sort order, confirmation dialogs). Table 4 excludes those checks
from its integration column.

Rule: a follow-up turn t is a GLOBAL-RULE turn iff no edge in `dependency_graph.edges` has
`to == "T{t}"`. An edge from T1 (the base app) counts as a real dependency.

Usage (from anywhere):
    python3 ablations/dag/dag_global_rule_checks.py            # table of the flagged turns
    python3 ablations/dag/dag_global_rule_checks.py --json     # also write
                                                  # ARTIFACTS/global_rule_checks.json

Importable: `benchmark_rows()` and `global_rule_turns()` (used by dag_slot.py).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))
from evoweb.metrics import benchmark_rows, global_rule_turns, incoming  # noqa: E402, F401
from evoweb.paths import ARTIFACTS  # noqa: E402

INTEGRATION_SLOT = 3


def flagged(rows):
    recs = []
    for i, row in enumerate(rows, start=1):
        for fu_i, fu in enumerate(row["follow_ups"]):
            turn = fu_i + 2
            if incoming(row, turn):
                continue
            chk = fu["ui_instruct"][INTEGRATION_SLOT]
            assert chk["kind"] == "integration", (row["id"], turn, chk["kind"])
            recs.append(
                {
                    "index": i,
                    "id": row["id"],
                    "turn": turn,
                    "task": chk["task"],
                    "expected_result": chk["expected_result"],
                    "global_rules": [g["rule"] for g in row["global_rules"]],
                }
            )
    return recs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true", help="write ARTIFACTS/global_rule_checks.json")
    a = ap.parse_args()

    rows = benchmark_rows()
    recs = flagged(rows)
    n_fu = sum(len(r["follow_ups"]) for r in rows)
    only_t1 = Counter()
    for row in rows:
        for fu_i in range(len(row["follow_ups"])):
            turn = fu_i + 2
            inc = incoming(row, turn)
            if inc and all(e["from"] == "T1" for e in inc):
                only_t1[turn] += 1

    print(f"follow-up requests: {n_fu} ({len(rows)} apps x T2-T10)")
    print(
        f"no incoming DAG edge -> slot-3 check is a GLOBAL RULE check: {len(recs)} "
        f"({len(recs) / n_fu * 100:.1f}%), in {len({r['id'] for r in recs})} apps"
    )
    print("  by turn:", dict(sorted(Counter(r["turn"] for r in recs).items())))
    print(
        f"incoming edge(s) only from T1 (kept as integration): {sum(only_t1.values())}, "
        f"by turn: {dict(sorted(only_t1.items()))}"
    )
    print()
    print("| idx | app | turn | slot-3 check (expected result) |")
    print("|---|---|---|---|")
    for r in recs:
        print(f"| {r['index']} | {r['id']} | T{r['turn']} | {r['expected_result'][:110]} |")

    if a.json:
        ARTIFACTS.mkdir(parents=True, exist_ok=True)
        out = ARTIFACTS / "global_rule_checks.json"
        out.write_text(json.dumps(recs, indent=1) + "\n")
        print(f"\nwrote {out}")


if __name__ == "__main__":
    main()
