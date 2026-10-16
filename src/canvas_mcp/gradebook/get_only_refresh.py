"""Protected GET refreshes that preserve every Edit field and its baseline.

This planner has no Google or Canvas write transport. Working tabs are opaque:
their formulas, extra cells and notes are included in native preservation checks
but never parsed as grade proposals. Full-sync and publication guards stay separate.
"""

from __future__ import annotations

import copy
import re
from datetime import UTC, datetime
from typing import Any

from . import native
from .client import GradebookClient, GradebookError
from .model import digest, identifier
from .refresh import build_requests, cell
from .store import Store
from .workbook import column_name, edits_from_cells

MODE = "GET_ONLY"
_KINDS = {
    "updateSheetProperties", "repeatCell", "updateCells",
    "updateDimensionProperties", "updateBorders",
}
_UNIT1_DISPLAY_ORIGIN = "https://fcps.instructure.com"
_UNIT1_DISPLAY_BOOK_URL = (
    "https://docs.google.com/spreadsheets/d/13ps0FZLBj2qpclMNKo7Eb95kE4Sb_fgf9s7Ki2_KoNc"
)
_UNIT1_DISPLAY_PAIRS = frozenset({("363308", "4099721"), ("374070", "4099724")})


def validate_get_workbook(
    raw: dict[str, Any], bindings: dict[str, Any]
) -> dict[str, dict[str, dict[str, Any]]]:
    """Validate GET ownership without interpreting or constraining Edit data."""
    state = native._state(raw)
    if not isinstance(bindings, dict) or not 1 <= len(bindings) <= 10:
        raise GradebookError("GET refresh requires bounded configured bindings.")
    claimed: set[int] = set()
    result = {}
    for course, binding in bindings.items():
        if type(course) is not str or not course.strip() or not isinstance(binding, dict):
            raise GradebookError("GET refresh workbook binding differs.")
        sheet_ids = binding.get("sheets")
        names = binding.get("tab_names")
        if (
            type(binding.get("spreadsheet_id")) is not str
            or binding["spreadsheet_id"] != state["spreadsheetId"]
            or not isinstance(sheet_ids, dict) or set(sheet_ids) != native.ROLES
            or not isinstance(names, dict) or set(names) != native.ROLES
        ):
            raise GradebookError("GET refresh workbook binding differs.")
        if (
            any(type(value) is not int or value < 0 for value in sheet_ids.values())
            or len(set(sheet_ids.values())) != len(native.ROLES)
            or any(type(value) is not str or not value.strip() for value in names.values())
            or len(set(names.values())) != len(native.ROLES)
            or type(binding.get("label")) is not str or not binding["label"].strip()
            or type(binding.get("working_protection_id")) is not int
            or binding["working_protection_id"] < 0
            or type(binding.get("course_id")) not in (str, int)
        ):
            raise GradebookError("GET refresh workbook binding differs.")
        course_id = identifier(binding["course_id"])
        mapped = {}
        for role in sorted(native.ROLES):
            sid = sheet_ids[role]
            sheet = state["sheets"].get(sid)
            if (
                sid in claimed or sheet is None
                or sheet["properties"]["title"] != names[role]
            ):
                raise GradebookError("GET refresh sheet identity or name differs.")
            claimed.add(sid)
            if role == "Working":
                continue  # No literal parser: all Edit fields remain opaque.
            mapped[role] = native._literal_cells(sheet)
            if not any(
                native._whole_sheet(p, sid) and not p.get("unprotectedRanges")
                for p in sheet["protectedRanges"]
            ):
                raise GradebookError("GET or metadata protection differs.")
            if role == "_Sync":
                if not sheet["properties"].get("hidden", False):
                    raise GradebookError("GET metadata sheet is no longer hidden.")
            else:
                grid = sheet["properties"]["gridProperties"]
                if (
                    grid.get("frozenRowCount", 0) != 5
                    or grid.get("frozenColumnCount", 0) != 2
                    or not sheet["rowMetadata"].get("4", {}).get("hiddenByUser", False)
                    or not sheet["columnMetadata"].get("0", {}).get("hiddenByUser", False)
                ):
                    raise GradebookError("GET identity headers changed.")
                last_row, columns = native._shape(mapped[role])
                for address, item in sheet["cells"].items():
                    row, col = map(int, address.split(":"))
                    if (row >= last_row or col >= columns) and any(
                        key in item for key in ("userEnteredValue", "note")
                    ):
                        raise GradebookError("GET data exceeds its mapped grid.")
                _axes(mapped[role])
        sync = mapped["_Sync"]
        if (
            str(sync.get("B1")) != "1"
            or not isinstance(sync.get("B2"), str)
            or not re.fullmatch(r"[a-f0-9]{64}", sync["B2"])
            or str(sync.get("B3")) != course_id
            or not isinstance(sync.get("B4"), str)
        ):
            raise GradebookError("GET metadata course or baseline differs.")
        result[course] = mapped
    return result


