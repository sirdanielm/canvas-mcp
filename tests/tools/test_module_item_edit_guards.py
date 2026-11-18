"""No-network regressions for exact published-parent inserts and draft edits."""
from copy import deepcopy
from unittest.mock import AsyncMock

import pytest

from canvas_mcp.tools import draft_module_items as draft
from canvas_mcp.tools.draft_assignments import digest, private_storage_supported

pytestmark = [pytest.mark.asyncio, pytest.mark.skipif(
    not private_storage_supported(), reason="Requires POSIX private storage")]


def parent(published=True, count=2):
    return {"id": 2, "course_id": 1, "published": published, "name": "Unit 4",
            "position": 7, "items_count": count, "require_sequential_progress": True,
            "prerequisite_module_ids": [5], "unlock_at": "2026-11-20T00:00:00Z"}


def child(item_id=10, position=1, **changes):
    value = {"id": item_id, "module_id": 2, "type": "ExternalUrl", "position": position,
             "title": "Existing material", "published": True, "indent": 0,
             "external_url": "https://example.org/material", "new_tab": True}
    value.update(changes)
    return value


def prepared(**changes):
    before = [child(), child(11, 2, title="Existing second")]
    values = {"operation_id": "insert", "course_id": "1", "module_id": "2",
              "item_type": "SubHeader", "position": 2, "existing_item_ids": ["10", "11"],
              "title": "Assessment window", "published": False,
              "expected_parent_published": True, "expected_parent_sha256": digest(parent()),
              "expected_items": before}
    values.update(changes)
    return values


def created(**changes):
    value = child(12, 2, type="SubHeader", title="Assessment window", published=False)
    value.pop("external_url")
    value.pop("new_tab")
    value.update(changes)
    return value


def after_insert(new=None):
    return [child(), new or created(), child(11, 3, title="Existing second")]


@pytest.fixture
def case(tmp_path, monkeypatch):
    service = draft.DraftModuleItems(tmp_path / "journal")
    request = AsyncMock()
    listing = AsyncMock()
    monkeypatch.setattr(draft, "make_canvas_request", request)
    monkeypatch.setattr(draft, "fetch_all_paginated_results", listing)
    return service, request, listing


def insert_reads(request, listing, *, after_parent=None, after=None, new=None):
    new = created() if new is None else new
    request.side_effect = [parent(), parent(), new, new, after_parent or parent(count=3)]
    listing.side_effect = [prepared()["expected_items"], prepared()["expected_items"], after or after_insert(new)]


async def test_published_parent_insert_preserves_all_business_fields_peers_and_order(case):
    service, request, listing = case
    insert_reads(request, listing)
    result = await service.execute(**prepared())
    assert result["status"] == "VERIFIED_DRAFT"
    writes = [c for c in request.call_args_list if c.args[0] != "get"]
    assert len(writes) == 1 and writes[0].args == ("post", "/courses/1/modules/2/items")
    assert writes[0].kwargs == {"data": {"module_item[type]": "SubHeader",
        "module_item[published]": "false", "module_item[position]": 2,
        "module_item[title]": "Assessment window"}, "use_form_data": True, "retry_rate_limits": False}
    assert [c.args[0] for c in request.call_args_list] == ["get", "get", "post", "get", "get"]
    assert listing.call_count == 3
    assert (await service.execute(**prepared(operation_id="new-id")))["status"] == "HELD"
    assert request.call_count == 5


@pytest.mark.parametrize("changes", [
    {"expected_parent_published": 1}, {"expected_parent_published": None},
    {"expected_parent_sha256": None}, {"expected_parent_sha256": "bad"},
    {"expected_items": None}, {"expected_items": [{}]},
    {"expected_items": [child(), child()]}, {"published": True},
])
async def test_published_parent_requires_exact_literal_preimages_before_network(case, changes):
    service, request, listing = case
    assert (await service.execute(**prepared(**changes)))["status"] == "HELD"
    request.assert_not_called()
    listing.assert_not_called()


