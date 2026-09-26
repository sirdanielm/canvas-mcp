"""Gradebook regression tests. Synthetic identities only; no live Canvas calls."""

import copy
import json
import os

import httpx
import pytest
from fastmcp import Client

from canvas_mcp.gradebook.client import GradebookClient, GradebookError
from canvas_mcp.gradebook.model import (
    compare_edits,
    digest,
    grade_value,
    normalize_snapshot,
    summary,
)
from canvas_mcp.gradebook.server import create_server
from canvas_mcp.gradebook.store import Store


@pytest.fixture
def snapshot():
    return normalize_snapshot(
        "https://school.example",
        {"id": 12, "name": "Synthetic class"},
        [{"id": 7, "name": "A1"}, {"id": 8, "name": "B1"}],
        [
            {
                "user_id": 101,
                "type": "StudentEnrollment",
                "enrollment_state": "active",
                "course_section_id": section,
                "user": {
                    "id": 101,
                    "name": "Synthetic Student",
                    "sortable_name": "Student, Synthetic",
                },
            }
            for section in [7, 8]
        ],
        [
            {
                "id": 21,
                "name": "Test activity",
                "published": True,
                "points_possible": 20,
                "grading_type": "points",
                "position": 1,
            }
        ],
        [
            {
                "user_id": 101,
                "assignment_id": 21,
                "score": 10,
                "grade": "10",
                "workflow_state": "graded",
                "assignment_visible": True,
            }
        ],
    )


def edits(snapshot, value):
    return {
        "course_id": "12",
        "snapshot_id": digest(snapshot),
        "edits": [{"user_id": "101", "assignment_id": "21", "value": value}],
    }


def test_multiple_enrollments_are_one_student(snapshot):
    assert summary(snapshot)["students"] == 1
    assert snapshot["students"][0]["sections"] == ["A1", "B1"]
    assert "Synthetic Student" not in json.dumps(summary(snapshot))


@pytest.mark.parametrize(
    "value,expected",
    [
        (0, 0),
        ("0", 0),
        ("EX", "EX"),
        ("Excused", "EX"),
        (None, None),
        ("", None),
        ("16.4", 16.4),
    ],
)
def test_grade_values_preserve_zero_blank_and_excused(value, expected):
    assert grade_value(value) == expected


@pytest.mark.parametrize(
    "value", [True, False, -1, float("nan"), float("inf"), "=1+1", "missing", [], {}]
)
def test_invalid_grade_values_rejected(value):
    with pytest.raises(GradebookError):
        grade_value(value)


def test_unchanged_edit_allows_new_canvas_value(snapshot):
    current = copy.deepcopy(snapshot)
    current["cells"]["101:21"]["value"] = 18
    assert compare_edits(snapshot, current, edits(snapshot, 10))["changes"] == []


def test_stale_edit_requires_review(snapshot):
    current = copy.deepcopy(snapshot)
    current["cells"]["101:21"]["value"] = 18
    change = compare_edits(snapshot, current, edits(snapshot, 20))["changes"][0]
    assert change["baseline"] == 10 and change["current"] == 18
    assert "canvas_changed_since_baseline" in change["reasons"]


@pytest.mark.parametrize(
    "value,reason",
    [
        (None, "blank_does_not_clear_grade"),
        (0, "decreases_grade"),
        (25, "points_possible_requires_review"),
    ],
)
def test_sensitive_changes_held(snapshot, value, reason):
    change = compare_edits(snapshot, snapshot, edits(snapshot, value))["changes"][0]
    assert reason in change["reasons"]


def test_excusal_removal_held(snapshot):
    snapshot["cells"]["101:21"].update(value="EX", excused=True)
    change = compare_edits(snapshot, snapshot, edits(snapshot, 20))["changes"][0]
    assert "removes_excusal" in change["reasons"]


def test_score_increase_is_reviewable_not_published(snapshot):
    review = compare_edits(snapshot, snapshot, edits(snapshot, 20))
    assert review["counts"] == {"ready_for_review": 1}
    assert review["canvas_writes"] == 0


def test_re_submission_even_same_grade_is_conflict(snapshot):
    current = copy.deepcopy(snapshot)
    current["cells"]["101:21"]["attempt"] = 2
    change = compare_edits(snapshot, current, edits(snapshot, 20))["changes"][0]
    assert "canvas_changed_since_baseline" in change["reasons"]


def test_changed_assignment_points_held(snapshot):
    current = copy.deepcopy(snapshot)
    current["assignments"][0]["points_possible"] = 30
    assert (
        "assignment_grading_changed"
        in compare_edits(snapshot, current, edits(snapshot, 20))["changes"][0][
            "reasons"
        ]
    )


