"""Score every condition in calls.jsonl, paired by app.

An app's score is the mean of the two label orders, so position bias cancels exactly.
Confidence ranges are a bootstrap over apps, which is the unit that actually varies.

See README.md for invocation.
"""

import json
import os
import random
import statistics as st
import sys

D = os.path.dirname(os.path.abspath(__file__))
SCORE = {True: 1.0, False: 0.0, "tie": 0.5}
KEYS = ("comparison", "model", "question", "focus", "drop")
rows = [r for r in map(json.loads, open(f"{D}/calls.jsonl")) if r.get("winner")]


def boot(v, n=20000):
    rng = random.Random(7)
    m = sorted(st.mean(rng.choices(v, k=len(v))) for _ in range(n))
    return m[int(0.025 * n)], m[int(0.975 * n)]


def per_app(cond):
    """cond -> {app: score}, score above 0.5 favouring the first arm."""
    out = {}
    for r in rows:
        if all(r.get(k) == v for k, v in cond.items()):
            out.setdefault(r["app"], {0: [], 1: []})[r["order"]].append(SCORE[r["a_won"]])
    return {a: st.mean([st.mean(x) for x in o.values()]) for a, o in out.items() if all(o.values())}


def label(c):
    bits = [c["model"].split("/")[-1], c["question"]]
    bits += [c["focus"] or "all requests"] + (["no " + c["drop"]] if c["drop"] else [])
    return " / ".join(bits)


def summarise():
    conds, results = {tuple(r.get(k) for k in KEYS) for r in rows}, []
    for c in sorted(conds):
        cond = dict(zip(KEYS, c))
        s = per_app(cond)
        lo, hi = boot(list(s.values()))
        results.append(
            {
                **cond,
                "apps": len(s),
                "pct": 100 * st.mean(s.values()),
                "ci": [100 * lo, 100 * hi],
                "separated": lo > 0.5 or hi < 0.5,
            }
        )
    results.sort(key=lambda r: (r["comparison"], r["question"], -r["pct"]))
    for n, r in enumerate(results):
        print(
            f"{n:3} {label(r):60}{r['pct']:6.1f}  [{r['ci'][0]:5.1f},{r['ci'][1]:5.1f}]"
            f"{'  clear' if r['separated'] else ''}"
        )
    json.dump(results, open(f"{D}/results.json", "w"), indent=1)


def compare(i, j):
    """Two conditions differ only if the PAIRED difference excludes zero. Comparing one
    'significant' number against one 'not significant' number is not the same test."""
    res = json.load(open(f"{D}/results.json"))
    a, b = (per_app({k: res[int(x)][k] for k in KEYS}) for x in (i, j))
    apps = sorted(set(a) & set(b))
    d = [a[x] - b[x] for x in apps]
    lo, hi = boot(d)
    print(
        f"{label(res[int(i)])}\n  minus {label(res[int(j)])}\n"
        f"  {100 * st.mean(d):+.1f} pts [{100 * lo:+.1f},{100 * hi:+.1f}] over {len(apps)} apps"
    )


if __name__ == "__main__":
    compare(*sys.argv[1:3]) if len(sys.argv) > 2 else summarise()
