"""Read mapped native Edit proposals without interpreting opaque helper cells.

This adapter creates the existing keyed edit envelope and private review only.
It never changes Sheets, rebases an Edit baseline, prepares a publisher operation
or sends Canvas grades/comments. Legacy XLSX and full-sync guards stay unchanged.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from . import native
from .client import GradebookClient, GradebookError
from .get_only_refresh import validate_get_workbook
from .model import compare_edits, digest, identifier
from .native_review_coverage import coverage_summary
from .publish import write_review_html
from .store import Store
from .workbook import column_name, edits_from_cells


def _literal(cell: dict[str, Any]) -> Any:
    value = cell.get("userEnteredValue", {})
    if (
        not isinstance(value, dict) or len(value) > 1
        or set(value) - {"numberValue", "stringValue", "boolValue"}
    ):
        raise GradebookError("Mapped Edit cells require literal values; formulas are held.")
    return next(iter(value.values()), None)


def _axes(sheet: dict[str, Any]) -> tuple[dict[int, str], dict[int, str]]:
    students: dict[int, str] = {}
    assignments: dict[int, str] = {}
    for address, cell in sheet["cells"].items():
        row, col = map(int, address.split(":"))
        if not ((col == 0 and row >= 5) or (row == 4 and col >= 2)):
            continue
        value = _literal(cell)
        if value in (None, ""):
            continue
        key = identifier(value)
        target = students if col == 0 else assignments
        position = row if col == 0 else col
        if key in target.values():
            raise GradebookError("Mapped Edit identity keys are duplicated.")
        target[position] = key
    if (
        not students or not assignments
        or sorted(students) != list(range(5, 5 + len(students)))
        or sorted(assignments) != list(range(2, 2 + len(assignments)))
    ):
        raise GradebookError("Mapped Edit identity axes are incomplete or contain gaps.")
    return students, assignments


def extract_native_edits(
    raw: dict[str, Any], binding: dict[str, Any], baseline: dict[str, Any],
) -> dict[str, Any]:
    """Project only independently bound identity, label, maximum and grade cells."""
    if "working_layout" in baseline:
        from .sparse_edit_axis_refresh import extract_sparse_edits

        return extract_sparse_edits(raw, binding, baseline)
    views = validate_get_workbook(raw, {"bound": binding})["bound"]
    sync = views["_Sync"]
    if (
        sync["B2"] != digest(baseline)
        or (baseline.get("course_id"), baseline.get("origin"))
        != (identifier(binding["course_id"]), sync["B4"])
    ):
        raise GradebookError("Native Edit does not belong to the original trusted baseline.")
    state = native._state(raw)
    sheet = state["sheets"][binding["sheets"]["Working"]]
    students, assignments = _axes(sheet)
    expected_students = {item["id"]: item for item in baseline["students"]}
    expected_assignments = {item["id"]: item for item in baseline["assignments"]}
    if (
        len(expected_students) != len(baseline["students"])
        or len(expected_assignments) != len(baseline["assignments"])
        or set(students.values()) != set(expected_students)
        or set(assignments.values()) != set(expected_assignments)
    ):
        raise GradebookError("Mapped Edit targets differ from the original trusted baseline.")
    projected: dict[str, Any] = {}
    for col, aid in assignments.items():
        name = column_name(col + 1)
        assignment = expected_assignments[aid]
        title = _literal(sheet["cells"].get(f"2:{col}", {}))
        maximum = _literal(sheet["cells"].get(f"3:{col}", {}))
        if title not in (assignment["name"], "'" + assignment["name"]):
            raise GradebookError("Mapped Edit assignment label differs from its identity.")
        if (
            isinstance(maximum, bool)
            or maximum != assignment["points_possible"]
        ):
            raise GradebookError("Mapped Edit points differ from the original grading schema.")
        projected[f"{name}3"] = title
        projected[f"{name}4"] = maximum
        projected[f"{name}5"] = aid
    for row, uid in students.items():
        number = row + 1
        projected[f"A{number}"] = uid
        projected[f"B{number}"] = _literal(sheet["cells"].get(f"{row}:1", {}))
        # Canonical edits_from_cells checks the exact frozen student label and
        # validates every proposed grade; helper formulas never reach it.
        for col in assignments:
            projected[f"{column_name(col + 1)}{number}"] = _literal(
                sheet["cells"].get(f"{row}:{col}", {})
            )
    return edits_from_cells({"Working": projected, "_Sync": sync}, baseline)


def extract_from_raw(
    raw: dict[str, Any], binding: dict[str, Any], baseline: dict[str, Any],
) -> dict[str, Any]:
    """Explicit pure entry point for callers holding a captured native workbook."""
    return extract_native_edits(raw, binding, baseline)


async def prepare_review(
    client: GradebookClient, store: Store, course: str,
    binding: dict[str, Any], raw: dict[str, Any],
) -> dict[str, Any]:
    """Compare retained Edit intent with fresh Canvas; save private artifacts only."""
    if type(course) is not str or not course.strip():
        raise GradebookError("Native Edit review course alias is invalid.")
    views = validate_get_workbook(raw, {course: binding})[course]
    baseline_id = views["_Sync"]["B2"]
    baseline = store.load("snapshot", baseline_id)
    course_id = identifier(binding["course_id"])
    if (baseline.get("course_id"), baseline.get("origin")) != (course_id, client.origin):
        raise GradebookError("Native Edit review baseline course or origin differs.")
    edits = extract_native_edits(raw, binding, baseline)
    current = await client.snapshot(course_id)
    if (current.get("course_id"), current.get("origin")) != (course_id, client.origin):
        raise GradebookError("Native Edit fresh snapshot course or origin differs.")
    coverage = coverage_summary(baseline, current)
    snapshot_id, _ = store.save("snapshot", current)
    review = compare_edits(baseline, current, edits)
    review_id, path = store.save("review", review)
    review_file = write_review_html(store, review)
    receipt_id, _ = store.save("receipt", {
        "schema_version": 1, "kind": "NATIVE_EDIT_REVIEW",
        "course_id": course_id, "origin": client.origin,
        "binding_digest": digest(binding), "input_fingerprint": native.fingerprint(raw),
        "baseline_id": baseline_id, "canvas_snapshot_id": snapshot_id,
        "review_id": review_id, "created_at": datetime.now(UTC).isoformat(),
        "coverage": coverage,
        "canvas_writes": 0, "sheets_writes": 0,
    })
    return {
        "course": course, "review_id": review_id, "review_file": review_file,
        "local_file": str(path), "changes": len(review["changes"]),
        "counts": review["counts"], "baseline_id": baseline_id,
        "snapshot_id": snapshot_id, "receipt_id": receipt_id,
        "coverage": coverage,
        "canvas_writes": 0, "sheets_writes": 0,
    }
