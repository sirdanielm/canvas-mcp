"""Sanctioned queue requests with fictional metadata and durable local intent."""

import asyncio
import copy
import json
import subprocess
import sys
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta

import pytest
from test_gradebook_worker_integration import BINDINGS, BOOK, INSTANCE

from canvas_mcp.gradebook import get_refresh_request as request_module
from canvas_mcp.gradebook.client import GradebookError
from canvas_mcp.gradebook.get_refresh_request import (
    MAX_METADATA_ID,
    request_get_refresh,
)
from canvas_mcp.gradebook.model import digest
from canvas_mcp.gradebook.store import Store
from canvas_mcp.gradebook.worker import (
    GET_ACTION,
    IDS,
    RefreshJournal,
    RefreshJournalBusy,
    metadata_create,
    stamp,
)


class HardCrash(BaseException):
    """Represent an interruption that cannot run exception cleanup."""


class Google:
    workbook_id = BOOK

    def __init__(self, store):
        self.store = store
        self.raw = {
            "spreadsheetId": BOOK,
            "sheets": [
                {"properties": {"sheetId": sid, "title": binding["tab_names"][role]}}
                for binding in BINDINGS.values()
                for role, sid in binding["sheets"].items()
            ],
            "developerMetadata": [],
        }
        self.posts = []
        self.reads = 0
        self.failure = None
        heartbeat = metadata_create(
            "heartbeat",
            {
                "v": 1,
                "state": "READY",
                "refresh_mode": "GET_ONLY",
                "workbook_id": BOOK,
                "updated_at": stamp(),
            },
        )["createDeveloperMetadata"]["developerMetadata"]
        self.raw["developerMetadata"].append(heartbeat)

    async def metadata(self):
        self.reads += 1
        if self.posts and self.failure == "readback":
            raise TimeoutError("fictional private response")
        return copy.deepcopy(self.raw)

    async def batch(self, requests):
        assert len(requests) == 1 and set(requests[0]) == {"createDeveloperMetadata"}
        item = requests[0]["createDeveloperMetadata"]["developerMetadata"]
        request = json.loads(item["metadataValue"])
        # The blocking intent row and immutable receipt precede any POST.
        operation = RefreshJournal(self.store.root, BOOK).get(request["id"])
        assert operation["status"] == "CLAIMING"
        assert operation["payload"]["request_send_state"] == "SENDING"
        assert operation["payload"]["refresh_mode"] == "GET_ONLY"
        receipt = self.store.load(
            "receipt", operation["payload"]["request_intent_receipt_id"]
        )
        assert receipt["request"] == request
        assert receipt["metadata_id"] == item["metadataId"]
        self.posts.append(copy.deepcopy(requests))
        if self.failure in {"before_commit", "crash_before_commit"}:
            if self.failure == "crash_before_commit":
                raise HardCrash
            raise TimeoutError("fictional private response")
        if self.failure == "cancel_before_commit":
            raise asyncio.CancelledError
        self.raw["developerMetadata"].append(copy.deepcopy(item))
        if self.failure == "wrong_readback_id":
            self.raw["developerMetadata"][-1]["metadataId"] += 1
        if self.failure == "after_commit":
            raise TimeoutError("fictional private response")
        if self.failure == "crash_after_commit":
            raise HardCrash
        return {}


@pytest.fixture
def scenario(tmp_path):
    store = Store(tmp_path)
    google = Google(store)
    return google, store, RefreshJournal(store.root, BOOK)


async def test_request_persists_intent_before_one_exact_metadata_post_and_deduplicates(
    scenario,
):
    google, store, journal = scenario
    result = await request_get_refresh(google, store, BINDINGS, INSTANCE)
    assert result["state"] == "QUEUED"
    assert result["canvas_writes"] == result["grade_writes"] == 0
    assert result["queue_write_verified"] is True
    assert result["retry_writes"] is False
    assert len(google.posts) == 1 and google.reads == 2
    item = google.posts[0][0]["createDeveloperMetadata"]["developerMetadata"]
    assert 0 < item["metadataId"] <= MAX_METADATA_ID
    assert item["metadataId"] not in IDS.values()
    assert item["location"] == {"spreadsheet": True}
    assert item["visibility"] == "DOCUMENT"
    request = json.loads(item["metadataValue"])
    assert request["action"] == GET_ACTION
    assert request["workbook_id"] == BOOK
    assert set(request) == {"v", "id", "action", "created_at", "workbook_id"}
    receipt = store.load("receipt", result["intent_receipt_id"])
    assert set(receipt) == {
        "request_intent_schema",
        "request",
        "metadata_id",
        "refresh_mode",
        "binding_digest",
        "workbook_id",
        "created_at",
        "canvas_writes",
    }
    assert receipt["binding_digest"] == digest(BINDINGS)
    operation = journal.get(request["id"])
    assert operation["payload"]["request_send_state"] == "CONFIRMED"
    repeated = await request_get_refresh(google, store, BINDINGS, INSTANCE)
    assert repeated["request_id"] == result["request_id"]
    assert repeated["state"] == "ALREADY_QUEUED"
    assert repeated["sheets_writes"] == 0
    assert len(google.posts) == 1


