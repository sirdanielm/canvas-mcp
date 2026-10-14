"""Deterministic empty-slot native Edit coverage tests; fictional records only."""

import copy
import json

import pytest
from test_gradebook import snapshot as snapshot
from test_gradebook_native import binding as binding
from test_gradebook_native import initial_raw, raw_from_state

from canvas_mcp.gradebook import native
from canvas_mcp.gradebook.client import GradebookError
from canvas_mcp.gradebook.edit_axis_refresh import (
    plan_edit_axis_refresh,
    verify_edit_axis_output,
)
from canvas_mcp.gradebook.model import digest
from canvas_mcp.gradebook.native_edit_review import extract_native_edits
from canvas_mcp.gradebook.refresh import build_requests


@pytest.fixture
def scenario(snapshot, binding):
    baseline = copy.deepcopy(snapshot)
    current = copy.deepcopy(snapshot)
    student = copy.deepcopy(current["students"][0])
    student.update(id="102", name="Fictional new learner")
    current["students"].append(student)
    assignment = copy.deepcopy(current["assignments"][0])
    assignment.update(id="22", name="Fictional new activity", position=2)
    current["assignments"].append(assignment)
    current["cells"]["101:21"].update(value=18, grade="18", late=True)
    current["cells"]["101:22"] = {
        **copy.deepcopy(snapshot["cells"]["101:21"]),
        "value": "EX",
        "excused": True,
    }
    current["cells"]["102:21"] = {
        **copy.deepcopy(snapshot["cells"]["101:21"]),
        "value": 0,
    }
    state = native._state(initial_raw(baseline, binding))
    # Model an earlier GET-only refresh: fresh GET, unchanged original Edit/B2.
    for request in build_requests(
        current, current, digest(current), binding, current, 0
    ):
        data = next(iter(request.values()))
        sid = data.get("start", {}).get(
            "sheetId",
            data.get("range", {}).get(
                "sheetId", data.get("properties", {}).get("sheetId")
            ),
        )
        if sid == binding["sheets"]["Canvas"]:
            native._apply_requests(state, [request], binding)
    working = state["sheets"][2]
    working["properties"]["gridProperties"]["frozenRowCount"] = 4
    working["cells"]["5:2"].update(
        userEnteredValue={"numberValue": 20},
        note="Private fictional feedback",
    )
    working["cells"]["0:8"] = {
        "userEnteredValue": {"formulaValue": "=SUM(C6:C7)"},
        "note": "Opaque helper",
    }
    working["cells"]["6:3"] = {"userEnteredFormat": {"textFormat": {"bold": True}}}
    working["protectedRanges"][0]["editors"] = {"users": ["operator@example.invalid"]}
    state["sheets"][3]["cells"]["8:1"]["userEnteredValue"] = {
        "stringValue": digest(current)
    }
    return raw_from_state(state), binding, baseline, current


def prepared(scenario):
    before, binding, baseline, current = scenario
    plan = plan_edit_axis_refresh("core", binding, before, baseline, current)
    state = native._state(before)
    native._apply_requests(state, plan["batch_update"]["requests"], binding)
    return plan, raw_from_state(state)


def test_rule_wire_format_preserves_raw_color_precision_and_aliases(scenario):
    before, binding, baseline, current = copy.deepcopy(scenario)
    working = next(
        sheet for sheet in before["sheets"]
        if sheet["properties"]["sheetId"] == binding["sheets"]["Working"]
    )
    raw_format = working["conditionalFormats"][0]["booleanRule"]["format"]
    rgb = {"red": 0.8666667, "green": 0.9529412, "blue": 0.89411765}
    raw_format["backgroundColor"] = copy.deepcopy(rgb)
    raw_format["backgroundColorStyle"] = {"rgbColor": copy.deepcopy(rgb)}
    original = copy.deepcopy(before)
    plan = plan_edit_axis_refresh("core", binding, before, baseline, current)
    rule = next(
        request["updateConditionalFormatRule"]["rule"]
        for request in plan["batch_update"]["requests"]
        if "updateConditionalFormatRule" in request
    )
    assert rule["booleanRule"]["format"] == raw_format
    assert rule["booleanRule"]["format"]["backgroundColor"]["green"] == 0.9529412
    assert native._clean(raw_format)["backgroundColor"]["green"] == 0.95294
    assert before == original
    state = native._state(before)
    native._apply_requests(state, plan["batch_update"]["requests"], binding)
    verify_edit_axis_output(before, raw_from_state(state), {"core": plan}, {"core": binding})


