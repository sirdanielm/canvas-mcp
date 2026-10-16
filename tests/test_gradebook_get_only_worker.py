"""GET-only worker lifecycle with fictional HTTP and native Sheets transport."""

import asyncio
import copy
import json

import httpx
import pytest
from test_gradebook_native import initial_raw
from test_gradebook_worker_integration import (
    BINDINGS,
    INSTANCE,
    FictionalCanvas,
    FictionalGoogle,
    fixture_records,
    fixture_snapshot,
    literal,
    set_literal,
)

from canvas_mcp.gradebook.client import GradebookClient, GradebookError
from canvas_mcp.gradebook.model import digest
from canvas_mcp.gradebook.native import _state
from canvas_mcp.gradebook.store import Store
from canvas_mcp.gradebook.worker import GET_ACTION, RefreshWorker, queue_metadata, stamp


@pytest.fixture
async def scenario(tmp_path):
    old = {
        "core": fixture_snapshot(fixture_records(12, 101, 21, 10)),
        "advanced": fixture_snapshot(fixture_records(13, 201, 31, 12)),
    }
    raw = initial_raw(old["core"], BINDINGS["core"])
    raw["sheets"].extend(
        initial_raw(old["advanced"], BINDINGS["advanced"])["sheets"][:3]
    )
    set_literal(raw, 2, 6, 3, 20)
    edit = next(sheet for sheet in raw["sheets"] if sheet["properties"]["sheetId"] == 2)
    edit["data"][0]["rowData"][5]["values"][2]["note"] = "Teacher feedback retained"
    while len(edit["data"][0]["rowData"][0]["values"]) < 6:
        edit["data"][0]["rowData"][0]["values"].append({})
    edit["data"][0]["rowData"][0]["values"][5] = {
        "userEnteredValue": {"formulaValue": "=SUM(C6:C7)"},
        "note": "Preserve helper formula and note",
    }
    google = FictionalGoogle(raw)
    request = google.enqueue()
    store = Store(tmp_path)
    for baseline in old.values():
        store.save("snapshot", baseline)
    source = FictionalCanvas()
    records = source.records["12"]
    additional = copy.deepcopy(records["enrollments"][0])
    additional["user_id"] = additional["user"]["id"] = 102
    additional["user"]["name"] = "Fictional Additional Student"
    records["enrollments"].append(additional)
    assignment = copy.deepcopy(records["assignments"][0])
    assignment.update(id=22, name="Fictional Additional Activity", position=2)
    records["assignments"].append(assignment)
    client = GradebookClient(
        "https://school.example", "fictional-token", httpx.MockTransport(source.handle)
    )
    worker = RefreshWorker(google, client, store, BINDINGS, INSTANCE, get_only=True)
    try:
        yield worker, google, source, request, old
    finally:
        await client.close()


async def test_get_only_worker_preserves_all_edit_fields_and_original_baseline(
    scenario,
):
    worker, google, source, request, old = scenario
    before = _state(google.raw)
    baseline_ids = {
        course: literal(google.raw, binding["sheets"]["_Sync"], 2, 2)
        for course, binding in BINDINGS.items()
    }

    result = await worker.step()

    assert result["state"] == "VERIFIED"
    assert result["canvas_writes"] == 0
    assert result["summary"]["core"] == {
        "students": 2,
        "assignments": 2,
        "pending_edits": None,
        "edit_preserved": True,
    }
    assert source.requests and all(r.method == "GET" for r in source.requests)
    after = _state(google.raw)
    for course, binding in BINDINGS.items():
        sid = binding["sheets"]["Working"]
        assert after["sheets"][sid] == before["sheets"][sid]
        sync = binding["sheets"]["_Sync"]
        assert literal(google.raw, sync, 2, 2) == baseline_ids[course]
        assert worker.store.load("snapshot", baseline_ids[course]) == old[course]
        assert literal(google.raw, sync, 9, 2) != baseline_ids[course]
    assert after["sheets"][4] == before["sheets"][4]
    assert literal(google.raw, 1, 6, 3) == 18
    assert literal(google.raw, 2, 6, 3) == 20
    assert literal(google.raw, 1, 7, 1) == "102"
    assert literal(google.raw, 1, 5, 4) == "22"
    assert len(google.grade_batches) == 1
    written = {
        r["updateCells"]["start"]["sheetId"]
        for r in google.grade_batches[0]
        if "updateCells" in r
    }
    assert written == {1, 3, 5, 7}
    operation = worker.journal.get(request["id"])
    manifest = worker.store.load("refresh", operation["payload"]["manifest_id"])
    assert manifest["refresh_mode"] == "GET_ONLY"
    assert not set(queue_metadata(google.raw)) & {"request", "claim", "applied"}


