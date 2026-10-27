"""Existing-owner integration with authenticated fictional LocalGrAss evidence.

Opt in with LOCALGRASS_TEST_ROOT as for test_localgrass_teacher_edit. Real owner
types and durable stores are composed; every external response is fictional.
"""

import asyncio
import copy
import hashlib
import json
import time
from types import SimpleNamespace

import httpx
import pytest
from test_gradebook import snapshot as snapshot
from test_gradebook_native import binding as binding
from test_gradebook_native import raw_from_state
from test_localgrass_teacher_edit import integrated as integrated

from canvas_mcp.gradebook import capture, native
from canvas_mcp.gradebook.client import GradebookClient, GradebookError
from canvas_mcp.gradebook.google import GoogleSheets
from canvas_mcp.gradebook.localgrass_edit_owner import LocalGrAssEditOwner
from canvas_mcp.gradebook.model import digest
from canvas_mcp.gradebook.worker import RefreshJournal, RefreshJournalBusy


def composed_source(integrated, tmp_path, monkeypatch):
    connection, context, domain, _, _, _, store = integrated
    # The canonical PIN join runs against the same fictional registry adapter
    # used by the authenticated capture fixture, not a second identity source.
    shared = capture.load_shared_pin_module(None)
    monkeypatch.setattr("localgrass.student_pin.binding", shared.binding)
    monkeypatch.setattr("localgrass.student_pin.read_table", shared.read_table)
    monkeypatch.setattr("localgrass.student_pin.roster_index", shared.roster_index)
    repo = tmp_path / "existing-canvas-repo"
    (repo / "config").mkdir(parents=True)
    binding_path = repo / "config/sdm-gradebook-workbooks.json"
    binding_path.write_text(json.dumps({"core": context["binding"]}), encoding="utf-8")
    output = tmp_path / "existing-participation-history"
    output.mkdir(mode=0o700)
    runtime = tmp_path / "existing-runtime"
    runtime.mkdir()
    domain.source.identity_runtime_root = runtime
    worker_config_path = tmp_path / "existing-worker-config.json"
    worker_config_path.write_text(json.dumps({"state_dir": str(store.root)}), encoding="utf-8")
    config = {
        "course": "core",
        "spreadsheet_id": context["binding"]["spreadsheet_id"],
        "assignment_bindings_path": str(connection.assignment_path),
        "assignment_bindings_sha256": connection.assignment_sha256,
        "pin_registry": str(connection.registry_path),
        "canvas_repo": str(repo),
        "output_root": str(output),
        "runtime_root": str(runtime),
        "worker_config": str(worker_config_path),
    }
    config_path = tmp_path / "existing-participation-config.json"
    config_path.write_text(json.dumps(config), encoding="utf-8")
    credential = tmp_path / "fictional-credentials.json"
    credential.write_text(
        json.dumps(
            {
                "tokens": {
                    "gradebook": {
                        "type": "authorized_user",
                        "client_id": "fictional-client",
                        "client_secret": "fictional-secret",
                        "refresh_token": "fictional-refresh",
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    credential.chmod(0o600)
    calls = {"canvas_reads": 0, "sheets_reads": 0, "posts": []}
    state = {
        "raw": copy.deepcopy(context["raw"]),
        "apply": True,
        "lose_reply": False,
        "canvas_unavailable": False,
        "fail_canvas_after_send": False,
    }
    journal = RefreshJournal(store.root, context["binding"]["spreadsheet_id"])

    def refuse_canvas(request):
        raise AssertionError("Unmocked Canvas transport reached")

    def sheets_transport(request):
        assert request.method == "POST"
        assert str(request.url) == google.url + ":batchUpdate"
        payload = json.loads(request.content)
        requests = payload["requests"]
        calls["posts"].append(copy.deepcopy(requests))
        # The existing workbook lock and durable SENDING intent must both
        # precede the actual native transport, not merely a wrapper callback.
        with pytest.raises(RefreshJournalBusy):
            with journal.exclusive():
                pass
        receipts = sorted(output.glob("*/receipt-*.json"))
        assert json.loads(receipts[-1].read_text(encoding="utf-8"))["status"] == "SENDING"
        if state["apply"]:
            current = native._state(state["raw"])
            for item in requests:
                update = item["updateCells"]
                assert update["fields"] == "userEnteredValue,note"
                start = update["start"]
                assert start == {"sheetId": 2, "rowIndex": 5, "columnIndex": 2}
                current["sheets"][2]["cells"]["5:2"].update(
                    update["rows"][0]["values"][0]
                )
            state["raw"] = raw_from_state(current)
        if state["fail_canvas_after_send"]:
            state["canvas_unavailable"] = True
            domain.source.csrf = "revoked"
        if state["lose_reply"]:
            raise httpx.ReadTimeout("Fictional lost native reply", request=request)
        return httpx.Response(200, json={"spreadsheetId": google.workbook_id})

    canvas = GradebookClient(
        context["current"]["origin"],
        "fictional-token",
        transport=httpx.MockTransport(refuse_canvas),
    )
    google = GoogleSheets(
        context["binding"]["spreadsheet_id"],
        credential,
        transport=httpx.MockTransport(sheets_transport),
    )

    async def canvas_snapshot(course):
        assert course == "12"
        calls["canvas_reads"] += 1
        if state["canvas_unavailable"]:
            raise GradebookError("Fictional Canvas read unavailable")
        return copy.deepcopy(context["current"])

    async def read_workbook():
        calls["sheets_reads"] += 1
        google._authorized = True
        google._access_token = google._validated_token = "fictional-validated-token"
        google._expires_at = time.monotonic() + 300
        return copy.deepcopy(state["raw"])

    monkeypatch.setattr(canvas, "snapshot", canvas_snapshot)
    monkeypatch.setattr(google, "read_workbook", read_workbook)
    kwargs = {
        "staging_config_path": config_path,
        "expected_staging_config_sha256": hashlib.sha256(
            config_path.read_bytes()
        ).hexdigest(),
        "binding": context["binding"],
    }
    owner = LocalGrAssEditOwner(connection, canvas, google, journal, **kwargs)
    yield SimpleNamespace(
        owner=owner,
        connection=connection,
        context=context,
        domain=domain,
        store=store,
        output=output,
        config=config,
        config_path=config_path,
        worker_config_path=worker_config_path,
        binding_path=binding_path,
        journal=journal,
        canvas=canvas,
        google=google,
        calls=calls,
        state=state,
        kwargs=kwargs,
    )
    asyncio.run(canvas.close())
    asyncio.run(google.close())


@pytest.fixture
def composed(integrated, tmp_path, monkeypatch):
    yield from composed_source(integrated, tmp_path, monkeypatch)


def artifacts(root):
    return {
        str(p.relative_to(root)): p.read_bytes() for p in root.rglob("*") if p.is_file()
    }


@pytest.mark.asyncio
async def test_prepare_retains_exact_authenticated_plan_from_sync_b2(
    composed, monkeypatch
):
    c = composed
    loads = []
    original_load = c.store.load

    def load(kind, artifact_id):
        loads.append((kind, artifact_id))
        return original_load(kind, artifact_id)

    monkeypatch.setattr(c.store, "load", load)
    before_changes = c.domain.registry.connection.total_changes
    before_raw = copy.deepcopy(c.state["raw"])
    result = await c.owner.prepare()
    plan = original_load("review", result["plan_id"])
    assert result["status"] == "PREPARED_LOCAL_EDIT_ONLY"
    assert digest(plan) == result["plan_id"]
    assert ("snapshot", digest(c.context["baseline"])) in loads
    assert plan["transfer"]["baseline"] == c.context["baseline"]
    assert (
        plan["transfer"]["decision"]["decision_revision"]
        == c.domain.acceptance["decision_id"]
    )
    assert plan["transfer"]["decision"]["feedback"].endswith(
        "Explicit fictional final feedback."
    )
    assert c.domain.registry.connection.total_changes == before_changes
    assert c.state["raw"] == before_raw
    assert c.calls == {"canvas_reads": 1, "sheets_reads": 1, "posts": []}
    assert not list(c.output.iterdir())
    assert result["canvas_writes"] == result["sheets_write_requests"] == 0
    assert result["publication_allowed"] is False
    assert await c.owner.prepare() == result
    assert len(list(c.store.root.glob("review-*.json"))) == 1


@pytest.mark.asyncio
async def test_disabled_execute_has_no_reads_writes_locks_or_artifacts(composed):
    c = composed
    before = artifacts(c.store.root)
    result = await c.owner.execute("not-even-a-stored-plan")
    assert result["status"] == "LOCAL_EDIT_WRITE_DISABLED"
    assert result["canvas_writes"] == result["sheets_write_requests"] == 0
    assert result["retry_writes"] is result["publication_allowed"] is False
    assert c.calls == {"canvas_reads": 0, "sheets_reads": 0, "posts": []}
    assert artifacts(c.store.root) == before
    assert not list(c.output.iterdir())


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", [{"enabled": 1}, {"reconcile_only": "yes"}])
async def test_execution_mode_requires_literal_booleans(composed, mode):
    with pytest.raises(GradebookError, match="EXPLICIT_LOCAL_EXECUTION_MODE"):
        await composed.owner.execute("unused", **mode)
    assert composed.calls == {"canvas_reads": 0, "sheets_reads": 0, "posts": []}


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["prepare", "execute"])
async def test_existing_refresh_lock_excludes_native_owner_before_io(
    composed, operation
):
    c = composed
    with c.journal.exclusive():
        with pytest.raises(RefreshJournalBusy):
            if operation == "prepare":
                await c.owner.prepare()
            else:
                await c.owner.execute("unused", enabled=True)
    assert c.calls == {"canvas_reads": 0, "sheets_reads": 0, "posts": []}
    assert not list(c.store.root.glob("review-*.json"))
    assert not list(c.output.iterdir())


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["prepare", "execute"])
async def test_unresolved_refresh_history_holds_before_any_transport(
    composed, operation
):
    c = composed
    plan_id = "unused"
    if operation == "execute":
        plan_id = (await c.owner.prepare())["plan_id"]
        c.calls.update(canvas_reads=0, sheets_reads=0)
    c.journal.create({"id": "fictional-existing-refresh"}, 17, refresh_mode="GET_ONLY")
    with pytest.raises(GradebookError, match="UNRESOLVED_WORKBOOK_REFRESH_HISTORY"):
        if operation == "prepare":
            await c.owner.prepare()
        else:
            await c.owner.execute(plan_id, enabled=True)
    assert c.calls == {"canvas_reads": 0, "sheets_reads": 0, "posts": []}
    assert c.journal.unresolved() == ["fictional-existing-refresh"]
    assert not list(c.output.iterdir())


@pytest.mark.asyncio
async def test_execute_uses_one_native_batch_and_preserves_complete_workbook(composed):
    c = composed
    result = await c.owner.prepare()
    plan = c.store.load("review", result["plan_id"])
    before = native._state(c.state["raw"])
    for _ in range(2):
        receipt = await c.owner.execute(result["plan_id"], enabled=True)
        assert receipt["status"] == "PLANNED_OUTPUT_OBSERVED"
        assert receipt["canvas_writes"] == 0
        assert receipt["retry_writes"] is receipt["publication_allowed"] is False
    assert len(c.calls["posts"]) == 1
    assert (
        json.loads(json.dumps(native._state(c.state["raw"])))
        == plan["transfer"]["after_state"]
    )
    expected = copy.deepcopy(before)
    expected["sheets"][2]["cells"]["5:2"].update(
        plan["transfer"]["requests"][0]["updateCells"]["rows"][0]["values"][0]
    )
    assert native._state(c.state["raw"]) == expected
    assert len(list((c.output / result["plan_id"]).glob("receipt-*.json"))) == 3


@pytest.mark.asyncio
@pytest.mark.parametrize("applied", [False, True])
async def test_uncertain_send_never_replays_and_reconciliation_preserves_refresh_hold(
    composed, applied
):
    c = composed
    result = await c.owner.prepare()
    c.state.update(apply=applied, lose_reply=True)
    uncertain = await c.owner.execute(result["plan_id"], enabled=True)
    assert uncertain["status"] == "UNCERTAIN_RECONCILIATION_REQUIRED"
    c.state["canvas_unavailable"] = True
    c.domain.source.csrf = "revoked"
    canvas_reads = c.calls["canvas_reads"]
    again = await c.owner.execute(result["plan_id"], enabled=True)
    assert again["status"] == (
        "PLANNED_OUTPUT_OBSERVED" if applied else "UNCERTAIN_RECONCILIATION_REQUIRED"
    )
    c.journal.create(
        {"id": "fictional-unresolved-refresh"}, 19, refresh_mode="GET_ONLY"
    )
    reconciled = await c.owner.execute(result["plan_id"], reconcile_only=True)
    assert reconciled["status"] == (
        "PLANNED_OUTPUT_OBSERVED" if applied else "UNCERTAIN_RECONCILIATION_REQUIRED"
    )
    assert reconciled["sheets_write_requests"] == reconciled["canvas_writes"] == 0
    assert len(c.calls["posts"]) == 1
    assert c.calls["canvas_reads"] == canvas_reads
    assert c.journal.unresolved() == ["fictional-unresolved-refresh"]


@pytest.mark.asyncio
async def test_native_success_uses_sheets_readback_when_canvas_and_teacher_login_fail(
    composed,
):
    c = composed
    prepared = await c.owner.prepare()
    c.state["fail_canvas_after_send"] = True
    receipt = await c.owner.execute(prepared["plan_id"], enabled=True)
    assert receipt["status"] == "PLANNED_OUTPUT_OBSERVED"
    assert c.state["canvas_unavailable"] is True
    assert c.domain.source.csrf == "revoked"
    assert (
        c.calls["canvas_reads"] == 3
    )  # Prepare and two preflight reads, all before send.
    assert c.calls["sheets_reads"] == 4  # Prepare, two preflights, native readback.
    c.journal.create(
        {"id": "fictional-unresolved-refresh"}, 23, refresh_mode="GET_ONLY"
    )
    for mode in ({"enabled": True}, {"reconcile_only": True}):
        result = await c.owner.execute(prepared["plan_id"], **mode)
        assert result["status"] == "PLANNED_OUTPUT_OBSERVED"
        assert result["sheets_write_requests"] == 0
    assert c.calls["canvas_reads"] == 3
    assert len(c.calls["posts"]) == 1
    assert c.journal.unresolved() == ["fictional-unresolved-refresh"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "changed",
    [
        "config",
        "registered_binding",
        "google_workbook",
        "journal_workbook",
        "worker_state",
    ],
)
async def test_changed_configuration_and_owner_binding_hold_before_io(
    composed, changed
):
    c = composed
    prepared = await c.owner.prepare()
    c.calls.update(canvas_reads=0, sheets_reads=0)
    if changed == "config":
        config = dict(c.config, output_root=str(c.output.parent / "parallel-root"))
        c.config_path.write_text(json.dumps(config), encoding="utf-8")
        code = "EXISTING_STAGING_CONFIG_CHANGED"
    elif changed == "registered_binding":
        c.binding_path.write_text(
            json.dumps({"core": dict(c.context["binding"], course_id="99")}),
            encoding="utf-8",
        )
        code = "REGISTERED_WORKBOOK_BINDING_CHANGED"
    elif changed == "worker_state":
        c.worker_config_path.write_text(json.dumps({"state_dir": str(c.output)}), encoding="utf-8")
        code = "EXISTING_WORKER_STATE_CHANGED"
    else:
        (
            c.google if changed == "google_workbook" else c.journal
        ).workbook_id = "other-fictional-book"
        code = "EXISTING_WORKBOOK_OWNER_MISMATCH"
    with pytest.raises(GradebookError, match=code):
        await c.owner.execute(prepared["plan_id"], enabled=True)
    assert c.calls == {"canvas_reads": 0, "sheets_reads": 0, "posts": []}
    assert not list(c.output.iterdir())


def test_constructor_requires_existing_stage_history_and_registered_root(composed):
    c = composed
    c.output.rmdir()
    with pytest.raises(GradebookError, match="EXISTING_STAGING_HISTORY_REQUIRED"):
        LocalGrAssEditOwner(c.connection, c.canvas, c.google, c.journal, **c.kwargs)
    assert not c.output.exists()


@pytest.mark.asyncio
async def test_sync_b2_must_resolve_to_baseline_of_fixed_canvas_owner(composed):
    c = composed
    other = copy.deepcopy(c.context["baseline"])
    other["origin"] = "https://different.example"
    snapshot_id, _ = c.store.save("snapshot", other)
    state = native._state(c.state["raw"])
    state["sheets"][3]["cells"]["1:1"]["userEnteredValue"] = {
        "stringValue": snapshot_id
    }
    c.state["raw"] = raw_from_state(state)
    with pytest.raises(GradebookError, match="TRUSTED_EDIT_BASELINE_CHANGED"):
        await c.owner.prepare()
    assert c.calls["posts"] == []
    assert not list(c.store.root.glob("review-*.json"))


@pytest.mark.asyncio
async def test_rehashed_retained_plan_cannot_change_registered_workbook(composed):
    c = composed
    result = await c.owner.prepare()
    plan = c.store.load("review", result["plan_id"])
    plan["binding"]["spreadsheet_id"] = "other-fictional-book"
    changed_id, _ = c.store.save("review", plan)
    c.calls.update(canvas_reads=0, sheets_reads=0)
    with pytest.raises(GradebookError, match="RETAINED_WORKBOOK_BINDING_CHANGED"):
        await c.owner.execute(changed_id, enabled=True)
    assert c.calls == {"canvas_reads": 0, "sheets_reads": 0, "posts": []}
    assert not list(c.output.iterdir())


@pytest.mark.asyncio
@pytest.mark.parametrize("phase", ["before_prepare", "after_prepare"])
@pytest.mark.parametrize("field", ["value", "note"])
async def test_existing_teacher_edits_remain_intact_when_target_conflicts(
    composed, phase, field
):
    c = composed
    plan_id = None
    if phase == "after_prepare":
        plan_id = (await c.owner.prepare())["plan_id"]
    state = native._state(c.state["raw"])
    cell = state["sheets"][2]["cells"]["5:2"]
    if field == "value":
        cell["userEnteredValue"] = {"numberValue": 6}
    else:
        cell["note"] = "Retained fictional teacher correction"
    c.state["raw"] = raw_from_state(state)
    preserved = copy.deepcopy(c.state["raw"])
    code = (
        "NATIVE_DESTINATION_DIVERGED"
        if phase == "after_prepare"
        else (
            "EXISTING_TEACHER_EDIT_PRESERVED"
            if field == "value"
            else "EXISTING_TEACHER_NOTE_PRESERVED"
        )
    )
    with pytest.raises(GradebookError, match=code):
        if phase == "before_prepare":
            await c.owner.prepare()
        else:
            await c.owner.execute(plan_id, enabled=True)
    assert c.state["raw"] == preserved
    assert c.calls["posts"] == []
    assert not list(c.output.glob("*/receipt-*.json"))


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "field,value", [("origin", "https://different.example"), ("course_id", "99")]
)
async def test_current_canvas_response_must_match_fixed_owner(composed, field, value):
    c = composed
    c.context["current"][field] = value
    with pytest.raises(GradebookError, match="CURRENT_CANVAS_OWNER_CHANGED"):
        await c.owner.prepare()
    assert c.calls == {"canvas_reads": 1, "sheets_reads": 0, "posts": []}
    assert not list(c.store.root.glob("review-*.json"))
