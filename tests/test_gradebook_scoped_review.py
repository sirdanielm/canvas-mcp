"""Captured-evidence review slices never clear holds or create publisher state."""

import copy

import pytest
from test_gradebook import snapshot as snapshot

from canvas_mcp.gradebook.client import GradebookError
from canvas_mcp.gradebook.model import compare_edits, digest
from canvas_mcp.gradebook.scoped_review import select_ready_batch
from canvas_mcp.gradebook.store import Store


def parent(store, snapshot, value=20):
    store.save("snapshot", snapshot)
    r = compare_edits(
        snapshot,
        snapshot,
        {
            "course_id": "12",
            "snapshot_id": digest(snapshot),
            "edits": [{"user_id": "101", "assignment_id": "21", "value": value}],
        },
    )
    rid, _ = store.save("review", r)
    return rid, r


def test_ready_scope_preserves_evidence_time_and_requires_teacher_review(
    tmp_path, snapshot
):
    s = Store(tmp_path)
    rid, r = parent(s, snapshot)
    out = select_ready_batch(s, "12", snapshot["origin"], rid)
    child = s.load("review", out["review_id"])
    assert child["changes"] == r["changes"]
    assert child["created_at"] == r["created_at"]
    assert child["baseline_id"] == r["baseline_id"]
    assert child["teacher_approval"] is False
    assert not out["teacher_approval"]
    assert out["selected"] == 1 and out["canvas_writes"] == 0
    assert (
        not list(tmp_path.glob("push-*")) and not (tmp_path / "ledger.sqlite3").exists()
    )


@pytest.mark.parametrize("value", [None, 5, "EX"])
def test_held_rows_are_never_selected(tmp_path, snapshot, value):
    s = Store(tmp_path)
    rid, r = parent(s, snapshot, value)
    if r["counts"].get("review_required"):
        with pytest.raises(GradebookError):
            select_ready_batch(s, "12", snapshot["origin"], rid)
        assert s.load("review", rid) == r


@pytest.mark.parametrize("mutation", ["status", "reasons", "counts", "origin", "index"])
def test_forged_classification_wrong_origin_and_bad_index_hold(
    tmp_path, snapshot, mutation
):
    s = Store(tmp_path)
    rid, r = parent(s, snapshot)
    if mutation == "status":
        r["changes"][0]["status"] = "review_required"
    if mutation == "reasons":
        r["changes"][0]["reasons"] = ["changed"]
    if mutation == "counts":
        r["counts"] = {"ready_for_review": 99}
    rid, _ = s.save("review", r)
    with pytest.raises(GradebookError):
        select_ready_batch(
            s,
            "12",
            "wrong" if mutation == "origin" else snapshot["origin"],
            rid,
            True if mutation == "index" else 0,
        )


def test_multiple_batches_cap_at_25_and_hold_parent_unchanged(tmp_path, snapshot):
    s = Store(tmp_path)
    b = copy.deepcopy(snapshot)
    template = b["students"][0]
    cell = b["cells"]["101:21"]
    b["students"] = []
    b["cells"] = {}
    for i in range(30):
        uid = str(101 + i)
        b["students"].append({**template, "id": uid})
        b["cells"][uid + ":21"] = copy.deepcopy(cell)
    s.save("snapshot", b)
    r = compare_edits(
        b,
        b,
        {
            "course_id": "12",
            "snapshot_id": digest(b),
            "edits": [
                {"user_id": x["id"], "assignment_id": "21", "value": 20}
                for x in b["students"]
            ],
        },
    )
    rid, _ = s.save("review", r)
    assert select_ready_batch(s, "12", b["origin"], rid, 0)["selected"] == 25
    last = select_ready_batch(s, "12", b["origin"], rid, 1)
    assert last["selected"] == 5
    assert last["remaining_ready"] == 0
    assert last["ready_before_batch"] == 25
    assert last["unselected_ready"] == 25
    assert s.load("review", rid) == r
    with pytest.raises(GradebookError):
        select_ready_batch(s, "12", b["origin"], rid, 2)


@pytest.mark.parametrize("field,value", [
    ("course_id", "13"), ("schema_version", 2), ("canvas_writes", 1),
    ("canvas_writes", False), ("created_at", "private invalid text"),
    ("created_at", "2026-10-14T11:00:00"), ("changes", {}),
])
def test_parent_metadata_mismatch_never_creates_a_child_or_approval(
    tmp_path, snapshot, field, value
):
    s = Store(tmp_path)
    _, r = parent(s, snapshot)
    r[field] = value
    rid, _ = s.save("review", r)
    before = {p.name: p.read_bytes() for p in tmp_path.iterdir() if p.is_file()}
    with pytest.raises(GradebookError):
        select_ready_batch(s, "12", snapshot["origin"], rid)
    assert {p.name: p.read_bytes() for p in tmp_path.iterdir() if p.is_file()} == before


def test_scope_does_not_inherit_claimed_teacher_approval_or_arbitrary_parent_text(
    tmp_path, snapshot
):
    s = Store(tmp_path)
    _, r = parent(s, snapshot)
    r["teacher_approval"] = True
    r["operator_claim"] = "private arbitrary claim"
    rid, _ = s.save("review", r)
    out = select_ready_batch(s, "12", snapshot["origin"], rid)
    child = s.load("review", out["review_id"])
    assert child["teacher_approval"] is False
    assert "operator_claim" not in child
    assert child["created_at"] == r["created_at"]
    assert s.load("review", rid) == r
    assert "private" not in str({k: v for k, v in out.items() if not k.endswith("file")})