@pytest.mark.parametrize("change", ["published", "name", "requirements", "course", "id"])
async def test_changed_parent_preimage_holds_before_write(case, change):
    service, request, listing = case
    value = parent()
    if change == "published":
        value["published"] = False
    elif change == "name":
        value["name"] = "Changed"
    elif change == "requirements":
        value["require_sequential_progress"] = False
    elif change == "course":
        value["course_id"] = 9
    else:
        value["id"] = 9
    request.return_value = value
    assert (await service.execute(**prepared()))["status"] == "HELD"
    assert request.call_count == 1
    listing.assert_not_called()


@pytest.mark.parametrize("change", ["content", "relative_order", "missing", "extra", "position"])
async def test_current_ordered_full_inventory_is_required_before_write(case, change):
    service, request, listing = case
    request.return_value = parent()
    values = deepcopy(prepared()["expected_items"])
    if change == "content":
        values[0]["title"] = "Teacher edit"
    elif change == "relative_order":
        values.reverse()
        for index, value in enumerate(values, 1):
            value["position"] = index
    elif change == "missing":
        values.pop()
    elif change == "extra":
        values.append(child(13, 3))
    else:
        values[1]["position"] = 1
    listing.return_value = values
    assert (await service.execute(**prepared()))["status"] == "HELD"
    assert all(c.args[0] == "get" for c in request.call_args_list)


@pytest.mark.parametrize("change", ["published", "name", "requirements", "unknown_field"])
async def test_parent_business_field_or_visibility_change_is_not_verified(case, change):
    service, request, listing = case
    value = parent(count=3)
    if change == "published":
        value["published"] = False
    elif change == "name":
        value["name"] = "Changed"
    elif change == "requirements":
        value["require_sequential_progress"] = False
    else:
        value["unexpected_control"] = True
    insert_reads(request, listing, after_parent=value)
    assert (await service.execute(**prepared()))["status"] == "UNVERIFIED"


@pytest.mark.parametrize("change", ["content", "order", "extra", "new_published", "new_target"])
async def test_readback_peer_content_order_and_new_draft_required(case, change):
    service, request, listing = case
    values = after_insert()
    new = created()
    if change == "content":
        values[0]["external_url"] = "https://example.org/changed"
    elif change == "order":
        values[0], values[2] = values[2], values[0]
        for index, value in enumerate(values, 1):
            value["position"] = index
    elif change == "extra":
        values.append(child(13, 4))
    elif change == "new_published":
        new["published"] = True
        values[1] = new
    else:
        new["module_id"] = 99
        values[1] = new
    insert_reads(request, listing, new=new, after=values)
    assert (await service.execute(**prepared()))["status"] == "UNVERIFIED"


@pytest.mark.parametrize("when", ["before", "after"])
@pytest.mark.parametrize("change", ["published", "course", "id", "missing_visibility"])
async def test_assignment_link_exact_draft_verified_on_both_sides(case, when, change):
    service, request, listing = case
    assignment = {"id": 7, "course_id": 1, "published": False, "is_quiz_assignment": False, "submission_types": ["on_paper"]}
    changed = dict(assignment)
    if change == "published":
        changed["published"] = True
    elif change == "course":
        changed["course_id"] = 9
    elif change == "id":
        changed["id"] = 9
    else:
        changed.pop("published")
    link = created(type="Assignment", content_id=7)
    request.side_effect = [parent(), changed if when == "before" else assignment, assignment, parent(),
                           link, link, parent(count=3), changed if when == "after" else assignment]
    listing.side_effect = [prepared()["expected_items"], prepared()["expected_items"], after_insert(link)]
    result = await service.execute(**prepared(item_type="Assignment", assignment_id="7", title=None))
    assert result["status"] == ("HELD" if when == "before" else "UNVERIFIED")
    if when == "before":
        assert all(c.args[0] == "get" for c in request.call_args_list)


async def test_unknown_insert_is_durable_for_new_operation_id_and_restart(case, tmp_path):
    service, request, listing = case
    request.side_effect = [parent(), parent(), RuntimeError("timeout")]
    listing.return_value = prepared()["expected_items"]
    assert (await service.execute(**prepared()))["status"] == "UNKNOWN"
    restarted = draft.DraftModuleItems(tmp_path / "journal")
    assert (await restarted.execute(**prepared(operation_id="different")))["status"] == "HELD"
    assert request.call_count == 3


