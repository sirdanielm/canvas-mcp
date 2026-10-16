"""Fictional diagnostics, privacy and strictly local read-only checks."""
import copy
import fcntl
import json
import os
import sqlite3
from datetime import UTC, datetime

import httpx
import pytest

from canvas_mcp.gradebook import diagnostics as module
from canvas_mcp.gradebook.client import GradebookClient, GradebookError
from canvas_mcp.gradebook.diagnostics import (
    Diagnostics,
    failure_code,
    inspect_journal,
    safe_record,
)
from canvas_mcp.gradebook.native import difference_categories

RID = "00000000-0000-4000-8000-000000000001"


@pytest.mark.parametrize("microsecond", [123456, 987123])
def test_allowlist_never_serializes_private_values(tmp_path, monkeypatch, microsecond):
    # Safe timestamps may contain the same digits as a fictional private ID.
    frozen = datetime(2026, 10, 15, 22, 44, 9, microsecond, tzinfo=UTC)

    class FrozenDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return frozen

    monkeypatch.setattr("canvas_mcp.gradebook.diagnostics.datetime", FrozenDateTime)
    log = tmp_path / "diagnostics.jsonl"
    diagnostic = Diagnostics(log)
    diagnostic.emit(
        "http",
        component="canvas",
        operation="get",
        request_id=RID,
        http_class="forbidden",
        duration_ms=12,
        token="private-token",
        url="https://private.invalid/student-123",
        headers={"Authorization": "private-token"},
        body="score=87",
        error="private-exception",
        student_id=123,
        grade=87,
    )
    diagnostic.emit("http", component="private-token", operation="private-url")
    rows = [json.loads(line) for line in log.read_text().splitlines()]
    assert rows == [
        {
            "v": 1,
            "event": "http",
            "at": frozen.isoformat(),
            "component": "canvas",
            "operation": "get",
            "request_id": RID,
            "http_class": "forbidden",
            "duration_ms": 12,
        },
        {"v": 1, "event": "http", "at": frozen.isoformat()},
    ]
    assert not any(
        value in log.read_text()
        for value in (
            "private",
            "score=87",
            "student_id",
            "Authorization",
            "grade",
            "student-123",
        )
    )
    assert log.stat().st_mode & 0o777 == 0o600


def test_failure_span_correlates_only_safe_code(tmp_path):
    diagnostic = Diagnostics(tmp_path / "diagnostics.jsonl")
    with pytest.raises(httpx.ReadTimeout):
        with diagnostic.stage("fresh_workbook", RID):
            raise httpx.ReadTimeout("token https://private.invalid student score")
    rows = [json.loads(line) for line in diagnostic.path.read_text().splitlines()]
    assert rows[-1]["request_id"] == RID
    assert rows[-1]["stage"] == "fresh_workbook"
    assert rows[-1]["failure_code"] == "transport_timeout"
    assert rows[-1]["duration_ms"] >= 0
    assert "private.invalid" not in diagnostic.path.read_text()


def test_logging_failure_cannot_interrupt_operation(tmp_path):
    target = tmp_path / "outside"
    target.write_text("preserve")
    log = tmp_path / "diagnostics.jsonl"
    log.symlink_to(target)
    diagnostic = Diagnostics(log)
    with diagnostic.stage("grade_batch", RID):
        diagnostic.emit("loop", state="HELD")
    assert target.read_text() == "preserve"
    assert diagnostic.dropped > 0


def test_absent_journal_does_not_create_store(tmp_path):
    state = tmp_path / "absent"
    result = inspect_journal(state, "fictional-workbook")
    assert result["state"] == "NO_LOCAL_HOLDS"
    assert result["journal_present"] is False
    assert not state.exists()
    assert result["worker_running"] == "unverified"


def test_live_local_activity_with_held_request_is_never_ready(tmp_path):
    root = tmp_path / "refresh-worker"
    root.mkdir(mode=0o700)
    path = root / "operations.sqlite3"
    now = datetime.now(UTC).isoformat()
    with sqlite3.connect(path) as db:
        db.execute(
            "CREATE TABLE operations (id TEXT PRIMARY KEY, workbook TEXT, status TEXT, payload TEXT, updated TEXT)"
        )
        db.execute(
            "INSERT INTO operations VALUES (?,?,?,?,?)",
            (
                RID,
                "fictional-workbook",
                "HELD",
                json.dumps(
                    {
                        "request": {"created_at": now},
                        "failure_reason": "Workbook changed while preparing; refresh held.",
                        "private": "token student score=87",
                    }
                ),
                now,
            ),
        )
    path.chmod(0o600)
    Diagnostics(root / "diagnostics.jsonl").emit("loop", state="HELD", request_id=RID)
    before = path.read_bytes()
    result = inspect_journal(tmp_path, "fictional-workbook")
    assert result["state"] == "HELD"
    assert result["recent_local_activity"] is True
    assert result["ready"] is False
    assert result["requests"][0]["request_id"] == RID
    assert result["requests"][0]["failure_code"] == "workbook_changed"
    assert result["requests"][0]["age_seconds"] >= 0
    assert "token student" not in json.dumps(result)
    assert path.read_bytes() == before
    assert sorted(p.name for p in root.iterdir()) == [
        "diagnostics.jsonl",
        "diagnostics.jsonl.lock",
        "operations.sqlite3",
    ]


