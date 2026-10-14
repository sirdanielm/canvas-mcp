"""Fictional sparse Edit layouts: helper columns remain protected and opaque."""

import copy
import json

import pytest
from test_gradebook import snapshot as snapshot
from test_gradebook_edit_axis_refresh import scenario as dense_scenario  # noqa: F401
from test_gradebook_native import binding as binding
from test_gradebook_native import initial_raw, raw_from_state

from canvas_mcp.gradebook import native
from canvas_mcp.gradebook import sparse_edit_axis_refresh as candidate
from canvas_mcp.gradebook.client import GradebookError
from canvas_mcp.gradebook.model import digest
from canvas_mcp.gradebook.native_edit_review import extract_native_edits
from canvas_mcp.gradebook.sparse_edit_axis_refresh import (
    extract_sparse_edits,
    plan_sparse_edit_axis_refresh,
    verify_sparse_edit_axis_output,
)


@pytest.fixture
def scenario(dense_scenario):  # noqa: F811 - imported pytest fixture alias
    before, binding, baseline, current = dense_scenario
    state = native._state(before)
    # A real worksheet can have a helper directly after the old grade axes.
    state["sheets"][2]["cells"]["5:3"] = {
        "userEnteredValue": {"formulaValue": "=SUM(C6)"},
        "note": "Private fictional helper",
        "userEnteredFormat": {"textFormat": {"italic": True}},
    }
    # The dense scenario's header helper is opaque too. Planners append after
    # every opaque non-format column, not only after the first collided grade.
    state["sheets"][2]["cells"].pop("0:8")
    return raw_from_state(state), binding, baseline, current


def prepared(scenario):
    before, binding, baseline, current = scenario
    plan = plan_sparse_edit_axis_refresh("core", binding, before, baseline, current)
    state = native._state(before)
    native._apply_requests(state, plan["batch_update"]["requests"], binding)
    return plan, raw_from_state(state)


def test_sparse_append_preserves_helper_every_old_field_and_all_context(scenario):
    before, binding, baseline, current = scenario
    untouched = copy.deepcopy(scenario)
    plan, after = prepared(scenario)
    assert scenario == untouched
    assert plan["counts"] == {
        "new_students": 1,
        "new_assignments": 1,
        "new_targets": 3,
        "retained_old_targets": 1,
        "preserved_original_edits": 1,
        "opaque_columns": 1,
    }
    merged = plan["merged_baseline"]
    assert merged["working_layout"]["columns"] == [
        {"id": "21", "index": 2},
        {"id": "22", "index": 4},
    ]
    assert merged["working_layout"]["opaque_columns"] == [3]
    assert merged["cells"]["101:21"] == baseline["cells"]["101:21"]
    assert merged["cells"]["101:22"] == current["cells"]["101:22"]
    assert "102:22" not in merged["cells"]
    old, new = native._state(before), native._state(after)
    for address in ("5:2", "5:3", "6:3"):
        assert old["sheets"][2]["cells"][address] == new["sheets"][2]["cells"][address]
    assert new["sheets"][2]["cells"]["5:4"]["userEnteredValue"] == {
        "stringValue": "Excused"
    }
    assert new["sheets"][2]["cells"]["6:2"]["userEnteredValue"] == {"numberValue": 0}
    assert "userEnteredValue" not in new["sheets"][2]["cells"]["6:4"]
    assert new["sheets"][2]["protectedRanges"][0]["unprotectedRanges"] == [
        {
            "sheetId": 2,
            "startRowIndex": 5,
            "endRowIndex": 7,
            "startColumnIndex": 2,
            "endColumnIndex": 3,
        },
        {
            "sheetId": 2,
            "startRowIndex": 5,
            "endRowIndex": 7,
            "startColumnIndex": 4,
            "endColumnIndex": 5,
        },
    ]
    rule = new["sheets"][2]["conditionalFormats"][0]
    formula = rule["booleanRule"]["condition"]["values"][0]["userEnteredValue"]
    assert formula.startswith('=IF(C$5="",FALSE,OR(')
    assert "$C$6:$D$7" in formula  # Dense GET bounds, not physical Edit bounds.
    assert rule["ranges"][0]["endColumnIndex"] == 5
    assert new["sheets"][1] == old["sheets"][1]
    assert new["sheets"][4] == old["sheets"][4]
    assert (
        extract_sparse_edits(after, binding, merged)["edits"]
        == extract_native_edits(before, binding, baseline)["edits"]
    )
    assert new["sheets"][3]["cells"]["8:1"] == old["sheets"][3]["cells"]["8:1"]
    assert new["sheets"][2]["properties"] == old["sheets"][2]["properties"]
    verify_sparse_edit_axis_output(
        before, after, json.loads(json.dumps([plan])), {"core": binding}
    )


