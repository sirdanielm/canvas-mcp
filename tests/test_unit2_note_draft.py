"""Fictional, independent note-only Unit 2 staging safety regressions."""

import copy

import pytest
from test_gradebook import snapshot as snapshot
from test_gradebook_native import binding as binding
from test_gradebook_native import initial_raw, raw_from_state

from canvas_mcp.gradebook import native
from canvas_mcp.gradebook.client import GradebookError
from canvas_mcp.gradebook.model import digest
from canvas_mcp.gradebook.unit2_note_draft import (
    EditOnlyAuthorization,
    classify_readback,
    prepare_note_draft,
    revalidate_note_draft,
)


@pytest.fixture
def scenario(snapshot, binding):
    target = {
        "origin": "https://example.invalid",
        "course_id": "12",
        "assignment_id": "21",
        "user_id": "101",
        "attempt": None,
        "submitted_at": None,
        "submission_types": ["on_paper"],
    }
    candidate = {
        "contract": "UNIT2_MC_NOTE_CANDIDATE_V1",
        "source_version": "UNIT2_COMPACT_FEEDBACK_V2",
        "component_scope": "MC_ONLY",
        "body": "Fictional MC deduction: explain Q2.",
        "source_pins": dict.fromkeys(
            (
                "source_sha256",
                "result_sha256",
                "policy_sha256",
                "formatter_sha256",
                "contract_sha256",
                "projection_sha256",
            ),
            "a" * 64,
        ),
        "target": copy.deepcopy(target),
        "teacher_accepted": False,
        "publication_allowed": False,
    }
    return {
        "candidate": candidate,
        "raw": initial_raw(snapshot, binding),
        "binding": binding,
        "target": target,
        "identity_binding": {
            "pin": "0042",
            "user_id": "101",
            "registry_sha256": "c" * 64,
            "roster_sha256": "d" * 64,
        },
        "authorization": EditOnlyAuthorization(
            "https://example.invalid", "12", "21", "fictional-human-approval"
        ),
        "source_check": lambda *_: None,
    }


def applied(plan):
    state = copy.deepcopy(plan["before_state"])
    request = plan["requests"][0]["updateCells"]
    assert request["fields"] == "note"
    assert request["start"] == {"sheetId": 2, "rowIndex": 5, "columnIndex": 2}
    assert len(request["rows"]) == len(request["rows"][0]["values"]) == 1
    assert set(request["rows"][0]["values"][0]) == {"note"}
    state["sheets"]["2"]["cells"]["5:2"]["note"] = request["rows"][0]["values"][0][
        "note"
    ]
    return raw_from_state(state)


@pytest.mark.parametrize("value", [{"numberValue": 77}, {"formulaValue": "=1+2"}, {}])
def test_only_note_changes_preserving_grade_formula_and_teacher_note(scenario, value):
    state = native._state(scenario["raw"])
    cell = state["sheets"][2]["cells"]["5:2"]
    cell["userEnteredValue"] = value
    cell["note"] = "Teacher note\r\nwith trailing space "
    scenario["raw"] = raw_from_state(state)
    original = copy.deepcopy(scenario["raw"])
    plan = prepare_note_draft(**scenario)
    assert scenario["raw"] == original
    after = applied(plan)
    expected = native._state(original)
    expected["sheets"][2]["cells"]["5:2"]["note"] = native._state(after)["sheets"][2][
        "cells"
    ]["5:2"]["note"]
    assert native._state(after) == expected
    note = expected["sheets"][2]["cells"]["5:2"]["note"]
    assert note.startswith("Teacher note\r\nwith trailing space \n\n")
    assert note.endswith(
        scenario["candidate"]["body"] + "\n[[END UNIT2 UNAPPROVED DRAFT]]"
    )
    assert plan["numeric_grade_disposition"] == "UNCHANGED"
    assert plan["teacher_accepted"] is False
    assert plan["publication_allowed"] is False
    assert plan["canvas_requests"] == []


def test_identical_repeat_has_no_request_but_changed_marker_holds(scenario):
    plan = prepare_note_draft(**scenario)
    scenario["raw"] = applied(plan)
    repeat = prepare_note_draft(**scenario)
    assert repeat["status"] == "NO_CHANGE"
    assert repeat["requests"] == []
    scenario["candidate"]["body"] += " Changed."
    with pytest.raises(GradebookError, match="CONFLICTING_DRAFT"):
        prepare_note_draft(**scenario)


@pytest.mark.parametrize(
    "field,value", [("assignment_id", "22"), ("user_id", "102"), ("attempt", 1)]
)
def test_candidate_exact_target_mismatch_holds(scenario, field, value):
    scenario["target"][field] = value
    with pytest.raises(GradebookError):
        prepare_note_draft(**scenario)


