"""Offline fictional exact-destination checks, no U3 source authority asserted."""

import copy

import pytest
from test_gradebook import snapshot as snapshot
from test_gradebook_edit_axis_refresh import scenario as dense_scenario  # noqa: F401
from test_gradebook_native import binding as binding
from test_gradebook_native import raw_from_state
from test_gradebook_sparse_edit_axis_refresh import (
    _fictional_current_only_case,
    _fictional_observed_u3_axis_case,
)
from test_gradebook_sparse_edit_axis_refresh import (
    scenario as scenario,
)

from canvas_mcp.gradebook import native
from canvas_mcp.gradebook.client import GradebookError
from canvas_mcp.gradebook.model import digest
from canvas_mcp.gradebook.sparse_edit_axis_refresh import plan_sparse_edit_axis_refresh
from canvas_mcp.gradebook.u3_v2_edit_gate import qualify_v2_note_destination


def build(scenario, observed):
    if observed:
        before, binding, baseline, current, args = _fictional_observed_u3_axis_case(
            scenario
        )
        owner = args["_observed_format_authority"]
    else:
        before, binding, baseline, current = _fictional_current_only_case(scenario)
        args = {"_current_rows_only": True, "_growth_assignment_id": "23"}
        owner = None
    plan = plan_sparse_edit_axis_refresh(
        "core", binding, before, baseline, current, **args
    )
    state = native._state(before)
    native._apply_requests(state, plan["batch_update"]["requests"], binding)
    return before, binding, plan, raw_from_state(state), owner


@pytest.mark.parametrize("observed", [False, True])
def test_v2_destination_gate_does_not_grant_source_or_write_authority(
    scenario, observed
):
    before, binding, plan, raw, authority = build(scenario, observed)
    copied = copy.deepcopy((before, binding, plan, raw))
    result = qualify_v2_note_destination(
        before_raw=before,
        plan=plan,
        expected_plan_sha256=digest(plan),
        raw=raw,
        binding=binding,
        target={"user_id": "102", "assignment_id": "23"},
        observed_format_authority=authority,
    )
    assert (before, binding, plan, raw) == copied
    assert (result["row"], result["column"]) == (6, 5)
    assert result["teacher_accepted"] is result["publication_allowed"] is False
    assert result["canvas_writes"] == result["sheets_writes"] == 0


@pytest.mark.parametrize(
    "mutation",
    [
        "excluded",
        "other_assignment",
        "wrong_plan_digest",
        "changed_plan",
        "baseline",
        "sheet",
        "rule",
        "protection",
        "no_authority",
        "retired_note",
        "extra_editor",
        "domain_edit",
        "protection_description",
        "extra_protection",
        "other_sheet_rule",
    ],
)
def test_v2_destination_gate_rejects_wrong_lineage_or_excluded_target(
    scenario, mutation
):
    before, binding, plan, raw, authority = build(scenario, True)
    target = {"user_id": "102", "assignment_id": "23"}
    expected = digest(plan)
    if mutation == "excluded":
        target["user_id"] = "101"
    elif mutation == "other_assignment":
        target["assignment_id"] = "21"
    elif mutation == "wrong_plan_digest":
        expected = "0" * 64
    elif mutation == "changed_plan":
        plan["counts"]["new_targets"] += 1
    elif mutation == "baseline":
        state = native._state(raw)
        state["sheets"][3]["cells"]["1:1"]["userEnteredValue"] = {
            "stringValue": "0" * 64
        }
        raw = raw_from_state(state)
    elif mutation == "sheet":
        raw["spreadsheetId"] = "wrong"
    elif mutation == "rule":
        next(s for s in raw["sheets"] if s["properties"]["sheetId"] == 2)[
            "conditionalFormats"
        ][0]["ranges"][0]["endColumnIndex"] -= 1
    elif mutation == "protection":
        next(s for s in raw["sheets"] if s["properties"]["sheetId"] == 2)[
            "protectedRanges"
        ][0]["unprotectedRanges"] = []
    elif mutation == "no_authority":
        authority = None
    elif mutation in {
        "extra_editor",
        "domain_edit",
        "protection_description",
        "extra_protection",
        "other_sheet_rule",
    }:
        sheet = next(
            s
            for s in raw["sheets"]
            if s["properties"]["sheetId"]
            == (1 if mutation == "other_sheet_rule" else 2)
        )
        if mutation == "extra_editor":
            sheet["protectedRanges"][0]["editors"] = {
                "users": ["fictional@example.invalid"]
            }
        elif mutation == "domain_edit":
            sheet["protectedRanges"][0]["editors"] = {"domainUsersCanEdit": True}
        elif mutation == "protection_description":
            sheet["protectedRanges"][0]["description"] = "changed"
        elif mutation == "extra_protection":
            sheet["protectedRanges"].append(copy.deepcopy(sheet["protectedRanges"][0]))
        else:
            sheet.setdefault("conditionalFormats", []).append({"fictional": True})
    else:
        state = native._state(raw)
        state["sheets"][2]["cells"].setdefault("5:5", {})["note"] = "fictional"
        raw = raw_from_state(state)
    with pytest.raises(GradebookError):
        qualify_v2_note_destination(
            before_raw=before,
            plan=plan,
            expected_plan_sha256=expected,
            raw=raw,
            binding=binding,
            target=target,
            observed_format_authority=authority,
        )


def test_current_teacher_note_changes_fingerprint_but_is_not_source_approval(scenario):
    before, binding, plan, raw, _ = build(scenario, False)
    args = {
        "before_raw": before,
        "plan": plan,
        "expected_plan_sha256": digest(plan),
        "binding": binding,
        "target": {"user_id": "102", "assignment_id": "23"},
    }
    first = qualify_v2_note_destination(raw=raw, **args)
    state = native._state(raw)
    state["sheets"][2]["cells"].setdefault("6:5", {})["note"] = "Fictional teacher note"
    second = qualify_v2_note_destination(raw=raw_from_state(state), **args)
    assert first["input_fingerprint"] != second["input_fingerprint"]
    assert first["teacher_accepted"] is second["teacher_accepted"] is False
    assert first["publication_allowed"] is second["publication_allowed"] is False


def test_core_extra_conditional_rule_is_not_silently_admitted(scenario):
    before, binding, plan, raw, _ = build(scenario, False)
    sheet = next(s for s in raw["sheets"] if s["properties"]["sheetId"] == 2)
    sheet["conditionalFormats"].append(copy.deepcopy(sheet["conditionalFormats"][0]))
    with pytest.raises(GradebookError, match="PROTECTION_OR_RULE_CHANGED"):
        qualify_v2_note_destination(
            before_raw=before,
            plan=plan,
            expected_plan_sha256=digest(plan),
            raw=raw,
            binding=binding,
            target={"user_id": "102", "assignment_id": "23"},
        )
