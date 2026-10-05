"""Shared planner regressions, with a fictional read-only snapshot source."""

import copy
from pathlib import Path
from typing import Any

import pytest
from test_gradebook import snapshot as snapshot
from test_gradebook_native import binding as binding
from test_gradebook_native import initial_raw

from canvas_mcp.gradebook.client import GradebookError
from canvas_mcp.gradebook.model import digest
from canvas_mcp.gradebook.native import validate_workbook
from canvas_mcp.gradebook.service import prepare_refresh
from canvas_mcp.gradebook.store import Store
from canvas_mcp.gradebook.workbook import column_name


class ReadOnlySource:
    origin = "https://school.example"

    def __init__(self, snapshot):
        self.value = snapshot
        self.calls = []

    async def snapshot(self, course):
        self.calls.append(course)
        return copy.deepcopy(self.value)


def setup(snapshot, binding, root):
    store = Store(root)
    store.save("snapshot", snapshot)
    cells = validate_workbook(initial_raw(snapshot, binding), {"core": binding})["core"]
    return store, cells


async def test_shared_service_preserves_pending_original_baseline(
    snapshot, binding, tmp_path
):
    store, cells = setup(snapshot, binding, tmp_path)
    cells["Working"]["C6"] = 20
    current = copy.deepcopy(snapshot)
    current["cells"]["101:21"]["value"] = 18
    source = ReadOnlySource(current)
    plan = await prepare_refresh(source, store, "core", binding, cells)
    assert source.calls == ["12"]
    assert plan["previous_baseline_id"] == digest(snapshot)
    assert plan["binding_digest"] == digest(binding)
    assert plan["pending_edits"] == [
        {"user_id": "101", "assignment_id": "21", "value": 20}
    ]
    merged = store.load("snapshot", plan["baseline_id"])
    assert merged["cells"]["101:21"]["value"] == 10
    assert (
        store.load("snapshot", plan["canvas_snapshot_id"])["cells"]["101:21"]["value"]
        == 18
    )
    review = store.load("review", plan["review_id"])
    assert review["changes"][0]["reasons"] == ["canvas_changed_since_baseline"]
    stored = store.load("refresh", plan["refresh_id"])
    assert "refresh_id" not in stored and "local_file" not in stored


async def test_shared_service_clears_already_fulfilled_proposal(
    snapshot, binding, tmp_path
):
    store, cells = setup(snapshot, binding, tmp_path)
    cells["Working"]["C6"] = 20
    current = copy.deepcopy(snapshot)
    current["cells"]["101:21"]["value"] = 20
    plan = await prepare_refresh(ReadOnlySource(current), store, "core", binding, cells)
    assert plan["pending_edits"] == []
    assert plan["baseline_id"] == plan["canvas_snapshot_id"]


@pytest.mark.parametrize(
    "change",
    [
        "missing_baseline",
        "wrong_origin",
        "wrong_course",
        "wrong_sync",
        "header",
        "incomplete",
    ],
)
async def test_shared_service_holds_bad_baseline_before_canvas(
    snapshot, binding, tmp_path, change
):
    store, cells = setup(snapshot, binding, tmp_path)
    source = ReadOnlySource(snapshot)
    if change == "missing_baseline":
        cells["_Sync"]["B2"] = "a" * 64
    elif change == "wrong_origin":
        source.origin = "https://other.example"
    elif change == "wrong_course":
        binding["course_id"] = "13"
    elif change == "wrong_sync":
        cells["_Sync"]["B3"] = "13"
    elif change == "header":
        cells["Working"]["C5"] = "999"
    else:
        cells.pop("Canvas")
    with pytest.raises(GradebookError):
        await prepare_refresh(source, store, "core", binding, cells)
    assert source.calls == []
    assert list(tmp_path.glob("refresh-*.json")) == []


@pytest.mark.parametrize(
    "change", ["visibility", "roster", "schema", "source_identity"]
)
async def test_shared_service_holds_unavailable_or_changed_pending_target(
    snapshot, binding, tmp_path, change
):
    store, cells = setup(snapshot, binding, tmp_path)
    cells["Working"]["C6"] = 20
    current = copy.deepcopy(snapshot)
    if change == "visibility":
        current["cells"]["101:21"]["visible"] = False
    elif change == "roster":
        current["students"] = []
    elif change == "schema":
        current["assignments"][0]["points_possible"] = 30
    else:
        current["course_id"] = "13"
    with pytest.raises(GradebookError):
        await prepare_refresh(ReadOnlySource(current), store, "core", binding, cells)
    assert list(tmp_path.glob("refresh-*.json")) == []