async def test_get_only_lost_response_after_commit_verifies_without_resending(scenario):
    worker, google, source, request, _ = scenario
    before_edit = _state(google.raw)["sheets"][2]
    google.lose_after_commit = True

    assert (await worker.step())["state"] == "VERIFIED"
    assert len(google.grade_batches) == 1
    assert _state(google.raw)["sheets"][2] == before_edit
    calls = len(source.requests)
    # Recovery honors the saved manifest mode, regardless of current CLI mode.
    restarted = RefreshWorker(google, worker.canvas, worker.store, BINDINGS, INSTANCE)
    assert (await restarted.step())["state"] == "IDLE"
    assert restarted.journal.get(request["id"])["status"] == "VERIFIED"
    assert len(google.grade_batches) == 1
    assert len(source.requests) == calls


async def test_get_only_restart_reconciles_saved_mode_after_readback_timeout(scenario):
    worker, google, source, request, _ = scenario
    before_edit = _state(google.raw)["sheets"][2]
    original_read = google.read_workbook
    fail_readback = True

    async def interrupted_readback():
        nonlocal fail_readback
        if google.grade_batches and fail_readback:
            fail_readback = False
            raise TimeoutError("Fictional readback timeout")
        return await original_read()

    google.read_workbook = interrupted_readback
    google.lose_after_commit = True
    with pytest.raises(GradebookError, match="stopped safely"):
        await worker.step()
    assert worker.journal.get(request["id"])["status"] == "UNCERTAIN"
    calls = len(source.requests)
    # A restarted full-sync process must select the persisted GET-only verifier.
    restarted = RefreshWorker(google, worker.canvas, worker.store, BINDINGS, INSTANCE)
    assert (await restarted.step())["state"] == "VERIFIED"
    assert _state(google.raw)["sheets"][2] == before_edit
    assert len(google.grade_batches) == 1
    assert len(source.requests) == calls


async def test_get_only_uncertain_before_commit_never_retransmits(scenario):
    worker, google, source, request, _ = scenario
    before = _state(google.raw)
    google.fail_before_commit = True

    assert (await worker.step())["state"] == "UNCERTAIN"
    assert _state(google.raw) == before
    calls = len(source.requests)
    restarted = RefreshWorker(google, worker.canvas, worker.store, BINDINGS, INSTANCE)
    assert (await restarted.step())["state"] == "UNCERTAIN"
    assert len(google.grade_batches) == 1
    assert len(source.requests) == calls
    assert restarted.journal.get(request["id"])["status"] == "UNCERTAIN"
    assert set(queue_metadata(google.raw)) >= {"request", "claim", "status"}


async def test_get_only_edit_note_changed_after_commit_blocks_verification(scenario):
    worker, google, _, _, _ = scenario
    original_batch = google.batch

    async def corrupt_after_commit(requests):
        result = await original_batch(requests)
        if any("updateCells" in r for r in requests):
            edit = next(
                sheet
                for sheet in google.raw["sheets"]
                if sheet["properties"]["sheetId"] == 2
            )
            edit["data"][0]["rowData"][5]["values"][2]["note"] = "Changed feedback"
        return result

    google.batch = corrupt_after_commit
    assert (await worker.step())["state"] == "UNCERTAIN"
    assert (await worker.step())["state"] == "UNCERTAIN"
    assert len(google.grade_batches) == 1


async def test_prepared_get_only_restart_cannot_upgrade_to_full_sync(scenario):
    worker, google, source, request, _ = scenario
    # Make the workbook otherwise eligible for full sync: the mode guard must
    # prevent feedback loss even when no unrelated schema guard would help.
    edit = next(s for s in google.raw["sheets"] if s["properties"]["sheetId"] == 2)
    edit["data"][0]["rowData"][0]["values"][5] = {}
    source.records["12"]["enrollments"] = source.records["12"]["enrollments"][:1]
    source.records["12"]["assignments"] = source.records["12"]["assignments"][:1]
    before_edit = copy.deepcopy(_state(google.raw)["sheets"][2])
    original_read = google.read_workbook
    interrupted = False

    async def interrupt_before_send():
        nonlocal interrupted
        if google.reads == 1 and not interrupted:
            interrupted = True
            raise asyncio.CancelledError()
        return await original_read()

    google.read_workbook = interrupt_before_send
    with pytest.raises(asyncio.CancelledError):
        await worker.step()
    operation = worker.journal.get(request["id"])
    assert operation["status"] == "PREPARED"
    manifest_id = operation["payload"]["manifest_id"]
    assert worker.store.load("refresh", manifest_id)["refresh_mode"] == "GET_ONLY"
    calls = len(source.requests)

    restarted = RefreshWorker(google, worker.canvas, worker.store, BINDINGS, INSTANCE)
    with pytest.raises(GradebookError, match="stopped safely"):
        await restarted.step()

    held = restarted.journal.get(request["id"])
    assert held["status"] == "HELD"
    assert held["payload"]["manifest_id"] == manifest_id
    assert "Refresh mode differs" in held["payload"]["failure_reason"]
    assert not google.grade_batches
    assert len(source.requests) == calls
    assert _state(google.raw)["sheets"][2] == before_edit


