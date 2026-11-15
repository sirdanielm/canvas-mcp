"""Fictional owner wiring; fake callbacks only and no network or live writes."""

import copy
import hashlib
import json
from contextlib import contextmanager
from types import ModuleType

import pytest
from test_canvas_primary_review import case as case
from test_gradebook import snapshot as snapshot
from test_gradebook_native import binding as binding

from canvas_mcp.gradebook.canvas_primary_owner import CanvasPrimaryEditConnection
from canvas_mcp.gradebook.client import GradebookError
from canvas_mcp.gradebook.localgrass_edit_execution import execute_local_edit_once
from canvas_mcp.gradebook.model import digest
from canvas_mcp.gradebook.store import Store


@pytest.fixture
def connection(case, tmp_path):
    from test_gradebook_native import raw_from_state

    from canvas_mcp.gradebook import native

    state = native._state(case["raw"])
    sheet = copy.deepcopy(state["sheets"][1])
    sheet["properties"]["sheetId"] = 99
    sheet["properties"]["title"] = "Student Info"
    sheet["cells"] = {}
    for col, name in enumerate(
        ("Canvas ID", "Student Number", "Canvas Enrollment", "Course", "Section")
    ):
        sheet["cells"][f"0:{col}"] = {"userEnteredValue": {"stringValue": name}}
    for col, value in enumerate(
        (
            case["record"]["user_id"],
            case["record"]["pin"],
            "Active",
            case["binding"]["label"],
            case["record"]["section"],
        )
    ):
        sheet["cells"][f"1:{col}"] = {"userEnteredValue": {"stringValue": value}}
    state["sheets"][99] = sheet
    case["raw"] = raw_from_state(state)

    class Authority:
        ready = False
        refresh_count = 0

        async def refresh(self, canvas, evidence):
            self.ready = False
            self.refresh_count += 1
            if (
                canvas != "fictional-canvas"
                and getattr(canvas, "label", None) != "fictional-canvas"
            ):
                raise ValueError("not current")
            case["authority"](evidence)
            self.ready = True

        def assert_protection_current(self, registry, target):
            if registry != self.expected_registry:
                raise ValueError("unverified protection source")

        def assert_current(self, evidence):
            if not self.ready:
                raise ValueError("fresh source missing")
            case["authority"](evidence)

    files = ModuleType("fictional_files")
    files.file_sha = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
    files.load = lambda p: json.loads(p.read_text(encoding="utf-8"))
    files.local_path = lambda p: p
    files.private_directory = lambda p: p.mkdir(parents=True, exist_ok=True) or p

    @contextmanager
    def locked(_):
        yield

    files.locked = locked

    def write(path, data):
        path.write_bytes(data if isinstance(data, bytes) else json.dumps(data).encode())

    files.write = write
    target = {
        k: v
        for k, v in case["assignment_binding"].items()
        if k not in ("assignment_metadata", "assignment_metadata_sha256")
    }
    path = tmp_path / "bindings.json"
    path.write_text(json.dumps([target]), encoding="utf-8")
    policy = {
        "contract": "CANVAS_PRIMARY_TARGET_PROTECTION_V1",
        "population_state": "COMPLETE",
        "population_evidence_sha256": "a" * 64,
        "protected_students": [
            {"user_id": "202", "evidence_sha256": "b" * 64},
            {"user_id": "303", "evidence_sha256": "c" * 64},
        ],
        "coverage": [],
        "protected_targets": [],
    }
    policy_path = tmp_path / "private-protection.json"
    policy_path.write_text(json.dumps(policy), encoding="utf-8")
    policy_path.chmod(0o600)
    auth = Authority()
    auth.expected_registry = copy.deepcopy(policy)
    return CanvasPrimaryEditConnection(
        store=Store(tmp_path / "store"),
        files=files,
        authority=auth,
        evidence=case["evidence"],
        record=case["record"],
        proposal=case["proposal"],
        assignment_bindings_path=path,
        expected_assignment_bindings_sha256=files.file_sha(path),
        registry_path=tmp_path / "registry.json",
        protection_registry_path=policy_path,
        expected_protection_registry_sha256=files.file_sha(policy_path),
    )


