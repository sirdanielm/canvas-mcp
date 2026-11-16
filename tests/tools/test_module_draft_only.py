"""Synthetic request-boundary tests; never contacts Canvas."""
from unittest.mock import AsyncMock, patch

import pytest
from fastmcp import Client, FastMCP
from fastmcp.exceptions import ToolError

from canvas_mcp.core.tool_policy import apply_tool_policy, resolve_tool_policy
from canvas_mcp.tools.modules import register_draft_module_tools


@pytest.fixture
def server():
    mcp = FastMCP('synthetic-draft-test')
    register_draft_module_tools(mcp)
    return mcp


@pytest.mark.asyncio
@pytest.mark.parametrize('tool,args', [
    ('create_module', {'course_identifier': '1', 'name': 'Bonding'}),
    ('add_module_item', {'course_identifier': '1', 'module_id': '2', 'item_type': 'ExternalUrl', 'title': 'Slides', 'external_url': 'https://example.org/a'}),
])
@pytest.mark.parametrize('value', [True, 'true', 'false', 0, 1, None, [], {}])
async def test_rejects_true_and_malformed_before_any_request(server, tool, args, value):
    with patch('canvas_mcp.tools.modules.get_course_id', new_callable=AsyncMock) as lookup, patch('canvas_mcp.tools.modules.make_canvas_request', new_callable=AsyncMock) as request:
        async with Client(server) as client:
            try:
                result = await client.call_tool(tool, {**args, 'published': value})
                assert result.is_error or 'Error' in str(result.content)
            except ToolError:
                pass  # MCP rejects invalid strict booleans before invocation.
        lookup.assert_not_awaited()
        request.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize('tool,args,key', [
    ('create_module', {'course_identifier': '1', 'name': 'Bonding'}, 'module[published]'),
    ('add_module_item', {'course_identifier': '1', 'module_id': '2', 'item_type': 'ExternalUrl', 'title': 'Slides', 'external_url': 'https://example.org/a'}, 'module_item[published]'),
])
@pytest.mark.parametrize('explicit', [False, True])
async def test_false_and_omitted_send_false(server, tool, args, key, explicit):
    with patch('canvas_mcp.tools.modules.get_course_id', new_callable=AsyncMock, return_value='1'), patch('canvas_mcp.tools.modules.get_course_code', new_callable=AsyncMock, return_value='course'), patch('canvas_mcp.tools.modules.make_canvas_request', new_callable=AsyncMock, return_value={'id': 3, 'published': False}) as request:
        async with Client(server) as client:
            await client.call_tool(tool, {**args, **({'published': False} if explicit else {})})
        request.assert_awaited_once()
        assert dict(request.await_args.kwargs['data'])[key] == 'false'
        assert request.await_args.args[0] == 'post'


@pytest.mark.asyncio
async def test_linked_assignment_is_rejected_without_read_or_write(server):
    with patch('canvas_mcp.tools.modules.get_course_id', new_callable=AsyncMock) as lookup, patch('canvas_mcp.tools.modules.make_canvas_request', new_callable=AsyncMock) as request:
        async with Client(server) as client:
            result = await client.call_tool('add_module_item', {'course_identifier': '1', 'module_id': '2', 'item_type': 'Assignment', 'content_id': '99', 'published': False})
        assert 'ExternalUrl only' in str(result.content)
        lookup.assert_not_awaited()
        request.assert_not_awaited()


@pytest.mark.asyncio
async def test_policy_exposes_no_other_writers(server):
    async with Client(server) as client:
        assert {x.name for x in await client.list_tools()} == {'create_module', 'add_module_item'}
    await apply_tool_policy(server, resolve_tool_policy('create_module,add_module_item', 'stdio'))
    async with Client(server) as client:
        assert {x.name for x in await client.list_tools()} == {'create_module', 'add_module_item'}


@pytest.mark.asyncio
async def test_unknown_publication_key_rejected(server):
    with patch('canvas_mcp.tools.modules.get_course_id', new_callable=AsyncMock) as lookup, patch('canvas_mcp.tools.modules.make_canvas_request', new_callable=AsyncMock) as request:
        async with Client(server) as client:
            try:
                result = await client.call_tool('create_module', {'course_identifier': '1', 'name': 'Bonding', 'publish': True})
                assert result.is_error or 'Error' in str(result.content)
            except ToolError:
                pass
        lookup.assert_not_awaited()
        request.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize('value,expected', [('false', 'false'), (0, 'false'), ('true', 'true'), (1, 'true')])
async def test_normal_profile_preserves_legacy_boolean_coercion(value, expected):
    from canvas_mcp.tools.modules import register_educator_module_tools

    normal = FastMCP('synthetic-normal-test')
    register_educator_module_tools(normal)
    with patch('canvas_mcp.tools.modules.get_course_id', new_callable=AsyncMock, return_value='1'), patch('canvas_mcp.tools.modules.get_course_code', new_callable=AsyncMock, return_value='course'), patch('canvas_mcp.tools.modules.make_canvas_request', new_callable=AsyncMock, return_value={'id': 3, 'published': False}) as request:
        async with Client(normal) as client:
            await client.call_tool('create_module', {'course_identifier': '1', 'name': 'Bonding', 'published': value})
        assert dict(request.await_args.kwargs['data'])['module[published]'] == expected


@pytest.mark.asyncio
@pytest.mark.parametrize('response, expected', [
    ({'error': 'timeout'}, 'UNKNOWN'),
    ({'published': False}, 'UNVERIFIED'),
    ({'id': 3}, 'UNVERIFIED'),
    ({'id': 3, 'published': True}, 'UNVERIFIED'),
    ({'id': 3, 'published': False}, 'UNVERIFIED'),
])
@pytest.mark.parametrize('tool,args', [
    ('create_module', {'course_identifier': '1', 'name': 'Bonding'}),
    ('add_module_item', {'course_identifier': '1', 'module_id': '2', 'item_type': 'ExternalUrl', 'title': 'Slides', 'external_url': 'https://example.org/a'}),
])
async def test_single_attempt_and_explicit_unverified_outcomes(server, tool, args, response, expected):
    with patch('canvas_mcp.tools.modules.get_course_id', new_callable=AsyncMock, return_value='1'), patch('canvas_mcp.tools.modules.make_canvas_request', new_callable=AsyncMock, return_value=response) as request:
        async with Client(server) as client:
            result = await client.call_tool(tool, args)
        assert expected in str(result.content)
        request.assert_awaited_once()
        assert request.await_args.kwargs['retry_rate_limits'] is False
