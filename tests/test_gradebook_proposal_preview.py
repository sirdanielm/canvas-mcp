"""Fictional source-only proposal fixtures; no clients or transports."""

import copy

import pytest

from canvas_mcp.gradebook.client import GradebookError
from canvas_mcp.gradebook.model import digest
from canvas_mcp.gradebook.proposal_preview import prepare_preview, save_preview
from canvas_mcp.gradebook.store import Store


@pytest.fixture
def scenario():
    proposal = {
        "source_lane": "GRASS_SUMMATIVE",
        "provider": "GRASS_SAVED_RESULT",
        "source_key": "a" * 64,
        "evaluation_id": "evaluation:fictional-β",
        "request_revision": "request-native-1",
        "source_revision": "source:révision-2",
        "result_revision": "e" * 64,
        "rubric_revision": "f" * 64,
        "config_revision": "1" * 64,
        "identity_revision": "registry:canonical-v7",
        "state": "READY_FOR_REVIEW",
        "review_state": "UNAPPROVED",
        "reasons": [],
        "publication": "NOT_AUTHORIZED",
        "policy": "fictional-reviewed-policy",
        "section": "B1",
        "pin": "0042",
        "course_id": "12",
        "user_id": "101",
        "assignment_id": "21",
        "canvas_attempt": 3,
        "submitted_at": "2026-10-17T12:00:00Z",
        "raw_score": 17.5,
        "raw_maximum": 24,
        "proposed_score": 73,
        "points_possible": 100,
        "score_scale": "EXPLICIT_OWNER_PROJECTION",
        "feedback": "Full feedback.\nRetain café and every line.",
    }
    snapshot = {
        "schema_version": 1,
        "origin": "https://canvas.example.invalid",
        "course_id": "12",
        "course_workflow_state": "available",
        "fetched_at": "first",
        "students": [{"id": "101", "sections": ["B1"]}],
        "assignments": [{"id": "21", "points_possible": 100, "grading_type": "points"}],
        "cells": {
            "101:21": {
                "value": None,
                "visible": True,
                "excused": False,
                "attempt": 3,
                "submitted_at": proposal["submitted_at"],
                "grade_matches_current_submission": True,
                "points_deducted": None,
            }
        },
    }
    pins = {
        "registry_sha256": "3" * 64,
        "roster_sha256": "4" * 64,
        "identity_revision": proposal["identity_revision"],
        "by_pin": {"0042": "101"},
    }
    binding = {
        "evaluation_id": proposal["evaluation_id"],
        "proposal_sha256": digest(proposal),
        "source_lane": proposal["source_lane"],
        "provider": proposal["provider"],
        "course_id": "12",
        "origin": "https://canvas.example.invalid",
        "assignment_id": "21",
        "section": "B1",
        "points_possible": 100,
        "canvas_attempt": 3,
        "submitted_at": proposal["submitted_at"],
        "assessment_floor": 50,
        "teacher_correction_present": False,
        "teacher_final_present": False,
        "excluded": False,
        "assignment_metadata": {
            "id": "21",
            "course_id": "12",
            "submission_types": ["online_upload"],
            "external_tool_tag_attributes": None,
        },
    }
    binding["assignment_metadata_sha256"] = digest(binding["assignment_metadata"])
    return {
        "proposals": [proposal],
        "baseline": snapshot,
        "current": copy.deepcopy(snapshot),
        "pin_binding": pins,
        "assignment_bindings": [binding],
        "source_check": lambda *_: None,
    }


def repin(scenario):
    scenario["assignment_bindings"][0]["proposal_sha256"] = digest(
        scenario["proposals"][0]
    )


@pytest.mark.parametrize("lane", ["GRASS_SUMMATIVE", "SDMGRASS_FORMATIVE"])
def test_both_lanes_retain_exact_evidence_feedback_and_no_authority(scenario, lane):
    scenario["proposals"][0]["source_lane"] = lane
    scenario["assignment_bindings"][0]["source_lane"] = lane
    repin(scenario)
    plan = prepare_preview(**scenario)
    assert plan["envelope"]["edits"] == [
        {"user_id": "101", "assignment_id": "21", "value": 73}
    ]
    assert plan["proposals"] == scenario["proposals"]
    assert plan["review"]["changes"][0]["proposed"] == 73
    assert plan["review_state"] == "UNAPPROVED"
    assert plan["requests"] == [] and plan["canvas_writes"] == 0
    for field in (
        "teacher_approval",
        "score_approval",
        "comment_approval",
        "publication_allowed",
    ):
        assert plan[field] is False
    assert "confirmation_token" not in plan


