"""Synthetic assignment slice: no credentials, startup or network."""
from unittest.mock import AsyncMock

import pytest

from canvas_mcp.tools import draft_assignments as draft
from canvas_mcp.tools.draft_assignments import private_storage_supported


def creation(**changes):
    value = {"name": "Draft", "description": "Body", "submission_type": "on_paper", "points_possible": 10,
             "assignment_group_id": "2", "due_at": None}
    value.update(changes)
    return value


def assignment(**changes):
    result = {"id": 4, "course_id": 1, "name": "Draft", "description": "Body", "published": False,
                  "submission_types": ["on_paper"], "points_possible": 10, "grading_type": "points",
                  "due_at": None, "unlock_at": None, "lock_at": None, "assignment_group_id": 2,
                  "peer_reviews": False, "automatic_peer_reviews": False, "is_quiz_assignment": False}
    result.update(has_overrides=False, post_to_sis=False)
    result.update(changes)
    return result


@pytest.fixture
def setup(tmp_path, monkeypatch):
    request = AsyncMock()
    monkeypatch.setattr(draft, "make_canvas_request", request)
    monkeypatch.setattr(draft, "fetch_all_paginated_results", AsyncMock(return_value=[{"id": 2}]))
    return draft.DraftAssignmentService(tmp_path / "journal"), request


@pytest.mark.asyncio
@pytest.mark.parametrize("published", [True, "false", "true", 0, 1, None])
async def test_strict_false_before_network(setup, published):
    service, request = setup
    result = await service.execute(operation_id="test", course_id="1", content=creation(), published=published)
    assert result["status"] == "HELD"
    request.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("field,value", [("published", False), ("publish_at", "tomorrow"),
    ("peer_reviews", True), ("notify", True), ("external_tool_tag_attributes", {}),
    ("submission_type", "external_tool"), ("submission_type", "discussion_topic")])
async def test_side_effect_fields_rejected(setup, field, value):
    service, request = setup
    result = await service.execute(operation_id="test", course_id="1", content=dict(creation(), **{field: value}))
    assert result["status"] == "HELD"
    request.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.skipif(not private_storage_supported(), reason="Requires POSIX private storage")
async def test_create_independent_readback_and_restart_replay(setup):
    service, request = setup
    request.side_effect = [assignment(), assignment()]
    args = {"operation_id": "one", "course_id": "1", "content": creation(), "published": False}
    assert (await service.execute(**args))["status"] == "VERIFIED_DRAFT"
    assert [x.args[0] for x in request.call_args_list] == ["post", "get"]
    assert request.call_args_list[0].kwargs["retry_rate_limits"] is False
    assert request.call_args_list[0].kwargs["data"]["assignment[published]"] == "false"
    restarted = draft.DraftAssignmentService(service.journal)
    assert (await restarted.execute(**args))["status"] == "HELD"
    assert request.call_count == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("response", [{"error": "timeout"}, {}, assignment(course_id=2), assignment(published=True)])
@pytest.mark.skipif(not private_storage_supported(), reason="Requires POSIX private storage")
async def test_uncertain_post_never_retried(setup, response):
    service, request = setup
    request.return_value = response
    args = {"operation_id": "uncertain", "course_id": "1", "content": creation()}
    assert (await service.execute(**args))["status"] == "UNKNOWN"
    assert (await service.execute(**args))["status"] == "HELD"
    request.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("changes", [{"published": True}, {"course_id": 2}, {"id": 8},
    {"is_quiz_assignment": True}, {"submission_types": ["external_tool"]}, {"published": None}])
@pytest.mark.skipif(not private_storage_supported(), reason="Requires POSIX private storage")
async def test_update_preflight_refuses_unsafe_target(setup, changes):
    service, request = setup
    before = assignment(**changes)
    request.return_value = before
    result = await service.execute(operation_id="update", course_id="1", assignment_id="4",
        expected_sha256=draft.digest(before), content={"description": "New"})
    assert result["status"] == "HELD"
    request.assert_awaited_once_with("get", "/courses/1/assignments/4")