@pytest.mark.asyncio
async def test_owner_fresh_source_plan_and_revalidation(connection, case):
    with pytest.raises(GradebookError):
        connection.assignment_targets(
            course_id=case["record"]["course_id"], pin_binding=case["pin_binding"]
        )
    await connection.refresh_source("fictional-canvas")
    plan = connection.prepare(
        **{k: case[k] for k in ("raw", "binding", "baseline", "current", "pin_binding")}
    )
    assert plan["canvas_writes"] == plan["sheets_writes"] == 0
    assert plan["publication_allowed"] is False
    assert plan["items"] == [{"key": "101:21"}]
    connection.revalidate(
        plan,
        expected_plan_sha256=digest(plan),
        raw=case["raw"],
        current=case["current"],
        pin_binding=case["pin_binding"],
    )
    assert (
        connection.classify(plan, case["raw"], expected_plan_sha256=digest(plan))[
            "status"
        ]
        == "BEFORE_STILL_PRESENT"
    )


@pytest.mark.asyncio
async def test_disabled_executor_never_writes(connection, case, tmp_path):
    await connection.refresh_source("fictional-canvas")
    plan = connection.prepare(
        **{k: case[k] for k in ("raw", "binding", "baseline", "current", "pin_binding")}
    )

    def forbidden(*args):
        raise AssertionError("unexpected call")

    result = await execute_local_edit_once(
        connection,
        plan,
        expected_plan_sha256=digest(plan),
        output_root=tmp_path / "history",
        read_context=forbidden,
        write_requests=forbidden,
    )
    assert result["status"] == "LOCAL_EDIT_WRITE_DISABLED"


def test_owner_accepts_independent_primary_but_rejects_a_duck_type(
    connection, case, tmp_path, monkeypatch
):
    from types import SimpleNamespace

    from canvas_mcp.gradebook import localgrass_edit_owner
    from canvas_mcp.gradebook.client import GradebookClient
    from canvas_mcp.gradebook.google import GoogleSheets
    from canvas_mcp.gradebook.localgrass_draft_edit import LocalGrAssDraftEditConnection
    from canvas_mcp.gradebook.localgrass_edit_owner import LocalGrAssEditOwner
    from canvas_mcp.gradebook.worker import RefreshJournal

    assert not isinstance(connection, LocalGrAssDraftEditConnection)
    config = {"output_root": tmp_path, "runtime_root": tmp_path}
    monkeypatch.setattr(LocalGrAssEditOwner, "_configuration", lambda self: config)
    monkeypatch.setattr(
        localgrass_edit_owner,
        "importlib",
        SimpleNamespace(import_module=lambda name: SimpleNamespace()),
    )
    canvas = object.__new__(GradebookClient)
    google = object.__new__(GoogleSheets)
    google.workbook_id = case["binding"]["spreadsheet_id"]
    journal = object.__new__(RefreshJournal)
    journal.root = connection.store.root / "refresh-journal"
    journal.workbook_id = google.workbook_id

    def owner(candidate):
        return LocalGrAssEditOwner(
            candidate,
            canvas,
            google,
            journal,
            staging_config_path=tmp_path / "staging.json",
            expected_staging_config_sha256="a" * 64,
            binding=case["binding"],
        )

    assert owner(connection).connection is connection
    duck = SimpleNamespace(**vars(connection))
    for name in ("prepare", "validate_plan", "revalidate", "classify"):
        setattr(duck, name, getattr(connection, name))
    with pytest.raises(GradebookError, match="EXISTING_LOCAL_EDIT_OWNERS_REQUIRED"):
        owner(duck)


@pytest.mark.asyncio
async def test_executor_rejects_a_duck_type_before_any_callback(connection, tmp_path):
    from types import SimpleNamespace

    def forbidden(*args, **kwargs):
        raise AssertionError("Unrecognized connection reached a callback")

    duck = SimpleNamespace(
        **vars(connection),
        contract=connection.contract,
        validate_plan=forbidden,
        revalidate=forbidden,
        classify=forbidden,
    )
    with pytest.raises(GradebookError, match="AUTHENTICATED_CONNECTION_REQUIRED"):
        await execute_local_edit_once(
            duck,
            {},
            expected_plan_sha256="a" * 64,
            output_root=tmp_path,
            read_context=forbidden,
            write_requests=forbidden,
        )