@pytest.mark.parametrize(
    "field",
    [
        "source_revision",
        "request_revision",
        "result_revision",
        "rubric_revision",
        "config_revision",
        "identity_revision",
    ],
)
def test_changed_revision_is_held_against_independent_binding(scenario, field):
    scenario["proposals"][0][field] = "9" * 64
    plan = prepare_preview(**scenario)
    assert plan["envelope"]["edits"] == []
    assert plan["holds"][0]["code"] == "PROPOSAL_BINDING_CHANGED"


@pytest.mark.parametrize(
    "change,code",
    [
        ({"state": "HOLD"}, "SOURCE_RESULT_HELD"),
        ({"review_state": "ACCEPTED"}, "PROPOSAL_REVIEW_STATE_HELD"),
        ({"reasons": ["SOURCE_HOLD"]}, "SOURCE_RESULT_HELD"),
        ({"publication": "AUTHORIZED"}, "PROPOSAL_AUTHORITY_HELD"),
        ({"provider": "EdPuZzLe"}, "EXCLUDED_PROVIDER"),
        ({"canvas_attempt": None}, "OBSERVED_ATTEMPT_REQUIRED"),
    ],
)
def test_unready_or_excluded_rows_never_enter_preview(scenario, change, code):
    scenario["proposals"][0].update(change)
    scenario["assignment_bindings"][0]["provider"] = scenario["proposals"][0][
        "provider"
    ]
    repin(scenario)
    plan = prepare_preview(**scenario)
    assert plan["envelope"]["edits"] == [] and plan["proposals"] == []
    assert plan["holds"][0]["code"] == code


@pytest.mark.parametrize(
    "change,code",
    [
        ({"assessment_floor": 80}, "ASSESSMENT_SCORE_FLOOR_PRESERVED"),
        ({"teacher_correction_present": True}, "TEACHER_AUTHORITY_PRESERVED"),
        ({"teacher_final_present": True}, "TEACHER_AUTHORITY_PRESERVED"),
        ({"excluded": True}, "EXCLUDED_PROVIDER"),
    ],
)
def test_assessment_floor_and_teacher_changes_are_preserved(scenario, change, code):
    scenario["assignment_bindings"][0].update(change)
    plan = prepare_preview(**scenario)
    assert plan["envelope"]["edits"] == []
    assert plan["holds"][0]["code"] == code


@pytest.mark.parametrize(
    "change,code",
    [
        ({"value": 90}, "CANVAS_COMPARISON_HELD"),
        ({"attempt": 4}, "CANVAS_ATTEMPT_CHANGED"),
        ({"submitted_at": "changed"}, "CANVAS_ATTEMPT_CHANGED"),
        ({"excused": True, "value": "EX"}, "CANVAS_EXCUSAL_PRESERVED"),
        ({"visible": None}, "EXACT_ACTIVE_TARGET_REQUIRED"),
        (
            {"grade_matches_current_submission": False},
            "CURRENT_SUBMISSION_REVIEW_REQUIRED",
        ),
    ],
)
def test_current_target_changes_or_higher_grade_hold(scenario, change, code):
    scenario["current"]["cells"]["101:21"].update(change)
    plan = prepare_preview(**scenario)
    assert plan["envelope"]["edits"] == []
    assert plan["holds"][0]["code"] == code


def test_unknown_or_conflicting_identity_is_held(scenario):
    scenario["pin_binding"]["by_pin"] = {"0042": "999"}
    plan = prepare_preview(**scenario)
    assert plan["envelope"]["edits"] == []
    assert plan["holds"][0]["code"] == "CANONICAL_PIN_JOIN_CHANGED"


