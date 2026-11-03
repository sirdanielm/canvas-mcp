"""Fictional whole-test numeric draft safety; no transport or source grading."""

import copy
import hashlib

import pytest
from test_gradebook import snapshot as snapshot
from test_gradebook_native import binding as binding
from test_gradebook_native import initial_raw, raw_from_state

from canvas_mcp.gradebook import native
from canvas_mcp.gradebook.client import GradebookError
from canvas_mcp.gradebook.model import digest
from canvas_mcp.gradebook.unit2_note_draft import EditOnlyAuthorization
from canvas_mcp.gradebook.unit2_numeric_draft import (
    classify_readback,
    prepare_numeric_draft,
    revalidate_numeric_draft,
)


@pytest.fixture
def scenario(snapshot, binding):
    target = {
        "origin": snapshot["origin"],
        "course_id": "12",
        "assignment_id": "21",
        "user_id": "101",
        "attempt": None,
        "submitted_at": None,
        "submission_types": ["on_paper"],
    }
    pins = dict.fromkeys(
        (
            "source_sha256",
            "packet_sha256",
            "reading_sha256",
            "reading_manifest_sha256",
            "result_sha256",
            "policy_sha256",
            "academic_sha256",
            "current_head_sha256",
        ),
        "a" * 64,
    )
    state = native._state(initial_raw(snapshot, binding))
    state["sheets"][2]["cells"]["5:2"].pop("userEnteredValue", None)
    state["sheets"][2]["cells"]["5:2"]["note"] = (
        "Teacher note\r\n [[UNIT2 UNAPPROVED DRAFT existing-mc]]\nMC source feedback. "
    )
    result = {
        "candidate": {
            "contract": "UNIT2_WHOLE_NUMERIC_DRAFT_V1",
            "status": "PROPOSED_REVIEW_REQUIRED",
            "component_scope": "WHOLE_TEST",
            "native_item_count": 24,
            "native_hold_count": 0,
            "grade_preview": "83",
            "points_possible": 100,
            "source_pins": pins,
            "target": copy.deepcopy(target),
            "is_final": False,
            "teacher_accepted": False,
            "publication_allowed": False,
            "score_delivery_authorized": False,
            "comment_delivery_authorized": False,
        },
        "raw": raw_from_state(state),
        "binding": binding,
        "target": target,
        "identity_binding": {
            "pin": "0042",
            "user_id": "101",
            "registry_sha256": "b" * 64,
            "roster_sha256": "c" * 64,
        },
        "canvas_observation": {
            "target": copy.deepcopy(target),
            "grade_observation": "UNGRADED",
            "score": None,
            "grade": None,
            "excused": False,
            "visible": True,
            "workflow_state": "unsubmitted",
            "grade_matches_current_submission": None,
            "closed_period": None,
            "observation_sha256": "d" * 64,
        },
        "floor_proof": {
            "status": "NO_ASSESSMENT_FLOOR_DEFINED",
            "value": None,
            "policy_sha256": "a" * 64,
            "evidence_sha256": "e" * 64,
            "evidence_ref": "fictional-owner-policy-no-floor",
        },
        "form_proof": {
            "contract": "UNIT2_NATIVE_FORM_PROOF_V1",
            "form_id": "FICTIONAL_CORE",
            "packet_sha256": "a" * 64,
            "academic_sha256": "a" * 64,
            "result_sha256": "a" * 64,
            "policy_sha256": "a" * 64,
            "question_map_sha256": "f" * 64,
            "expected_items": {
                "MC": [f"MC:{item}" for item in range(1, 21)],
                "FRQ": [f"FRQ:{item}" for item in range(1, 5)],
            },
            "actual_items": {
                "MC": [f"MC:{item}" for item in range(1, 21)],
                "FRQ": [f"FRQ:{item}" for item in range(1, 5)],
            },
        },
        "authorization": EditOnlyAuthorization(
            snapshot["origin"], "12", "21", "fictional-human-draft"
        ),
        "feedback_proof": {
            "contract": "UNIT2_WHOLE_FEEDBACK_PROOF_V1",
            "source_version": "UNIT2_COMPACT_FEEDBACK_V2",
            "component_scope": "WHOLE_TEST",
            "body": "MC: Review particle evidence.\nFRQ: Explain the comparison.\n",
            "body_sha256": hashlib.sha256(
                b"MC: Review particle evidence.\nFRQ: Explain the comparison.\n"
            ).hexdigest(),
            "source_binding": copy.deepcopy(pins),
            "formatter_sha256": "b" * 64,
            "contract_sha256": "c" * 64,
            "projection_sha256": "d" * 64,
        },
        "source_check": lambda *_: None,
    }
    nearest_rounding(result)
    return result


def applied(plan):
    state = copy.deepcopy(plan["before_state"])
    request = plan["requests"][0]["updateCells"]
    assert request["fields"] == "userEnteredValue,note"
    assert request["start"] == {"sheetId": 2, "rowIndex": 5, "columnIndex": 2}
    assert len(request["rows"]) == len(request["rows"][0]["values"]) == 1
    state["sheets"]["2"]["cells"]["5:2"].update(request["rows"][0]["values"][0])
    return raw_from_state(state)


