"""Preview-only formative/summative channel contracts; fictional records."""

import pytest
import test_gradebook_proposal_preview as preview_cases

from canvas_mcp.gradebook.proposal_preview import prepare_preview

preview_scenario = preview_cases.scenario
repin = preview_cases.repin


@pytest.mark.parametrize("feedback", [None, ""])
def test_formative_preview_needs_score_not_manufactured_feedback(
    preview_scenario, feedback
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