def test_source_authority_is_mandatory_and_cannot_mutate_inputs(scenario):
    def check(proposals, pins, bindings):
        proposals.clear()
        pins.clear()
        bindings.clear()

    original = copy.deepcopy({k: v for k, v in scenario.items() if k != "source_check"})
    scenario["source_check"] = check
    assert prepare_preview(**scenario)["envelope"]["edits"]
    assert {k: v for k, v in scenario.items() if k != "source_check"} == original
    scenario["source_check"] = lambda *_: True
    with pytest.raises(GradebookError, match="SOURCE_AUTHORITY_REVALIDATION_HELD"):
        prepare_preview(**scenario)


def test_28_packet_scope_is_rejected_not_truncated(scenario):
    scenario["proposals"] *= 28
    with pytest.raises(GradebookError, match="PROPOSAL_BATCH_LIMIT"):
        prepare_preview(**scenario)


def test_duplicates_are_held_not_selected(scenario):
    scenario["proposals"] *= 2
    with pytest.raises(GradebookError, match="DUPLICATE_PROPOSAL"):
        prepare_preview(**scenario)


def test_timestamp_only_refresh_reuses_existing_immutable_review(scenario, tmp_path):
    first = prepare_preview(**scenario)
    scenario["baseline"]["fetched_at"] = "later"
    scenario["current"]["fetched_at"] = "latest"
    second = prepare_preview(**scenario)
    assert first == second
    store = Store(tmp_path / "private")
    artifact_id, path = save_preview(store, first)
    assert save_preview(store, second) == (artifact_id, path)
    assert store.load("review", artifact_id) == first
    assert len(list(store.root.glob("review-*.json"))) == 1
    damaged = copy.deepcopy(first)
    damaged["score_approval"] = True
    with pytest.raises(GradebookError, match="PROPOSAL_PREVIEW_CHANGED"):
        save_preview(store, damaged)


def test_already_matching_canvas_grade_is_noop(scenario):
    scenario["current"]["cells"]["101:21"]["value"] = 73
    plan = prepare_preview(**scenario)
    assert plan["envelope"]["edits"] == [] and not plan["holds"]
    assert plan["already_present"] == [scenario["proposals"][0]["evaluation_id"]]
    assert plan["proposals"] == scenario["proposals"]
    assert plan["proposals"][0]["feedback"] == scenario["proposals"][0]["feedback"]


@pytest.mark.parametrize(
    "external_url",
    ["https://edpuzzle.com/assignments/fictional", "https://LTI.EDPUZZLE.COM/launch"],
)
def test_edpuzzle_metadata_blocks_selection_and_retention(
    scenario, tmp_path, external_url
):
    plan = prepare_preview(**scenario)
    entry = scenario["assignment_bindings"][0]
    entry["assignment_metadata"].update(
        submission_types=["external_tool"],
        external_tool_tag_attributes={"url": external_url},
    )
    entry["assignment_metadata_sha256"] = digest(entry["assignment_metadata"])
    held = prepare_preview(**scenario)
    assert (
        held["envelope"]["edits"] == []
        and held["holds"][0]["code"] == "EXCLUDED_PROVIDER"
    )
    plan["assignment_bindings"] = copy.deepcopy(scenario["assignment_bindings"])
    plan["preview_id"] = digest({k: v for k, v in plan.items() if k != "preview_id"})
    with pytest.raises(GradebookError, match="EXCLUDED_PROVIDER"):
        save_preview(Store(tmp_path / "private"), plan)


def test_unknown_lti_provenance_is_held(scenario):
    entry = scenario["assignment_bindings"][0]
    entry["assignment_metadata"].update(
        submission_types=["external_tool"],
        external_tool_tag_attributes={"url": "https://unknown.example.invalid/launch"},
    )
    entry["assignment_metadata_sha256"] = digest(entry["assignment_metadata"])
    plan = prepare_preview(**scenario)
    assert plan["envelope"]["edits"] == []
    assert plan["holds"][0]["code"] == "EXTERNAL_TOOL_REVIEW_REQUIRED"


