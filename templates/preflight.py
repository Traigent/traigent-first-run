#!/usr/bin/env python3
"""Compatibility entry point for the self-contained first-run preflight."""

from pathlib import Path
import runpy

SCRIPT = (
    Path(__file__).resolve().parents[1]
    / "skills"
    / "traigent-first-run"
    / "scripts"
    / "preflight.py"
)

runpy.run_path(str(SCRIPT), run_name="__main__")