def test_explicit_ungraded_and_no_floor_are_distinct_and_existing_mc_note_preserved(
    scenario,
):
    original = copy.deepcopy(scenario["raw"])
    note = native._state(original)["sheets"][2]["cells"]["5:2"]["note"]
    plan = prepare_numeric_draft(**scenario)
    assert scenario["raw"] == original
    assert plan["canvas_observation"]["score"] is None
    assert plan["floor_proof"]["value"] is None
    assert plan["target"]["attempt"] is None
    assert plan["currentness_hold"] == "FINAL_CURRENTNESS_REVIEW_REQUIRED"
    after = native._state(applied(plan))
    changed = after["sheets"][2]["cells"]["5:2"]
    assert changed["userEnteredValue"] == {"numberValue": 83}
    assert changed["note"].startswith(note + "\n\n")
    before = native._state(original)
    before["sheets"][2]["cells"]["5:2"].update(
        userEnteredValue={"numberValue": 83}, note=changed["note"]
    )
    assert after == before
    assert (
        plan["teacher_accepted"]
        is plan["is_final"]
        is plan["publication_allowed"]
        is False
    )
    assert plan["canvas_requests"] == []


@pytest.mark.parametrize(
    "value", ["83.0", "83/1", "83/2", "083", "NaN", "101", "-1", True, 83]
)
def test_native_preview_spelling_must_be_exact_and_canonical(scenario, value):
    scenario["candidate"]["grade_preview"] = value
    with pytest.raises(GradebookError, match="GRADE_PREVIEW"):
        prepare_numeric_draft(**scenario)


@pytest.mark.parametrize(
    "state,value",
    [
        ("UNKNOWN", None),
        ("HELD", None),
        ("DEFINED", None),
        ("NO_ASSESSMENT_FLOOR_DEFINED", "0"),
    ],
)
def test_unknown_or_inconsistent_floor_holds(scenario, state, value):
    scenario["floor_proof"].update(status=state, value=value)
    with pytest.raises(GradebookError, match="FLOOR"):
        prepare_numeric_draft(**scenario)


def test_explicit_verified_floor_not_inferred_or_waived(scenario):
    scenario["floor_proof"].update(status="DEFINED", value="84")
    with pytest.raises(GradebookError, match="FLOOR"):
        prepare_numeric_draft(**scenario)
    scenario["floor_proof"]["value"] = "50"
    assert prepare_numeric_draft(**scenario)["floor_proof"]["value"] == "50"
    scenario["floor_proof"]["policy_sha256"] = "f" * 64
    with pytest.raises(GradebookError, match="FLOOR"):
        prepare_numeric_draft(**scenario)


@pytest.mark.parametrize(
    "value",
    [
        {"numberValue": 0},
        {"numberValue": 83},
        {"formulaValue": '=IF(TRUE,"",1)'},
        {"stringValue": "EX"},
        {"stringValue": ""},
    ],
)
def test_only_physically_blank_destination_no_overwrite(scenario, value):
    state = native._state(scenario["raw"])
    state["sheets"][2]["cells"]["5:2"]["userEnteredValue"] = value
    scenario["raw"] = raw_from_state(state)
    with pytest.raises(GradebookError, match="DESTINATION"):
        prepare_numeric_draft(**scenario)


def test_identical_repeat_noop_changed_source_or_numeric_value_holds(scenario):
    plan = prepare_numeric_draft(**scenario)
    scenario["raw"] = applied(plan)
    assert prepare_numeric_draft(**scenario)["requests"] == []
    scenario["candidate"]["source_pins"]["current_head_sha256"] = "f" * 64
    scenario["feedback_proof"]["source_binding"]["current_head_sha256"] = "f" * 64
    scenario["rounding_proof"]["source_binding"]["current_head_sha256"] = "f" * 64
    with pytest.raises(GradebookError, match="CONFLICTING"):
        prepare_numeric_draft(**scenario)


@pytest.mark.parametrize(
    "field,value",
    [
        ("score", 0),
        ("excused", True),
        ("visible", False),
        ("grade_matches_current_submission", False),
        ("grade", ""),
    ],
)
def test_unknown_graded_or_excused_canvas_target_holds(scenario, field, value):
    scenario["canvas_observation"][field] = value
    with pytest.raises(GradebookError, match="CANVAS"):
        prepare_numeric_draft(**scenario)


@pytest.mark.parametrize(
    "field,value",
    [
        ("is_final", True),
        ("native_hold_count", 1),
        ("native_item_count", 23),
        ("component_scope", "MC_ONLY"),
    ],
)
def test_genuine_whole_proposal_required_not_flag_acceptance(scenario, field, value):
    scenario["candidate"][field] = value
    with pytest.raises(GradebookError):
        prepare_numeric_draft(**scenario)


def test_owner_authentication_not_boolean_or_async(scenario):
    for response in (True, False):
        scenario["source_check"] = lambda *_, response=response: response
        with pytest.raises(GradebookError, match="SOURCE"):
            prepare_numeric_draft(**scenario)

    async def invalid(*_):
        return None

    scenario["source_check"] = invalid
    with pytest.raises(GradebookError, match="SOURCE"):
        prepare_numeric_draft(**scenario)