def test_unrecognized_legacy_exception_is_suppressed(tmp_path):
    root = tmp_path / "refresh-worker"
    root.mkdir(mode=0o700)
    path = root / "operations.sqlite3"
    with sqlite3.connect(path) as db:
        db.execute(
            "CREATE TABLE operations (id TEXT PRIMARY KEY, workbook TEXT, status TEXT, payload TEXT, updated TEXT)"
        )
        db.execute(
            "INSERT INTO operations VALUES (?,?,?,?,?)",
            (
                RID,
                "fictional-workbook",
                "HELD",
                json.dumps(
                    {
                        "failure_reason": "Bearer private-token https://private.invalid student=123 grade=87"
                    }
                ),
                datetime.now(UTC).isoformat(),
            ),
        )
    path.chmod(0o600)
    result = inspect_journal(tmp_path, "fictional-workbook", RID)
    assert result["requests"][0]["failure_code"] == "unknown"
    assert "private" not in json.dumps(result)


def test_difference_categories_never_include_cell_positions_or_contents():
    before = {
        "spreadsheetId": "fictional-workbook",
        "sheets": [
            {
                "properties": {
                    "sheetId": 1,
                    "title": "Private title",
                    "gridProperties": {"rowCount": 20, "columnCount": 20},
                },
                "data": [
                    {
                        "startRow": 7,
                        "startColumn": 9,
                        "rowData": [
                            {
                                "values": [
                                    {
                                        "userEnteredValue": {"numberValue": 87},
                                        "note": "private student",
                                    }
                                ]
                            }
                        ],
                    }
                ],
            }
        ],
    }
    after = copy.deepcopy(before)
    cell = after["sheets"][0]["data"][0]["rowData"][0]["values"][0]
    cell["userEnteredValue"]["numberValue"] = 92
    cell["note"] = "private feedback"
    assert difference_categories(before, after) == ["cell_note", "cell_value"]


async def test_canvas_http_failure_class_and_correlation_without_raw_exception(
    tmp_path,
):
    def respond(request):
        return httpx.Response(
            403, json={"private": "Bearer token student=123 grade=87"}
        )

    client = GradebookClient(
        "https://fictional.invalid", "private-token", httpx.MockTransport(respond)
    )
    client.diagnostics = Diagnostics(tmp_path / "diagnostics.jsonl")
    try:
        with client.diagnostics.stage("prepare_core", RID):
            with pytest.raises(GradebookError):
                await client.get("/courses/1")
    finally:
        await client.close()
    rows = [
        json.loads(line) for line in client.diagnostics.path.read_text().splitlines()
    ]
    http = next(row for row in rows if row["event"] == "http")
    assert http["http_class"] == "forbidden" and http["attempt"] == 1
    assert http["stage"] == "prepare_core" and http["request_id"] == RID
    assert "private" not in client.diagnostics.path.read_text()


@pytest.mark.parametrize(
    "message,expected",
    [
        ("Google read stopped: HTTP 429.", "throttled"),
        ("Google retry delay requires a later attempt.", "retry_deferred"),
        (
            "Google workbook read exceeded its time limit; no partial read accepted.",
            "workbook_timeout",
        ),
        ("GET refresh workbook binding differs.", "binding_differs"),
        ("GET or metadata protection differs.", "structure_differs"),
        ("GET identity keys are duplicated.", "identity_invalid"),
        ("GET data exceeds its mapped grid.", "schema_differs"),
        ("GET baseline course or origin differs.", "baseline_differs"),
        ("Fresh GET snapshot course or origin differs.", "source_differs"),
        ("GET refresh plan binding or provenance differs.", "plan_differs"),
        ("GET refresh requires an explicit row expansion.", "capacity_required"),
        ("GET readback differs from its complete snapshot.", "readback_differs"),
        (
            "GET refresh native readback differs; never replay writes.",
            "readback_differs",
        ),
        (
            "GET refresh request readback is uncertain; do not enqueue another request.",
            "request_uncertain",
        ),
        ("Another local refresh worker owns this workbook.", "worker_busy"),
        (
            "A fresh READY GET-only worker is required before requesting refresh.",
            "worker_not_ready",
        ),
    ],
)
def test_owned_quota_and_get_only_failures_have_static_privacy_safe_codes(
    message, expected
):
    code = failure_code(GradebookError(message))
    assert code == expected
    result = safe_record(
        "loop",
        {"state": "HELD", "failure_code": code, "private_error": "fictional secret"},
    )
    assert result["failure_code"] == expected
    serialized = json.dumps(result)
    assert message not in serialized
    assert "fictional secret" not in serialized


