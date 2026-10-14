#!/usr/bin/env python3
"""Deterministic checks on the translation parts, per app x language.

The translation is trusted only where a machine can verify it:
- structure: instructions "1".."10" present and non-empty, task_edits indices valid
- language: zh/he/hi instructions are mostly target-script; de/fr carry target stopwords
- invariants: every $-amount, decimal, percentage and signed American odds in an EN
  instruction/task survives byte-identical in its translation; every class=="keep"
  anchor (brands, teams, tickers, CSS color keywords, URLs) survives wherever its
  exact form appears within its declared requests
- anchors: every class=="translate" anchor's canonical translation appears in the
  translated instruction of each declared request whose EN instruction uses the label
- task edits: tasks stay English; an edit exists for EVERY task whose EN text uses a
  translate anchor's exact form (nothing missed), carries both the translated anchor
  and the EN gloss, and leaks no target-script text beyond the anchor substitutions

Anchor detection is the exact label form at word boundaries, case-sensitive, and only
inside the anchor's declared "requests" — prose that happens to reuse a label's word in
lowercase ("the three weights", "a value equal to") is the translator's judgment, not
a hard requirement; raw substring matching drowned real checks in false positives
('Core' inside "score", 'navy' re-described by hex in the restyle request).

Errors fail the run (exit 1); warnings are printed for review.

Usage: python3 validate_parts.py [--enui] [app_id ...]   (default: every app with anchors.json)

--enui checks the English-UI variant (<lang>_enui.json) instead: translated instructions
with every anchor kept in English and no task edits — see check_app_enui.
"""

import json
import re
import sys
from pathlib import Path

ML = Path(__file__).resolve().parent
sys.path.insert(0, str(ML.parents[2]))
from evoweb.paths import LANGS  # noqa: E402

PARTS = ML / "parts"
SCRIPT_RANGES = {"zh": (0x4E00, 0x9FFF), "he": (0x0590, 0x05FF), "hi": (0x0900, 0x097F)}
STOPWORD_HINTS = {
    "de": ["der", "die", "das", "und", "mit", "ein", "eine", "jede", "alle", "soll"],
    "fr": ["le", "la", "les", "des", "une", "pour", "avec", "que", "chaque", "doit"],
}
# $-amounts, decimals, percentages, signed American odds — the literals tasks verify.
NUM_RE = re.compile(
    r"\$\d[\d,]*(?:\.\d+)?|\b\d+\.\d+\b|\b\d+(?:\.\d+)?%|(?<![\w\d.$])[+-]\d{2,4}\b"
)
MIN_LEN_RATIO = {"zh": 0.15, "he": 0.4, "hi": 0.4, "de": 0.5, "fr": 0.5}


def en_requests(row) -> dict[int, str]:
    out = {1: row["instruction"]}
    for i, f in enumerate(row.get("follow_ups", []), start=2):
        out[i] = f["instruction"]
    return out


def en_tasks(row) -> dict[int, list[dict]]:
    out = {1: row["ui_instruct"]}
    for i, f in enumerate(row.get("follow_ups", []), start=2):
        out[i] = f["ui_instruct"]
    return out


def uses(anchor_en: str, text: str) -> bool:
    """Exact label form at word boundaries, case-sensitive."""
    return re.search(rf"(?<!\w){re.escape(anchor_en)}(?!\w)", text) is not None


def anchor_requests(a: dict) -> set[int]:
    return set(a.get("requests") or range(1, 11))


def script_ratio(text: str, lang: str) -> float:
    lo, hi = SCRIPT_RANGES[lang]
    alpha = [c for c in text if c.isalpha()]
    if not alpha:
        return 0.0
    return sum(lo <= ord(c) <= hi for c in alpha) / len(alpha)


def has_stopwords(text: str, lang: str, n: int = 2) -> bool:
    words = set(re.findall(r"[a-záéíóúñü]+", text.lower()))
    return len(words & set(STOPWORD_HINTS[lang])) >= n