async def test_shared_service_never_substitutes_fresh_snapshot_for_b2(
    snapshot, binding, tmp_path
):
    store, cells = setup(snapshot, binding, tmp_path)
    changed = copy.deepcopy(snapshot)
    changed["cells"]["101:21"]["value"] = 18
    changed_id, _ = store.save("snapshot", changed)
    cells["_Sync"]["B2"] = changed_id
    cells["Working"]["C6"] = 20
    plan = await prepare_refresh(ReadOnlySource(changed), store, "core", binding, cells)
    assert plan["previous_baseline_id"] == changed_id
    assert store.load("snapshot", plan["baseline_id"])["cells"]["101:21"]["value"] == 18


def fictional_large_snapshot(template: dict[str, Any]) -> dict[str, Any]:
    """Independent fictional identities with a populated 120 by 18 grade grid."""
    result = copy.deepcopy(template)
    result["students"] = [
        {
            "id": str(1000 + index),
            "name": f"Fictional Learner {index:03}",
            "sort_name": f"Learner, Fictional {index:03}",
            "sections": ["Fictional Section"],
        }
        for index in range(120)
    ]
    result["assignments"] = [
        {
            **copy.deepcopy(template["assignments"][0]),
            "id": str(2000 + index),
            "name": f"Fictional Activity {index:02}",
            "points_possible": 100,
            "position": index + 1,
            "html_url": f"https://school.example/courses/12/assignments/{2000 + index}",
        }
        for index in range(18)
    ]
    result["cells"] = {
        f"{student['id']}:{assignment['id']}": copy.deepcopy(
            template["cells"]["101:21"]
        )
        for student in result["students"]
        for assignment in result["assignments"]
    }
    return result


def literal_gradebook_cells(
    baseline: dict[str, Any], binding: dict[str, Any]
) -> dict[str, dict[str, Any]]:
    """Build literal inputs directly, without a production layout projector."""
    grade: dict[str, Any] = {}
    for column_index, assignment in enumerate(baseline["assignments"], 3):
        column = column_name(column_index)
        for row, field in ((3, "name"), (4, "points_possible"), (5, "id")):
            grade[f"{column}{row}"] = assignment[field]
    for row, student in enumerate(baseline["students"], 6):
        grade[f"A{row}"] = student["id"]
        grade[f"B{row}"] = student["name"] + "\n" + ", ".join(student["sections"])
        for column_index, assignment in enumerate(baseline["assignments"], 3):
            grade[f"{column_name(column_index)}{row}"] = (
                baseline["cells"]
                .get(f"{student['id']}:{assignment['id']}", {})
                .get("value")
            )
    return {
        "Canvas": copy.deepcopy(grade),
        "Working": copy.deepcopy(grade),
        "_Sync": {
            "B1": 1,
            "B2": digest(baseline),
            "B3": baseline["course_id"],
            "B4": baseline["origin"],
        },
    }


def snapshot_with_added_assignment(baseline: dict[str, Any]) -> dict[str, Any]:
    current = copy.deepcopy(baseline)
    added = {
        **copy.deepcopy(baseline["assignments"][0]),
        "id": "2999",
        "name": "Fictional Newly Published Test",
        "points_possible": 100,
        "position": 2,
        "html_url": "https://school.example/courses/12/assignments/2999",
    }
    reversed_assignments = list(reversed(current["assignments"]))
    current["assignments"] = [reversed_assignments[0], added, *reversed_assignments[1:]]
    current["students"].reverse()
    current["fetched_at"] = "2026-10-04T12:00:00+00:00"
    for student in current["students"]:
        current["cells"][f"{student['id']}:2999"] = {
            **copy.deepcopy(next(iter(baseline["cells"].values()))),
            "value": 40,
            "grade": "40",
        }
    return current


def literal_plan_output(
    plan: dict[str, Any], binding: dict[str, Any]
) -> dict[str, dict[str, Any]]:
    """Read literal updateCells payloads, independently of native projection."""
    roles = {identifier: role for role, identifier in binding["sheets"].items()}
    result: dict[str, dict[str, Any]] = {role: {} for role in roles.values()}
    for request in plan["batch_update"]["requests"]:
        if "updateCells" not in request:
            continue
        update = request["updateCells"]
        start = update["start"]
        target = result[roles[start["sheetId"]]]
        for row_index, row in enumerate(update["rows"], start.get("rowIndex", 0) + 1):
            for column_index, cell in enumerate(
                row["values"], start.get("columnIndex", 0) + 1
            ):
                value = cell.get("userEnteredValue", {})
                assert "formulaValue" not in value
                target[f"{column_name(column_index)}{row_index}"] = next(
                    iter(value.values()), None
                )
    return result