def edit_args(**changes):
    target = child(10, 1, type="SubHeader", title="Old heading", published=False)
    values = {"operation_id": "edit", "course_id": "1", "module_id": "2", "item_id": "10",
              "content": {"title": "Assessment window", "position": 2, "indent": 1},
              "expected_item": target, "expected_items": [target, child(11, 2)],
              "expected_parent_sha256": digest(parent()), "expected_parent_published": True}
    values.update(changes)
    return values


def edit_reads(request, listing, *, edited=None, after_parent=None, after=None):
    before = edit_args()["expected_item"]
    edited = dict(before, title="Assessment window", position=2, indent=1) if edited is None else edited
    request.side_effect = [parent(), before, parent(), edited, edited, after_parent or parent()]
    listing.side_effect = [edit_args()["expected_items"], edit_args()["expected_items"], after or [child(11, 1), edited]]


async def test_edit_exact_unpublished_child_moves_only_position_indent_header_title(case):
    service, request, listing = case
    edit_reads(request, listing)
    assert (await service.edit(**edit_args()))["status"] == "VERIFIED_DRAFT"
    writes = [c for c in request.call_args_list if c.args[0] != "get"]
    assert len(writes) == 1 and writes[0].args == ("put", "/courses/1/modules/2/items/10")
    assert writes[0].kwargs == {"data": {"module_item[title]": "Assessment window",
        "module_item[position]": 2, "module_item[indent]": 1},
        "use_form_data": True, "retry_rate_limits": False}
    assert (await service.edit(**edit_args(operation_id="other")))["status"] == "HELD"
    assert len(request.call_args_list) == 6


@pytest.mark.parametrize("changes", [
    {"published": True}, {"expected_parent_published": 0}, {"expected_parent_sha256": "bad"},
    {"content": {"published": False}}, {"content": {"content_id": 7}}, {"content": {"type": "Assignment"}},
    {"content": {"position": True}}, {"content": {"position": 3}}, {"content": {"indent": -1}},
    {"content": {"indent": True}}, {"content": {"indent": 6}}, {"content": {"title": ""}},
    {"expected_item": child(10, 1, published=True)}, {"expected_items": []},
])
async def test_edit_rejects_broad_changes_or_missing_preimages_before_network(case, changes):
    service, request, listing = case
    assert (await service.edit(**edit_args(**changes)))["status"] == "HELD"
    request.assert_not_called()
    listing.assert_not_called()


@pytest.mark.parametrize("change", ["parent", "item", "inventory"])
async def test_edit_fresh_preimage_mismatch_holds(case, change):
    service, request, listing = case
    before = edit_args()["expected_item"]
    request.side_effect = [dict(parent(), name="Teacher edit") if change == "parent" else parent(),
                           dict(before, indent=2) if change == "item" else before]
    listing.return_value = ([before, child(11, 2, title="Teacher edit")] if change == "inventory"
                            else edit_args()["expected_items"])
    assert (await service.edit(**edit_args()))["status"] == "HELD"
    assert all(c.args[0] == "get" for c in request.call_args_list)


@pytest.mark.parametrize("change", ["target_published", "target_content", "peer", "parent", "order"])
async def test_edit_readback_checks_all_unchanged_content_and_published_state(case, change):
    service, request, listing = case
    edited = dict(edit_args()["expected_item"], title="Assessment window", position=2, indent=1)
    after = [child(11, 1), edited]
    after_parent = parent()
    if change == "target_published":
        edited["published"] = True
    elif change == "target_content":
        edited["external_url"] = "https://example.org/changed"
    elif change == "peer":
        after[0]["title"] = "Teacher edit"
    elif change == "parent":
        after_parent["prerequisite_module_ids"] = []
    else:
        after.reverse()
        for index, value in enumerate(after, 1):
            value["position"] = index
    edit_reads(request, listing, edited=edited, after=after, after_parent=after_parent)
    assert (await service.edit(**edit_args()))["status"] in {"UNKNOWN", "UNVERIFIED"}