@pytest.mark.parametrize(
    "message",
    [
        "fictional student identity and private provider response",
        "Google read stopped: HTTP 429. private added text",
        "GET baseline course or origin differs. fictional private value",
    ],
)
def test_near_match_or_provider_text_stays_unknown_and_is_not_reflected(message):
    code = failure_code(GradebookError(message))
    assert code == "unknown"
    result = safe_record("loop", {"failure_code": code, "message": message})
    assert message not in json.dumps(result)


def test_full_log_archives_history_and_records_fresh_startup(tmp_path):
    root = tmp_path / "refresh-worker"
    root.mkdir(mode=0o700)
    path = root / "diagnostics.jsonl"
    line = b'{"v":1,"event":"loop","at":"2000-01-01T00:00:00Z","state":"IDLE"}\n'
    history = line * (5_000_000 // len(line) + 1)
    path.write_bytes(history)
    path.chmod(0o600)
    diagnostics = Diagnostics(path)

    diagnostics.emit("startup", source_digest="a" * 64)

    archives = list(root.glob("diagnostics.archive-*.jsonl"))
    assert len(archives) == 1
    assert archives[0].read_bytes() == history
    assert path.stat().st_size < 5_000_000
    assert diagnostics.dropped == 0
    result = inspect_journal(tmp_path, "fictional-book")
    assert result["startup_pin"]["source_digest"] == "a" * 64
    assert result["recent_local_activity"] is True
    assert result["worker_running"] == "unverified"


def test_fresh_http_activity_and_header_startup_survive_large_log_tail(tmp_path):
    root = tmp_path / "refresh-worker"
    root.mkdir(mode=0o700)
    path = root / "diagnostics.jsonl"
    diagnostics = Diagnostics(path)
    diagnostics.emit("startup", source_digest="a" * 64)
    old_line = b'{"v":1,"event":"loop","at":"2000-01-01T00:00:00Z","state":"IDLE"}\n'
    with path.open("ab") as stream:
        stream.write(old_line * 1200)
    diagnostics.emit(
        "http", component="google", operation="workbook_read", http_class="success"
    )

    result = inspect_journal(tmp_path, "fictional-book")

    assert result["startup_pin"]["source_digest"] == "a" * 64
    assert result["recent_local_activity"] is True
    assert result["worker_running"] == "unverified"
    assert result["ready"] is False


def test_repeated_rotation_is_private_bounded_and_retains_each_startup_header(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(module, "MAX_LOG_BYTES", 600)
    root = tmp_path / "refresh-worker"
    root.mkdir(mode=0o700)
    path = root / "diagnostics.jsonl"
    diagnostics = Diagnostics(path)
    diagnostics.emit("startup", source_digest="a" * 64)
    first = json.loads(path.read_text())
    for _ in range(20):
        diagnostics.emit("stage_start", stage="readback")
    archives = list(root.glob("diagnostics.archive-*.jsonl"))
    assert len(archives) > 1
    for file in [path, *archives]:
        assert file.stat().st_size <= 600
        assert file.stat().st_mode & 0o777 == 0o600
        assert file.stat().st_nlink == 1
        lines = [json.loads(line) for line in file.read_text().splitlines()]
        assert lines[0] == first
    assert diagnostics.dropped == 0
    result = inspect_journal(tmp_path, "fictional-book")
    assert result["recent_local_activity"] is True
    assert result["startup_pin"]["source_digest"] == "a" * 64


def test_rotation_can_recover_header_when_a_new_diagnostics_object_opens_log(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(module, "MAX_LOG_BYTES", 600)
    root = tmp_path / "refresh-worker"
    root.mkdir(mode=0o700)
    path = root / "diagnostics.jsonl"
    initial = Diagnostics(path)
    initial.emit("startup", source_digest="a" * 64)
    first = json.loads(path.read_text())
    while path.stat().st_size < 490:
        initial.emit("stage_start", stage="readback")
    other = Diagnostics(path)
    other.emit(
        "http", component="google", operation="workbook_read", http_class="success"
    )
    assert list(root.glob("diagnostics.archive-*.jsonl"))
    assert json.loads(path.read_text().splitlines()[0]) == first
    assert other.dropped == 0


@pytest.mark.parametrize(
    "unsafe",
    [
        "log_symlink",
        "parent_symlink",
        "public_log",
        "lock_symlink",
        "fifo",
        "hard_link",
    ],
)
def test_unsafe_telemetry_paths_cannot_modify_another_file(tmp_path, unsafe):
    root = tmp_path / "refresh-worker"
    root.mkdir(mode=0o700)
    path = root / "diagnostics.jsonl"
    protected = tmp_path / "untouched"
    protected.write_bytes(b"retain-private-bytes")
    protected.chmod(0o600)
    if unsafe == "log_symlink":
        path.symlink_to(protected)
    elif unsafe == "parent_symlink":
        link = tmp_path / "linked-root"
        link.symlink_to(root, target_is_directory=True)
        path = link / "diagnostics.jsonl"
    elif unsafe == "public_log":
        path.write_bytes(b"public-log-bytes")
        path.chmod(0o644)
    elif unsafe == "lock_symlink":
        path.with_name(path.name + ".lock").symlink_to(protected)
    elif unsafe == "fifo":
        os.mkfifo(path, 0o600)
    else:
        os.link(protected, path)
    diagnostics = Diagnostics(path)
    diagnostics.emit("startup", source_digest="a" * 64)
    assert diagnostics.dropped == 1
    assert protected.read_bytes() == b"retain-private-bytes"
    assert not list(root.glob("diagnostics.archive-*.jsonl"))
    if unsafe == "public_log":
        assert path.read_bytes() == b"public-log-bytes"


def test_busy_telemetry_lock_drops_without_blocking_the_worker(tmp_path):
    root = tmp_path / "refresh-worker"
    root.mkdir(mode=0o700)
    path = root / "diagnostics.jsonl"
    fd = os.open(path.with_name(path.name + ".lock"), os.O_CREAT | os.O_RDWR, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        diagnostics = Diagnostics(path)
        diagnostics.emit("loop", state="IDLE")
        assert diagnostics.dropped == 1
        assert not path.exists()
    finally:
        os.close(fd)


def test_failed_rotation_preserves_active_history_and_later_emit_recovers(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(module, "MAX_LOG_BYTES", 600)
    root = tmp_path / "refresh-worker"
    root.mkdir(mode=0o700)
    path = root / "diagnostics.jsonl"
    diagnostics = Diagnostics(path)
    diagnostics.emit("startup", source_digest="a" * 64)
    while path.stat().st_size < 490:
        diagnostics.emit("stage_start", stage="readback")
    original = path.read_bytes()
    rename = module.os.rename

    def fail_rename(*args, **kwargs):
        raise OSError("fictional archive failure")

    monkeypatch.setattr(module.os, "rename", fail_rename)
    diagnostics.emit(
        "http", component="google", operation="workbook_read", http_class="success"
    )
    assert path.read_bytes() == original
    assert path.stat().st_nlink == 1
    assert diagnostics.dropped == 1
    reserved = {
        p.name: p.read_bytes() for p in root.glob("diagnostics.archive-*.jsonl")
    }
    monkeypatch.setattr(module.os, "rename", rename)
    diagnostics.emit(
        "http", component="google", operation="workbook_read", http_class="success"
    )
    assert diagnostics.dropped == 1
    assert any(
        p.read_bytes() == original for p in root.glob("diagnostics.archive-*.jsonl")
    )
    for name, contents in reserved.items():
        assert (root / name).read_bytes() == contents


def test_inspection_reads_only_bounded_private_samples_and_changes_no_files(tmp_path):
    root = tmp_path / "refresh-worker"
    root.mkdir(mode=0o700)
    path = root / "diagnostics.jsonl"
    diagnostics = Diagnostics(path)
    diagnostics.emit("startup", source_digest="a" * 64)
    diagnostics.emit("stage_start", stage="readback")
    before = {p.name: p.read_bytes() for p in root.iterdir()}
    result = inspect_journal(tmp_path, "fictional-book")
    assert result["recent_local_activity"] is True
    assert result["worker_running"] == "unverified"
    assert {p.name: p.read_bytes() for p in root.iterdir()} == before
    path.chmod(0o644)
    assert inspect_journal(tmp_path, "fictional-book")["recent_local_activity"] is False