def use_get_action(google, request):
    request["action"] = GET_ACTION
    for item in google.raw["developerMetadata"]:
        if item["metadataKey"].endswith("request.v1"):
            item["metadataValue"] = json.dumps(request)


def remove_mode_pin(worker, request):
    with worker.journal.connect() as db:
        operation = worker.journal.get(request["id"])
        payload = operation["payload"]
        payload.pop("refresh_mode_schema", None)
        payload.pop("refresh_mode", None)
        db.execute(
            "UPDATE operations SET payload=? WHERE id=?",
            (json.dumps(payload), request["id"]),
        )


async def test_mode_is_durable_before_first_outbound_claim(scenario):
    worker, google, _, request, _ = scenario
    original_batch = google.batch
    observed = []

    async def inspect_claim(requests):
        for item in requests:
            metadata = item.get("createDeveloperMetadata", {}).get("developerMetadata", {})
            if metadata.get("metadataKey", "").endswith("claim.v1"):
                payload = worker.journal.get(request["id"])["payload"]
                observed.append((payload["refresh_mode_schema"], payload["refresh_mode"]))
        return await original_batch(requests)

    google.batch = inspect_claim
    assert (await worker.step())["state"] == "VERIFIED"
    assert observed == [(1, "GET_ONLY")]


async def test_claimed_get_only_restart_cannot_switch_mode(scenario):
    worker, google, source, request, _ = scenario
    original_read = google.read_workbook
    interrupted = False

    async def interrupt_initial_capture():
        nonlocal interrupted
        if not interrupted:
            interrupted = True
            raise asyncio.CancelledError()
        return await original_read()

    google.read_workbook = interrupt_initial_capture
    with pytest.raises(asyncio.CancelledError):
        await worker.step()
    operation = worker.journal.get(request["id"])
    assert operation["status"] == "CLAIMED"
    assert operation["payload"]["refresh_mode"] == "GET_ONLY"
    assert "manifest_id" not in operation["payload"]
    restarted = RefreshWorker(google, worker.canvas, worker.store, BINDINGS, INSTANCE)
    with pytest.raises(GradebookError, match="stopped safely"):
        await restarted.step()
    assert restarted.journal.get(request["id"])["status"] == "HELD"
    assert not google.grade_batches
    assert not source.requests


async def test_new_get_request_is_rejected_by_full_worker_before_claim(scenario):
    worker, google, source, request, _ = scenario
    use_get_action(google, request)
    full = RefreshWorker(google, worker.canvas, worker.store, BINDINGS, INSTANCE)
    with pytest.raises(GradebookError, match="requires a GET-only worker"):
        await full.step()
    assert full.journal.get(request["id"]) is None
    assert "claim" not in queue_metadata(google.raw)
    assert not google.grade_batches
    assert not source.requests
    # Wrong composition leaves the request usable by the correct worker.
    assert (await worker.step())["state"] == "VERIFIED"


async def test_new_get_request_post_send_recovery_is_mode_independent(scenario):
    worker, google, _, request, _ = scenario
    use_get_action(google, request)
    original_read = google.read_workbook
    interrupted = False

    async def interrupt_readback():
        nonlocal interrupted
        if google.grade_batches and not interrupted:
            interrupted = True
            raise asyncio.CancelledError()
        return await original_read()

    google.read_workbook = interrupt_readback
    with pytest.raises(asyncio.CancelledError):
        await worker.step()
    assert worker.journal.get(request["id"])["status"] == "VERIFYING"
    restarted = RefreshWorker(google, worker.canvas, worker.store, BINDINGS, INSTANCE)
    assert (await restarted.step())["state"] == "VERIFIED"
    assert len(google.grade_batches) == 1


