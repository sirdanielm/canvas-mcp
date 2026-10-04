"""Regression probes derived from the independent review, fictional data only."""

import os
import sqlite3
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

import pytest
from test_gradebook_worker import setup as setup

from canvas_mcp.gradebook.client import GradebookError
from canvas_mcp.gradebook.diagnostics import inspect_journal

RID = "00000000-0000-4000-8000-000000000001"
WORKBOOK = "fictional-workbook"
ROOT = Path(__file__).resolve().parents[1]


def journal(tmp_path, *, wal=False):
    root = tmp_path / "refresh-worker"
    root.mkdir(mode=0o700)
    path = root / "operations.sqlite3"
    db = sqlite3.connect(path)
    if wal:
        assert db.execute("PRAGMA journal_mode=WAL").fetchone()[0] == "wal"
    db.execute(
        "CREATE TABLE operations (id TEXT PRIMARY KEY, workbook TEXT, status TEXT, payload TEXT, updated TEXT)"
    )
    db.commit()
    return root, path, db


def test_closed_wal_database_diagnostics_creates_no_sidecars(tmp_path):
    root, path, db = journal(tmp_path, wal=True)
    db.close()
    path.chmod(0o600)
    files, before = {p.name for p in root.iterdir()}, path.read_bytes()
    inspect_journal(tmp_path, WORKBOOK)
    assert path.read_bytes() == before
    assert {p.name for p in root.iterdir()} == files == {"operations.sqlite3"}


@pytest.mark.parametrize("state", ["VERIFIED", "HELD"])
def test_old_exact_request_and_unresolved_hold_survive_newer_completed_rows(
    tmp_path, state
):
    root, path, db = journal(tmp_path)
    now = datetime.now(UTC)
    db.execute(
        "INSERT INTO operations VALUES(?,?,?,?,?)",
        (RID, WORKBOOK, state, "{}", (now - timedelta(days=2)).isoformat()),
    )
    for n in range(2, 1002):
        db.execute(
            "INSERT INTO operations VALUES(?,?,?,?,?)",
            (str(UUID(int=n)), WORKBOOK, "VERIFIED", "{}", now.isoformat()),
        )
    db.commit()
    db.close()
    path.chmod(0o600)
    before = path.read_bytes()
    exact = inspect_journal(tmp_path, WORKBOOK, RID)
    assert exact["requests"][0]["state"] == state
    if state == "HELD":
        aggregate = inspect_journal(tmp_path, WORKBOOK)
        assert aggregate["state"] == "HELD" and aggregate["unresolved"] == 1
        assert aggregate["requests"][0]["request_id"] == RID
    assert path.read_bytes() == before


async def test_recovered_claim_response_does_not_mask_prepare_failure(
    setup, monkeypatch
):
    worker, google, req, fail = setup
    original = google.batch

    async def lost_claim_response(requests):
        result = await original(requests)
        if any(
            "createDeveloperMetadata" in r
            and r["createDeveloperMetadata"]["developerMetadata"][
                "metadataKey"
            ].endswith(".claim.v1")
            for r in requests
        ):
            raise TimeoutError("fictional lost claim response")
        return result

    monkeypatch.setattr(google, "batch", lost_claim_response)
    fail["course"] = "advanced"
    with pytest.raises(GradebookError):
        await worker.step()
    operation = worker.journal.get(req["id"])
    assert operation["status"] == "HELD" and google.grade_calls == 0
    assert operation["payload"]["failure_stage"] == "prepare_advanced"


@pytest.mark.parametrize("operation", ["emit", "inspect"])
@pytest.mark.parametrize("fifo_reader", [False, True])
def test_fifo_log_never_blocks_writer_or_inspection(tmp_path, operation, fifo_reader):
    root = tmp_path / "refresh-worker"
    root.mkdir(mode=0o700)
    log = root / "diagnostics.jsonl"
    os.mkfifo(log, 0o600)
    reader = os.open(log, os.O_RDONLY | os.O_NONBLOCK) if fifo_reader else None
    code = (
        f"from pathlib import Path; from canvas_mcp.gradebook.diagnostics import Diagnostics; d=Diagnostics(Path({str(log)!r})); d.emit('loop', state='HELD'); assert d.dropped > 0"
        if operation == "emit"
        else f"from pathlib import Path; from canvas_mcp.gradebook.diagnostics import inspect_journal; inspect_journal(Path({str(tmp_path)!r}), 'fictional-workbook')"
    )
    try:
        subprocess.run(
            [sys.executable, "-c", code],
            cwd=ROOT,
            env={
                **os.environ,
                "PYTHONPATH": str(ROOT / "src"),
                "PYTHON_DOTENV_DISABLED": "1",
            },
            timeout=2,
            capture_output=True,
            check=True,
        )
    except subprocess.TimeoutExpired:
        pytest.fail(f"{operation} blocked on FIFO")
    finally:
        if reader is not None:
            os.close(reader)


def test_active_wal_is_refused_without_touching_database_or_sidecars(tmp_path):
    root, path, db = journal(tmp_path, wal=True)
    try:
        before = {p.name: p.read_bytes() for p in root.iterdir()}
        with pytest.raises(ValueError):
            inspect_journal(tmp_path, WORKBOOK)
        assert {p.name: p.read_bytes() for p in root.iterdir()} == before
    finally:
        db.close()


def test_over_bound_unresolved_inventory_is_refused_instead_of_truncated(tmp_path):
    root, path, db = journal(tmp_path)
    for n in range(1, 1002):
        db.execute(
            "INSERT INTO operations VALUES(?,?,?,?,?)",
            (str(UUID(int=n)), WORKBOOK, "HELD", "{}", datetime.now(UTC).isoformat()),
        )
    db.commit()
    db.close()
    before = path.read_bytes()
    with pytest.raises(ValueError, match="inventory exceeds"):
        inspect_journal(tmp_path, WORKBOOK)
    assert path.read_bytes() == before


def test_active_rollback_journal_is_refused_without_touching_files(tmp_path):
    root, path, db = journal(tmp_path)
    db.close()
    sidecar = path.with_name(path.name + "-journal")
    sidecar.write_bytes(b"fictional active rollback journal")
    before = {p.name: p.read_bytes() for p in root.iterdir()}
    with pytest.raises(ValueError, match="active journal"):
        inspect_journal(tmp_path, WORKBOOK)
    assert {p.name: p.read_bytes() for p in root.iterdir()} == before
