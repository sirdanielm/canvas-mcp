"""Concrete existing-owner wiring; all identities and transports are fictional."""

import hashlib
import json
import socket
from pathlib import Path

import pytest
from test_gradebook import snapshot as snapshot
from test_gradebook_native import binding as binding
from test_gradebook_native import raw_from_state
from test_localgrass_edit_owner import composed as composed
from test_localgrass_teacher_edit import integrated as integrated

from canvas_mcp.gradebook import localgrass_application as app
from canvas_mcp.gradebook import native
from canvas_mcp.gradebook.client import GradebookError
from canvas_mcp.gradebook.localgrass_edit_owner import LocalGrAssEditOwner
from canvas_mcp.gradebook.model import digest


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def refuse(*args, **kwargs):
        raise AssertionError("network is forbidden in application qualification")

    monkeypatch.setattr(socket.socket, "connect", refuse)
    monkeypatch.setattr(socket.socket, "connect_ex", refuse)


def encoded(value):
    return json.dumps(value, sort_keys=True).encode()


@pytest.fixture
def configured(composed, tmp_path):
    c = composed
    c.config_path.chmod(0o600)
    c.worker_config_path.chmod(0o600)
    source = c.connection.source
    c.config["runtime_root"] = str(source.identity_runtime_root)
    c.config_path.write_bytes(encoded(c.config))
    shared_tool = tmp_path / "existing-shared-pin-tool.py"
    shared_tool.write_text("# fictional pinned shared tool\n", encoding="utf-8")
    c.connection.shared_tool = shared_tool
    value = {
        "contract": app.CONTRACT,
        "decision_id": source.decision_id,
        "source_receipt_id": source.receipt_id,
        "section": c.connection.section,
        "source_root": str(source.root),
        "identity_runtime_root": c.config["runtime_root"],
        "shared_tool": str(c.connection.shared_tool),
        "staging_config_path": str(c.config_path),
        "staging_config_sha256": hashlib.sha256(c.config_path.read_bytes()).hexdigest(),
    }
    path = tmp_path / "private-application.json"
    path.write_bytes(encoded(value))
    path.chmod(0o600)

    def kwargs():
        return {
            "config_path": path,
            "expected_config_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "runtime_check": lambda: None,
        }

    def owners():
        return (source.review, source.intake, c.canvas, c.google, c.store, c.journal)

    return c, value, path, kwargs, owners


def test_check_reads_no_database_or_clients(configured, monkeypatch, capsys):
    c, _, path, kwargs, _ = configured

    def refuse(*args, **kwargs):
        raise AssertionError("check created an owner or opened a database")

    import sqlite3

    monkeypatch.setattr(sqlite3, "connect", refuse)
    monkeypatch.setattr(app, "GradebookClient", refuse)
    monkeypatch.setattr(app, "GoogleSheets", refuse)
    monkeypatch.setattr(app, "Store", refuse)
    monkeypatch.setattr(app, "RefreshJournal", refuse)
    assert (
        app.main(
            [
                "--config",
                str(path),
                "--config-sha256",
                kwargs()["expected_config_sha256"],
                "--check",
            ]
        )
        == 0
    )
    result = json.loads(capsys.readouterr().out)
    assert (
        result["database_opens"]
        == result["network_calls"]
        == result["Canvas_writes"]
        == 0
    )
    assert result["real_case_checked"] is result["staging_enabled"] is False
    assert c.calls == {"canvas_reads": 0, "sheets_reads": 0, "posts": []}


def test_factory_composes_fixed_existing_real_owners_without_network(configured):
    c, value, _, kwargs, owners = configured
    before = c.domain.registry.connection.total_changes
    factory = app.build_owner_factory(*owners(), **kwargs())
    owner = factory(c.domain.token, c.domain.csrf)
    assert isinstance(owner, LocalGrAssEditOwner)
    assert (
        owner.canvas is c.canvas
        and owner.google is c.google
        and owner.journal is c.journal
    )
    assert owner.connection.store is c.store
    assert owner.connection.source.review is c.domain.review
    assert owner.connection.source.intake is c.domain.intake
    assert owner.connection.source.identity_runtime_root == Path(
        value["identity_runtime_root"]
    )
    assert owner.connection.source.decision_id == value["decision_id"]
    assert owner.connection.section == value["section"]
    assert c.domain.registry.connection.total_changes == before
    assert c.calls == {"canvas_reads": 0, "sheets_reads": 0, "posts": []}