async def test_noop_edit_makes_no_put_and_is_still_once_only(case):
    service, request, listing = case
    args = edit_args(content={"title": "Old heading"})
    request.side_effect = [parent(), args["expected_item"]]
    listing.return_value = args["expected_items"]
    assert (await service.edit(**args))["status"] == "VERIFIED_NOOP"
    assert all(c.args[0] == "get" for c in request.call_args_list)
    assert (await service.edit(**dict(args, operation_id="other")))["status"] == "HELD"


async def test_uncertain_edit_no_retry_or_replay(case, tmp_path):
    service, request, listing = case
    request.side_effect = [parent(), edit_args()["expected_item"], parent(), RuntimeError("timeout")]
    listing.return_value = edit_args()["expected_items"]
    assert (await service.edit(**edit_args()))["status"] == "UNKNOWN"
    restarted = draft.DraftModuleItems(tmp_path / "journal")
    assert (await restarted.edit(**edit_args(operation_id="other")))["status"] == "HELD"
    assert request.call_count == 4


async def test_assignment_edit_allows_only_position_indent_never_title_or_published_target(case):
    service, request, listing = case
    target = child(10, 1, type="Assignment", published=False, content_id=7)
    args = edit_args(expected_item=target, expected_items=[target, child(11, 2)])
    assert (await service.edit(**args))["status"] == "HELD"
    request.assert_not_called()
    args["content"] = {"position": 2, "indent": 1}
    assignment = {"id": 7, "course_id": 1, "published": False, "is_quiz_assignment": False, "submission_types": ["on_paper"]}
    edited = dict(target, position=2, indent=1)
    request.side_effect = [parent(), target, assignment, assignment, parent(), edited, edited, parent(), assignment]
    listing.side_effect = [args["expected_items"], args["expected_items"], [child(11, 1), edited]]
    assert (await service.edit(**args))["status"] == "VERIFIED_DRAFT"
    assert sum(c.args[0] == "put" for c in request.call_args_list) == 1


async def test_assignment_insert_into_published_parent_remains_unpublished(case):
    service, request, listing = case
    assignment = {"id": 7, "course_id": 1, "published": False, "is_quiz_assignment": False, "submission_types": ["on_paper"]}
    link = created(type="Assignment", content_id=7)
    request.side_effect = [parent(), assignment, assignment, parent(), link, link, parent(count=3), assignment]
    listing.side_effect = [prepared()["expected_items"], prepared()["expected_items"], after_insert(link)]
    assert (await service.execute(**prepared(item_type="Assignment", assignment_id="7", title=None)))["status"] == "VERIFIED_DRAFT"
    post = next(c for c in request.call_args_list if c.args[0] == "post")
    assert post.kwargs["data"]["module_item[content_id]"] == "7"
    assert post.kwargs["data"]["module_item[published]"] == "false"
    assert not any(c.args[0] in {"put", "delete"} for c in request.call_args_list)


@pytest.mark.parametrize("count", [1, True, None])
async def test_parent_count_must_match_fresh_complete_inventory(case, count):
    service, request, listing = case
    before = parent(count=count)
    request.return_value = before
    listing.return_value = prepared()["expected_items"]
    assert (await service.execute(**prepared(expected_parent_sha256=digest(before))))["status"] == "HELD"
    assert all(c.args[0] == "get" for c in request.call_args_list)


async def test_known_created_identity_durable_when_readback_fails(case, tmp_path):
    service, request, listing = case
    request.side_effect = [parent(), parent(), created(), RuntimeError("readback unavailable")]
    listing.return_value = prepared()["expected_items"]
    assert (await service.execute(**prepared()))["status"] == "UNVERIFIED"
    import json
    saved = json.loads((tmp_path / "journal" / "insert.dispatch.result.json").read_text(encoding="utf-8"))
    assert saved == {"item_id": "12", "module_id": "2", "course_id": "1"}
    assert (await service.execute(**prepared(operation_id="retry")))["status"] == "HELD"
    assert sum(c.args[0] == "post" for c in request.call_args_list) == 1


