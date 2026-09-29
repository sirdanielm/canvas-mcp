"""Native safety regressions: fictional grades, no remote transports."""

import copy

import pytest
from test_gradebook import snapshot as snapshot

from canvas_mcp.gradebook.client import GradebookError
from canvas_mcp.gradebook.model import digest
from canvas_mcp.gradebook.native import (
    _apply_requests,
    _state,
    fingerprint,
    validate_workbook,
    verify_native_output,
)
from canvas_mcp.gradebook.refresh import build_requests, source_digest
from canvas_mcp.gradebook.store import Store


@pytest.fixture
def binding():
    return {
        "label": "Fictional",
        "course_id": "12",
        "spreadsheet_id": "fictional-book",
        "sheets": {"Canvas": 1, "Working": 2, "_Sync": 3},
        "tab_names": {
            "Canvas": "Core GET",
            "Working": "Core Edit",
            "_Sync": "_Core Sync",
        },
        "working_protection_id": 102,
    }


def raw_from_state(state):
    """Serialize a simulated Sheets response; intentionally no student fixtures."""
    raw = {"spreadsheetId": state["spreadsheetId"], "sheets": []}
    for sheet in state["sheets"].values():
        result = {
            k: copy.deepcopy(sheet[k])
            for k in (
                "properties",
                "protectedRanges",
                "conditionalFormats",
                "basicFilter",
            )
        }
        rows = []
        for address, cell in sheet["cells"].items():
            r, c = map(int, address.split(":"))
            while len(rows) <= r:
                rows.append({"values": []})
            while len(rows[r]["values"]) <= c:
                rows[r]["values"].append({})
            rows[r]["values"][c] = copy.deepcopy(cell)
        block = {"rowData": rows}
        for key in ("rowMetadata", "columnMetadata"):
            block[key] = []
            for index, value in sheet[key].items():
                while len(block[key]) <= int(index):
                    block[key].append({})
                block[key][int(index)] = copy.deepcopy(value)
        result["data"] = [block]
        raw["sheets"].append(result)
    return raw


def initial_raw(snapshot, binding):
    state = {"spreadsheetId": binding["spreadsheet_id"], "sheets": {}}
    for role, sid in binding["sheets"].items():
        state["sheets"][sid] = {
            "properties": {
                "sheetId": sid,
                "title": binding["tab_names"][role],
                "sheetType": "GRID",
                "hidden": role == "_Sync",
                "gridProperties": {
                    "rowCount": 30,
                    "columnCount": 26,
                    "frozenRowCount": 5 if role != "_Sync" else 0,
                    "frozenColumnCount": 2 if role != "_Sync" else 0,
                },
            },
            "cells": {},
            "rowMetadata": {"4": {"hiddenByUser": True}} if role != "_Sync" else {},
            "columnMetadata": {"0": {"hiddenByUser": True}} if role != "_Sync" else {},
            "protectedRanges": [
                {
                    "protectedRangeId": 100 + sid,
                    "range": {"sheetId": sid},
                    "warningOnly": False,
                }
            ],
            "conditionalFormats": [{}] if role == "Working" else [],
            "basicFilter": {},
        }
    # A reference tab is deliberately outside the connector's three sheets.
    state["sheets"][4] = {
        "properties": {
            "sheetId": 4,
            "title": "Reference",
            "sheetType": "GRID",
            "gridProperties": {"rowCount": 10, "columnCount": 5},
        },
        "cells": {
            "0:0": {
                "userEnteredValue": {"stringValue": "Do not replace"},
                "note": "Reference note",
                "userEnteredFormat": {"textFormat": {"bold": True}},
            }
        },
        "rowMetadata": {},
        "columnMetadata": {},
        "protectedRanges": [],
        "conditionalFormats": [],
        "basicFilter": {},
    }
    requests = build_requests(
        snapshot, snapshot, digest(snapshot), binding, snapshot, 0
    )
    _apply_requests(state, requests, binding)
    return raw_from_state(state)


def plan_for(snapshot, binding, store, before=None):
    sid, _ = store.save("snapshot", snapshot)
    before = before if before is not None else initial_raw(snapshot, binding)
    return {
        "course": "core",
        "course_id": "12",
        "binding_digest": digest(binding),
        "input_digest": source_digest(
            validate_workbook(before, {"core": binding})["core"]
        ),
        "canvas_snapshot_id": sid,
        "baseline_id": sid,
        "pending_edits": [],
        "batch_update": {
            "spreadsheet_id": binding["spreadsheet_id"],
            "requests": build_requests(snapshot, snapshot, sid, binding, snapshot, 0),
        },
    }