@pytest.mark.asyncio
async def test_changed_assignment_binding_and_source_hold(connection, case):
    await connection.refresh_source("fictional-canvas")
    plan = connection.prepare(
        **{k: case[k] for k in ("raw", "binding", "baseline", "current", "pin_binding")}
    )
    changed = copy.deepcopy(case["current"])
    changed["cells"]["101:21"]["attempt"] += 1
    with pytest.raises(GradebookError):
        connection.revalidate(
            plan,
            expected_plan_sha256=digest(plan),
            raw=case["raw"],
            current=changed,
            pin_binding=case["pin_binding"],
        )
    connection.assignment_path.write_text("[]", encoding="utf-8")
    with pytest.raises(GradebookError, match="ASSIGNMENT_BINDINGS_CHANGED"):
        connection.revalidate(
            plan,
            expected_plan_sha256=digest(plan),
            raw=case["raw"],
            current=case["current"],
            pin_binding=case["pin_binding"],
        )


@pytest.mark.asyncio
async def test_failed_refresh_invalidates_previous_seal(connection, case):
    await connection.refresh_source("fictional-canvas")
    with pytest.raises(ValueError):
        await connection.refresh_source("wrong-canvas")
    with pytest.raises(GradebookError):
        connection.assignment_targets(
            course_id=case["record"]["course_id"], pin_binding=case["pin_binding"]
        )


@pytest.mark.asyncio
async def test_fake_one_shot_and_repeat_does_not_resend(connection, case, tmp_path):
    from test_gradebook_native import raw_from_state

    from canvas_mcp.gradebook import native

    await connection.refresh_source("fictional-canvas")
    plan = connection.prepare(
        **{k: case[k] for k in ("raw", "binding", "baseline", "current", "pin_binding")}
    )
    state = {"raw": copy.deepcopy(case["raw"]), "writes": 0}

    def read():
        return {
            "raw": state["raw"],
            "current": case["current"],
            "pin_binding": case["pin_binding"],
        }

    def write(spreadsheet, requests):
        assert spreadsheet == case["binding"]["spreadsheet_id"]
        assert len(requests) == 1
        item = requests[0]["updateCells"]
        assert item["fields"] == "userEnteredValue"
        native_state = native._state(state["raw"])
        start = item["start"]
        address = f"{start['rowIndex']}:{start['columnIndex']}"
        native_state["sheets"][start["sheetId"]]["cells"][address].update(
            item["rows"][0]["values"][0]
        )
        state["raw"] = raw_from_state(native_state)
        state["writes"] += 1

    kwargs = {
        "expected_plan_sha256": digest(plan),
        "output_root": tmp_path / "history",
        "read_context": read,
        "write_requests": write,
        "enabled": True,
    }
    result = await execute_local_edit_once(connection, plan, **kwargs)
    assert result["status"] == "PLANNED_OUTPUT_OBSERVED"
    assert state["writes"] == 1
    again = await execute_local_edit_once(connection, plan, **kwargs)
    assert again["status"] == "PLANNED_OUTPUT_OBSERVED"
    assert state["writes"] == 1


