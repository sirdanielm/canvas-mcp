"""Synthetic container-publication contract; no live Canvas or credentials."""
from __future__ import annotations

import copy
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock
from urllib.parse import parse_qs

import httpx
import pytest

from canvas_mcp.tools import module_publication as publication
from canvas_mcp.tools.draft_assignments import private_storage_supported

pytestmark = pytest.mark.skipif(not private_storage_supported(), reason="Requires POSIX private journal")


def parent() -> dict:
    return {"id": 2, "course_id": 1, "name": "Synthetic module", "published": False,
            "position": 1, "unlock_at": None, "require_sequential_progress": False,
            "prerequisite_module_ids": [], "publish_final_grade": False, "items_count": 0}


def assignment() -> dict:
    return {"id": 4, "course_id": 1, "name": "Synthetic assignment", "description": "Existing body",
            "published": True, "is_quiz_assignment": False, "discussion_topic": None,
            "submission_types": ["on_paper"], "points_possible": 5, "grading_type": "points",
            "due_at": None, "unlock_at": None, "lock_at": None, "assignment_group_id": 7,
            "peer_reviews": False, "automatic_peer_reviews": False, "post_to_sis": False}


def item(item_id: int = 3, **changes) -> dict:
    value = {"id": item_id, "module_id": 2, "published": True, "type": "Assignment",
             "content_id": 4, "position": 1, "indent": 0, "title": "Synthetic assignment"}
    value.update(changes)
    return value


@pytest.fixture
def case(tmp_path, monkeypatch):
    state = {"parent": parent(), "items": [], "assignment": assignment(), "put_count": 0,
             "put_error": None, "put_response": None, "after_put": None}

    async def request(method, endpoint, **kwargs):
        if method == "get":
            if endpoint == "/courses/1/modules/2":
                return copy.deepcopy(state["parent"])
            if endpoint == "/courses/1/assignments/4":
                return copy.deepcopy(state["assignment"])
            raise AssertionError(f"Unexpected GET: {endpoint}")
        assert method == "put"
        assert endpoint == "/courses/1/modules/2"
        assert kwargs == {"data": {"module[published]": "true", "module[skip_content_tags]": "true"},
                          "use_form_data": True, "retry_rate_limits": False}
        state["put_count"] += 1
        if state["put_error"]:
            raise state["put_error"]
        state["parent"]["published"] = True
        if state["after_put"]:
            state["after_put"](state)
        return copy.deepcopy(state["put_response"] if state["put_response"] is not None else state["parent"])

    async def listing(endpoint):
        assert endpoint == "/courses/1/modules/2/items"
        return copy.deepcopy(state["items"])

    request_mock = AsyncMock(side_effect=request)
    listing_mock = AsyncMock(side_effect=listing)
    monkeypatch.setattr(publication, "make_canvas_request", request_mock)
    monkeypatch.setattr(publication, "fetch_all_paginated_results", listing_mock)
    service = publication.ModulePublicationService(tmp_path / "journal", course_id="1", module_id="2", enabled=True)
    return service, state, request_mock, listing_mock


def with_items(state: dict, values: list[dict]) -> None:
    state["items"] = values
    state["parent"]["items_count"] = len(values)


async def prepared(service, **changes):
    args = {"operation_id": "publish-one", "purpose": "Approved synthetic container-only release"}
    args.update(changes)
    preview = await service.prepare(**args)
    assert preview["status"] == "REVIEW"
    return args, preview


@pytest.mark.asyncio
async def test_disabled_is_default_before_any_network(case, tmp_path):
    _, _, request, listing = case
    service = publication.ModulePublicationService(tmp_path / "off", course_id="1", module_id="2")
    assert (await service.prepare(operation_id="one", purpose="Release"))["status"] == "HELD"
    assert (await service.confirm(operation_id="one", purpose="Release", confirmation_token="x"))["status"] == "HELD"
    request.assert_not_called()
    listing.assert_not_called()
    assert not service.receipts.journal.exists()


@pytest.mark.parametrize("course,module,enabled", [("x", "2", True), ("1", "0", True),
    ("1", "2/other", True), ("1", "2", 1)])