def test_native_reads_literal_cells_and_rejects_wrong_binding(snapshot, binding):
    raw = initial_raw(snapshot, binding)
    cells = validate_workbook(raw, {"core": binding})
    assert cells["core"]["Working"]["C6"] == 10
    assert cells["core"]["_Sync"]["B2"] == digest(snapshot)
    raw["spreadsheetId"] = "wrong-book"
    with pytest.raises(GradebookError, match="binding"):
        validate_workbook(raw, {"core": binding})


@pytest.mark.parametrize(
    "change",
    [
        "rename",
        "identity",
        "protection",
        "editable",
        "hidden",
        "freeze",
        "rule",
        "formula",
        "outside",
    ],
)
def test_native_layout_ownership_holds(snapshot, binding, change):
    raw = initial_raw(snapshot, binding)
    edit = raw["sheets"][1]
    if change == "rename":
        edit["properties"]["title"] = "Other"
    elif change == "identity":
        edit["properties"]["sheetId"] = 20
    elif change == "protection":
        raw["sheets"][0]["protectedRanges"] = []
    elif change == "editable":
        edit["protectedRanges"][0]["unprotectedRanges"][0]["startColumnIndex"] = 0
    elif change == "hidden":
        edit["data"][0]["columnMetadata"][0]["hiddenByUser"] = False
    elif change == "freeze":
        edit["properties"]["gridProperties"]["frozenRowCount"] = 3
    elif change == "rule":
        edit["conditionalFormats"][0]["booleanRule"]["condition"]["values"][0][
            "userEnteredValue"
        ] = "=TRUE"
    elif change == "formula":
        edit["data"][0]["rowData"][5]["values"][2]["userEnteredValue"] = {
            "formulaValue": "=10"
        }
    else:
        edit["data"][0]["rowData"].append({"values": [{"note": "Outside owned rows"}]})
    with pytest.raises(GradebookError):
        validate_workbook(raw, {"core": binding})


def test_fingerprint_ignores_only_queue_metadata(snapshot, binding):
    raw = initial_raw(snapshot, binding)
    changed = copy.deepcopy(raw)
    changed["developerMetadata"] = [{"metadataId": 8, "metadataValue": "running"}]
    changed["sheets"][0]["developerMetadata"] = [{"metadataValue": "queue"}]
    assert fingerprint(changed) == fingerprint(raw)
    changed["sheets"][3]["data"][0]["rowData"][0]["values"][0]["note"] = "different"
    assert fingerprint(changed) != fingerprint(raw)


def test_native_verifies_canonical_value_and_structure(snapshot, binding, tmp_path):
    before = initial_raw(snapshot, binding)
    current = copy.deepcopy(snapshot)
    current["cells"]["101:21"]["value"] = 18
    current["cells"]["101:21"]["late"] = True
    store = Store(tmp_path)
    plan = plan_for(current, binding, store, before)
    state = _state(before)
    _apply_requests(state, plan["batch_update"]["requests"], binding)
    after = raw_from_state(state)
    verify_native_output(before, after, [plan], store, {"core": binding})
    assert validate_workbook(after, {"core": binding})["core"]["Canvas"]["C6"] == 18
    assert (
        "Late: True" in after["sheets"][0]["data"][0]["rowData"][5]["values"][2]["note"]
    )


@pytest.mark.parametrize(
    "change",
    [
        "grade",
        "note",
        "color",
        "validation",
        "reference_value",
        "reference_note",
        "reference_format",
        "protection",
        "row_height",
        "binding",
        "missing_plan",
    ],
)
def test_native_detects_output_corruption(snapshot, binding, tmp_path, change):
    before = initial_raw(snapshot, binding)
    after = copy.deepcopy(before)
    store = Store(tmp_path)
    plan = plan_for(snapshot, binding, store)
    grade = after["sheets"][0]["data"][0]["rowData"][5]["values"][2]
    reference = after["sheets"][3]["data"][0]["rowData"][0]["values"][0]
    if change == "grade":
        grade["userEnteredValue"]["numberValue"] = 19
    elif change == "note":
        grade["note"] = "Corrupted status"
    elif change == "color":
        grade["userEnteredFormat"]["backgroundColor"] = {"red": 1}
    elif change == "validation":
        del after["sheets"][1]["data"][0]["rowData"][5]["values"][2]["dataValidation"]
    elif change == "reference_value":
        reference["userEnteredValue"] = {"numberValue": 8}
    elif change == "reference_note":
        reference["note"] = "Changed"
    elif change == "reference_format":
        reference["userEnteredFormat"]["textFormat"]["bold"] = False
    elif change == "protection":
        after["sheets"][0]["protectedRanges"][0]["warningOnly"] = True
    elif change == "row_height":
        after["sheets"][0]["data"][0]["rowMetadata"][0]["pixelSize"] = 7
    elif change == "binding":
        plan["binding_digest"] = "wrong"
    plans = [] if change == "missing_plan" else [plan]
    with pytest.raises(GradebookError):
        verify_native_output(before, after, plans, store, {"core": binding})