@pytest.mark.parametrize(
    "field",
    ["source_root", "identity_runtime_root", "shared_tool", "staging_config_path"],
)
def test_missing_configured_paths_hold(configured, field):
    _, value, path, kwargs, _ = configured
    value[field] = str(path.parent / "missing")
    path.write_bytes(encoded(value))
    with pytest.raises(GradebookError):
        app.load_configuration(
            **{"path": path, "expected_sha256": kwargs()["expected_config_sha256"]}
        )


def test_symlink_and_nonprivate_config_hold(configured):
    _, _, path, kwargs, _ = configured
    linked = path.parent / "config-link"
    linked.symlink_to(path)
    with pytest.raises(GradebookError):
        app.load_configuration(linked, kwargs()["expected_config_sha256"])
    path.chmod(0o644)
    with pytest.raises(GradebookError, match="PRIVATE"):
        app.load_configuration(path, kwargs()["expected_config_sha256"])


def test_missing_real_case_holds_before_owner_and_network(configured, monkeypatch):
    c, value, path, kwargs, owners = configured
    value["decision_id"] = "f" * 64
    path.write_bytes(encoded(value))
    factory = app.build_owner_factory(*owners(), **kwargs())

    def refuse(*args, **kwargs):
        raise AssertionError("missing real case constructed an owner")

    monkeypatch.setattr(app, "LocalGrAssEditConnection", refuse)
    with pytest.raises(GradebookError, match="LOCAL_EDIT_CASE_OR_CONFIG_HELD"):
        factory(c.domain.token, c.domain.csrf)
    assert c.calls == {"canvas_reads": 0, "sheets_reads": 0, "posts": []}


def test_existing_config_drift_holds_before_network(configured):
    c, _, _, kwargs, owners = configured
    factory = app.build_owner_factory(*owners(), **kwargs())
    c.config_path.write_bytes(c.config_path.read_bytes() + b" ")
    with pytest.raises(GradebookError, match="HELD"):
        factory(c.domain.token, c.domain.csrf)
    assert c.calls == {"canvas_reads": 0, "sheets_reads": 0, "posts": []}


@pytest.mark.asyncio
async def test_application_defaults_disabled_without_factory_or_network(
    configured, monkeypatch
):
    c, _, _, kwargs, owners = configured

    def refuse(*args, **kwargs):
        raise AssertionError("disabled controller called runtime checker or factory")

    options = kwargs()
    options["runtime_check"] = refuse
    application = app.build_application(*owners(), **options)
    application.owner_factory = refuse
    with pytest.raises(Exception, match="LOCAL_EDIT_DISABLED"):
        await application.prepare(c.domain.token, c.domain.csrf)
    assert c.calls == {"canvas_reads": 0, "sheets_reads": 0, "posts": []}


@pytest.mark.asyncio
async def test_enabled_fictional_case_remains_held_without_network(configured):
    c, _, _, kwargs, owners = configured
    application = app.build_application(*owners(), **kwargs(), enabled=True)
    with pytest.raises(Exception, match="LOCAL_EDIT_REAL_POLICY_REQUIRED"):
        application._current(application.owner_factory(c.domain.token, c.domain.csrf))
    with pytest.raises(Exception, match="LOCAL_EDIT_REAL_POLICY_REQUIRED"):
        await application.prepare(c.domain.token, c.domain.csrf)
    assert c.calls == {"canvas_reads": 0, "sheets_reads": 0, "posts": []}


def test_config_cannot_enable_staging_or_supply_browser_callback(configured):
    _, value, path, kwargs, _ = configured
    value["enabled"] = True
    value["owner_factory"] = "untrusted.import.callback"
    path.write_bytes(encoded(value))
    with pytest.raises(GradebookError, match="CONFIGURATION_INVALID"):
        app.load_configuration(path, kwargs()["expected_config_sha256"])


def test_changed_assignment_binding_pin_holds(configured):
    c, _, path, kwargs, _ = configured
    c.connection.assignment_path.write_bytes(
        c.connection.assignment_path.read_bytes() + b" "
    )
    with pytest.raises(GradebookError, match="ASSIGNMENT_BINDINGS_CHANGED"):
        app.load_configuration(path, kwargs()["expected_config_sha256"])


def test_wrong_existing_workbook_cannot_be_composed(configured):
    c, _, _, kwargs, owners = configured
    c.journal.workbook_id = "different-fictional-workbook"
    with pytest.raises(GradebookError, match="LOCAL_EDIT_APP_OWNER_MISMATCH"):
        app.build_owner_factory(*owners(), **kwargs())
    assert c.calls == {"canvas_reads": 0, "sheets_reads": 0, "posts": []}