def test_opaque_foreign_revisions_and_digests_are_retained_verbatim(scenario):
    row = scenario["proposals"][0]
    row["foreign_source_digest"] = "foreign-canonical:é/no-floats"
    repin(scenario)
    plan = prepare_preview(**scenario)
    assert plan["proposals"][0] == row
    assert plan["proposals"][0]["source_revision"] == "source:révision-2"
    assert plan["proposals"][0]["identity_revision"] == "registry:canonical-v7"


def test_extra_unselected_evaluation_within_limit_is_held(scenario):
    extra = copy.deepcopy(scenario["proposals"][0])
    extra.update(evaluation_id="unselected-owner-evaluation", user_id="102", pin="0043")
    scenario["proposals"].append(extra)
    plan = prepare_preview(**scenario)
    assert len(plan["envelope"]["edits"]) == 1
    assert plan["holds"] == [
        {
            "evaluation_id": extra["evaluation_id"],
            "code": "PROPOSAL_NOT_IN_SELECTED_SCOPE",
        }
    ]


def test_competing_evaluations_for_same_target_are_all_held(scenario):
    extra = copy.deepcopy(scenario["proposals"][0])
    extra["evaluation_id"] = "competing-evaluation"
    binding = copy.deepcopy(scenario["assignment_bindings"][0])
    binding.update(evaluation_id=extra["evaluation_id"], proposal_sha256=digest(extra))
    scenario["proposals"].append(extra)
    scenario["assignment_bindings"].append(binding)
    plan = prepare_preview(**scenario)
    assert plan["envelope"]["edits"] == []
    assert len(plan["holds"]) == 2
    assert {h["code"] for h in plan["holds"]} == {"DUPLICATE_TARGET"}


@pytest.mark.parametrize("kind", ["exception", "async", "missing"])
def test_source_check_failures_are_fixed_holds(scenario, kind):
    def fail(*_):
        raise ValueError("Private source details must not escape")

    async def asynchronous(*_):
        return None

    scenario["source_check"] = {
        "exception": fail,
        "async": asynchronous,
        "missing": None,
    }[kind]
    with pytest.raises(GradebookError, match="^SOURCE_AUTHORITY_REVALIDATION_HELD$"):
        prepare_preview(**scenario)


def test_missing_score_is_a_hold_never_numeric_zero(scenario):
    scenario["proposals"][0]["raw_score"] = None
    repin(scenario)
    plan = prepare_preview(**scenario)
    assert plan["envelope"]["edits"] == []
    assert plan["holds"][0]["code"] == "EXPLICIT_SCORE_PROJECTION_REQUIRED"


def test_unknown_teacher_correction_state_is_a_hold(scenario):
    del scenario["assignment_bindings"][0]["teacher_correction_present"]
    plan = prepare_preview(**scenario)
    assert plan["envelope"]["edits"] == []
    assert plan["holds"][0]["code"] == "TEACHER_AUTHORITY_PRESERVED"


def test_changed_assignment_metadata_is_held(scenario):
    scenario["assignment_bindings"][0]["assignment_metadata"]["submission_types"] = [
        "external_tool"
    ]
    plan = prepare_preview(**scenario)
    assert plan["envelope"]["edits"] == []
    assert plan["holds"][0]["code"] == "ASSIGNMENT_METADATA_CHANGED"


def test_formed_held_pair_retains_complete_documentary_source(scenario, tmp_path):
    scenario["assignment_bindings"][0]["assessment_floor"] = 80
    plan = prepare_preview(**scenario)
    assert plan["envelope"]["edits"] == [] and plan["proposals"] == []
    held = plan["held_proposals"][0]
    assert held["proposal"] == scenario["proposals"][0]
    assert held["assignment_binding"] == scenario["assignment_bindings"][0]
    assert held["code"] == "ASSESSMENT_SCORE_FLOOR_PRESERVED"
    assert held["documentary_only"] is True and held["review_state"] == "HELD"
    assert held["score_approval"] is held["comment_approval"] is False
    artifact_id, _ = save_preview(Store(tmp_path / "private"), plan)
    assert Store(tmp_path / "private").load("review", artifact_id) == plan


