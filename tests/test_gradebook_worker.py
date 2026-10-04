"""Synthetic coordination failures: no real credentials or external systems."""

import copy
import json
import uuid
from datetime import UTC, datetime, timedelta

import pytest

from canvas_mcp.gradebook.client import GradebookError
from canvas_mcp.gradebook.model import digest
from canvas_mcp.gradebook.store import Store
from canvas_mcp.gradebook.worker import (
    IDS,
    KEYS,
    RefreshJournal,
    RefreshWorker,
    metadata_create,
    queue_metadata,
    stamp,
)

WORKBOOK = "fictional-workbook"
INSTANCE = "11111111-1111-1111-1111-111111111111"
BINDINGS = {
    c: {
        "spreadsheet_id": WORKBOOK,
        "course_id": str(i),
        "sheets": {"Canvas": i, "Working": i + 2, "_Sync": i + 4},
    }
    for c, i in [("core", 1), ("advanced", 2)]
}


def request():
    return {
        "v": 1,
        "id": str(uuid.uuid4()),
        "workbook_id": WORKBOOK,
        "action": "REFRESH_BOTH",
        "created_at": stamp(),
    }


class Google:
    def __init__(self, req):
        item = metadata_create("request", req)["createDeveloperMetadata"][
            "developerMetadata"
        ]
        item["metadataId"] = 99
        self.raw = {
            "spreadsheetId": WORKBOOK,
            "developerMetadata": [item],
            "state": 0,
            "sheets": [
                {"properties": {"sheetId": n, "gridProperties": {"columnCount": 40}}}
                for n in [1, 2]
            ],
        }
        self.grade_calls = 0
        self.reads = 0
        self.after_write_timeout = False
        self.before_write_timeout = False
        self.changed_preflight = False
        self.corrupt_readback = False
        self.cleanup_timeout = False
        self.cleanup_after_timeout = False

    async def metadata(self):
        return copy.deepcopy(self.raw)

    async def read_workbook(self):
        self.reads += 1
        result = copy.deepcopy(self.raw)
        if self.changed_preflight and self.reads == 2:
            result["state"] = 7
        if self.corrupt_readback and self.grade_calls:
            result["state"] = 8
        return result

    async def send_preflighted_batch(self, requests):
        return await self.batch(requests)

    async def batch(self, requests):
        is_grade = any("updateCells" in r for r in requests)
        if is_grade:
            self.grade_calls += 1
            if self.before_write_timeout:
                raise TimeoutError("synthetic transport failure")
        if self.cleanup_timeout and any(
            "deleteDeveloperMetadata" in r for r in requests
        ):
            self.cleanup_timeout = False
            raise TimeoutError("synthetic cleanup interruption")
        new = copy.deepcopy(self.raw)
        for r in requests:
            if "createDeveloperMetadata" in r:
                item = r["createDeveloperMetadata"]["developerMetadata"]
                if any(
                    x["metadataId"] == item["metadataId"]
                    for x in new["developerMetadata"]
                ):
                    raise GradebookError("Duplicate metadata ID")
                new["developerMetadata"].append(copy.deepcopy(item))
            elif "updateDeveloperMetadata" in r:
                update = r["updateDeveloperMetadata"]
                mid = update["dataFilters"][0]["developerMetadataLookup"]["metadataId"]
                for item in new["developerMetadata"]:
                    if item["metadataId"] == mid:
                        item.update(update["developerMetadata"])
            elif "deleteDeveloperMetadata" in r:
                mid = r["deleteDeveloperMetadata"]["dataFilter"][
                    "developerMetadataLookup"
                ]["metadataId"]
                new["developerMetadata"] = [
                    x for x in new["developerMetadata"] if x["metadataId"] != mid
                ]
            elif "updateCells" in r:
                new["state"] = 42
            elif "updateSheetProperties" in r:
                props = r["updateSheetProperties"]["properties"]
                assert (
                    props["gridProperties"]["columnCount"] >= 40
                ), "Never shrink existing columns"
        self.raw = new
        if self.cleanup_after_timeout and any(
            "deleteDeveloperMetadata" in r for r in requests
        ):
            self.cleanup_after_timeout = False
            raise TimeoutError("synthetic response lost after cleanup")
        if is_grade and self.after_write_timeout:
            raise TimeoutError("synthetic response lost after commit")
        return {}


