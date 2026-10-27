"""Opt-in cross-repo test: real authenticated local stores, fictional bytes.

Set LOCALGRASS_TEST_ROOT to the reviewed LocalGrAss checkout to run. No service,
real roster, model or external transport is used. Default CI reports this
external-repository integration as skipped rather than substituting fake auth.
"""

import asyncio
import copy
import hashlib
import importlib.util
import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from test_gradebook import snapshot as snapshot
from test_gradebook_native import binding as binding
from test_gradebook_native import initial_raw, raw_from_state

from canvas_mcp.gradebook import native
from canvas_mcp.gradebook.capture import save_capture
from canvas_mcp.gradebook.client import GradebookError
from canvas_mcp.gradebook.localgrass_edit_execution import execute_local_edit_once
from canvas_mcp.gradebook.localgrass_teacher_edit import LocalGrAssEditConnection
from canvas_mcp.gradebook.model import digest
from canvas_mcp.gradebook.store import Store

external = os.environ.get("LOCALGRASS_TEST_ROOT")
if not external:
    pytest.skip(
        "Explicit reviewed LocalGrAss test checkout required", allow_module_level=True
    )
external_root = Path(external)
assert external_root.is_absolute()
sys.path.insert(0, str(external_root))
spec = importlib.util.spec_from_file_location(
    "reviewed_localgrass_teacher_fixture",
    external_root / "tests/test_teacher_edit_source.py",
)
assert spec is not None and spec.loader is not None
fixture_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fixture_module)


@pytest.fixture
def integrated(tmp_path, snapshot, binding, monkeypatch):
    snapshot["course_workflow_state"] = "available"
    snapshot["assignments"][0]["points_possible"] = 10
    snapshot["cells"]["101:21"].update(
        value=2,
        grade="2",
        attempt=3,
        submitted_at="2026-10-10T12:00:00Z",
        grade_matches_current_submission=True,
    )
    store = Store(tmp_path / "canvas")
    capture_id = save_capture(store, snapshot)
    registry_path, roster_path = (
        tmp_path / "pin-registry.json",
        tmp_path / "roster.json",
    )
    registry_path.write_bytes(b"Fictional shared registry only")
    roster_path.write_bytes(b"Fictional shared roster only")
    registry_hash = hashlib.sha256(registry_path.read_bytes()).hexdigest()
    roster_hash = hashlib.sha256(roster_path.read_bytes()).hexdigest()
    pins = {
        "registry_sha256": registry_hash,
        "roster_sha256": roster_hash,
        "by_pin": {"0042": "101"},
    }

    def transform(receipt):
        receipt["capture_revision"] = capture_id
        receipt["identity"].update(
            registry_sha256=registry_hash,
            snapshot_sha256=roster_hash,
            revision="identity-"
            + digest(
                {"registry_sha256": registry_hash, "snapshot_sha256": roster_hash}
            ),
        )

    source_root = tmp_path / "source"
    source_root.mkdir(mode=0o700)
    domain = fixture_module.VerifiedTeacherSourceFixture(
        source_root, receipt_transform=transform
    )

    def explicit_identity(runtime):
        assert runtime == domain.source.identity_runtime_root
        return (
            {"registry_sha256": registry_hash, "roster_sha256": roster_hash},
            {"fictional@example.invalid": "0042"},
            {},
        )

    monkeypatch.setattr(
        "localgrass.manual_local_recovery.identity_binding",
        explicit_identity,
    )

    def read_shared_table(path, raw, sheet, runtime):
        assert runtime == domain.source.identity_runtime_root
        return (
            ["Canvas ID", "Email"],
            [{"Canvas ID": "101", "Email": "fictional@example.invalid"}],
        )

    shared = SimpleNamespace(
        binding=lambda _: (
            {
                "roster_sheet": "Student Info",
                "roster_sha256": roster_hash,
                "email_column": "Email",
            },
            roster_path,
            roster_path.read_bytes(),
            registry_hash,
        ),
        read_table=read_shared_table,
        roster_index=lambda *unused: ({"fictional@example.invalid": "0042"}, {}),
    )
    monkeypatch.setattr(
        "canvas_mcp.gradebook.capture.load_shared_pin_module", lambda _: shared
    )
    assignments = [
        {
            "assignment_key": domain.scope.assignment_id,
            "student_track": domain.scope.track,
            "source_target": "fictional-target",
            "course_id": "12",
            "assignment_id": "21",
            "maximum": 10,
            "section": "B1",
            "score_scale": "RAW_IDENTITY",
        }
    ]
    assignment_path = tmp_path / "existing-assignment-bindings.json"
    assignment_path.write_text(json.dumps(assignments), encoding="utf-8")
    kwargs = {
        "assignment_bindings_path": assignment_path,
        "expected_assignment_bindings_sha256": hashlib.sha256(
            assignment_path.read_bytes()
        ).hexdigest(),
        "section": "B1",
        "registry_path": registry_path,
        "shared_tool": tmp_path / "existing-shared-pin-tool.py",
    }
    connection = LocalGrAssEditConnection(domain.source, store, **kwargs)
    context = {
        "raw": initial_raw(snapshot, binding),
        "binding": binding,
        "baseline": snapshot,
        "current": copy.deepcopy(snapshot),
        "pin_binding": pins,
    }
    yield connection, context, domain, assignments, assignment_path, kwargs, store
    domain.registry.close()


