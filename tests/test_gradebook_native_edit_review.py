"""Native Edit score review regressions with fictional private records only."""

import copy
import json

import pytest
from test_gradebook import snapshot as snapshot
from test_gradebook_native import binding as binding
from test_gradebook_native import initial_raw, raw_from_state

from canvas_mcp.gradebook import native
from canvas_mcp.gradebook.client import GradebookError
from canvas_mcp.gradebook.model import digest
from canvas_mcp.gradebook.native_edit_review import extract_native_edits, prepare_review
from canvas_mcp.gradebook.store import Store


class Canvas:
    origin = "https://school.example"

    def __init__(self, snapshot):
        self.current = copy.deepcopy(snapshot)
        self.reads = []

    async def snapshot(self, course_id):
        self.reads.append(course_id)
        return copy.deepcopy(self.current)


@pytest.fixture
def scenario(snapshot, binding, tmp_path):
    before = initial_raw(snapshot, binding)
    state = native._state(before)
    working = state["sheets"][2]
    working["cells"]["5:2"]["userEnteredValue"] = {"numberValue": 20}
    working["cells"]["5:2"]["note"] = "Fictional teacher feedback retained"
    working["cells"]["0:5"] = {
        "userEnteredValue": {"formulaValue": "=SUM(C6:C7)"},
        "note": "Opaque header helper",
    }
    working["cells"]["20:10"] = {
        "userEnteredValue": {"formulaValue": "=2+2"},
        "note": "Opaque extra helper",
    }
    store = Store(tmp_path)
    store.save("snapshot", snapshot)
    return raw_from_state(state), binding, snapshot, Canvas(snapshot), store


def test_opaque_helpers_and_notes_never_change_or_enter_envelope(scenario):
    raw, binding, baseline, _, _ = scenario
    original = copy.deepcopy(raw)
    result = extract_native_edits(raw, binding, baseline)
    assert result == {
        "course_id": "12", "snapshot_id": digest(baseline),
        "edits": [{"user_id": "101", "assignment_id": "21", "value": 20}],
    }
    assert raw == original
    assert "Fictional teacher feedback" not in json.dumps(result)
    assert "formulaValue" not in json.dumps(result)


@pytest.mark.parametrize(
    "change",
    ["score_formula", "uid_formula", "aid_formula", "points_formula", "title_formula",
     "student_formula", "unknown_uid", "unknown_aid", "duplicate_uid", "duplicate_aid",
     "gap_uid", "gap_aid", "student_label", "assignment_label", "points", "checkbox",
     "baseline", "sheet_name"],
)
def test_mapped_metadata_or_score_changes_hold_without_private_error_text(scenario, change):
    raw, binding, baseline, _, _ = scenario
    state = native._state(raw)
    cells = state["sheets"][2]["cells"]
    formula_positions = {
        "score_formula": "5:2", "uid_formula": "5:0", "aid_formula": "4:2",
        "points_formula": "3:2", "title_formula": "2:2", "student_formula": "5:1",
    }
    if change in formula_positions:
        cells[formula_positions[change]]["userEnteredValue"] = {"formulaValue": "=1+1"}
    elif change in {"unknown_uid", "unknown_aid"}:
        cells["5:0" if change == "unknown_uid" else "4:2"]["userEnteredValue"] = {"stringValue": "999999"}
    elif change in {"duplicate_uid", "duplicate_aid", "gap_uid", "gap_aid"}:
        source = "5:0" if change.endswith("uid") else "4:2"
        target = {"duplicate_uid": "6:0", "duplicate_aid": "4:3", "gap_uid": "7:0", "gap_aid": "4:4"}[change]
        cells[target] = copy.deepcopy(cells[source])
        if change.startswith("gap"):
            cells[target]["userEnteredValue"] = {"stringValue": "999999"}
    elif change in {"student_label", "assignment_label"}:
        cells["5:1" if change == "student_label" else "2:2"]["userEnteredValue"] = {"stringValue": "private-sensitive-sentinel"}
    elif change == "points":
        cells["3:2"]["userEnteredValue"] = {"numberValue": 100}
    elif change == "checkbox":
        cells["5:2"]["userEnteredValue"] = {"boolValue": True}
    elif change == "baseline":
        state["sheets"][3]["cells"]["1:1"]["userEnteredValue"] = {"stringValue": "0" * 64}
    else:
        state["sheets"][2]["properties"]["title"] = "Renamed Edit"
    with pytest.raises(GradebookError) as error:
        extract_native_edits(raw_from_state(state), binding, baseline)
    assert "private-sensitive-sentinel" not in str(error.value)
    assert "999999" not in str(error.value)


@pytest.mark.asyncio
async def test_review_uses_original_baseline_and_fresh_canvas_without_writes(scenario):
    raw, binding, baseline, canvas, store = scenario
    original = copy.deepcopy(raw)
    canvas.current["cells"]["101:21"].update(value=18, grade="18")
    result = await prepare_review(canvas, store, "core", binding, raw)
    assert canvas.reads == ["12"]
    assert result["changes"] == 1
    assert result["counts"] == {"review_required": 1}
    review = store.load("review", result["review_id"])
    assert review["changes"][0]["baseline"] == 10
    assert review["changes"][0]["current"] == 18
    assert review["changes"][0]["proposed"] == 20
    assert "canvas_changed_since_baseline" in review["changes"][0]["reasons"]
    assert result["baseline_id"] == digest(baseline)
    assert store.load("snapshot", result["baseline_id"]) == baseline
    assert result["canvas_writes"] == result["sheets_writes"] == 0
    assert raw == original
    assert "user_id" not in json.dumps(result)
    assert "assignment_id" not in json.dumps(result)
    assert (store.root / ("review-" + result["review_id"] + ".html")).is_file()
    receipt = store.load("receipt", result["receipt_id"])
    assert receipt["input_fingerprint"] == native.fingerprint(raw)


@pytest.mark.asyncio
async def test_fulfilled_current_canvas_value_is_no_change(scenario):
    raw, binding, _, canvas, store = scenario
    canvas.current["cells"]["101:21"].update(value=20, grade="20")
    result = await prepare_review(canvas, store, "core", binding, raw)
    assert result["changes"] == 0
    assert result["counts"] == {}


@pytest.mark.asyncio
async def test_mapped_formula_holds_before_canvas_get_or_artifact_creation(scenario):
    raw, binding, _, canvas, store = scenario
    state = native._state(raw)
    state["sheets"][2]["cells"]["5:2"]["userEnteredValue"] = {"formulaValue": "=20"}
    files = set(store.root.iterdir())
    with pytest.raises(GradebookError):
        await prepare_review(canvas, store, "core", binding, raw_from_state(state))
    assert not canvas.reads
    assert set(store.root.iterdir()) == files


@pytest.mark.asyncio
@pytest.mark.parametrize("field,value", [("course_id", "13"), ("origin", "https://other.example")])
async def test_current_snapshot_scope_mismatch_holds(scenario, field, value):
    raw, binding, _, canvas, store = scenario
    canvas.current[field] = value
    with pytest.raises(GradebookError, match="course or origin"):
        await prepare_review(canvas, store, "core", binding, raw)
    assert not list(store.root.glob("review-*"))