@pytest.mark.asyncio
@pytest.mark.skipif(not private_storage_supported(), reason="Requires POSIX private storage")
async def test_update_exact_preimage_and_protected_metadata(setup):
    service, request = setup
    before = assignment()
    after = assignment(description="New")
    request.side_effect = [before, after, after]
    result = await service.execute(operation_id="update", course_id="1", assignment_id="4",
        expected_sha256=draft.digest(before), content={"description": "New"})
    assert result["status"] == "VERIFIED_DRAFT"
    assert [x.args[0] for x in request.call_args_list] == ["get", "put", "get"]
    assert request.call_args_list[1].kwargs["data"] == {"assignment[description]": "New"}


@pytest.mark.asyncio
@pytest.mark.parametrize("changes", [{"published": True}, {"points_possible": 9}, {"course_id": 2}, {"description": "Teacher change"}])
@pytest.mark.skipif(not private_storage_supported(), reason="Requires POSIX private storage")
async def test_changed_readback_never_verified(setup, changes):
    service, request = setup
    before = assignment()
    after = assignment(description="New")
    readback = dict(after, **changes)
    request.side_effect = [before, after, readback]
    result = await service.execute(operation_id="update", course_id="1", assignment_id="4",
        expected_sha256=draft.digest(before), content={"description": "New"})
    assert result["status"] == "UNVERIFIED"


@pytest.mark.asyncio
@pytest.mark.skipif(not private_storage_supported(), reason="Requires POSIX private storage")
async def test_stale_preimage_stops_before_put(setup):
    service, request = setup
    request.return_value = assignment(description="Teacher change")
    result = await service.execute(operation_id="update", course_id="1", assignment_id="4",
        expected_sha256=draft.digest(assignment()), content={"description": "New"})
    assert result["status"] == "HELD"
    assert request.call_count == 1


@pytest.mark.asyncio
@pytest.mark.skipif(not private_storage_supported(), reason="Requires POSIX private storage")
async def test_unknown_create_blocks_same_binding_with_new_operation(setup):
    service, request = setup
    request.return_value = {"error": "timeout"}
    args = {"course_id": "1", "content": creation()}
    assert (await service.execute(operation_id="first", **args))["status"] == "UNKNOWN"
    assert (await service.execute(operation_id="second", **args))["status"] == "HELD"
    assert request.call_count == 1


@pytest.mark.asyncio
@pytest.mark.skipif(not private_storage_supported(), reason="Requires POSIX private storage")
async def test_failed_readback_retains_confirmed_identity(setup):
    import json
    service, request = setup
    request.side_effect = [assignment(), RuntimeError("read unavailable")]
    result = await service.execute(operation_id="first", course_id="1", content=creation())
    assert result["status"] == "UNVERIFIED"
    assert result["assignment_id"] == "4"
    assert json.loads((service.journal / "first.dispatch.json").read_text(encoding="utf-8"))["assignment_id"] == "4"


@pytest.mark.asyncio
@pytest.mark.skipif(not private_storage_supported(), reason="Requires POSIX private storage")
async def test_insecure_journal_cannot_dispatch(setup):
    service, request = setup
    service.journal.mkdir(mode=0o755)
    service.journal.chmod(0o755)
    with pytest.raises(ValueError, match="Journal"):
        await service.execute(operation_id="first", course_id="1", content=creation())
    request.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("field", ["points_possible", "assignment_group_id", "due_at", "description", "submission_type"])
async def test_missing_canonical_create_field_holds_before_network(setup, field):
    service, request = setup
    content = creation()
    content.pop(field)
    assert (await service.execute(operation_id="missing", course_id="1", content=content))["status"] == "HELD"
    request.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("points", [True, -1, float("nan"), float("inf"), "10"])
