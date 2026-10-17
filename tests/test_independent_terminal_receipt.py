"""Regression reproducer: historical verified success must stay terminal."""

import copy

import pytest
from test_gradebook_native import raw_from_state
from test_localgrass_teacher_edit import binding as binding
from test_localgrass_teacher_edit import integrated as integrated
from test_localgrass_teacher_edit import snapshot as snapshot

from canvas_mcp.gradebook import native
from canvas_mcp.gradebook.client import GradebookError
from canvas_mcp.gradebook.localgrass_edit_execution import execute_local_edit_once
from canvas_mcp.gradebook.model import digest


@pytest.mark.asyncio
async def test_later_teacher_edit_does_not_revoke_historical_verified_send(
    integrated, tmp_path
):
    connection, context, *_ = integrated
    plan = connection.prepare(**context)
    root = tmp_path / "shared-history"
    writes = []

    def write(book, requests):
        writes.append(copy.deepcopy(requests))
        update = requests[0]["updateCells"]
        state = native._state(context["raw"])
        state["sheets"][2]["cells"]["5:2"].update(update["rows"][0]["values"][0])
        context["raw"] = raw_from_state(state)

    options = {
        "expected_plan_sha256": digest(plan),
        "output_root": root,
        "read_context": lambda: context,
        "write_requests": write,
        "enabled": True,
    }
    first = await execute_local_edit_once(connection, plan, **options)
    assert first["status"] == "PLANNED_OUTPUT_OBSERVED"
    prior_paths = sorted((root / digest(plan)).glob("receipt-*.json"))
    prior_bytes = {path.name: path.read_bytes() for path in prior_paths}
    state = native._state(context["raw"])
    state["sheets"][2]["cells"]["0:0"]["note"] = "Later unrelated teacher note"
    context["raw"] = raw_from_state(state)
    repeated = await execute_local_edit_once(connection, plan, **options)
    assert len(writes) == 1
    assert repeated["status"] == "VERIFIED_HISTORY_RETAINED"
    assert repeated["historical_status"] == "PLANNED_OUTPUT_OBSERVED"
    assert repeated["current_observed_status"] == "DIVERGED"
    assert repeated["historical_receipt_sha256"] == digest(first)
    assert repeated["sheets_write_requests"] == 0
    assert {path.name: path.read_bytes() for path in prior_paths} == prior_bytes
    assert sorted((root / digest(plan)).glob("receipt-*.json")) == prior_paths
    assert (
        native._state(context["raw"])["sheets"][2]["cells"]["0:0"]["note"]
        == "Later unrelated teacher note"
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "field,value", [("contract", "WRONG_CONTRACT"), ("plan_id", "f" * 64)]
)
async def test_terminal_receipt_cannot_claim_another_contract_or_plan(
    integrated, tmp_path, field, value
):
    connection, context, *_ = integrated
    plan = connection.prepare(**context)
    root = connection.files.private_directory(tmp_path / "shared-history")
    session = connection.files.private_directory(root / digest(plan))
    connection.files.write(session / "plan.json", plan)
    receipt = {
        "contract": plan["contract"],
        "plan_id": digest(plan),
        "status": "PLANNED_OUTPUT_OBSERVED",
        "canvas_writes": 0,
        "retry_writes": False,
        "publication_allowed": False,
    }
    receipt[field] = value
    connection.files.write(session / "receipt-001.json", receipt)

    def forbidden(*unused):
        raise AssertionError("Invalid retained receipt reached native I/O")

    with pytest.raises(GradebookError, match="RETAINED_NATIVE_RECEIPT_UNVERIFIED"):
        await execute_local_edit_once(
            connection,
            plan,
            expected_plan_sha256=digest(plan),
            output_root=root,
            read_context=forbidden,
            write_requests=forbidden,
            enabled=True,
        )