async def test_shared_service_appends_assignment_preserving_all_pending_history(
    snapshot: dict[str, Any], binding: dict[str, Any], tmp_path: Path
) -> None:
    baseline = fictional_large_snapshot(snapshot)
    pending_keys = list(baseline["cells"])[:527]
    missing_origins = set(pending_keys[:29])
    for key in missing_origins:
        baseline["cells"].pop(key)
    store = Store(tmp_path)
    original_id, _ = store.save("snapshot", baseline)
    cells = literal_gradebook_cells(baseline, binding)
    current = snapshot_with_added_assignment(baseline)
    proposals: dict[str, Any] = {}
    addresses: dict[str, str] = {}
    for index, key in enumerate(pending_keys):
        user_id, assignment_id = key.split(":")
        row = 6 + int(user_id) - 1000
        column = column_name(3 + int(assignment_id) - 2000)
        addresses[key] = f"{column}{row}"
        proposals[key] = "EX" if index < 29 else 50 + index % 3
        cells["Working"][addresses[key]] = proposals[key]
        if key not in missing_origins:
            current["cells"][key].update(value=12, grade="12")
    untouched = "1119:2017"
    current["cells"][untouched].update(value=15, grade="15")
    expected_assignments = [a["id"] for a in baseline["assignments"]] + ["2999"]
    expected_students = [s["id"] for s in baseline["students"]]
    source = ReadOnlySource(current)
    plan = await prepare_refresh(source, store, "core", binding, cells)
    assert source.calls == ["12"]
    assert plan["previous_baseline_id"] == original_id
    assert len(plan["pending_edits"]) == 527
    assert sum(e["value"] == "EX" for e in plan["pending_edits"]) == 29
    assert {
        f"{e['user_id']}:{e['assignment_id']}": e["value"]
        for e in plan["pending_edits"]
    } == proposals
    stored_current = store.load("snapshot", plan["canvas_snapshot_id"])
    merged = store.load("snapshot", plan["baseline_id"])
    for artifact in (stored_current, merged):
        assert [a["id"] for a in artifact["assignments"]] == expected_assignments
        assert [s["id"] for s in artifact["students"]] == expected_students
    assert stored_current["cells"] == current["cells"]
    assert merged["working_baseline"]["previous_baseline_id"] == original_id
    assert (
        merged["working_baseline"]["canvas_snapshot_id"] == plan["canvas_snapshot_id"]
    )
    assert set(merged["working_baseline"]["retained_cells"]) == set(proposals)
    for key in proposals:
        if key in missing_origins:
            assert key not in merged["cells"]
            assert key not in stored_current["cells"]
        else:
            assert merged["cells"][key] == baseline["cells"][key]
    assert merged["cells"][untouched] == current["cells"][untouched]
    for student_id in expected_students:
        key = f"{student_id}:2999"
        assert merged["cells"][key] == stored_current["cells"][key]
    review = store.load("review", plan["review_id"])
    assert len(review["changes"]) == 527
    assert review["counts"] == {"review_required": 527}
    assert plan["review_counts"] == review["counts"]
    for change in review["changes"]:
        key = f"{change['user_id']}:{change['assignment_id']}"
        if key in missing_origins:
            assert change["baseline"] is None
            assert change["current"] is None
            assert change["proposed"] == "EX"
            assert change["reasons"] == ["submission_not_verified"]
        else:
            assert "canvas_changed_since_baseline" in change["reasons"]
    assert {f"{c['user_id']}:{c['assignment_id']}" for c in review["changes"]} == set(
        proposals
    )
    output = literal_plan_output(plan, binding)
    for role in ("Canvas", "Working"):
        assert [
            output[role][f"{column_name(c)}5"] for c in range(3, 22)
        ] == expected_assignments
        assert [output[role][f"A{r}"] for r in range(6, 126)] == expected_students
        assert output[role]["U3"] == "Fictional Newly Published Test"
        assert output[role]["U4"] == 100
        assert output[role]["U6"] == 40
    for key, value in proposals.items():
        assert output["Working"][addresses[key]] == (
            "Excused" if value == "EX" else value
        )
        assert output["Canvas"][addresses[key]] == (
            None if key in missing_origins else 12
        )
    assert output["_Sync"]["B2"] == plan["baseline_id"]
    assert output["_Sync"]["B9"] == plan["canvas_snapshot_id"]
    assert output["_Sync"]["B10"] == 527
    stored_plan = store.load("refresh", plan["refresh_id"])
    assert stored_plan["batch_update"] == plan["batch_update"]
    again = await prepare_refresh(source, store, "core", binding, output)
    assert again["previous_baseline_id"] == plan["baseline_id"]
    assert again["pending_edits"] == plan["pending_edits"]
    repeated = store.load("snapshot", again["baseline_id"])
    for key in proposals:
        if key in missing_origins:
            assert key not in repeated["cells"]
        else:
            assert repeated["cells"][key] == baseline["cells"][key]
    repeated_review = store.load("review", again["review_id"])
    assert [c["reasons"] for c in repeated_review["changes"]] == [
        c["reasons"] for c in review["changes"]
    ]
    repeated_output = literal_plan_output(again, binding)
    assert repeated_output["Working"] == output["Working"]
    assert store.load("snapshot", original_id) == baseline

    # An actual later Canvas EX observation must not replace the missing origin.
    later_current = copy.deepcopy(current)
    later_current["fetched_at"] = "2026-10-04T12:05:00+00:00"
    for key in missing_origins:
        later_current["cells"][key] = {
            **copy.deepcopy(snapshot["cells"]["101:21"]),
            "value": "EX",
            "excused": True,
            "grade": None,
        }
    source.value = later_current
    later = await prepare_refresh(source, store, "core", binding, repeated_output)
    assert later["pending_edits"] == plan["pending_edits"]
    later_baseline = store.load("snapshot", later["baseline_id"])
    assert (
        later_baseline["working_baseline"]["previous_baseline_id"]
        == again["baseline_id"]
    )
    assert set(later_baseline["working_baseline"]["retained_cells"]) == set(proposals)
    later_canvas = store.load("snapshot", later["canvas_snapshot_id"])
    later_review = store.load("review", later["review_id"])
    assert later_review["counts"] == {"review_required": 527}
    for change in later_review["changes"]:
        key = f"{change['user_id']}:{change['assignment_id']}"
        if key in missing_origins:
            assert key not in later_baseline["cells"]
            assert later_canvas["cells"][key] == later_current["cells"][key]
            assert change["baseline"] is None
            assert change["current"] == "EX"
            assert change["proposed"] == "EX"
            assert change["status"] == "review_required"
            assert change["reasons"] == ["submission_not_verified"]
    assert source.calls == ["12", "12", "12"]
    assert store.load("snapshot", original_id) == baseline


