"""Regression probes derived from the independent review, fictional data only."""

import os
import select
import sqlite3
import subprocess
import sys
import time
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


def _run_fifo_probe(import_code, operation_code, *, startup_timeout=30):
    """Bound imports separately; retain the two-second FIFO-operation guard."""
    code = (
        "import sys\n" + import_code + "\n"
        "print('READY', flush=True)\n"
        "if sys.stdin.readline() != 'RUN\\n':\n"
        "    raise RuntimeError('Probe was not released')\n" + operation_code + "\n"
    )
    with subprocess.Popen(
        [sys.executable, "-c", code],
        cwd=ROOT,
        env={
            **os.environ,
            "PYTHONPATH": str(ROOT / "src"),
            "PYTHON_DOTENV_DISABLED": "1",
        },
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    ) as process:
        try:
            assert process.stdout is not None
            deadline = time.monotonic() + startup_timeout
            response = b""
            while b"\n" not in response:
                remaining = deadline - time.monotonic()
                ready, _, _ = select.select([process.stdout], [], [], max(0, remaining))
                if remaining <= 0 or not ready:
                    pytest.fail("FIFO probe startup timed out before operation began")
                chunk = os.read(process.stdout.fileno(), 64)
                if not chunk:
                    break
                response += chunk
                if len(response) > 64:
                    pytest.fail(
                        "FIFO probe startup emitted an invalid readiness response"
                    )
            if response != b"READY\n":
                _, error = process.communicate(timeout=5)
                pytest.fail("FIFO probe startup failed: " + error[-2000:])
            try:
                _, error = process.communicate(input="RUN\n", timeout=2)
            except subprocess.TimeoutExpired:
                pytest.fail("FIFO operation blocked after readiness")
            if process.returncode:
                pytest.fail("FIFO operation failed: " + error[-2000:])
        finally:
            if process.poll() is None:
                process.kill()
                process.communicate(timeout=5)


@pytest.mark.parametrize("operation", ["emit", "inspect"])
@pytest.mark.parametrize("fifo_reader", [False, True])
def test_fifo_log_never_blocks_writer_or_inspection(tmp_path, operation, fifo_reader):
    root = tmp_path / "refresh-worker"
    root.mkdir(mode=0o700)
    log = root / "diagnostics.jsonl"
    os.mkfifo(log, 0o600)
    reader = os.open(log, os.O_RDONLY | os.O_NONBLOCK) if fifo_reader else None
    import_code = (
        "from pathlib import Path; from canvas_mcp.gradebook.diagnostics import Diagnostics"
        if operation == "emit"
        else "from pathlib import Path; from canvas_mcp.gradebook.diagnostics import inspect_journal"
    )
    operation_code = (
        f"d=Diagnostics(Path({str(log)!r})); d.emit('loop', state='HELD'); assert d.dropped > 0"
        if operation == "emit"
        else f"inspect_journal(Path({str(tmp_path)!r}), 'fictional-workbook')"
    )
    try:
        _run_fifo_probe(import_code, operation_code)
    finally:
        if reader is not None:
            os.close(reader)


@pytest.mark.parametrize(
    "failure",
    [
        "startup_failure",
        "startup_timeout",
        "partial_startup_timeout",
        "operation_timeout",
    ],
)
def test_fifo_probe_bounds_startup_and_operation_and_reaps_child(monkeypatch, failure):
    created = []
    original = subprocess.Popen

    def track(*args, **kwargs):
        process = original(*args, **kwargs)
        created.append(process)
        return process

    monkeypatch.setattr(subprocess, "Popen", track)
    startup = (
        "raise RuntimeError('fictional startup failure')"
        if failure == "startup_failure"
        else "import time"
    )
    if failure == "startup_timeout":
        startup += "; time.sleep(10)"
    if failure == "partial_startup_timeout":
        startup = "import sys,time; sys.stdout.write('REA'); sys.stdout.flush(); time.sleep(10)"
    operation = "time.sleep(10)" if failure == "operation_timeout" else "pass"
    expected = {
        "startup_failure": "startup failed",
        "startup_timeout": "startup timed out",
        "partial_startup_timeout": "startup timed out",
        "operation_timeout": "operation blocked",
    }[failure]
    with pytest.raises(pytest.fail.Exception, match=expected):
        _run_fifo_probe(
            startup,
            operation,
            startup_timeout=(
                0.2 if failure in ("startup_timeout", "partial_startup_timeout") else 30
            ),
        )
    assert len(created) == 1 and created[0].poll() is not None


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