def _axes(cells: dict[str, Any]) -> tuple[list[str], list[str]]:
    """Read exact keys in physical order, rejecting duplicates and blank gaps."""
    last_row, columns = native._shape(cells)
    students = [identifier(cells[f"A{row}"]) for row in range(6, last_row + 1)]
    assignments = [
        identifier(cells[f"{column_name(col)}5"]) for col in range(3, columns + 1)
    ]
    if len(set(students)) != len(students) or len(set(assignments)) != len(assignments):
        raise GradebookError("GET identity keys are duplicated.")
    return students, assignments


def _ordered(current: dict[str, Any], old: dict[str, Any]) -> dict[str, Any]:
    students, assignments = _axes(old)
    ordered = copy.deepcopy(current)
    for name, existing in (("students", students), ("assignments", assignments)):
        by_id = {item["id"]: item for item in ordered[name]}
        if len(by_id) != len(ordered[name]):
            raise GradebookError("Fresh GET snapshot contains duplicate keys.")
        known = set(existing)
        ordered[name] = [by_id[key] for key in existing if key in by_id] + [
            item for item in ordered[name] if item["id"] not in known
        ]
    return ordered


def _request_sid(request: dict[str, Any]) -> int | None:
    if len(request) != 1:
        raise GradebookError("GET refresh contains an invalid request.")
    kind, data = next(iter(request.items()))
    if kind == "updateSheetProperties":
        return int(data["properties"]["sheetId"])
    if kind == "updateCells":
        return int(data["start"]["sheetId"])
    if kind in {"repeatCell", "updateDimensionProperties", "updateBorders"}:
        return int(data["range"]["sheetId"])
    return None


def _unit1_number_display(
    requests: list[dict[str, Any]], current: dict[str, Any],
    binding: dict[str, Any], state: dict[str, Any],
) -> None:
    """Whole-number display for the exact authorized 100-point GET targets only."""
    book_id = _UNIT1_DISPLAY_BOOK_URL.rsplit("/", 1)[1]
    if (
        current.get("origin") != _UNIT1_DISPLAY_ORIGIN
        or binding.get("spreadsheet_id") != book_id
        or state.get("spreadsheetId") != book_id
        or current.get("course_id") != identifier(binding["course_id"])
    ):
        return
    for request in requests:
        update = request.get("updateCells")
        if update is None or update["start"]["sheetId"] != binding["sheets"]["Canvas"]:
            continue
        for column, assignment in enumerate(current["assignments"], 2):
            if (
                (current["course_id"], assignment["id"]) not in _UNIT1_DISPLAY_PAIRS
                or type(assignment.get("points_possible")) not in (int, float)
                or assignment["points_possible"] != 100
                or assignment.get("grading_type") != "points"
            ):
                continue
            for row in update["rows"][5:]:
                grade = row["values"][column]
                value = grade.get("userEnteredValue", {})
                if set(value) == {"numberValue"} and type(value["numberValue"]) in (int, float):
                    # Points out of 100 need NUMBER, not a multiplying percent format.
                    grade["userEnteredFormat"]["numberFormat"] = {"type": "NUMBER", "pattern": "0"}


def _requests(
    current: dict[str, Any], current_id: str,
    binding: dict[str, Any], state: dict[str, Any],
) -> list[dict[str, Any]]:
    sid = binding["sheets"]["Canvas"]
    sheet = state["sheets"][sid]
    old = native._literal_cells(sheet)
    students, assignments = _axes(old)
    grid = sheet["properties"]["gridProperties"]
    if max(len(students), len(current["students"])) + 5 > grid["rowCount"]:
        raise GradebookError("GET refresh requires an explicit row expansion.")
    generated = build_requests(
        current, current, current_id, binding,
        {"students": students, "assignments": assignments}, 0,
    )
    selected = []
    for request in generated:
        kind = next(iter(request))
        if kind in _KINDS and _request_sid(request) == sid:
            if kind == "updateSheetProperties":
                props = request[kind]["properties"]["gridProperties"]
                props["columnCount"] = max(grid["columnCount"], props["columnCount"])
            selected.append(request)
    if len(selected) != 7:
        raise GradebookError("Canonical GET renderer request contract changed.")
    _unit1_number_display(selected, current, binding, state)
    # B2 is the immutable Working baseline. Only fresh observation fields move.
    for row_index, value in ((4, current["fetched_at"]), (8, current_id)):
        selected.append({
            "updateCells": {
                "start": {"sheetId": binding["sheets"]["_Sync"],
                          "rowIndex": row_index, "columnIndex": 1},
                "rows": [{"values": [cell(value)]}], "fields": "userEnteredValue",
            }
        })
    return selected


