"""Caller regexes must not stall the MCP loop or authorize partial deletion.

The subprocess guard contains a regression to Python's unbounded backtracking;
the tool's own worker deadline must finish well before the outer test budget.
"""

import asyncio
import re
import subprocess
import sys
import textwrap
import threading
from unittest.mock import AsyncMock

import pytest
from fastmcp import FastMCP

from canvas_mcp.tools import discussions


def _criteria_tool():
    server = FastMCP("announcement-regex-limits")
    captured = {}
    original = server.tool

    def tool(*args, **kwargs):
        decorator = original(*args, **kwargs)

        def register(fn):
            captured[fn.__name__] = fn
            return decorator(fn)

        return register

    server.tool = tool
    discussions.register_educator_discussion_tools(server)
    return captured["delete_announcements_by_criteria"]


@pytest.fixture
def criteria_tool(monkeypatch):
    topics = [
        {"id": 7, "title": "Week 12 — Lab", "is_announcement": True},
        {"id": 8, "title": "Week 2 — Notes", "is_announcement": True},
        {"id": 9, "title": "Other discussion", "is_announcement": False},
    ]
    monkeypatch.setattr(discussions, "get_course_id", AsyncMock(return_value="42"))
    monkeypatch.setattr(discussions, "get_course_code", AsyncMock(return_value="SYNTH101"))
    fetch = AsyncMock(side_effect=lambda *a, **kw: topics)
    request = AsyncMock(return_value={"id": 7})
    monkeypatch.setattr(discussions, "fetch_all_paginated_results", fetch)
    monkeypatch.setattr(discussions, "make_canvas_request", request)
    return _criteria_tool(), topics, fetch, request


def _token(preview):
    match = re.search(r"Confirmation token: (\S+)", preview)
    assert match, preview
    return match[1]


def test_catastrophic_regex_finishes_and_cannot_resurrect_confirmation():
    program = textwrap.dedent('''
        import asyncio, re
        from unittest.mock import AsyncMock
        from fastmcp import FastMCP
        from canvas_mcp.tools import discussions
        mcp = FastMCP("regex-budget-regression")
        captured = {}
        def tool(*args, **kwargs):
            def capture(fn):
                captured[fn.__name__] = fn
                return fn
            return capture
        mcp.tool = tool
        discussions.register_educator_discussion_tools(mcp)
        discussions.get_course_id = AsyncMock(return_value="42")
        discussions.get_course_code = AsyncMock(return_value="SYNTH101")
        topics = [{"id": 7, "title": "aaa", "is_announcement": True}]
        discussions.fetch_all_paginated_results = AsyncMock(side_effect=lambda *a, **kw: topics)
        request = AsyncMock(return_value={"id": 7})
        discussions.make_canvas_request = request
        async def run():
            call = captured["delete_announcements_by_criteria"]
            criteria = {"title_regex": "(a+)+$"}
            preview = await call("42", criteria)
            token = re.search(r"Confirmation token: (\\S+)", preview)[1]
            topics[0]["title"] = "a" * 1000 + "!"
            held = await call("42", criteria, confirmation_token=token)
            assert "time limit" in held.lower(), held
            assert "Nothing was deleted" in held and "Confirmation token:" not in held
            topics[0]["title"] = "aaa"
            replay = await call("42", criteria, confirmation_token=token)
            assert "already used" in replay.lower(), replay
            assert request.await_count == 0
        asyncio.run(run())
    ''')
    result = subprocess.run(
        [sys.executable, "-c", program], capture_output=True, text=True,
        encoding="utf-8", timeout=12,
    )
    assert result.returncode == 0, result.stderr


async def test_oversize_regex_is_refused_before_canvas_or_worker(criteria_tool):
    call, _, fetch, request = criteria_tool
    result = await call("42", {"title_regex": "a" * 513})
    assert "limit" in result.lower() and "Nothing was deleted" in result
    assert "Confirmation token:" not in result
    fetch.assert_not_awaited()
    request.assert_not_awaited()


@pytest.mark.parametrize("pattern,ids", [
    (r"^week\s+\d+.*lab$", [7]),
    (r"Week (1?2)\b", [7, 8]),
    (r"(?<=— )Notes$", [8]),
    (r"(Week)\s+\d+.*", [7, 8]),
    (r"^no match$", []),
])
async def test_ordinary_python_regex_selection_keeps_exact_preview(criteria_tool, pattern, ids):
    call, _, _, request = criteria_tool
    preview = await call("42", {"title_regex": pattern})
    for identifier in (7, 8, 9):
        assert (f"ID: {identifier}," in preview) is (identifier in ids)
    assert ("Confirmation token:" in preview) is bool(ids)
    request.assert_not_awaited()


async def test_invalid_regex_never_prepares_or_deletes(criteria_tool):
    call, _, _, request = criteria_tool
    result = await call("42", {"title_regex": "["})
    assert "Invalid regex" in result
    assert "Confirmation token:" not in result
    request.assert_not_awaited()


