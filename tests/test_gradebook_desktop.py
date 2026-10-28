"""Desktop refresh behavior with fictional receipts and no live transports."""

import importlib.util
import json
import sqlite3
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "gradebook_desktop_under_test", ROOT / "scripts/sdm_gradebook_desktop.py"
)
desktop = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = desktop
SPEC.loader.exec_module(desktop)

RID = "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee"
BINDINGS = {
    "core": {"spreadsheet_id": "fictional-workbook"},
    "advanced": {"spreadsheet_id": "fictional-workbook"},
}


def coverage(*, added=False):
    return {
        "edit_students": 1, "edit_assignments": 1,
        "canvas_students": 2 if added else 1, "canvas_assignments": 2 if added else 1,
        "added_students": 1 if added else 0, "removed_students": 0,
        "added_assignments": 1 if added else 0, "removed_assignments": 0,
        "mapped_edit_targets": 1, "missing_edit_targets": 3 if added else 0,
        "edit_targets_removed_from_canvas": 0, "matches_canvas_axes": not added,
        "warning": "private sentinel", "names": "private sentinel",
    }


def test_coverage_output_is_whitelisted_and_does_not_accept_response_text():
    safe = desktop.safe_coverage(coverage(added=True))
    assert safe["missing_edit_targets"] == 3
    assert safe["matches_canvas_axes"] is False
    assert "private sentinel" not in json.dumps(safe)
    assert "warning" not in safe and "names" not in safe


@pytest.mark.parametrize("field,value", [
    ("edit_students", True), ("matches_canvas_axes", "private sentinel"),
    ("added_students", 1), ("mapped_edit_targets", 2), ("missing_edit_targets", -1),
])
def test_malformed_or_inconsistent_coverage_holds_privately(field, value):
    data = coverage()
    data[field] = value
    with pytest.raises(desktop.DesktopHold) as error:
        desktop.safe_coverage(data)
    assert "private sentinel" not in str(error.value)


def save(root, kind, value):
    artifact = desktop.digest(value)
    (root / f"{kind}-{artifact}.json").write_text(json.dumps(value), encoding="utf-8")
    return artifact


def operation(root, *, mode="GET_ONLY", preserved=True):
    request = {"v": 1, "id": RID, "action": "REFRESH_GET_BOTH",
               "workbook_id": "fictional-workbook", "created_at": "2026-10-14T10:40:00Z"}
    plans = {k: {"mode": mode, "edit_preserved": preserved,
                 "baseline_id": "0" * 64, "previous_baseline_id": "0" * 64} for k in BINDINGS}
    manifest = {"refresh_mode": mode, "binding_digest": desktop.digest(BINDINGS),
                "request": request, "plans": plans}
    mid = save(root, "refresh", manifest)
    summary = {k: {"students": 1, "assignments": 2,
                   "edit_preserved": preserved, "names": "do not print this"} for k in BINDINGS}
    receipt = {"worker_schema": 1, "request_id": RID, "manifest_id": mid,
               "canvas_writes": 0, "verified_at": "2026-10-14T10:42:00Z", "summary": summary}
    receipt_id = save(root, "receipt", receipt)
    return {"status": "VERIFIED", "payload": {"request": request,
            "refresh_mode": mode, "refresh_mode_schema": 1, "receipt_id": receipt_id,
            "manifest_id": mid, "finalized": True}}


def test_verified_summary_requires_get_mode_and_original_edit_baselines(tmp_path):
    op = operation(tmp_path)
    result = desktop.verified_summary(tmp_path, BINDINGS, RID, op)
    assert result["state"] == "VERIFIED"
    assert result["summary"]["core"] == {
        "students": 1, "assignments": 2, "edit_preserved": True
    }
    assert "do not print" not in json.dumps(result)
    for mode, preserved in [("FULL_SYNC", True), ("GET_ONLY", False)]:
        with pytest.raises(desktop.DesktopHold):
            desktop.verified_summary(tmp_path, BINDINGS, RID,
                                     operation(tmp_path, mode=mode, preserved=preserved))