@pytest.mark.parametrize(
    "change", ["stale", "future", "busy", "mode", "workbook", "missing", "schema_bool"]
)
async def test_request_requires_fresh_ready_get_only_worker(scenario, change):
    google, store, journal = scenario
    item = google.raw["developerMetadata"][0]
    heartbeat = json.loads(item["metadataValue"])
    if change in {"stale", "future"}:
        heartbeat["updated_at"] = (
            datetime.now(UTC) + timedelta(seconds=-91 if change == "stale" else 31)
        ).isoformat()
    elif change == "busy":
        heartbeat["state"] = "BUSY"
    elif change == "mode":
        heartbeat["refresh_mode"] = "FULL_SYNC"
    elif change == "workbook":
        heartbeat["workbook_id"] = "another-book"
    elif change == "schema_bool":
        heartbeat["v"] = True
    else:
        google.raw["developerMetadata"] = []
    item["metadataValue"] = json.dumps(heartbeat)
    with pytest.raises(GradebookError):
        await request_get_refresh(google, store, BINDINGS, INSTANCE)
    assert google.posts == [] and journal.unresolved() == []


@pytest.mark.parametrize(
    "change", ["client_workbook", "response_workbook", "sheet_name", "course_inventory"]
)
async def test_request_rejects_wrong_fixed_scope(scenario, change):
    google, store, _ = scenario
    bindings = copy.deepcopy(BINDINGS)
    if change == "client_workbook":
        google.workbook_id = "another-book"
    elif change == "response_workbook":
        google.raw["spreadsheetId"] = "another-book"
    elif change == "sheet_name":
        google.raw["sheets"][0]["properties"]["title"] = "another-sheet"
    else:
        del bindings["advanced"]
    with pytest.raises(GradebookError):
        await request_get_refresh(google, store, bindings, INSTANCE)
    assert google.posts == []


async def test_existing_local_hold_blocks_new_queue_request(scenario):
    google, store, journal = scenario
    request = {
        "v": 1,
        "id": INSTANCE,
        "action": GET_ACTION,
        "created_at": stamp(),
        "workbook_id": BOOK,
    }
    journal.create(request, 99, refresh_mode="GET_ONLY")
    journal.update(INSTANCE, "HELD")
    with pytest.raises(GradebookError, match="Unresolved refresh"):
        await request_get_refresh(google, store, BINDINGS, INSTANCE)
    assert google.posts == []


async def test_local_worker_lock_blocks_request_before_google_access(scenario, monkeypatch):
    google, store, journal = scenario
    clock, pauses = [0.0], []
    monkeypatch.setattr(request_module, "monotonic", lambda: clock[0], raising=False)
    async def pause(seconds):
        assert google.reads == 0 and not google.posts and not journal.unresolved()
        clock[0] += seconds
        pauses.append(seconds)
    monkeypatch.setattr(request_module, "_admission_pause", pause, raising=False)
    with journal.exclusive():
        with pytest.raises(GradebookError, match="no request was created or sent"):
            await request_get_refresh(google, store, BINDINGS, INSTANCE)
    assert google.posts == [] and google.reads == 0
    assert clock[0] == 30 and all(0 < p <= 0.25 for p in pauses)
    assert not list(store.root.glob("receipt-*")) and not journal.unresolved()


async def test_busy_then_free_waits_before_every_google_call_and_sends_once(scenario, monkeypatch):
    google, store, journal = scenario
    clock, pauses = [0.0], []
    guard = journal.exclusive()
    guard.__enter__()
    released = False
    monkeypatch.setattr(request_module, "monotonic", lambda: clock[0], raising=False)
    async def pause(seconds):
        nonlocal released
        assert google.reads == 0 and not google.posts and not journal.unresolved()
        assert not list(store.root.glob("receipt-*"))
        pauses.append(seconds)
        clock[0] += seconds
        guard.__exit__(None, None, None)
        released = True
    monkeypatch.setattr(request_module, "_admission_pause", pause, raising=False)
    try:
        result = await request_get_refresh(google, store, BINDINGS, INSTANCE)
    finally:
        if not released:
            guard.__exit__(None, None, None)
    assert result["state"] == "QUEUED"
    assert len(pauses) == 1 and pauses[0] == 0.25
    assert google.reads == 2 and len(google.posts) == 1


