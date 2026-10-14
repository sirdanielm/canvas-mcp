"""Fictional GET-only refresh regressions; no live transports or identities."""

import copy
import json

import pytest
from test_gradebook import snapshot as snapshot
from test_gradebook_native import binding as binding
from test_gradebook_native import initial_raw, raw_from_state

from canvas_mcp.gradebook import native
from canvas_mcp.gradebook.client import GradebookError
from canvas_mcp.gradebook.get_only_refresh import (
    prepare_get_only_refresh,
    validate_get_workbook,
    verify_get_only_output,
)
from canvas_mcp.gradebook.model import digest
from canvas_mcp.gradebook.store import Store


class Canvas:
    def __init__(self, snapshot):
        self.origin = "https://school.example"
        self.current = copy.deepcopy(snapshot)
        self.reads = []

    async def snapshot(self, course_id):
        self.reads.append(course_id)
        return copy.deepcopy(self.current)


@pytest.fixture
def scenario(snapshot, binding, tmp_path):
    store = Store(tmp_path)
    store.save("snapshot", snapshot)
    before = initial_raw(snapshot, binding)
    state = native._state(before)
    # Deliberate pending proposal, full feedback and unrelated Edit formula.
    state["sheets"][2]["cells"]["5:2"]["userEnteredValue"] = {"numberValue": 20}
    state["sheets"][2]["cells"]["5:2"]["note"] = "Teacher feedback\nPreserve exactly."
    state["sheets"][2]["cells"]["20:10"] = {
        "userEnteredValue": {"formulaValue": "=1+1"},
        "note": "Unmapped teacher data",
        "userEnteredFormat": {"textFormat": {"italic": True}},
    }
    return raw_from_state(state), Canvas(snapshot), store, binding


def apply(before, plan, binding):
    state = native._state(before)
    native._apply_requests(state, plan["batch_update"]["requests"], binding)
    return raw_from_state(state)


def literal(raw, sid, address):
    return native._literal_cells(native._state(raw)["sheets"][sid])[address]


def test_validator_treats_edit_as_opaque(scenario):
    before, _, _, binding = scenario
    views = validate_get_workbook(before, {"core": binding})
    assert set(views["core"]) == {"Canvas", "_Sync"}
    assert views["core"]["Canvas"]["C6"] == 10
    with pytest.raises(GradebookError):
        native.validate_workbook(before, {"core": binding})


@pytest.mark.asyncio
async def test_refresh_preserves_all_edit_fields_and_original_baseline(scenario):
    before, canvas, store, binding = scenario
    canvas.current["cells"]["101:21"].update(value=18, grade="18")
    plan = await prepare_get_only_refresh(canvas, store, "core", binding, before)
    assert canvas.reads == ["12"]
    assert "pending_edits" not in plan
    assert len(plan["batch_update"]["requests"]) == 9
    after = apply(before, plan, binding)
    verify_get_only_output(before, after, {"core": plan}, store, {"core": binding})
    first, second = native._state(before), native._state(after)
    assert first["sheets"][2] == second["sheets"][2]
    assert first["sheets"][4] == second["sheets"][4]
    assert literal(after, 1, "C6") == 18
    assert literal(after, 3, "B2") == literal(before, 3, "B2")
    assert literal(after, 3, "B9") == plan["canvas_snapshot_id"]
    assert literal(after, 3, "B5") == canvas.current["fetched_at"]


@pytest.mark.asyncio
async def test_roster_and_assignments_can_expand_without_touching_edit(scenario):
    before, canvas, store, binding = scenario
    student = copy.deepcopy(canvas.current["students"][0])
    student.update(id="102", name="Fictional second student")
    assignment = copy.deepcopy(canvas.current["assignments"][0])
    assignment.update(id="22", name="Fictional second assignment")
    canvas.current["students"] = [student, *canvas.current["students"]]
    canvas.current["assignments"] = [assignment, *canvas.current["assignments"]]
    for uid, aid in (("102", "21"), ("102", "22"), ("101", "22")):
        cell = copy.deepcopy(canvas.current["cells"]["101:21"])
        cell.update(value=12, grade="12")
        canvas.current["cells"][f"{uid}:{aid}"] = cell
    plan = await prepare_get_only_refresh(canvas, store, "core", binding, before)
    after = apply(before, plan, binding)
    verify_get_only_output(before, after, [plan], store, {"core": binding})
    assert literal(after, 1, "A6") == "101"
    assert literal(after, 1, "A7") == "102"
    assert literal(after, 1, "C5") == "21"
    assert literal(after, 1, "D5") == "22"
    assert literal(after, 1, "D7") == 12
    assert native._state(before)["sheets"][2] == native._state(after)["sheets"][2]