def test_append_preserves_all_old_fields_context_intent_and_helpers(scenario):
    before, binding, baseline, current = scenario
    originals = copy.deepcopy(scenario)
    plan, after = prepared(scenario)
    assert scenario == originals
    assert plan["counts"] == {
        "new_students": 1,
        "new_assignments": 1,
        "new_targets": 3,
        "retained_old_targets": 1,
        "preserved_original_edits": 1,
    }
    merged = plan["merged_baseline"]
    assert merged["cells"]["101:21"] == baseline["cells"]["101:21"]
    assert merged["students"][:1] == baseline["students"]
    assert merged["assignments"][:1] == baseline["assignments"]
    assert "102:22" not in merged["cells"]
    assert merged["cells"]["101:22"] == current["cells"]["101:22"]
    assert plan["baseline_id"] == digest(merged)
    assert merged["working_baseline"]["fresh_snapshot_id"] == digest(current)
    old, expanded = native._state(before), native._state(after)
    assert old["sheets"][2]["cells"]["5:2"] == expanded["sheets"][2]["cells"]["5:2"]
    assert old["sheets"][2]["cells"]["0:8"] == expanded["sheets"][2]["cells"]["0:8"]
    assert expanded["sheets"][2]["cells"]["6:3"]["userEnteredFormat"] == {
        "textFormat": {"bold": True}
    }
    assert expanded["sheets"][2]["properties"] == old["sheets"][2]["properties"]
    assert expanded["sheets"][2]["cells"]["5:3"]["userEnteredValue"] == {
        "stringValue": "Excused"
    }
    assert expanded["sheets"][2]["cells"]["6:2"]["userEnteredValue"] == {
        "numberValue": 0
    }
    assert "userEnteredValue" not in expanded["sheets"][2]["cells"]["6:3"]
    assert (
        extract_native_edits(after, binding, merged)["edits"]
        == extract_native_edits(before, binding, baseline)["edits"]
    )
    assert (
        expanded["sheets"][2]["protectedRanges"][0]["editors"]
        == old["sheets"][2]["protectedRanges"][0]["editors"]
    )
    assert expanded["sheets"][1] == old["sheets"][1]
    assert expanded["sheets"][4] == old["sheets"][4]
    verify_edit_axis_output(
        before, after, json.loads(json.dumps([plan])), {"core": binding}
    )


@pytest.mark.parametrize(
    "field,value",
    [
        ("userEnteredValue", {"numberValue": 0}),
        ("userEnteredValue", {"stringValue": "EX"}),
        ("userEnteredValue", {"formulaValue": "=1+1"}),
        ("note", "private-sentinel"),
        (
            "dataValidation",
            {
                "condition": {
                    "type": "NUMBER_GREATER",
                    "values": [{"userEnteredValue": "0"}],
                }
            },
        ),
    ],
)
@pytest.mark.parametrize("position", ["2:3", "5:3", "6:1", "6:3"])
def test_every_new_header_label_score_collision_holds(scenario, field, value, position):
    raw, binding, baseline, current = scenario
    state = native._state(raw)
    state["sheets"][2]["cells"].setdefault(position, {})[field] = value
    with pytest.raises(GradebookError) as error:
        plan_edit_axis_refresh(
            "core", binding, raw_from_state(state), baseline, current
        )
    assert "private-sentinel" not in str(error.value)


@pytest.mark.parametrize(
    "change",
    [
        "removal_student",
        "removal_assignment",
        "points",
        "grading_type",
        "scope",
        "duplicate",
        "formula",
        "capacity",
        "protection",
        "rule",
    ],
)
def test_ambiguous_or_drifting_schema_holds(scenario, change):
    raw, binding, baseline, current = scenario
    state = native._state(raw)
    if change == "removal_student":
        current["students"] = current["students"][1:]
        current["cells"] = {
            k: v for k, v in current["cells"].items() if k.startswith("102:")
        }
    elif change == "removal_assignment":
        current["assignments"] = current["assignments"][1:]
        current["cells"] = {
            k: v for k, v in current["cells"].items() if k.endswith(":22")
        }
    elif change in ("points", "grading_type"):
        current["assignments"][0][
            "points_possible" if change == "points" else "grading_type"
        ] = 21 if change == "points" else "percent"
    elif change == "scope":
        current["origin"] = "https://other.example"
    elif change == "duplicate":
        current["students"].append(copy.deepcopy(current["students"][0]))
    elif change == "formula":
        state["sheets"][2]["cells"]["5:2"]["userEnteredValue"] = {"formulaValue": "=20"}
    elif change == "capacity":
        state["sheets"][2]["properties"]["gridProperties"]["rowCount"] = 6
        state["sheets"][2]["cells"].pop("6:3")
    elif change == "protection":
        state["sheets"][2]["protectedRanges"][0]["unprotectedRanges"][0][
            "startColumnIndex"
        ] = 1
    else:
        state["sheets"][2]["conditionalFormats"][0]["booleanRule"]["condition"][
            "values"
        ][0]["userEnteredValue"] = "=TRUE"
    with pytest.raises(GradebookError):
        plan_edit_axis_refresh(
            "core", binding, raw_from_state(state), baseline, current
        )


