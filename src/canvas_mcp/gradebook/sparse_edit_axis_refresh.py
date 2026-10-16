"""Explicit physical Edit axes that leave opaque helper columns in place.

All functions are pure. A versioned layout belongs to the immutable derived B2
baseline; ordinary native/XLSX/full-sync validation keeps its existing guards.
Only declared physical grades are projected into the existing dense envelope.
"""

from __future__ import annotations

import copy
from typing import Any

from . import native
from .client import GradebookError
from .edit_axis_refresh import _inventory, _raw
from .get_only_refresh import validate_get_workbook
from .model import digest, identifier
from .native_edit_review import _axes, _literal, extract_native_edits
from .refresh import cell, grade_validation_formula
from .workbook import column_name, edits_from_cells

MODE = "SPARSE_EDIT_AXIS_APPEND"
LAYOUT_MODE = "SPARSE_ASSIGNMENT_COLUMNS"
LAYOUT_KEYS = {
    "schema_version",
    "mode",
    "spreadsheet_id",
    "course_id",
    "working_sheet_id",
    "rows",
    "columns",
    "opaque_columns",
    "get_rows",
    "get_columns",
}


def _intervals(columns: dict[int, str]) -> list[tuple[int, int]]:
    intervals: list[tuple[int, int]] = []
    for col in sorted(columns):
        if intervals and intervals[-1][1] == col:
            intervals[-1] = (intervals[-1][0], col + 1)
        else:
            intervals.append((col, col + 1))
    return intervals


def _editable(
    sid: int, rows: dict[int, str], columns: dict[int, str]
) -> list[dict[str, int]]:
    return [
        {
            "sheetId": sid,
            "startRowIndex": 5,
            "endRowIndex": max(rows) + 1,
            "startColumnIndex": first,
            "endColumnIndex": last,
        }
        for first, last in _intervals(columns)
    ]


def _layout_axes(
    sheet: dict[str, Any],
    binding: dict[str, Any],
    baseline: dict[str, Any],
) -> tuple[dict[int, str], dict[int, str]]:
    """No implicit gap admission: keys, positions and exclusions are explicit."""
    try:
        layout = baseline["working_layout"]
        if (
            not isinstance(layout, dict)
            or set(layout) != LAYOUT_KEYS
            or (
                type(layout["schema_version"]) is not int
                or layout["schema_version"] != 1
                or layout["mode"] != LAYOUT_MODE
                or layout["spreadsheet_id"] != binding["spreadsheet_id"]
                or layout["course_id"] != identifier(binding["course_id"])
                or type(layout["working_sheet_id"]) is not int
                or layout["working_sheet_id"] != binding["sheets"]["Working"]
            )
        ):
            raise ValueError
        grid = sheet["properties"]["gridProperties"]
        result = []
        for field, minimum, maximum in (
            ("rows", 5, min(grid["rowCount"], 1000)),
            ("columns", 2, min(grid["columnCount"], 258)),
        ):
            items = layout[field]
            if not isinstance(items, list) or not items:
                raise ValueError
            indexed: dict[int, str] = {}
            for item in items:
                if (
                    not isinstance(item, dict)
                    or set(item) != {"id", "index"}
                    or (
                        type(item["id"]) is not str
                        or type(item["index"]) is not int
                        or not minimum <= item["index"] < maximum
                        or item["index"] in indexed
                        or item["id"] in indexed.values()
                    )
                ):
                    raise ValueError
                indexed[item["index"]] = identifier(item["id"])
            if list(indexed) != sorted(indexed):
                raise ValueError
            result.append(indexed)
        rows, columns = result
        if sorted(rows) != list(range(5, 5 + len(rows))) or len(columns) > 256:
            raise ValueError
        opaque = layout["opaque_columns"]
        expected_opaque = [
            col for col in range(2, max(columns) + 1) if col not in columns
        ]
        if (
            not isinstance(opaque, list)
            or any(type(col) is not int for col in opaque)
            or opaque != expected_opaque
        ):
            raise ValueError
        for field, minimum, maximum in (("get_rows", 6, 1000), ("get_columns", 3, 258)):
            if (
                type(layout[field]) is not int
                or not minimum <= layout[field] <= maximum
            ):
                raise ValueError
        students, assignments = _inventory(baseline)
        if set(rows.values()) != set(students) or set(columns.values()) != set(
            assignments
        ):
            raise ValueError
        for address, item in sheet["cells"].items():
            row, col = map(int, address.split(":"))
            if not ((col == 0 and row >= 5) or (row == 4 and col >= 2)):
                continue
            value = _literal(item)
            if value in (None, ""):
                continue
            expected = rows.get(row) if col == 0 else columns.get(col)
            if expected is None or identifier(value) != expected:
                raise ValueError
        for row, uid in rows.items():
            if identifier(_literal(sheet["cells"].get(f"{row}:0", {}))) != uid:
                raise ValueError
        for col, aid in columns.items():
            if identifier(_literal(sheet["cells"].get(f"4:{col}", {}))) != aid:
                raise ValueError
        return rows, columns
    except (KeyError, TypeError, ValueError, GradebookError) as exc:
        raise GradebookError(
            "Sparse Edit physical layout or identity axes differ."
        ) from exc


