"""Cross-platform fail-closed policy; executes on Windows as well as POSIX."""
import os
import sys
from unittest.mock import AsyncMock

import pytest
from fastmcp import FastMCP

from canvas_mcp.tools import draft_assignments as assignments
from canvas_mcp.tools import draft_content as content
from canvas_mcp.tools import draft_module_items as modules


@pytest.fixture(params=["missing_getuid", "windows"])
def unsupported(request, monkeypatch, tmp_path):
    if request.param == "missing_getuid":
        monkeypatch.delattr(os, "getuid", raising=False)
    else:
        monkeypatch.setattr(sys, "platform", "win32")


def test_manifest_fails_before_read_and_claim_before_mkdir(unsupported, tmp_path):
    manifest = tmp_path / "does-not-exist.json"
    journal = tmp_path / "journal"
    with pytest.raises(ValueError, match="requires POSIX"):
        content.PreparedAssignments(manifest, "0" * 64, journal)
    with pytest.raises(ValueError, match="requires POSIX"):
        assignments.DraftAssignmentService(journal)._claim("one", {})
    assert not journal.exists()


@pytest.mark.asyncio
async def test_services_hold_without_network_or_storage(unsupported, tmp_path, monkeypatch):
    network = AsyncMock(side_effect=AssertionError("Network must not be called"))
    for module in (assignments, modules, content):
        monkeypatch.setattr(module, "make_canvas_request", network)
        monkeypatch.setattr(module, "fetch_all_paginated_results", network)
    journal = tmp_path / "journal"
    result = await assignments.DraftAssignmentService(journal).execute(
        operation_id="one", course_id="1", content={"name": "Draft"})
    item = await modules.DraftModuleItems(journal).execute(
        operation_id="two", course_id="1", module_id="2", item_type="SubHeader",
        position=1, existing_item_ids=[], title="Header")
    for value in (result, item):
        assert value["status"] == "HELD"
        assert "requires POSIX" in value["reason"]
    network.assert_not_called()
    assert not journal.exists()


@pytest.mark.asyncio
async def test_legacy_registries_still_register(unsupported):
    from canvas_mcp.core.tool_policy import apply_tool_policy, resolve_tool_policy
    from canvas_mcp.server import register_all_tools

    for module_only in (False, True):
        mcp = FastMCP("synthetic")
        register_all_tools(mcp, role="educator", draft_modules_only=module_only)
        await apply_tool_policy(mcp, resolve_tool_policy("none", "stdio"))
        names = {tool.name for tool in await mcp.list_tools()}
        assert "list_modules" in names
        assert content.WRITER not in names
        assert content.MODULE_WRITER not in names