async def test_heartbeat_advertises_refresh_mode(scenario):
    worker, google, _, _, _ = scenario
    await worker.heartbeat()
    assert queue_metadata(google.raw)["heartbeat"]["value"]["refresh_mode"] == "GET_ONLY"
    full = RefreshWorker(google, worker.canvas, worker.store, BINDINGS, INSTANCE)
    await full.heartbeat()
    assert queue_metadata(google.raw)["heartbeat"]["value"]["refresh_mode"] == "FULL_SYNC"


async def test_unversioned_prepared_manifest_remains_authoritative(scenario):
    worker, google, _, request, _ = scenario
    original_read = google.read_workbook
    interrupted = False

    async def interrupt_before_send():
        nonlocal interrupted
        if google.reads == 1 and not interrupted:
            interrupted = True
            raise asyncio.CancelledError()
        return await original_read()

    google.read_workbook = interrupt_before_send
    with pytest.raises(asyncio.CancelledError):
        await worker.step()
    remove_mode_pin(worker, request)
    operation = worker.journal.get(request["id"])
    assert worker._operation_mode(operation) == "GET_ONLY"
    restarted = RefreshWorker(google, worker.canvas, worker.store, BINDINGS, INSTANCE, get_only=True)
    assert (await restarted.step())["state"] == "VERIFIED"
    assert len(google.grade_batches) == 1


async def test_true_legacy_claimed_operation_defaults_full_sync(scenario):
    worker, google, source, request, _ = scenario
    original_read = google.read_workbook
    interrupted = False

    async def interrupt_initial_capture():
        nonlocal interrupted
        if not interrupted:
            interrupted = True
            raise asyncio.CancelledError()
        return await original_read()

    google.read_workbook = interrupt_initial_capture
    with pytest.raises(asyncio.CancelledError):
        await worker.step()
    remove_mode_pin(worker, request)
    operation = worker.journal.get(request["id"])
    assert worker._operation_mode(operation) == "FULL_SYNC"
    with pytest.raises(GradebookError, match="stopped safely"):
        await worker.step()
    assert not google.grade_batches
    assert not source.requests


def precreate_request_intent(worker, google, request, *, send_state="SENDING", attempted=None):
    use_get_action(google, request)
    metadata_id = queue_metadata(google.raw)["request"]["metadata_id"]
    operation = worker.journal.create(request, metadata_id, refresh_mode="GET_ONLY")
    receipt = {
        "request_intent_schema": 1, "request": copy.deepcopy(request),
        "metadata_id": metadata_id, "refresh_mode": "GET_ONLY",
        "binding_digest": digest(BINDINGS), "workbook_id": worker.workbook_id,
        "created_at": stamp(), "canvas_writes": 0,
    }
    receipt_id, _ = worker.store.save("receipt", receipt)
    # Model the helper's pre-POST durable intent; this journal self-update is
    # the intended new production API, so no independent second ledger exists.
    patch = {
        "request_intent_schema": 1, "request_intent_receipt_id": receipt_id,
        "request_send_state": send_state,
    }
    if attempted is not None:
        patch["claim_send_attempted"] = attempted
    worker.journal.update(operation["id"], "CLAIMING", **patch)
    return receipt


@pytest.mark.parametrize("send_state", ["SENDING", "CONFIRMED"])
async def test_precreated_cli_request_intent_can_claim_once(scenario, send_state):
    worker, google, _, request, _ = scenario
    precreate_request_intent(worker, google, request, send_state=send_state)
    original_batch = google.batch
    claims = []

    async def observe_claim(requests):
        for item in requests:
            metadata = item.get("createDeveloperMetadata", {}).get("developerMetadata", {})
            if metadata.get("metadataKey", "").endswith("claim.v1"):
                assert worker.journal.get(request["id"])["payload"]["claim_send_attempted"] is True
                claims.append(metadata)
        return await original_batch(requests)

    google.batch = observe_claim
    assert (await worker.step())["state"] == "VERIFIED"
    assert len(claims) == 1
    assert len(google.grade_batches) == 1


async def test_request_intent_unknown_claim_attempt_never_retries(scenario):
    worker, google, source, request, _ = scenario
    precreate_request_intent(worker, google, request, attempted=True)
    calls = []
    original_batch = google.batch

    async def capture_post(requests):
        calls.append(requests)
        return await original_batch(requests)

    google.batch = capture_post
    with pytest.raises(GradebookError, match="claim outcome requires reconciliation"):
        await worker.step()
    assert worker.journal.get(request["id"])["status"] == "HELD"
    assert not calls
    assert not google.grade_batches
    assert not source.requests
    assert (await worker.step())["state"] == "HELD"
    assert not calls