def test_unknown_sparse_gap_without_layout_stays_held(scenario):
    _, binding, _, _ = scenario
    plan, after = prepared(scenario)
    unversioned = copy.deepcopy(plan["merged_baseline"])
    del unversioned["working_layout"]
    state = native._state(after)
    state["sheets"][3]["cells"]["1:1"]["userEnteredValue"] = {
        "stringValue": digest(unversioned)
    }
    with pytest.raises(GradebookError, match="gaps"):
        extract_native_edits(raw_from_state(state), binding, unversioned)


@pytest.mark.parametrize(
    "change",
    [
        "version_bool",
        "version",
        "mode",
        "workbook",
        "course",
        "sheet_bool",
        "sheet",
        "extra_field",
        "missing_field",
        "rows_not_list",
        "cols_not_list",
        "duplicate_id",
        "duplicate_position",
        "position_bool",
        "position_negative",
        "position_capacity",
        "position_unsorted",
        "unknown_id",
        "row_gap",
        "opaque_missing",
        "opaque_bool",
        "get_rows_bool",
        "get_cols_large",
    ],
)
def test_layout_never_guesses_or_admits_malformed_identity_positions(scenario, change):
    _, binding, _, _ = scenario
    plan, after = prepared(scenario)
    baseline = copy.deepcopy(plan["merged_baseline"])
    layout = baseline["working_layout"]
    if change in ("version_bool", "version"):
        layout["schema_version"] = True if change.endswith("bool") else 2
    elif change in ("mode", "workbook", "course", "sheet_bool", "sheet"):
        field = {
            "mode": "mode",
            "workbook": "spreadsheet_id",
            "course": "course_id",
            "sheet_bool": "working_sheet_id",
            "sheet": "working_sheet_id",
        }[change]
        layout[field] = (
            True
            if change == "sheet_bool"
            else (999 if change == "sheet" else "private-sentinel")
        )
    elif change == "extra_field":
        layout["unexpected"] = "private-sentinel"
    elif change == "missing_field":
        del layout["opaque_columns"]
    elif change in ("rows_not_list", "cols_not_list"):
        layout["rows" if change.startswith("rows") else "columns"] = {}
    elif change in (
        "duplicate_id",
        "duplicate_position",
        "position_bool",
        "position_negative",
        "position_capacity",
        "position_unsorted",
        "unknown_id",
    ):
        item = layout["columns"][1]
        if change == "duplicate_id":
            item["id"] = layout["columns"][0]["id"]
        elif change == "duplicate_position":
            item["index"] = layout["columns"][0]["index"]
        elif change == "position_unsorted":
            layout["columns"].reverse()
        elif change == "unknown_id":
            item["id"] = "private-sentinel"
        else:
            item["index"] = {
                "position_bool": True,
                "position_negative": -1,
                "position_capacity": 999,
            }[change]
    elif change == "row_gap":
        layout["rows"][1]["index"] = 8
    elif change == "opaque_missing":
        layout["opaque_columns"] = []
    elif change == "opaque_bool":
        layout["opaque_columns"] = [True]
    elif change == "get_rows_bool":
        layout["get_rows"] = True
    else:
        layout["get_columns"] = 999
    state = native._state(after)
    state["sheets"][3]["cells"]["1:1"]["userEnteredValue"] = {
        "stringValue": digest(baseline)
    }
    with pytest.raises(GradebookError) as error:
        extract_sparse_edits(raw_from_state(state), binding, baseline)
    assert "private-sentinel" not in str(error.value)


@pytest.mark.parametrize(
    "position,value",
    [
        ("4:3", {"stringValue": "999"}),
        ("4:4", {"stringValue": "999"}),
        ("7:0", {"stringValue": "999"}),
        ("5:4", {"formulaValue": "=20"}),
        ("2:4", {"stringValue": "private-sentinel"}),
        ("3:4", {"numberValue": 99}),
        ("6:1", {"stringValue": "private-sentinel"}),
        ("4:3", {"formulaValue": "=1"}),
    ],
)
def test_sparse_mapped_cells_and_reserved_identity_row_stay_strict(
    scenario, position, value
):
    _, binding, _, _ = scenario
    plan, after = prepared(scenario)
    state = native._state(after)
    state["sheets"][2]["cells"].setdefault(position, {})["userEnteredValue"] = value
    with pytest.raises(GradebookError) as error:
        extract_sparse_edits(raw_from_state(state), binding, plan["merged_baseline"])
    assert "private-sentinel" not in str(error.value)


