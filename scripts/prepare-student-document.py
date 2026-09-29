#!/usr/bin/env python3
"""Run the shared local PIN document preparation tool."""
from pathlib import Path
import runpy
shared = Path(__file__).resolve().parents[2] / "LocalGrAss-github" / "scripts" / "prepare-student-document.py"
if not shared.is_file():
    raise SystemExit("Shared student document tool unavailable; no preparation was made.")
runpy.run_path(str(shared), run_name="__main__")
