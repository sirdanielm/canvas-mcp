"""Exact-key coverage facts stay distinct from grade readiness and approval."""

import copy
import json

import pytest
from test_gradebook import snapshot as snapshot
from test_gradebook_native import binding as binding
from test_gradebook_native_edit_review import scenario as review_scenario  # noqa: F401

from canvas_mcp.gradebook.client import GradebookError
from canvas_mcp.gradebook.model import compare_edits, digest
from canvas_mcp.gradebook.native_edit_review import extract_native_edits, prepare_review
from canvas_mcp.gradebook.native_review_coverage import coverage_summary


def test_added_axes_count_new_mapped_slots_without_private_data(snapshot):
    current = copy.deepcopy(snapshot)
    current["students"].append({"id": "102", "name": "private sentinel"})
    current["assignments"].append({"id": "22", "name": "private sentinel"})
    before = copy.deepcopy((snapshot, current))
    out = coverage_summary(snapshot, current)
    assert out["edit_students"] == out["edit_assignments"] == 1
    assert out["canvas_students"] == out["canvas_assignments"] == 2
    assert out["added_students"] == out["added_assignments"] == 1
    assert out["removed_students"] == out["removed_assignments"] == 0
    assert out["mapped_edit_targets"] == 1 and out["missing_edit_targets"] == 3
    assert out["edit_targets_removed_from_canvas"] == 0
    assert out["matches_canvas_axes"] is False and out["warning"]
    assert "private sentinel" not in json.dumps(out)
    assert "101" not in json.dumps(out) and "102" not in json.dumps(out)
    assert (snapshot, current) == before
    assert "ready_for_review" not in out and "teacher_approval" not in out


def test_replaced_axes_report_added_and_removed_without_count_guess(snapshot):
    current = copy.deepcopy(snapshot)
    current["students"][0]["id"] = "102"
    current["assignments"][0]["id"] = "22"
    out = coverage_summary(snapshot, current)
    assert out["canvas_students"] == out["edit_students"] == 1
    assert out["canvas_assignments"] == out["edit_assignments"] == 1
    for key in ("added_students", "removed_students", "added_assignments", "removed_assignments"):
        assert out[key] == 1
    assert out["missing_edit_targets"] == out["edit_targets_removed_from_canvas"] == 1
    assert out["matches_canvas_axes"] is False


def test_equal_identity_sets_have_no_warning_even_when_observations_change(snapshot):
    current = copy.deepcopy(snapshot)
    current["cells"] = {}
    current["students"][0]["name"] = "private sentinel"
    out = coverage_summary(snapshot, current)
    assert out["matches_canvas_axes"] is True and out["warning"] is None
    assert out["missing_edit_targets"] == out["edit_targets_removed_from_canvas"] == 0
    assert "private sentinel" not in json.dumps(out)


def test_removed_all_assignments_is_visible_as_a_coverage_gap(snapshot):
    current = copy.deepcopy(snapshot)
    current["assignments"] = []
    out = coverage_summary(snapshot, current)
    assert out["canvas_assignments"] == 0
    assert out["removed_assignments"] == out["edit_targets_removed_from_canvas"] == 1
    assert out["warning"]


@pytest.mark.parametrize("change", ["duplicate", "unknown_id", "schema_bool", "schema", "course", "origin", "array"])
def test_invalid_coverage_holds_without_private_error_text(snapshot, change):
    current = copy.deepcopy(snapshot)
    if change == "duplicate":
        current["students"].append(copy.deepcopy(current["students"][0]))
    elif change == "unknown_id":
        current["students"][0]["id"] = "private sentinel"
    elif change in ("schema_bool", "schema"):
        current["schema_version"] = True if change == "schema_bool" else 2
    elif change == "array":
        current["assignments"] = {}
    else:
        current["course_id" if change == "course" else "origin"] = "private sentinel"
    with pytest.raises(GradebookError) as error:
        coverage_summary(snapshot, current)
    assert "private sentinel" not in str(error.value)


async def test_native_review_reports_coverage_without_changing_canonical_review(review_scenario):  # noqa: F811 - pytest fixture alias
    raw, binding, baseline, canvas, store = review_scenario
    student = copy.deepcopy(canvas.current["students"][0])
    student.update(id="102", name="private sentinel")
    assignment = copy.deepcopy(canvas.current["assignments"][0])
    assignment.update(id="22", name="private sentinel")
    canvas.current["students"].append(student)
    canvas.current["assignments"].append(assignment)
    before = copy.deepcopy(raw)
    expected = compare_edits(
        baseline, canvas.current, extract_native_edits(raw, binding, baseline)
    )
    result = await prepare_review(canvas, store, "core", binding, raw)
    assert result["coverage"] == coverage_summary(baseline, canvas.current)
    assert result["coverage"]["missing_edit_targets"] == 3
    canonical = store.load("review", result["review_id"])
    assert set(canonical) == set(expected)
    assert canonical["changes"] == expected["changes"]
    assert canonical["counts"] == expected["counts"] == {"ready_for_review": 1}
    assert digest(canonical) == result["review_id"]
    assert store.load("receipt", result["receipt_id"])["coverage"] == result["coverage"]
    assert canvas.reads == ["12"]
    assert result["canvas_writes"] == result["sheets_writes"] == 0
    assert "private sentinel" not in json.dumps(result)
    assert raw == before
    assert not list(store.root.glob("push-*"))