@pytest.mark.asyncio
async def test_composed_owner_refreshes_before_send_but_not_reconcile_or_disabled(
    connection, case, tmp_path
):
    from types import SimpleNamespace

    from test_gradebook_native import raw_from_state

    from canvas_mcp.gradebook import native
    from canvas_mcp.gradebook.localgrass_edit_owner import LocalGrAssEditOwner

    reads = []

    class Canvas:
        label = "fictional-canvas"
        origin = case["current"]["origin"]

        async def snapshot(self, course_id):
            assert course_id == case["record"]["course_id"]
            assert connection.authority.ready
            reads.append("snapshot")
            current = copy.deepcopy(case["current"])
            for assignment in current["assignments"]:
                assignment.pop("assignment_metadata", None)
                assignment.pop("assignment_metadata_sha256", None)
            return current

        async def get(self, path):
            assert path.endswith("/assignments/" + case["record"]["assignment_id"])
            reads.append("assignment")
            return copy.deepcopy(case["assignment_binding"]["assignment_metadata"])

    class Google:
        workbook_id = case["binding"]["spreadsheet_id"]

        def __init__(self):
            self.raw = copy.deepcopy(case["raw"])
            self.writes = 0

        async def read_workbook(self):
            reads.append("native")
            return copy.deepcopy(self.raw)

        async def send_preflighted_batch(self, requests):
            assert len(requests) == 1
            update = requests[0]["updateCells"]
            state = native._state(self.raw)
            point = update["start"]
            address = f"{point['rowIndex']}:{point['columnIndex']}"
            state["sheets"][point["sheetId"]]["cells"][address].update(
                update["rows"][0]["values"][0]
            )
            self.raw = raw_from_state(state)
            self.writes += 1

    class Journal:
        @contextmanager
        def exclusive(self):
            yield

    owner = object.__new__(LocalGrAssEditOwner)
    owner.connection, owner.canvas, owner.google, owner.journal = (
        connection,
        Canvas(),
        Google(),
        Journal(),
    )
    owner.binding = case["binding"]
    owner.runtime_root = tmp_path
    owner.output_root = tmp_path / "history"
    owner._configuration = lambda: None
    owner._check_owner = lambda **kwargs: None
    owner._pin_module = SimpleNamespace(
        canonical_pin_binding=lambda *args: copy.deepcopy(case["pin_binding"])
    )
    await connection.refresh_source(owner.canvas)
    plan = connection.prepare(
        **{k: case[k] for k in ("raw", "binding", "baseline", "current", "pin_binding")}
    )
    plan_id, _ = connection.store.save("review", plan)
    count = connection.authority.refresh_count
    disabled = await owner.execute(plan_id)
    assert disabled["status"] == "LOCAL_EDIT_WRITE_DISABLED"
    assert connection.authority.refresh_count == count and owner.google.writes == 0
    assert reads == []
    sent = await owner.execute(plan_id, enabled=True)
    assert sent["status"] == "PLANNED_OUTPUT_OBSERVED"
    assert connection.authority.refresh_count == count + 2 and owner.google.writes == 1
    assert reads[:3] == ["snapshot", "assignment", "native"]
    assert reads.count("assignment") == 2
    again = await owner.execute(plan_id, enabled=True)
    assert again["status"] == "PLANNED_OUTPUT_OBSERVED"
    assert connection.authority.refresh_count == count + 2 and owner.google.writes == 1
    assert reads.count("assignment") == 2


@pytest.mark.asyncio
async def test_current_student_info_identity_or_pin_drift_holds(connection, case):
    from test_gradebook_native import raw_from_state

    from canvas_mcp.gradebook import native

    await connection.refresh_source("fictional-canvas")
    plan = connection.prepare(
        **{k: case[k] for k in ("raw", "binding", "baseline", "current", "pin_binding")}
    )
    for column, bad in (
        (0, "999"),
        (1, "8888"),
        (2, "Inactive"),
        (3, "Other"),
        (4, "Wrong"),
    ):
        state = native._state(case["raw"])
        state["sheets"][99]["cells"][f"1:{column}"]["userEnteredValue"][
            "stringValue"
        ] = bad
        with pytest.raises(GradebookError, match="PRIMARY_CURRENT_STUDENT_INFO_HELD"):
            connection.revalidate(
                plan,
                expected_plan_sha256=digest(plan),
                raw=raw_from_state(state),
                current=case["current"],
                pin_binding=case["pin_binding"],
            )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "mutation",
    ["duplicate_row", "duplicate_header", "numeric_id", "formula_pin", "missing_sheet"],
)
async def test_nonliteral_and_duplicate_identity_cells_hold(connection, case, mutation):
    from test_gradebook_native import raw_from_state

    from canvas_mcp.gradebook import native

    await connection.refresh_source("fictional-canvas")
    state = native._state(case["raw"])
    cells = state["sheets"][99]["cells"]
    if mutation == "duplicate_row":
        for col in range(5):
            cells[f"2:{col}"] = copy.deepcopy(cells[f"1:{col}"])
    elif mutation == "duplicate_header":
        cells["0:8"] = copy.deepcopy(cells["0:0"])
    elif mutation == "numeric_id":
        cells["2:0"] = {"userEnteredValue": {"numberValue": 101}}
    elif mutation == "formula_pin":
        cells["2:1"] = {"userEnteredValue": {"formulaValue": '= "0042"'}}
    else:
        del state["sheets"][99]
    with pytest.raises(GradebookError, match="PRIMARY_CURRENT_STUDENT_INFO_HELD"):
        connection.prepare(
            **{
                **{
                    k: case[k]
                    for k in ("binding", "baseline", "current", "pin_binding")
                },
                "raw": raw_from_state(state),
            }
        )