def test_helper_formula_and_notes_remain_opaque_for_future_reviews(scenario):
    _, binding, _, _ = scenario
    plan, after = prepared(scenario)
    state = native._state(after)
    state["sheets"][2]["cells"]["5:3"]["userEnteredValue"] = {
        "formulaValue": "=SUM(C6,E6)"
    }
    state["sheets"][2]["cells"]["5:3"]["note"] = "Opaque updated teacher helper"
    result = extract_sparse_edits(
        raw_from_state(state), binding, plan["merged_baseline"]
    )
    assert result["edits"] == [{"user_id": "101", "assignment_id": "21", "value": 20}]
    assert "formulaValue" not in json.dumps(result)


@pytest.mark.parametrize(
    "change",
    [
        "helper_value",
        "helper_note",
        "old_note",
        "reference",
        "get",
        "metadata",
        "format",
        "validation",
        "editor",
        "protection",
        "rule",
        "plan",
    ],
)
def test_exact_readback_holds_all_unplanned_mutations(scenario, change):
    before, binding, _, _ = scenario
    plan, after = prepared(scenario)
    state = native._state(after)
    if change == "plan":
        plan["counts"]["opaque_columns"] = 2
    elif change == "editor":
        state["sheets"][2]["protectedRanges"][0]["editors"] = {"users": []}
    elif change == "protection":
        state["sheets"][2]["protectedRanges"][0]["unprotectedRanges"][0][
            "endColumnIndex"
        ] = 4
    elif change == "rule":
        state["sheets"][2]["conditionalFormats"][0]["booleanRule"]["condition"][
            "values"
        ][0]["userEnteredValue"] = "=TRUE"
    else:
        sid, address, field, value = {
            "helper_value": (2, "5:3", "userEnteredValue", {"formulaValue": "=2"}),
            "helper_note": (2, "5:3", "note", "changed"),
            "old_note": (2, "5:2", "note", "changed"),
            "reference": (4, "0:0", "note", "changed"),
            "get": (1, "5:2", "note", "changed"),
            "metadata": (3, "1:1", "userEnteredValue", {"stringValue": "0" * 64}),
            "format": (2, "5:3", "userEnteredFormat", {}),
            "validation": (2, "6:4", "dataValidation", {}),
        }[change]
        state["sheets"][sid]["cells"][address][field] = value
    with pytest.raises(GradebookError):
        verify_sparse_edit_axis_output(
            before, raw_from_state(state), [plan], {"core": binding}
        )


def test_append_after_last_opaque_column_and_leave_all_gaps_protected(scenario):
    before, binding, baseline, current = scenario
    state = native._state(before)
    state["sheets"][2]["cells"]["0:5"] = {"note": "Retained opaque header note"}
    plan = plan_sparse_edit_axis_refresh(
        "core", binding, raw_from_state(state), baseline, current
    )
    assert plan["merged_baseline"]["working_layout"]["columns"][-1]["index"] == 6
    assert plan["merged_baseline"]["working_layout"]["opaque_columns"] == [3, 4, 5]
    assert all(
        r.get("updateCells", {}).get("start", {}).get("columnIndex") not in (3, 4, 5)
        for r in plan["batch_update"]["requests"]
    )


def test_second_append_is_noop_and_reuses_exact_derived_baseline(scenario):
    _, binding, _, current = scenario
    plan, after = prepared(scenario)
    again = plan_sparse_edit_axis_refresh(
        "core", binding, after, plan["merged_baseline"], current
    )
    assert again["batch_update"]["requests"] == []
    assert again["merged_baseline"] == plan["merged_baseline"]
    verify_sparse_edit_axis_output(after, after, [again], {"core": binding})


def test_contiguous_no_growth_keeps_original_unversioned_path(snapshot, binding):
    before = initial_raw(snapshot, binding)
    plan = plan_sparse_edit_axis_refresh("core", binding, before, snapshot, snapshot)
    assert plan["merged_baseline"] == snapshot
    assert plan["batch_update"]["requests"] == []
    verify_sparse_edit_axis_output(before, before, [plan], {"core": binding})


def test_insufficient_allocated_columns_holds_without_source_mutation(scenario):
    before, binding, baseline, current = scenario
    state = native._state(before)
    state["sheets"][2]["properties"]["gridProperties"]["columnCount"] = 4
    with pytest.raises(GradebookError, match="capacity"):
        plan_sparse_edit_axis_refresh(
            "core", binding, raw_from_state(state), baseline, current
        )


