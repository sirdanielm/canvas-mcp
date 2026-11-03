"""Observed formative channel mismatch; fictional records only."""

import copy
import json

import pytest
import test_gradebook_proposal_preview as preview_cases
import test_teacher_edit_transfer as transfer_cases
from test_gradebook import snapshot as snapshot
from test_gradebook_native import binding as binding

from canvas_mcp.gradebook import native
from canvas_mcp.gradebook.client import GradebookError
from canvas_mcp.gradebook.model import digest
from canvas_mcp.gradebook.proposal_preview import prepare_preview, save_preview
from canvas_mcp.gradebook.store import Store
from canvas_mcp.gradebook.teacher_edit_transfer import (
    prepare_transfer,
    revalidate_transfer,
)

preview_scenario = preview_cases.scenario
transfer_scenario = transfer_cases.scenario
repin = preview_cases.repin


@pytest.mark.parametrize("feedback", [None, ""])
def test_formative_preview_needs_score_not_manufactured_feedback(
    preview_scenario, feedback, tmp_path
):
    args = preview_scenario
    row = args["proposals"][0]
    row.update(
        source_lane="SDMGRASS_FORMATIVE",
        delivery_policy="SCORE_ONLY",
        feedback=feedback,
    )
    args["assignment_bindings"][0].update(
        source_lane="SDMGRASS_FORMATIVE", delivery_policy="SCORE_ONLY"
    )
    repin(args)
    plan = prepare_preview(**args)
    assert plan["holds"] == []
    assert plan["envelope"]["edits"] == [
        {"user_id": "101", "assignment_id": "21", "value": 73}
    ]
    assert plan["delivery_policies"] == {row["evaluation_id"]: "SCORE_ONLY"}
    assert plan["proposals"][0]["feedback"] is feedback
    assert plan["comment_approval"] is False and plan["requests"] == []
    artifact, _ = save_preview(Store(tmp_path), plan)
    assert Store(tmp_path).load("review", artifact) == plan


def test_formative_preview_retains_internal_analysis_without_comment_intent(
    preview_scenario,
):
    args = preview_scenario
    args["proposals"][0]["source_lane"] = "SDMGRASS_FORMATIVE"
    args["assignment_bindings"][0]["source_lane"] = "SDMGRASS_FORMATIVE"
    repin(args)
    plan = prepare_preview(**args)
    assert plan["proposals"][0]["feedback"] == args["proposals"][0]["feedback"]
    assert plan["delivery_policies"] == {
        args["proposals"][0]["evaluation_id"]: "SCORE_ONLY"
    }
    assert plan["comment_approval"] is False


def test_formative_cannot_claim_summative_comment_channel(preview_scenario):
    args = preview_scenario
    args["proposals"][0].update(
        source_lane="SDMGRASS_FORMATIVE", delivery_policy="SCORE_AND_FEEDBACK"
    )
    args["assignment_bindings"][0].update(
        source_lane="SDMGRASS_FORMATIVE", delivery_policy="SCORE_AND_FEEDBACK"
    )
    repin(args)
    plan = prepare_preview(**args)
    assert plan["envelope"]["edits"] == []
    assert plan["holds"][0]["code"] == "DELIVERY_POLICY_CHANGED"


@pytest.mark.parametrize("feedback", [None, ""])
def test_summative_preview_still_requires_full_feedback(preview_scenario, feedback):
    preview_scenario["proposals"][0]["feedback"] = feedback
    repin(preview_scenario)
    plan = prepare_preview(**preview_scenario)
    assert plan["envelope"]["edits"] == []
    assert plan["holds"][0]["code"] == "FULL_FEEDBACK_REQUIRED"


@pytest.mark.parametrize(
    "feedback", [None, "", "Internal teacher rationale; not a student comment."]
)
def test_formative_transfer_preserves_note_and_changes_score_only(
    transfer_scenario, feedback
):
    args, _ = transfer_scenario
    args["record"].update(
        source_lane="SDMGRASS_FORMATIVE", delivery_policy="SCORE_ONLY"
    )
    args["decision"].update(
        source_lane="SDMGRASS_FORMATIVE",
        delivery_policy="SCORE_ONLY",
        feedback=feedback,
    )
    args["raw"]["sheets"][1]["data"][0]["rowData"][5]["values"][2]["note"] = (
        "Teacher note retained exactly.\nSecond line."
    )
    before = native._state(args["raw"])
    plan = prepare_transfer(**args)
    write = plan["requests"][0]["updateCells"]
    assert write["fields"] == "userEnteredValue"
    assert write["rows"] == [{"values": [{"userEnteredValue": {"numberValue": 16}}]}]
    after = copy.deepcopy(before)
    after["sheets"][2]["cells"]["5:2"]["userEnteredValue"] = {"numberValue": 16}
    assert plan["after_state"] == json.loads(json.dumps(after))
    assert plan["decision"]["feedback"] == feedback
    assert plan["delivery_policy"] == "SCORE_ONLY"
    assert plan["comment_delivery_authorized"] is False
    revalidate_transfer(
        plan,
        expected_plan_sha256=digest(plan),
        raw=args["raw"],
        current=args["current"],
        pin_binding=args["pin_binding"],
        source_check=args["source_check"],
    )


def test_lane_policy_is_part_of_the_authenticated_transfer_selection(transfer_scenario):
    args, _ = transfer_scenario
    args["record"].update(
        source_lane="SDMGRASS_FORMATIVE", delivery_policy="SCORE_ONLY"
    )
    args["decision"].update(
        source_lane="SDMGRASS_FORMATIVE", delivery_policy="SCORE_AND_FEEDBACK"
    )
    with pytest.raises(GradebookError, match="DELIVERY_POLICY_CHANGED"):
        prepare_transfer(**args)