def test_actual_authenticated_source_capture_and_native_edit_are_connected(integrated):
    connection, context, domain, _, _, _, _ = integrated
    before = domain.registry.connection.total_changes
    plan = connection.prepare(**context)
    assert domain.registry.connection.total_changes == before
    transfer = plan["transfer"]
    assert transfer["record"]["pin"] == "0042"
    assert transfer["record"]["canvas_attempt"] == 3
    assert transfer["record"]["raw_score"] == 10
    assert transfer["decision"]["total_score"] == 7
    assert transfer["decision"]["decision_revision"] == domain.acceptance["decision_id"]
    cell = transfer["requests"][0]["updateCells"]["rows"][0]["values"][0]
    assert cell["userEnteredValue"] == {"numberValue": 7}
    assert cell["note"].endswith("Explicit fictional final feedback.")
    connection.revalidate(
        plan,
        expected_plan_sha256=digest(plan),
        raw=context["raw"],
        current=context["current"],
        pin_binding=context["pin_binding"],
    )
    assert plan["canvas_writes"] == plan["sheets_writes"] == 0
    assert (
        plan["score_delivery_authorized"]
        is plan["comment_delivery_authorized"]
        is False
    )


@pytest.mark.parametrize(
    "change",
    ["attempt", "submission_time", "teacher_note", "target_file", "source", "csrf"],
)
def test_real_cross_repo_authority_and_destination_changes_hold(integrated, change):
    connection, context, domain, _, assignment_path, _, _ = integrated
    plan = connection.prepare(**context)
    if change == "attempt":
        context["current"]["cells"]["101:21"]["attempt"] = 4
    elif change == "submission_time":
        context["current"]["cells"]["101:21"]["submitted_at"] = "2026-10-11T12:00:00Z"
    elif change == "target_file":
        assignment_path.write_text("[]", encoding="utf-8")
    elif change == "source":
        domain.original.write_bytes(b"X" * domain.original.stat().st_size)
    elif change == "csrf":
        domain.source.csrf = "revoked"
    else:
        state = native._state(context["raw"])
        state["sheets"][2]["cells"]["5:2"]["note"] = "Retained teacher correction"
        context["raw"] = raw_from_state(state)
    codes = {
        "attempt": "SOURCE_AUTHORITY_REVALIDATION_HELD",
        "submission_time": "SOURCE_AUTHORITY_REVALIDATION_HELD",
        "teacher_note": "TRANSFER_DESTINATION_CHANGED",
        "target_file": "SOURCE_AUTHORITY_REVALIDATION_HELD",
        "source": "SOURCE_HASH_MISMATCH",
        "csrf": "CSRF_DENIED",
    }
    with pytest.raises(
        (GradebookError, fixture_module.AuthenticatedSourceError), match=codes[change]
    ):
        connection.revalidate(
            plan,
            expected_plan_sha256=digest(plan),
            raw=context["raw"],
            current=context["current"],
            pin_binding=context["pin_binding"],
        )


def test_browser_json_flags_cannot_supply_authentication(integrated):
    _, _, _, _, _, kwargs, store = integrated
    with pytest.raises(GradebookError, match="AUTHENTICATED_SOURCE_REQUIRED"):
        LocalGrAssEditConnection(
            {"source_verified": True, "is_final": True}, store, **kwargs
        )