async def test_real_other_process_lock_handoff_stays_pre_admission(scenario, monkeypatch):
    google, store, journal = scenario
    code = (
        "import fcntl,sys\n"
        "with open(sys.argv[1], 'a+') as lock:\n"
        " fcntl.flock(lock, fcntl.LOCK_EX)\n"
        " print('locked', flush=True)\n"
        " sys.stdin.readline()\n"
    )
    process = subprocess.Popen(
        [sys.executable, "-c", code, str(journal.lock)],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True,
    )
    monkeypatch.setattr(request_module, "LOCK_WAIT_SECONDS", 2.0)
    pauses = []
    async def pause(seconds):
        assert google.reads == 0 and not google.posts and not journal.unresolved()
        assert not list(store.root.glob("receipt-*"))
        pauses.append(seconds)
        process.stdin.write("release\n")
        process.stdin.flush()
        await asyncio.wait_for(asyncio.to_thread(process.wait), timeout=1.0)
    monkeypatch.setattr(request_module, "_admission_pause", pause)
    try:
        assert await asyncio.wait_for(
            asyncio.to_thread(process.stdout.readline), timeout=2.0
        ) == "locked\n"
        result = await request_get_refresh(google, store, BINDINGS, INSTANCE)
        assert result["state"] == "QUEUED" and len(pauses) == 1
        assert google.reads == 2 and len(google.posts) == 1
    finally:
        if process.poll() is None:
            process.kill()
        await asyncio.wait_for(asyncio.to_thread(process.wait), timeout=2.0)
        for stream in (process.stdin, process.stdout, process.stderr):
            stream.close()


@pytest.mark.parametrize("error_type", [GradebookError, OSError])
async def test_untyped_lock_errors_are_never_retried_or_sent(scenario, monkeypatch, error_type):
    google, store, journal = scenario
    attempts = []
    @contextmanager
    def fail(_):
        attempts.append(1)
        raise error_type("synthetic lock error")
        yield
    async def forbidden_pause(_):
        pytest.fail("Only typed contention can wait")
    monkeypatch.setattr(RefreshJournal, "exclusive", fail)
    monkeypatch.setattr(request_module, "_admission_pause", forbidden_pause, raising=False)
    with pytest.raises(error_type, match="synthetic lock error"):
        await request_get_refresh(google, store, BINDINGS, INSTANCE)
    assert attempts == [1] and google.reads == 0 and not google.posts
    assert not list(store.root.glob("receipt-*")) and not journal.unresolved()


async def test_body_typed_error_is_not_reinterpreted_as_admission_contention(scenario, monkeypatch):
    google, store, _ = scenario
    async def fail_metadata():
        google.reads += 1
        raise RefreshJournalBusy("synthetic body error")
    async def forbidden_pause(_):
        pytest.fail("The admitted request body must not retry")
    monkeypatch.setattr(google, "metadata", fail_metadata)
    monkeypatch.setattr(request_module, "_admission_pause", forbidden_pause, raising=False)
    with pytest.raises(RefreshJournalBusy, match="synthetic body error"):
        await request_get_refresh(google, store, BINDINGS, INSTANCE)
    assert google.reads == 1 and not google.posts


async def test_cancel_during_admission_creates_no_intent_and_does_not_retry(scenario, monkeypatch):
    google, store, journal = scenario
    pauses = []
    async def pause(seconds):
        pauses.append(seconds)
        raise asyncio.CancelledError
    monkeypatch.setattr(request_module, "_admission_pause", pause)
    with journal.exclusive():
        with pytest.raises(asyncio.CancelledError):
            await request_get_refresh(google, store, BINDINGS, INSTANCE)
    assert len(pauses) == 1 and google.reads == 0 and not google.posts
    assert not list(store.root.glob("receipt-*")) and not journal.unresolved()
    with journal.exclusive():
        pass  # Failed admission left no leaked lock descriptor.


async def test_lock_wait_does_not_weaken_fresh_heartbeat_gate(scenario, monkeypatch):
    google, store, journal = scenario
    guard = journal.exclusive()
    guard.__enter__()
    released = False
    async def pause(_):
        nonlocal released
        item = google.raw["developerMetadata"][0]
        heartbeat = json.loads(item["metadataValue"])
        heartbeat["updated_at"] = (datetime.now(UTC) - timedelta(seconds=91)).isoformat()
        item["metadataValue"] = json.dumps(heartbeat)
        guard.__exit__(None, None, None)
        released = True
    monkeypatch.setattr(request_module, "_admission_pause", pause)
    try:
        with pytest.raises(GradebookError, match="fresh READY"):
            await request_get_refresh(google, store, BINDINGS, INSTANCE)
    finally:
        if not released:
            guard.__exit__(None, None, None)
    assert google.reads == 1 and not google.posts
    assert not journal.unresolved() and not list(store.root.glob("receipt-*"))