@pytest.fixture
def setup(tmp_path, monkeypatch):
    from canvas_mcp.gradebook import native, service

    req = request()
    google = Google(req)
    store = Store(tmp_path)
    snapshot_id, _ = store.save(
        "snapshot",
        {"students": [{"id": "fictional"}], "assignments": [{"id": "fictional"}]},
    )
    fail = {"course": None}

    async def prepare(client, store, course, binding, cells):
        if fail["course"] == course:
            raise GradebookError("Synthetic unavailable baseline")
        return {
            "created_at": stamp(),
            "canvas_snapshot_id": snapshot_id,
            "pending_edits": [],
            "batch_update": {
                "requests": [
                    {
                        "updateCells": {
                            "start": {"sheetId": binding["sheets"]["Canvas"]},
                            "rows": [],
                        }
                    },
                    {
                        "updateSheetProperties": {
                            "properties": {
                                "sheetId": binding["sheets"]["Canvas"],
                                "gridProperties": {"columnCount": 26},
                            },
                            "fields": "gridProperties.columnCount",
                        }
                    },
                ]
            },
        }

    monkeypatch.setattr(service, "prepare_refresh", prepare)
    monkeypatch.setattr(
        native, "validate_workbook", lambda raw, bindings: {c: {} for c in bindings}
    )
    monkeypatch.setattr(
        native,
        "fingerprint",
        lambda raw: digest({"sheets": raw["sheets"], "state": raw["state"]}),
    )

    def verify(before, after, plans, store, bindings):
        if after["state"] != 42:
            raise GradebookError("Synthetic complete-output mismatch")

    monkeypatch.setattr(native, "verify_native_output", verify)
    worker = RefreshWorker(google, object(), store, BINDINGS, INSTANCE)
    return worker, google, req, fail


@pytest.mark.asyncio
async def test_both_courses_one_batch_verified_and_queue_retired(setup):
    worker, google, req, _ = setup
    result = await worker.step()
    assert result["state"] == "VERIFIED"
    assert google.grade_calls == 1
    assert worker.journal.get(req["id"])["status"] == "VERIFIED"
    assert set(queue_metadata(google.raw)) == {"status"}
    assert await worker.step() == {"state": "IDLE", "canvas_writes": 0}
    assert google.grade_calls == 1


@pytest.mark.asyncio
async def test_second_course_hold_writes_neither_course(setup):
    worker, google, req, fail = setup
    fail["course"] = "advanced"
    with pytest.raises(GradebookError):
        await worker.step()
    assert google.grade_calls == 0
    assert worker.journal.get(req["id"])["status"] == "HELD"
    assert (await worker.step())["state"] == "HELD"


@pytest.mark.asyncio
async def test_changed_native_input_holds_before_grade_write(setup):
    worker, google, req, _ = setup
    google.changed_preflight = True
    with pytest.raises(GradebookError):
        await worker.step()
    assert google.grade_calls == 0
    assert worker.journal.get(req["id"])["status"] == "HELD"


async def test_changed_input_records_safe_reason_and_stage_without_send(setup):
    worker, google, req, _ = setup
    google.changed_preflight = True
    with pytest.raises(GradebookError):
        await worker.step()
    payload = worker.journal.get(req["id"])["payload"]
    assert (
        payload["failure_reason"] == "Workbook changed while preparing; refresh held."
    )
    assert payload["failure_code"] == "workbook_changed"
    assert payload["failure_stage"] == "fresh_workbook"
    assert google.grade_calls == 0


