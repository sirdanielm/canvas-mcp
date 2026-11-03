"""Explicit registered Unit2 local proof command; never accepts response payloads."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

from canvas_mcp.gradebook.client import GradebookError
from canvas_mcp.gradebook.google import GoogleSheets
from canvas_mcp.gradebook.unit2_typed_capture import (
    CELL_FIELDS,
    capture_to_local_sink,
    file_ref,
    need,
    pinned_json,
    qualify_registration,
    validate_request,
)


def direct_ref(path: Path) -> dict[str, Any]:
    need(
        path.is_absolute() and not any(p.is_symlink() for p in (path, *path.parents)),
        "DIRECT_ARGUMENT_PATH_REQUIRED",
    )
    return file_ref(path)


def load_sink(ref: dict[str, Any]) -> Any:
    need(
        type(ref) is dict and set(ref) == {"path", "bytes", "sha256"},
        "PINNED_SINK_CODE_REQUIRED",
    )
    path = Path(ref["path"])
    need(
        path.is_absolute() and not any(p.is_symlink() for p in (path, *path.parents)),
        "DIRECT_SINK_CODE_REQUIRED",
    )
    raw = path.read_bytes()
    need(
        len(raw) == ref["bytes"] and hashlib.sha256(raw).hexdigest() == ref["sha256"],
        "SINK_CODE_CHANGED",
    )
    namespace: dict[str, Any] = {
        "__name__": "registered_unit2_local_sink",
        "__file__": str(path),
    }
    # Execute only the exact frozen owner code bytes just verified, never a
    # second filesystem read or a model-supplied native response.
    try:
        exec(compile(raw, str(path), "exec"), namespace)
        return namespace["LocalTypedProofSink"]
    except Exception:
        raise GradebookError("SINK_INITIALIZATION_FAILED") from None


async def run(args: argparse.Namespace) -> dict[str, Any]:
    need(args.read_registered_proof is True, "EXPLICIT_READ_INVOCATION_REQUIRED")
    registration_ref = direct_ref(Path(args.registration))
    registration = pinned_json(registration_ref)
    config = qualify_registration(
        registration
    )  # Must precede credential/client construction.
    google_source = sys.modules[GoogleSheets.__module__].__file__
    endpoint_source = sys.modules[capture_to_local_sink.__module__].__file__
    need(
        isinstance(google_source, str) and isinstance(endpoint_source, str),
        "LOADED_TRANSPORT_SOURCE_REQUIRED",
    )
    assert isinstance(google_source, str) and isinstance(endpoint_source, str)
    loaded_refs = {
        "google": file_ref(Path(google_source)),
        "endpoint": file_ref(Path(endpoint_source)),
        "cli": file_ref(Path(__file__)),
    }
    need(
        registration["transport_code_refs"] == loaded_refs,
        "LOADED_TRANSPORT_SOURCE_BINDING_CHANGED",
    )
    request_file = pinned_json(direct_ref(Path(args.ranges_file)))
    need(set(request_file) == {"ranges"}, "RANGE_FILE_ONLY_NO_PAYLOAD_ALLOWED")
    request = {
        "spreadsheet_id": config["spreadsheet_id"],
        "ranges": request_file["ranges"],
        "cell_fields": CELL_FIELDS,
    }
    validate_request(config, request)
    sink_type = load_sink(registration["sink_code_ref"])
    try:
        sink = sink_type(config, Path(args.output_root))
    except Exception:
        raise GradebookError("SINK_INITIALIZATION_FAILED") from None
    google = GoogleSheets(
        config["spreadsheet_id"],
        registration["credential_path"],
        registration["credential_profile"],
        read_only=True,
    )
    try:
        # Native object never leaves this process except through the pinned sink.
        return await capture_to_local_sink(
            google,
            sink,
            registration=registration,
            request=request,
            registration_ref=registration_ref,
            transport_code_ref=file_ref(Path(__file__).resolve()),
        )
    finally:
        await google.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--registration", required=True)
    parser.add_argument("--ranges-file", required=True)
    parser.add_argument("--output-root", required=True)
    parser.add_argument("--read-registered-proof", action="store_true")
    args = parser.parse_args()
    try:
        result = asyncio.run(run(args))
    except Exception:
        # Avoid traceback response/credential disclosure in command results.
        print(
            json.dumps(
                {
                    "status": "CAPTURE_HELD",
                    "raw_payload_returned": False,
                    "external_mutations": 0,
                }
            )
        )
        raise SystemExit(2) from None
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