@pytest.mark.asyncio
async def test_registry_change_blocks_existing_plan_before_send(connection, case):
    await connection.refresh_source("fictional-canvas")
    plan = connection.prepare(
        **{k: case[k] for k in ("raw", "binding", "baseline", "current", "pin_binding")}
    )
    # A newer registry means the pinned authority/config must be reviewed anew.
    connection.protection_registry_path.write_text("{}", encoding="utf-8")
    with pytest.raises(GradebookError, match="PROTECTION_REGISTRY_HELD"):
        connection.revalidate(
            plan,
            expected_plan_sha256=digest(plan),
            raw=case["raw"],
            current=case["current"],
            pin_binding=case["pin_binding"],
        )


@pytest.mark.asyncio
async def test_single_transfer_layout_is_bound_and_legacy_recovery_remains_readable(
    connection, case
):
    await connection.refresh_source("fictional-canvas")
    plan = connection.prepare(
        **{k: case[k] for k in ("raw", "binding", "baseline", "current", "pin_binding")}
    )
    assert plan["plan_layout"] == "SINGLE_TRANSFER_V1"
    assert "transfer" not in plan["primary_plan"]
    assert plan["primary_plan"]["transfer_sha256"] == digest(plan["transfer"])
    connection.validate_plan(plan, expected_plan_sha256=digest(plan))
    legacy = copy.deepcopy(plan)
    legacy.pop("plan_layout")
    legacy["primary_plan"].pop("transfer_sha256")
    legacy["primary_plan"]["transfer"] = copy.deepcopy(legacy["transfer"])
    connection.validate_plan(legacy, expected_plan_sha256=digest(legacy))
    connection.revalidate(
        legacy,
        expected_plan_sha256=digest(legacy),
        raw=case["raw"],
        current=case["current"],
        pin_binding=case["pin_binding"],
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "mutation",
    [
        "transfer",
        "transfer_pin",
        "missing_pin",
        "duplicate_transfer",
        "layout",
        "approval_flag",
        "protection_pin",
    ],
)
async def test_single_transfer_tampering_holds_even_with_recomputed_outer_digest(
    connection, case, mutation
):
    await connection.refresh_source("fictional-canvas")
    plan = connection.prepare(
        **{k: case[k] for k in ("raw", "binding", "baseline", "current", "pin_binding")}
    )
    if mutation == "transfer":
        plan["transfer"]["canvas_writes"] = 1
    elif mutation == "transfer_pin":
        plan["primary_plan"]["transfer_sha256"] = "0" * 64
    elif mutation == "missing_pin":
        del plan["primary_plan"]["transfer_sha256"]
    elif mutation == "duplicate_transfer":
        plan["primary_plan"]["transfer"] = copy.deepcopy(plan["transfer"])
    elif mutation == "approval_flag":
        plan["primary_plan"]["teacher_accepted"] = True
    elif mutation == "protection_pin":
        plan["primary_plan"]["protection_registry_sha256"] = "bad"
    else:
        plan["plan_layout"] = "UNKNOWN"
    with pytest.raises(GradebookError, match="PRIMARY_OWNER_PLAN_CHANGED"):
        connection.validate_plan(plan, expected_plan_sha256=digest(plan))


def test_observed_format_owner_hook_requires_fresh_trusted_exact_receipt(
    connection, case
):
    connection.evidence["observed_format_sha256"] = "a" * 64
    calls = []
    connection.authority.assert_current = lambda evidence: None
    connection.authority.assert_observed_format = (
        lambda raw, binding, baseline, receipt: calls.append(receipt)
    )
    with pytest.raises(GradebookError, match="OBSERVED_FORMAT_AUTHORITY_REQUIRED"):
        connection._assert_observed_format(
            case["raw"], case["binding"], case["baseline"], "a" * 64
        )
    connection._source_fresh = True
    with pytest.raises(GradebookError, match="OBSERVED_FORMAT_AUTHORITY_REQUIRED"):
        connection._assert_observed_format(
            case["raw"], case["binding"], case["baseline"], "b" * 64
        )
    connection._assert_observed_format(
        case["raw"], case["binding"], case["baseline"], "a" * 64
    )
    assert calls == ["a" * 64]
    del connection.authority.assert_observed_format
    with pytest.raises(GradebookError, match="OBSERVED_FORMAT_AUTHORITY_REQUIRED"):
        connection._assert_observed_format(
            case["raw"], case["binding"], case["baseline"], "a" * 64
        )