def test_complete_preimage_revalidation_and_native_readback(scenario):
    plan = prepare_numeric_draft(**scenario)
    sha = digest(plan)
    revalidate_numeric_draft(
        plan,
        raw=scenario["raw"],
        expected_plan_sha256=sha,
        source_check=scenario["source_check"],
    )
    assert (
        classify_readback(plan, applied(plan), expected_plan_sha256=sha)["status"]
        == "PLANNED_OUTPUT_OBSERVED"
    )
    changed = native._state(scenario["raw"])
    changed["sheets"][4]["cells"]["0:0"]["note"] += " Changed"
    with pytest.raises(GradebookError, match="STALE"):
        revalidate_numeric_draft(
            plan,
            raw=raw_from_state(changed),
            expected_plan_sha256=sha,
            source_check=scenario["source_check"],
        )
    assert (
        classify_readback(plan, raw_from_state(changed), expected_plan_sha256=sha)[
            "status"
        ]
        == "DIVERGED"
    )


def test_boolean_numeric_field_is_not_the_same_grade_as_integer_one(scenario):
    scenario["candidate"]["grade_preview"] = "1"
    plan = prepare_numeric_draft(**scenario)
    changed = native._state(applied(plan))
    changed["sheets"][2]["cells"]["5:2"]["userEnteredValue"] = {"numberValue": True}
    actual = raw_from_state(changed)
    assert (
        classify_readback(plan, actual, expected_plan_sha256=digest(plan))["status"]
        == "DIVERGED"
    )
    scenario["raw"] = actual
    with pytest.raises(GradebookError, match="CONFLICTING"):
        prepare_numeric_draft(**scenario)


@pytest.mark.parametrize(
    "field,value",
    [("attempt", 0), ("attempt", 1), ("user_id", "102"), ("assignment_id", "22")],
)
def test_changed_target_or_attempt_is_never_coerced(scenario, field, value):
    scenario["target"][field] = value
    with pytest.raises(GradebookError, match="TARGET"):
        prepare_numeric_draft(**scenario)


def test_missing_floor_proof_and_owner_policy_rejection_are_held(scenario):
    scenario["floor_proof"] = {}
    with pytest.raises(GradebookError, match="FLOOR"):
        prepare_numeric_draft(**scenario)


def test_unrelated_native_bool_integer_type_drift_is_not_equal(scenario):
    before = native._state(scenario["raw"])
    before["sheets"][4]["cells"]["0:0"]["userEnteredValue"] = {"numberValue": 1}
    scenario["raw"] = raw_from_state(before)
    plan = prepare_numeric_draft(**scenario)
    before["sheets"][4]["cells"]["0:0"]["userEnteredValue"] = {"numberValue": True}
    with pytest.raises(GradebookError, match="STALE"):
        revalidate_numeric_draft(
            plan,
            raw=raw_from_state(before),
            expected_plan_sha256=digest(plan),
            source_check=scenario["source_check"],
        )
    assert (
        classify_readback(
            plan, raw_from_state(before), expected_plan_sha256=digest(plan)
        )["status"]
        == "DIVERGED"
    )


def administrative_floor(scenario):
    """A fictional, separately authenticated teacher-floor receipt binding."""
    scenario["floor_proof"].update(
        contract="UNIT2_TEACHER_ADMIN_FLOOR_V1",
        status="DEFINED",
        value="40",
        application="MAX_COMPLETE_NATIVE_GRADE_AND_FLOOR",
        assessment="UNIT2",
        paper_attempt="R1",
        scope={
            key: scenario["target"][key]
            for key in ("origin", "course_id", "assignment_id")
        },
        source_binding={
            key: scenario["candidate"]["source_pins"][key]
            for key in (
                "source_sha256",
                "packet_sha256",
                "result_sha256",
                "current_head_sha256",
            )
        },
    )


@pytest.mark.parametrize(
    "earned,staged,applied_floor",
    [("0", 40, True), ("30", 40, True), ("40", 40, False), ("83", 83, False)],
)
def test_authorized_administrative_floor_preserves_raw_native_grade(
    scenario, earned, staged, applied_floor
):
    administrative_floor(scenario)
    scenario["candidate"]["grade_preview"] = earned
    before = copy.deepcopy(scenario["candidate"])
    original_note = native._state(scenario["raw"])["sheets"][2]["cells"]["5:2"]["note"]
    plan = prepare_numeric_draft(**scenario)
    assert scenario["candidate"] == plan["candidate"] == before
    assert plan["contract"] == "UNIT2_UNAPPROVED_NUMERIC_DRAFT_V5"
    assert plan["raw_grade_preview"] == earned
    assert plan["staged_grade_preview"] == str(staged)
    assert plan["floor_applied"] is applied_floor
    cell = native._state(applied(plan))["sheets"][2]["cells"]["5:2"]
    assert cell["userEnteredValue"] == {"numberValue": staged}
    assert cell["note"].startswith(original_note + "\n\n")
    assert f"Native whole-test preview: {earned}/100" in cell["note"]
    assert (
        f"Administrative draft floor: 40/100; staged draft: {staged}/100"
        in cell["note"]
    )
    assert all(
        plan[key] is False
        for key in (
            "is_final",
            "teacher_accepted",
            "publication_allowed",
            "score_delivery_authorized",
            "comment_delivery_authorized",
        )
    )
    scenario["raw"] = applied(plan)
    assert prepare_numeric_draft(**scenario)["requests"] == []


@pytest.mark.parametrize(
    "field,value",
    [
        ("native_hold_count", 1),
        ("native_item_count", 23),
        ("status", "HELD"),
        ("grade_preview", None),
        ("grade_preview", "NaN"),
    ],
)
def test_floor_never_turns_incomplete_or_unknown_source_into_40(
    scenario, field, value
):
    administrative_floor(scenario)
    scenario["candidate"][field] = value
    with pytest.raises(GradebookError):
        prepare_numeric_draft(**scenario)