def test_oversized_assignment_bindings_hold_even_with_matching_hash(configured):
    c, value, path, kwargs, _ = configured
    raw = encoded([{"fictional": "x" * (2 * 1024 * 1024)}])
    c.connection.assignment_path.write_bytes(raw)
    c.config["assignment_bindings_sha256"] = hashlib.sha256(raw).hexdigest()
    c.config_path.write_bytes(encoded(c.config))
    value["staging_config_sha256"] = hashlib.sha256(
        c.config_path.read_bytes()
    ).hexdigest()
    path.write_bytes(encoded(value))
    with pytest.raises(GradebookError, match="CONFIGURATION_INVALID"):
        app.load_configuration(path, kwargs()["expected_config_sha256"])
    assert c.calls == {"canvas_reads": 0, "sheets_reads": 0, "posts": []}


def test_enabled_application_requires_trusted_runtime_checker(configured):
    _, _, path, kwargs, owners = configured
    with pytest.raises(GradebookError, match="LOCAL_EDIT_RUNTIME_CHECK_REQUIRED"):
        app.build_application(
            *owners(),
            config_path=path,
            expected_config_sha256=kwargs()["expected_config_sha256"],
            enabled=True,
        )


@pytest.mark.asyncio
async def test_runtime_drift_before_prepare_holds_without_network(configured):
    c, _, _, kwargs, owners = configured
    options = kwargs()

    def changed():
        raise RuntimeError("fictional private path must not escape")

    options["runtime_check"] = changed
    application = app.build_application(*owners(), **options, enabled=True)
    with pytest.raises(Exception, match="HELD") as held:
        await application.prepare(c.domain.token, c.domain.csrf)
    assert "private path" not in str(held.value)
    assert c.calls == {"canvas_reads": 0, "sheets_reads": 0, "posts": []}


@pytest.mark.asyncio
async def test_retained_owner_source_rechecks_runtime_on_execute_validation(configured):
    c, _, _, kwargs, owners = configured
    state = {"valid": True, "checks": 0}

    def check():
        state["checks"] += 1
        if not state["valid"]:
            raise RuntimeError("fictional changed code")

    options = kwargs()
    options["runtime_check"] = check
    factory = app.build_owner_factory(*owners(), **options)
    owner = factory(c.domain.token, c.domain.csrf)
    snapshot = owner.connection.source.read()
    assert state["checks"] == 3  # factory, before read, after read
    state["valid"] = False
    # assert_current dynamically calls this concrete source's guarded read,
    # including when execute retains the owner and never invokes factory again.
    with pytest.raises(GradebookError, match="IMMUTABLE_RUNTIME_HELD"):
        owner.connection.source.assert_current(snapshot)
    assert state["checks"] == 4
    application = app.build_application(*owners(), **options, enabled=True)
    preview = "e" * 64
    # Seed only the fictional in-memory retained-preview state. No academic
    # policy, decision, stored plan or production guard is changed by the test.
    application._previews[preview] = {
        "session": application._session(c.domain.token, c.domain.csrf)[0],
        "decision_id": application.decision_id,
        "state": "PREPARED",
        "expires": c.domain.review.clock() + 60,
        "owner": owner,
        "source": snapshot,
        "plan_id": "f" * 64,
    }
    with pytest.raises(Exception, match="LOCAL_EDIT_RECONCILIATION_REQUIRED"):
        await application.execute(c.domain.token, c.domain.csrf, preview)
    assert state["checks"] == 5
    assert application._previews[preview]["state"] == "EXECUTION_STARTED"
    assert c.calls == {"canvas_reads": 0, "sheets_reads": 0, "posts": []}


def test_runtime_drift_during_source_read_is_rejected(configured):
    c, _, _, kwargs, owners = configured
    calls = []

    def check():
        calls.append(None)
        if len(calls) == 3:
            raise RuntimeError("fictional changed after source read")

    options = kwargs()
    options["runtime_check"] = check
    owner = app.build_owner_factory(*owners(), **options)(c.domain.token, c.domain.csrf)
    with pytest.raises(GradebookError, match="IMMUTABLE_RUNTIME_HELD"):
        owner.connection.source.read()
    assert len(calls) == 3
    assert c.calls == {"canvas_reads": 0, "sheets_reads": 0, "posts": []}


