"""Owned-container lifecycle tests with no Docker/Podman daemon calls."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastmcp import FastMCP

from canvas_mcp.core.config import reset_config
from canvas_mcp.tools import code_execution


@pytest.fixture
def container_tool(monkeypatch):
    monkeypatch.setenv('CANVAS_API_TOKEN', 'fixture-token')
    monkeypatch.setenv('CANVAS_API_URL', 'https://canvas.invalid/api/v1')
    monkeypatch.setenv('ENABLE_TS_SANDBOX', 'true')
    monkeypatch.setenv('TS_SANDBOX_MODE', 'container')
    monkeypatch.setenv('EXECUTE_TYPESCRIPT_ENABLED', 'true')
    reset_config()
    captured = {}
    mcp = FastMCP('owned-container-test')

    def tool(*args, **kwargs):
        def capture(fn):
            captured[fn.__name__] = fn
            return fn
        return capture

    with patch.object(mcp, 'tool', tool):
        code_execution.register_code_execution_tools(mcp)
    monkeypatch.setattr(code_execution, '_detect_container_runtime', lambda: 'docker')
    monkeypatch.setattr(code_execution, '_runtime_available', AsyncMock(return_value=True))
    monkeypatch.setattr(code_execution, 'is_http_request_active', lambda: False)
    monkeypatch.setattr(code_execution, 'get_request_credentials', lambda: None)
    monkeypatch.setattr(code_execution.asyncio, 'create_subprocess_exec', AsyncMock(return_value=MagicMock(returncode=0)))
    yield captured['execute_typescript']
    reset_config()


@pytest.mark.asyncio
@pytest.mark.parametrize('reason', ['timeout', 'output_limit'])
async def test_resource_failure_cleans_exact_owned_container(container_tool, monkeypatch, reason):
    cleanup = AsyncMock(return_value=True)
    monkeypatch.setattr(code_execution, '_cleanup_owned_container', cleanup, raising=False)
    monkeypatch.setattr(
        code_execution, '_collect_process_output',
        AsyncMock(side_effect=code_execution._ProcessOutputError(reason, code_execution._CapturedOutput(b'', b''))),
    )
    result = await container_tool(code='// fixture')
    cleanup.assert_awaited_once()
    owned = cleanup.await_args.args[0]
    assert owned.runtime == 'docker'
    assert owned.name == 'canvas-mcp-' + owned.nonce
    assert len(owned.nonce) == 32
    assert 'Do not automatically retry' in result


@pytest.mark.asyncio
async def test_cancellation_cleans_owned_container_before_propagating(container_tool, monkeypatch):
    cleanup = AsyncMock(return_value=True)
    monkeypatch.setattr(code_execution, '_cleanup_owned_container', cleanup, raising=False)
    monkeypatch.setattr(code_execution, '_collect_process_output', AsyncMock(side_effect=asyncio.CancelledError))
    with pytest.raises(asyncio.CancelledError):
        await container_tool(code='// fixture')
    cleanup.assert_awaited_once()


CONTAINER_ID = 'a' * 64
NONCE = '1' * 32


@pytest.fixture
def scripted_engine(monkeypatch):
    """Real asyncio readers around a deterministic, daemon-free engine double."""
    calls = []
    responses = []
    monkeypatch.setenv('CANVAS_API_TOKEN', 'fixture-secret-never-forwarded')
    monkeypatch.setenv('NODE_OPTIONS', '--require=fixture-never-forwarded')

    async def spawn(*args, **kwargs):
        calls.append(args)
        assert 'CANVAS_API_TOKEN' not in kwargs['env']
        assert 'CANVAS_API_URL' not in kwargs['env']
        assert 'NODE_OPTIONS' not in kwargs['env']
        assert kwargs['limit'] == 16384
        code, output = responses.pop(0)
        stdout, stderr = asyncio.StreamReader(), asyncio.StreamReader()
        stdout.feed_data(output)
        stdout.feed_eof()
        stderr.feed_eof()
        return MagicMock(
            stdout=stdout, stderr=stderr, stdin=None,
            wait=AsyncMock(return_value=code), returncode=code,
        )

    monkeypatch.setattr(code_execution.asyncio, 'create_subprocess_exec', spawn)
    return responses, calls


def owned():
    return code_execution._OwnedContainer('docker', 'canvas-mcp-' + NONCE, NONCE)


@pytest.mark.asyncio
@pytest.mark.parametrize('remove_code', [0, 1])
async def test_cleanup_targets_only_verified_immutable_id_and_reads_back_absence(scripted_engine, remove_code):
    responses, calls = scripted_engine
    responses.extend([(0, f'{CONTAINER_ID} {NONCE}\n'.encode()), (remove_code, b''), (0, b'')])
    assert await code_execution._cleanup_owned_container(owned()) is True
    assert calls[0][-1] == 'canvas-mcp-' + NONCE
    assert '.Config.Labels' in calls[0][-2]
    assert calls[1] == ('docker', 'rm', '--force', CONTAINER_ID)
    assert calls[2] == ('docker', 'ps', '--all', '--quiet', '--no-trunc', '--filter', 'id=' + CONTAINER_ID)


@pytest.mark.asyncio
@pytest.mark.parametrize('identity', [
    f'{CONTAINER_ID} {"2" * 32}\n'.encode(),
    f'not-an-immutable-id {NONCE}\n'.encode(),
    f'{CONTAINER_ID} {NONCE}\n{"b" * 64} {NONCE}\n'.encode(),
])
async def test_cleanup_never_removes_unknown_owner_or_malformed_id(scripted_engine, identity):
    responses, calls = scripted_engine
    responses.append((0, identity))
    assert await code_execution._cleanup_owned_container(owned()) is False
    assert len(calls) == 1
    assert all('rm' not in call for call in calls)


@pytest.mark.asyncio
async def test_late_daemon_create_is_reconciled_by_bounded_reads(scripted_engine):
    responses, calls = scripted_engine
    responses.extend([(1, b''), (0, f'{CONTAINER_ID} {NONCE}\n'.encode()), (0, b''), (0, b'')])
    assert await code_execution._cleanup_owned_container(owned()) is True
    assert [call[1] for call in calls] == ['inspect', 'inspect', 'rm', 'ps']


@pytest.mark.asyncio
async def test_not_found_during_creation_race_remains_unknown(scripted_engine):
    responses, calls = scripted_engine
    responses.extend([(1, b'')] * 3)
    assert await code_execution._cleanup_owned_container(owned()) is False
    assert len(calls) == 3
    assert all(call[1] == 'inspect' for call in calls)


@pytest.mark.asyncio
@pytest.mark.parametrize('readback', [(0, (CONTAINER_ID + '\n').encode()), (1, b'')])
async def test_successful_rm_without_absence_readback_remains_unknown(scripted_engine, readback):
    responses, _calls = scripted_engine
    responses.extend([(0, f'{CONTAINER_ID} {NONCE}\n'.encode()), (0, b''), readback])
    assert await code_execution._cleanup_owned_container(owned()) is False


@pytest.mark.asyncio
@pytest.mark.parametrize('failure', ['timeout', 'output_limit', 'startup', 'nonzero_exit'])
async def test_failed_or_unavailable_cleanup_is_held_and_not_retried(container_tool, monkeypatch, failure):
    cleanup = AsyncMock(return_value=False)
    monkeypatch.setattr(code_execution, '_cleanup_owned_container', cleanup)
    if failure == 'startup':
        monkeypatch.setattr(code_execution.asyncio, 'create_subprocess_exec', AsyncMock(side_effect=OSError('fixture engine startup error')))
    elif failure == 'nonzero_exit':
        monkeypatch.setattr(code_execution.asyncio, 'create_subprocess_exec', AsyncMock(return_value=MagicMock(returncode=1)))
        monkeypatch.setattr(code_execution, '_collect_process_output', AsyncMock(return_value=code_execution._CapturedOutput(b'', b'fixture error')))
    else:
        monkeypatch.setattr(code_execution, '_collect_process_output', AsyncMock(side_effect=code_execution._ProcessOutputError(failure, code_execution._CapturedOutput(b'', b''))))
    result = await container_tool(code='// fixture')
    assert 'cleanup HELD/UNKNOWN' in result
    assert 'Do not automatically retry' in result
    cleanup.assert_awaited_once()


@pytest.mark.asyncio
async def test_second_cancellation_cannot_abandon_guest_cleanup(container_tool, monkeypatch, tmp_path):
    entered, release = asyncio.Event(), asyncio.Event()
    guard = tmp_path / 'owned-network-guard.cjs'
    guard.write_text('// controlled fixture', encoding='utf-8')
    monkeypatch.setattr(code_execution, '_write_network_guard', lambda *_args: guard)

    async def cleanup_guest(_owned):
        entered.set()
        await release.wait()
        return True

    cleanup = AsyncMock(side_effect=cleanup_guest)
    monkeypatch.setattr(code_execution, '_cleanup_owned_container', cleanup)
    monkeypatch.setattr(code_execution, '_collect_process_output', AsyncMock(side_effect=asyncio.CancelledError))
    task = asyncio.create_task(container_tool(code='// fixture'))
    await entered.wait()
    task.cancel()
    await asyncio.sleep(0)
    assert not task.done()
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    cleanup.assert_awaited_once()
    assert not guard.exists()


@pytest.mark.asyncio
async def test_engine_startup_is_inside_cleanup_deadline(monkeypatch):
    async def stalled_spawn(*args, **kwargs):
        await asyncio.Event().wait()

    monkeypatch.setattr(code_execution.asyncio, 'create_subprocess_exec', stalled_spawn)
    monkeypatch.setattr(code_execution, '_CONTAINER_CLEANUP_SECONDS', .02)
    assert await asyncio.wait_for(code_execution._cleanup_owned_container(owned()), .2) is False


@pytest.mark.asyncio
async def test_successful_runs_use_unique_ownership_without_extra_cleanup(container_tool, monkeypatch):
    cleanup = AsyncMock()
    monkeypatch.setattr(code_execution, '_cleanup_owned_container', cleanup)
    monkeypatch.setattr(
        code_execution, '_collect_process_output',
        AsyncMock(return_value=code_execution._CapturedOutput(b'fixture complete', b'')),
    )
    spawn = code_execution.asyncio.create_subprocess_exec
    for _ in range(2):
        result = await container_tool(code='// fixture')
        assert 'completed successfully' in result
    names = []
    for call in spawn.await_args_list:
        args = call.args
        assert args[:2] == ('docker', 'run')
        assert '--rm' in args
        name = args[args.index('--name') + 1]
        assert name.startswith('canvas-mcp-')
        nonce = name[len('canvas-mcp-'):]
        assert len(nonce) == 32 and all(char in '0123456789abcdef' for char in nonce)
        assert args[args.index('--label') + 1] == 'io.github.canvas-mcp.execution=' + nonce
        names.append(name)
    assert len(set(names)) == 2
    cleanup.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize('identity', [
    code_execution._OwnedContainer('unknown', 'canvas-mcp-' + NONCE, NONCE),
    code_execution._OwnedContainer('docker', 'other-service', NONCE),
    code_execution._OwnedContainer('docker', 'canvas-mcp-untrusted', 'untrusted'),
])
async def test_untrusted_ownership_never_reaches_engine(scripted_engine, identity):
    _responses, calls = scripted_engine
    assert await code_execution._cleanup_owned_container(identity) is False
    assert calls == []


@pytest.mark.asyncio
async def test_podman_cleanup_uses_same_exact_id_contract(scripted_engine):
    responses, calls = scripted_engine
    responses.extend([(0, f'{CONTAINER_ID} {NONCE}\n'.encode()), (0, b''), (0, b'')])
    podman_owned = owned()._replace(runtime='podman')
    assert await code_execution._cleanup_owned_container(podman_owned) is True
    assert all(call[0] == 'podman' for call in calls)
    assert calls[1] == ('podman', 'rm', '--force', CONTAINER_ID)


@pytest.mark.asyncio
@pytest.mark.parametrize('failure', ['timeout', 'output_limit'])
async def test_engine_resource_failure_reaps_cli_and_remains_unknown(monkeypatch, failure):
    stdout, stderr = asyncio.StreamReader(), asyncio.StreamReader()
    if failure == 'output_limit':
        stdout.feed_data(b'X' * (64 * 1024 + 1))
    killed = asyncio.Event()

    async def wait():
        await killed.wait()
        return -9

    process = MagicMock(stdout=stdout, stderr=stderr, stdin=None, returncode=None)
    process.wait = AsyncMock(side_effect=wait)

    def kill():
        process.returncode = -9
        stdout.feed_eof()
        stderr.feed_eof()
        killed.set()

    process.kill.side_effect = kill
    spawn = AsyncMock(return_value=process)
    monkeypatch.setattr(code_execution.asyncio, 'create_subprocess_exec', spawn)
    monkeypatch.setattr(code_execution, '_CONTAINER_CLEANUP_SECONDS', .02)
    assert await asyncio.wait_for(code_execution._cleanup_owned_container(owned()), .2) is False
    assert killed.is_set()
    process.kill.assert_called_once()
    spawn.assert_awaited_once()


@pytest.mark.asyncio
async def test_cancelled_unknown_cleanup_records_only_run_reference(container_tool, monkeypatch):
    monkeypatch.setattr(code_execution, '_cleanup_owned_container', AsyncMock(return_value=False))
    monkeypatch.setattr(code_execution, '_collect_process_output', AsyncMock(side_effect=asyncio.CancelledError))
    warning = MagicMock()
    monkeypatch.setattr(code_execution, 'log_warning', warning)
    with pytest.raises(asyncio.CancelledError):
        await container_tool(code='// private caller code')
    messages = '\n'.join(str(call.args[0]) for call in warning.call_args_list)
    assert 'cleanup HELD/UNKNOWN: canvas-mcp-' in messages
    assert 'do not automatically retry' in messages
    assert 'private caller code' not in messages
    assert 'fixture-token' not in messages