@pytest.mark.parametrize("field", ["origin", "course_id", "assignment_id"])
def test_administrative_floor_scope_is_exact(scenario, field):
    administrative_floor(scenario)
    scenario["floor_proof"]["scope"][field] = "different"
    with pytest.raises(GradebookError, match="FLOOR"):
        prepare_numeric_draft(**scenario)


@pytest.mark.parametrize(
    "field", ["source_sha256", "packet_sha256", "result_sha256", "current_head_sha256"]
)
def test_administrative_floor_source_binding_is_exact(scenario, field):
    administrative_floor(scenario)
    scenario["floor_proof"]["source_binding"][field] = "f" * 64
    with pytest.raises(GradebookError, match="FLOOR"):
        prepare_numeric_draft(**scenario)


@pytest.mark.parametrize(
    "field,value",
    [
        ("paper_attempt", "R2"),
        ("assessment", "UNIT1"),
        ("value", "50"),
        ("status", "UNKNOWN"),
        ("application", "ACCEPT_NATIVE_GRADE"),
    ],
)
def test_administrative_floor_receipt_semantics_are_narrow(scenario, field, value):
    administrative_floor(scenario)
    scenario["floor_proof"][field] = value
    with pytest.raises(GradebookError, match="FLOOR"):
        prepare_numeric_draft(**scenario)


def test_changed_floor_receipt_requires_owner_reauthentication_and_conflict_hold(
    scenario,
):
    administrative_floor(scenario)
    scenario["candidate"]["grade_preview"] = "30"
    plan = prepare_numeric_draft(**scenario)
    scenario["raw"] = applied(plan)
    scenario["floor_proof"]["evidence_sha256"] = "f" * 64
    with pytest.raises(GradebookError, match="CONFLICTING"):
        prepare_numeric_draft(**scenario)
    scenario["source_check"] = lambda *_: False
    with pytest.raises(GradebookError, match="SOURCE"):
        prepare_numeric_draft(**scenario)


@pytest.mark.parametrize(
    "value", [{"numberValue": 99}, {"formulaValue": "=100"}, {"stringValue": "EX"}]
)
def test_administrative_floor_never_replaces_existing_grade_formula_or_excusal(
    scenario, value
):
    administrative_floor(scenario)
    scenario["candidate"]["grade_preview"] = "30"
    state = native._state(scenario["raw"])
    state["sheets"][2]["cells"]["5:2"]["userEnteredValue"] = value
    scenario["raw"] = raw_from_state(state)
    with pytest.raises(GradebookError, match="DESTINATION"):
        prepare_numeric_draft(**scenario)


def test_complete_issued_28_item_form_is_proven_by_exact_map_not_count_only(scenario):
    scenario["candidate"]["native_item_count"] = 28
    scenario["form_proof"]["form_id"] = "FICTIONAL_24_MC_FORM"
    for kind in ("expected_items", "actual_items"):
        scenario["form_proof"][kind]["MC"] = [f"MC:{i}" for i in range(1, 25)]
    plan = prepare_numeric_draft(**scenario)
    assert plan["form_proof"] == scenario["form_proof"]
    assert plan["candidate"]["native_item_count"] == 28


@pytest.mark.parametrize("raw", ["1/3", "119/3"])
def test_exact_fraction_below_40_derives_exact_floor_without_rounding(scenario, raw):
    administrative_floor(scenario)
    scenario["candidate"]["grade_preview"] = raw
    plan = prepare_numeric_draft(**scenario)
    assert plan["raw_grade_preview"] == raw == scenario["candidate"]["grade_preview"]
    assert plan["staged_grade_preview"] == "40"
    assert plan["floor_applied"] is True
    assert native._state(applied(plan))["sheets"][2]["cells"]["5:2"][
        "userEnteredValue"
    ] == {"numberValue": 40}
    assert (
        classify_readback(plan, applied(plan), expected_plan_sha256=digest(plan))[
            "status"
        ]
        == "PLANNED_OUTPUT_OBSERVED"
    )


@pytest.mark.parametrize(
    "raw", ["83/2", "0/3", "2/6", "40/1", "3/0", "-1/3", "1e1", "NaN", True]
)
def test_noncanonical_fraction_or_unknown_preview_stays_held(scenario, raw):
    administrative_floor(scenario)
    scenario["candidate"]["grade_preview"] = raw
    with pytest.raises(GradebookError, match="GRADE_PREVIEW"):
        prepare_numeric_draft(**scenario)


@pytest.mark.parametrize(
    "mutation", ["missing", "extra", "duplicate", "wrong_kind", "reordered"]
)
def test_incomplete_or_changed_item_map_cannot_use_floor(scenario, mutation):
    administrative_floor(scenario)
    scenario["candidate"]["grade_preview"] = "1/3"
    observed = scenario["form_proof"]["actual_items"]
    if mutation == "missing":
        observed["MC"].pop()
    elif mutation == "extra":
        observed["MC"].append("MC:extra")
    elif mutation == "duplicate":
        observed["MC"][-1] = observed["MC"][0]
    elif mutation == "wrong_kind":
        observed["MC"][0], observed["FRQ"][0] = observed["FRQ"][0], observed["MC"][0]
    else:
        observed["MC"].reverse()
    with pytest.raises(GradebookError, match="FORM"):
        prepare_numeric_draft(**scenario)