def configure_preserved_cell(configured, tmp_path):
    c, value, path, kwargs, owners = configured
    transfer = c.connection.prepare(**c.context)["transfer"]
    state = native._state(c.state["raw"])
    cell = state["sheets"][2]["cells"]["5:2"]
    cell.update(
        userEnteredValue={"numberValue": 4},
        note="Original retained teacher note.\nExact prefix.",
    )
    c.state["raw"] = raw_from_state(state)
    portable = json.loads(json.dumps(native._state(c.state["raw"])))
    permit = {
        "contract": "EXACT_LOCAL_EDIT_PRESERVATION_V1",
        "authorization_ref": "sha256:" + "8" * 64,
        "selection_sha256": transfer["selection_sha256"],
        "spreadsheet_id": c.context["binding"]["spreadsheet_id"],
        "course_id": "12",
        "user_id": "101",
        "assignment_id": "21",
        "baseline_sha256": digest(c.context["baseline"]),
        "current_basis_sha256": digest(transfer["current_basis"]),
        "before_state_sha256": digest(portable),
        "cell_sha256": digest(portable["sheets"]["2"]["cells"]["5:2"]),
        "prior_value": 4,
        "prior_note": cell["note"],
    }
    permit_path = tmp_path / "private-exact-preservation.json"
    permit_path.write_bytes(encoded(permit))
    permit_path.chmod(0o600)
    c.config.update(
        edit_preservation_path=str(permit_path),
        edit_preservation_sha256=hashlib.sha256(permit_path.read_bytes()).hexdigest(),
    )
    c.config_path.write_bytes(encoded(c.config))
    value["staging_config_sha256"] = hashlib.sha256(
        c.config_path.read_bytes()
    ).hexdigest()
    path.write_bytes(encoded(value))
    owner = app.build_owner_factory(*owners(), **kwargs())(
        c.domain.source.token, c.domain.source.csrf
    )
    return c, owner, permit_path


@pytest.mark.asyncio
async def test_pinned_operator_preservation_through_actual_owner_sends_one_cell_once(
    configured, tmp_path
):
    c, owner, _ = configure_preserved_cell(configured, tmp_path)
    before = json.loads(json.dumps(native._state(c.state["raw"])))
    prepared = await owner.prepare()
    plan = c.store.load("review", prepared["plan_id"])
    assert plan["transfer"]["before_state"] == before
    assert plan["transfer"]["before_state"]["sheets"]["2"]["cells"]["5:2"][
        "userEnteredValue"
    ] == {"numberValue": 4}
    result = await owner.execute(prepared["plan_id"], enabled=True)
    assert result["status"] == "PLANNED_OUTPUT_OBSERVED"
    assert len(c.calls["posts"]) == 1
    update = c.calls["posts"][0][0]["updateCells"]
    assert update["fields"] == "userEnteredValue,note"
    replacement = update["rows"][0]["values"][0]
    assert replacement["userEnteredValue"] == {"numberValue": 7}
    assert replacement["note"].startswith(
        before["sheets"]["2"]["cells"]["5:2"]["note"] + "\n\n"
    )
    assert replacement["note"].endswith("Explicit fictional final feedback.")
    before["sheets"]["2"]["cells"]["5:2"].update(replacement)
    assert json.loads(json.dumps(native._state(c.state["raw"]))) == before
    again = await owner.execute(prepared["plan_id"], enabled=True)
    assert again["status"] == "PLANNED_OUTPUT_OBSERVED"
    assert len(c.calls["posts"]) == 1
    assert result["canvas_writes"] == 0
    assert result["publication_allowed"] is False


@pytest.mark.asyncio
async def test_changed_operator_preservation_file_holds_before_send(
    configured, tmp_path
):
    c, owner, permit_path = configure_preserved_cell(configured, tmp_path)
    prepared = await owner.prepare()
    permit_path.write_bytes(permit_path.read_bytes() + b" ")
    before_reads = (c.calls["canvas_reads"], c.calls["sheets_reads"])
    with pytest.raises(GradebookError, match="EXACT_EDIT_PRESERVATION_CHANGED"):
        await owner.execute(prepared["plan_id"], enabled=True)
    assert (c.calls["canvas_reads"], c.calls["sheets_reads"]) == before_reads
    assert c.calls["posts"] == []


@pytest.mark.parametrize(
    "changed", ["missing_hash", "not_private", "different_connection"]
)
def test_preservation_config_cannot_be_partial_or_unbound(
    configured, tmp_path, changed
):
    c, owner, permit_path = configure_preserved_cell(configured, tmp_path)
    if changed == "missing_hash":
        c.config.pop("edit_preservation_sha256")
        c.config_path.write_bytes(encoded(c.config))
        owner.config_sha256 = hashlib.sha256(c.config_path.read_bytes()).hexdigest()
    elif changed == "not_private":
        permit_path.chmod(0o644)
    else:
        owner.connection.preservation = None
    with pytest.raises(GradebookError, match="EXACT_EDIT_"):
        owner._configuration()
    assert c.calls == {"canvas_reads": 0, "sheets_reads": 0, "posts": []}