@pytest.mark.parametrize("when", ["before", "after"])
async def test_assignment_edit_requires_linked_unpublished_assignment_pre_and_post(case, when):
    service, request, listing = case
    target = child(10, 1, type="Assignment", published=False, content_id=7)
    args = edit_args(expected_item=target, expected_items=[target, child(11, 2)],
                     content={"position": 2})
    good = {"id": 7, "course_id": 1, "published": False, "is_quiz_assignment": False, "submission_types": ["on_paper"]}
    bad = dict(good, published=True)
    edited = dict(target, position=2)
    request.side_effect = [parent(), target, bad if when == "before" else good, good, parent(),
                           edited, edited, parent(), bad]
    listing.side_effect = [args["expected_items"], args["expected_items"], [child(11, 1), edited]]
    assert (await service.edit(**args))["status"] == ("HELD" if when == "before" else "UNVERIFIED")
    assert sum(c.args[0] == "put" for c in request.call_args_list) == (0 if when == "before" else 1)


@pytest.mark.parametrize("operation", ["insert", "edit"])
@pytest.mark.parametrize("field,value", [("name", "Teacher edit"), ("description", "Teacher body"),
    ("points_possible", 9)])
async def test_full_linked_assignment_preimage_preserved_after_write(case, operation, field, value):
    service, request, listing = case
    assignment = {"id": 7, "course_id": 1, "published": False, "is_quiz_assignment": False, "submission_types": ["on_paper"], "name": "Original",
                  "description": "Original body", "points_possible": 5}
    changed = dict(assignment, **{field: value})
    if operation == "insert":
        link = created(type="Assignment", content_id=7)
        request.side_effect = [parent(), assignment, assignment, parent(), link, link, parent(count=3), changed]
        listing.side_effect = [prepared()["expected_items"], prepared()["expected_items"], after_insert(link)]
        result = await service.execute(**prepared(item_type="Assignment", assignment_id="7", title=None))
    else:
        target = child(10, 1, type="Assignment", published=False, content_id=7)
        edited = dict(target, position=2)
        args = edit_args(content={"position": 2}, expected_item=target, expected_items=[target, child(11, 2)])
        request.side_effect = [parent(), target, assignment, assignment, parent(), edited, edited, parent(), changed]
        listing.side_effect = [args["expected_items"], args["expected_items"], [child(11, 1), edited]]
        result = await service.edit(**args)
    assert result["status"] == "UNVERIFIED"
    assert sum(c.args[0] in {"post", "put"} for c in request.call_args_list) == 1


@pytest.mark.parametrize("operation", ["insert", "edit"])
@pytest.mark.parametrize("changed", ["parent", "inventory", "assignment"])
async def test_final_presend_preimages_changed_holds_without_write(case, operation, changed):
    service, request, listing = case
    assignment = {"id": 7, "course_id": 1, "published": False, "is_quiz_assignment": False, "submission_types": ["on_paper"], "name": "Original"}
    final_assignment = dict(assignment, name="Teacher edit") if changed == "assignment" else assignment
    final_parent = dict(parent(), name="Teacher edit") if changed == "parent" else parent()
    if operation == "insert":
        before = prepared()["expected_items"]
        request.side_effect = [parent(), assignment, final_assignment, final_parent]
        final_items = [dict(before[0], title="Teacher edit"), before[1]] if changed == "inventory" else before
        listing.side_effect = [before, final_items]
        result = await service.execute(**prepared(item_type="Assignment", assignment_id="7", title=None))
    else:
        target = child(10, 1, type="Assignment", published=False, content_id=7)
        before = [target, child(11, 2)]
        request.side_effect = [parent(), target, assignment, final_assignment, final_parent]
        final_items = [target, child(11, 2, title="Teacher edit")] if changed == "inventory" else before
        listing.side_effect = [before, final_items]
        result = await service.edit(**edit_args(content={"position": 2}, expected_item=target, expected_items=before))
    assert result["status"] == "HELD"
    assert all(c.args[0] == "get" for c in request.call_args_list)


