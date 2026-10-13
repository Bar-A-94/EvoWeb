"""Xvfb + ffmpeg session recording for WebVoyager evals.

Lives next to (not inside) the vendored WebVoyager sources — run.py/utils.py
are upstream copies and stay pristine for future syncs.
"""

from __future__ import annotations

import itertools
import os
import shutil
import signal
import subprocess
import time
from pathlib import Path

# Pid-seeded (parallel pods) and incremented per eval (sequential turns).
_DISPLAY_NO = itertools.count(90 + os.getpid() % 50)


class SessionRecording:
    """A live private Xvfb display with ffmpeg capturing it to an mp4."""

    def __init__(self, display: str, video_path: Path, xvfb, ffmpeg):
        self.display = display
        self.video_path = video_path
        self._xvfb = xvfb
        self._ffmpeg = ffmpeg

    def finalize(self) -> Path | None:
        """Stop capture + display; return the video path if a non-empty mp4 landed."""
        self._ffmpeg.send_signal(signal.SIGINT)  # clean stop so the mp4 is finalized
        try:
            self._ffmpeg.wait(timeout=20)
        except subprocess.TimeoutExpired:
            self._ffmpeg.kill()
        self._xvfb.terminate()
        try:
            self._xvfb.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self._xvfb.kill()
        if self.video_path.exists() and self.video_path.stat().st_size > 0:
            return self.video_path
        return None


def start_session_recording(output_dir: Path, log=print) -> SessionRecording | None:
    """Start Xvfb + ffmpeg writing output_dir/videos/webvoyager_<tag>.mp4.

    The video name carries output_dir.name so multi-turn videos don't collide.
    Returns None (with a warning) when Xvfb/ffmpeg are missing — the caller
    falls back to a headless, unrecorded eval."""
    xvfb_bin, ffmpeg_bin = shutil.which("Xvfb"), shutil.which("ffmpeg")
    if not (xvfb_bin and ffmpeg_bin):
        log("WARNING: record_video needs Xvfb + ffmpeg on PATH; running headless without video")
        return None
    display = f":{next(_DISPLAY_NO)}"
    xvfb = subprocess.Popen(
        [xvfb_bin, display, "-screen", "0", "1280x900x24", "-nolisten", "tcp"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    time.sleep(1.0)
    video_path = output_dir / "videos" / f"webvoyager_{output_dir.name}.mp4"
    video_path.parent.mkdir(parents=True, exist_ok=True)
    ffmpeg = subprocess.Popen(
        [
            ffmpeg_bin,
            "-y",
            "-loglevel",
            "error",
            "-f",
            "x11grab",
            "-video_size",
            "1280x900",
            "-framerate",
            "8",
            "-i",
            display,
            "-codec:v",
            "libx264",
            "-preset",
            "ultrafast",
            "-pix_fmt",
            "yuv420p",
            "-movflags",
            "+faststart",  # moov up front for in-browser playback
            str(video_path),
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return SessionRecording(display, video_path, xvfb, ffmpeg)
