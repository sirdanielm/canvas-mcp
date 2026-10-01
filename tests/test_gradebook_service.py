"""Shared planner regressions, with a fictional read-only snapshot source."""

import copy

import pytest
from test_gradebook import snapshot as snapshot
from test_gradebook_native import binding as binding
from test_gradebook_native import initial_raw

from canvas_mcp.gradebook.client import GradebookError
from canvas_mcp.gradebook.model import digest
from canvas_mcp.gradebook.native import validate_workbook
from canvas_mcp.gradebook.service import prepare_refresh
from canvas_mcp.gradebook.store import Store


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