def test_cross_course_edit_rejected(snapshot):
    envelope = edits(snapshot, 20)
    envelope["course_id"] = "13"
    with pytest.raises(GradebookError):
        compare_edits(snapshot, snapshot, envelope)


def test_duplicate_targets_rejected(snapshot):
    envelope = edits(snapshot, 20)
    envelope["edits"] *= 2
    with pytest.raises(GradebookError):
        compare_edits(snapshot, snapshot, envelope)


def test_missing_submission_is_not_zero(snapshot):
    current = copy.deepcopy(snapshot)
    current["cells"] = {}
    change = compare_edits(snapshot, current, edits(snapshot, 20))["changes"][0]
    assert change["current"] is None
    assert "submission_not_verified" in change["reasons"]


def test_snapshot_integrity_and_file_permissions(tmp_path, snapshot):
    store = Store(tmp_path / "private")
    artifact_id, path = store.save("snapshot", snapshot)
    assert store.load("snapshot", artifact_id) == snapshot
    assert path.stat().st_mode & 0o777 == 0o600
    assert store.root.stat().st_mode & 0o777 == 0o700
    path.write_text("{}")
    with pytest.raises(GradebookError):
        store.load("snapshot", artifact_id)


def test_path_traversal_and_symlink_rejected(tmp_path):
    store = Store(tmp_path)
    with pytest.raises(GradebookError):
        store.read_edits("../../secret.json")
    (tmp_path / "inbox").mkdir()
    (tmp_path / "inbox" / "edit.json").symlink_to(tmp_path / "secret.json")
    with pytest.raises(GradebookError):
        store.read_edits("edit.json")


@pytest.mark.asyncio
async def test_short_page_still_follows_next_link():
    requests = []

    def handler(request):
        requests.append(request)
        if len(requests) == 1:
            return httpx.Response(
                200,
                json=[{"id": 1}],
                headers={
                    "Link": '<https://school.example/api/v1/courses/12/assignments?page=2>; rel="next"'
                },
            )
        return httpx.Response(200, json=[{"id": 2}])

    client = GradebookClient(
        "https://school.example", "fake", httpx.MockTransport(handler)
    )
    try:
        assert await client.pages("/courses/12/assignments", {"per_page": 100}) == [
            {"id": 1},
            {"id": 2},
        ]
        assert all(r.method == "GET" for r in requests)
    finally:
        await client.close()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "url",
    [
        "https://evil.example/api/v1/courses/12/assignments?page=2",
        "https://school.example/api/v1/users/1?page=2",
    ],
)
async def test_pagination_never_sends_token_to_different_target(url):
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(200, json=[], headers={"Link": f'<{url}>; rel="next"'})

    client = GradebookClient(
        "https://school.example", "fake", httpx.MockTransport(handler)
    )
    try:
        with pytest.raises(GradebookError):
            await client.pages("/courses/12/assignments")
        assert len(requests) == 1
    finally:
        await client.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [401, 403, 302, 500])
async def test_http_failure_never_exposes_body(status):
    client = GradebookClient(
        "https://school.example",
        "fake",
        httpx.MockTransport(
            lambda _: httpx.Response(status, text="private student content")
        ),
    )
    try:
        with pytest.raises(GradebookError) as error:
            await client.get("/courses/12")
        assert "private" not in str(error.value)
        assert str(status) in str(error.value)
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_no_permission_stops_before_roster():
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(200, json={"id": 12, "permissions": {}})

    client = GradebookClient(
        "https://school.example", "fake", httpx.MockTransport(handler)
    )
    try:
        with pytest.raises(GradebookError):
            await client.snapshot("12")
        assert len(requests) == 2
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_mcp_registry_and_aggregate_only_result(tmp_path, snapshot):
    class FakeClient:
        origin = "https://school.example"

        async def snapshot(self, course_id):
            assert course_id == "12"
            return snapshot

    server = create_server(FakeClient(), Store(tmp_path), {"core": "12"})
    async with Client(server) as client:
        listed = await client.list_tools()
        assert {t.name for t in listed} == {
            "get_canvas_gradebook",
            "preview_gradebook_changes",
            "prepare_gradebook_push",
            "get_gradebook_push_status",
            "reconcile_gradebook_push",
        }
        result = await client.call_tool("get_canvas_gradebook", {"course": "core"})
        assert "Synthetic Student" not in str(result)
        assert "user_id" not in result.data and "cells" not in result.data
        assert result.data["students"] == 1
        assert result.data["canvas_writes"] == 0


def test_ignored_state_directory():
    from pathlib import Path

    assert "local_gradebooks/" in (Path(__file__).parents[1] / ".gitignore").read_text()
    assert os.name == "posix" or os.name == "nt"
