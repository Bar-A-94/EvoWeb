"""Node package installs for the harness CLIs."""

from __future__ import annotations

import subprocess
from pathlib import Path


def install(
    prefix: Path, packages: list[str], bins: list[str], ignore_scripts: bool = True
) -> Path:
    """Install `packages` under `prefix` unless every bin is already there.

    Pass `ignore_scripts=False` for a harness whose postinstall fetches a native binary:
    Claude Code installs fine with scripts off and then dies at startup with "claude
    native binary not installed".
    """
    node_bin = prefix / "node_modules/.bin"
    if all((node_bin / name).exists() for name in bins):
        return node_bin
    prefix.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            "npm",
            "install",
            "--prefix",
            str(prefix),
            "--no-audit",
            "--no-fund",
            "--omit=dev",
            # Without this npm records `^x.y.z`, so a re-install into a fresh prefix can
            # resolve a newer patch. Two of my own pi runs silently ran different versions.
            "--save-exact",
            *(["--ignore-scripts"] if ignore_scripts else []),
            *packages,
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    return node_bin