def _sparse_rule(
    binding: dict[str, Any],
    rows: dict[int, str],
    columns: dict[int, str],
    get_rows: int,
    get_columns: int,
) -> dict[str, Any]:
    rule = native._rule(binding, get_rows, get_columns)
    rule["ranges"] = [
        {
            "sheetId": binding["sheets"]["Working"],
            "startRowIndex": 5,
            "endRowIndex": max(rows) + 1,
            "startColumnIndex": 2,
            "endColumnIndex": max(columns) + 1,
        }
    ]
    value = rule["booleanRule"]["condition"]["values"][0]
    value["userEnteredValue"] = (
        '=IF(C$5="",FALSE,' + value["userEnteredValue"][1:] + ")"
    )
    return rule


def _wire_format(raw: dict[str, Any], sid: int) -> dict[str, Any]:
    """Retain source precision: normalized RGB floats are audit-only.

    Sheets quantizes RGB floats to eight-bit channels. Sending a rounded audit
    value can cross a channel boundary. Copy the independently recognized owned
    rule's raw format verbatim, including equivalent API color-style aliases.
    """
    try:
        sheet = next(
            item for item in raw["sheets"] if item["properties"]["sheetId"] == sid
        )
        value = sheet["conditionalFormats"][0]["booleanRule"]["format"]
        if not isinstance(value, dict):
            raise ValueError
        return copy.deepcopy(value)
    except (KeyError, IndexError, StopIteration, TypeError, ValueError) as exc:
        raise GradebookError(
            "Sparse Edit raw owned highlight format is unavailable."
        ) from exc


def _permission_ranges_equal(actual: Any, expected: list[dict[str, int]]) -> bool:
    """Only list order is immaterial; retain all fields and multiplicity."""
    if not isinstance(actual, list) or any(
        not isinstance(item, dict) for item in actual
    ):
        return False
    try:
        return sorted(actual, key=digest) == sorted(expected, key=digest)
    except (TypeError, ValueError):
        return False


def _permission_projection(
    state: dict[str, Any], bindings: dict[str, Any]
) -> dict[str, Any]:
    """Normalize only exact connector-owned score permission list ordering."""
    result = copy.deepcopy(state)
    for binding in bindings.values():
        protections = result["sheets"][binding["sheets"]["Working"]]["protectedRanges"]
        matches = [
            p
            for p in protections
            if p.get("protectedRangeId") == binding["working_protection_id"]
        ]
        if len(matches) != 1:
            raise GradebookError("Sparse Edit owned score protection differs.")
        ranges = matches[0].get("unprotectedRanges")
        if not isinstance(ranges, list) or any(
            not isinstance(item, dict) for item in ranges
        ):
            raise GradebookError("Sparse Edit owned score protection differs.")
        matches[0]["unprotectedRanges"] = sorted(ranges, key=digest)
    return native._comparable(result, set())