async def test_shared_service_absent_ex_origin_stays_unverified_after_canvas_ex(
    snapshot: dict[str, Any], binding: dict[str, Any], tmp_path: Path
) -> None:
    baseline = copy.deepcopy(snapshot)
    baseline["cells"].pop("101:21")
    store = Store(tmp_path)
    original_id, _ = store.save("snapshot", baseline)
    cells = literal_gradebook_cells(baseline, binding)
    cells["Working"]["C6"] = "EX"
    current = snapshot_with_added_assignment(snapshot)
    current["cells"].pop("101:21")
    source = ReadOnlySource(current)
    first = await prepare_refresh(source, store, "core", binding, cells)
    output = literal_plan_output(first, binding)
    assert output["Canvas"]["C6"] is None
    assert output["Working"]["C6"] == "Excused"
    expected_pending = [{"user_id": "101", "assignment_id": "21", "value": "EX"}]
    assert first["pending_edits"] == expected_pending
    for canvas_ex in (False, True, True):
        if canvas_ex:
            source.value["cells"]["101:21"] = {
                **copy.deepcopy(snapshot["cells"]["101:21"]),
                "value": "EX",
                "excused": True,
                "grade": None,
            }
        following = await prepare_refresh(source, store, "core", binding, output)
        assert following["pending_edits"] == expected_pending
        merged = store.load("snapshot", following["baseline_id"])
        assert "101:21" not in merged["cells"]
        assert merged["working_baseline"]["retained_cells"] == ["101:21"]
        assert (
            merged["working_baseline"]["previous_baseline_id"] == output["_Sync"]["B2"]
        )
        review = store.load("review", following["review_id"])
        assert review["counts"] == {"review_required": 1}
        assert review["changes"][0]["status"] == "review_required"
        assert review["changes"][0]["baseline"] is None
        assert review["changes"][0]["current"] == ("EX" if canvas_ex else None)
        assert review["changes"][0]["reasons"] == ["submission_not_verified"]
        output = literal_plan_output(following, binding)
        assert output["Canvas"]["C6"] == ("Excused" if canvas_ex else None)
        assert output["Working"]["C6"] == "Excused"
    assert store.load("snapshot", original_id) == baseline


