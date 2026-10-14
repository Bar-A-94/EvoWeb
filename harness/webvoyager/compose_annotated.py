#!/usr/bin/env python3
"""Compose a WebVoyager session video with a synced side panel.

Panel shows, per judged check: the task + expected result, the judge's live
thinking, the concrete action it took, errors, and the final verdict — so a
viewer sees end-to-end what the LLM judge did and why.

Post-processing tool (run on a workstation, not in the container).

Usage: compose_annotated.py SAMPLE_DIR OUT.mp4
  SAMPLE_DIR = a downloaded S3 sample dir: videos/webvoyager_*.mp4 +
               eval/results/task*/agent.log + eval/tasks.jsonl
  Needs ffmpeg/ffprobe + Pillow; FONT below may need adjusting per machine.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

VW, VH = 1280, 900  # session video geometry (recording.py)
PW = 640  # panel width
FPS = 8
FIRST_TASK_VIDEO_T = 3.0  # est. video time of the first TASK log line (s)

FONT = "/usr/share/fonts/google-noto-vf/NotoSans[wght].ttf"
F_TITLE = ImageFont.truetype(FONT, 26)
F_H = ImageFont.truetype(FONT, 21)
F_BODY = ImageFont.truetype(FONT, 19)
F_SMALL = ImageFont.truetype(FONT, 16)

BG = (17, 19, 28)
C_TITLE = (240, 242, 255)
C_TASK = (125, 175, 255)
C_EXPECT = (170, 220, 170)
C_THINK = (200, 200, 210)
C_ACTION = (120, 230, 160)
C_ERR = (255, 130, 130)
C_MUT = (130, 135, 150)
VERDICT_C = {"YES": (110, 230, 140), "PARTIAL": (250, 200, 90), "NO": (255, 120, 120)}

TS_RE = re.compile(r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2},\d{3}) - \w+ - (.*)$", re.S)


def _ts(s):
    return datetime.strptime(s, "%Y-%m-%d %H:%M:%S,%f").timestamp()


def parse_agent_log(path: Path):
    """One task's timeline: header ts, per-iter (ts, thinking), actions, verdict."""
    entries = []  # (ts, text) merged multi-line
    for raw in path.read_text(errors="replace").split("\n"):
        m = TS_RE.match(raw)
        if m:
            entries.append([_ts(m.group(1)), m.group(2)])
        elif entries:
            entries[-1][1] += "\n" + raw
    task_id, t0 = None, None
    iters = []  # {t, n, thinking}
    for t, txt in entries:
        if txt.startswith("#####"):
            task_id = txt.strip("# ").strip()
            t0 = t
        elif txt.startswith("Iter: "):
            iters.append({"t": t, "n": int(txt.split()[1]), "thinking": ""})
        elif txt.startswith("[THINKING]") and iters:
            iters[-1]["thinking"] = txt[len("[THINKING]") :].strip()
    # actions + verdict live in the end-of-run message dump (assistant msgs, in order)
    acts, verdict = [], None
    for t, txt in entries:
        if txt.startswith("{'role': 'assistant'"):
            try:
                msg = eval(txt, {"__builtins__": {}})  # trusted local log
            except Exception:
                continue
            content = msg.get("content", "")
            if isinstance(content, str):
                am = re.search(r"Action:\s*(.+)", content)
                thm = re.search(r"Thought:\s*(.+?)(?:\n|$)", content, re.S)
                if am:
                    acts.append(
                        {
                            "action": am.group(1).strip(),
                            "thought": (thm.group(1).strip() if thm else ""),
                        }
                    )
                elif content.strip() in ("YES", "NO", "PARTIAL"):
                    verdict = content.strip()
                elif content.startswith("ANSWER") or "ANSWER;" in content:
                    verdict = content.split(";", 1)[-1].strip()[:40]
    for i, it in enumerate(iters):
        it.update(acts[i] if i < len(acts) else {"action": "", "thought": ""})
    last_t = entries[-1][0] if entries else t0
    return {"task_id": task_id, "t0": t0, "iters": iters, "verdict": verdict, "t_end": last_t}


def wrap(draw, text, font, width):
    out = []
    for para in text.split("\n"):
        line = ""
        for w in para.split(" "):
            cand = (line + " " + w).strip()
            if draw.textlength(cand, font=font) <= width:
                line = cand
            else:
                out.append(line)
                line = w
        out.append(line)
    return out


