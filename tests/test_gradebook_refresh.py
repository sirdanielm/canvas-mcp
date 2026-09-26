"""Refresh tests: no live systems and only synthetic student records."""

import copy

import pytest
from test_gradebook import edits
from test_gradebook import snapshot as snapshot

from canvas_mcp.gradebook.client import GradebookError
from canvas_mcp.gradebook.model import compare_edits, digest
from canvas_mcp.gradebook.refresh import (
    build_requests,
    merge_refresh,
    source_digest,
    verify_refresh_output,
)


def test_refresh_keeps_pending_baseline_and_new_canvas(snapshot):
    current = copy.deepcopy(snapshot)
    current["cells"]["101:21"]["value"] = 18
    merged, display, review = merge_refresh(snapshot, current, edits(snapshot, 20))
    assert merged["cells"]["101:21"]["value"] == 10
    assert display["cells"]["101:21"]["value"] == 20
    assert current["cells"]["101:21"]["value"] == 18
    assert merged["working_baseline"]["previous_baseline_id"] == digest(snapshot)
    assert "canvas_changed_since_baseline" in review["changes"][0]["reasons"]
    subsequent = compare_edits(merged, current, edits(merged, 20))
    assert "canvas_changed_since_baseline" in subsequent["changes"][0]["reasons"]


def test_refresh_untouched_cells_accept_canvas(snapshot):
    current = copy.deepcopy(snapshot)
    current["cells"]["101:21"]["value"] = 18
    merged, display, review = merge_refresh(snapshot, current, edits(snapshot, 10))
    assert merged == current == display
    assert review["changes"] == []


def test_refresh_after_successful_push_clears_fulfilled_edits(snapshot):
    current = copy.deepcopy(snapshot)
    current["cells"]["101:21"]["value"] = 20
    current["cells"]["101:21"]["graded_at"] = "2026-09-17T22:00:00Z"
    merged, display, review = merge_refresh(snapshot, current, edits(snapshot, 20))
    assert merged == display == current
    assert "working_baseline" not in merged
    assert review["changes"] == []


@pytest.mark.parametrize("change", ["roster", "points", "visibility"])
def test_refresh_pending_schema_or_visibility_change_holds(snapshot, change):
    current = copy.deepcopy(snapshot)
    if change == "roster":
        current["students"] = []
    elif change == "points":
        current["assignments"][0]["points_possible"] = 30
    else:
        current["cells"]["101:21"]["visible"] = False
    with pytest.raises(GradebookError):
        merge_refresh(snapshot, current, edits(snapshot, 20))


@pytest.mark.parametrize("value", [None, 0, "EX"])
def test_refresh_preserves_held_blanks_zeros_excusal(snapshot, value):
    merged, display, review = merge_refresh(snapshot, snapshot, edits(snapshot, value))
    assert merged["cells"]["101:21"]["value"] == 10
    assert display["cells"]["101:21"]["value"] == value
    assert len(review["changes"]) == 1


def test_build_requests_literal_values_and_roundtrip(snapshot):
    snapshot["assignments"][0]["name"] = "=MALICIOUS()"
    binding = {
        "label": "Test",
        "sheets": {"Canvas": 1, "Working": 2, "_Sync": 3},
        "working_protection_id": 4,
    }
    baseline, display, review = merge_refresh(snapshot, snapshot, edits(snapshot, 20))
    requests = build_requests(snapshot, display, digest(baseline), binding, snapshot, 1)
    sheet_names = {1: "Canvas", 2: "Working", 3: "_Sync"}
    sheets = {}
    for request in requests:
        if "updateCells" not in request:
            continue
        update = request["updateCells"]
        cells = {}
        for row, data in enumerate(update["rows"], 1):
            for col, c in enumerate(data["values"]):
                value = c.get("userEnteredValue", {})
                assert "formulaValue" not in value
                cells[f"{chr(65+col)}{row}"] = next(iter(value.values()), None)
        sheets[sheet_names[update["start"]["sheetId"]]] = cells
    plan = {"pending_edits": [{"user_id": "101", "assignment_id": "21", "value": 20}]}
    verify_refresh_output(sheets, plan, snapshot, baseline)
    sheets["Canvas"]["C6"] = 999
    with pytest.raises(GradebookError, match="Canvas tab readback"):
        verify_refresh_output(sheets, plan, snapshot, baseline)


def test_input_digest_detects_changes_ignores_only_empty_format_cells():
    original = {"Working": {"A6": "101", "C6": 0}, "_Sync": {"B2": "snapshot"}}
    formatted = copy.deepcopy(original)
    formatted["Working"]["Q999"] = None
    assert source_digest(original) == source_digest(formatted)
    formatted["Working"]["C6"] = None
    assert source_digest(original) != source_digest(formatted)


def test_shared_workbook_highlights_reference_its_own_course(snapshot):
    binding = {
        "label": "Core", "sheets": {"Canvas": 1, "Working": 2, "_Sync": 3},
        "working_protection_id": 4,
        "tab_names": {"Canvas": "Core's Canvas Mirror", "Working": "Core Edit", "_Sync": "_Core Sync"},
    }
    requests = build_requests(snapshot, snapshot, digest(snapshot), binding, snapshot, 0)
    rule = next(r["updateConditionalFormatRule"] for r in requests if "updateConditionalFormatRule" in r)
    formula = rule["rule"]["booleanRule"]["condition"]["values"][0]["userEnteredValue"]
    assert "'Core''s Canvas Mirror'!" in formula
    assert "'Canvas'!" not in formula
    assert rule["sheetId"] == 2


def test_refresh_includes_canvas_submission_details_on_both_tabs(snapshot):
    binding = {"label": "Test", "sheets": {"Canvas": 1, "Working": 2, "_Sync": 3}, "working_protection_id": 4}
    snapshot["cells"]["101:21"].update(workflow_state="submitted", attempt=2, submitted_at="2026-09-20T12:00:00Z")
    requests = build_requests(snapshot, snapshot, digest(snapshot), binding, snapshot, 0)
    updates = [r["updateCells"] for r in requests if "updateCells" in r and r["updateCells"]["start"]["sheetId"] in (1, 2)]
    for update in updates:
        note = update["rows"][5]["values"][2]["note"]
        assert "Canvas status: submitted" in note
        assert "Attempt: 2" in note
        assert "Submitted UTC: 2026-09-20T12:00:00Z" in note
        assert "note" in update["fields"]


def test_refresh_expands_grade_grid_for_later_units(snapshot):
    binding = {"label": "Test", "sheets": {"Canvas": 1, "Working": 2, "_Sync": 3}, "working_protection_id": 4}
    template = snapshot["assignments"][0]
    snapshot["assignments"] = [{**template, "id": str(1000+i)} for i in range(30)]
    requests = build_requests(snapshot, snapshot, digest(snapshot), binding, snapshot, 0)
    dimensions = [r["updateSheetProperties"] for r in requests if "updateSheetProperties" in r]
    assert {d["properties"]["sheetId"] for d in dimensions} == {1, 2}
    assert all(d["properties"]["gridProperties"]["columnCount"] == 32 for d in dimensions)