async def test_expired_request_reason_is_retained_without_canvas_or_grade_send(setup):
    worker, google, req, _ = setup
    req["created_at"] = (datetime.now(UTC) - timedelta(minutes=11)).isoformat()
    google.raw["developerMetadata"][0]["metadataValue"] = json.dumps(req)
    assert (await worker.step())["state"] == "HELD"
    payload = worker.journal.get(req["id"])["payload"]
    assert payload["failure_code"] == "request_expired"
    assert (
        payload["failure_reason"]
        == "Refresh request expired; no grade data was replaced."
    )
    assert google.reads == 0 and google.grade_calls == 0


@pytest.mark.asyncio
async def test_lost_response_after_commit_reconciles_without_resend(setup):
    worker, google, _, _ = setup
    google.after_write_timeout = True
    assert (await worker.step())["state"] == "VERIFIED"
    assert google.grade_calls == 1


@pytest.mark.asyncio
async def test_uncertain_before_commit_never_retransmits_and_cannot_release(setup):
    worker, google, req, _ = setup
    google.before_write_timeout = True
    assert (await worker.step())["state"] == "UNCERTAIN"
    assert (await worker.step())["state"] == "UNCERTAIN"
    assert google.grade_calls == 1
    with pytest.raises(GradebookError, match="before SENDING"):
        await worker.release_held(req["id"])


@pytest.mark.asyncio
async def test_bad_readback_preserves_request_and_hold(setup):
    worker, google, req, _ = setup
    google.corrupt_readback = True
    assert (await worker.step())["state"] == "UNCERTAIN"
    assert set(queue_metadata(google.raw)) >= {"request", "claim", "applied"}
    assert worker.journal.get(req["id"])["status"] == "UNCERTAIN"
    assert google.grade_calls == 1


@pytest.mark.asyncio
async def test_cleanup_failure_restarts_without_rechecking_or_overwriting_later_edits(
    setup,
):
    worker, google, req, _ = setup
    google.cleanup_timeout = True
    with pytest.raises(GradebookError):
        await worker.step()
    assert worker.journal.get(req["id"])["status"] == "VERIFIED"
    google.raw["state"] = 100  # Teacher edits after successful grade readback.
    assert (await worker.step())["state"] == "VERIFIED"
    assert google.raw["state"] == 100
    assert google.grade_calls == 1


@pytest.mark.asyncio
async def test_foreign_claim_blocks_and_does_not_erase_it(setup):
    worker, google, req, _ = setup
    claim = metadata_create(
        "claim",
        {"v": 1, "id": req["id"], "owner": str(uuid.uuid4()), "workbook_id": WORKBOOK},
    )
    await google.batch([claim])
    with pytest.raises(GradebookError):
        await worker.step()
    assert google.grade_calls == 0
    assert "claim" in queue_metadata(google.raw)


@pytest.mark.asyncio
async def test_expired_request_is_durably_held_and_releasable_without_grade_change(
    setup,
):
    worker, google, req, _ = setup
    req["created_at"] = (datetime.now(UTC) - timedelta(hours=1)).isoformat()
    google.raw["developerMetadata"][0]["metadataValue"] = json.dumps(req)
    assert (await worker.step())["state"] == "HELD"
    assert (await worker.release_held(req["id"]))["state"] == "RELEASED"
    assert worker.journal.get(req["id"])["status"] == "RELEASED"
    assert google.grade_calls == 0
    assert (await worker.heartbeat())["state"] == "READY"


@pytest.mark.asyncio
async def test_local_lock_blocks_second_worker(setup):
    worker, google, _, _ = setup
    other = RefreshWorker(google, object(), worker.store, BINDINGS, INSTANCE)
    with (
        worker.journal.exclusive(),
        pytest.raises(GradebookError, match="Another local"),
    ):
        await other.step()
    assert google.grade_calls == 0


