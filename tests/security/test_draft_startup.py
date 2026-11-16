"""Isolated startup registry checks; no Canvas credentials or calls."""
from unittest.mock import AsyncMock, patch

import pytest
from fastmcp import Client, FastMCP
from fastmcp.exceptions import ToolError

import canvas_mcp.server as server
from canvas_mcp.core.tool_policy import (
    TOOL_EFFECTS,
    Effect,
    ToolPolicyError,
    apply_tool_policy,
    resolve_tool_policy,
)


@pytest.mark.asyncio
@pytest.mark.parametrize('policy', ['create_module,add_module_item'])
async def test_draft_startup_has_hard_writer_ceiling(policy):
    mcp = FastMCP('synthetic-startup')
    server.register_all_tools(mcp, role='all', draft_modules_only=True)
    await server._assert_draft_registry(mcp)
    await apply_tool_policy(mcp, server._resolve_draft_policy(policy, 'stdio'))
    async with Client(mcp) as client:
        names = {x.name for x in await client.list_tools()}
    assert {'list_modules', 'list_module_items', 'create_module', 'add_module_item'} <= names
    assert {n for n in names if TOOL_EFFECTS[n] != Effect.READ} == {'create_module', 'add_module_item'}


@pytest.mark.asyncio
async def test_read_only_policy_removes_and_denies_writers():
    mcp = FastMCP('synthetic-readonly')
    server.register_all_tools(mcp, role='educator', draft_modules_only=True)
    await server._assert_draft_registry(mcp)
    await apply_tool_policy(mcp, resolve_tool_policy('none', 'stdio'))
    async with Client(mcp) as client:
        assert 'create_module' not in {x.name for x in await client.list_tools()}
        with patch('canvas_mcp.tools.modules.make_canvas_request', new_callable=AsyncMock) as request:
            with pytest.raises(ToolError, match='Unknown tool'):
                await client.call_tool('create_module', {'course_identifier': '1', 'name': 'Bonding'})
            request.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize('name', ['unknown_new_tool', 'update_assignment'])
async def test_unexpected_writer_or_unknown_aborts_registry(name):
    mcp = FastMCP('synthetic-extra')
    server.register_all_tools(mcp, draft_modules_only=True)

    async def extra():
        return 'never called'

    mcp.tool(name=name)(extra)
    with pytest.raises(RuntimeError, match='Unsafe draft module registry'):
        await server._assert_draft_registry(mcp)


def test_malformed_allowlist_remains_denied():
    with pytest.raises(ToolPolicyError):
        resolve_tool_policy('none,create_module', 'stdio')


@pytest.mark.parametrize('policy, expected_writers', [(None, set()), ('', set()), ('none', set()), ('all', set()), ('create_module', set()), ('create_module,add_module_item', {'create_module', 'add_module_item'})])
def test_actual_main_cli_wires_guarded_registry_without_live_io(monkeypatch, policy, expected_writers):
    import asyncio
    import sys
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    import canvas_mcp.core.audit as audit

    config = SimpleNamespace(canvas_api_url='https://example.invalid/api/v1', institution_name='',
                             canvas_role='educator', allowed_write_tools=policy, mcp_server_name='mock')
    monkeypatch.setattr(sys, 'argv', ['canvas-mcp-server', '--draft-modules-only'])
    monkeypatch.setattr(server, 'get_config', lambda: config)
    monkeypatch.setattr(server, 'validate_config', lambda: True)
    monkeypatch.setattr(server, '_validate_token', AsyncMock(return_value=(True, 'synthetic')))
    monkeypatch.setattr(audit, 'init_audit_logging', lambda: None)
    observed = set()

    def capture_run(mcp):
        async def names():
            return {t.name for t in await mcp.list_tools(run_middleware=False)}
        observed.update(asyncio.run(names()))

    monkeypatch.setattr(FastMCP, 'run', capture_run)
    server.main()
    assert {name for name in observed if TOOL_EFFECTS[name] != Effect.READ} == expected_writers


def test_typoed_draft_cli_flag_never_falls_back(monkeypatch):
    import sys

    monkeypatch.setattr(sys, 'argv', ['canvas-mcp-server', '--draft-modules-onli'])
    with pytest.raises(SystemExit):
        server.main()


@pytest.mark.parametrize('role', ['student', 'all', 'typo'])
def test_draft_main_rejects_wrong_or_invalid_role(monkeypatch, role):
    import sys
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    import canvas_mcp.core.audit as audit

    config = SimpleNamespace(canvas_api_url='https://example.invalid/api/v1', institution_name='',
                             canvas_role=role, allowed_write_tools='all', mcp_server_name='mock')
    monkeypatch.setattr(sys, 'argv', ['canvas-mcp-server', '--draft-modules-only'])
    monkeypatch.setattr(server, 'get_config', lambda: config)
    monkeypatch.setattr(server, 'validate_config', lambda: True)
    monkeypatch.setattr(server, '_validate_token', AsyncMock(return_value=(True, 'synthetic')))
    monkeypatch.setattr(audit, 'init_audit_logging', lambda: None)
    with pytest.raises(RuntimeError, match='role'):
        server.main()


@pytest.mark.asyncio
@pytest.mark.parametrize('tool,args', [
    ('create_module', {'course_identifier': '1', 'name': 'Bonding'}),
    ('add_module_item', {'course_identifier': '1', 'module_id': '2', 'item_type': 'ExternalUrl', 'title': 'Slides', 'external_url': 'https://example.org/a'}),
])
@pytest.mark.parametrize('response,label', [({'error': 'timeout'}, 'UNKNOWN'), ({'id': 3, 'published': False}, 'UNVERIFIED')])
async def test_startup_wire_marks_uncertain_writes_as_errors(tool, args, response, label):
    mcp = FastMCP('synthetic-startup-wire')
    server.register_all_tools(mcp, role='educator', draft_modules_only=True)
    await server._assert_draft_registry(mcp)
    with patch('canvas_mcp.tools.modules.get_course_id', new_callable=AsyncMock, return_value='1'), patch('canvas_mcp.tools.modules.make_canvas_request', new_callable=AsyncMock, return_value=response):
        async with Client(mcp) as client:
            result = await client.call_tool(tool, args, raise_on_error=False)
        assert result.is_error
        assert label in str(result.content)