def test_invalid_fixed_configuration_rejected(tmp_path, course, module, enabled):
    with pytest.raises(ValueError):
        publication.ModulePublicationService(tmp_path / "off", course_id=course, module_id=module, enabled=enabled)


@pytest.mark.asyncio
async def test_empty_module_preview_no_journal_or_write_and_confirm_full_readback(case):
    service, state, request, listing = case
    args, preview = await prepared(service)
    assert not service.receipts.journal.exists()
    assert state["put_count"] == 0
    assert preview["course_id"] == "1" and preview["module_id"] == "2"
    assert preview["item_count"] == 0
    assert "client" in preview["approval_requirement"]
    result = await service.confirm(**args, confirmation_token=preview["confirmation_token"])
    assert result["status"] == "VERIFIED_PUBLISHED"
    assert state["put_count"] == 1
    assert listing.await_count == 3  # Preview, fresh confirm and independent readback.
    assert [call.args[0] for call in request.call_args_list] == ["get"] * 4 + ["put", "get", "get"]
    assert (await service.confirm(**args, confirmation_token=preview["confirmation_token"]))["status"] == "HELD"
    assert state["put_count"] == 1


@pytest.mark.asyncio
async def test_already_published_items_and_assignments_preserved_in_full(case):
    service, state, _, _ = case
    with_items(state, [item(), item(5, type="SubHeader", position=2, title="Existing header"),
                       item(6, type="ExternalUrl", position=3, external_url="https://example.invalid/resource")])
    before = copy.deepcopy(state)
    args, preview = await prepared(service)
    assert preview["linked_assignment_ids"] == ["4"]
    result = await service.confirm(**args, confirmation_token=preview["confirmation_token"])
    assert result["status"] == "VERIFIED_PUBLISHED"
    assert state["items"] == before["items"] and state["assignment"] == before["assignment"]
    assert state["parent"] == {**before["parent"], "published": True}


@pytest.mark.asyncio
@pytest.mark.parametrize("changes", [{"published": False}, {"published": 1}, {"published": None},
    {"type": "Quiz"}, {"type": "Page"}, {"type": "ExternalTool"}, {"id": True},
    {"module_id": 9}, {"position": True}, {"position": 2}, {"content_id": "4/other"}])
async def test_draft_unsupported_or_wrong_item_never_gets_token(case, changes):
    service, state, _, _ = case
    with_items(state, [item(**changes)])
    assert (await service.prepare(operation_id="one", purpose="Release"))["status"] == "HELD"
    assert state["put_count"] == 0
    assert not service.receipts.journal.exists()


@pytest.mark.asyncio
@pytest.mark.parametrize("changes", [{"published": False}, {"published": 1}, {"course_id": 9},
    {"id": 5}, {"is_quiz_assignment": True}, {"discussion_topic": {"id": 8}},
    {"submission_types": ["external_tool"]}, {"submission_types": []}])
async def test_nonordinary_draft_or_wrong_assignment_never_gets_token(case, changes):
    service, state, _, _ = case
    with_items(state, [item()])
    state["assignment"].update(changes)
    assert (await service.prepare(operation_id="one", purpose="Release"))["status"] == "HELD"
    assert state["put_count"] == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("mutation", ["parent", "item", "assignment", "order", "draft"])
async def test_changed_preview_burns_token_and_never_sends_even_after_revert(case, mutation):
    service, state, _, _ = case
    with_items(state, [item(), item(5, type="SubHeader", position=2, title="Header")])
    args, preview = await prepared(service)
    before = copy.deepcopy(state)
    if mutation == "parent":
        state["parent"]["name"] = "Teacher edit"
    elif mutation == "item":
        state["items"][0]["indent"] = 1
    elif mutation == "assignment":
        state["assignment"]["description"] = "Teacher edit"
    elif mutation == "order":
        state["items"].reverse()
        for position, entry in enumerate(state["items"], 1):
            entry["position"] = position
    else:
        state["items"][1]["published"] = False
    assert (await service.confirm(**args, confirmation_token=preview["confirmation_token"]))["status"] == "HELD"
    state.update(before)
    assert (await service.confirm(**args, confirmation_token=preview["confirmation_token"]))["status"] == "HELD"
    assert state["put_count"] == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["operation", "purpose", "caller", "expiry", "process"])