def panel_frame(sample, task_q, expect, state):
    img = Image.new("RGB", (PW, VH), BG)
    d = ImageDraw.Draw(img)
    x, y, wpx = 24, 18, PW - 48

    def block(label, text, color, font=F_BODY, max_lines=99):
        nonlocal y
        if not text:
            return
        d.text((x, y), label, font=F_SMALL, fill=C_MUT)
        y += 24
        lines = wrap(d, text, font, wpx)[:max_lines]
        if len(lines) == max_lines:
            lines[-1] += " …"
        for ln in lines:
            d.text((x, y), ln, font=font, fill=color)
            y += 26
        y += 12

    d.text((x, y), f"WebVoyager judge — sample {sample}", font=F_TITLE, fill=C_TITLE)
    y += 42
    d.text((x, y), state["check"], font=F_H, fill=C_MUT)
    y += 34
    block("TASK", task_q, C_TASK, max_lines=4)
    block("EXPECTED", expect, C_EXPECT, max_lines=4)
    if state.get("verdict"):
        v = state["verdict"]
        d.rectangle([x, y, x + wpx, y + 46], outline=VERDICT_C.get(v, C_MUT), width=2)
        d.text((x + 14, y + 8), f"VERDICT: {v}", font=F_H, fill=VERDICT_C.get(v, C_MUT))
        y += 62
    else:
        block(f"STEP {state.get('n', 0)} — ACTION", state.get("action", ""), C_ACTION, F_H, 3)
        think = state.get("thinking") or state.get("thought") or ""
        err = ""
        if "wrong" in think.lower() and "format" in think.lower():
            err = "format error — agent retried"
        block("JUDGE THINKING", think, C_THINK, F_BODY, 16)
        block("ERROR", err, C_ERR)
    d.text((x, VH - 30), "EvoWeb — recorded judge session", font=F_SMALL, fill=C_MUT)
    return img


def main(sample_dir: Path, out_mp4: Path):
    video = next((sample_dir / "videos").glob("webvoyager_*.mp4"))
    sample = video.stem.split("_")[-1]
    tasks = {
        json.loads(l)["id"]: json.loads(l)["ques"]
        for l in (sample_dir / "eval" / "tasks.jsonl").read_text().splitlines()
        if l.strip()
    }
    logs = sorted((sample_dir / "eval" / "results").glob("task*/agent.log"))
    parsed = sorted((parse_agent_log(p) for p in logs), key=lambda r: r["t0"] or 0)
    parsed = [p for p in parsed if p["t0"]]
    dur = float(
        subprocess.check_output(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "csv=p=0",
                str(video),
            ]
        ).strip()
    )

    wall0 = parsed[0]["t0"] - FIRST_TASK_VIDEO_T  # wall clock at video t=0

    # timeline of (video_t, state) changes
    events = []
    n_tasks = len(parsed)
    for k, p in enumerate(parsed):
        tid = p["task_id"].replace("TASK", "").lower()
        q = tasks.get(tid.replace("task", ""), "") or tasks.get(tid, "")
        tm = re.search(r"Task:\s*(.*?)\n\s*\nExpected Result:\s*(.*)", q, re.S)
        task_q = tm.group(1).strip() if tm else q[:300]
        expect = tm.group(2).strip() if tm else ""
        check = f"check {k + 1}/{n_tasks}  ({tid})"
        base = {"check": check, "_task": task_q, "_expect": expect}
        events.append(
            (p["t0"] - wall0, {**base, "n": 0, "action": "loading page…", "thinking": ""})
        )
        for it in p["iters"]:
            events.append(
                (
                    it["t"] - wall0,
                    {
                        **base,
                        "n": it["n"] + 1,
                        "action": it.get("action", ""),
                        "thinking": it.get("thinking") or it.get("thought", ""),
                    },
                )
            )
        events.append((p["t_end"] - wall0, {**base, "verdict": p["verdict"] or "?"}))

    events = [(max(0.0, t), s) for t, s in sorted(events, key=lambda e: e[0]) if t < dur]

    tmp = Path(tempfile.mkdtemp(prefix="panel_"))
    concat = ["ffconcat version 1.0"]
    for i, (t, state) in enumerate(events):
        end = events[i + 1][0] if i + 1 < len(events) else dur
        if end - t < 0.05:
            continue
        f = tmp / f"p{i:04d}.png"
        panel_frame(sample, state["_task"], state["_expect"], state).save(f)
        concat += [f"file '{f}'", f"duration {end - t:.3f}"]
    concat += [f"file '{tmp / f'p{i:04d}.png'}'"]  # concat demuxer needs a trailing entry
    (tmp / "panel.ffconcat").write_text("\n".join(concat))

    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-loglevel",
            "error",
            "-i",
            str(video),
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(tmp / "panel.ffconcat"),
            "-filter_complex",
            f"[1:v]fps={FPS},scale={PW}:{VH}[p];[0:v][p]hstack=inputs=2[v]",
            "-map",
            "[v]",
            "-c:v",
            "libx264",
            "-preset",
            "fast",
            "-crf",
            "26",
            "-pix_fmt",
            "yuv420p",
            "-movflags",
            "+faststart",
            str(out_mp4),
        ],
        check=True,
    )
    print(
        f"wrote {out_mp4} ({out_mp4.stat().st_size / 1e6:.1f} MB, {dur:.0f}s, {len(events)} panel states)"
    )


if __name__ == "__main__":
    main(Path(sys.argv[1]), Path(sys.argv[2]))