def _ownership(
    state: dict[str, Any],
    binding: dict[str, Any],
    rows: dict[int, str],
    columns: dict[int, str],
    expected_rule: dict[str, Any],
    *,
    legacy: bool = False,
) -> None:
    sid = binding["sheets"]["Working"]
    sheet = state["sheets"][sid]
    protections = [
        p
        for candidate in state["sheets"].values()
        for p in candidate["protectedRanges"]
        if p.get("protectedRangeId") == binding["working_protection_id"]
    ]
    if (
        len(protections) != 1
        or not native._whole_sheet(protections[0], sid)
        or not _permission_ranges_equal(
            protections[0].get("unprotectedRanges"), _editable(sid, rows, columns)
        )
    ):
        raise GradebookError("Sparse Edit owned score protection differs.")
    if not sheet["conditionalFormats"]:
        raise GradebookError("Sparse Edit owned highlight rule is unavailable.")
    actual = copy.deepcopy(sheet["conditionalFormats"][0])
    if legacy:
        try:
            value = actual["booleanRule"]["condition"]["values"][0]
            value["userEnteredValue"] = value["userEnteredValue"].replace("\\'", "'")
        except (KeyError, TypeError, AttributeError, IndexError) as exc:
            raise GradebookError("Sparse Edit owned highlight rule differs.") from exc
    if actual != expected_rule:
        raise GradebookError("Sparse Edit owned highlight rule differs.")


def extract_sparse_edits(
    raw: dict[str, Any],
    binding: dict[str, Any],
    baseline: dict[str, Any],
) -> dict[str, Any]:
    """Project only declared grade cells into an unchanged dense edit envelope."""
    views = validate_get_workbook(raw, {"bound": binding})["bound"]
    sync = views["_Sync"]
    if sync["B2"] != digest(baseline) or (
        baseline.get("course_id"),
        baseline.get("origin"),
    ) != (identifier(binding["course_id"]), sync["B4"]):
        raise GradebookError("Sparse Edit does not belong to its immutable baseline.")
    state = native._state(raw)
    sheet = state["sheets"][binding["sheets"]["Working"]]
    rows, columns = _layout_axes(sheet, binding, baseline)
    layout = baseline["working_layout"]
    _ownership(
        state,
        binding,
        rows,
        columns,
        _sparse_rule(
            binding,
            rows,
            columns,
            layout["get_rows"],
            layout["get_columns"],
        ),
    )
    assignments = {item["id"]: item for item in baseline["assignments"]}
    projected: dict[str, Any] = {}
    for logical_col, (physical_col, aid) in enumerate(columns.items(), 3):
        name = column_name(logical_col)
        assignment = assignments[aid]
        title = _literal(sheet["cells"].get(f"2:{physical_col}", {}))
        maximum = _literal(sheet["cells"].get(f"3:{physical_col}", {}))
        if title not in (assignment["name"], "'" + assignment["name"]) or (
            isinstance(maximum, bool) or maximum != assignment["points_possible"]
        ):
            raise GradebookError(
                "Sparse Edit mapped assignment label or points differ."
            )
        projected[f"{name}3"] = title
        projected[f"{name}4"] = maximum
        projected[f"{name}5"] = aid
        for physical_row in rows:
            projected[f"{name}{physical_row + 1}"] = _literal(
                sheet["cells"].get(f"{physical_row}:{physical_col}", {})
            )
    for row, uid in rows.items():
        projected[f"A{row + 1}"] = uid
        projected[f"B{row + 1}"] = _literal(sheet["cells"].get(f"{row}:1", {}))
    return edits_from_cells({"Working": projected, "_Sync": sync}, baseline)


def _get_source(
    views: dict[str, Any],
    state: dict[str, Any],
    binding: dict[str, Any],
    current: dict[str, Any],
) -> tuple[int, int]:
    fresh_students, fresh_assignments = _inventory(current)
    if views["_Sync"].get("B9") != digest(current):
        raise GradebookError(
            "Sparse Edit source differs from the protected GET reference."
        )
    rows, columns = _axes(state["sheets"][binding["sheets"]["Canvas"]])
    if set(rows.values()) != set(fresh_students) or set(columns.values()) != set(
        fresh_assignments
    ):
        raise GradebookError("Sparse Edit protected GET axes differ from its snapshot.")
    for col, aid in columns.items():
        assignment = fresh_assignments[aid]
        label = views["Canvas"].get(f"{column_name(col + 1)}3")
        maximum = views["Canvas"].get(f"{column_name(col + 1)}4")
        if label not in (assignment["name"], "'" + assignment["name"]) or (
            isinstance(maximum, bool) or maximum != assignment["points_possible"]
        ):
            raise GradebookError("Sparse Edit protected GET labels or points differ.")
    if edits_from_cells(
        {
            "Working": views["Canvas"],
            "_Sync": {
                **views["_Sync"],
                "B2": digest(current),
            },
        },
        current,
    )["edits"]:
        raise GradebookError(
            "Sparse Edit protected GET grades differ from its snapshot."
        )
    return max(rows) + 1, max(columns) + 1