async def test_cancelled_claim_post_retains_no_retry_checkpoint(scenario):
    worker, google, source, request, _ = scenario
    precreate_request_intent(worker, google, request)
    original_batch = google.batch

    async def cancel_claim(requests):
        if any(r.get("createDeveloperMetadata", {}).get("developerMetadata", {}).get("metadataKey", "").endswith("claim.v1") for r in requests):
            raise asyncio.CancelledError()
        return await original_batch(requests)

    google.batch = cancel_claim
    with pytest.raises(asyncio.CancelledError):
        await worker.step()
    operation = worker.journal.get(request["id"])
    assert operation["status"] == "CLAIMING"
    assert operation["payload"]["claim_send_attempted"] is True
    assert "claim" not in queue_metadata(google.raw)
    google.batch = original_batch
    with pytest.raises(GradebookError, match="claim outcome requires reconciliation"):
        await worker.step()
    assert worker.journal.get(request["id"])["status"] == "HELD"
    assert not google.grade_batches
    assert not source.requests


@pytest.mark.parametrize("change", ["request", "metadata_id", "full_mode", "receipt"])
async def test_intent_takeover_rejects_conflicting_scope_without_posts(scenario, change):
    worker, google, source, request, _ = scenario
    receipt = precreate_request_intent(worker, google, request)
    if change == "request":
        item = next(m for m in google.raw["developerMetadata"] if m["metadataKey"].endswith("request.v1"))
        altered = json.loads(item["metadataValue"])
        altered["created_at"] = stamp()
        item["metadataValue"] = json.dumps(altered)
    elif change == "metadata_id":
        next(m for m in google.raw["developerMetadata"] if m["metadataKey"].endswith("request.v1"))["metadataId"] += 1
    elif change == "receipt":
        receipt["binding_digest"] = "0" * 64
        rid, _ = worker.store.save("receipt", receipt)
        worker.journal.update(request["id"], "CLAIMING", request_intent_receipt_id=rid)
    else:
        worker = RefreshWorker(google, worker.canvas, worker.store, BINDINGS, INSTANCE)
    calls = []
    original_batch = google.batch

    async def capture_post(requests):
        calls.append(requests)
        return await original_batch(requests)

    google.batch = capture_post
    with pytest.raises(GradebookError):
        await worker.step()
    assert not calls
    assert not google.grade_batches
    assert not source.requests


async def test_absent_remote_intent_requires_explicit_release_and_blocks_late_arrival(scenario):
    worker, google, source, request, _ = scenario
    precreate_request_intent(worker, google, request)
    original_request = copy.deepcopy(google.raw["developerMetadata"])
    google.raw["developerMetadata"] = []
    with pytest.raises(GradebookError, match="Unresolved refresh"):
        await worker.step()
    assert (await worker.release_held(request["id"]))["state"] == "RELEASED"
    operation = worker.journal.get(request["id"])
    assert operation["payload"]["release_reason"] == "UNCLAIMED_REQUEST_INTENT_ABSENT_REMOTE"
    assert "request_intent_receipt_id" in operation["payload"]
    assert (await worker.step())["state"] == "IDLE"
    google.raw["developerMetadata"] = original_request
    with pytest.raises(GradebookError, match="arrived late"):
        await worker.step()
    assert worker.journal.get(request["id"])["status"] == "RELEASED"
    assert not google.grade_batches
    assert not source.requests


@pytest.mark.parametrize("obstruction", ["attempted", "manifest", "applied"])
async def test_absent_remote_release_never_discards_attempted_claim_or_data_intent(scenario, obstruction):
    worker, google, _, request, _ = scenario
    precreate_request_intent(worker, google, request)
    google.raw["developerMetadata"] = []
    if obstruction == "attempted":
        worker.journal.update(request["id"], "CLAIMING", claim_send_attempted=True)
    elif obstruction == "manifest":
        worker.journal.update(request["id"], "CLAIMING", manifest_id="0" * 64)
    else:
        from canvas_mcp.gradebook.worker import metadata_create
        google.raw["developerMetadata"].append(metadata_create("applied", {"v": 1})["createDeveloperMetadata"]["developerMetadata"])
    with pytest.raises(GradebookError):
        await worker.release_held(request["id"])
    assert worker.journal.get(request["id"])["status"] == "CLAIMING"
    assert not google.grade_batches