def test_source_without_exact_retained_canvas_capture_is_held(integrated):
    connection, context, _, _, _, _, _ = integrated
    receipt = connection.store.load(
        "receipt", connection.source.read()["source_receipt"]["capture_revision"]
    )
    snapshot = connection.store.load("snapshot", receipt["snapshot_id"])
    snapshot["cells"]["101:21"]["attempt"] = 4
    # A current read changing alone never retargets the old decision/capture.
    context["current"] = snapshot
    with pytest.raises(GradebookError, match="ORIGINAL_CANVAS_ATTEMPT_CHANGED"):
        connection.prepare(**context)


def test_unknown_native_write_outcome_remains_readback_only(integrated):
    connection, context, _, _, _, _, _ = integrated
    plan = connection.prepare(**context)
    outcome = connection.classify(
        plan, context["raw"], expected_plan_sha256=digest(plan)
    )
    assert outcome["status"] == "BEFORE_STILL_PRESENT"
    assert outcome["retry_writes"] is False
    state = native._state(context["raw"])
    cell = plan["transfer"]["requests"][0]["updateCells"]["rows"][0]["values"][0]
    state["sheets"][2]["cells"]["5:2"].update(cell)
    outcome = connection.classify(
        plan, raw_from_state(state), expected_plan_sha256=digest(plan)
    )
    assert outcome["status"] == "PLANNED_OUTPUT_OBSERVED"
    assert (
        outcome["score_delivery_verified"]
        is outcome["comment_delivery_verified"]
        is False
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["binding", "items"])
async def test_rehashed_wrapper_cannot_retarget_authenticated_transfer(
    integrated, tmp_path, change
):
    connection, context, _, _, _, _, _ = integrated
    plan = connection.prepare(**context)
    if change == "binding":
        plan["binding"]["spreadsheet_id"] = "another-fictional-book"
    else:
        plan["items"] = []
    changed_digest = digest(plan)
    with pytest.raises(GradebookError, match="AUTHENTICATED_TARGET_CHANGED"):
        connection.revalidate(
            plan,
            expected_plan_sha256=changed_digest,
            raw=context["raw"],
            current=context["current"],
            pin_binding=context["pin_binding"],
        )
    with pytest.raises(GradebookError, match="AUTHENTICATED_TARGET_CHANGED"):
        connection.classify(plan, context["raw"], expected_plan_sha256=changed_digest)

    def forbidden(*unused):
        raise AssertionError("Changed wrapper reached native transport")

    output = tmp_path / "existing-stage-root"
    with pytest.raises(GradebookError, match="AUTHENTICATED_TARGET_CHANGED"):
        await execute_local_edit_once(
            connection,
            plan,
            expected_plan_sha256=changed_digest,
            output_root=output,
            read_context=forbidden,
            write_requests=forbidden,
            enabled=True,
        )
    assert not output.exists()


@pytest.mark.asyncio
async def test_executor_is_disabled_without_native_reads_writes_or_local_receipts(
    integrated, tmp_path
):
    connection, context, _, _, _, _, _ = integrated
    plan = connection.prepare(**context)

    def forbidden(*unused):
        raise AssertionError("Disabled executor reached a native owner")

    output = tmp_path / "existing-stage-root"
    result = await execute_local_edit_once(
        connection,
        plan,
        expected_plan_sha256=digest(plan),
        output_root=output,
        read_context=forbidden,
        write_requests=forbidden,
    )
    assert result["status"] == "LOCAL_EDIT_WRITE_DISABLED"
    assert not output.exists()