@pytest.mark.parametrize("value", [True, 1.0, "1"])
async def test_existing_unresolved_mode_schema_requires_exact_integer(scenario, value):
    google, store, journal = scenario
    result = await request_get_refresh(google, store, BINDINGS, INSTANCE)
    operation = journal.get(result["request_id"])
    payload = operation["payload"]
    payload["refresh_mode_schema"] = value
    with journal.connect() as db:
        db.execute("UPDATE operations SET payload=? WHERE id=?",
                   (json.dumps(payload), result["request_id"]))
    with pytest.raises(GradebookError, match="Unresolved refresh"):
        await request_get_refresh(google, store, BINDINGS, INSTANCE)
    assert len(google.posts) == 1


async def test_lost_post_response_is_read_back_once_and_never_reposted(scenario):
    google, store, _ = scenario
    google.failure = "after_commit"
    result = await request_get_refresh(google, store, BINDINGS, INSTANCE)
    assert result["state"] == "QUEUED"
    assert result["queue_write_verified"] is True
    assert len(google.posts) == 1 and google.reads == 2


@pytest.mark.parametrize("failure", ["before_commit", "readback", "wrong_readback_id"])
async def test_uncertain_request_is_held_with_known_id_and_never_retried(
    scenario, failure
):
    google, store, journal = scenario
    google.failure = failure
    result = await request_get_refresh(google, store, BINDINGS, INSTANCE)
    assert result["state"] == "REQUEST_UNCERTAIN"
    assert result["retry_writes"] is False
    operation = journal.get(result["request_id"])
    assert operation["status"] == "HELD"
    assert operation["payload"]["refresh_mode"] == "GET_ONLY"
    assert (
        operation["payload"]["metadata_id"]
        == google.posts[0][0]["createDeveloperMetadata"]["developerMetadata"][
            "metadataId"
        ]
    )
    google.failure = None
    with pytest.raises(GradebookError, match="Unresolved refresh"):
        await request_get_refresh(google, store, BINDINGS, INSTANCE)
    assert len(google.posts) == 1


async def test_cancelled_request_keeps_durable_hold_without_resend(scenario):
    google, store, journal = scenario
    google.failure = "cancel_before_commit"
    with pytest.raises(asyncio.CancelledError):
        await request_get_refresh(google, store, BINDINGS, INSTANCE)
    unresolved = journal.unresolved()
    assert len(unresolved) == 1
    assert journal.get(unresolved[0])["status"] == "HELD"
    google.failure = None
    with pytest.raises(GradebookError, match="Unresolved refresh"):
        await request_get_refresh(google, store, BINDINGS, INSTANCE)
    assert len(google.posts) == 1


@pytest.mark.parametrize("failure", ["crash_before_commit", "crash_after_commit"])
async def test_hard_interruption_retains_blocking_intent_and_never_resends(
    scenario, failure
):
    google, store, journal = scenario
    google.failure = failure
    with pytest.raises(HardCrash):
        await request_get_refresh(google, store, BINDINGS, INSTANCE)
    request = json.loads(
        google.posts[0][0]["createDeveloperMetadata"]["developerMetadata"][
            "metadataValue"
        ]
    )
    operation = journal.get(request["id"])
    assert operation["status"] == "CLAIMING"
    assert operation["payload"]["request_send_state"] == "SENDING"
    google.failure = None
    if failure == "crash_after_commit":
        repeated = await request_get_refresh(google, store, BINDINGS, INSTANCE)
        assert repeated["request_id"] == request["id"]
    else:
        with pytest.raises(GradebookError, match="Unresolved refresh"):
            await request_get_refresh(google, store, BINDINGS, INSTANCE)
    assert len(google.posts) == 1


async def test_existing_full_sync_request_cannot_be_adopted_as_get_only(scenario):
    google, store, _ = scenario
    request = {
        "v": 1,
        "id": INSTANCE,
        "action": "REFRESH_BOTH",
        "created_at": stamp(),
        "workbook_id": BOOK,
    }
    item = metadata_create("request", request)["createDeveloperMetadata"][
        "developerMetadata"
    ]
    item["metadataId"] = 99
    google.raw["developerMetadata"].append(item)
    with pytest.raises(GradebookError, match="different mode"):
        await request_get_refresh(google, store, BINDINGS, INSTANCE)
    assert google.posts == []