@pytest.mark.parametrize(
    "field", ["packet_sha256", "academic_sha256", "result_sha256", "policy_sha256"]
)
def test_form_binding_drift_holds(scenario, field):
    scenario["form_proof"][field] = "b" * 64
    with pytest.raises(GradebookError, match="FORM"):
        prepare_numeric_draft(**scenario)


def test_matching_count_alone_and_cross_kind_duplicate_ids_do_not_prove_form(scenario):
    scenario["form_proof"]["expected_items"]["FRQ"][0] = "MC:1"
    scenario["form_proof"]["actual_items"]["FRQ"][0] = "MC:1"
    with pytest.raises(GradebookError, match="FORM"):
        prepare_numeric_draft(**scenario)


def test_owner_callback_receives_and_must_authenticate_whole_form_proof(scenario):
    calls = []

    def check(
        candidate, target, identity, observation, floor, form, feedback, rounding
    ):
        assert form == scenario["form_proof"]
        assert form["packet_sha256"] == candidate["source_pins"]["packet_sha256"]
        calls.append(form)

    scenario["source_check"] = check
    prepare_numeric_draft(**scenario)
    assert len(calls) == 1


@pytest.mark.parametrize(
    "field,value",
    [("form_id", "DIFFERENT_ISSUED_FORM"), ("question_map_sha256", "b" * 64)],
)
def test_owner_must_authenticate_actual_form_and_canonical_qmap_not_hash_shape(
    scenario, field, value
):
    actual_source_form = copy.deepcopy(scenario["form_proof"])

    def check(
        candidate, target, identity, observation, floor, form, feedback, rounding
    ):
        if form != actual_source_form:
            raise GradebookError("ACTUAL_SOURCE_FORM_OR_QMAP_CHANGED")

    scenario["source_check"] = check
    scenario["form_proof"][field] = value
    with pytest.raises(GradebookError, match="SOURCE"):
        prepare_numeric_draft(**scenario)


def test_issued_form_native_namespaces_need_no_normalization(scenario):
    for field in ("expected_items", "actual_items"):
        scenario["form_proof"][field] = {
            "MC": [f"MC{i:02}" for i in range(1, 21)],
            "FRQ": [f"FRQ{i:02}" for i in range(1, 5)],
        }
    plan = prepare_numeric_draft(**scenario)
    assert plan["form_proof"] == scenario["form_proof"]


@pytest.mark.parametrize("raw", ["0.5", "39.5", "0.125"])
def test_canonical_native_finite_decimal_below_floor_is_exact(scenario, raw):
    administrative_floor(scenario)
    scenario["candidate"]["grade_preview"] = raw
    plan = prepare_numeric_draft(**scenario)
    assert plan["raw_grade_preview"] == raw
    assert plan["staged_grade_preview"] == "40"
    assert plan["floor_applied"] is True


@pytest.mark.parametrize(
    "raw", ["1/2", "79/2", "1/8", "0.50", "39.500", ".5", "00.5", "5e-1"]
)
def test_finite_fraction_alias_or_noncanonical_decimal_is_not_native_text(
    scenario, raw
):
    administrative_floor(scenario)
    scenario["candidate"]["grade_preview"] = raw
    with pytest.raises(GradebookError, match="GRADE_PREVIEW"):
        prepare_numeric_draft(**scenario)


def test_exact_above_floor_decimal_stays_held_without_rounding(scenario):
    administrative_floor(scenario)
    scenario["candidate"]["grade_preview"] = "40.5"
    with pytest.raises(GradebookError, match="ROUNDING_TIE"):
        prepare_numeric_draft(**scenario)


def test_full_canonical_feedback_and_prior_mc_note_share_one_owned_update(scenario):
    old_note = native._state(scenario["raw"])["sheets"][2]["cells"]["5:2"]["note"]
    proof = copy.deepcopy(scenario["feedback_proof"])
    authenticated = []

    def check(
        candidate, target, identity, observation, floor, form, feedback, rounding
    ):
        assert feedback == proof
        authenticated.append(copy.deepcopy(feedback))

    scenario["source_check"] = check
    plan = prepare_numeric_draft(**scenario)
    assert authenticated == [proof]
    assert plan["feedback_proof"] == proof
    assert len(plan["requests"]) == 1
    actual = applied(plan)
    note = native._state(actual)["sheets"][2]["cells"]["5:2"]["note"]
    assert note.startswith(old_note + "\n\n")
    assert proof["body"] in note
    assert note.count(proof["body"]) == 1
    assert (
        classify_readback(plan, actual, expected_plan_sha256=digest(plan))["status"]
        == "PLANNED_OUTPUT_OBSERVED"
    )
    scenario["raw"] = actual
    repeat = prepare_numeric_draft(**scenario)
    assert repeat["requests"] == []
    assert repeat["status"] == "NO_CHANGE"
    altered = native._state(actual)
    altered["sheets"][2]["cells"]["5:2"]["note"] = note.replace("Explain", "Changed")
    assert (
        classify_readback(
            plan, raw_from_state(altered), expected_plan_sha256=digest(plan)
        )["status"]
        == "DIVERGED"
    )