async def test_invalid_points_hold(setup, points):
    service, request = setup
    assert (await service.execute(operation_id="points", course_id="1", content=creation(points_possible=points)))["status"] == "HELD"
    request.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("due", ["tomorrow", "2026-11-20", "2026-11-20T12:00:00", "2026-02-30T12:00:00Z"])
async def test_ambiguous_or_invalid_due_holds(setup, due):
    service, request = setup
    assert (await service.execute(operation_id="due", course_id="1", content=creation(due_at=due)))["status"] == "HELD"
    request.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.skipif(not private_storage_supported(), reason="Requires POSIX private storage")
async def test_canonical_create_metadata_and_due_readback(setup):
    service, request = setup
    due = "2026-11-20T17:00:00Z"
    request.side_effect = [assignment(due_at=due), assignment(due_at=due)]
    assert (await service.execute(operation_id="canonical", course_id="1", content=creation(due_at=due)))["status"] == "VERIFIED_DRAFT"
    wire = request.call_args_list[0].kwargs["data"]
    assert wire["assignment[points_possible]"] == 10
    assert wire["assignment[assignment_group_id]"] == "2"
    assert wire["assignment[due_at]"] == due
    assert wire["assignment[published]"] == wire["assignment[post_to_sis]"] == "false"
    assert not any("notify" in k or "external_tool" in k or "override" in k for k in wire)


@pytest.mark.asyncio
@pytest.mark.parametrize("groups", [[], {"error": "unavailable"}, [{"id": 2, "course_id": 9}], [{"id": 2}, {"id": 2}]])
@pytest.mark.skipif(not private_storage_supported(), reason="Requires POSIX private storage")
async def test_wrong_missing_ambiguous_group_no_post(setup, monkeypatch, groups):
    service, request = setup
    monkeypatch.setattr(draft, "fetch_all_paginated_results", AsyncMock(return_value=groups))
    assert (await service.execute(operation_id="group", course_id="1", content=creation()))["status"] == "HELD"
    request.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("changes", [{"points_possible": 20}, {"assignment_group_id": 3},
    {"due_at": "2026-11-20T12:00:00Z"}, {"has_overrides": True}, {"post_to_sis": True},
    {"unlock_at": "2026-11-20T12:00:00Z"}])
@pytest.mark.skipif(not private_storage_supported(), reason="Requires POSIX private storage")
async def test_metadata_readback_mismatch_unverified(setup, changes):
    service, request = setup
    request.side_effect = [assignment(), assignment(**changes)]
    assert (await service.execute(operation_id="mismatch", course_id="1", content=creation()))["status"] == "UNVERIFIED"


@pytest.mark.asyncio
@pytest.mark.parametrize("field,value", [("points_possible", 10), ("assignment_group_id", "2"), ("due_at", None),
    ("assignment_overrides", []), ("notify_of_update", True), ("post_to_sis", True)])
async def test_updates_cannot_alter_grade_metadata_dates_or_side_effects(setup, field, value):
    service, request = setup
    result = await service.execute(operation_id="update", course_id="1", assignment_id="4",
        expected_sha256=draft.digest(assignment()), content={"description": "New", field: value})
    assert result["status"] == "HELD"
    request.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.skipif(not private_storage_supported(), reason="Requires POSIX private storage")
async def test_absent_null_due_readback_is_not_verified(setup):
    service, request = setup
    readback = assignment()
    readback.pop("due_at")
    request.side_effect = [assignment(), readback]
    assert (await service.execute(operation_id="absent", course_id="1", content=creation()))["status"] == "UNVERIFIED"


@pytest.mark.asyncio
@pytest.mark.parametrize("points", [True, False, float("nan"), float("inf")])
@pytest.mark.skipif(not private_storage_supported(), reason="Requires POSIX private storage")
async def test_readback_points_require_actual_finite_number(setup, points):
    service, request = setup
    content = creation(points_possible=int(points) if type(points) is bool else 10)
    request.side_effect = [assignment(), assignment(points_possible=points)]
    assert (await service.execute(operation_id="badpoints", course_id="1", content=content))["status"] == "UNVERIFIED"
