"""Exact-assignment snapshot regressions; fictional responses, no live calls."""

import asyncio
import copy

import httpx
import pytest
from fastmcp import Client

from canvas_mcp.gradebook import client as transport_module
from canvas_mcp.gradebook.client import GradebookClient, GradebookError
from canvas_mcp.gradebook.server import create_server
from canvas_mcp.gradebook.store import Store


def assignment(aid=21, **changes):
    return {
        "id": aid,
        "course_id": 12,
        "name": "Fictional assignment",
        "published": True,
        "grading_type": "points",
        "points_possible": 20,
        **changes,
    }


def submission(uid=101, aid=21, **changes):
    return {
        "user_id": uid,
        "assignment_id": aid,
        "score": 10,
        "attempt": 1,
        "assignment_visible": True,
        **changes,
    }


class FictionalCanvas:
    def __init__(self):
        self.requests = []
        self.assignments = [assignment()]
        self.records = {21: [submission()]}
        self.overrides = {}

    def handle(self, request):
        self.requests.append(request)
        assert request.method == "GET"
        path = request.url.path.removeprefix("/api/v1/courses/12")
        if path in self.overrides:
            return self.overrides[path](request)
        if path == "":
            value = {"id": 12, "name": "Fictional course"}
        elif path == "/permissions":
            value = {"manage_grades": True}
        elif path == "/sections":
            value = [{"id": 7, "name": "A1"}]
        elif path == "/enrollments":
            value = [
                {
                    "user_id": uid,
                    "type": "StudentEnrollment",
                    "enrollment_state": "active",
                    "course_section_id": 7,
                    "user": {"id": uid, "name": "Fictional student"},
                }
                for uid in (101, 102)
            ]
        elif path == "/assignments":
            value = self.assignments
        elif path == "/students/submissions":
            # Upstream bulk visibility defect: other cell values still agree.
            value = [submission(assignment_visible=False)]
        elif path.startswith("/assignments/") and path.endswith("/submissions"):
            assert request.url.params.get("include[]") == "visibility"
            value = self.records[int(path.split("/")[2])]
        else:
            raise AssertionError("Unexpected fictional endpoint")
        return httpx.Response(200, json=copy.deepcopy(value))


@pytest.fixture
async def canvas():
    source = FictionalCanvas()
    client = GradebookClient(
        "https://school.example", "fake", httpx.MockTransport(source.handle)
    )
    try:
        yield client, source
    finally:
        await client.close()


async def test_snapshot_uses_exact_cells_not_bulk_visibility(canvas):
    client, source = canvas
    result = await client.snapshot("12")
    assert result["cells"]["101:21"]["visible"] is True
    assert result["cells"]["101:21"]["value"] == 10
    assert not any("/students/submissions" in r.url.path for r in source.requests)


async def test_wrong_course_stops_before_permissions_or_roster(canvas):
    client, source = canvas
    source.overrides[""] = lambda _: httpx.Response(200, json={"id": 13})
    with pytest.raises(GradebookError, match="course identity"):
        await client.snapshot("12")
    assert len(source.requests) == 1


@pytest.mark.parametrize("visibility", [True, False, None, "absent"])
async def test_exact_visibility_preserves_true_false_and_unknown(canvas, visibility):
    client, source = canvas
    if visibility == "absent":
        del source.records[21][0]["assignment_visible"]
    else:
        source.records[21][0]["assignment_visible"] = visibility
    result = await client.snapshot("12")
    expected = None if visibility == "absent" else visibility
    assert result["cells"]["101:21"]["visible"] is expected


async def test_exact_pages_follow_next_link_and_keep_only_active_students(canvas):
    client, source = canvas

    def pages(request):
        if request.url.params.get("page") == "2":
            return httpx.Response(200, json=[submission(102), submission(999)])
        return httpx.Response(
            200,
            json=[submission()],
            headers={
                "Link": '<https://school.example/api/v1/courses/12/assignments/21/submissions?page=2&include%5B%5D=visibility>; rel="next"'
            },
        )

    source.overrides["/assignments/21/submissions"] = pages
    result = await client.snapshot("12")
    assert set(result["cells"]) == {"101:21", "102:21"}
    assert len([r for r in source.requests if r.url.path.endswith("/submissions")]) == 2