def test_receipt_tampering_or_another_request_cannot_report_success(tmp_path):
    op = operation(tmp_path)
    with pytest.raises(desktop.DesktopHold):
        desktop.verified_summary(tmp_path, BINDINGS,
                                 "11111111-2222-4333-8444-555555555555", op)
    path = tmp_path / f"receipt-{op['payload']['receipt_id']}.json"
    path.write_text(path.read_text(encoding="utf-8").replace('"canvas_writes": 0', '"canvas_writes": 1'), encoding="utf-8")
    with pytest.raises(desktop.DesktopHold):
        desktop.verified_summary(tmp_path, BINDINGS, RID, op)


@pytest.mark.parametrize("field", ["refresh_mode_schema", "worker_schema"])
def test_boolean_schema_never_counts_as_complete_get_proof(tmp_path, field):
    op = operation(tmp_path)
    if field == "refresh_mode_schema":
        op["payload"][field] = True
    else:
        receipt = desktop.artifact(tmp_path, "receipt", op["payload"]["receipt_id"])
        receipt[field] = True
        op["payload"]["receipt_id"] = save(tmp_path, "receipt", receipt)
    with pytest.raises(desktop.DesktopHold):
        desktop.verified_summary(tmp_path, BINDINGS, RID, op)


def test_poll_hold_never_requests_releases_reconciles_or_replays(tmp_path):
    reads = []
    def read(*args):
        reads.append(args)
        return {"status": "UNCERTAIN", "payload": {}}
    with pytest.raises(desktop.DesktopHold, match="UNCERTAIN"):
        desktop.poll_refresh(tmp_path, BINDINGS, RID, read_operation=read,
                             emit=lambda _: None, sleep=lambda _: pytest.fail("No retry"))
    assert len(reads) == 1


def test_verified_but_unfinalized_request_still_waits_for_cleanup(tmp_path):
    complete = operation(tmp_path)
    pending = dict(complete, payload=dict(complete["payload"], finalized=False))
    states = iter([pending, complete])
    sleeps = []
    result = desktop.poll_refresh(tmp_path, BINDINGS, RID,
        read_operation=lambda *_: next(states), emit=lambda _: None, sleep=sleeps.append)
    assert result["state"] == "VERIFIED"
    assert len(sleeps) == 1


def test_local_journal_reader_opens_existing_database_read_only(tmp_path):
    folder = tmp_path / "refresh-worker"
    folder.mkdir()
    path = folder / "operations.sqlite3"
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE operations(id TEXT, workbook TEXT, status TEXT, payload TEXT)")
        db.execute("INSERT INTO operations VALUES(?,?,?,?)",
                   (RID, "fictional-workbook", "CLAIMED", "{}"))
    before = path.read_bytes()
    assert desktop.read_operation(tmp_path, "fictional-workbook", RID)["status"] == "CLAIMED"
    assert path.read_bytes() == before
    with pytest.raises(desktop.DesktopHold):
        desktop.read_operation(tmp_path, "another-workbook", RID)
    assert path.read_bytes() == before


def test_request_calls_only_the_existing_get_queue_once(monkeypatch, tmp_path):
    calls = []
    def run(command, **options):
        calls.append((command, options))
        return SimpleNamespace(returncode=0, stdout=json.dumps({"state": "QUEUED", "request_id": RID}))
    monkeypatch.setattr(desktop.subprocess, "run", run)
    assert desktop.request_refresh(tmp_path) == {"state": "QUEUED", "request_id": RID}
    assert len(calls) == 1
    assert calls[0][0] == [str(tmp_path / ".venv/bin/python"),
                           str(tmp_path / "scripts/sdm_gradebook_worker.py"), "--get-only", "request"]


def test_request_timeout_never_retries(monkeypatch, tmp_path):
    calls = []
    def run(command, **options):
        calls.append(command)
        raise desktop.subprocess.TimeoutExpired(command, 180)
    monkeypatch.setattr(desktop.subprocess, "run", run)
    with pytest.raises(desktop.DesktopHold, match="uncertain"):
        desktop.request_refresh(tmp_path)
    assert len(calls) == 1


def test_unknown_journal_state_never_reaches_user_output(tmp_path):
    output = []
    with pytest.raises(desktop.DesktopHold):
        desktop.poll_refresh(tmp_path, BINDINGS, RID,
            read_operation=lambda *_: {"status": "private unexpected text", "payload": {}},
            emit=output.append, sleep=lambda _: pytest.fail("No retry"))
    assert output == []


