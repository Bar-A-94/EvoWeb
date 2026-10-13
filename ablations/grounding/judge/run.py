"""Blind pairwise judge: are grounded follow-up requests preferred over ungrounded ones?

One call = one app, one question, one label order. Only the request text is sent; the arms
carry different metadata fields, so anything else would identify them. Appends to calls.jsonl
and skips work already done, so re-running resumes.

See README.md for invocation.
"""

import json
import os
import random
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import requests

D = os.path.dirname(os.path.abspath(__file__))
_PKG = os.path.abspath(os.path.join(D, "..", "..", ".."))
if _PKG not in sys.path:
    sys.path.insert(0, _PKG)
from evoweb.paths import DATA, ensure_data  # noqa: E402

ARMS = {
    "grounded": "evoweb_benchmark.jsonl",
    "ungrounded": "ablation_no_grounding.jsonl",
}
A, B = os.environ.get("ARMS", "grounded:ungrounded").split(":")
MODEL = os.environ.get("JUDGE_MODEL", "openai/gpt-5.6-sol")
FOCUS = os.environ.get("FOCUS", "")
DROP = [x for x in os.environ.get("DROP", "").split(",") if x]
OUT = os.environ.get("OUT", f"{D}/calls.jsonl")
SEED = 20260812

QUESTIONS = {
    "realism": "Which set asks for features you would actually find on a mature, real-world website in this category?",
    "diversity_coverage": "Which set covers a wider variety of distinct capabilities, touching more different parts of the application rather than circling the same kind of change?",
    "diversity_repetition": "Which set is less repetitive, meaning the nine requests differ more from one another in what they actually ask the app to do?",
    "quality": "Which set is higher quality?",
    "choice": "You have to pick one set to use as the follow-up requests for building this app out. Which set do you pick?",
}
ASK = [q for q in os.environ.get("QUESTIONS", "realism").split(",") if q]
WINDOW = {
    "early": "requests 1 to 3",
    "mid": "requests 4 to 6",
    "late": "requests 7 to 9",
    "tail3": "the last three requests",
}  # tail3 is for use with DROP, where 7-9 may not exist

SYSTEM = """You judge candidate follow-up requests for web applications. You see the original build prompt for an app, then two sets of follow-up requests a user might send afterwards. The sets come from two different generation methods; you are not told which is which and the order is randomised. Judge only the text shown, using this rubric.

What counts as a feature a real site would have:
- a capability you would expect on a mature, widely used product in this category, the common-sense core of that kind of site, plus the depth such a product accumulates
- it fits the domain and the audience the build prompt describes, consumer-facing vs internal admin
- it is something real users of that product would need, not a demo, toy or novelty mechanic

What counts as higher quality, when that is the question:
- implementable and internally consistent with the app described so far
- the requests build on each other rather than repeating or contradicting
- specific enough to act on, without inventing constraints a real user would not state

Explicitly NOT criteria, ignore them in every judgement:
- writing style, tone, register, or how much it sounds like a person typing
- length, level of detail, or the presence of exact values, seeded data and numbers
- the order the sets are shown in

Reply with JSON only: {"winner":"A"|"B"|"tie","confidence":1-5,"reason":"at most two sentences"}. Use "tie" only when the two sets are genuinely indistinguishable on the question asked."""


def load(arm):
    ensure_data(DATA / ARMS[arm])
    rows = {r["id"]: r for r in map(json.loads, open(DATA / ARMS[arm], encoding="utf-8"))}
    if DROP:
        for r in rows.values():
            r["follow_ups"] = [f for f in r["follow_ups"] if f.get("archetype") not in DROP]
    return rows


def render(t1, first, second, question):
    block = lambda label, fus: f"SET {label} - {len(fus)} follow-up requests:\n" + "\n".join(
        f"{n}. {f['instruction'].strip()}" for n, f in enumerate(fus, 1)
    )
    return (
        f"ORIGINAL BUILD PROMPT (turn 1):\n{t1.strip()}\n\n{block('A', first)}\n\n{block('B', second)}\n\n"
        f"QUESTION: {question}\n"
        + (f"Judge ONLY {WINDOW[FOCUS]} in each set. The rest are context.\n" if FOCUS else "")
        + "\nJSON only."
    )