@pytest.mark.asyncio
async def test_existing_receipts_guard_one_native_batch_and_exact_replay(
    integrated, tmp_path
):
    connection, context, _, _, _, _, _ = integrated
    plan = connection.prepare(**context)
    output = tmp_path / "existing-stage-root"
    current = {"raw": context["raw"]}
    writes = []

    def read():
        return {
            "raw": current["raw"],
            "current": context["current"],
            "pin_binding": context["pin_binding"],
        }

    def write(book, requests):
        receipts = sorted((output / digest(plan)).glob("receipt-*.json"))
        assert json.loads(receipts[-1].read_text(encoding="utf-8"))["status"] == "SENDING"
        assert book == "fictional-book" and len(requests) == 1
        update = requests[0]["updateCells"]
        assert update["start"] == {"sheetId": 2, "rowIndex": 5, "columnIndex": 2}
        assert update["fields"] == "userEnteredValue,note"
        state = native._state(current["raw"])
        state["sheets"][2]["cells"]["5:2"].update(update["rows"][0]["values"][0])
        current["raw"] = raw_from_state(state)
        writes.append(copy.deepcopy(requests))

    for _ in range(2):
        result = await execute_local_edit_once(
            connection,
            plan,
            expected_plan_sha256=digest(plan),
            output_root=output,
            read_context=read,
            write_requests=write,
            enabled=True,
        )
        assert result["status"] == "PLANNED_OUTPUT_OBSERVED"
        assert result["retry_writes"] is result["publication_allowed"] is False
    assert len(writes) == 1
    assert len(list((output / digest(plan)).glob("receipt-*.json"))) == 3
    assert (
        json.loads(json.dumps(native._state(current["raw"])))
        == plan["transfer"]["after_state"]
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("working_id", [2, 10])
async def test_saved_wrapper_and_executor_reopen_without_resending(
    integrated, tmp_path, working_id
):
    connection, context, _, _, _, _, _ = integrated
    context["binding"]["sheets"]["Working"] = working_id
    context["binding"]["working_protection_id"] = 100 + working_id
    context["raw"] = initial_raw(context["baseline"], context["binding"])
    plan = connection.prepare(**context)
    expected = digest(plan)
    root = connection.files.private_directory(tmp_path / "existing-stage-root")
    session = connection.files.private_directory(root / expected)
    connection.files.write(session / "plan.json", plan)
    reopened = connection.files.load(session / "plan.json")
    assert reopened == plan and digest(reopened) == expected
    writes = []

    def write(book, requests):
        writes.append(book)
        state = native._state(context["raw"])
        update = requests[0]["updateCells"]
        state["sheets"][working_id]["cells"]["5:2"].update(
            update["rows"][0]["values"][0]
        )
        context["raw"] = raw_from_state(state)

    for _ in range(2):
        # Read plan/receipt bytes again to model a restarted process.
        reopened = connection.files.load(session / "plan.json")
        result = await execute_local_edit_once(
            connection,
            reopened,
            expected_plan_sha256=expected,
            output_root=root,
            read_context=lambda: context,
            write_requests=write,
            enabled=True,
        )
        assert result["status"] == "PLANNED_OUTPUT_OBSERVED"
        assert result["retry_writes"] is False
    assert writes == ["fictional-book"]


@pytest.mark.asyncio
async def test_destination_changed_after_send_intent_is_held_before_transport(
    integrated, tmp_path
):
    connection, context, _, _, _, _, _ = integrated
    plan = connection.prepare(**context)
    reads, writes = [], []

    def read():
        reads.append(True)
        if len(reads) == 2:
            state = native._state(context["raw"])
            state["sheets"][2]["cells"]["5:2"]["note"] = "Later teacher correction"
            context["raw"] = raw_from_state(state)
        return context

    result = await execute_local_edit_once(
        connection,
        plan,
        expected_plan_sha256=digest(plan),
        output_root=tmp_path / "existing-stage-root",
        read_context=read,
        write_requests=lambda *args: writes.append(args),
        enabled=True,
    )
    assert result["status"] == "HELD_BEFORE_SEND"
    assert len(reads) == 2 and writes == []


@pytest.mark.asyncio
@pytest.mark.parametrize("applied", [False, True])
async def test_lost_native_reply_never_resends_even_if_preimage_is_still_present(
    integrated, tmp_path, applied
):
    connection, context, _, _, _, _, _ = integrated
    plan = connection.prepare(**context)
    output = tmp_path / "existing-stage-root"
    current = {"raw": context["raw"]}
    calls = []

    def read():
        return {
            "raw": current["raw"],
            "current": context["current"],
            "pin_binding": context["pin_binding"],
        }

    def loses_reply(book, requests):
        calls.append(book)
        if applied:
            state = native._state(current["raw"])
            state["sheets"][2]["cells"]["5:2"].update(
                requests[0]["updateCells"]["rows"][0]["values"][0]
            )
            current["raw"] = raw_from_state(state)
        raise TimeoutError("Fictional native response was lost")

    result = await execute_local_edit_once(
        connection,
        plan,
        expected_plan_sha256=digest(plan),
        output_root=output,
        read_context=read,
        write_requests=loses_reply,
        enabled=True,
    )
    assert result["status"] == "UNCERTAIN_RECONCILIATION_REQUIRED"
    for reconcile in (False, True):
        result = await execute_local_edit_once(
            connection,
            plan,
            expected_plan_sha256=digest(plan),
            output_root=output,
            read_context=read,
            write_requests=loses_reply,
            enabled=not reconcile,
            reconcile_only=reconcile,
        )
        assert result["status"] == (
            "PLANNED_OUTPUT_OBSERVED"
            if applied
            else "UNCERTAIN_RECONCILIATION_REQUIRED"
        )
    assert calls == ["fictional-book"]


@pytest.mark.asyncio
async def test_authentication_revoked_after_durable_intent_is_known_not_sent(
    integrated, tmp_path, monkeypatch
):
    connection, context, domain, _, _, _, _ = integrated
    plan = connection.prepare(**context)
    writes = []
    original_write = connection.files.write

    def revoke(path, value):
        original_write(path, value)
        if value.get("status") == "SENDING":
            domain.source.csrf = "revoked"

    monkeypatch.setattr(connection.files, "write", revoke)
    result = await execute_local_edit_once(
        connection,
        plan,
        expected_plan_sha256=digest(plan),
        output_root=tmp_path / "existing-stage-root",
        read_context=lambda: context,
        write_requests=lambda *args: writes.append(args),
        enabled=True,
    )
    assert result["status"] == "HELD_BEFORE_SEND"
    assert writes == []
    assert result["sheets_write_requests"] == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("empty_scope", [False, True])
async def test_existing_unresolved_target_history_and_shared_lock_remain_authoritative(
    integrated, tmp_path, empty_scope
):
    connection, context, _, _, _, _, _ = integrated
    plan = connection.prepare(**context)
    root = connection.files.private_directory(tmp_path / "existing-stage-root")
    writes = []
    with connection.files.locked(root / ".participation-stage.lock"):
        with pytest.raises(Exception, match="ANOTHER_LOCAL_CHAIN_IS_RUNNING"):
            await execute_local_edit_once(
                connection,
                plan,
                expected_plan_sha256=digest(plan),
                output_root=root,
                read_context=lambda: context,
                write_requests=lambda *args: writes.append(args),
                enabled=True,
            )
    prior_plan = {
        "binding": plan["binding"],
        "items": [] if empty_scope else plan["items"],
    }
    prior = connection.files.private_directory(root / digest(prior_plan))
    connection.files.write(prior / "plan.json", prior_plan)
    connection.files.write(
        prior / "receipt-001.json", {"status": "UNKNOWN_HISTORICAL_PHASE"}
    )
    with pytest.raises(GradebookError, match="UNRESOLVED_NATIVE_TARGET_HISTORY"):
        await execute_local_edit_once(
            connection,
            plan,
            expected_plan_sha256=digest(plan),
            output_root=root,
            read_context=lambda: context,
            write_requests=lambda *args: writes.append(args),
            enabled=True,
        )
    assert writes == []


@pytest.mark.asyncio
async def test_malformed_prior_scope_is_held_before_any_native_callback(
    integrated, tmp_path
):
    connection, context, _, _, _, _, _ = integrated
    plan = connection.prepare(**context)
    root = connection.files.private_directory(tmp_path / "existing-stage-root")
    prior_plan = {"binding": {"course_id": "12"}, "items": []}
    prior = connection.files.private_directory(root / digest(prior_plan))
    connection.files.write(prior / "plan.json", prior_plan)

    def forbidden(*unused):
        raise AssertionError("Malformed historical scope reached native transport")

    with pytest.raises(GradebookError, match="PRIOR_OPERATION_SCOPE_UNKNOWN"):
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
async def test_timeout_after_send_intent_retains_uncertainty_without_resend(
    integrated, tmp_path
):
    connection, context, _, _, _, _, _ = integrated
    plan = connection.prepare(**context)
    output = tmp_path / "existing-stage-root"
    calls = []

    async def delayed(*unused):
        calls.append(True)
        await asyncio.sleep(10)

    with pytest.raises(GradebookError, match="NATIVE_EXECUTION_TIMED_OUT"):
        await execute_local_edit_once(
            connection,
            plan,
            expected_plan_sha256=digest(plan),
            output_root=output,
            read_context=lambda: context,
            write_requests=delayed,
            enabled=True,
            max_seconds=0.1,
        )
    receipts = sorted((output / digest(plan)).glob("receipt-*.json"))
    assert (
        json.loads(receipts[-1].read_text(encoding="utf-8"))["status"]
        == "UNCERTAIN_RECONCILIATION_REQUIRED"
    )
    result = await execute_local_edit_once(
        connection,
        plan,
        expected_plan_sha256=digest(plan),
        output_root=output,
        read_context=lambda: context,
        write_requests=delayed,
        enabled=True,
    )
    assert result["status"] == "UNCERTAIN_RECONCILIATION_REQUIRED"
    assert calls == [True]