def test_wire_rule_preserves_raw_rgb_precision_and_color_style_aliases(scenario):
    before, binding, baseline, current = scenario
    sheet = next(
        item for item in before["sheets"] if item["properties"]["sheetId"] == 2
    )
    original_format = sheet["conditionalFormats"][0]["booleanRule"]["format"]
    original_format["backgroundColor"]["green"] = 0.9529412
    original_format["backgroundColorStyle"] = {
        "rgbColor": copy.deepcopy(original_format["backgroundColor"])
    }
    assert (
        native._state(before)["sheets"][2]["conditionalFormats"][0]["booleanRule"][
            "format"
        ]["backgroundColor"]["green"]
        == 0.95294
    )
    plan = plan_sparse_edit_axis_refresh("core", binding, before, baseline, current)
    wire = next(
        request["updateConditionalFormatRule"]["rule"]
        for request in plan["batch_update"]["requests"]
        if "updateConditionalFormatRule" in request
    )
    assert wire["booleanRule"]["format"] == original_format
    assert wire["booleanRule"]["format"]["backgroundColor"]["green"] == 0.9529412
    assert int(wire["booleanRule"]["format"]["backgroundColor"]["green"] * 255) == 243
    assert int(0.95294 * 255) == 242
    state = native._state(before)
    native._apply_requests(state, plan["batch_update"]["requests"], binding)
    verify_sparse_edit_axis_output(
        before, raw_from_state(state), [plan], {"core": binding}
    )


def test_exact_permutation_is_accepted_without_mutating_input(scenario):
    before, binding, _, _ = scenario
    plan, after = prepared(scenario)
    state = native._state(after)
    state["sheets"][2]["protectedRanges"][0]["unprotectedRanges"].reverse()
    after = raw_from_state(state)
    unchanged = copy.deepcopy(after)
    expected = candidate.extract_sparse_edits(after, binding, plan["merged_baseline"])
    assert expected["edits"] == [{"user_id": "101", "assignment_id": "21", "value": 20}]
    candidate.verify_sparse_edit_axis_output(before, after, [plan], {"core": binding})
    assert after == unchanged


@pytest.mark.parametrize(
    "change",
    [
        "duplicate",
        "missing",
        "extra",
        "bounds",
        "field",
        "editors",
        "sheet_scope",
        "opaque_unlocked",
        "unrelated_order",
    ],
)
def test_permission_drift_still_holds_every_field_and_multiplicity(scenario, change):
    before, binding, _, _ = scenario
    plan, after = prepared(scenario)
    state = native._state(after)
    p = state["sheets"][2]["protectedRanges"][0]
    ranges = p["unprotectedRanges"]
    ranges.reverse()
    if change == "duplicate":
        ranges[1] = copy.deepcopy(ranges[0])
    elif change == "missing":
        ranges.pop()
    elif change == "extra":
        ranges.append(copy.deepcopy(ranges[0]))
    elif change == "bounds":
        ranges[0]["endRowIndex"] += 1
    elif change == "field":
        ranges[0]["unexpected"] = "private-sentinel"
    elif change == "editors":
        p["editors"] = {"users": ["changed@example.invalid"]}
    elif change == "sheet_scope":
        ranges[0]["sheetId"] = 4
    elif change == "opaque_unlocked":
        ranges[0]["startColumnIndex"] = 3
    else:
        # An unrelated reference protection has the same rectangles in different
        # order; it must not receive the owned permission normalization.
        original = [
            {
                "sheetId": 4,
                "startRowIndex": 0,
                "endRowIndex": 1,
                "startColumnIndex": 0,
                "endColumnIndex": 1,
            },
            {
                "sheetId": 4,
                "startRowIndex": 1,
                "endRowIndex": 2,
                "startColumnIndex": 1,
                "endColumnIndex": 2,
            },
        ]
        old = native._state(before)
        old["sheets"][4]["protectedRanges"] = [
            {
                "protectedRangeId": 999,
                "range": {"sheetId": 4},
                "unprotectedRanges": original,
            }
        ]
        before = raw_from_state(old)
        baseline = plan["original_baseline"]
        current = plan["current_snapshot"]
        plan = candidate.plan_sparse_edit_axis_refresh(
            "core", binding, before, baseline, current
        )
        state = native._state(before)
        native._apply_requests(state, plan["batch_update"]["requests"], binding)
        state["sheets"][4]["protectedRanges"][0]["unprotectedRanges"].reverse()
    with pytest.raises(GradebookError) as error:
        candidate.verify_sparse_edit_axis_output(
            before, raw_from_state(state), [plan], {"core": binding}
        )
    assert "private-sentinel" not in str(error.value)
