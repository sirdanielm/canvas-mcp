#!/usr/bin/env python3
"""Validate a private archive without publishing, or explicitly ingest a copy."""

import argparse
import importlib.util
import json
import sys
from pathlib import Path

if sys.version_info < (3, 11):  # noqa: UP036 -- direct CLI may run before package installation
    print(
        json.dumps({"status": "HELD", "reason": "PYTHON_3_11_REQUIRED"}),
        file=sys.stderr,
    )
    raise SystemExit(1)

module_path = (
    Path(__file__).resolve().parents[1]
    / "src/canvas_mcp/gradebook/pseudonymize_export.py"
)
spec = importlib.util.spec_from_file_location("local_pin_export", module_path)
module = importlib.util.module_from_spec(spec)
try:
    spec.loader.exec_module(module)
except ModuleNotFoundError:
    print(
        json.dumps({"status": "HELD", "reason": "LOCAL_EXPORT_DEPENDENCY_MISSING"}),
        file=sys.stderr,
    )
    raise SystemExit(1) from None
ExportHeld = module.ExportHeld


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["ingest", "preflight"])
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument(
        "--source-registry",
        type=Path,
        default=Path.home() / "QuinnOperator/config/student-pin-source.json",
    )
    parser.add_argument("--shared-pin-tool", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument(
        "--expected-source-sha256", help="bind the exact QC input bytes"
    )
    args = parser.parse_args()
    try:
        if args.action == "preflight" and args.output is not None:
            raise ExportHeld("PREFLIGHT_OUTPUT_NOT_ALLOWED")
        if args.action == "ingest" and args.output is None:
            raise ExportHeld("OUTPUT_REQUIRED")
        shared_tool = args.shared_pin_tool or module.default_shared_pin_tool(
            Path(__file__).resolve().parents[1]
        )
        options = {}
        if args.action == "preflight":
            options["validate_only"] = True
        if args.expected_source_sha256 is not None:
            options["expected_source_hash"] = args.expected_source_sha256
        result = module.registry_bound_export(
            args.source, args.output, args.source_registry, shared_tool, **options
        )
    except module.ExportPublicationUncertain:
        print(
            json.dumps(
                {
                    "status": "ARCHIVE_PUBLICATION_UNCERTAIN",
                    "reason": "CHECK_PRIVATE_OUTPUT_BEFORE_RETRY",
                }
            ),
            file=sys.stderr,
        )
        return 2
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
