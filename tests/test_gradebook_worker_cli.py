"""Worker CLI lifecycle checks with injected local collaborators only."""

import asyncio
import importlib.util
import json
import os
import plistlib
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from canvas_mcp.gradebook.client import GradebookError

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "gradebook_worker_cli_under_test", ROOT / "scripts/sdm_gradebook_worker.py"
)
cli = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = cli
spec.loader.exec_module(cli)


@pytest.fixture
def configured(tmp_path):
    path = tmp_path / "worker.json"
    cli.configure(path, state_dir=tmp_path / "state")
    return path


def args(path, *arguments):
    return cli.parser().parse_args(["--config", str(path), *arguments])


def test_configure_stable_id_private_modes_and_no_start(configured):
    before = configured.read_bytes()
    result = cli.configure(configured)
    assert result == {"state": "CONFIGURED", "existing": True, "started": False}
    assert configured.read_bytes() == before
    assert configured.stat().st_mode & 0o777 == 0o600
    assert cli.load_config(configured)["poll_seconds"] == 30


@pytest.mark.parametrize(
    "changes",
    [
        {"schema_version": True},
        {"schema_version": 1.0},
        {"profile": "tf"},
        {"instance_id": "bad"},
        {"poll_seconds": 1},
        {"poll_seconds": True},
        {"credential_path": "relative.json"},
        {"extra": "unsupported"},
    ],
)
def test_config_rejects_unsafe_or_unknown_fields(configured, changes):
    value = json.loads(configured.read_text())
    value.update(changes)
    configured.write_text(json.dumps(value))
    with pytest.raises(GradebookError):
        cli.load_config(configured)


async def test_status_is_local_and_does_not_open_google(configured, monkeypatch):
    monkeypatch.setattr(
        cli, "google_client", lambda *_: pytest.fail("no Google access")
    )
    result = await cli.execute(args(configured, "status"))
    assert result["unresolved"] == 0 and result["worker_running"] == "unverified"
    assert result["state"] == "NO_LOCAL_HOLDS"


@pytest.mark.parametrize(
    "phases,expected",
    [
        ([phase], "IN_PROGRESS")
        for phase in ("CLAIMING", "CLAIMED", "PREPARED", "SENDING", "VERIFYING")
    ]
    + [
        (["HELD"], "HELD"),
        (["UNCERTAIN"], "UNCERTAIN"),
        (["CLAIMED", "PREPARED"], "IN_PROGRESS"),
        (["CLAIMED", "HELD"], "HELD"),
        (["VERIFYING", "UNCERTAIN"], "UNCERTAIN"),
        (["HELD", "UNCERTAIN"], "UNCERTAIN"),
        (["UNKNOWN_PHASE"], "HELD"),
    ],
)
def test_local_status_distinguishes_progress_without_inferring_liveness(
    configured, monkeypatch, phases, expected
):
    operations = {str(i): {"status": phase} for i, phase in enumerate(phases)}
    monkeypatch.setattr(
        cli,
        "RefreshJournal",
        lambda *_: SimpleNamespace(
            unresolved=lambda: list(operations), get=operations.get
        ),
    )
    result = cli.local_status(cli.load_config(configured), cli.bindings())
    assert result["state"] == expected
    assert result["unresolved"] == len(phases)
    assert result["states"] == dict(cli.Counter(phases))
    assert result["worker_running"] == "unverified"
    assert result["source"] == "local_journal"


def test_status_exposes_owned_safe_failure_reason_only(configured, monkeypatch):
    rid = "00000000-0000-4000-8000-000000000001"
    operation = {
        "status": "HELD",
        "payload": {
            "failure_reason": "Trusted baseline course or origin differs.",
            "other_private_payload": "not-output",
        },
    }
    monkeypatch.setattr(
        cli, "RefreshJournal", lambda *_: SimpleNamespace(get=lambda _: operation)
    )
    result = cli.local_status(cli.load_config(configured), cli.bindings(), rid)
    assert result["failure_reason"] == operation["payload"]["failure_reason"]
    assert "not-output" not in json.dumps(result)


async def test_release_requires_confirmation_before_connections(
    configured, monkeypatch
):
    monkeypatch.setattr(
        cli, "google_client", lambda *_: pytest.fail("no Google access")
    )
    with pytest.raises(GradebookError, match="--confirm"):
        await cli.execute(
            args(configured, "release-held", "00000000-0000-4000-8000-000000000001")
        )


async def test_doctor_reads_native_and_local_baselines_without_canvas(monkeypatch):
    viewed = []
    bound = cli.bindings()
    views = {course: {"_Sync": {"B2": course}} for course in cli.COURSES}
    snapshots = {
        course: {
            "course_id": cid,
            "origin": cli.ORIGIN,
            "students": [{}, {}],
            "assignments": [{}],
        }
        for course, cid in cli.COURSES.items()
    }

    class Google:
        async def read_workbook(self):
            viewed.append("read")
            return {}

    monkeypatch.setattr(cli, "validate_workbook", lambda raw, bindings: views)
    monkeypatch.setattr(cli, "edits_from_cells", lambda cells, baseline: {"edits": []})
    result = await cli.doctor(
        Google(), SimpleNamespace(load=lambda kind, key: snapshots[key]), bound
    )
    assert viewed == ["read"]
    assert result["state"] == "READY" and result["sheets_writes"] == 0
    assert result["summary"]["core"]["students"] == 2