async def test_private_review_reads_once_and_invokes_only_preview_helpers(tmp_path, monkeypatch):
    calls = []
    class Google:
        async def read_workbook(self):
            calls.append("native_read")
            return {"fictional": "private source"}
        async def close(self):
            calls.append("google_close")
        async def batch(self, *args):
            pytest.fail("Review cannot write Sheets")
    class Canvas:
        async def close(self):
            calls.append("canvas_close")
        async def put(self, *args):
            pytest.fail("Review cannot publish")
    state = tmp_path / "private"
    state.mkdir()
    runtime = ModuleType("sdm_gradebook_worker")
    runtime.DEFAULT_CONFIG = tmp_path / "fictional-config.json"
    runtime.load_config = lambda _: {"state_dir": str(state)}
    runtime.bindings = lambda: BINDINGS
    runtime.google_client = lambda *_: Google()
    runtime.canvas_client = Canvas
    helper = ModuleType("canvas_mcp.gradebook.native_edit_review")
    async def prepare_review(canvas, store, course, binding, raw):
        calls.append("preview_" + course)
        assert raw == {"fictional": "private source"}
        assert binding == BINDINGS[course]
        path = store.root / f"review-{course}.html"
        path.write_text("Private fictional review", encoding="utf-8")
        return {"canvas_writes": 0, "changes": 1, "counts": {"review_required": 1},
                "review_file": str(path), "names": "never expose", "coverage": coverage()}
    helper.prepare_review = prepare_review
    monkeypatch.setitem(sys.modules, "sdm_gradebook_worker", runtime)
    monkeypatch.setitem(sys.modules, "canvas_mcp.gradebook.native_edit_review", helper)
    result = await desktop.private_reviews(ROOT)
    assert calls == ["native_read", "preview_core", "preview_advanced", "google_close", "canvas_close"]
    assert len(result) == 2
    assert "never expose" not in json.dumps(result)
    assert "private sentinel" not in json.dumps(result)


def test_review_terminal_reports_coverage_gaps_without_changing_grade_readiness(
    tmp_path, monkeypatch, capsys
):
    def load(path, maximum):
        return BINDINGS if path.name == "sdm-gradebook-workbooks.json" else {"state_dir": str(tmp_path)}
    calls = []
    async def preview(repo):
        calls.append(repo)
        return [{"course": "core", "changes": 1, "counts": {"ready_for_review": 1},
                 "coverage": coverage(added=True), "review_file": str(tmp_path / "review.html")}]
    monkeypatch.setattr(desktop, "load_json", load)
    monkeypatch.setattr("builtins.input", lambda _: "")
    monkeypatch.setattr(desktop, "private_reviews", preview)
    monkeypatch.setattr(desktop, "request_refresh", lambda _: pytest.fail("No queue"))
    assert desktop.main(["review", "--repo", str(tmp_path), "--no-open"]) == 0
    output = capsys.readouterr().out
    assert "1 ready for teacher review" in output
    assert "Coverage: EDIT 1 students / 1 assignments; fresh Canvas 2 students / 2 assignments." in output
    assert "3 fresh Canvas score slots are outside EDIT" in output
    assert "separately reviewed append plan" in output
    assert "does not change grade readiness" in output
    assert "private sentinel" not in output
    assert len(calls) == 1


@pytest.mark.parametrize("mode", ["fresh-get", "review"])
def test_canceling_shortcut_invokes_no_online_read_or_queue(mode, tmp_path, monkeypatch):
    def load(path, maximum):
        return BINDINGS if path.name == "sdm-gradebook-workbooks.json" else {"state_dir": str(tmp_path)}
    monkeypatch.setattr(desktop, "load_json", load)
    monkeypatch.setattr("builtins.input", lambda _: "cancel")
    monkeypatch.setattr(desktop, "request_refresh", lambda _: pytest.fail("No queue"))
    monkeypatch.setattr(desktop, "private_reviews", lambda _: pytest.fail("No reads"))
    assert desktop.main([mode, "--repo", str(tmp_path), "--no-open"]) == 0