def test_native_rejects_shrinking_columns_and_foreign_writes(snapshot, binding):
    raw = initial_raw(snapshot, binding)
    state = _state(raw)
    with pytest.raises(GradebookError, match="shrink"):
        _apply_requests(
            state,
            [
                {
                    "updateSheetProperties": {
                        "properties": {
                            "sheetId": 1,
                            "gridProperties": {"columnCount": 10},
                        },
                        "fields": "gridProperties.columnCount",
                    }
                }
            ],
            binding,
        )
    with pytest.raises(GradebookError, match="another sheet"):
        _apply_requests(
            state,
            [
                {
                    "updateCells": {
                        "start": {"sheetId": 4},
                        "rows": [],
                        "fields": "userEnteredValue",
                    }
                }
            ],
            binding,
        )
    with pytest.raises(GradebookError, match="unsupported"):
        _apply_requests(state, [{"deleteSheet": {"sheetId": 1}}], binding)


def test_duplicate_sheet_and_overlapping_native_data_hold(snapshot, binding):
    raw = initial_raw(snapshot, binding)
    raw["sheets"].append(copy.deepcopy(raw["sheets"][0]))
    with pytest.raises(GradebookError, match="duplicate"):
        fingerprint(raw)
    raw = initial_raw(snapshot, binding)
    raw["sheets"][0]["data"].append(copy.deepcopy(raw["sheets"][0]["data"][0]))
    with pytest.raises(GradebookError, match="overlapping"):
        fingerprint(raw)


def test_native_accepts_google_rgb_aliases_and_default_omissions(snapshot, binding):
    raw = initial_raw(snapshot, binding)
    raw["sheets"][3]["data"][0]["rowData"][0]["values"][0]["userEnteredFormat"][
        "backgroundColor"
    ] = {}
    changed = copy.deepcopy(raw)

    def aliases(value):
        if isinstance(value, list):
            for item in value:
                aliases(item)
        elif isinstance(value, dict):
            for key in list(value):
                item = value[key]
                aliases(item)
                if key in {"backgroundColor", "foregroundColor"}:
                    color = dict(item)
                    color["alpha"] = 1
                    value[key + "Style"] = {"rgbColor": color}
                    del value[key]
                elif key in {"warningOnly", "hidden"} and item is False:
                    del value[key]

    aliases(changed)
    assert fingerprint(raw) == fingerprint(changed)


def test_native_both_courses_require_both_plans_and_preserve_reference(
    snapshot, binding, tmp_path
):
    advanced_binding = copy.deepcopy(binding)
    advanced_binding.update(course_id="13", working_protection_id=106)
    advanced_binding["sheets"] = {"Canvas": 5, "Working": 6, "_Sync": 7}
    advanced_binding["tab_names"] = {
        "Canvas": "Adv GET",
        "Working": "Adv Edit",
        "_Sync": "_Adv Sync",
    }
    advanced = copy.deepcopy(snapshot)
    advanced["course_id"] = "13"
    before = initial_raw(snapshot, binding)
    before["sheets"].extend(initial_raw(advanced, advanced_binding)["sheets"][:3])
    bindings = {"core": binding, "advanced": advanced_binding}
    assert set(validate_workbook(before, bindings)) == set(bindings)
    store = Store(tmp_path)
    core_plan = plan_for(snapshot, binding, store, before)
    advanced_plan = plan_for(advanced, advanced_binding, store, before)
    advanced_plan["course"] = "advanced"
    plans = [core_plan, advanced_plan]
    state = _state(before)
    for plan in plans:
        _apply_requests(
            state, plan["batch_update"]["requests"], bindings[plan["course"]]
        )
    after = raw_from_state(state)
    verify_native_output(before, after, plans, store, bindings)
    with pytest.raises(GradebookError, match="every configured course"):
        verify_native_output(before, after, [core_plan], store, bindings)
    core_plan["input_digest"] = "wrong-input"
    with pytest.raises(GradebookError, match="preserved native input"):
        verify_native_output(before, after, plans, store, bindings)
