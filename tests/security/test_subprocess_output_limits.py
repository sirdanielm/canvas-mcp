"""Harmless real-child regressions for host output and lifecycle bounds.

The fake credential never leaves the process tree. Python replaces the Node
command, so no Canvas call, package installation or container daemon is used.
"""

import asyncio
import os
import signal
import sys
from collections.abc import AsyncIterator
from unittest.mock import AsyncMock, patch

import pytest
from fastmcp import FastMCP

from canvas_mcp.core.config import reset_config
from canvas_mcp.tools import code_execution

OUTPUT_LIMIT = 1024 * 1024


@pytest.fixture
async def real_child_tool(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator:
    monkeypatch.setenv("CANVAS_API_TOKEN", "fixture-token")
    monkeypatch.setenv("CANVAS_API_URL", "https://canvas.invalid/api/v1")
    monkeypatch.setenv("ENABLE_TS_SANDBOX", "false")
    monkeypatch.setenv("EXECUTE_TYPESCRIPT_ENABLED", "true")
    reset_config()
    captured = {}
    mcp = FastMCP("bounded-child-test")

    def tool(*args, **kwargs):
        def capture(fn):
            captured[fn.__name__] = fn
            return fn
        return capture

    with patch.object(mcp, "tool", tool):
        code_execution.register_code_execution_tools(mcp)
    children = []
    real_spawn = asyncio.create_subprocess_exec

    async def execute(script: str, timeout: int = 3) -> str:
        async def spawn(*args, **kwargs):
            process = await real_spawn(sys.executable, "-c", script, **kwargs)
            children.append(process)
            return process
        with patch.object(code_execution.asyncio, "create_subprocess_exec", spawn), patch.object(
            code_execution, "_build_local_tsx_command", return_value=["fixture-node"]
        ), patch.object(code_execution, "is_http_request_active", return_value=False), patch.object(
            code_execution, "get_request_credentials", return_value=None
        ):
            return await captured["execute_typescript"](code="// fixture", timeout=timeout)

    yield execute, children
    for process in children:
        if process.returncode is None:
            process.kill()
        await asyncio.wait_for(process.wait(), 2)
    reset_config()


@pytest.mark.asyncio
async def test_combined_output_overflow_is_bounded_and_child_reaped(real_child_tool) -> None:
    execute, children = real_child_tool
    result = await execute(
        "import os,threading; "
        "a=threading.Thread(target=lambda: os.write(1,b'O'*786432)); "
        "b=threading.Thread(target=lambda: os.write(2,b'E'*786432)); "
        "a.start(); b.start(); a.join(); b.join()"
    )
    limited = "output limit" in result.lower()
    assert limited, result[:200]
    assert len(result.encode()) <= OUTPUT_LIMIT + 4096
    assert children[0].returncode is not None
    assert "completed successfully" not in result[:200]
    assert "Do not automatically retry" in result[:400]


@pytest.mark.asyncio
@pytest.mark.parametrize("extra", [0, 1])
async def test_exact_output_boundary(real_child_tool, extra: int) -> None:
    execute, children = real_child_tool
    result = await execute(f"import os; os.write(1,b'B'*{OUTPUT_LIMIT + extra})")
    limited = "output limit" in result.lower()
    assert limited == bool(extra), result[:200]
    assert children[0].returncode is not None
    if not extra:
        assert result.count("B") == OUTPUT_LIMIT


@pytest.mark.asyncio
async def test_both_pipes_larger_than_pipe_buffer_complete_without_deadlock(real_child_tool) -> None:
    execute, _children = real_child_tool
    result = await execute(
        "import os,threading; "
        "a=threading.Thread(target=lambda: os.write(1,b'A'*262144)); "
        "b=threading.Thread(target=lambda: os.write(2,b'Z'*262144)); "
        "a.start(); b.start(); a.join(); b.join()"
    )
    assert result.count("A") == 262144
    assert result.count("Z") == 262144
    assert "completed successfully" in result[:200]


@pytest.mark.asyncio
async def test_cancelled_tool_reaps_owned_child(real_child_tool) -> None:
    execute, children = real_child_tool
    task = asyncio.create_task(execute("import time; time.sleep(30)"))
    while not children:
        await asyncio.sleep(0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    await asyncio.sleep(0)
    reaped = children[0].returncode is not None
    assert reaped


@pytest.mark.asyncio
async def test_timeout_preserves_bounded_diagnostics_and_reaps_child(real_child_tool) -> None:
    execute, children = real_child_tool
    result = await execute(
        "import os,time; os.write(1,b'partial output'); "
        "os.write(2,b'fixture diagnostic'); time.sleep(30)", timeout=1
    )
    assert "timed out" in result[:200]
    assert "Do not automatically retry" in result[:400]
    diagnostic_retained = "fixture diagnostic" in result and "partial output" in result
    assert diagnostic_retained
    assert children[0].returncode is not None


@pytest.mark.asyncio
async def test_stdin_and_both_output_pipes_are_pumped_concurrently() -> None:
    process = await asyncio.create_subprocess_exec(
        sys.executable, "-c",
        "import os,sys; os.write(1,b'R'*262144); "
        "data=sys.stdin.buffer.read(); os.write(2,str(len(data)).encode())",
        stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE, limit=16384,
        start_new_session=os.name == "posix", env={},
    )
    output = await code_execution._collect_process_output(
        process, timeout=3, input_data=b'I' * 262144,
        owns_process_group=os.name == "posix",
    )
    assert output.stdout == b'R' * 262144
    assert output.stderr == b'262144'
    assert process.returncode == 0


@pytest.mark.asyncio
async def test_closed_stdin_does_not_drop_child_diagnostics() -> None:
    process = await asyncio.create_subprocess_exec(
        sys.executable, "-c", "import os; os.close(0); print('fixture complete')",
        stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE, limit=16384,
        start_new_session=os.name == "posix", env={},
    )
    output = await code_execution._collect_process_output(
        process, timeout=3, input_data=b'I' * 262144,
        owns_process_group=os.name == "posix",
    )
    assert output.stdout == b'fixture complete\n'
    assert process.returncode == 0


@pytest.mark.asyncio
async def test_runtime_version_probe_fails_closed_on_output_overflow(monkeypatch) -> None:
    real_spawn = asyncio.create_subprocess_exec
    children = []

    async def spawn(*args, **kwargs):
        process = await real_spawn(
            sys.executable, '-c', "import os,time; os.write(1,b'V'*131072); time.sleep(30)",
            **kwargs, env={},
        )
        children.append(process)
        return process

    monkeypatch.setattr(code_execution.asyncio, 'create_subprocess_exec', spawn)
    assert await code_execution._runtime_available('fixture-runtime') is False
    assert children[0].returncode is not None


@pytest.mark.asyncio
async def test_reader_failure_also_reaps_owned_child(monkeypatch) -> None:
    process = await asyncio.create_subprocess_exec(
        sys.executable, '-c', 'import time; time.sleep(30)',
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        start_new_session=os.name == 'posix', env={},
    )
    assert process.stdout is not None
    monkeypatch.setattr(process.stdout, 'read', AsyncMock(side_effect=OSError('fixture read failure')))
    with pytest.raises(OSError, match='fixture read failure'):
        await code_execution._collect_process_output(
            process, timeout=3, owns_process_group=os.name == 'posix',
        )
    assert process.returncode is not None


@pytest.mark.asyncio
@pytest.mark.skipif(os.name != 'posix', reason='owned process groups are POSIX-specific')
async def test_timeout_stops_descendant_holding_output_pipe(tmp_path) -> None:
    heartbeat = tmp_path / 'owned-child-heartbeat'
    child = (
        "import time,pathlib; p=pathlib.Path(" + repr(str(heartbeat)) + "); "
        "\nwhile True:\n p.write_text(str(time.monotonic())); time.sleep(.01)"
    )
    parent = (
        "import subprocess,sys; "
        f"subprocess.Popen([sys.executable,'-c',{child!r}]); print('parent exited')"
    )
    process = await asyncio.create_subprocess_exec(
        sys.executable, '-c', parent, stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE, start_new_session=True, env={},
    )
    try:
        with pytest.raises(code_execution._ProcessOutputError, match='timeout'):
            await code_execution._collect_process_output(
                process, timeout=.3, owns_process_group=True,
            )
        assert heartbeat.exists()
        before = heartbeat.read_bytes()
        await asyncio.sleep(.1)
        assert heartbeat.read_bytes() == before
        assert process.returncode == 0
    finally:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            # Successful collector cleanup already removed this owned group.
            pass
        await asyncio.wait_for(process.wait(), 2)