@pytest.mark.asyncio
async def test_plan_survives_immutable_store_and_json_roundtrip(scenario):
    before, canvas, store, binding = scenario
    plan = await prepare_get_only_refresh(canvas, store, "core", binding, before)
    retained = json.loads(json.dumps(store.load("refresh", plan["refresh_id"])))
    after = apply(before, retained, binding)
    verify_get_only_output(before, after, {"core": retained}, store, {"core": binding})


@pytest.mark.asyncio
@pytest.mark.parametrize("field,value", [("course_id", "13"), ("origin", "https://other.example")])
async def test_wrong_course_or_origin_cannot_self_validate(scenario, field, value):
    before, canvas, store, binding = scenario
    canvas.current[field] = value
    with pytest.raises(GradebookError, match="course or origin"):
        await prepare_get_only_refresh(canvas, store, "core", binding, before)


@pytest.mark.parametrize("change", ["protection", "identity", "duplicate", "gap"])
def test_get_ownership_or_identity_changes_hold(scenario, change):
    before, _, _, binding = scenario
    state = native._state(before)
    sheet = state["sheets"][1]
    if change == "protection":
        sheet["protectedRanges"] = []
    elif change == "identity":
        sheet["properties"]["title"] = "Renamed GET"
    elif change == "duplicate":
        sheet["cells"]["6:0"] = copy.deepcopy(sheet["cells"]["5:0"])
    else:
        sheet["cells"]["7:0"] = copy.deepcopy(sheet["cells"]["5:0"])
    with pytest.raises(GradebookError):
        validate_get_workbook(raw_from_state(state), {"core": binding})


@pytest.mark.asyncio
@pytest.mark.parametrize("target", ["get_note", "edit_note", "baseline", "reference"])
async def test_any_protected_readback_drift_holds(scenario, target):
    before, canvas, store, binding = scenario
    plan = await prepare_get_only_refresh(canvas, store, "core", binding, before)
    after = apply(before, plan, binding)
    state = native._state(after)
    if target == "baseline":
        state["sheets"][3]["cells"]["1:1"]["userEnteredValue"] = {"stringValue": "0" * 64}
    else:
        sid, address = {"get_note": (1, "5:2"), "edit_note": (2, "5:2"), "reference": (4, "0:0")}[target]
        state["sheets"][sid]["cells"][address]["note"] = "Corrupted fictional note"
    with pytest.raises(GradebookError):
        verify_get_only_output(before, raw_from_state(state), [plan], store, {"core": binding})


@pytest.mark.asyncio
async def test_injected_edit_request_is_rejected_independently(scenario):
    before, canvas, store, binding = scenario
    plan = await prepare_get_only_refresh(canvas, store, "core", binding, before)
    after = apply(before, plan, binding)
    plan["batch_update"]["requests"].append({
        "updateCells": {"start": {"sheetId": 2}, "rows": [], "fields": "note"},
    })
    with pytest.raises(GradebookError, match="canonical projection"):
        verify_get_only_output(before, after, [plan], store, {"core": binding})


@pytest.mark.asyncio
async def test_changed_input_cannot_validate_an_old_plan(scenario):
    before, canvas, store, binding = scenario
    plan = await prepare_get_only_refresh(canvas, store, "core", binding, before)
    after = apply(before, plan, binding)
    changed = native._state(before)
    changed["sheets"][2]["cells"]["5:2"]["note"] = "Later teacher note"
    with pytest.raises(GradebookError, match="provenance"):
        verify_get_only_output(raw_from_state(changed), after, [plan], store, {"core": binding})


@pytest.mark.asyncio
async def test_snapshot_checksum_is_verified(scenario):
    before, canvas, store, binding = scenario
    plan = await prepare_get_only_refresh(canvas, store, "core", binding, before)
    after = apply(before, plan, binding)
    path = store.root / f"snapshot-{plan['canvas_snapshot_id']}.json"
    altered = json.loads(path.read_text())
    altered["cells"]["101:21"]["value"] = 99
    path.write_text(json.dumps(altered))
    assert digest(altered) != plan["canvas_snapshot_id"]
    with pytest.raises(GradebookError, match="integrity"):
        verify_get_only_output(before, after, [plan], store, {"core": binding})