def _updates(sid: int, writes: dict[tuple[int, int], Any]) -> list[dict[str, Any]]:
    requests = []
    for row in sorted({position[0] for position in writes}):
        groups: list[list[int]] = []
        for col in sorted(col for r, col in writes if r == row):
            if not groups or col != groups[-1][-1] + 1:
                groups.append([])
            groups[-1].append(col)
        for group in groups:
            requests.append(
                {
                    "updateCells": {
                        "start": {
                            "sheetId": sid,
                            "rowIndex": row,
                            "columnIndex": group[0],
                        },
                        "rows": [{"values": [cell(writes[row, col]) for col in group]}],
                        "fields": "userEnteredValue",
                    }
                }
            )
    return requests


def _validation(
    sid: int, start: int, end: int, columns: dict[int, str]
) -> list[dict[str, Any]]:
    if start == end:
        return []
    return [
        {
            "setDataValidation": {
                "range": {
                    "sheetId": sid,
                    "startRowIndex": start,
                    "endRowIndex": end,
                    "startColumnIndex": first,
                    "endColumnIndex": last,
                },
                "rule": {
                    "condition": {
                        "type": "CUSTOM_FORMULA",
                        "values": [
                            {
                                "userEnteredValue": grade_validation_formula(
                                    start, first
                                ),
                            }
                        ],
                    },
                    "strict": True,
                    "inputMessage": "Enter literal points, EX, or blank. Preview before pushing; blank never clears Canvas.",
                },
            }
        }
        for first, last in _intervals(columns)
    ]