async def prepare_get_only_refresh(
    client: GradebookClient, store: Store, course: str,
    binding: dict[str, Any], before_raw: dict[str, Any],
) -> dict[str, Any]:
    """Fetch one complete Canvas snapshot and prepare protected GET changes only."""
    views = validate_get_workbook(before_raw, {course: binding})[course]
    course_id = identifier(binding.get("course_id"))
    sync = views["_Sync"]
    baseline = store.load("snapshot", sync["B2"])
    if (
        sync["B4"] != client.origin
        or (baseline.get("course_id"), baseline.get("origin")) != (course_id, client.origin)
    ):
        raise GradebookError("GET baseline course or origin differs.")
    current = await client.snapshot(course_id)
    if (current.get("course_id"), current.get("origin")) != (course_id, client.origin):
        raise GradebookError("Fresh GET snapshot course or origin differs.")
    current = _ordered(current, views["Canvas"])
    current_id, _ = store.save("snapshot", current)
    plan = {
        "schema_version": 1, "mode": MODE, "course": course,
        "course_id": course_id, "origin": client.origin,
        "created_at": datetime.now(UTC).isoformat(),
        "binding_digest": digest(binding),
        "input_fingerprint": native.fingerprint(before_raw),
        "previous_baseline_id": sync["B2"], "baseline_id": sync["B2"],
        "canvas_snapshot_id": current_id,
        "edit_preserved": True,
        "batch_update": {
            "spreadsheet_id": binding["spreadsheet_id"],
            "requests": _requests(current, current_id, binding, native._state(before_raw)),
        },
    }
    plan_id, path = store.save("refresh", plan)
    return {**plan, "refresh_id": plan_id, "local_file": str(path)}


def verify_get_only_output(
    before: dict[str, Any], after: dict[str, Any], plans: Any,
    store: Store, bindings: dict[str, Any],
) -> None:
    """Verify complete GET observations and every preserved native field."""
    views = validate_get_workbook(before, bindings)
    output = validate_get_workbook(after, bindings)
    expected = native._state(before)
    iterable = list(plans.values()) if isinstance(plans, dict) else list(plans)
    if len(iterable) != len(bindings) or {p.get("course") for p in iterable} != set(bindings):
        raise GradebookError("GET verification requires every configured course.")
    for plan in iterable:
        course = plan["course"]
        binding = bindings[course]
        sync = views[course]["_Sync"]
        current_id = plan["canvas_snapshot_id"]
        current = store.load("snapshot", current_id)
        if (
            plan.get("mode") != MODE
            or plan.get("binding_digest") != digest(binding)
            or plan.get("input_fingerprint") != native.fingerprint(before)
            or plan.get("baseline_id") != sync["B2"]
            or plan.get("previous_baseline_id") != sync["B2"]
            or plan["batch_update"]["spreadsheet_id"] != before["spreadsheetId"]
            or (current.get("course_id"), current.get("origin"))
            != (identifier(binding["course_id"]), sync["B4"])
        ):
            raise GradebookError("GET refresh plan binding or provenance differs.")
        requests = _requests(current, current_id, binding, native._state(before))
        if plan["batch_update"]["requests"] != requests:
            raise GradebookError("GET refresh requests differ from canonical projection.")
        native._apply_requests(expected, requests, binding)
        surrogate = {
            "Working": output[course]["Canvas"],
            "_Sync": {"B1": 1, "B2": current_id,
                      "B3": current["course_id"], "B4": current["origin"]},
        }
        if edits_from_cells(surrogate, current)["edits"]:
            raise GradebookError("GET readback differs from its complete snapshot.")
    owned = {binding["sheets"]["Canvas"] for binding in bindings.values()}
    if native._comparable(expected, owned) != native._comparable(native._state(after), owned):
        raise GradebookError("GET refresh native readback differs; never replay writes.")
