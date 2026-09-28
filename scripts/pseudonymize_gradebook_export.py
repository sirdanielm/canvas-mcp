#!/usr/bin/env python3
"""One explicit export-ingest action: sanitize before creating a private archive."""

import argparse
import importlib.util
import json
import sys
from pathlib import Path

module_path = (
    Path(__file__).resolve().parents[1]
    / "src/canvas_mcp/gradebook/pseudonymize_export.py"
)
spec = importlib.util.spec_from_file_location("local_pin_export", module_path)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
ExportHeld, sanitize_export = module.ExportHeld, module.sanitize_export


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["ingest"])
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--central-roster", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--roster-sheet", choices=["Student Info", "Student Numbers"])
    args = parser.parse_args()
    try:
        result = sanitize_export(
            args.source, args.central_roster, args.output, args.roster_sheet
        )
    except ExportHeld as error:
        print(json.dumps({"status": "HELD", "reason": str(error)}), file=sys.stderr)
        return 1
    except Exception:
        print(
            json.dumps({"status": "HELD", "reason": "EXPORT_VALIDATION_FAILED"}),
            file=sys.stderr,
        )
        return 1
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