async def test_exact_pagination_cannot_switch_assignment(canvas):
    client, source = canvas
    source.overrides["/assignments/21/submissions"] = lambda _: httpx.Response(
        200,
        json=[submission()],
        headers={
            "Link": '<https://school.example/api/v1/courses/12/assignments/22/submissions?page=2>; rel="next"'
        },
    )
    with pytest.raises(GradebookError, match="changed origin or endpoint"):
        await client.snapshot("12")
    assert not any("/assignments/22/" in r.url.path for r in source.requests)


async def test_partial_failure_does_not_save_or_replace_snapshot(canvas, tmp_path):
    client, source = canvas
    source.assignments.append(assignment(22))
    source.overrides["/assignments/22/submissions"] = lambda _: httpx.Response(
        503, text="private fictional response"
    )
    store = Store(tmp_path)
    _, previous = store.save("snapshot", {"previous": "fictional snapshot"})
    original = previous.read_bytes()
    before = set(tmp_path.rglob("snapshot-*.json"))
    server = create_server(client, store, {"core": "12"})
    async with Client(server) as session:
        response = await session.call_tool("get_canvas_gradebook", {"course": "core"})
    assert "503" in response.data["error"]
    assert "private fictional" not in response.data["error"]
    assert previous.read_bytes() == original
    assert set(tmp_path.rglob("snapshot-*.json")) == before


@pytest.mark.parametrize("bad", [assignment(course_id=13), assignment(id="bad")])
async def test_assignment_identity_failure_stops_before_submission_reads(canvas, bad):
    client, source = canvas
    source.assignments = [bad]
    with pytest.raises(GradebookError):
        await client.snapshot("12")
    assert not any(r.url.path.endswith("/submissions") for r in source.requests)


async def test_wrong_submission_assignment_is_rejected_even_for_inactive_user(canvas):
    client, source = canvas
    source.records[21] = [submission(999, aid=22)]
    with pytest.raises(GradebookError, match="submission assignment identity"):
        await client.snapshot("12")


async def test_duplicate_exact_submission_is_rejected(canvas):
    client, source = canvas
    source.records[21].append(submission())
    with pytest.raises(GradebookError, match="Duplicate Canvas submission"):
        await client.snapshot("12")


async def test_unpublished_and_ungraded_assignments_do_not_trigger_reads(canvas):
    client, source = canvas
    source.assignments += [
        assignment(22, published=False),
        assignment(23, grading_type="not_graded"),
    ]
    result = await client.snapshot("12")
    assert [a["id"] for a in result["assignments"]] == ["21"]
    assert not any(
        "/assignments/22/" in r.url.path or "/assignments/23/" in r.url.path
        for r in source.requests
    )


async def test_assignment_bound_stops_before_any_submission_reads(canvas):
    client, source = canvas
    source.assignments = [assignment(i) for i in range(1, 102)]
    with pytest.raises(GradebookError, match="assignment safety limit"):
        await client.snapshot("12")
    assert not any(r.url.path.endswith("/submissions") for r in source.requests)


async def test_duplicate_assignments_stop_before_any_submission_reads(canvas):
    client, source = canvas
    source.assignments.append(assignment())
    with pytest.raises(GradebookError, match="Duplicate Canvas assignment"):
        await client.snapshot("12")
    assert not any(r.url.path.endswith("/submissions") for r in source.requests)


async def test_total_snapshot_deadline_is_sanitized(monkeypatch):
    async def delayed_response(_):
        await asyncio.sleep(1)
        return httpx.Response(200, json={"private": "fictional"})

    monkeypatch.setattr(transport_module, "SNAPSHOT_TIMEOUT_SECONDS", 0.001)
    client = GradebookClient(
        "https://school.example", "fake", httpx.MockTransport(delayed_response)
    )
    try:
        with pytest.raises(GradebookError) as error:
            await client.snapshot("12")
        assert (
            str(error.value)
            == "Canvas snapshot exceeded the time limit; previous snapshot retained."
        )
    finally:
        await client.close()
