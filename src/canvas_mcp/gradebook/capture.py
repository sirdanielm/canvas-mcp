"""Receipt-bound private observations and permanent-PIN intake port.

No network, evidence download, grading, teacher acceptance or LMS write lives in
this module. Only the GET client may create a current observation receipt.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from .client import GradebookError
from .model import digest, identifier
from .pseudonymize_export import load_shared_pin_module
from .store import Store


def _require(condition: object, code: str) -> None:
    if not condition:
        raise GradebookError(code)


def _token(value: Any) -> bool:
    return (
        type(value) is str and re.fullmatch(r"[A-Za-z0-9_-]{1,128}", value) is not None
    )


def _hash(value: Any) -> bool:
    return type(value) is str and re.fullmatch(r"[a-f0-9]{64}", value) is not None


def intake_digest(value: Any) -> str:
    """LocalGrAss canonical-v1 hash; preserve existing Canvas Store hash IDs."""

    def validate(item: Any, depth: int = 0) -> None:
        _require(depth <= 64, "INTAKE_DIGEST_VALUE_INVALID")
        if item is None or type(item) in (str, int, bool):
            return
        if type(item) in (list, tuple):
            for child in item:
                validate(child, depth + 1)
            return
        if type(item) is dict and all(type(key) is str for key in item):
            for child in item.values():
                validate(child, depth + 1)
            return
        raise GradebookError("INTAKE_DIGEST_VALUE_INVALID")

    try:
        validate(value)
        raw = json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
        _require(len(raw) <= 1024 * 1024, "INTAKE_DIGEST_VALUE_INVALID")
        return hashlib.sha256(raw).hexdigest()
    except (UnicodeError, RecursionError):
        raise GradebookError("INTAKE_DIGEST_VALUE_INVALID") from None


def save_capture(store: Store, snapshot: dict[str, Any]) -> str:
    """Called after a fully returned GET-only snapshot, never a workbook baseline."""
    _require(
        snapshot.get("schema_version") == 1
        and isinstance(snapshot.get("fetched_at"), str),
        "CAPTURE_INVALID",
    )
    snapshot_id, _ = store.save("snapshot", snapshot)
    receipt = {
        "schema_version": 1,
        "kind": "CANVAS_GET_CAPTURE",
        "snapshot_id": snapshot_id,
        "origin": snapshot["origin"],
        "course_id": identifier(snapshot["course_id"]),
        "captured_at": snapshot["fetched_at"],
        "capture_state": "COMPLETE",
        "scope": snapshot["scope"],
        "canvas_writes": 0,
    }
    receipt_id, _ = store.save("receipt", receipt)
    return receipt_id


def build_case_receipt(
    store: Store,
    capture_receipt_id: str,
    *,
    expected_origin: str,
    expected_course_id: str,
    assignment_id: str,
    academic_assignment_id: str,
    user_id: str,
    case_id: str,
    sources: list[dict[str, Any]],
    records: list[dict[str, Any]],
    expected_record_keys: list[str],
    registry_path: Path,
    shared_tool: Path,
) -> dict[str, Any]:
    """Join one exact Canvas observation to the shared canonical PIN authority.

    Source records are independently selected private operator metadata. This
    port binds them; LocalGrAss must verify original bytes and trusted retained
    expectations before admission. It never infers scan ownership from a name.
    """
    course_id, aid, uid = (
        identifier(value) for value in (expected_course_id, assignment_id, user_id)
    )
    _require(_token(case_id), "CASE_REFERENCE_INVALID")
    _require(
        type(academic_assignment_id) is str
        and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}", academic_assignment_id),
        "ACADEMIC_ASSIGNMENT_INVALID",
    )
    capture = store.load("receipt", capture_receipt_id)
    _require(
        set(capture)
        == {
            "schema_version",
            "kind",
            "snapshot_id",
            "origin",
            "course_id",
            "captured_at",
            "capture_state",
            "scope",
            "canvas_writes",
        }
        and capture["schema_version"] == 1
        and capture["kind"] == "CANVAS_GET_CAPTURE"
        and capture["capture_state"] == "COMPLETE"
        and capture["canvas_writes"] == 0
        and capture["origin"] == expected_origin
        and capture["course_id"] == course_id,
        "CAPTURE_SCOPE_MISMATCH",
    )
    snapshot = store.load("snapshot", capture["snapshot_id"])
    _require(
        snapshot.get("schema_version") == 1
        and snapshot.get("origin") == expected_origin
        and snapshot.get("course_id") == course_id
        and snapshot.get("fetched_at") == capture["captured_at"]
        and snapshot.get("scope") == capture["scope"],
        "CAPTURE_SCOPE_MISMATCH",
    )
    students, assignments, cells = (
        snapshot.get(key) for key in ("students", "assignments", "cells")
    )
    if not (
        isinstance(students, list)
        and isinstance(assignments, list)
        and isinstance(cells, dict)
    ):
        raise GradebookError("CAPTURE_INCOMPLETE")
    student_ids = [identifier(row.get("id")) for row in students]
    assignment_ids = [identifier(row.get("id")) for row in assignments]
    _require(
        len(student_ids) == len(set(student_ids))
        and len(assignment_ids) == len(set(assignment_ids))
        and uid in student_ids
        and aid in assignment_ids,
        "CAPTURE_TARGET_MISMATCH",
    )
    # Complete assignment coverage is counted from populated exact Canvas keys.
    _require(
        all(f"{student}:{aid}" in cells for student in student_ids),
        "CAPTURE_INCOMPLETE",
    )
    cell = cells[f"{uid}:{aid}"]
    _require(
        type(cell) is dict
        and cell.get("visible") is True
        and type(cell.get("attempt")) is int
        and cell["attempt"] >= 0,
        "CAPTURE_TARGET_HELD",
    )
    _require(registry_path.is_absolute(), "ABSOLUTE_REGISTRY_REQUIRED")
    shared = load_shared_pin_module(shared_tool)
    try:
        registry, roster, raw, registry_hash = shared.binding(registry_path)
        _require(
            registry.get("roster_sheet") == "Student Info",
            "CURRENT_PIN_AUTHORITY_REQUIRED",
        )
        headers, rows = shared.read_table(roster, raw, registry["roster_sheet"])
        index, _ = shared.roster_index(headers, rows, registry)
        _require("Canvas ID" in headers, "CANVAS_PIN_JOIN_UNAVAILABLE")
        by_canvas: dict[str, str] = {}
        for row in rows:
            if not any(
                value is not None and str(value).strip() for value in row.values()
            ):
                continue
            row_id = identifier(row["Canvas ID"])
            email = row[registry.get("email_column", "Email")]
            _require(
                type(email) is str and row_id not in by_canvas,
                "CANVAS_PIN_JOIN_CONFLICT",
            )
            pin = index[email.strip().casefold()]
            _require(
                type(pin) is str and re.fullmatch(r"[0-9]{4}", pin),
                "CANONICAL_PIN_INVALID",
            )
            by_canvas[row_id] = pin
        _require(uid in by_canvas, "CANONICAL_IDENTITY_UNRESOLVED")
        _require(
            hashlib.sha256(registry_path.read_bytes()).hexdigest() == registry_hash
            and hashlib.sha256(roster.read_bytes()).hexdigest()
            == registry["roster_sha256"],
            "PIN_AUTHORITY_CHANGED",
        )
    except GradebookError:
        raise
    except Exception:
        raise GradebookError("CANONICAL_IDENTITY_UNAVAILABLE") from None
    _require(
        type(sources) is list
        and 1 <= len(sources) <= 64
        and type(records) is list
        and 1 <= len(records) <= 64
        and type(expected_record_keys) is list
        and all(_token(k) for k in expected_record_keys)
        and len(set(expected_record_keys)) == len(expected_record_keys),
        "SOURCE_CATALOG_INVALID",
    )
    refs: list[str] = []
    for source in sources:
        _require(
            type(source) is dict
            and set(source)
            == {"source_ref", "relative_path", "sha256", "size_bytes", "schema_version"}
            and type(source["schema_version"]) is int
            and source["schema_version"] == 1
            and _token(source["source_ref"])
            and _hash(source["sha256"])
            and type(source["size_bytes"]) is int
            and 0 < source["size_bytes"] <= 16 * 1024 * 1024
            and type(source["relative_path"]) is str
            and bool(source["relative_path"])
            and len(source["relative_path"]) <= 1024
            and not source["relative_path"].startswith("/")
            and "\\" not in source["relative_path"]
            and all(
                part not in ("", ".", "..")
                for part in source["relative_path"].split("/")
            )
            and all(
                ord(char) >= 32 and ord(char) != 127 for char in source["relative_path"]
            ),
            "SOURCE_CATALOG_INVALID",
        )
        refs.append(source["source_ref"])
    _require(
        len(set(refs)) == len(refs)
        and len({source["relative_path"] for source in sources}) == len(sources)
        and len({source["sha256"] for source in sources}) == len(sources)
        and sum(s["size_bytes"] for s in sources) <= 64 * 1024 * 1024,
        "SOURCE_CATALOG_INVALID",
    )
    actual_keys: list[str] = []
    covered: list[str] = []
    for record in records:
        _require(
            type(record) is dict
            and set(record) == {"record_key", "source_refs"}
            and _token(record["record_key"])
            and type(record["source_refs"]) is list
            and bool(record["source_refs"])
            and all(_token(ref) for ref in record["source_refs"]),
            "SOURCE_RECORD_INVALID",
        )
        actual_keys.append(record["record_key"])
        covered.extend(record["source_refs"])
    _require(
        len(actual_keys) == len(set(actual_keys))
        and set(actual_keys) == set(expected_record_keys)
        and len(covered) == len(set(covered))
        and set(covered) == set(refs),
        "SOURCE_COVERAGE_MISMATCH",
    )
    identity_revision = "identity-" + digest(
        {"registry_sha256": registry_hash, "snapshot_sha256": registry["roster_sha256"]}
    )
    return {
        "schema_version": 1,
        "producer": "CANVAS_READ_ONLY_CAPTURE",
        "course_id": course_id,
        "assignment_id": academic_assignment_id,
        "canvas_assignment_id": aid,
        "case_id": case_id,
        "capture_revision": capture_receipt_id,
        "capture_state": "COMPLETE",
        "identity": {
            "authority": "CANVAS_MCP_GRADEBOOK_MIRROR",
            "revision": identity_revision,
            "registry_sha256": registry_hash,
            "snapshot_sha256": registry["roster_sha256"],
            "state": "RESOLVED",
            "student_pin": by_canvas[uid],
        },
        "expected_record_keys": sorted(expected_record_keys),
        "records": sorted(records, key=lambda record: record["record_key"]),
        "sources": sorted(sources, key=lambda source: source["source_ref"]),
        "scoring_manifest": {"schema_version": 1, "source_refs": sorted(refs)},
    }