def plan_sparse_edit_axis_refresh(
    course: str,
    binding: dict[str, Any],
    before_raw: dict[str, Any],
    baseline: dict[str, Any],
    current: dict[str, Any],
) -> dict[str, Any]:
    """Append after the last opaque column; never reuse or move existing cells."""
    views = validate_get_workbook(before_raw, {course: binding})[course]
    old_students, old_assignments = _inventory(baseline)
    fresh_students, fresh_assignments = _inventory(current)
    if (current["course_id"], current["origin"]) != (
        baseline["course_id"],
        baseline["origin"],
    ):
        raise GradebookError("Sparse Edit source course or origin differs.")
    if not set(old_students) <= set(fresh_students) or not set(old_assignments) <= set(
        fresh_assignments
    ):
        raise GradebookError(
            "Sparse Edit target removals require separate reconciliation."
        )
    if any(
        (item["points_possible"], item["grading_type"])
        != (
            fresh_assignments[aid]["points_possible"],
            fresh_assignments[aid]["grading_type"],
        )
        for aid, item in old_assignments.items()
    ):
        raise GradebookError("Sparse Edit existing grading schema changed.")
    state = native._state(before_raw)
    sid = binding["sheets"]["Working"]
    sheet = state["sheets"][sid]
    get_rows, get_columns = _get_source(views, state, binding, current)
    if "working_layout" in baseline:
        original_edits = extract_sparse_edits(before_raw, binding, baseline)
        rows, columns = _layout_axes(sheet, binding, baseline)
    else:
        original_edits = extract_native_edits(before_raw, binding, baseline)
        rows, columns = _axes(sheet)
        _ownership(
            state,
            binding,
            rows,
            columns,
            native._rule(
                binding,
                max(rows) + 1,
                max(columns) + 1,
            ),
            legacy=True,
        )
    new_students = [
        item for uid, item in fresh_students.items() if uid not in old_students
    ]
    new_assignments = [
        item for aid, item in fresh_assignments.items() if aid not in old_assignments
    ]
    old_end_row = max(rows) + 1
    last_column = max(columns)
    for address, item in sheet["cells"].items():
        _, col = map(int, address.split(":"))
        if (
            col >= 2
            and col not in columns
            and any(
                field in item
                for field in ("userEnteredValue", "note", "dataValidation")
            )
        ):
            last_column = max(last_column, col)
    all_rows, all_columns = dict(rows), dict(columns)
    for row, item in enumerate(new_students, old_end_row):
        all_rows[row] = item["id"]
    for col, item in enumerate(new_assignments, last_column + 1):
        all_columns[col] = item["id"]
    grid = sheet["properties"]["gridProperties"]
    if max(all_rows) >= min(grid["rowCount"], 1000) or max(all_columns) >= min(
        grid["columnCount"], 258
    ):
        raise GradebookError("Sparse Edit appends exceed existing empty grid capacity.")
    merged = copy.deepcopy(baseline)
    merged["students"].extend(copy.deepcopy(new_students))
    merged["assignments"].extend(copy.deepcopy(new_assignments))
    new_uids, new_aids = (
        {item["id"] for item in new_students},
        {item["id"] for item in new_assignments},
    )
    targets = {
        f"{uid}:{aid}"
        for uid in fresh_students
        for aid in fresh_assignments
        if uid in new_uids or aid in new_aids
    }
    for key in targets:
        if key in current["cells"]:
            merged["cells"][key] = copy.deepcopy(current["cells"][key])
    merged["working_baseline"] = {
        "mode": MODE,
        "original_baseline_id": digest(baseline),
        "fresh_snapshot_id": digest(current),
        "retained_old_targets": len(rows) * len(columns),
        "new_targets": len(targets),
    }
    merged["working_layout"] = {
        "schema_version": 1,
        "mode": LAYOUT_MODE,
        "spreadsheet_id": binding["spreadsheet_id"],
        "course_id": baseline["course_id"],
        "working_sheet_id": sid,
        "rows": [{"id": uid, "index": row} for row, uid in all_rows.items()],
        "columns": [{"id": aid, "index": col} for col, aid in all_columns.items()],
        "opaque_columns": [
            col for col in range(2, max(all_columns) + 1) if col not in all_columns
        ],
        "get_rows": get_rows,
        "get_columns": get_columns,
    }
    writes: dict[tuple[int, int], Any] = {}
    for row, uid in all_rows.items():
        if uid in new_uids:
            item = fresh_students[uid]
            writes[row, 0], writes[row, 1] = (
                uid,
                item["name"] + "\n" + ", ".join(item["sections"]),
            )
    for col, aid in all_columns.items():
        if aid in new_aids:
            item = fresh_assignments[aid]
            for row, field in ((2, "name"), (3, "points_possible"), (4, "id")):
                writes[row, col] = item[field]
        for row, uid in all_rows.items():
            key = f"{uid}:{aid}"
            if key in targets:
                value = merged["cells"].get(key, {}).get("value")
                writes[row, col] = "Excused" if value == "EX" else value
    for row, col in writes:
        if any(
            field in sheet["cells"].get(f"{row}:{col}", {})
            for field in ("userEnteredValue", "note", "dataValidation")
        ):
            raise GradebookError(
                "Sparse Edit append destination contains existing content."
            )
    requests = _updates(sid, writes)
    added_columns = {col: aid for col, aid in all_columns.items() if aid in new_aids}
    requests.extend(_validation(sid, 5, old_end_row, added_columns))
    requests.extend(_validation(sid, old_end_row, max(all_rows) + 1, all_columns))
    if writes:
        wire_rule = _sparse_rule(binding, all_rows, all_columns, get_rows, get_columns)
        wire_rule["booleanRule"]["format"] = _wire_format(before_raw, sid)
        requests.extend(
            [
                {
                    "updateProtectedRange": {
                        "protectedRange": {
                            "protectedRangeId": binding["working_protection_id"],
                            "unprotectedRanges": _editable(sid, all_rows, all_columns),
                        },
                        "fields": "unprotectedRanges",
                    }
                },
                {
                    "updateConditionalFormatRule": {
                        "sheetId": sid,
                        "index": 0,
                        "rule": wire_rule,
                    }
                },
                {
                    "updateCells": {
                        "start": {
                            "sheetId": binding["sheets"]["_Sync"],
                            "rowIndex": 1,
                            "columnIndex": 1,
                        },
                        "rows": [{"values": [cell(digest(merged))]}],
                        "fields": "userEnteredValue",
                    }
                },
            ]
        )
    else:
        merged = copy.deepcopy(baseline)
    projected = copy.deepcopy(state)
    native._apply_requests(projected, requests, binding)
    after_raw = _raw(projected)
    expanded_edits = (
        extract_sparse_edits(after_raw, binding, merged)
        if "working_layout" in merged
        else extract_native_edits(after_raw, binding, merged)
    )
    if expanded_edits["edits"] != original_edits["edits"]:
        raise GradebookError(
            "Sparse Edit expansion changed existing teacher proposals."
        )
    return {
        "mode": MODE,
        "course": course,
        "binding_digest": digest(binding),
        "input_fingerprint": native.fingerprint(before_raw),
        "previous_baseline_id": digest(baseline),
        "baseline_id": digest(merged),
        "canvas_snapshot_id": digest(current),
        "original_baseline": copy.deepcopy(baseline),
        "current_snapshot": copy.deepcopy(current),
        "merged_baseline": merged,
        "counts": {
            "new_students": len(new_students),
            "new_assignments": len(new_assignments),
            "new_targets": len(targets),
            "retained_old_targets": len(rows) * len(columns),
            "preserved_original_edits": len(original_edits["edits"]),
            "opaque_columns": len(
                merged.get("working_layout", {}).get("opaque_columns", [])
            ),
        },
        "batch_update": {
            "spreadsheet_id": binding["spreadsheet_id"],
            "requests": requests,
        },
        "canvas_writes": 0,
    }


