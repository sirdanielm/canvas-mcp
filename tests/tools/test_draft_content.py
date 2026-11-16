"""Isolated prepared-profile contract; no live connections."""
import hashlib
import json
from unittest.mock import AsyncMock

import pytest
from fastmcp import Client, FastMCP
from fastmcp.exceptions import ToolError

from canvas_mcp.core.tool_policy import apply_tool_policy, resolve_tool_policy
from canvas_mcp.tools import draft_content as draft
from canvas_mcp.tools.draft_assignments import private_storage_supported


@pytest.fixture
def prepared(tmp_path, monkeypatch):
    path = tmp_path / "manifest.json"
    value = {"schema_version": 1, "assignments": {"lesson": {"operation_id": "lesson1", "course_id": "1",
        "content": {"name": "New", "description": "Body", "submission_type": "on_paper", "points_possible": 10, "assignment_group_id": "2", "due_at": None}, "published": False, "existing_assignment_ids": ["2"]}}}
    path.write_text(json.dumps(value), encoding="utf-8")
    path.chmod(0o600)
    obj = draft.PreparedAssignments(path, hashlib.sha256(path.read_bytes()).hexdigest(), tmp_path / "journal")
    listing = AsyncMock(return_value=[{"id": 2, "course_id": 1, "name": "Other"}])
    monkeypatch.setattr(draft, "fetch_all_paginated_results", listing)
    obj.service.execute = AsyncMock(return_value={"status": "VERIFIED_DRAFT"})
    return obj, listing


@pytest.mark.asyncio
@pytest.mark.skipif(not private_storage_supported(), reason="Requires POSIX private storage")
async def test_inspection_is_nonmutating(prepared):
    obj, _ = prepared
    assert (await obj.inspect("lesson"))["status"] == "REVIEW"
    assert not obj.service.journal.exists()
    obj.service.execute.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("items", [{"error": "pagination failed"}, [{"id": 2, "course_id": 3}],
    [{"id": 2, "course_id": 1, "name": "New"}], [],
    [{"id": 2, "course_id": 1}, {"id": 3, "course_id": 1}]])
@pytest.mark.skipif(not private_storage_supported(), reason="Requires POSIX private storage")
async def test_reconciliation_holds(prepared, items):
    obj, listing = prepared
    listing.return_value = items
    assert (await obj.apply("lesson"))["status"] == "HELD"
    obj.service.execute.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.skipif(not private_storage_supported(), reason="Requires POSIX private storage")
async def test_apply_only_pinned_entry(prepared):
    obj, _ = prepared
    assert (await obj.apply("lesson"))["status"] == "VERIFIED_DRAFT"
    obj.service.execute.assert_awaited_once_with(operation_id="lesson1", course_id="1",
        content={"name": "New", "description": "Body", "submission_type": "on_paper", "points_possible": 10, "assignment_group_id": "2", "due_at": None}, published=False)
    obj.manifest.write_text("{}", encoding="utf-8")
    assert (await obj.apply("lesson"))["status"] == "HELD"
    assert obj.service.execute.call_count == 1


@pytest.mark.asyncio
@pytest.mark.skipif(not private_storage_supported(), reason="Requires POSIX private storage")
async def test_registry_and_denied_policy(prepared):
    obj, _ = prepared
    mcp = FastMCP("synthetic")
    draft.register_draft_content_tools(mcp, obj)
    async with Client(mcp) as client:
        assert {x.name for x in await client.list_tools()} == {draft.READER, draft.WRITER, draft.MODULE_WRITER}
    await apply_tool_policy(mcp, resolve_tool_policy("none", "stdio"))
    async with Client(mcp) as client:
        assert {x.name for x in await client.list_tools()} == {draft.READER}
        result = await client.call_tool(draft.READER, {"key": "lesson"})
        assert not result.is_error


@pytest.mark.asyncio
@pytest.mark.skipif(not private_storage_supported(), reason="Requires POSIX private storage")
async def test_unknown_input_cannot_replace_manifest(prepared):
    obj, _ = prepared
    mcp = FastMCP("synthetic")
    draft.register_draft_content_tools(mcp, obj)
    async with Client(mcp) as client:
        with pytest.raises(ToolError):
            await client.call_tool(draft.WRITER, {"key": "lesson", "published": True})
    obj.service.execute.assert_not_called()


@pytest.mark.parametrize("policy,writers", [(None, set()), ("none", set()), ("all", set()),
    ("create_module,add_module_item", set()), (draft.WRITER, {draft.WRITER}), (draft.MODULE_WRITER, {draft.MODULE_WRITER}),
    (draft.WRITER + "," + draft.MODULE_WRITER, {draft.WRITER, draft.MODULE_WRITER})])
@pytest.mark.skipif(not private_storage_supported(), reason="Requires POSIX private storage")
def test_cli_exact_policy_and_isolated_registry(prepared, monkeypatch, policy, writers):
    import asyncio
    import sys
    from types import SimpleNamespace

    import canvas_mcp.core.audit as audit
    import canvas_mcp.server as server
    obj, _ = prepared
    config = SimpleNamespace(canvas_api_url="https://example.invalid/api/v1", institution_name="",
        canvas_role="educator", allowed_write_tools=policy, mcp_server_name="synthetic")
    monkeypatch.setattr(sys, "argv", ["canvas-mcp-server", "--draft-content-only",
        "--draft-content-manifest", str(obj.manifest), "--draft-content-sha256", obj.expected_sha256,
        "--draft-content-journal", str(obj.service.journal)])
    monkeypatch.setattr(server, "get_config", lambda: config)
    monkeypatch.setattr(server, "validate_config", lambda: True)
    monkeypatch.setattr(server, "_validate_token", AsyncMock(return_value=(True, "synthetic")))
    monkeypatch.setattr(audit, "init_audit_logging", lambda: None)
    observed = set()

    def capture(mcp):
        async def names():
            return {t.name for t in await mcp.list_tools(run_middleware=False)}
        observed.update(asyncio.run(names()))

    monkeypatch.setattr(FastMCP, "run", capture)
    server.main()
    assert observed == {draft.READER} | writers
    assert not obj.service.journal.exists()


@pytest.mark.asyncio
@pytest.mark.skipif(not private_storage_supported(), reason="Requires POSIX private storage")
async def test_module_only_manifest_needs_no_dummy_assignment(tmp_path):
    path = tmp_path / "modules.json"
    value = {"schema_version": 1, "assignments": {}, "module_items": {"test": {
        "operation_id": "test", "course_id": "1", "module_id": "2", "item_type": "SubHeader",
        "title": "Test date", "position": 1, "existing_item_ids": [], "published": False}}}
    path.write_text(json.dumps(value), encoding="utf-8")
    path.chmod(0o600)
    obj = draft.PreparedAssignments(path, hashlib.sha256(path.read_bytes()).hexdigest(), tmp_path / "journal")
    obj.module_items.execute = AsyncMock(return_value={"status": "VERIFIED_DRAFT"})
    mcp = FastMCP("synthetic-module-only")
    draft.register_draft_content_tools(mcp, obj)
    await apply_tool_policy(mcp, resolve_tool_policy(draft.MODULE_WRITER, "stdio"))
    async with Client(mcp) as client:
        assert {x.name for x in await client.list_tools()} == {draft.READER, draft.MODULE_WRITER}
        assert not (await client.call_tool(draft.MODULE_WRITER, {"key": "test"})).is_error
    obj.module_items.execute.assert_awaited_once_with(**value["module_items"]["test"])