@pytest.mark.parametrize(
    "body",
    [
        None,
        "",
        " \n\t",
        42,
        "\ud800",
        "[[UNIT2 UNAPPROVED WHOLE NUMERIC injected]]",
        "[[END UNIT2 UNAPPROVED WHOLE NUMERIC]]",
    ],
)
def test_missing_invalid_or_marker_feedback_body_holds(scenario, body):
    scenario["feedback_proof"]["body"] = body
    with pytest.raises(GradebookError, match="FEEDBACK"):
        prepare_numeric_draft(**scenario)


@pytest.mark.parametrize(
    "field",
    [
        "source_sha256",
        "packet_sha256",
        "reading_sha256",
        "reading_manifest_sha256",
        "result_sha256",
        "policy_sha256",
        "academic_sha256",
        "current_head_sha256",
    ],
)
def test_feedback_source_binding_must_match_whole_numeric_source(scenario, field):
    scenario["feedback_proof"]["source_binding"][field] = "f" * 64
    with pytest.raises(GradebookError, match="FEEDBACK"):
        prepare_numeric_draft(**scenario)


@pytest.mark.parametrize(
    "field", ["formatter_sha256", "contract_sha256", "projection_sha256", "body_sha256"]
)
def test_feedback_pins_and_body_digest_are_required(scenario, field):
    scenario["feedback_proof"][field] = "invalid"
    with pytest.raises(GradebookError, match="FEEDBACK"):
        prepare_numeric_draft(**scenario)


@pytest.mark.parametrize(
    "field,value",
    [
        ("contract", "OTHER"),
        ("source_version", "UNIT2_COMPACT_FEEDBACK_V1"),
        ("component_scope", "MC_ONLY"),
        ("body_sha256", "f" * 64),
    ],
)
def test_feedback_contract_scope_and_actual_body_digest_are_exact(
    scenario, field, value
):
    scenario["feedback_proof"][field] = value
    with pytest.raises(GradebookError, match="FEEDBACK"):
        prepare_numeric_draft(**scenario)


@pytest.mark.parametrize(
    "field", ["formatter_sha256", "contract_sha256", "projection_sha256"]
)
def test_owner_authenticates_actual_saved_formatter_contract_and_projection(
    scenario, field
):
    saved = copy.deepcopy(scenario["feedback_proof"])

    def check(
        candidate, target, identity, observation, floor, form, feedback, rounding
    ):
        if feedback != saved:
            raise GradebookError("SAVED_CANONICAL_FEEDBACK_CHANGED")

    scenario["source_check"] = check
    scenario["feedback_proof"][field] = "f" * 64
    with pytest.raises(GradebookError, match="SOURCE"):
        prepare_numeric_draft(**scenario)


def test_owner_authenticates_saved_body_even_when_substituted_body_hash_matches(
    scenario,
):
    saved = copy.deepcopy(scenario["feedback_proof"])

    def check(
        candidate, target, identity, observation, floor, form, feedback, rounding
    ):
        if feedback != saved:
            raise GradebookError("SAVED_CANONICAL_FEEDBACK_CHANGED")

    scenario["source_check"] = check
    scenario["feedback_proof"]["body"] = "A different self-consistent body."
    scenario["feedback_proof"]["body_sha256"] = hashlib.sha256(
        scenario["feedback_proof"]["body"].encode()
    ).hexdigest()
    with pytest.raises(GradebookError, match="SOURCE"):
        prepare_numeric_draft(**scenario)


def test_feedback_mutation_after_prepare_is_held_without_send(scenario):
    plan = prepare_numeric_draft(**scenario)
    expected = digest(plan)
    scenario["feedback_proof"]["body"] = "Caller mutation does not mutate plan."
    assert plan["feedback_proof"]["body"] != scenario["feedback_proof"]["body"]
    plan["feedback_proof"]["body"] = "Changed after preparation."
    with pytest.raises(GradebookError, match="PLAN_CHANGED"):
        revalidate_numeric_draft(
            plan,
            raw=scenario["raw"],
            expected_plan_sha256=expected,
            source_check=scenario["source_check"],
        )


def test_owner_reauthenticates_feedback_before_send_and_note_capacity_holds(scenario):
    plan = prepare_numeric_draft(**scenario)

    def changed_saved_feedback(*_):
        raise GradebookError("SAVED_CANONICAL_FEEDBACK_CHANGED")

    with pytest.raises(GradebookError, match="SOURCE"):
        revalidate_numeric_draft(
            plan,
            raw=scenario["raw"],
            expected_plan_sha256=digest(plan),
            source_check=changed_saved_feedback,
        )
    scenario["feedback_proof"]["body"] = "x" * 50_000
    scenario["feedback_proof"]["body_sha256"] = hashlib.sha256(
        scenario["feedback_proof"]["body"].encode()
    ).hexdigest()
    with pytest.raises(GradebookError, match="CAPACITY"):
        prepare_numeric_draft(**scenario)


@pytest.mark.parametrize(
    "closed,hold", [(False, None), (None, "CLOSED_PERIOD_UNCONFIRMED")]
)
def test_closed_period_observation_retains_truthful_local_draft_hold(
    scenario, closed, hold
):
    scenario["canvas_observation"]["closed_period"] = closed
    plan = prepare_numeric_draft(**scenario)
    assert plan["canvas_observation"]["closed_period"] is closed
    assert plan["grading_period_hold"] == hold
    assert plan["currentness_hold"] == "FINAL_CURRENTNESS_REVIEW_REQUIRED"
    assert plan["publication_allowed"] is plan["is_final"] is False
    assert (
        plan["score_delivery_authorized"]
        is plan["comment_delivery_authorized"]
        is False
    )