def verify_sparse_edit_axis_output(
    before: dict[str, Any],
    after: dict[str, Any],
    plans: Any,
    bindings: dict[str, Any],
) -> None:
    """Independently regenerate exact requests and every native preserved field."""
    validate_get_workbook(before, bindings)
    validate_get_workbook(after, bindings)
    if not isinstance(plans, (dict, list, tuple)):
        raise GradebookError("Sparse Edit verification plans are invalid.")
    iterable = list(plans.values()) if isinstance(plans, dict) else list(plans)
    if any(
        not isinstance(plan, dict)
        or type(plan.get("course")) is not str
        or not isinstance(plan.get("original_baseline"), dict)
        or not isinstance(plan.get("current_snapshot"), dict)
        for plan in iterable
    ):
        raise GradebookError("Sparse Edit verification plans are invalid.")
    if len(iterable) != len(bindings) or {plan["course"] for plan in iterable} != set(
        bindings
    ):
        raise GradebookError(
            "Sparse Edit verification requires exact configured coverage."
        )
    expected = native._state(before)
    for plan in iterable:
        course = plan["course"]
        canonical = plan_sparse_edit_axis_refresh(
            course,
            bindings[course],
            before,
            plan["original_baseline"],
            plan["current_snapshot"],
        )
        if plan != canonical:
            raise GradebookError(
                "Sparse Edit immutable plan differs from canonical evidence."
            )
        native._apply_requests(
            expected, canonical["batch_update"]["requests"], bindings[course]
        )
        baseline = canonical["merged_baseline"]
        observed = (
            extract_sparse_edits(after, bindings[course], baseline)
            if "working_layout" in baseline
            else extract_native_edits(after, bindings[course], baseline)
        )
        original = canonical["original_baseline"]
        prior = (
            extract_sparse_edits(before, bindings[course], original)
            if "working_layout" in original
            else extract_native_edits(before, bindings[course], original)
        )
        if observed["edits"] != prior["edits"]:
            raise GradebookError(
                "Sparse Edit readback changed existing teacher proposals."
            )
    if _permission_projection(expected, bindings) != _permission_projection(
        native._state(after), bindings
    ):
        raise GradebookError(
            "Sparse Edit native readback differs from the exact preserved projection."
        )
