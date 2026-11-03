"""Registered Unit2 typed GET -> local sink boundary. No mutation capability.

Registration is operator configuration, not self-authenticating user consent.
No credential is loaded by this module; only the CLI may construct the canonical
Google client after validating an explicitly active, separately reviewed config.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

from .client import GradebookError

TABS = ("Grades", "Intake", "Responses", "Review", "Audit")
CELL_FIELDS = "userEnteredValue,userEnteredFormat,dataValidation,note,chipRuns"
TYPED_FIELDS = (
    "spreadsheetId,sheets(properties(sheetId,title,gridProperties),"
    "data(startRow,startColumn,rowData(values(" + CELL_FIELDS + ")))))"
)
PROPERTY_FIELDS = "spreadsheetId,sheets(properties(sheetId,title,gridProperties))"


def need(condition: bool, code: str) -> None:
    if not condition:
        raise GradebookError(code)


def file_ref(path: Path) -> dict[str, Any]:
    raw = path.read_bytes()
    return {
        "path": str(path),
        "bytes": len(raw),
        "sha256": hashlib.sha256(raw).hexdigest(),
    }


def pinned_json(ref: dict[str, Any]) -> dict[str, Any]:
    need(
        type(ref) is dict and set(ref) == {"path", "bytes", "sha256"},
        "EXACT_FILE_REF_REQUIRED",
    )
    p = Path(ref["path"])
    need(
        p.is_absolute() and not any(x.is_symlink() for x in (p, *p.parents)),
        "DIRECT_LOCAL_REF_REQUIRED",
    )
    fd = os.open(p, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(fd, "rb") as stream:
        info = os.fstat(stream.fileno())
        need(
            stat.S_ISREG(info.st_mode) and 0 < info.st_size <= 2_000_000,
            "BOUNDED_REGISTRATION_REQUIRED",
        )
        raw = stream.read(2_000_001)
    need(
        len(raw) == ref["bytes"] and hashlib.sha256(raw).hexdigest() == ref["sha256"],
        "LOCAL_REF_CHANGED",
    )
    try:
        value = json.loads(raw)
    except (ValueError, UnicodeDecodeError):
        raise GradebookError("LOCAL_CONFIG_JSON_REQUIRED") from None
    need(type(value) is dict, "LOCAL_CONFIG_OBJECT_REQUIRED")
    return cast(dict[str, Any], value)


def column(n: int) -> str:
    value = ""
    while n:
        n, digit = divmod(n - 1, 26)
        value = chr(65 + digit) + value
    return value


def validate_request(
    config: dict[str, Any], request: dict[str, Any]
) -> dict[str, tuple[int, int]]:
    need(
        type(config) is dict and config.get("header_row") == 6,
        "REGISTERED_NATIVE_HEADERS_REQUIRED",
    )
    need(
        type(request) is dict
        and set(request) == {"spreadsheet_id", "ranges", "cell_fields"},
        "EXACT_TYPED_REQUEST_REQUIRED",
    )
    need(
        request["spreadsheet_id"] == config.get("spreadsheet_id"),
        "REGISTERED_WORKBOOK_MISMATCH",
    )
    need(request["cell_fields"] == CELL_FIELDS, "EXACT_FIVE_TYPED_FIELDS_REQUIRED")
    ranges = request["ranges"]
    need(type(ranges) is list and len(ranges) == 5, "EXACT_FIVE_TABLE_RANGES_REQUIRED")
    result: dict[str, tuple[int, int]] = {}
    total = 0
    for value in ranges:
        need(type(value) is str, "QUOTED_BOUNDED_A1_REQUIRED")
        match = re.fullmatch(
            r"'(Grades|Intake|Responses|Review|Audit)'!A6:([A-Z]{1,3})([1-9][0-9]{0,5})",
            value,
        )
        need(match is not None, "QUOTED_BOUNDED_A1_REQUIRED")
        assert match is not None
        tab, right, last = match.groups()
        need(tab not in result, "DUPLICATE_TABLE_RANGE")
        headers = config.get("headers", {}).get(tab)
        cap = config.get("table_capacities", {}).get(tab)
        sid = config.get("sheet_ids", {}).get(tab)
        need(
            type(headers) is list
            and 0 < len(headers) <= 26
            and all(type(x) is str and x for x in headers),
            "REGISTERED_HEADERS_REQUIRED",
        )
        need(
            type(cap) is int and cap > 0 and type(sid) is int and sid >= 0,
            "REGISTERED_TAB_CAPACITY_REQUIRED",
        )
        end = int(last)
        need(
            right == column(len(headers)) and 6 <= end <= cap + 6,
            "REGISTERED_RANGE_BOUNDS_REQUIRED",
        )
        cells = (end - 5) * len(headers)
        need(cells <= 50_000, "TYPED_RANGE_CELL_LIMIT")
        total += cells
        result[tab] = (end, len(headers))
    need(
        set(result) == set(TABS) and total <= 500_000,
        "COMPLETE_BOUNDED_TYPED_REQUEST_REQUIRED",
    )
    return result


def registered_properties(
    config: dict[str, Any], response: dict[str, Any], bounds: dict[str, tuple[int, int]]
) -> dict[str, Any]:
    need(
        type(response) is dict
        and response.get("spreadsheetId") == config["spreadsheet_id"],
        "RESPONSE_WORKBOOK_CHANGED",
    )
    sheets = response.get("sheets")
    need(type(sheets) is list and len(sheets) <= 100, "BOUNDED_NATIVE_SHEETS_REQUIRED")
    selected: dict[str, Any] = {}
    ids: set[int] = set()
    names: set[str] = set()
    for sheet in cast(list[Any], sheets):
        need(
            type(sheet) is dict and type(sheet.get("properties")) is dict,
            "NATIVE_SHEET_PROPERTIES_REQUIRED",
        )
        props = sheet["properties"]
        title, sid = props.get("title"), props.get("sheetId")
        need(
            type(title) is str
            and title not in names
            and type(sid) is int
            and sid not in ids,
            "DUPLICATE_NATIVE_SHEET",
        )
        names.add(title)
        ids.add(sid)
        if title not in bounds:
            need(not sheet.get("data"), "UNREQUESTED_NATIVE_GRID")
            continue
        need(sid == config["sheet_ids"][title], "REGISTERED_TAB_ID_CHANGED")
        grid = props.get("gridProperties", {})
        end, width = bounds[title]
        need(
            type(grid.get("rowCount")) is int
            and grid["rowCount"] >= end
            and type(grid.get("columnCount")) is int
            and grid["columnCount"] >= width,
            "REGISTERED_GRID_TOO_SMALL",
        )
        selected[title] = props
    need(set(selected) == set(TABS), "REGISTERED_TABLE_MISSING")
    return selected


def validate_native_response(
    config: dict[str, Any], request: dict[str, Any], response: dict[str, Any]
) -> None:
    bounds = validate_request(config, request)
    registered_properties(config, response, bounds)
    seen: dict[str, set[tuple[int, int]]] = {t: set() for t in TABS}
    headers: dict[str, dict[int, Any]] = {t: {} for t in TABS}
    for sheet in response["sheets"]:
        tab = sheet["properties"]["title"]
        if tab not in bounds:
            continue
        end, width = bounds[tab]
        for block in sheet.get("data", []):
            need(type(block) is dict, "NATIVE_GRID_REQUIRED")
            r0, c0 = block.get("startRow", 0), block.get("startColumn", 0)
            need(
                type(r0) is int and type(c0) is int and r0 >= 0 and c0 >= 0,
                "NATIVE_GRID_ORIGIN_REQUIRED",
            )
            for i, row in enumerate(block.get("rowData", [])):
                need(
                    type(row) is dict and type(row.get("values", [])) is list,
                    "NATIVE_ROW_REQUIRED",
                )
                for j, cell in enumerate(row.get("values", [])):
                    rr, cc = r0 + i, c0 + j
                    need(5 <= rr < end and 0 <= cc < width, "RESPONSE_OUTSIDE_REQUEST")
                    need((rr, cc) not in seen[tab], "OVERLAPPING_NATIVE_GRID")
                    seen[tab].add((rr, cc))
                    need(
                        type(cell) is dict and set(cell) <= set(CELL_FIELDS.split(",")),
                        "UNREQUESTED_CELL_FIELD",
                    )
                    if rr == 5:
                        headers[tab][cc] = cell.get("userEnteredValue")
        need(
            headers[tab]
            == {i: {"stringValue": h} for i, h in enumerate(config["headers"][tab])},
            "FRESH_LITERAL_HEADER_CHANGED",
        )
    # Trailing absent blank CellData remains absent; never synthesize cells.


def qualify_registration(registration: dict[str, Any]) -> dict[str, Any]:
    need(
        type(registration) is dict
        and registration.get("schema") == "UNIT2_LOCAL_TYPED_CAPTURE_REGISTRATION_V1",
        "EXPLICIT_CAPTURE_REGISTRATION_REQUIRED",
    )
    need(
        registration.get("state") == "ACTIVE_REVIEWED_READ_ONLY",
        "CAPTURE_REGISTRATION_NOT_ACTIVATED",
    )
    need(
        registration.get("allowed_operation") == "READ_UNIT2_TYPED_PROOF_ONLY",
        "READ_ONLY_OPERATION_REQUIRED",
    )
    code_refs = registration.get("transport_code_refs")
    need(
        type(code_refs) is dict and set(code_refs) == {"google", "endpoint", "cli"},
        "COMPLETE_TRANSPORT_SOURCE_REFS_REQUIRED",
    )
    for ref in cast(dict[str, Any], code_refs).values():
        verify_source_ref(ref)
    config = pinned_json(registration["native_config_ref"])
    need(
        config.get("canvas_writes") is False and config.get("paid_calls") is False,
        "NATIVE_CONFIG_SCOPE_CHANGED",
    )
    need(
        registration.get("spreadsheet_id") == config.get("spreadsheet_id"),
        "REGISTRATION_WORKBOOK_MISMATCH",
    )
    need(
        type(registration.get("credential_path")) is str
        and Path(registration["credential_path"]).is_absolute()
        and registration.get("credential_profile") == "unit2-typed-capture",
        "EXPLICIT_UNIT2_CREDENTIAL_BINDING_REQUIRED",
    )
    # An authority FileRef documents operator review, but is never treated as
    # authentication or human consent by itself. The actual host gate still applies.
    pinned_json(registration["operator_review_ref"])
    return config


def verify_source_ref(ref: dict[str, Any]) -> None:
    need(
        type(ref) is dict and set(ref) == {"path", "bytes", "sha256"},
        "EXACT_SOURCE_CODE_REF_REQUIRED",
    )
    p = Path(ref["path"])
    need(
        p.is_absolute() and not any(x.is_symlink() for x in (p, *p.parents)),
        "DIRECT_SOURCE_CODE_REQUIRED",
    )
    need(file_ref(p) == ref, "SOURCE_CODE_PIN_CHANGED")


def persist_metadata(root: Path, value: dict[str, Any]) -> dict[str, Any]:
    need(
        root.is_absolute() and not any(p.is_symlink() for p in (root, *root.parents)),
        "DIRECT_METADATA_ROOT_REQUIRED",
    )
    info = root.stat()
    need(
        stat.S_ISDIR(info.st_mode)
        and info.st_uid == os.getuid()
        and info.st_mode & 0o077 == 0,
        "OWNER_ONLY_METADATA_ROOT_REQUIRED",
    )
    raw = (
        json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )
        + "\n"
    ).encode()
    need(len(raw) < 100_000, "METADATA_MANIFEST_LIMIT")
    name = "TYPED-CAPTURE-METADATA-" + hashlib.sha256(raw).hexdigest() + ".private.json"
    directory = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    temporary = ".metadata-" + uuid.uuid4().hex
    try:
        fd = os.open(
            temporary,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
            0o600,
            dir_fd=directory,
        )
        with os.fdopen(fd, "wb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.link(
                temporary,
                name,
                src_dir_fd=directory,
                dst_dir_fd=directory,
                follow_symlinks=False,
            )
        except FileExistsError:
            existing = os.open(name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=directory)
            with os.fdopen(existing, "rb") as stream:
                prior = os.fstat(stream.fileno())
                need(
                    stat.S_ISREG(prior.st_mode)
                    and prior.st_uid == os.getuid()
                    and prior.st_mode & 0o077 == 0
                    and stream.read() == raw,
                    "METADATA_MANIFEST_CONFLICT",
                )
        os.fsync(directory)
    finally:
        try:
            os.unlink(temporary, dir_fd=directory)
        except FileNotFoundError:
            pass
        os.close(directory)
    return {
        "path": str(root / name),
        "bytes": len(raw),
        "sha256": hashlib.sha256(raw).hexdigest(),
    }


def _same_metadata_value(actual: Any, expected: Any) -> bool:
    """Compare only the bounded known metadata schema, preserving JSON types."""
    if type(actual) is not type(expected):
        return False
    if type(expected) is dict:
        return actual.keys() == expected.keys() and all(
            _same_metadata_value(actual[key], value) for key, value in expected.items()
        )
    if type(expected) is list:
        return len(actual) == len(expected) and all(
            _same_metadata_value(a, b) for a, b in zip(actual, expected, strict=True)
        )
    return bool(actual == expected)


def _sink_metadata(
    result: Any,
    *,
    root: Path,
    request: dict[str, Any],
    bounds: dict[str, tuple[int, int]],
    started_at: str,
    completed_at: str,
    transport_code_ref: dict[str, Any],
    registration_ref: dict[str, Any],
) -> dict[str, Any]:
    """Validate and rebuild the exact metadata-only owner-sink receipt.

    A pinned sink is trusted code, but its result is still a privacy boundary.
    Unknown fields or altered nested metadata never enter a manifest or stdout.
    """
    expected = {
        "contract": "UNIT2_LOCAL_TYPED_FILE_RECEIPT_V1",
        "status": "LOCAL_FILE_SAVED_NOT_TRANSPORT_AUTHORITY",
        "started_at": started_at,
        "completed_at": completed_at,
        "request": request,
        "transport_code_ref": transport_code_ref,
        "registration_ref": registration_ref,
        "counts": {
            "requested_cells": sum((end - 5) * width for end, width in bounds.values()),
            "tables": list(TABS),
            "range_count": len(request["ranges"]),
        },
        "raw_payload_returned": False,
        "external_mutations": 0,
    }
    need(
        type(result) is dict and set(result) == set(expected) | {"capture_ref"},
        "SINK_METADATA_EXACT_FIELDS_REQUIRED",
    )
    need(
        all(
            _same_metadata_value(result[key], value) for key, value in expected.items()
        ),
        "SINK_METADATA_BINDING_CHANGED",
    )
    ref = result["capture_ref"]
    need(
        type(ref) is dict
        and set(ref) == {"path", "bytes", "sha256"}
        and type(ref.get("path")) is str
        and type(ref.get("bytes")) is int
        and ref["bytes"] > 0
        and type(ref.get("sha256")) is str
        and re.fullmatch(r"[a-f0-9]{64}", ref["sha256"]) is not None,
        "SINK_METADATA_CAPTURE_REFERENCE_REQUIRED",
    )
    path = Path(ref["path"])
    need(
        path.is_absolute()
        and ".." not in path.parts
        and path.parent == root
        and path.name == "TYPED-CAPTURE-" + ref["sha256"] + ".receipt.private.json"
        and not any(item.is_symlink() for item in (path, *path.parents)),
        "SINK_METADATA_PRIVATE_CAPTURE_PATH_REQUIRED",
    )
    try:
        info = path.stat(follow_symlinks=False)
    except OSError:
        raise GradebookError("SINK_METADATA_CAPTURE_UNAVAILABLE") from None
    need(
        stat.S_ISREG(info.st_mode)
        and info.st_uid == os.getuid()
        and stat.S_IMODE(info.st_mode) == 0o600
        and info.st_nlink == 1
        and info.st_size == ref["bytes"],
        "SINK_METADATA_PRIVATE_CAPTURE_REQUIRED",
    )
    return {**expected, "capture_ref": dict(ref)}


async def capture_to_local_sink(
    google: Any,
    sink: Any,
    *,
    registration: dict[str, Any],
    request: dict[str, Any],
    registration_ref: dict[str, Any],
    transport_code_ref: dict[str, Any],
) -> dict[str, Any]:
    need(
        pinned_json(registration_ref) == registration, "REGISTRATION_OBJECT_REF_CHANGED"
    )
    expected_registration = json.loads(json.dumps(registration))
    expected_request = json.loads(json.dumps(request))
    expected_source_ref = json.loads(json.dumps(transport_code_ref))
    expected_registration_ref = json.loads(json.dumps(registration_ref))
    verify_source_ref(expected_source_ref)
    config = qualify_registration(registration)
    bounds = validate_request(config, request)
    need(
        google.workbook_id == config["spreadsheet_id"],
        "CANONICAL_CLIENT_WORKBOOK_MISMATCH",
    )
    need(getattr(google, "read_only", None) is True, "READ_ONLY_CLIENT_MODE_REQUIRED")
    need(sink.config == config, "SINK_REGISTRATION_CONFIG_CHANGED")
    started = datetime.now(UTC).isoformat()
    response = await google.read_registered_unit2_typed_ranges(config, request)
    completed = datetime.now(UTC).isoformat()
    need(
        registration == expected_registration
        and pinned_json(registration_ref) == expected_registration,
        "REGISTRATION_CHANGED_DURING_CAPTURE",
    )
    need(request == expected_request, "REQUEST_CHANGED_DURING_CAPTURE")
    need(
        qualify_registration(expected_registration) == config,
        "NATIVE_CONFIG_CHANGED_DURING_CAPTURE",
    )
    verify_source_ref(expected_source_ref)
    validate_native_response(config, request, response)
    try:
        result = sink.persist(
            request=request,
            response=response,
            started_at=started,
            completed_at=completed,
            transport_code_ref=transport_code_ref,
            registration_ref=registration_ref,
        )
    except Exception:
        raise GradebookError("SINK_PERSISTENCE_HELD") from None
    result = _sink_metadata(
        result,
        root=sink.root,
        request=expected_request,
        bounds=bounds,
        started_at=started,
        completed_at=completed,
        transport_code_ref=expected_source_ref,
        registration_ref=expected_registration_ref,
    )

    metadata = {
        "contract": "UNIT2_TYPED_CAPTURE_INVOCATION_METADATA_V1",
        "invocation_id": uuid.uuid4().hex,
        "started_at": started,
        "completed_at": completed,
        "request": expected_request,
        "registration_ref": expected_registration_ref,
        "transport_code_ref": expected_source_ref,
        "native_config_ref": expected_registration["native_config_ref"],
        "operator_review_ref": expected_registration["operator_review_ref"],
        "sink_result": result,
        "raw_payload_in_manifest": False,
        "external_mutations": 0,
        "transaction_snapshot_claim": False,
    }
    ref = persist_metadata(sink.root, metadata)
    return {**result, "metadata_manifest_ref": ref}
