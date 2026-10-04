"""Fictional diagnostics, privacy and strictly local read-only checks."""

import copy
import json
import sqlite3
from datetime import UTC, datetime

import httpx
import pytest

from canvas_mcp.gradebook.client import GradebookClient, GradebookError
from canvas_mcp.gradebook.diagnostics import Diagnostics, inspect_journal
from canvas_mcp.gradebook.native import difference_categories

RID = "00000000-0000-4000-8000-000000000001"


def test_allowlist_never_serializes_private_values(tmp_path):
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
    assert rows[0]["request_id"] == RID
    assert rows[0]["http_class"] == "forbidden"
    assert "component" not in rows[1] and "operation" not in rows[1]
    assert not any(
        value in log.read_text()
        for value in (
            "private",
            "score=87",
            "student_id",
            "Authorization",
            "grade",
            "123",
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