def test_highlight_extends_exact_get_bounds_and_supports_legacy_quotes(scenario):
    raw, binding, baseline, current = scenario
    state = native._state(raw)
    rule = state["sheets"][2]["conditionalFormats"][0]
    item = rule["booleanRule"]["condition"]["values"][0]
    item["userEnteredValue"] = item["userEnteredValue"].replace("'", "\\'")
    plan = plan_edit_axis_refresh(
        "core", binding, raw_from_state(state), baseline, current
    )
    update = next(
        r["updateConditionalFormatRule"]
        for r in plan["batch_update"]["requests"]
        if "updateConditionalFormatRule" in r
    )
    formula = update["rule"]["booleanRule"]["condition"]["values"][0][
        "userEnteredValue"
    ]
    assert "$C$6:$D$7" in formula
    assert "\\'Core GET\\'" in formula
    assert update["rule"]["booleanRule"]["format"] == rule["booleanRule"]["format"]


@pytest.mark.parametrize(
    "change",
    [
        "old_value",
        "old_note",
        "helper",
        "reference",
        "get",
        "baseline",
        "validation",
        "plan",
    ],
)
def test_exact_readback_rejects_any_unplanned_mutation(scenario, change):
    before, binding, _, _ = scenario
    plan, after = prepared(scenario)
    state = native._state(after)
    if change == "plan":
        plan["counts"]["new_students"] = 2
    else:
        sid, address, field, value = {
            "old_value": (2, "5:2", "userEnteredValue", {"numberValue": 19}),
            "old_note": (2, "5:2", "note", "changed"),
            "helper": (2, "0:8", "note", "changed"),
            "reference": (4, "0:0", "note", "changed"),
            "get": (1, "5:2", "userEnteredValue", {"numberValue": 99}),
            "baseline": (3, "1:1", "userEnteredValue", {"stringValue": "0" * 64}),
            "validation": (2, "6:3", "dataValidation", {}),
        }[change]
        state["sheets"][sid]["cells"][address][field] = value
    with pytest.raises(GradebookError):
        verify_edit_axis_output(
            before, raw_from_state(state), [plan], {"core": binding}
        )


def test_no_growth_is_zero_requests_and_unchanged_baseline(snapshot, binding):
    before = initial_raw(snapshot, binding)
    plan = plan_edit_axis_refresh("core", binding, before, snapshot, snapshot)
    assert plan["batch_update"]["requests"] == []
    assert plan["merged_baseline"] == snapshot
    verify_edit_axis_output(before, before, [plan], {"core": binding})


@pytest.mark.parametrize(
    "change", ["snapshot_reference", "title", "maximum", "grade", "label"]
)
def test_get_source_must_exactly_match_its_bound_snapshot(scenario, change):
    raw, binding, baseline, current = scenario
    state = native._state(raw)
    if change == "snapshot_reference":
        state["sheets"][3]["cells"]["8:1"]["userEnteredValue"] = {
            "stringValue": "0" * 64
        }
    else:
        address, value = {
            "title": ("2:3", {"stringValue": "private-sentinel"}),
            "maximum": ("3:3", {"numberValue": 99}),
            "grade": ("5:3", {"numberValue": 99}),
            "label": ("6:1", {"stringValue": "private-sentinel"}),
        }[change]
        state["sheets"][1]["cells"][address]["userEnteredValue"] = value
    with pytest.raises(GradebookError) as error:
        plan_edit_axis_refresh(
            "core", binding, raw_from_state(state), baseline, current
        )
    assert "private-sentinel" not in str(error.value)


@pytest.mark.parametrize(
    "field,value",
    [
        ("schema_version", True),
        ("cells", []),
        ("students", [{"id": "private-sentinel"}]),
        ("assignments", None),
        ("origin", None),
        ("course_id", []),
        ("fetched_at", None),
    ],
)
def test_malformed_snapshot_holds_with_static_private_error(scenario, field, value):
    before, binding, baseline, current = scenario
    current[field] = value
    with pytest.raises(GradebookError, match="snapshot structure") as error:
        plan_edit_axis_refresh("core", binding, before, baseline, current)
    assert "private-sentinel" not in str(error.value)


def test_second_append_attempt_is_noop_and_keeps_derived_baseline(scenario):
    _, binding, _, current = scenario
    plan, expanded = prepared(scenario)
    again = plan_edit_axis_refresh(
        "core", binding, expanded, plan["merged_baseline"], current
    )
    assert again["batch_update"]["requests"] == []
    assert again["merged_baseline"] == plan["merged_baseline"]
    assert again["baseline_id"] == plan["baseline_id"]
    verify_edit_axis_output(expanded, expanded, [again], {"core": binding})