@pytest.mark.parametrize("titles", [
    ["x" * 4097],
    ["x" * 4096] * 33,
    ["x"] * 5001,
    [None],
])
async def test_oversize_or_invalid_titles_hold_before_worker(criteria_tool, monkeypatch, titles):
    call, topics, _, request = criteria_tool
    topics[:] = [{"id": index + 1, "title": title, "is_announcement": True} for index, title in enumerate(titles)]

    async def forbidden_spawn(*a, **kw):
        pytest.fail("Rejected selection must not create a regex worker")

    monkeypatch.setattr(discussions.asyncio, "create_subprocess_exec", forbidden_spawn)
    result = await call("42", {"title_regex": "."})
    assert "Nothing was deleted" in result and "Confirmation token:" not in result
    request.assert_not_awaited()


async def test_one_isolated_worker_keeps_python_compatibility_and_no_credentials(criteria_tool, monkeypatch):
    call, topics, _, request = criteria_tool
    topics[:] = [
        {"id": 7, "title": "Résumé Résumé", "is_announcement": True},
        {"id": 8, "title": "Résumé Different", "is_announcement": True},
    ]
    created = []
    real_spawn = asyncio.create_subprocess_exec
    monkeypatch.setenv("CANVAS_API_TOKEN", "SYNTHETIC_NOT_A_CREDENTIAL")
    monkeypatch.setenv("PYTHONPATH", "/fictional/untrusted/import/path")

    async def spawn(*args, **kwargs):
        created.append((args, kwargs))
        return await real_spawn(*args, **kwargs)

    monkeypatch.setattr(discussions.asyncio, "create_subprocess_exec", spawn)
    preview = await call("42", {"title_regex": r"^(résumé) \1$"})
    assert "ID: 7," in preview and "ID: 8," not in preview
    assert len(created) == 1
    args, kwargs = created[0]
    assert args[:4] == (sys.executable, "-I", "-S", "-c")
    assert set(kwargs["env"]) <= {"SYSTEMROOT", "WINDIR"}
    assert "SYNTHETIC_NOT_A_CREDENTIAL" not in repr((args, kwargs))
    assert "Résumé" not in repr(args)
    request.assert_not_awaited()


async def test_title_contains_prefilter_avoids_work_on_excluded_titles(criteria_tool):
    call, topics, _, request = criteria_tool
    topics[0]["title"] = "a" * 1000 + "!"
    result = await call("42", {"title_contains": "not present", "title_regex": "(a+)+$"})
    assert "No announcements matched" in result
    assert "Confirmation token:" not in result
    request.assert_not_awaited()


async def test_cancelled_selection_reaps_only_owned_worker_and_keeps_loop_responsive(criteria_tool, monkeypatch):
    call, topics, _, request = criteria_tool
    topics[0]["title"] = "a" * 1000 + "!"
    created = []
    started = asyncio.Event()
    real_spawn = asyncio.create_subprocess_exec

    async def spawn(*args, **kwargs):
        process = await real_spawn(*args, **kwargs)
        created.append(process)
        started.set()
        return process

    monkeypatch.setattr(discussions.asyncio, "create_subprocess_exec", spawn)
    task = asyncio.create_task(call("42", {"title_regex": "(a+)+$"}))
    await asyncio.wait_for(started.wait(), timeout=2)
    # A synchronous regex on the MCP loop would prevent this yield/cancellation.
    await asyncio.sleep(0.05)
    assert not task.done()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(task, timeout=2)
    assert len(created) == 1 and created[0].returncode is not None
    request.assert_not_awaited()


async def test_deadline_includes_worker_creation(criteria_tool, monkeypatch):
    call, _, _, request = criteria_tool
    cancelled = asyncio.Event()

    async def slow_spawn(*args, **kwargs):
        try:
            await asyncio.sleep(10)
        finally:
            cancelled.set()

    monkeypatch.setattr(discussions.asyncio, "create_subprocess_exec", slow_spawn)
    monkeypatch.setattr(discussions, "_TITLE_REGEX_SECONDS", 0.02)
    result = await asyncio.wait_for(call("42", {"title_regex": "."}), timeout=1)
    assert "time limit" in result and "Confirmation token:" not in result
    assert cancelled.is_set()
    request.assert_not_awaited()


async def test_busy_selection_holds_without_spawning_or_preview(criteria_tool, monkeypatch):
    call, _, _, request = criteria_tool
    slots = threading.BoundedSemaphore(2)
    assert slots.acquire(blocking=False) and slots.acquire(blocking=False)
    monkeypatch.setattr(discussions, "_TITLE_REGEX_WORKERS", slots)

    async def forbidden_spawn(*args, **kwargs):
        pytest.fail("No worker slot must mean no new process")

    monkeypatch.setattr(discussions.asyncio, "create_subprocess_exec", forbidden_spawn)
    result = await call("42", {"title_regex": "."})
    assert "busy" in result and "Nothing was deleted" in result
    assert "Confirmation token:" not in result
    request.assert_not_awaited()


async def test_spawn_failure_is_private_and_does_not_prepare(criteria_tool, monkeypatch):
    call, _, _, request = criteria_tool

    async def broken_spawn(*args, **kwargs):
        raise OSError("/fictional/private/path SYNTHETIC_SECRET")

    monkeypatch.setattr(discussions.asyncio, "create_subprocess_exec", broken_spawn)
    result = await call("42", {"title_regex": "."})
    assert "unavailable" in result and "Nothing was deleted" in result
    assert "fictional" not in result and "SYNTHETIC_SECRET" not in result
    assert "Confirmation token:" not in result
    request.assert_not_awaited()
