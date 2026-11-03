"""Actual mock HTTP and reopened durable owner receipt failure contracts."""

import copy
from typing import Any

import httpx
import pytest
from test_gradebook import snapshot as snapshot
from test_gradebook_publish import observed_system as observed_system
from test_gradebook_publish import system as system

from canvas_mcp.gradebook.client import GradebookError
from canvas_mcp.gradebook.ledger import Ledger
from canvas_mcp.gradebook.publish import OwnerControls, WriteUncertain


def owned_controls(*, response: Any = None, readback: Any = None) -> OwnerControls:
    async def refresh(course_id: str, item: dict[str, Any]) -> None:
        return None

    def current(course_id: str, item: dict[str, Any]) -> None:
        return None

    def bind(plan: dict[str, Any]) -> dict[str, Any]:
        return {
            "contract": "FICTIONAL_OWNER_RECEIPT_TEST_V1",
            "source": "saved-fixture",
        }

    return OwnerControls(refresh, current, bind, response, readback)


@pytest.mark.parametrize("sink_phase", ["response", "readback"])
@pytest.mark.parametrize("failure", ["raises", "invalid_return", "async_return"])
async def test_failed_owner_sink_keeps_durable_uncertainty_and_forbids_replay(
    system: Any, sink_phase: str, failure: str
) -> None:
    publisher, state, review_id, _ = system
    observations = []

    async def invalid_async() -> None:
        raise AssertionError("Asynchronous receipt must not execute")

    def sink(course_id: str, item: dict[str, Any], evidence: Any) -> Any:
        assert course_id == "12"
        assert item["proposed"] == 20
        assert len(state["puts"]) == 1
        if sink_phase == "response":
            assert isinstance(evidence, httpx.Response)
            assert evidence.status_code == 200
        else:
            assert evidence["submission"]["value"] == 20
        observations.append(sink_phase)
        if failure == "raises":
            raise OSError("Synthetic receipt storage failure")
        if failure == "invalid_return":
            return {"not_a_synchronous_save": True}
        return invalid_async()

    owner = owned_controls(**{sink_phase: sink})
    proposal = await publisher.prepare("12", review_id, owner_controls=owner)
    op_id = proposal["operation_id"]
    token = proposal["confirmation_token"]
    try:
        await publisher.confirm("12", op_id, token, owner_controls=owner)
    except WriteUncertain:
        pass
    assert observations == [sink_phase]
    assert state["puts"] == [{"submission": {"posted_grade": "20"}}]
    # Reopen sqlite, rather than relying on the in-memory Publisher's result.
    persisted = Ledger(publisher.store.root)
    assert persisted.summary(op_id)["status"] == "uncertain"
    assert persisted.summary(op_id)["counts"] == {"uncertain": 1}
    with persisted.connect() as db:
        assert (
            db.execute(
                "SELECT count(*) FROM target_locks WHERE operation_id=?", (op_id,)
            ).fetchone()[0]
            == 1
        )
    with pytest.raises(GradebookError, match="already consumed"):
        await publisher.confirm("12", op_id, token, owner_controls=owner)
    assert len(state["puts"]) == 1
    reconciled = await publisher.reconcile("12", op_id)
    assert reconciled["counts"] == {"observed_applied": 1}
    assert "verified" not in reconciled["counts"]
    assert observations == [sink_phase]
    assert len(state["puts"]) == 1


@pytest.mark.parametrize("owner_bound", [False, True])
@pytest.mark.parametrize("drift", ["score", "attempt", "missing_safety_field"])
async def test_independent_target_mismatched_readback_is_never_verified(
    observed_system: Any, owner_bound: bool, drift: str
) -> None:
    publisher, state, review_id, _ = observed_system
    captured = []

    def readback(
        course_id: str, item: dict[str, Any], evidence: dict[str, Any]
    ) -> None:
        captured.append(copy.deepcopy(evidence))

    owner = owned_controls(readback=readback) if owner_bound else None
    proposal = await publisher.prepare("12", review_id, owner_controls=owner)
    if drift == "score":
        state["after_put"]["score"] = 19
    elif drift == "attempt":
        state["after_put"]["attempt"] = 2
    else:
        state["remove_after_put"] = ["grade_matches_current_submission"]
    op_id = proposal["operation_id"]
    result = await publisher.confirm(
        "12",
        op_id,
        proposal["confirmation_token"],
        independent_targets=True,
        owner_controls=owner,
    )
    assert result["status"] == "uncertain"
    assert result["counts"] == {"uncertain": 1}
    persisted = Ledger(publisher.store.root)
    assert persisted.summary(op_id)["counts"] == {"uncertain": 1}
    assert persisted.operation(op_id)["items"][0]["status"] == "uncertain"
    if owner_bound:
        assert len(captured) == 1
        if drift == "score":
            assert captured[0]["submission"]["value"] == 19
        elif drift == "attempt":
            assert captured[0]["submission"]["attempt"] == 2
        else:
            assert captured[0]["submission"]["grade_matches_current_submission"] is None
    assert len(state["puts"]) == 1
    assert (await publisher.reconcile("12", op_id))["counts"] == {"uncertain": 1}
    with pytest.raises(GradebookError, match="already consumed"):
        await publisher.confirm(
            "12",
            op_id,
            proposal["confirmation_token"],
            independent_targets=True,
            owner_controls=owner,
        )
    assert len(state["puts"]) == 1
