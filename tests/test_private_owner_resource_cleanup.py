"""Real lock descriptors and awaited mock-client cleanup across interruptions."""

import asyncio
import errno
import json
import os
from typing import Any

import pytest
from test_gradebook import snapshot as snapshot
from test_gradebook_native import binding as binding
from test_private_proposed_edit import scenario as scenario
from test_reviewed_whole_private_bridge import no_network as no_network
from test_reviewed_whole_private_bridge import once as once
from test_reviewed_whole_private_bridge import reviewed as reviewed

from canvas_mcp.gradebook.client import GradebookError
from canvas_mcp.gradebook.model import digest


@pytest.fixture
def lock_descriptors(once: Any, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    owner, _, _, _ = once
    paths = {os.fspath(path) for path, _, _ in owner.locks}
    opened: list[int] = []
    active: set[int] = set()
    closed: list[int] = []
    original_open, original_close = os.open, os.close

    def track_open(path: Any, flags: int, *args: Any, **kwargs: Any) -> int:
        descriptor = original_open(path, flags, *args, **kwargs)
        if os.fspath(path) in paths:
            opened.append(descriptor)
            active.add(descriptor)
        return descriptor

    def track_close(descriptor: int) -> None:
        tracked = descriptor in active
        original_close(descriptor)
        if tracked:
            # Prove actual OS closure before another operation can reuse it.
            with pytest.raises(OSError) as error:
                os.fstat(descriptor)
            assert error.value.errno == errno.EBADF
            active.remove(descriptor)
            closed.append(descriptor)

    monkeypatch.setattr(os, "open", track_open)
    monkeypatch.setattr(os, "close", track_close)
    return {"opened": opened, "active": active, "closed": closed}


@pytest.mark.parametrize(
    "outcome", ["success", "early_owner_hold", "cancel_after_send"]
)
async def test_all_acquired_lock_descriptors_close_on_each_exit(
    once: Any, lock_descriptors: dict[str, Any], outcome: str
) -> None:
    owner, host, plan, state = once
    if outcome == "early_owner_hold":

        def deny() -> None:
            raise GradebookError("FICTIONAL_EARLY_OWNER_HOLD")

        host.owner_check = deny
    elif outcome == "cancel_after_send":
        original_send = host.google.send_preflighted_batch

        async def cancelled(requests: Any) -> None:
            await original_send(requests)
            raise asyncio.CancelledError()

        host.google.send_preflighted_batch = cancelled

    if outcome == "success":
        result = await owner.execute(
            plan, host, expected_plan_sha256=digest(plan), review_check=lambda _: None
        )
        assert result["status"] == "PLANNED_OUTPUT_OBSERVED"
    else:
        error = (
            GradebookError if outcome == "early_owner_hold" else asyncio.CancelledError
        )
        with pytest.raises(error):
            await owner.execute(
                plan,
                host,
                expected_plan_sha256=digest(plan),
                review_check=lambda _: None,
            )
    expected_acquisitions = 1 if outcome == "early_owner_hold" else len(owner.locks)
    assert len(lock_descriptors["opened"]) == expected_acquisitions
    assert lock_descriptors["closed"] == list(reversed(lock_descriptors["opened"]))
    assert lock_descriptors["active"] == set()
    assert host.google.http.is_closed and host.canvas.http.is_closed
    assert state["sends"] == (0 if outcome == "early_owner_hold" else 1)
    if outcome == "cancel_after_send":
        directory = next(owner.root.iterdir())
        terminal = json.loads((directory / "terminal.json").read_text(encoding="utf-8"))
        assert terminal["status"] == "READBACK_UNCERTAIN"
        assert terminal["send_attempts"] == 1
        assert terminal["retry_writes"] is False


async def test_cancellation_waits_for_closing_task_before_releasing_locks(
    once: Any, lock_descriptors: dict[str, Any]
) -> None:
    owner, host, plan, state = once
    started, release = asyncio.Event(), asyncio.Event()
    closing_tasks = []
    original_close = host.close

    async def delayed_close() -> None:
        closing_tasks.append(asyncio.current_task())
        started.set()
        await release.wait()
        await original_close()

    host.close = delayed_close
    task = asyncio.create_task(
        owner.execute(
            plan, host, expected_plan_sha256=digest(plan), review_check=lambda _: None
        )
    )
    try:
        await asyncio.wait_for(started.wait(), timeout=2)
        task.cancel()
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        # Awaiting the shielded closing task has a required effect: the owner
        # cannot finish cancellation/release its mutexes before clients close.
        assert not task.done()
        assert len(lock_descriptors["active"]) == len(owner.locks)
        assert not host.google.http.is_closed and not host.canvas.http.is_closed
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await task
    finally:
        release.set()
        await asyncio.gather(task, *closing_tasks, return_exceptions=True)
    assert state["sends"] == 1
    assert host.google.http.is_closed and host.canvas.http.is_closed
    assert lock_descriptors["active"] == set()
    assert lock_descriptors["closed"] == list(reversed(lock_descriptors["opened"]))
