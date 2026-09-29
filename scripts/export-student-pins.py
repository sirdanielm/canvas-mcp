#!/usr/bin/env python3
"""Use the shared local-only student PIN exporter without a second mapper."""

import runpy
import sys
from pathlib import Path


def main() -> None:
    shared = (
        Path(__file__).resolve().parents[2]
        / "LocalGrAss-github"
        / "scripts"
        / "export-student-pins.py"
    )
    if not shared.is_file():
        print(
            "Shared student PIN exporter is unavailable; no export was made.",
            file=sys.stderr,
        )
        raise SystemExit(2)
    runpy.run_path(str(shared), run_name="__main__")


if __name__ == "__main__":
    main()