def check_app(app: str) -> tuple[list[str], list[str]]:
    errors, warnings = [], []
    d = PARTS / app
    row = json.loads((d / "en.json").read_text(encoding="utf-8"))
    requests, tasks = en_requests(row), en_tasks(row)
    corpus = (
        "\n".join(requests.values())
        + "\n"
        + "\n".join(t["task"] + "\n" + t["expected_result"] for ts in tasks.values() for t in ts)
    )

    anchors = json.loads((d / "anchors.json").read_text(encoding="utf-8"))["anchors"]
    xlate = [a for a in anchors if a["class"] == "translate"]
    keep = [a for a in anchors if a["class"] == "keep"]
    for a in anchors:
        if a["class"] not in ("translate", "keep"):
            errors.append(f"anchors: bad class {a['class']!r} for {a['en']!r}")
        if a["en"].lower() not in corpus.lower():
            warnings.append(f"anchors: {a['en']!r} not found in EN corpus (hallucinated?)")
        if a["class"] == "translate":
            missing = [g for g in LANGS if not (a.get("translations") or {}).get(g)]
            if missing:
                errors.append(f"anchors: {a['en']!r} missing translations {missing}")

    for lang in LANGS:
        f = d / f"{lang}.json"
        if not f.is_file():
            errors.append(f"{lang}: file missing")
            continue
        part = json.loads(f.read_text(encoding="utf-8"))
        instr = part.get("instructions", {})
        for t in range(1, 11):
            src, dst = requests[t], instr.get(str(t), "")
            tag = f"{lang} R{t}"
            if not dst:
                errors.append(f"{tag}: instruction missing/empty")
                continue
            if len(dst) < MIN_LEN_RATIO[lang] * len(src):
                errors.append(f"{tag}: suspiciously short ({len(dst)} vs EN {len(src)} chars)")
            if lang in SCRIPT_RANGES:
                r = script_ratio(dst, lang)
                if r < 0.4:
                    errors.append(f"{tag}: only {r:.0%} target-script letters")
            elif not has_stopwords(dst, lang):
                errors.append(f"{tag}: no {lang} stopwords — not translated?")
            for lit in NUM_RE.findall(src):
                if lit not in dst:
                    errors.append(f"{tag}: numeric literal {lit!r} lost")
            for a in keep:
                if t in anchor_requests(a) and uses(a["en"], src) and a["en"] not in dst:
                    # colors are pinned visually (and by hex, which NUM-like checks keep);
                    # losing the keyword in a request that re-describes them is reviewable, not fatal
                    (warnings if a.get("kind") == "css_visual" else errors).append(
                        f"{tag}: keep-anchor {a['en']!r} lost"
                    )
            for a in xlate:
                if (
                    t in anchor_requests(a)
                    and uses(a["en"], src)
                    and a["translations"][lang].casefold() not in dst.casefold()
                ):
                    errors.append(
                        f"{tag}: translate-anchor {a['en']!r} -> {a['translations'][lang]!r} absent"
                    )

        # --- task edits ---
        edits = {(e["request"], e["task_index"]): e for e in part.get("task_edits", [])}
        for (t, i), e in edits.items():
            tag = f"{lang} R{t} task{i}"
            if t not in tasks or not 0 <= i < len(tasks[t]):
                errors.append(f"{tag}: no such task")
                continue
            src_t = tasks[t][i]
            for field in ("task", "expected_result"):
                src, dst = src_t[field], e.get(field, "")
                if not dst:
                    errors.append(f"{tag}: {field} empty")
                    continue
                for lit in NUM_RE.findall(src):
                    if lit not in dst:
                        errors.append(f"{tag}: {field} numeric literal {lit!r} lost")
                for a in keep:
                    if t in anchor_requests(a) and uses(a["en"], src) and a["en"] not in dst:
                        errors.append(f"{tag}: {field} keep-anchor {a['en']!r} lost")
                for a in xlate:
                    if t in anchor_requests(a) and uses(a["en"], src):
                        if a["translations"][lang].casefold() not in dst.casefold():
                            errors.append(f"{tag}: {field} lacks translated {a['en']!r}")
                        if a["en"].casefold() not in dst.casefold():
                            errors.append(f"{tag}: {field} lacks EN gloss for {a['en']!r}")
                if lang in SCRIPT_RANGES:
                    stripped = dst
                    for tr in sorted(
                        {a["translations"][lang] for a in xlate}, key=len, reverse=True
                    ):
                        stripped = stripped.replace(tr, "")
                    lo, hi = SCRIPT_RANGES[lang]
                    leak = "".join(c for c in stripped if lo <= ord(c) <= hi)
                    if leak:
                        errors.append(
                            f"{tag}: {field} target-script text outside anchor substitutions: {leak[:40]!r}"
                        )
        # completeness: every task using a translate anchor's exact form must have an edit
        for t, ts in tasks.items():
            for i, task in enumerate(ts):
                text = task["task"] + " " + task["expected_result"]
                needed = [a["en"] for a in xlate if t in anchor_requests(a) and uses(a["en"], text)]
                if needed and (t, i) not in edits:
                    errors.append(f"{lang} R{t} task{i}: uses {needed} but has no edit")
    return errors, warnings