@pytest.mark.parametrize(
    "mutation",
    [
        "duplicate",
        "private",
        "wrong_location",
        "reserved_collision",
        "extra_field",
        "boolean_version",
    ],
)
@pytest.mark.asyncio
async def test_untrusted_queue_cannot_select_another_operation(setup, mutation):
    worker, google, req, _ = setup
    item = google.raw["developerMetadata"][0]
    if mutation == "duplicate":
        google.raw["developerMetadata"].append(copy.deepcopy(item))
    elif mutation == "private":
        item["visibility"] = "PROJECT"
    elif mutation == "wrong_location":
        item["location"] = {"sheetId": 1}
    elif mutation == "reserved_collision":
        item["metadataKey"] = "unrelated"
        item["metadataId"] = IDS["claim"]
    elif mutation == "boolean_version":
        req["v"] = True
        item["metadataValue"] = json.dumps(req)
    else:
        req["url"] = "https://attacker.invalid"
        item["metadataValue"] = json.dumps(req)
    with pytest.raises(GradebookError):
        await worker.step()
    assert google.grade_calls == 0


def test_journal_prevents_sending_retry_and_private_files(tmp_path):
    journal = RefreshJournal(tmp_path, WORKBOOK)
    req = request()
    journal.create(req, 1)
    journal.update(req["id"], "CLAIMED")
    journal.update(req["id"], "PREPARED")
    journal.update(req["id"], "SENDING")
    with pytest.raises(GradebookError):
        journal.update(req["id"], "PREPARED")
    assert journal.path.stat().st_mode & 0o777 == 0o600


@pytest.mark.asyncio
async def test_cleanup_lost_response_is_confirmed_without_second_grade_batch(setup):
    worker, google, req, _ = setup
    google.cleanup_after_timeout = True
    assert (await worker.step())["state"] == "VERIFIED"
    assert worker.journal.get(req["id"])["payload"]["finalized"] is True
    google.raw["state"] = 100
    assert (await worker.reconcile(req["id"]))["state"] == "VERIFIED"
    assert google.raw["state"] == 100
    assert google.grade_calls == 1


@pytest.mark.asyncio
async def test_release_lost_response_is_confirmed_without_grade_write(setup):
    worker, google, req, fail = setup
    fail["course"] = "advanced"
    with pytest.raises(GradebookError):
        await worker.step()
    google.cleanup_after_timeout = True
    assert (await worker.release_held(req["id"]))["state"] == "RELEASED"
    assert worker.journal.get(req["id"])["payload"]["release_requested"] is True
    assert google.grade_calls == 0
    assert (await worker.step())["state"] == "IDLE"


@pytest.mark.asyncio
async def test_release_crash_after_cleanup_recovers_from_durable_intent(setup):
    worker, google, req, fail = setup
    fail["course"] = "advanced"
    with pytest.raises(GradebookError):
        await worker.step()
    worker.journal.update(req["id"], "HELD", release_requested=True)
    google.raw["developerMetadata"] = [
        m
        for m in google.raw["developerMetadata"]
        if m["metadataKey"] not in {KEYS["request"], KEYS["claim"]}
    ]
    assert (await worker.release_held(req["id"]))["state"] == "RELEASED"
    assert google.grade_calls == 0


@pytest.mark.asyncio
async def test_reconcile_cannot_start_a_new_operation(setup):
    worker, google, req, _ = setup
    with pytest.raises(GradebookError, match="previously attempted"):
        await worker.reconcile(req["id"])
    assert google.grade_calls == 0


@pytest.mark.asyncio
async def test_google_readonly_metadata_location_type_is_accepted(setup):
    worker, google, _, _ = setup
    google.raw["developerMetadata"][0]["location"]["locationType"] = "SPREADSHEET"
    assert (await worker.step())["state"] == "VERIFIED"


@pytest.mark.asyncio
async def test_copied_instance_does_not_adopt_another_journals_claim(setup, tmp_path):
    worker, google, req, _ = setup
    first = worker.journal.create(req, 99)
    claim = metadata_create(
        "claim",
        {
            "v": 1,
            "id": req["id"],
            "owner": INSTANCE,
            "nonce": first["payload"]["claim_nonce"],
            "workbook_id": WORKBOOK,
        },
    )
    await google.batch([claim])
    second = RefreshWorker(
        google, object(), Store(tmp_path / "different-store"), BINDINGS, INSTANCE
    )
    second.journal.create(req, 99)
    with pytest.raises(GradebookError, match="another worker"):
        await second.step()
    assert google.grade_calls == 0
