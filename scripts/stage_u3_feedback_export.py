"""Stage an explicit private U3 export from stdin; never contact Canvas.

No input path discovery, credentials, connection, source-authority callback,
publisher inbox or approval token is accepted. All output remains unapproved.
The caller supplies the exact SHA-256 of the stdin bytes from the export owner.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import stat
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from canvas_mcp.gradebook.client import GradebookError  # noqa: E402
from canvas_mcp.gradebook.store import Store  # noqa: E402
from canvas_mcp.gradebook.u3_feedback_staging import stage_u3_feedback  # noqa: E402

MAX_BYTES = 5_000_000


def _json_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("duplicate key")
        value[key] = item
    return value


def _not_finite(value: str) -> None:
    raise ValueError("nonfinite JSON number")


def _finite_float(value: str) -> float:
    number = float(value)
    if not math.isfinite(number):
        raise ValueError("overflowed JSON number")
    return number


def stage_export(raw: bytes, expected_sha256: str) -> dict[str, Any]:
    """Validate one closed export and preserve every case, including errors."""
    if len(raw) > MAX_BYTES or hashlib.sha256(raw).hexdigest() != expected_sha256:
        raise GradebookError("U3_EXPORT_BYTES_CHANGED_OR_TOO_LARGE")
    try:
        value = json.loads(
            raw,
            object_pairs_hook=_json_object,
            parse_constant=_not_finite,
            parse_float=_finite_float,
        )
    except (ValueError, UnicodeError, RecursionError):
        raise GradebookError("U3_EXPORT_JSON_REQUIRED") from None
    if (
        type(value) is not dict
        or set(value) != {"contract", "cases"}
        or value["contract"] != "CANVAS_U3_FEEDBACK_STAGING_INPUT_V1"
        or type(value["cases"]) is not list
        or not 1 <= len(value["cases"]) <= 1000
    ):
        raise GradebookError("U3_CLOSED_EXPORT_REQUIRED")
    staged = []
    for position, case in enumerate(value["cases"]):
        try:
            if (
                type(case) is not dict
                or not set(case)
                <= {
                    "envelope",
                    "findings",
                    "producer_ref",
                    "producer_source_refs",
                    "feedback",
                    "target",
                }
                or not {"envelope", "findings", "producer_ref", "producer_source_refs"}
                <= set(case)
            ):
                raise GradebookError("U3_EXPORT_CASE_SCHEMA")
            result = stage_u3_feedback(**case)
        except GradebookError as exc:
            result = {
                "state": "HELD_UNAPPROVED",
                "retained_input": case,
                "holds": [str(exc)],
                "publication_allowed": False,
                "publisher_envelope": None,
                "canvas_writes": 0,
            }
        staged.append({"source_position": position, "stage": result})
    return {
        "contract": "CANVAS_U3_FEEDBACK_STAGED_EXPORT_V1",
        "input_bytes_sha256": expected_sha256,
        "source_case_count": len(value["cases"]),
        "staged": staged,
        "publication_allowed": False,
        "canvas_writes": 0,
        "sheets_writes": 0,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--expected-sha256", required=True)
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args()
    try:
        # The existing immutable Store needs POSIX ownership and directory fsync.
        # Keep pure export validation portable; refuse unsupported output before I/O.
        if os.name != "posix" or not callable(getattr(os, "getuid", None)):
            raise GradebookError("U3_PRIVATE_OUTPUT_UNAVAILABLE")
        # The explicit output is either fresh or an already-private owned root.
        root = args.output_dir
        if not root.exists() and not root.is_symlink():
            root.mkdir(mode=0o700)
        info = root.lstat()
        if (
            not stat.S_ISDIR(info.st_mode)
            or root.is_symlink()
            or info.st_uid != os.getuid()
            or stat.S_IMODE(info.st_mode) != 0o700
        ):
            raise GradebookError("U3_PRIVATE_OUTPUT_REQUIRED")
        result = stage_export(
            sys.stdin.buffer.read(MAX_BYTES + 1), args.expected_sha256
        )
        artifact_id, path = Store(root).save("receipt", result)
        if Store(root).load("receipt", artifact_id) != result:
            raise GradebookError("U3_STAGING_READBACK_FAILED")
        print(
            json.dumps(
                {
                    "state": "STAGED_UNAPPROVED",
                    "cases": result["source_case_count"],
                    "private_artifact": str(path),
                    "artifact_digest": artifact_id,
                    "canvas_writes": 0,
                    "sheets_writes": 0,
                    "publication_allowed": False,
                }
            )
        )
        return 0
    except (GradebookError, OSError):
        print(
            json.dumps(
                {
                    "error": "U3_STAGING_HELD_CHECK_PRIVATE_INPUT_OR_OUTPUT",
                    "canvas_writes": 0,
                    "publication_allowed": False,
                }
            )
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
