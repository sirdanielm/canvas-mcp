"""Actual registry/startup tests with fake credentials and no Canvas traffic."""
from unittest.mock import AsyncMock, patch

import pytest
from fastmcp import Client, FastMCP
from fastmcp.exceptions import ToolError

import canvas_mcp.server as server
from canvas_mcp.core.tool_policy import TOOL_EFFECTS, Effect, apply_tool_policy
from canvas_mcp.tools.module_authoring import READERS, WRITERS, ModuleAuthoring


@pytest.mark.asyncio
@pytest.mark.parametrize("publication", [False, True])
@pytest.mark.parametrize("policy", [None, "", "none", "all", "update_assignment", "add_draft_module_item,edit_draft_module_item"])
async def test_registry_has_exact_writer_ceiling(tmp_path, publication, policy):
    service = ModuleAuthoring(courses=frozenset({"123"}), journal=tmp_path,
                              publication_enabled=publication)
    mcp = FastMCP("fixture")
    server.register_all_tools(mcp, role="educator", module_authoring=service)
    await apply_tool_policy(mcp, server._resolve_module_policy(policy, publication_enabled=publication))
    async with Client(mcp) as client:
        names = {t.name for t in await client.list_tools()}
        status = await client.call_tool("module_authoring_status", {})
        assert "module-authoring-only" in str(status)
    expected = {"add_draft_module_item", "edit_draft_module_item"} if policy and policy.startswith("add_draft") else set()
    assert {n for n in names if TOOL_EFFECTS[n] != Effect.READ} == expected
    assert names <= READERS | WRITERS
    assert ("prepare_module_publication" in names) is publication


@pytest.mark.asyncio
async def test_explicit_publish_flag_and_policy_both_required(tmp_path):
    service = ModuleAuthoring(courses=frozenset({"123"}), journal=tmp_path)
    mcp = FastMCP("fixture")
    server.register_all_tools(mcp, role="educator", module_authoring=service)
    await apply_tool_policy(mcp, server._resolve_module_policy("confirm_module_publication"))
    async with Client(mcp) as client:
        assert "confirm_module_publication" not in {t.name for t in await client.list_tools()}
        with pytest.raises(ToolError, match="Unknown tool"):
            await client.call_tool("confirm_module_publication", {})


@pytest.mark.asyncio
async def test_wrong_course_rejected_before_any_read_or_write(tmp_path):
    service = ModuleAuthoring(courses=frozenset({"123"}), journal=tmp_path,
                              publication_enabled=True)
    mcp = FastMCP("fixture")
    server.register_all_tools(mcp, role="educator", module_authoring=service)
    with patch("canvas_mcp.tools.module_authoring.make_canvas_request", new_callable=AsyncMock) as request:
        async with Client(mcp) as client:
            result = await client.call_tool("inspect_module_authoring", {"course_id": "999", "module_id": "2"}, raise_on_error=False)
            assert result.is_error and "HELD" in str(result)
            result = await client.call_tool("prepare_module_publication", {
                "course_id": "999", "module_id": "2", "operation_id": "fixture", "purpose": "fixture"}, raise_on_error=False)
            assert result.is_error and "HELD" in str(result)
        request.assert_not_awaited()


@pytest.mark.asyncio
async def test_boolean_coercion_rejected_at_actual_mcp_boundary(tmp_path):
    service = ModuleAuthoring(courses=frozenset({"123"}), journal=tmp_path)
    mcp = FastMCP("fixture")
    server.register_all_tools(mcp, role="educator", module_authoring=service)
    with patch.object(service.items, "execute", new_callable=AsyncMock) as execute:
        async with Client(mcp) as client:
            for bad in ("true", 1, "false", 0):
                with pytest.raises(ToolError):
                    await client.call_tool("add_draft_module_item", {
                        "operation_id": "fixture", "course_id": "123", "module_id": "2",
                        "item_type": "SubHeader", "position": 1, "title": "Fixture",
                        "expected_items": [], "expected_parent_sha256": "a" * 64,
                        "expected_parent_published": bad})
        execute.assert_not_awaited()


@pytest.mark.parametrize("flag", [False, True])
def test_actual_main_wires_profile_without_live_io(monkeypatch, tmp_path, flag):
    import asyncio
    import sys
    from types import SimpleNamespace

    import canvas_mcp.core.audit as audit

    config = SimpleNamespace(canvas_api_url="https://example.invalid/api/v1", institution_name="",
        canvas_role="educator", allowed_write_tools="add_draft_module_item,edit_draft_module_item" +
        (",confirm_module_publication" if flag else ""), mcp_server_name="fixture")
    argv = ["canvas-mcp-server", "--role", "educator", "--module-authoring-only",
            "--module-authoring-courses", "123", "--module-authoring-journal", str(tmp_path)]
    if flag:
        argv.append("--enable-module-publication")
    monkeypatch.setattr(sys, "argv", argv)
    monkeypatch.setattr(server, "get_config", lambda: config)
    monkeypatch.setattr(server, "validate_config", lambda: True)
    token = AsyncMock(return_value=(True, "fixture"))
    monkeypatch.setattr(server, "_validate_token", token)
    monkeypatch.setattr(audit, "init_audit_logging", lambda: None)
    observed = set()

    def capture(mcp):
        async def names():
            return {t.name for t in await mcp.list_tools(run_middleware=False)}
        observed.update(asyncio.run(names()))

    monkeypatch.setattr(FastMCP, "run", capture)
    server.main()
    assert observed == (READERS | WRITERS if flag else (READERS | WRITERS) - {
        "prepare_module_publication", "confirm_module_publication"})
    token.assert_awaited_once()


@pytest.mark.parametrize("courses", [frozenset(), frozenset({"abc"}), frozenset({"0"}), frozenset({"123", "../2"})])
def test_invalid_operator_course_scope(tmp_path, courses):
    with pytest.raises(ValueError):
        ModuleAuthoring(courses=courses, journal=tmp_path)
