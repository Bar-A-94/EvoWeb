#!/usr/bin/env python3
"""Compare your own run of a model with the paper's released runs of the same model (one of
the four Anthropic models in `evoweb.arms.TABLE2`).

    python3 -m evoweb.compare_to_released "Haiku 4.5" runs/my-haiku-r1 [--json out.json]

The run directory must have the released layout (<sample:06d>/result.json, plus
<sample>/turn<N>/generation/model_calls.jsonl for turns and cost). It is scored with exactly
the functions behind Table 2 (`evoweb.metrics`), next to each released run of the model in
`evoweb.arms.TABLE2`, and compared three ways: the Table 2 scalars, the Grade of every app on
its own, and the ungated accuracy of every request index.
"""

from __future__ import annotations

import argparse
import json
import os
import statistics as st
import sys
from pathlib import Path


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("model", help='a Table 2 row name, e.g. "Haiku 4.5"')
    ap.add_argument("run_dir", type=Path, help="your run: <run_dir>/<sample>/result.json")
    ap.add_argument("--json", type=Path, help="also write every number here")
    a = ap.parse_args()

    # Score the fresh run through the same TRACES lookup as the released ones: link it in.
    from evoweb import arms, metrics, paths

    run_dir = a.run_dir.resolve()
    fresh = run_dir.name
    link = paths.ensure_traces() / fresh
    made_link = False
    if not link.exists():
        link.symlink_to(run_dir, target_is_directory=True)
        made_link = True
    elif link.resolve() != run_dir:
        sys.exit(f"{link} exists and is not {run_dir}; rename your run directory")

    try:
        released = arms.TABLE2[a.model]
        ids = released + [fresh]
        exp = metrics.expected_tasks()

        scalars = {}
        for rid in ids:
            m = metrics.arm_metrics([rid], exp)["runs"][0]
            scalars[rid] = {
                k: m[k]
                for k in ("grade", "survival", "turns_per_request", "cost_per_sample", "raw")
            }
        ladders = {rid: metrics.load_ladders(rid) for rid in ids}

        per_app = {}
        for idx in sorted(ladders[fresh]):
            g = {
                rid: metrics.run_scores({idx: ladders[rid][idx]}, {idx: exp[idx]})["grade"]
                for rid in ids
            }
            r = [g[x] for x in released]
            per_app[idx] = {"fresh": g[fresh], "released": r, "min": min(r), "max": max(r)}

        def by_request(lad):
            out = {}
            for t in metrics.TURNS:
                v = [
                    s for s in (metrics.turn_score(b.get(t)) for b in lad.values()) if s is not None
                ]
                out[t] = st.mean(v) if v else None
            return out

        per_request = {rid: by_request(ladders[rid]) for rid in ids}
        errors = [
            (i, t, (b.get(t) or {}).get("error_class"))
            for i, b in ladders[fresh].items()
            for t in metrics.TURNS
            if (b.get(t) or {}).get("status") == "error"
        ]

        rel_grades = [scalars[r]["grade"] for r in released]
        mean, std = st.mean(rel_grades), (st.pstdev(rel_grades) if len(rel_grades) > 1 else 0.0)
        g = scalars[fresh]["grade"]
        inside = sum(1 for p in per_app.values() if p["min"] <= p["fresh"] <= p["max"])

        print(
            "| run | Grade | Survival | Turns / request | $ / sample | RAW % |\n|---|---|---|---|---|---|"
        )
        for rid in ids:
            s = scalars[rid]
            cost = f"{s['cost_per_sample']:.2f}" if s["cost_per_sample"] is not None else "n/a"
            tag = " (yours)" if rid == fresh else ""
            print(
                f"| {rid}{tag} | {s['grade']:.3f} | {s['survival']:.2f} | "
                f"{s['turns_per_request']:.1f} | {cost} | {s['raw']:.1f} |"
            )
        print(
            f"\nreleased Grade {mean:.3f} ± {std:.3f} (population std, n={len(released)}); "
            f"yours {g:.3f} = {(g - mean) / std if std else float('nan'):+.2f} std from the mean"
        )
        print(f"apps whose Grade lies inside the released [min, max]: {inside}/{len(per_app)}")
        print(f"errored requests in your run: {errors or 'none'}")

        if a.json:
            a.json.write_text(
                json.dumps(
                    {
                        "model": a.model,
                        "fresh": fresh,
                        "released": released,
                        "scalars": scalars,
                        "released_grade": {"mean": mean, "std": std},
                        "per_app": per_app,
                        "per_request": per_request,
                        "errors": errors,
                        "apps_inside_range": inside,
                    },
                    indent=1,
                )
                + "\n"
            )
            print("wrote", a.json)
    finally:
        if made_link and os.environ.get("EVOWEB_KEEP_LINK") != "1":
            link.unlink()


if __name__ == "__main__":
    main()
