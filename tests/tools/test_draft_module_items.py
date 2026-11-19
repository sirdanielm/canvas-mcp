"""Synthetic module-item preparation, no live Canvas."""
from unittest.mock import AsyncMock

import pytest

from canvas_mcp.tools import draft_module_items as draft
from canvas_mcp.tools.draft_assignments import private_storage_supported


@pytest.fixture
def case(tmp_path, monkeypatch):
    service = draft.DraftModuleItems(tmp_path / "journal")
    request = AsyncMock()
    listing = AsyncMock(return_value=[])
    monkeypatch.setattr(draft, "make_canvas_request", request)
    monkeypatch.setattr(draft, "fetch_all_paginated_results", listing)
    return service, request, listing


def args(**changes):
    values = {"operation_id": "one", "course_id": "1", "module_id": "2", "item_type": "SubHeader",
              "title": "Test date", "position": 1, "existing_item_ids": [], "published": False}
    values.update(changes)
    return values


def item(**changes):
    values = {"id": 3, "module_id": 2, "type": "SubHeader", "title": "Test date", "position": 1, "published": False}
    values.update(changes)
    return values


@pytest.mark.asyncio
@pytest.mark.parametrize("changes", [{"published": True}, {"published": 0}, {"item_type": "ExternalTool"},
    {"position": True}, {"position": 0}, {"assignment_id": "4"}])
async def test_invalid_before_network(case, changes):
    service, request, listing = case
    assert (await service.execute(**args(**changes)))["status"] == "HELD"
    request.assert_not_called()
    listing.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.skipif(not private_storage_supported(), reason="Requires POSIX private storage")
async def test_header_with_parent_and_position_readback(case):
    service, request, _ = case
    parent = {"id": 2, "published": False}
    request.side_effect = [parent, item(), item(), parent]
    assert (await service.execute(**args()))["status"] == "VERIFIED_DRAFT"
    assert [c.args[0] for c in request.call_args_list] == ["get", "post", "get", "get"]
    assert request.call_args_list[1].kwargs["retry_rate_limits"] is False


@pytest.mark.asyncio
@pytest.mark.parametrize("assignment", [{"id": 4, "course_id": 9, "published": False},
    {"id": 4, "course_id": 1, "published": True}, {"id": 5, "course_id": 1, "published": False}])
@pytest.mark.skipif(not private_storage_supported(), reason="Requires POSIX private storage")
async def test_wrong_or_published_assignment_held(case, assignment):
    service, request, listing = case
    request.side_effect = [{"id": 2, "published": False}, assignment]
    assert (await service.execute(**args(item_type="Assignment", assignment_id="4", title=None)))["status"] == "HELD"
    assert all(c.args[0] == "get" for c in request.call_args_list)
    listing.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.skipif(not private_storage_supported(), reason="Requires POSIX private storage")
async def test_assignment_independent_link_parent_content_readback(case):
    service, request, _ = case
    parent = {"id": 2, "published": False}
    assignment = ordinary_assignment()
    link = item(type="Assignment", content_id=4)
    request.side_effect = [parent, assignment, link, link, parent, assignment]
    assert (await service.execute(**args(item_type="Assignment", assignment_id="4", title=None)))["status"] == "VERIFIED_DRAFT"
    assert [c.args[0] for c in request.call_args_list] == ["get", "get", "post", "get", "get", "get"]


@pytest.mark.asyncio
@pytest.mark.parametrize("readback", [item(position=2), item(published=True), item(module_id=9), item(type="Page")])
@pytest.mark.skipif(not private_storage_supported(), reason="Requires POSIX private storage")
async def test_readback_mismatch_held(case, readback):
    service, request, _ = case
    parent = {"id": 2, "published": False}
    request.side_effect = [parent, item(), readback, parent]
    assert (await service.execute(**args()))["status"] == "UNVERIFIED"


