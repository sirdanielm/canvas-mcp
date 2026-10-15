"""Verify one previously admitted connector export; reference arrives on stdin."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

if __name__ == "__main__":
    from canvas_mcp.mirror.export_materializer import main

    raise SystemExit(main())