@pytest.mark.parametrize("proposal,hidden", [(0, False), (19, False), ("EX", True)])
async def test_shared_service_missing_origin_unsafe_proposal_remains_held(
    snapshot: dict[str, Any],
    binding: dict[str, Any],
    tmp_path: Path,
    proposal: Any,
    hidden: bool,
) -> None:
    baseline = copy.deepcopy(snapshot)
    baseline["cells"].pop("101:21")
    store = Store(tmp_path)
    store.save("snapshot", baseline)
    cells = literal_gradebook_cells(baseline, binding)
    cells["Working"]["C6"] = proposal
    current = snapshot_with_added_assignment(snapshot)
    current["cells"].pop("101:21")
    if hidden:
        current["cells"]["101:21"] = {
            **copy.deepcopy(snapshot["cells"]["101:21"]),
            "visible": False,
            "value": "EX",
            "excused": True,
        }
    with pytest.raises(GradebookError, match="pending edit target is unavailable"):
        await prepare_refresh(ReadOnlySource(current), store, "core", binding, cells)
    assert list(tmp_path.glob("refresh-*.json")) == []


@pytest.mark.parametrize("proposal", [None, 0])
async def test_shared_service_addition_preserves_blank_and_zero_proposals(
    snapshot: dict[str, Any], binding: dict[str, Any], tmp_path: Path, proposal: Any
) -> None:
    store, cells = setup(snapshot, binding, tmp_path)
    cells["Working"]["C6"] = proposal
    current = snapshot_with_added_assignment(snapshot)
    plan = await prepare_refresh(ReadOnlySource(current), store, "core", binding, cells)
    assert plan["pending_edits"] == [
        {"user_id": "101", "assignment_id": "21", "value": proposal}
    ]
    merged = store.load("snapshot", plan["baseline_id"])
    assert merged["cells"]["101:21"] == snapshot["cells"]["101:21"]
    assert literal_plan_output(plan, binding)["Working"]["C6"] == proposal
    reasons = store.load("review", plan["review_id"])["changes"][0]["reasons"]
    assert (
        "blank_does_not_clear_grade" if proposal is None else "decreases_grade"
    ) in reasons


@pytest.mark.parametrize(
    "change",
    ["remove_assignment", "points", "type", "roster", "missing_target", "visibility"],
)
@pytest.mark.parametrize("proposal", [19, "EX"])
async def test_shared_service_addition_keeps_existing_safety_holds(
    snapshot: dict[str, Any],
    binding: dict[str, Any],
    tmp_path: Path,
    change: str,
    proposal: Any,
) -> None:
    store, cells = setup(snapshot, binding, tmp_path)
    cells["Working"]["C6"] = proposal
    current = snapshot_with_added_assignment(snapshot)
    old_assignment = next(a for a in current["assignments"] if a["id"] == "21")
    if change == "remove_assignment":
        current["assignments"].remove(old_assignment)
    elif change == "points":
        old_assignment["points_possible"] = 30
    elif change == "type":
        old_assignment["grading_type"] = "letter_grade"
    elif change == "roster":
        current["students"] = []
    elif change == "missing_target":
        current["cells"].pop("101:21")
    else:
        current["cells"]["101:21"]["visible"] = False
    before = copy.deepcopy(cells)
    with pytest.raises(GradebookError):
        await prepare_refresh(ReadOnlySource(current), store, "core", binding, cells)
    assert cells == before
    assert list(tmp_path.glob("refresh-*.json")) == []
    assert list(tmp_path.glob("review-*.json")) == []
    assert len(list(tmp_path.glob("snapshot-*.json"))) == 1


@pytest.mark.parametrize("role", ["Canvas", "Working"])
@pytest.mark.parametrize("dimension", ["columns", "rows"])
async def test_shared_service_refuses_manual_grid_reorder_before_canvas(
    snapshot: dict[str, Any],
    binding: dict[str, Any],
    tmp_path: Path,
    role: str,
    dimension: str,
) -> None:
    baseline = fictional_large_snapshot(snapshot)
    store = Store(tmp_path)
    store.save("snapshot", baseline)
    cells = literal_gradebook_cells(baseline, binding)
    target = cells[role]
    if dimension == "columns":
        for row in range(3, 126):
            target[f"C{row}"], target[f"D{row}"] = target[f"D{row}"], target[f"C{row}"]
    else:
        for column_index in range(1, 21):
            column = column_name(column_index)
            target[f"{column}6"], target[f"{column}7"] = (
                target[f"{column}7"],
                target[f"{column}6"],
            )
    source = ReadOnlySource(snapshot_with_added_assignment(baseline))
    with pytest.raises(GradebookError):
        await prepare_refresh(source, store, "core", binding, cells)
    assert source.calls == []
    assert list(tmp_path.glob("refresh-*.json")) == []