@pytest.mark.asyncio
async def test_get_columns_never_shrink(scenario):
    before, canvas, store, binding = scenario
    state = native._state(before)
    state["sheets"][1]["properties"]["gridProperties"]["columnCount"] = 40
    before = raw_from_state(state)
    plan = await prepare_get_only_refresh(canvas, store, "core", binding, before)
    after = apply(before, plan, binding)
    verify_get_only_output(before, after, [plan], store, {"core": binding})
    assert native._state(after)["sheets"][1]["properties"]["gridProperties"]["columnCount"] == 40


@pytest.mark.asyncio
async def test_insufficient_get_rows_hold_without_grid_expansion(scenario):
    before, canvas, store, binding = scenario
    state = native._state(before)
    state["sheets"][1]["properties"]["gridProperties"]["rowCount"] = 6
    before = raw_from_state(state)
    second = copy.deepcopy(canvas.current["students"][0])
    second.update(id="102", name="Fictional second student")
    canvas.current["students"].append(second)
    with pytest.raises(GradebookError, match="row expansion"):
        await prepare_get_only_refresh(canvas, store, "core", binding, before)


@pytest.mark.asyncio
async def test_original_origin_mismatch_holds_before_canvas_read(scenario):
    before, canvas, store, binding = scenario
    state = native._state(before)
    state["sheets"][3]["cells"]["3:1"]["userEnteredValue"] = {"stringValue": "https://other.example"}
    with pytest.raises(GradebookError, match="course or origin"):
        await prepare_get_only_refresh(canvas, store, "core", binding, raw_from_state(state))
    assert canvas.reads == []


@pytest.mark.asyncio
async def test_incomplete_plan_inventory_is_rejected(scenario):
    before, canvas, store, binding = scenario
    plan = await prepare_get_only_refresh(canvas, store, "core", binding, before)
    after = apply(before, plan, binding)
    with pytest.raises(GradebookError, match="every configured course"):
        verify_get_only_output(before, after, [], store, {"core": binding})


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "field,value",
    [
        (None, None), (None, ["private-sensitive-sentinel"]),
        (None, "private-sensitive-sentinel"),
        ("sheets", None), ("sheets", True),
        ("sheets", ["private-sensitive-sentinel"]),
        ("tab_names", None), ("tab_names", False),
        ("tab_names", ["private-sensitive-sentinel"]),
        ("sheets.Canvas", ["private-sensitive-sentinel"]),
        ("sheets.Working", {"private-sensitive-sentinel": 1}),
        ("sheets._Sync", True), ("sheets.Canvas", 1.0),
        ("sheets.Canvas", "1"), ("sheets.Canvas", -1),
        ("tab_names.Canvas", ["private-sensitive-sentinel"]),
        ("tab_names.Working", {"private-sensitive-sentinel": 1}),
        ("tab_names._Sync", False), ("tab_names.Canvas", ""),
        ("spreadsheet_id", {"private-sensitive-sentinel": 1}),
        ("course_id", ["private-sensitive-sentinel"]),
        ("course_id", True), ("label", None),
        ("label", {"private-sensitive-sentinel": 1}),
        ("working_protection_id", None), ("working_protection_id", False),
    ],
)
async def test_malformed_bindings_are_safe_before_canvas_or_artifact_writes(
    scenario, field, value,
):
    before, canvas, store, binding = scenario
    invalid = copy.deepcopy(binding)
    if field is None:
        invalid = value
    elif "." in field:
        group, name = field.split(".")
        invalid[group][name] = value
    else:
        invalid[field] = value
    files = set(store.root.iterdir())
    with pytest.raises(GradebookError) as error:
        await prepare_get_only_refresh(canvas, store, "core", invalid, before)
    assert "private-sensitive-sentinel" not in str(error.value)
    assert not canvas.reads
    assert set(store.root.iterdir()) == files


@pytest.mark.asyncio
@pytest.mark.parametrize("field", ["label", "working_protection_id", "sheets", "tab_names"])
async def test_missing_renderer_bindings_hold_before_canvas_read(scenario, field):
    before, canvas, store, binding = scenario
    invalid = copy.deepcopy(binding)
    invalid.pop(field)
    with pytest.raises(GradebookError, match="workbook binding differs"):
        await prepare_get_only_refresh(canvas, store, "core", invalid, before)
    assert not canvas.reads