async def test_reorder_duplicate_linked_asset_omits_publication_and_preserves_other_link(case):
    service, request, listing = case
    target = child(10, 1, type="Assignment", published=False, content_id=7)
    second_link = child(11, 2, type="Assignment", published=False, content_id=7,
                        title="Same asset, separately retained tag", indent=2)
    assignment = {"id": 7, "course_id": 1, "published": False, "is_quiz_assignment": False, "submission_types": ["on_paper"], "name": "Draft asset",
                  "description": "Retained draft body", "points_possible": 5}
    original_assignment = deepcopy(assignment)
    original_peer = deepcopy(second_link)
    state = {"items": [target, second_link]}

    async def fake_request(method, endpoint, **kwargs):
        if method == "get":
            if endpoint == "/courses/1/modules/2":
                return parent()
            if endpoint == "/courses/1/assignments/7":
                return deepcopy(assignment)
            assert endpoint == "/courses/1/modules/2/items/10"
            return deepcopy(next(i for i in state["items"] if i["id"] == 10))
        assert method == "put" and endpoint == "/courses/1/modules/2/items/10"
        # A published key would invoke Canvas's coupled asset/tag workflow.
        assert kwargs == {"data": {"module_item[position]": 2},
                          "use_form_data": True, "retry_rate_limits": False}
        state["items"] = [dict(second_link, position=1), dict(target, position=2)]
        return deepcopy(state["items"][1])

    request.side_effect = fake_request
    listing.side_effect = lambda endpoint: deepcopy(state["items"])
    result = await service.edit(**edit_args(content={"position": 2}, expected_item=target,
                                            expected_items=[target, second_link]))
    assert result["status"] == "VERIFIED_DRAFT"
    assert assignment == original_assignment
    assert state["items"][0] == dict(original_peer, position=1)
    assert assignment["published"] is False and state["items"][0]["published"] is False
    assert sum(c.args[0] == "put" for c in request.call_args_list) == 1


@pytest.mark.parametrize("operation", ["insert", "edit"])
@pytest.mark.parametrize("bad", [
    {"is_quiz_assignment": True, "submission_types": ["online_quiz"]},
    {"is_quiz_assignment": None},
    {"discussion_topic": {"id": 8}},
    {"submission_types": ["discussion_topic"]},
    {"submission_types": ["external_tool"]},
    {"submission_types": []},
    {"submission_types": [None]},
])
async def test_nonordinary_linked_assignment_held_before_any_write(case, operation, bad):
    service, request, listing = case
    assignment = {"id": 7, "course_id": 1, "published": False,
                  "is_quiz_assignment": False, "submission_types": ["on_paper"], **bad}
    if operation == "insert":
        request.side_effect = [parent(), assignment]
        result = await service.execute(**prepared(item_type="Assignment", assignment_id="7", title=None))
        listing.assert_not_called()
    else:
        target = child(10, 1, type="Assignment", published=False, content_id=7)
        before = [target, child(11, 2)]
        request.side_effect = [parent(), target, assignment]
        listing.return_value = before
        result = await service.edit(**edit_args(content={"position": 2}, expected_item=target, expected_items=before))
    assert result["status"] == "HELD"
    assert all(call.args[0] == "get" for call in request.call_args_list)


@pytest.mark.parametrize("operation", ["insert", "edit"])
@pytest.mark.parametrize("phase", ["final", "readback"])
async def test_linked_assignment_ordinary_guard_at_last_send_and_readback(case, operation, phase):
    service, request, listing = case
    good = {"id": 7, "course_id": 1, "published": False,
            "is_quiz_assignment": False, "submission_types": ["on_paper"]}
    bad = dict(good, is_quiz_assignment=True, submission_types=["online_quiz"])
    if operation == "insert":
        link = created(type="Assignment", content_id=7)
        request.side_effect = [parent(), good, bad if phase == "final" else good,
                               parent(), link, link, parent(count=3), bad]
        before = prepared()["expected_items"]
        listing.side_effect = [before, before, after_insert(link)]
        result = await service.execute(**prepared(item_type="Assignment", assignment_id="7", title=None))
    else:
        target = child(10, 1, type="Assignment", published=False, content_id=7)
        before = [target, child(11, 2)]
        edited = dict(target, position=2)
        request.side_effect = [parent(), target, good, bad if phase == "final" else good,
                               parent(), edited, edited, parent(), bad]
        listing.side_effect = [before, before, [child(11, 1), edited]]
        result = await service.edit(**edit_args(content={"position": 2}, expected_item=target, expected_items=before))
    assert result["status"] == ("HELD" if phase == "final" else "UNVERIFIED")
    assert sum(call.args[0] in {"post", "put"} for call in request.call_args_list) == (0 if phase == "final" else 1)
