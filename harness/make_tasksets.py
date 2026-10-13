"""Write the smoke subsets of the benchmark (data/evoweb_benchmark.jsonl) into tests/smoke_sets/.

    python3 harness/make_tasksets.py

WAVE is the 32-app EvoWeb set in its row order, which is also the 1-based sample index every
run and every score uses; evoweb_benchmark.jsonl is committed in that order. The smoke sets are
rows of it with the follow-ups trimmed, for runs that cost minutes; they are not committed.
harness/Dockerfile runs this so the image carries them, and run_sample.sh looks for JSONL_FILE
under tests/smoke_sets/ as well as data/.
"""

from __future__ import annotations

import json
from pathlib import Path

WAVE = """000001 000004 000006 000011 000014 000015 000017 000018 000021 000023 000030 000031
000033 000035 000038 000040 000041 000042 000044 000047 000048 000050 000051 000058
000061 000067 000069 000070 000073 000078 000091 000093""".split()
# name -> (apps, user requests per app). The full wave keeps every follow-up; the smaller sets
# trim them so a smoke costs minutes. Adding a set is one row.
SETS = {
    "evoweb_smoke_2apps_3requests.jsonl": (2, 3),
    "evoweb_smoke_3apps_2requests.jsonl": (3, 2),
    # Shortest ladder the HARNESS generators accept, all 32 apps, row order (and therefore
    # --start-idx) identical to evoweb_benchmark.jsonl. For per-app turn-1 experiments: turn 1 is judged
    # exactly as in the full run, at ~2 turns of cost instead of 10.
    # NOT 1 request: run_single_sample rejects a row with no follow_ups for openhands/bash/
    # mini/claude_code ("needs a multi-turn dataset"), so a 1-request set errors out before
    # generating anything. Verified 2026-08-31 on six wasted dispatches.
    "evoweb_2requests.jsonl": (len(WAVE), 2),
}

# Open-source layout: this file lives in PKG/harness/, the datasets in PKG/data/ (sibling of
# harness/). The Dockerfile copies both to /app/harness and /app/data, so the same expression
# resolves inside the image.
ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
SMOKE_DIR = ROOT / "tests" / "smoke_sets"


def taskset(rows: dict[str, str], apps: int, requests: int | None) -> str:
    out = []
    for app in WAVE[:apps]:
        row = json.loads(rows[app])
        if requests is not None:
            # requests counts the build too, so keep one fewer follow-up than requests.
            row["follow_ups"] = (row.get("follow_ups") or [])[: requests - 1]
        out.append(json.dumps(row))
    return "\n".join(out) + "\n"


if __name__ == "__main__":
    rows = {json.loads(line)["id"]: line for line in (DATA / "evoweb_benchmark.jsonl").open()}
    SMOKE_DIR.mkdir(parents=True, exist_ok=True)
    for name, (apps, requests) in SETS.items():
        (SMOKE_DIR / name).write_text(taskset(rows, apps, requests))
        print(f"wrote {apps} rows to {SMOKE_DIR / name} ({requests or 'all'} requests each)")
