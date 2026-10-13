#!/usr/bin/env python3
"""Unpack a full-trace run from examples_artifacts/full_traces/ and print its Grade and Survival.

    python3 -m evoweb.score_zip fable-5-run1

The zip is unpacked into runs/<run-id>/ (kept, so you can read the conversations), scored with
the Table 2 functions in `evoweb.metrics`, and printed next to the released scores of the same
run in examples_artifacts/traces.zip. The two rows must agree: the archive holds the same verdicts plus everything
the agent and the judge said and wrote.
"""

from __future__ import annotations

import argparse
import os
import sys
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def unpack(run_id: str, into: Path) -> Path:
    zp = ROOT / "examples_artifacts" / "full_traces" / f"{run_id}.zip"
    if not zp.is_file():
        sys.exit(f"no {zp}")
    target = into / run_id
    if target.is_dir():
        return target
    into.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zp) as z:
        assert all(n.startswith(run_id + "/") for n in z.namelist()), zp
        z.extractall(into)
    print(f"unpacked to {target}")
    return target


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("run_id", help="e.g. fable-5-run1 (a path to the zip also works)")
    ap.add_argument(
        "--into", type=Path, default=ROOT / "runs", help="where to unpack (default runs/)"
    )
    a = ap.parse_args()
    run_id = Path(a.run_id).name.removesuffix(".zip")
    target = unpack(run_id, a.into)

    from evoweb import paths

    released = paths.ensure_traces() / run_id

    # Score the unpacked run and the released copy through one TRACES directory of links.
    with tempfile.TemporaryDirectory() as tmp:
        os.environ["EVOWEB_TRACES"] = tmp
        (Path(tmp) / run_id).symlink_to(target.resolve(), target_is_directory=True)
        ids = [run_id]
        if released.is_dir():
            (Path(tmp) / f"{run_id} (released)").symlink_to(released, target_is_directory=True)
            ids.append(f"{run_id} (released)")

        import importlib

        from evoweb import metrics

        importlib.reload(paths)
        importlib.reload(metrics)
        exp = metrics.expected_tasks()
        print("| Run | Grade | Survival | Turns / request | $ / sample |")
        print("|---|---|---|---|---|")
        rows = []
        for rid in ids:
            m = metrics.arm_metrics([rid], exp)["runs"][0]
            rows.append(m)
            cost = "n/a" if m["cost_per_sample"] is None else f"{m['cost_per_sample']:.2f}"
            print(
                f"| {rid} | {m['grade']:.3f} | {m['survival']:.2f} | "
                f"{m['turns_per_request']:.1f} | {cost} |"
            )
        if len(rows) == 2 and (rows[0]["grade"], rows[0]["survival"]) != (
            rows[1]["grade"],
            rows[1]["survival"],
        ):
            sys.exit("archive and released scores differ")


if __name__ == "__main__":
    main()