@pytest.mark.parametrize("closed", [True, 0, "false"])
def test_known_closed_or_invalid_period_holds(scenario, closed):
    scenario["canvas_observation"]["closed_period"] = closed
    with pytest.raises(GradebookError, match="CANVAS|PERIOD"):
        prepare_numeric_draft(**scenario)


def test_closed_period_observation_must_be_explicit(scenario):
    del scenario["canvas_observation"]["closed_period"]
    with pytest.raises(GradebookError, match="CANVAS|PERIOD"):
        prepare_numeric_draft(**scenario)


def nearest_rounding(scenario):
    scenario["rounding_proof"] = {
        "contract": "UNIT2_TEACHER_ROUNDING_V1",
        "mode": "NEAREST_WHOLE_PERCENT",
        "application_order": "FLOOR_THEN_ROUND",
        "tie_breaker": "UNSPECIFIED",
        "assessment": "UNIT2",
        "paper_attempt": "R1",
        "evidence_ref": "fictional-explicit-Unit2-nearest-percent-rule",
        "evidence_sha256": "9" * 64,
        "scope": {
            k: scenario["target"][k] for k in ("origin", "course_id", "assignment_id")
        },
        "source_binding": {
            k: scenario["candidate"]["source_pins"][k]
            for k in (
                "source_sha256",
                "packet_sha256",
                "reading_sha256",
                "reading_manifest_sha256",
                "result_sha256",
                "policy_sha256",
                "academic_sha256",
                "current_head_sha256",
            )
        },
    }


def test_authorized_nearest_percent_preserves_raw_and_full_feedback(scenario):
    administrative_floor(scenario)
    nearest_rounding(scenario)
    scenario["candidate"]["grade_preview"] = "78.6"
    candidate = copy.deepcopy(scenario["candidate"])
    feedback = copy.deepcopy(scenario["feedback_proof"])
    plan = prepare_numeric_draft(**scenario)
    assert plan["staged_grade_preview"] == "79"
    assert plan["candidate"] == candidate
    assert plan["feedback_proof"] == feedback
    assert plan["raw_grade_preview"] == "78.6"
    assert plan["rounding_applied"] is True
    assert len(plan["requests"]) == 1
    assert plan["requests"][0]["updateCells"]["fields"] == "userEnteredValue,note"


@pytest.mark.parametrize(
    "preview,expected,exact",
    [
        ("236/3", "79", "236/3"),
        ("235/3", "78", "235/3"),
        ("121/3", "40", "121/3"),
        ("78.4", "78", "392/5"),
        ("90.6", "91", "453/5"),
        ("99.6", "100", "498/5"),
    ],
)
def test_exact_nearest_non_ties_preserve_native_rational(
    scenario, preview, expected, exact
):
    administrative_floor(scenario)
    scenario["candidate"]["grade_preview"] = preview
    original = copy.deepcopy(scenario)
    plan = prepare_numeric_draft(**scenario)
    assert plan["staged_grade_preview"] == expected
    assert plan["raw_grade_preview"] == preview
    assert plan["raw_grade_exact"] == exact
    assert plan["candidate"] == original["candidate"]
    assert plan["feedback_proof"] == original["feedback_proof"]
    assert scenario == original
    assert plan["requests"][0]["updateCells"]["rows"][0]["values"][0][
        "userEnteredValue"
    ] == {"numberValue": int(expected)}


@pytest.mark.parametrize("preview", ["40.5", "78.5", "99.5"])
def test_unit2_half_tie_policy_is_not_inherited(scenario, preview):
    administrative_floor(scenario)
    scenario["candidate"]["grade_preview"] = preview
    with pytest.raises(GradebookError, match="ROUNDING_TIE_HELD"):
        prepare_numeric_draft(**scenario)


@pytest.mark.parametrize("preview", ["39.9", "119/3", "0"])
def test_exact_administrative_floor_precedes_nearest_rounding(scenario, preview):
    administrative_floor(scenario)
    scenario["candidate"]["grade_preview"] = preview
    plan = prepare_numeric_draft(**scenario)
    assert plan["staged_grade_preview"] == plan["post_floor_grade_exact"] == "40"
    assert plan["floor_applied"] is True
    assert plan["rounding_applied"] is False


@pytest.mark.parametrize(
    "field,value",
    [
        ("contract", "OTHER"),
        ("mode", "HALF_UP"),
        ("application_order", "ROUND_THEN_FLOOR"),
        ("tie_breaker", "HALF_UP"),
        ("assessment", "UNIT1"),
        ("paper_attempt", "R2"),
        ("evidence_ref", ""),
        ("evidence_sha256", "bad"),
    ],
)
def test_rounding_authority_schema_is_required(scenario, field, value):
    scenario["rounding_proof"][field] = value
    with pytest.raises(GradebookError, match="ROUNDING_PROOF"):
        prepare_numeric_draft(**scenario)


@pytest.mark.parametrize(
    "field",
    [
        "source_sha256",
        "packet_sha256",
        "reading_sha256",
        "reading_manifest_sha256",
        "result_sha256",
        "policy_sha256",
        "academic_sha256",
        "current_head_sha256",
    ],
)
def test_nearest_rule_is_bound_to_all_eight_current_source_pins(scenario, field):
    scenario["rounding_proof"]["source_binding"][field] = "f" * 64
    with pytest.raises(GradebookError, match="ROUNDING_BINDING"):
        prepare_numeric_draft(**scenario)


