"""Append native Edit coverage without rewriting any existing teacher cell.

Pure planning and exact native readback only. Callers own immutable storage,
freshness checks, durable dispatch and transport; this module has no API client.
The original baseline remains authoritative for every old target, including all
submission context. Only newly introduced targets receive fresh baselines.
"""

from __future__ import annotations

import copy
import math
from typing import Any, cast

from . import native
from .client import GradebookError
from .get_only_refresh import validate_get_workbook
from .model import digest, grade_value, identifier
from .native_edit_review import _axes, extract_native_edits
from .refresh import cell, grade_validation_formula
from .workbook import column_name, edits_from_cells

MODE = "EDIT_AXIS_APPEND"


def _inventory(snapshot: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    try:
        if (
            type(snapshot["schema_version"]) is not int
            or snapshot["schema_version"] != 1
            or not isinstance(snapshot["cells"], dict)
            or type(snapshot["origin"]) is not str
            or type(snapshot["course_id"]) is not str
            or identifier(snapshot["course_id"]) != snapshot["course_id"]
            or type(snapshot["fetched_at"]) is not str
        ):
            raise ValueError
        inventories = []
        for field in ("students", "assignments"):
            if not isinstance(snapshot[field], list) or not snapshot[field]:
                raise ValueError
            indexed = {}
            for item in snapshot[field]:
                if not isinstance(item, dict) or type(item.get("id")) is not str:
                    raise ValueError
                key = identifier(item["id"])
                if key in indexed or type(item.get("name")) is not str:
                    raise ValueError
                if field == "students":
                    if not isinstance(item.get("sections"), list) or any(
                        type(value) is not str for value in item["sections"]
                    ):
                        raise ValueError
                else:
                    maximum = item.get("points_possible")
                    if (
                        not isinstance(maximum, (int, float))
                        or isinstance(maximum, bool)
                        or not math.isfinite(maximum)
                        or maximum < 0
                        or type(item.get("grading_type")) is not str
                    ):
                        raise ValueError
                indexed[key] = item
            inventories.append(indexed)
        students, assignments = inventories
        for key, item in snapshot["cells"].items():
            if type(key) is not str or not isinstance(item, dict):
                raise ValueError
            parts = key.split(":")
            if (
                len(parts) != 2
                or parts[0] not in students
                or parts[1] not in assignments
            ):
                raise ValueError
            value = grade_value(item.get("value"))
            if value != item.get("value") or (value == "EX") != (
                item.get("excused") is True
            ):
                raise ValueError
        digest(snapshot)
        return students, assignments
    except (KeyError, TypeError, ValueError, GradebookError) as exc:
        raise GradebookError("Edit axis snapshot structure is invalid.") from exc


def _rectangle(sid: int, end_row: int, end_col: int) -> dict[str, int]:
    return {
        "sheetId": sid,
        "startRowIndex": 5,
        "endRowIndex": end_row,
        "startColumnIndex": 2,
        "endColumnIndex": end_col,
    }


def _owned_rule(
    sheet: dict[str, Any],
    binding: dict[str, Any],
    old_row: int,
    old_col: int,
    get_row: int,
    get_col: int,
    new_row: int,
    new_col: int,
) -> dict[str, Any]:
    rules = sheet["conditionalFormats"]
    if not rules:
        raise GradebookError("Edit axis owned highlight rule is unavailable.")
    # Historical native workbooks escaped sheet-name apostrophes inside the
    # INDIRECT string. Recognize only that exact canonical legacy spelling.
    found = copy.deepcopy(rules[0])
    normalized = copy.deepcopy(found)
    try:
        formula = normalized["booleanRule"]["condition"]["values"][0][
            "userEnteredValue"
        ]
        normalized["booleanRule"]["condition"]["values"][0]["userEnteredValue"] = (
            formula.replace("\\'", "'")
        )
    except (KeyError, TypeError, AttributeError, IndexError) as exc:
        raise GradebookError("Edit axis owned highlight rule differs.") from exc
    approved = native._rule(binding, old_row, old_col)
    if normalized != approved:
        raise GradebookError("Edit axis owned highlight rule differs.")
    fresh = native._rule(binding, get_row, get_col)
    # Only bounds change: retain the existing rule's exact format fields.
    found["ranges"] = [_rectangle(binding["sheets"]["Working"], new_row, new_col)]
    fresh_formula = fresh["booleanRule"]["condition"]["values"][0]["userEnteredValue"]
    if "\\'" in formula:
        fresh_formula = fresh_formula.replace("'", "\\'")
    found["booleanRule"]["condition"]["values"][0]["userEnteredValue"] = fresh_formula
    return cast(dict[str, Any], found)


def plan_edit_axis_refresh(
    course: str,
    binding: dict[str, Any],
    before_raw: dict[str, Any],
    baseline: dict[str, Any],
    current: dict[str, Any],
) -> dict[str, Any]:
    """Plan empty-slot appends, keeping old physical cells and old evidence."""
    views = validate_get_workbook(before_raw, {course: binding})[course]
    old_students, old_assignments = _inventory(baseline)
    fresh_students, fresh_assignments = _inventory(current)
    original_edits = extract_native_edits(before_raw, binding, baseline)
    if (current.get("course_id"), current.get("origin")) != (
        identifier(binding["course_id"]),
        baseline.get("origin"),
    ):
        raise GradebookError("Edit axis snapshot course or origin differs.")
    if views["_Sync"].get("B9") != digest(current):
        raise GradebookError(
            "Edit axis source differs from the protected GET snapshot reference."
        )
    if not set(old_students) <= set(fresh_students) or not set(old_assignments) <= set(
        fresh_assignments
    ):
        raise GradebookError("Edit axis removals require separate reconciliation.")
    if any(
        (item["points_possible"], item["grading_type"])
        != (
            fresh_assignments[aid]["points_possible"],
            fresh_assignments[aid]["grading_type"],
        )
        for aid, item in old_assignments.items()
    ):
        raise GradebookError("Edit axis existing grading schema changed.")
    state = native._state(before_raw)
    sid = binding["sheets"]["Working"]
    sheet = state["sheets"][sid]
    rows, cols = _axes(sheet)
    new_students = [
        item for key, item in fresh_students.items() if key not in old_students
    ]
    new_assignments = [
        item for key, item in fresh_assignments.items() if key not in old_assignments
    ]
    old_row, old_col = 5 + len(rows), 2 + len(cols)
    new_row, new_col = old_row + len(new_students), old_col + len(new_assignments)
    grid = sheet["properties"]["gridProperties"]
    if new_row > grid["rowCount"] or new_col > grid["columnCount"]:
        raise GradebookError("Edit axis appends exceed existing empty grid capacity.")
    if new_row > 1000 or new_col > 258:
        raise GradebookError("Edit axis appends exceed the supported populated shape.")
    get_rows, get_cols = _axes(state["sheets"][binding["sheets"]["Canvas"]])
    if set(get_rows.values()) != set(fresh_students) or set(get_cols.values()) != set(
        fresh_assignments
    ):
        raise GradebookError(
            "Edit axis fresh targets are absent from the protected GET mirror."
        )
    for col, aid in get_cols.items():
        assignment = fresh_assignments[aid]
        label = views["Canvas"].get(f"{column_name(col + 1)}3")
        maximum = views["Canvas"].get(f"{column_name(col + 1)}4")
        if label not in (assignment["name"], "'" + assignment["name"]) or (
            isinstance(maximum, bool) or maximum != assignment["points_possible"]
        ):
            raise GradebookError(
                "Edit axis protected GET labels or points differ from its snapshot."
            )
    surrogate_sync = {**views["_Sync"], "B2": digest(current)}
    if edits_from_cells({"Working": views["Canvas"], "_Sync": surrogate_sync}, current)[
        "edits"
    ]:
        raise GradebookError("Edit axis protected GET values differ from its snapshot.")
    protections = [
        p
        for candidate in state["sheets"].values()
        for p in candidate["protectedRanges"]
        if p.get("protectedRangeId") == binding["working_protection_id"]
    ]
    if (
        len(protections) != 1
        or not native._whole_sheet(protections[0], sid)
        or protections[0].get("unprotectedRanges")
        != [_rectangle(sid, old_row, old_col)]
    ):
        raise GradebookError("Edit axis owned protection differs.")
    rule = _owned_rule(
        sheet,
        binding,
        old_row,
        old_col,
        5 + len(get_rows),
        2 + len(get_cols),
        new_row,
        new_col,
    )
    # Audit normalization rounds RGB values. Sending those rounded values back
    # can move an eight-bit color channel. The rule has already been recognized
    # exactly above; retain its original API format and aliases on the wire.
    try:
        raw_sheet = next(
            item
            for item in before_raw["sheets"]
            if item["properties"]["sheetId"] == sid
        )
        raw_format = raw_sheet["conditionalFormats"][0]["booleanRule"]["format"]
        if not isinstance(raw_format, dict):
            raise ValueError
        rule["booleanRule"]["format"] = copy.deepcopy(raw_format)
    except (KeyError, IndexError, StopIteration, TypeError, ValueError) as exc:
        raise GradebookError("Edit axis raw owned highlight format is unavailable.") from exc
    merged = copy.deepcopy(baseline)
    merged["students"].extend(copy.deepcopy(new_students))
    merged["assignments"].extend(copy.deepcopy(new_assignments))
    new_uids = {item["id"] for item in new_students}
    new_aids = {item["id"] for item in new_assignments}
    new_targets = {
        f"{uid}:{aid}"
        for uid in fresh_students
        for aid in fresh_assignments
        if uid in new_uids or aid in new_aids
    }
    for key in new_targets:
        if key in current["cells"]:
            merged["cells"][key] = copy.deepcopy(current["cells"][key])
    merged["working_baseline"] = {
        "mode": MODE,
        "original_baseline_id": digest(baseline),
        "fresh_snapshot_id": digest(current),
        "retained_old_targets": len(rows) * len(cols),
        "new_targets": len(new_targets),
    }
    writes: dict[tuple[int, int], Any] = {}
    all_rows = dict(rows)
    all_cols = dict(cols)
    for index, item in enumerate(new_students, old_row):
        all_rows[index] = item["id"]
        writes[index, 0] = item["id"]
        writes[index, 1] = item["name"] + "\n" + ", ".join(item["sections"])
    for index, item in enumerate(new_assignments, old_col):
        all_cols[index] = item["id"]
        for row, field in ((2, "name"), (3, "points_possible"), (4, "id")):
            writes[row, index] = item[field]
    for row, uid in all_rows.items():
        for col, aid in all_cols.items():
            key = f"{uid}:{aid}"
            if key in new_targets:
                value = merged["cells"].get(key, {}).get("value")
                writes[row, col] = "Excused" if value == "EX" else value
    for row, col in writes:
        existing = sheet["cells"].get(f"{row}:{col}", {})
        if any(
            field in existing
            for field in ("userEnteredValue", "note", "dataValidation")
        ):
            raise GradebookError(
                "Edit axis append destination contains existing content."
            )
    requests: list[dict[str, Any]] = []
    # Compact contiguous row runs; no padding or broad clearing masks.
    for row in sorted({position[0] for position in writes}):
        positions = sorted(col for r, col in writes if r == row)
        groups: list[list[int]] = []
        for col in positions:
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
    for start_row, end_row, start_col, end_col in (
        (5, old_row, old_col, new_col),
        (old_row, new_row, 2, new_col),
    ):
        if start_row < end_row and start_col < end_col:
            requests.append(
                {
                    "setDataValidation": {
                        "range": {
                            "sheetId": sid,
                            "startRowIndex": start_row,
                            "endRowIndex": end_row,
                            "startColumnIndex": start_col,
                            "endColumnIndex": end_col,
                        },
                        "rule": {
                            "condition": {
                                "type": "CUSTOM_FORMULA",
                                "values": [
                                    {
                                        "userEnteredValue": grade_validation_formula(
                                            start_row, start_col
                                        ),
                                    }
                                ],
                            },
                            "strict": True,
                            "inputMessage": "Enter literal points, EX, or blank. Preview before pushing; blank never clears Canvas.",
                        },
                    }
                }
            )
    if writes:
        requests.extend(
            [
                {
                    "updateProtectedRange": {
                        "protectedRange": {
                            "protectedRangeId": binding["working_protection_id"],
                            "unprotectedRanges": [_rectangle(sid, new_row, new_col)],
                        },
                        "fields": "unprotectedRanges",
                    }
                },
                {
                    "updateConditionalFormatRule": {
                        "sheetId": sid,
                        "index": 0,
                        "rule": rule,
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
    # Serialize the native projection without touching inputs or reading a service.
    projected_raw = _raw(projected)
    expanded_edits = extract_native_edits(projected_raw, binding, merged)
    if expanded_edits["edits"] != original_edits["edits"]:
        raise GradebookError("Edit axis expansion changed existing teacher proposals.")
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
            "new_targets": len(new_targets),
            "retained_old_targets": len(rows) * len(cols),
            "preserved_original_edits": len(original_edits["edits"]),
        },
        "batch_update": {
            "spreadsheet_id": binding["spreadsheet_id"],
            "requests": requests,
        },
        "canvas_writes": 0,
    }


def _raw(state: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {"spreadsheetId": state["spreadsheetId"], "sheets": []}
    for sheet in state["sheets"].values():
        item = {
            key: copy.deepcopy(sheet[key])
            for key in (
                "properties",
                "protectedRanges",
                "conditionalFormats",
                "basicFilter",
            )
        }
        rows: list[dict[str, Any]] = []
        for address, value in sheet["cells"].items():
            row, col = map(int, address.split(":"))
            while len(rows) <= row:
                rows.append({"values": []})
            while len(rows[row]["values"]) <= col:
                rows[row]["values"].append({})
            rows[row]["values"][col] = copy.deepcopy(value)
        block = {"rowData": rows}
        for key in ("rowMetadata", "columnMetadata"):
            values: list[dict[str, Any]] = []
            for index, value in sheet[key].items():
                while len(values) <= int(index):
                    values.append({})
                values[int(index)] = copy.deepcopy(value)
            block[key] = values
        item["data"] = [block]
        result["sheets"].append(item)
    return result


def verify_edit_axis_output(
    before: dict[str, Any],
    after: dict[str, Any],
    plans: Any,
    bindings: dict[str, Any],
) -> None:
    """Recompile immutable evidence and compare every selected native field."""
    validate_get_workbook(before, bindings)
    validate_get_workbook(after, bindings)
    if not isinstance(plans, (dict, list, tuple)):
        raise GradebookError("Edit axis verification plans are invalid.")
    iterable = list(plans.values()) if isinstance(plans, dict) else list(plans)
    if any(
        not isinstance(plan, dict)
        or type(plan.get("course")) is not str
        or not isinstance(plan.get("original_baseline"), dict)
        or not isinstance(plan.get("current_snapshot"), dict)
        for plan in iterable
    ):
        raise GradebookError("Edit axis verification plans are invalid.")
    if len(iterable) != len(bindings) or {
        plan.get("course") for plan in iterable
    } != set(bindings):
        raise GradebookError(
            "Edit axis verification requires exact configured coverage."
        )
    expected = native._state(before)
    for plan in iterable:
        course = plan["course"]
        canonical = plan_edit_axis_refresh(
            course,
            bindings[course],
            before,
            plan["original_baseline"],
            plan["current_snapshot"],
        )
        if plan != canonical:
            raise GradebookError(
                "Edit axis immutable plan differs from canonical evidence."
            )
        native._apply_requests(
            expected, canonical["batch_update"]["requests"], bindings[course]
        )
        observed = extract_native_edits(
            after, bindings[course], canonical["merged_baseline"]
        )
        prior = extract_native_edits(
            before, bindings[course], canonical["original_baseline"]
        )
        if observed["edits"] != prior["edits"]:
            raise GradebookError(
                "Edit axis readback changed existing teacher proposals."
            )
    if native._comparable(expected, set()) != native._comparable(
        native._state(after), set()
    ):
        raise GradebookError(
            "Edit axis native readback differs from the exact preserved projection."
        )