def test_null_attempt_requires_actual_paper_observation(scenario):
    scenario["target"]["submission_types"] = ["online_upload"]
    scenario["candidate"]["target"] = copy.deepcopy(scenario["target"])
    with pytest.raises(GradebookError, match="PAPER_NULL"):
        prepare_note_draft(**scenario)


@pytest.mark.parametrize("flag", ["teacher_accepted", "publication_allowed"])
def test_no_false_approval(scenario, flag):
    scenario["candidate"][flag] = True
    with pytest.raises(GradebookError):
        prepare_note_draft(**scenario)


def test_source_verifier_must_be_synchronous_none_not_success_boolean(scenario):
    scenario["source_check"] = lambda *_: True
    with pytest.raises(GradebookError, match="SOURCE_QUALIFICATION"):
        prepare_note_draft(**scenario)


def test_exact_preimage_cas_and_complete_readback(scenario):
    plan = prepare_note_draft(**scenario)
    sha = digest(plan)
    revalidate_note_draft(
        plan,
        raw=scenario["raw"],
        expected_plan_sha256=sha,
        source_check=scenario["source_check"],
    )
    assert (
        classify_readback(plan, scenario["raw"], expected_plan_sha256=sha)["status"]
        == "BEFORE_STILL_PRESENT"
    )
    assert (
        classify_readback(plan, applied(plan), expected_plan_sha256=sha)["status"]
        == "PLANNED_OUTPUT_OBSERVED"
    )
    state = native._state(scenario["raw"])
    state["sheets"][1]["cells"]["0:0"] = {"note": "Unrelated change"}
    changed = raw_from_state(state)
    with pytest.raises(GradebookError, match="STALE_PREIMAGE"):
        revalidate_note_draft(
            plan,
            raw=changed,
            expected_plan_sha256=sha,
            source_check=scenario["source_check"],
        )
    assert (
        classify_readback(plan, changed, expected_plan_sha256=sha)["status"]
        == "DIVERGED"
    )


def test_tampered_plan_is_rejected(scenario):
    plan = prepare_note_draft(**scenario)
    sha = digest(plan)
    plan["requests"][0]["updateCells"]["fields"] = "note,userEnteredValue"
    with pytest.raises(GradebookError, match="PLAN_CHANGED"):
        classify_readback(plan, scenario["raw"], expected_plan_sha256=sha)


@pytest.mark.parametrize("mode", ["PUSH", "FORMATIVE", "EDIT_AND_PUBLISH"])
def test_authorization_cannot_admit_another_lane(scenario, mode):
    scenario["authorization"] = EditOnlyAuthorization(
        "https://example.invalid",
        "12",
        "21",
        "fictional-approval",
        mode,
    )
    with pytest.raises(GradebookError, match="EDIT_ONLY_AUTHORIZATION"):
        prepare_note_draft(**scenario)


def test_identity_and_authorized_assignment_are_exact(scenario):
    scenario["identity_binding"]["user_id"] = "102"
    with pytest.raises(GradebookError, match="EXACT_IDENTITY"):
        prepare_note_draft(**scenario)
    scenario["identity_binding"]["user_id"] = "101"
    scenario["authorization"] = EditOnlyAuthorization(
        "https://example.invalid",
        "12",
        "22",
        "fictional-approval",
    )
    with pytest.raises(GradebookError, match="EDIT_ONLY_AUTHORIZATION"):
        prepare_note_draft(**scenario)


def test_async_and_mutating_verifiers_cannot_change_planned_body(scenario):
    async def asynchronous(*_):
        return None

    scenario["source_check"] = asynchronous
    with pytest.raises(GradebookError, match="SOURCE_QUALIFICATION"):
        prepare_note_draft(**scenario)

    def mutating(candidate, *_):
        candidate["body"] = "Changed by checker."

    scenario["source_check"] = mutating
    plan = prepare_note_draft(**scenario)
    assert plan["candidate"]["body"] == "Fictional MC deduction: explain Q2."


def test_readback_with_correct_note_but_changed_numeric_grade_is_diverged(scenario):
    plan = prepare_note_draft(**scenario)
    state = native._state(applied(plan))
    state["sheets"][2]["cells"]["5:2"]["userEnteredValue"] = {"numberValue": 99}
    result = classify_readback(
        plan, raw_from_state(state), expected_plan_sha256=digest(plan)
    )
    assert result["status"] == "DIVERGED"
    assert result["retry_writes"] is False
    assert result["score_delivery_verified"] is False