BIDI_CONTROLS = re.compile("[‎‏‪-‮⁦-⁩]")


def check_app_enui(app: str) -> tuple[list[str], list[str]]:
    """English-UI variant: instructions translated, but EVERY anchor (translate and keep)
    stays in its exact English form and the judge tasks are the EN originals (no edits).

    The language check runs on the instruction with all anchors stripped, since the
    embedded English labels would otherwise drag zh/he/hi under the script threshold."""
    errors, warnings = [], []
    d = PARTS / app
    row = json.loads((d / "en.json").read_text(encoding="utf-8"))
    requests = en_requests(row)
    anchors = json.loads((d / "anchors.json").read_text(encoding="utf-8"))["anchors"]
    for lang in LANGS:
        f = d / f"{lang}_enui.json"
        if not f.is_file():
            errors.append(f"{lang}: {f.name} missing")
            continue
        part = json.loads(f.read_text(encoding="utf-8"))
        if part.get("task_edits"):
            errors.append(f"{lang}: enui variant must not carry task_edits")
        instr = part.get("instructions", {})
        for t in range(1, 11):
            src, dst = requests[t], instr.get(str(t), "")
            tag = f"{lang} enui R{t}"
            if not dst:
                errors.append(f"{tag}: instruction missing/empty")
                continue
            if BIDI_CONTROLS.search(dst):
                errors.append(f"{tag}: contains bidi control characters")
            if len(dst) < MIN_LEN_RATIO[lang] * len(src):
                errors.append(f"{tag}: suspiciously short ({len(dst)} vs EN {len(src)} chars)")
            for lit in NUM_RE.findall(src):
                if lit not in dst:
                    errors.append(f"{tag}: numeric literal {lit!r} lost")
            stripped = dst
            for a in anchors:
                if t in anchor_requests(a) and uses(a["en"], src):
                    if a["en"] not in dst:
                        (warnings if a.get("kind") == "css_visual" else errors).append(
                            f"{tag}: anchor {a['en']!r} must appear in English verbatim"
                        )
                    stripped = stripped.replace(a["en"], " ")
                if (
                    a["class"] == "translate"
                    and a["translations"].get(lang)
                    and a["translations"][lang] in dst
                ):
                    warnings.append(
                        f"{tag}: native translation of {a['en']!r} present — UI names must stay English"
                    )
            if lang in SCRIPT_RANGES:
                r = script_ratio(stripped, lang)
                if r < 0.4:
                    errors.append(f"{tag}: only {r:.0%} target-script letters outside anchors")
            elif not has_stopwords(stripped, lang):
                errors.append(f"{tag}: no {lang} stopwords — not translated?")
    return errors, warnings


if __name__ == "__main__":
    argv = sys.argv[1:]
    enui = True  # only the English-UI variant ships; --enui is accepted and implied
    argv = [a for a in argv if a != "--enui"]
    apps = argv or sorted(p.parent.name for p in PARTS.glob("*/anchors.json"))
    total_err = 0
    for app in apps:
        errors, warnings = (check_app_enui if enui else check_app)(app)
        total_err += len(errors)
        status = "PASS" if not errors else f"FAIL ({len(errors)} errors)"
        print(f"== {app}: {status}, {len(warnings)} warnings")
        for e in errors:
            print("  ERROR", e)
        for w in warnings:
            print("  warn ", w)
    sys.exit(1 if total_err else 0)