async def test_confirmation_bound_to_exact_request_caller_process_and_expiry(case, tmp_path, monkeypatch, change):
    service, state, _, _ = case
    args, preview = await prepared(service)
    if change == "operation":
        args["operation_id"] = "different"
    elif change == "purpose":
        args["purpose"] = "Different publication purpose"
    elif change == "caller":
        monkeypatch.setattr(service.guard, "caller_identity", lambda: "other-caller")
    elif change == "expiry":
        monkeypatch.setattr(service.guard, "_now", lambda: 10**15)
    else:
        service = publication.ModulePublicationService(tmp_path / "fresh", course_id="1", module_id="2", enabled=True)
    assert (await service.confirm(**args, confirmation_token=preview["confirmation_token"]))["status"] == "HELD"
    assert state["put_count"] == 0


@pytest.mark.asyncio
async def test_uncertain_send_durable_across_fresh_token_operation_purpose_and_restart(case):
    service, state, _, _ = case
    args, preview = await prepared(service)
    state["put_error"] = TimeoutError("Synthetic timeout")
    result = await service.confirm(**args, confirmation_token=preview["confirmation_token"])
    assert result["status"] == "UNKNOWN"
    result_path = service.receipts.journal / "publish-one.result.json"
    assert json.loads(result_path.read_text(encoding="utf-8"))["status"] == "UNKNOWN"
    assert state["put_count"] == 1
    service = publication.ModulePublicationService(service.receipts.journal, course_id="1", module_id="2", enabled=True)
    args, preview = await prepared(service, operation_id="replacement", purpose="New words cannot authorize replay")
    assert (await service.confirm(**args, confirmation_token=preview["confirmation_token"]))["status"] == "HELD"
    assert state["put_count"] == 1
    assert json.loads(result_path.read_text(encoding="utf-8"))["status"] == "UNKNOWN"


@pytest.mark.asyncio
@pytest.mark.parametrize("mutation", ["parent", "unknown-parent-field", "item", "assignment", "draft", "count"])
async def test_readback_mismatch_is_unverified_never_corrected_or_retried(case, mutation):
    service, state, _, _ = case
    with_items(state, [item()])
    args, preview = await prepared(service)

    def change(value):
        if mutation == "parent":
            value["parent"]["require_sequential_progress"] = True
        elif mutation == "unknown-parent-field":
            value["parent"]["new_server_setting"] = "Unexpected change"
        elif mutation == "item":
            value["items"][0]["title"] = "Unexpected rewrite"
        elif mutation == "assignment":
            value["assignment"]["points_possible"] = 6
        elif mutation == "draft":
            value["assignment"]["published"] = False
        else:
            value["parent"]["items_count"] = 2

    state["after_put"] = change
    result = await service.confirm(**args, confirmation_token=preview["confirmation_token"])
    assert result["status"] == "UNVERIFIED"
    assert state["put_count"] == 1
    assert (await service.confirm(**args, confirmation_token=preview["confirmation_token"]))["status"] == "HELD"
    assert state["put_count"] == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("response", [{"error": "Synthetic rejection"}, {"id": 9}, {}, None])
async def test_bad_response_unknown_and_no_retry(case, response):
    service, state, _, _ = case
    args, preview = await prepared(service)
    state["put_response"] = response if response is not None else {"id": True}
    assert (await service.confirm(**args, confirmation_token=preview["confirmation_token"]))["status"] == "UNKNOWN"
    assert state["put_count"] == 1