def test_nearest_rule_is_assignment_scoped_and_required(scenario):
    saved = scenario["rounding_proof"]
    scenario["rounding_proof"] = None
    with pytest.raises(GradebookError, match="ROUNDING_PROOF"):
        prepare_numeric_draft(**scenario)
    scenario["rounding_proof"] = saved
    saved["scope"]["assignment_id"] = "22"
    with pytest.raises(GradebookError, match="ROUNDING_BINDING"):
        prepare_numeric_draft(**scenario)


def test_owner_must_authenticate_actual_rounding_authority_with_eight_args(scenario):
    expected = copy.deepcopy(scenario["rounding_proof"])
    seen = []

    def check(
        candidate, target, identity, observation, floor, form, feedback, rounding
    ):
        seen.append(rounding)
        if rounding != expected:
            raise GradebookError("ROUNDING_AUTHORITY_CHANGED")
        rounding["evidence_ref"] = "callback mutation is isolated"

    scenario["source_check"] = check
    plan = prepare_numeric_draft(**scenario)
    assert len(seen) == 1
    assert plan["rounding_proof"] == expected
    scenario["rounding_proof"]["evidence_sha256"] = "8" * 64
    with pytest.raises(GradebookError, match="SOURCE"):
        prepare_numeric_draft(**scenario)

    def old_seven(candidate, target, identity, observation, floor, form, feedback):
        return None

    scenario["source_check"] = old_seven
    with pytest.raises(GradebookError, match="SOURCE"):
        prepare_numeric_draft(**scenario)


def test_rounding_proof_mutation_revalidation_and_repeated_no_replay(scenario):
    administrative_floor(scenario)
    scenario["candidate"]["grade_preview"] = "236/3"
    saved = copy.deepcopy(scenario["rounding_proof"])

    def check(
        candidate, target, identity, observation, floor, form, feedback, rounding
    ):
        if rounding != saved:
            raise GradebookError("ROUNDING_AUTHORITY_CHANGED")

    scenario["source_check"] = check
    plan = prepare_numeric_draft(**scenario)
    expected = digest(plan)
    revalidate_numeric_draft(
        plan, raw=scenario["raw"], expected_plan_sha256=expected, source_check=check
    )
    actual = applied(plan)
    assert (
        classify_readback(plan, actual, expected_plan_sha256=expected)["status"]
        == "PLANNED_OUTPUT_OBSERVED"
    )
    scenario["raw"] = actual
    assert prepare_numeric_draft(**scenario)["requests"] == []
    scenario["rounding_proof"]["evidence_sha256"] = "8" * 64
    assert plan["rounding_proof"] == saved
    plan["rounding_proof"]["evidence_sha256"] = "8" * 64
    with pytest.raises(GradebookError, match="PLAN_CHANGED"):
        revalidate_numeric_draft(
            plan, raw=actual, expected_plan_sha256=expected, source_check=check
        )


@pytest.mark.parametrize("location", ["canvas", "native"])
def test_rounding_never_replaces_existing_grade_above_ninety(scenario, location):
    scenario["candidate"]["grade_preview"] = "78.6"
    if location == "canvas":
        scenario["canvas_observation"].update(
            score=95, grade="95", grade_observation="GRADED"
        )
    else:
        state = native._state(scenario["raw"])
        state["sheets"][2]["cells"]["5:2"]["userEnteredValue"] = {"numberValue": 95}
        scenario["raw"] = raw_from_state(state)
    with pytest.raises(GradebookError, match="CANVAS|DESTINATION"):
        prepare_numeric_draft(**scenario)


@pytest.mark.parametrize(
    "mutation",
    [
        None,
        "source_version",
        "formatter_sha256",
        "contract_sha256",
        "projection_sha256",
        "body",
    ],
)
def test_v3_feedback_needs_exact_owner_version_pins_and_body(scenario, mutation):
    scenario["feedback_proof"].update(
        source_version="UNIT2_COMPACT_FEEDBACK_V3",
        formatter_sha256="1" * 64,
        contract_sha256="2" * 64,
        projection_sha256="3" * 64,
    )
    saved = copy.deepcopy(scenario["feedback_proof"])

    def check(
        candidate, target, identity, observation, floor, form, feedback, rounding
    ):
        if feedback != saved:
            raise GradebookError("QUALIFIED_V3_SAVED_BODY_OR_PINS_CHANGED")

    scenario["source_check"] = check
    if mutation == "source_version":
        scenario["feedback_proof"][mutation] = "UNIT2_COMPACT_FEEDBACK_V2"
    elif mutation == "body":
        scenario["feedback_proof"]["body"] = (
            "Self-consistent substituted whole feedback."
        )
        scenario["feedback_proof"]["body_sha256"] = hashlib.sha256(
            scenario["feedback_proof"]["body"].encode()
        ).hexdigest()
    elif mutation:
        scenario["feedback_proof"][mutation] = "f" * 64
    if mutation:
        with pytest.raises(GradebookError, match="SOURCE"):
            prepare_numeric_draft(**scenario)
    else:
        plan = prepare_numeric_draft(**scenario)
        assert plan["feedback_proof"] == saved
        assert (
            saved["body"]
            in plan["requests"][0]["updateCells"]["rows"][0]["values"][0]["note"]
        )
        assert plan["publication_allowed"] is plan["is_final"] is False