@pytest.mark.asyncio
@pytest.mark.skipif(not private_storage_supported(), reason="Requires POSIX private storage")
async def test_uncertain_post_no_retry(case):
    service, request, _ = case
    request.side_effect = [{"id": 2, "published": False}, {"error": "timeout"}]
    assert (await service.execute(**args()))["status"] == "UNKNOWN"
    assert (await service.execute(**args()))["status"] == "HELD"
    assert request.call_count == 2


@pytest.mark.asyncio
@pytest.mark.skipif(not private_storage_supported(), reason="Requires POSIX private storage")
async def test_published_parent_no_write(case):
    service, request, listing = case
    request.return_value = {"id": 2, "published": True}
    assert (await service.execute(**args()))["status"] == "HELD"
    request.assert_awaited_once()
    listing.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("inventory", [{"error": "failed"}, [{}], [{"id": 9, "module_id": 2}],
    [{"id": 9, "module_id": 2}, {"id": 9, "module_id": 2}]])
@pytest.mark.skipif(not private_storage_supported(), reason="Requires POSIX private storage")
async def test_bad_inventory_never_posts(case, inventory):
    service, request, listing = case
    request.return_value = {"id": 2, "published": False}
    listing.return_value = inventory
    assert (await service.execute(**args()))["status"] == "HELD"
    request.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("changed", ["parent", "assignment"])
@pytest.mark.skipif(not private_storage_supported(), reason="Requires POSIX private storage")
async def test_visibility_changes_during_readback_unverified(case, changed):
    service, request, _ = case
    parent = {"id": 2, "published": False}
    assignment = ordinary_assignment()
    link = item(type="Assignment", content_id=4)
    after_parent = dict(parent, published=changed == "parent")
    after_assignment = dict(assignment, published=changed == "assignment")
    request.side_effect = [parent, assignment, link, link, after_parent, after_assignment]
    result = await service.execute(**args(item_type="Assignment", assignment_id="4", title=None))
    assert result["status"] == "UNVERIFIED"


def ordinary_assignment(**changes):
    value = {"id": 4, "course_id": 1, "published": False, "is_quiz_assignment": False,
             "discussion_topic": None, "submission_types": ["on_paper"]}
    value.update(changes)
    return value


@pytest.mark.asyncio
@pytest.mark.parametrize("shape", [
    {"is_quiz_assignment": True},
    {"discussion_topic": {"id": 8}},
    {"submission_types": ["external_tool"]},
    {"submission_types": ["unsupported"]},
    {"submission_types": None},
    {"is_quiz_assignment": None},
    {},
])
@pytest.mark.skipif(not private_storage_supported(), reason="Requires POSIX private storage")
async def test_assignment_proxy_or_unknown_shape_held_before_post(case, shape):
    service, request, listing = case
    parent = {"id": 2, "published": False}
    linked = ordinary_assignment(**shape) if shape else {"id": 4, "course_id": 1, "published": False}
    link = item(type="Assignment", content_id=4)
    request.side_effect = [parent, linked, link, link, parent, linked]
    result = await service.execute(**args(item_type="Assignment", assignment_id="4", title=None))
    assert result["status"] == "HELD"
    assert [c.args[0] for c in request.call_args_list] == ["get", "get"]
    listing.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("shape", [
    {"is_quiz_assignment": True},
    {"discussion_topic": {"id": 8}},
    {"submission_types": ["external_tool"]},
    {"submission_types": ["unsupported"]},
    {"submission_types": None},
    {"is_quiz_assignment": None},
    {},
])
@pytest.mark.skipif(not private_storage_supported(), reason="Requires POSIX private storage")
async def test_assignment_becoming_proxy_or_unknown_unverified(case, shape):
    service, request, _ = case
    parent = {"id": 2, "published": False}
    linked = ordinary_assignment(**shape) if shape else {"id": 4, "course_id": 1, "published": False}
    link = item(type="Assignment", content_id=4)
    request.side_effect = [parent, ordinary_assignment(), link, link, parent, linked]
    result = await service.execute(**args(item_type="Assignment", assignment_id="4", title=None))
    assert result["status"] == "UNVERIFIED"
    assert [c.args[0] for c in request.call_args_list].count("post") == 1
