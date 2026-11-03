"""Independent draft executor integration; fictional rows and no transport."""

import copy

import pytest
from test_gradebook import snapshot as snapshot
from test_gradebook_native import binding as binding
from test_gradebook_native import raw_from_state
from test_localgrass_draft_edit import case as case

from canvas_mcp.gradebook import native
from canvas_mcp.gradebook.client import GradebookError
from canvas_mcp.gradebook.localgrass_draft_edit import CONTRACT as DRAFT_CONTRACT
from canvas_mcp.gradebook.localgrass_edit_execution import execute_local_edit_once
from canvas_mcp.gradebook.localgrass_teacher_edit import CONTRACT as ACCEPTED_CONTRACT
from canvas_mcp.gradebook.model import digest


@pytest.mark.asyncio
async def test_real_existing_executor_stages_draft_once_with_draft_receipts(
    case, tmp_path
):
    connection, context, _, _ = case
    plan = connection.prepare(**context)
    writes = []

    def write(book, requests):
        writes.append(copy.deepcopy(requests))
        state = native._state(context["raw"])
        native._apply_requests(state, requests, context["binding"])
        context["raw"] = raw_from_state(state)

    args = {
        "expected_plan_sha256": digest(plan),
        "output_root": tmp_path / "shared-history",
        "read_context": lambda: context,
        "write_requests": write,
        "enabled": True,
    }
    first = await execute_local_edit_once(connection, plan, **args)
    again = await execute_local_edit_once(connection, plan, **args)
    assert len(writes) == 1
    for receipt in (first, again):
        assert receipt["contract"] == DRAFT_CONTRACT
        assert receipt["status"] == "PLANNED_OUTPUT_OBSERVED"
        assert receipt["review_state"] == "UNAPPROVED"
        assert receipt["source_lane"] == "SDMGRASS_FORMATIVE"
        assert receipt["delivery_policy"] == "SCORE_ONLY"
        assert receipt["teacher_approval"] is receipt["publication_allowed"] is False
        assert (
            receipt["score_delivery_authorized"]
            is receipt["comment_delivery_authorized"]
            is False
        )
        assert receipt["retry_writes"] is False and receipt["canvas_writes"] == 0


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "contract", [ACCEPTED_CONTRACT, DRAFT_CONTRACT, "LOCAL_PARTICIPATION_EDIT_STAGE_V1"]
)
@pytest.mark.parametrize("phase", ["SENDING", "UNCERTAIN_RECONCILIATION_REQUIRED"])
async def test_all_contract_histories_block_overlapping_draft_before_native_reads(
    case, tmp_path, contract, phase
):
    connection, context, _, _ = case
    plan = connection.prepare(**context)
    root = connection.files.private_directory(tmp_path / "shared-history")
    prior = {"contract": contract, "binding": plan["binding"], "items": plan["items"]}
    folder_id = digest(prior)
    if contract == "LOCAL_PARTICIPATION_EDIT_STAGE_V1":
        prior["plan_id"] = folder_id
    folder = connection.files.private_directory(root / folder_id)
    connection.files.write(folder / "plan.json", prior)
    connection.files.write(
        folder / "receipt-001.json", {"status": phase, "contract": contract}
    )

    def forbidden(*args):
        raise AssertionError(
            "Cross-contract uncertain history reached native callbacks"
        )

    with pytest.raises(GradebookError, match="UNRESOLVED_NATIVE_TARGET_HISTORY"):
        await execute_local_edit_once(
            connection,
            plan,
            expected_plan_sha256=digest(plan),
            output_root=root,
            read_context=forbidden,
            write_requests=forbidden,
            enabled=True,
        )


@pytest.mark.asyncio
async def test_draft_same_plan_cannot_adopt_accepted_contract_receipt(case, tmp_path):
    connection, context, _, _ = case
    plan = connection.prepare(**context)
    plan_id = digest(plan)
    root = connection.files.private_directory(tmp_path / "shared-history")
    folder = connection.files.private_directory(root / plan_id)
    connection.files.write(folder / "plan.json", plan)
    connection.files.write(
        folder / "receipt-001.json",
        {
            "contract": ACCEPTED_CONTRACT,
            "plan_id": plan_id,
            "status": "PLANNED_OUTPUT_OBSERVED",
            "canvas_writes": 0,
            "retry_writes": False,
            "publication_allowed": False,
        },
    )

    def forbidden(*args):
        raise AssertionError("Wrong receipt contract reached native callbacks")

    with pytest.raises(GradebookError, match="RETAINED_NATIVE_RECEIPT_UNVERIFIED"):
        await execute_local_edit_once(
            connection,
            plan,
            expected_plan_sha256=plan_id,
            output_root=root,
            read_context=forbidden,
            write_requests=forbidden,
            reconcile_only=True,
        )


@pytest.mark.asyncio
async def test_compact_history_roundtrips_through_same_bounded_file_loader(
    case, tmp_path, monkeypatch
):
    import json

    connection, context, _, _ = case
    plan = connection.prepare(**context)
    files = connection.files
    compact = json.dumps(
        plan, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode()
    pretty = files.encoded(plan)
    assert len(pretty) > len(compact)
    cap = (len(pretty) + len(compact)) // 2
    original_load = files.load
    monkeypatch.setattr(files, "MAX_JSON", cap)
    monkeypatch.setattr(files, "load", lambda path: original_load(path, maximum=cap))
    writes = []

    def write(book, requests):
        writes.append(copy.deepcopy(requests))
        state = native._state(context["raw"])
        native._apply_requests(state, requests, context["binding"])
        context["raw"] = raw_from_state(state)

    kwargs = {
        "expected_plan_sha256": digest(plan),
        "output_root": tmp_path / "compact-history",
        "read_context": lambda: context,
        "write_requests": write,
        "enabled": True,
    }
    first = await execute_local_edit_once(connection, plan, **kwargs)
    again = await execute_local_edit_once(connection, plan, **kwargs)
    saved = kwargs["output_root"] / digest(plan) / "plan.json"
    assert saved.read_bytes() == compact
    assert len(saved.read_bytes()) <= cap < len(pretty)
    assert files.load(saved) == plan
    assert len(writes) == 1
    assert first["status"] == again["status"] == "PLANNED_OUTPUT_OBSERVED"


@pytest.mark.asyncio
async def test_oversized_compact_plan_holds_before_history_write_or_context_read(
    case, tmp_path, monkeypatch
):
    import json

    connection, context, _, _ = case
    plan = connection.prepare(**context)
    files = connection.files
    compact = json.dumps(
        plan, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode()
    monkeypatch.setattr(files, "MAX_JSON", len(compact) - 1)
    output_root = tmp_path / "oversized-history"

    def forbidden(*args):
        raise AssertionError("Oversized history reached a source/native callback")

    with pytest.raises(GradebookError, match="NATIVE_PLAN_EXCEEDS_LOAD_LIMIT"):
        await execute_local_edit_once(
            connection,
            plan,
            expected_plan_sha256=digest(plan),
            output_root=output_root,
            read_context=forbidden,
            write_requests=forbidden,
            enabled=True,
        )
    assert not list(output_root.glob("*/plan.json"))
    assert not list(output_root.glob("*/receipt-*.json"))
