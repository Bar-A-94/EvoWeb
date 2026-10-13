#!/usr/bin/env python3
"""Render viewer.html: per app, EN | translated instructions side by side per turn,
plus the task edits, with translate-anchors highlighted. For human review before runs.

Usage: python3 make_viewer.py [app_id ...]   (default: every app with anchors.json)
"""

import html
import json
import sys
from pathlib import Path

ML = Path(__file__).resolve().parent
PARTS = ML / "parts"
LANGS = ["es", "zh", "he", "hi", "sw", "de", "fr"]
RTL = {"he"}

CSS = """
body{font-family:system-ui,sans-serif;margin:16px;background:#fafafa;color:#111}
h2{margin-top:40px;border-bottom:2px solid #333}
h3{margin:24px 0 4px}
table{border-collapse:collapse;width:100%;table-layout:fixed}
td,th{border:1px solid #ccc;padding:6px 8px;vertical-align:top;font-size:13px}
th{background:#eee}
td.rtl{direction:rtl;text-align:right}
mark{background:#ffe08a}
.edit{background:#eef6ff}
.anchor-table td{font-size:12px}
details{margin:8px 0}
"""


def mark_anchors(text: str, needles: list[str]) -> str:
    out = html.escape(text)
    for n in sorted(set(needles), key=len, reverse=True):
        if n:
            out = out.replace(html.escape(n), f"<mark>{html.escape(n)}</mark>")
    return out


def en_turns(row):
    out = {1: row["instruction"]}
    for i, f in enumerate(row.get("follow_ups", []), start=2):
        out[i] = f["instruction"]
    return out


def en_tasks(row):
    out = {1: row["ui_instruct"]}
    for i, f in enumerate(row.get("follow_ups", []), start=2):
        out[i] = f["ui_instruct"]
    return out


def render_app(app: str, enui: bool = False) -> str:
    d = PARTS / app
    row = json.loads((d / "en.json").read_text())
    anchors = json.loads((d / "anchors.json").read_text())["anchors"]
    xlate = [a for a in anchors if a["class"] == "translate"]
    suffix = "_enui" if enui else ""
    parts = {
        g: json.loads((d / f"{g}{suffix}.json").read_text())
        for g in LANGS
        if (d / f"{g}{suffix}.json").is_file()
    }
    turns, tasks = en_turns(row), en_tasks(row)
    # English-UI variant: every anchor stays English, so highlight the EN forms in every column
    needles_for = (
        (lambda g: [a["en"] for a in anchors])
        if enui
        else (lambda g: [a["translations"][g] for a in xlate])
    )

    out = [f"<h2>{app}</h2>"]
    out.append("<details><summary>anchor inventory</summary><table class=anchor-table>")
    out.append(
        "<tr><th>en</th><th>class</th><th>kind</th>"
        + "".join(f"<th>{g}</th>" for g in LANGS)
        + "</tr>"
    )
    for a in anchors:
        tr = a.get("translations") or {}
        out.append(
            f"<tr><td>{html.escape(a['en'])}</td><td>{a['class']}</td><td>{a.get('kind', '')}</td>"
            + "".join(f"<td>{html.escape(tr.get(g, '—'))}</td>" for g in LANGS)
            + "</tr>"
        )
    out.append("</table></details>")

    for t in range(1, 11):
        out.append(
            f"<h3>Turn {t}</h3><table><tr><th>en</th>"
            + "".join(f"<th>{g}</th>" for g in parts)
            + "</tr><tr>"
        )
        out.append(f"<td>{mark_anchors(turns[t], [a['en'] for a in xlate])}</td>")
        for g, p in parts.items():
            cls = " class=rtl" if g in RTL else ""
            out.append(
                f"<td{cls}>{mark_anchors(p['instructions'].get(str(t), ''), needles_for(g))}</td>"
            )
        out.append("</tr></table>")
        if enui:
            continue  # judge tasks are the EN originals — nothing to show
        edits = {
            g: {(e["turn"], e["task_index"]): e for e in p.get("task_edits", [])}
            for g, p in parts.items()
        }
        for i, task in enumerate(tasks[t]):
            if not any((t, i) in edits[g] for g in parts):
                continue
            out.append(f"<table class=edit><tr><th colspan=2>task {i} (edited)</th></tr>")
            out.append(
                f"<tr><td>en</td><td>{html.escape(task['task'])}<br><i>{html.escape(task['expected_result'])}</i></td></tr>"
            )
            for g, p in parts.items():
                e = edits[g].get((t, i))
                if e:
                    needles = [a["translations"][g] for a in xlate]
                    out.append(
                        f"<tr><td>{g}</td><td>{mark_anchors(e['task'], needles)}<br>"
                        f"<i>{mark_anchors(e['expected_result'], needles)}</i></td></tr>"
                    )
            out.append("</table>")
    return "\n".join(out)


if __name__ == "__main__":
    argv = sys.argv[1:]
    enui = True  # only the English-UI variant ships; --enui is accepted and implied
    argv = [a for a in argv if a != "--enui"]
    apps = argv or sorted(p.parent.name for p in PARTS.glob("*/anchors.json"))
    body = "\n".join(render_app(a, enui) for a in apps)
    out = ML / ("viewer_enui.html" if enui else "viewer.html")
    title = "EvoWeb multilingual review" + (" — English-UI variant" if enui else "")
    out.write_text(
        f"<!doctype html><meta charset=utf-8><title>{title}</title><style>{CSS}</style>\n{body}\n"
    )
    print("wrote", out, f"({len(apps)} apps)")
