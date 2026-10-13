#!/usr/bin/env python3
"""M2's method applied to n-grams: cross-app overlap of INVENTED PHRASING.

Two existing measures each give up something:

  M2 (cross-app sameness)  subtracts each app's base prompt and uses a graded Jaccard on equal-sized
                           sets -- but on single words, so word ORDER is discarded.
  self-rep n-grams         keeps order, but is a BINARY "shares any n-gram" indicator on raw text
                           with no base subtraction, which saturates at 100% for n<=2 because every
                           app shares some word with some other app.

This takes M2's three good properties and applies them to n-grams:

  1. BASE SUBTRACTION. Remove every n-gram that already appears in the app's own base prompt, so what
     remains is phrasing the generator INVENTED. Without this the measure is dominated by shared
     domain wording, which is exactly what saturates the binary version.
  2. GRADED, not binary. Mean pairwise Jaccard between apps' invented-n-gram sets: what SHARE of
     invented phrasing is common, not merely whether any is.
  3. EQUAL SET SIZE. Jaccard is size-dependent, so each app contributes its first K invented n-grams
     in order of first appearance. K is chosen per n as the largest value every app in both arms can
     supply, and is reported.

No stoplist -- removing stopwords would break the contiguity that makes an n-gram an n-gram. That is
the one respect in which n=1 here differs from M2 proper (M2 is on stoplisted content words).

Paired per-app bootstrap plus exact sign test over the 30 apps, the same test as M1/M2.

Usage: python3 invented_ngram_overlap.py [--json <ARTIFACTS>/invented_ngram_overlap.json]
"""

from __future__ import annotations

import argparse
import json
import os
import statistics as st

import ablation_lib as L

_HERE = os.path.dirname(os.path.abspath(__file__))
NS = [1, 2, 3, 4, 5, 6, 7, 8]


def invented(app_texts, base, n):
    """Ordered n-grams of the ladder that do NOT occur in this app's own base prompt.

    Subtracting the base is what makes this a measure of INVENTED phrasing: every arm describes the
    same apps, so without it the metric is dominated by shared domain wording.
    """
    bset = set(L.ngrams_in_order(base, n))
    return [g for g in L.ngrams_in_order(" ".join(app_texts), n) if g not in bset]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", default=os.path.join(L.ARTIFACTS, "invented_ngram_overlap.json"))
    ap.add_argument("--iters", type=int, default=4000)
    a = ap.parse_args()

    BASE = L.base_prompts()
    arms = {
        "control": L.instructions("control"),
        "no_grounding": L.instructions("no_grounding_fable"),
    }
    apps = sorted(set(arms["control"]) & set(arms["no_grounding"]))
    print(f"{len(apps)} apps · invented n-gram overlap (M2's method, applied to n-grams)\n")

    result = {"n_apps": len(apps), "per_n": {}}
    print(
        f"{'n':>3}{'K':>7}{'grounded':>11}{'ungrounded':>12}{'Δ':>10}{'Δ%':>9}"
        f"   95% CI              apps     p"
    )
    print("-" * 100)
    for n in NS:
        inv = {arm: {app: invented(arms[arm][app], BASE[app], n) for app in apps} for arm in arms}
        K = min(len(v) for arm in inv for v in inv[arm].values())
        sets = {arm: {app: set(inv[arm][app][:K]) for app in apps} for arm in inv}

        per = {}
        for arm in sets:
            per[arm] = {}
            for i in apps:
                others = [sets[arm][j] for j in apps if j != i]
                s = sets[arm][i]
                per[arm][i] = st.mean(len(s & o) / len(s | o) for o in others)
        diffs = [per["no_grounding"][i] - per["control"][i] for i in apps]
        lo, hi = L.bootstrap_ci(diffs, a.iters)
        up, nn, p = L.sign_test(diffs)
        base_lvl = st.mean(per["control"].values())
        ng_lvl = st.mean(per["no_grounding"].values())
        sep = (lo > 0) == (hi > 0)
        result["per_n"][n] = {
            "K": K,
            "control": base_lvl,
            "no_grounding": ng_lvl,
            "mean_diff": st.mean(diffs),
            "ci": [lo, hi],
            "apps_more_alike": up,
            "n": nn,
            "p": p,
            "separated": sep,
        }
        print(
            f"{n:>3}{K:>7}{base_lvl:>11.5f}{ng_lvl:>12.5f}{st.mean(diffs):>+10.5f}"
            f"{st.mean(diffs) / base_lvl * 100:>+8.2f}%   [{lo:+.5f},{hi:+.5f}]{'*' if sep else ' '}"
            f"  {up:>2}/{nn}  p={p:.4f}"
        )

    with open(a.json, "w") as fh:
        json.dump(result, fh, indent=1)
        fh.write("\n")
    print(
        f"\n* = 95% CI excludes zero.  K = invented n-grams per app (equal across arms)."
        f"\nwrote {a.json}"
    )


if __name__ == "__main__":
    main()