def test_wrong_institution_with_matching_snapshots_is_held(scenario):
    for name in ("baseline", "current"):
        scenario[name]["origin"] = "https://other.example.invalid"
    plan = prepare_preview(**scenario)
    assert plan["envelope"]["edits"] == []
    assert plan["holds"][0]["code"] == "CANVAS_ORIGIN_CHANGED"


def test_edpuzzle_retains_only_excluded_inventory_references(scenario, tmp_path):
    binding = scenario["assignment_bindings"][0]
    binding["assignment_metadata"].update(
        submission_types=["external_tool"],
        external_tool_tag_attributes={"url": "https://edpuzzle.com/launch"},
    )
    binding["assignment_metadata_sha256"] = digest(binding["assignment_metadata"])
    plan = prepare_preview(**scenario)
    assert plan["proposals"] == [] and plan["assignment_bindings"] == []
    assert plan["held_proposals"] == []
    excluded = plan["excluded_inventory"][0]
    assert excluded["code"] == "EXCLUDED_PROVIDER"
    assert (
        excluded["references"]["source_revision"]
        == scenario["proposals"][0]["source_revision"]
    )
    assert (
        "proposal" not in excluded
        and "feedback" not in excluded
        and "raw_score" not in excluded
    )
    store = Store(tmp_path / "private")
    artifact_id, _ = save_preview(store, plan)
    assert store.load("review", artifact_id) == plan


def test_edpuzzle_cannot_be_rehashed_into_full_held_retention(scenario, tmp_path):
    scenario["assignment_bindings"][0]["assessment_floor"] = 80
    plan = prepare_preview(**scenario)
    held = plan["held_proposals"][0]
    held["assignment_binding"]["assignment_metadata"].update(
        submission_types=["external_tool"],
        external_tool_tag_attributes={"url": "https://edpuzzle.com/launch"},
    )
    held["assignment_binding"]["assignment_metadata_sha256"] = digest(
        held["assignment_binding"]["assignment_metadata"]
    )
    plan["preview_id"] = digest({k: v for k, v in plan.items() if k != "preview_id"})
    with pytest.raises(GradebookError, match="EXCLUDED_PROVIDER"):
        save_preview(Store(tmp_path / "private"), plan)


def test_other_unknown_lti_can_retain_only_an_inert_held_pair(scenario, tmp_path):
    binding = scenario["assignment_bindings"][0]
    binding["assignment_metadata"].update(
        submission_types=["external_tool"],
        external_tool_tag_attributes={"url": "https://unknown.example.invalid/launch"},
    )
    binding["assignment_metadata_sha256"] = digest(binding["assignment_metadata"])
    plan = prepare_preview(**scenario)
    assert plan["proposals"] == [] and plan["envelope"]["edits"] == []
    assert plan["held_proposals"][0]["proposal"] == scenario["proposals"][0]
    assert plan["held_proposals"][0]["code"] == "EXTERNAL_TOOL_REVIEW_REQUIRED"
    store = Store(tmp_path / "private")
    artifact_id, _ = save_preview(store, plan)
    assert store.load("review", artifact_id) == plan


def test_excluded_inventory_cannot_hide_feedback_in_malformed_revision(
    scenario, tmp_path
):
    secret = "This complete feedback must never appear in excluded inventory."
    row = scenario["proposals"][0]
    row["source_revision"] = {"feedback": secret, "score": 73}
    repin(scenario)
    binding = scenario["assignment_bindings"][0]
    binding["assignment_metadata"].update(
        submission_types=["external_tool"],
        external_tool_tag_attributes={"url": "https://edpuzzle.com/launch"},
    )
    binding["assignment_metadata_sha256"] = digest(binding["assignment_metadata"])
    plan = prepare_preview(**scenario)
    refs = plan["excluded_inventory"][0]["references"]
    assert "source_revision" not in refs
    assert all(type(value) is str for value in refs.values())
    refs["source_revision"] = {"feedback": secret}
    plan["preview_id"] = digest(
        {key: value for key, value in plan.items() if key != "preview_id"}
    )
    with pytest.raises(GradebookError, match="PROPOSAL_PREVIEW_CHANGED"):
        save_preview(Store(tmp_path / "private"), plan)