@pytest.mark.asyncio
async def test_receipts_contain_only_bindings_and_metadata_never_content_or_token(case):
    service, state, _, _ = case
    with_items(state, [item()])
    args, preview = await prepared(service)
    assert (await service.confirm(**args, confirmation_token=preview["confirmation_token"]))["status"] == "VERIFIED_PUBLISHED"
    all_receipts = "".join(path.read_text(encoding="utf-8") for path in service.receipts.journal.iterdir())
    for private_value in (state["assignment"]["description"], state["assignment"]["name"],
                          state["parent"]["name"], args["purpose"], preview["confirmation_token"]):
        assert private_value not in all_receipts
    assert (service.receipts.journal / "publish-one.dispatch.result.json").exists()


@pytest.mark.asyncio
@pytest.mark.parametrize("changes", [{"id": 9}, {"id": True}, {"course_id": 9},
    {"published": 0}, {"position": True}, {"items_count": 1}, {"prerequisite_module_ids": [True]},
    {"publish_final_grade": True}, {"publish_final_grade": 0}, {"workflow_state": "deleted"}])
async def test_wrong_or_ambiguous_parent_never_gets_token(case, changes):
    service, state, _, _ = case
    state["parent"].update(changes)
    assert (await service.prepare(operation_id="one", purpose="Release"))["status"] == "HELD"
    assert state["put_count"] == 0


@pytest.mark.asyncio
async def test_duplicate_inventory_and_missing_assignment_protected_field_hold(case):
    service, state, _, _ = case
    with_items(state, [item(), item(position=2)])
    assert (await service.prepare(operation_id="one", purpose="Release"))["status"] == "HELD"
    with_items(state, [item()])
    del state["assignment"]["points_possible"]
    assert (await service.prepare(operation_id="two", purpose="Release"))["status"] == "HELD"
    assert state["put_count"] == 0


@pytest.mark.asyncio
async def test_concurrent_confirmation_has_only_one_dispatch(case):
    import asyncio

    service, state, _, _ = case
    args, preview = await prepared(service)
    results = await asyncio.gather(*[
        service.confirm(**args, confirmation_token=preview["confirmation_token"]) for _ in range(10)])
    assert sum(result["status"] == "VERIFIED_PUBLISHED" for result in results) == 1
    assert state["put_count"] == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("put_status", [200, 429])
async def test_real_client_form_encoding_and_single_transport_attempt(tmp_path, monkeypatch, put_status):
    from canvas_mcp.core import audit, client, config

    state = parent()
    calls = []

    def transport(request):
        calls.append(request)
        assert request.url.host == "example.invalid"
        if request.method == "PUT":
            assert request.url.path == "/api/v1/courses/1/modules/2"
            assert request.headers["Content-Type"] == "application/x-www-form-urlencoded"
            assert parse_qs(request.content.decode()) == {
                "module[published]": ["true"], "module[skip_content_tags]": ["true"]}
            if put_status == 429:
                return httpx.Response(429, json={"error": "Synthetic rate limit"})
            state["published"] = True
            return httpx.Response(200, json=state)
        assert request.method == "GET"
        if request.url.path == "/api/v1/courses/1/modules/2/items":
            return httpx.Response(200, json=[])
        assert request.url.path == "/api/v1/courses/1/modules/2"
        return httpx.Response(200, json=state)

    synthetic_config = SimpleNamespace(canvas_api_url="https://example.invalid/api/v1",
                                       max_concurrent_requests=2, log_api_requests=False,
                                       enable_data_anonymization=False)
    monkeypatch.setattr(config, "get_config", lambda: synthetic_config)
    monkeypatch.setattr(client, "get_request_credentials", lambda: None)
    monkeypatch.setattr(audit, "log_data_access", lambda *args: None)
    async with httpx.AsyncClient(transport=httpx.MockTransport(transport)) as http:
        monkeypatch.setattr(client, "_get_http_client", lambda: http)
        service = publication.ModulePublicationService(tmp_path / "journal", course_id="1", module_id="2", enabled=True)
        args, preview = await prepared(service)
        result = await service.confirm(**args, confirmation_token=preview["confirmation_token"])
    assert result["status"] == ("VERIFIED_PUBLISHED" if put_status == 200 else "UNKNOWN")
    assert sum(request.method == "PUT" for request in calls) == 1
    assert not any(request.method in {"POST", "DELETE"} for request in calls)