async def test_reconcile_uses_reconcile_only_without_canvas(configured, monkeypatch):
    called = []

    class Google:
        async def close(self):
            called.append("close")

    class Worker:
        def __init__(self, google, canvas, *rest):
            assert canvas is None

        async def reconcile(self, rid):
            called.append("reconcile")
            return {"state": "UNCERTAIN", "request_id": rid, "retry_writes": False}

    monkeypatch.setattr(cli, "google_client", lambda *_: Google())
    monkeypatch.setattr(cli, "RefreshWorker", Worker)
    monkeypatch.setattr(cli, "canvas_client", lambda: pytest.fail("no Canvas needed"))
    result = await cli.execute(
        args(configured, "reconcile", "00000000-0000-4000-8000-000000000001")
    )
    assert result["retry_writes"] is False and called == ["reconcile", "close"]


async def test_once_runs_doctor_before_step_and_only_heartbeat_when_idle(
    configured, monkeypatch
):
    called = []

    class Client:
        async def close(self):
            called.append("close")

    class Worker:
        def __init__(self, *args):
            pass

        async def step(self):
            called.append("step")
            return {"state": "IDLE"}

        async def heartbeat(self):
            called.append("heartbeat")

    async def check(*args):
        called.append("doctor")
        return {"state": "READY"}

    monkeypatch.setattr(cli, "doctor", check)
    monkeypatch.setattr(cli, "google_client", lambda *_: Client())
    monkeypatch.setattr(cli, "canvas_client", Client)
    monkeypatch.setattr(cli, "RefreshWorker", Worker)
    await cli.execute(args(configured, "once"))
    assert called == ["doctor", "step", "heartbeat", "close", "close"]


async def test_launch_agent_is_template_only_and_follows_doctor(
    configured, monkeypatch
):
    called = []

    class Google:
        async def close(self):
            pass

    async def check(*args):
        called.append("doctor")
        return {"state": "READY"}

    monkeypatch.setattr(cli, "doctor", check)
    monkeypatch.setattr(cli, "google_client", lambda *_: Google())
    output = configured.parent / "agent.plist"
    result = await cli.execute(
        args(configured, "launch-agent", "--output", str(output))
    )
    assert called == ["doctor"] and result["installed"] is False
    saved = plistlib.loads(output.read_bytes())
    assert saved["ProgramArguments"][-1] == "run"
    assert saved["ProgramArguments"][2:4] == ["--config", str(configured)]
    assert output.stat().st_mode & 0o777 == 0o600


async def test_run_error_backoff_is_bounded_and_sanitized(monkeypatch, capsys):
    delays = []

    class Worker:
        async def step(self):
            raise RuntimeError("fictional-private-secret")

    async def sleep(delay):
        delays.append(delay)
        if len(delays) == 6:
            raise asyncio.CancelledError

    monkeypatch.setattr(cli.asyncio, "sleep", sleep)
    with pytest.raises(asyncio.CancelledError):
        await cli.run_loop(Worker(), 30)
    assert delays == [30, 60, 120, 240, 300, 300]
    assert "fictional-private-secret" not in capsys.readouterr().out


def test_main_redacts_unexpected_exception(configured, monkeypatch, capsys):
    async def fail(_):
        raise RuntimeError("fictional-private-secret")

    monkeypatch.setattr(cli, "execute", fail)
    assert cli.main(["--config", str(configured), "doctor"]) == 1
    assert "fictional-private-secret" not in capsys.readouterr().err


def test_fresh_import_disables_dotenv_before_canvas_package_load(tmp_path):
    sentinel = tmp_path / "synthetic.env"
    sentinel.write_text("SDM_WORKER_DOTENV_SENTINEL=must_not_load\n")
    worker_script = ROOT / "scripts/sdm_gradebook_worker.py"
    # Patch the real dotenv loader before importing the worker in a clean
    # process. Its only possible file read is this synthetic sentinel file.
    code = f"""
import importlib.util
import os
import sys
import dotenv
original = dotenv.load_dotenv
calls = []
def guarded(*args, **kwargs):
    assert os.environ.get('PYTHON_DOTENV_DISABLED') == '1', 'dotenv disabled too late'
    calls.append(True)
    return original(dotenv_path={str(sentinel)!r})
dotenv.load_dotenv = guarded
spec = importlib.util.spec_from_file_location('fresh_worker_fixture', {str(worker_script)!r})
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)
assert calls, 'fixture did not exercise the package dotenv load'
assert 'SDM_WORKER_DOTENV_SENTINEL' not in os.environ
print('dotenv import guard verified')
"""
    environment = {"PATH": os.environ.get("PATH", ""), "HOME": str(tmp_path)}
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "dotenv import guard verified"