def ask(key, prompt, tries=3):
    """A reply we cannot parse is asked again, never scored."""
    msgs = [{"role": "system", "content": SYSTEM}, {"role": "user", "content": prompt}]
    for attempt in range(tries):
        try:
            body = requests.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers={"Authorization": f"Bearer {key}"},
                json={
                    "model": MODEL,
                    "messages": msgs,
                    "reasoning": {"effort": "high"},
                    "usage": {"include": True},
                },
                timeout=300,
            ).json()
            msg = body["choices"][0]["message"]
            txt = msg["content"].strip()
            v = json.loads(txt[txt.find("{") : txt.rfind("}") + 1])
            # models answer "CORPUS A" as often as "A"; take the trailing token rather than
            # rejecting, which used to cost a retry and could have silently dropped verdicts
            w = str(v.get("winner", "")).strip().upper()
            v["winner"] = "tie" if "TIE" in w else w[-1:] if w[-1:] in ("A", "B") else w
            if v["winner"] not in ("A", "B", "tie"):
                raise ValueError(v["winner"])
            u = body.get("usage", {})
            return v, {"cost": u.get("cost"), "reasoning": (msg.get("reasoning") or "").strip()}
        except Exception as e:
            msgs = msgs[:2] + [
                {
                    "role": "user",
                    "content": f"Your reply could not be used ({e}). Resend JSON only.",
                }
            ]
            time.sleep(2 * (attempt + 1))
    return None, {}


def main(limit=0, reps=1):
    a, b = load(A), load(B)
    # >=3 keeps only apps generated in both arms; the excluded ones have no counterpart
    ids = sorted(
        i for i in a if i in b and min(len(a[i]["follow_ups"]), len(b[i]["follow_ups"])) >= 3
    )
    ids = ids[:limit] if limit else ids
    cond = {"comparison": f"{A}_vs_{B}", "model": MODEL, "focus": FOCUS, "drop": ",".join(DROP)}
    done = (
        {
            (r["app"], r["question"], r["order"], r["rep"])
            for r in map(json.loads, open(OUT))
            if r.get("winner") and all(r.get(k) == v for k, v in cond.items())
        }
        if os.path.exists(OUT)
        else set()
    )

    cells = []
    for i in ids:
        for q in ASK:
            flip = random.Random(f"{SEED}:{i}:{q}").random() < 0.5  # stable under any filter
            cells += [
                (i, q, o, flip, rep)
                for o in (0, 1)
                for rep in range(reps)
                if (i, q, o, rep) not in done
            ]
    print(f"{len(ids)} apps, {len(cells)} calls", flush=True)

    key = os.environ["OPENROUTER_API_KEY"]
    lock, fh = threading.Lock(), open(OUT, "a")

    def run(cell):
        i, q, o, flip, rep = cell
        a_first = (o == 0) != flip
        first, second = (a[i], b[i]) if a_first else (b[i], a[i])
        v, meta = ask(
            key,
            render(a[i]["instruction"], first["follow_ups"], second["follow_ups"], QUESTIONS[q]),
        )
        rec = {"app": i, "question": q, "order": o, "rep": rep, **cond, **meta}
        if not v:
            print("FAILED", cell, flush=True)
        else:
            first_won = (
                "tie" if v["winner"] == "tie" else (v["winner"] == ("A" if a_first else "B"))
            )
            rec.update(
                winner=v["winner"],
                confidence=v.get("confidence"),
                reason=v.get("reason"),
                a_won=first_won,
            )
        with lock:
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
            fh.flush()

    with ThreadPoolExecutor(int(os.environ.get("WORKERS", 16))) as ex:
        list(ex.map(run, cells))


if __name__ == "__main__":
    import sys

    main(*(int(x) for x in sys.argv[1:3]))
