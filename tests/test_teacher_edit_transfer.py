"""Exact, offline teacher-decision transfer contracts with fictional records."""

import copy
import json

import pytest
from test_gradebook import snapshot as snapshot
from test_gradebook_native import binding as binding
from test_gradebook_native import initial_raw, raw_from_state

from canvas_mcp.gradebook import native
from canvas_mcp.gradebook.client import GradebookError
from canvas_mcp.gradebook.model import digest
from canvas_mcp.gradebook.teacher_edit_transfer import (
    classify_readback,
    prepare_transfer,
    revalidate_transfer,
)


@pytest.fixture
def scenario(snapshot, binding):
    snapshot["course_workflow_state"] = "available"
    snapshot["cells"]["101:21"].update(
        attempt=3,
        submitted_at="2026-10-10T12:00:00Z",
        grade_matches_current_submission=True,
    )
    record = {
        "evaluation_id": "a" * 64,
        "source_revision": "b" * 64,
        "result_revision": "c" * 64,
        "source_key": "d" * 64,
        "state": "READY_FOR_REVIEW",
        "policy": "fictional-sealed-policy-v1",
        "section": "B1",
        "pin": "0042",
        "course_id": "12",
        "user_id": "101",
        "assignment_id": "21",
        "paper_attempt": "R1",
        "form": "Core-X",
        "canvas_attempt": 3,
        "raw_score": 16,
        "raw_maximum": 20,
        "proposed_score": 16,
        "score_scale": "RAW_IDENTITY",
    }
    decision = {
        "evaluation_id": record["evaluation_id"],
        "source_revision": record["source_revision"],
        "result_revision": record["result_revision"],
        "policy": record["policy"],
        "decision_revision": "teacher-final-v1",
        "is_final": True,
        "total_score": 16,
        "points_possible": 20,
        "score_units": "CANVAS_POINTS",
        "feedback": "Fictional complete teacher feedback.\nExplain the second step.",
    }
    pins = {
        "registry_sha256": "e" * 64,
        "roster_sha256": "f" * 64,
        "by_pin": {"0042": "101"},
    }
    calls = []

    def source_check(selected, final, binding):
        # This represents domain-owned authentication of the actual M:O cells
        # and exact saved source/result. Neither a JSON flag nor an M string
        # supplies this authority to the Canvas adapter.
        assert selected["evaluation_id"] == record["evaluation_id"]
        assert final["feedback"] == decision["feedback"]
        assert binding == pins
        calls.append((copy.deepcopy(selected), copy.deepcopy(final)))

    return {
        "record": record,
        "decision": decision,
        "raw": initial_raw(snapshot, binding),
        "binding": binding,
        "baseline": snapshot,
        "current": copy.deepcopy(snapshot),
        "pin_binding": pins,
        "source_check": source_check,
    }, calls


def prepare(scenario):
    args, _ = scenario
    return prepare_transfer(**args)


def observed_after(args, plan):
    # Independent one-cell simulation: do not use production request application.
    state = native._state(args["raw"])
    write = plan["requests"][0]["updateCells"]
    assert write["fields"] == "userEnteredValue,note"
    assert write["start"] == {"sheetId": 2, "rowIndex": 5, "columnIndex": 2}
    assert len(write["rows"]) == len(write["rows"][0]["values"]) == 1
    state["sheets"][2]["cells"]["5:2"].update(write["rows"][0]["values"][0])
    return raw_from_state(state)


def test_exact_teacher_score_and_full_feedback_are_only_a_local_edit_plan(scenario):
    args, calls = scenario
    before = copy.deepcopy(args)
    plan = prepare(scenario)
    assert len(calls) == 1
    assert args == before
    write = plan["requests"][0]["updateCells"]
    cell = write["rows"][0]["values"][0]
    assert cell["userEnteredValue"] == {"numberValue": 16}
    assert cell["note"].endswith(args["decision"]["feedback"])
    assert plan["record"]["pin"] == "0042"
    assert plan["record"]["paper_attempt"] == "R1"
    assert plan["record"]["canvas_attempt"] == 3
    assert plan["score_delivery_authorized"] is False
    assert plan["comment_delivery_authorized"] is False
    assert plan["canvas_writes"] == plan["sheets_writes"] == 0
    assert (
        json.loads(json.dumps(native._state(observed_after(args, plan))))
        == plan["after_state"]
    )


@pytest.mark.parametrize("working_id", [2, 10])
def test_persisted_transfer_reopens_with_stable_digest_and_native_state(
    scenario, tmp_path, working_id
):
    args, _ = scenario
    args["binding"]["sheets"]["Working"] = working_id
    args["binding"]["working_protection_id"] = 100 + working_id
    args["raw"] = initial_raw(args["baseline"], args["binding"])
    plan = prepare(scenario)
    expected = digest(plan)
    path = tmp_path / "plan.json"
    path.write_text(json.dumps(plan))
    reopened = json.loads(path.read_text())
    assert digest(reopened) == expected
    revalidate_transfer(
        reopened,
        expected_plan_sha256=expected,
        raw=args["raw"],
        current=args["current"],
        pin_binding=args["pin_binding"],
        source_check=args["source_check"],
    )
    assert (
        classify_readback(reopened, args["raw"], expected_plan_sha256=expected)[
            "status"
        ]
        == "BEFORE_STILL_PRESENT"
    )
    state = native._state(args["raw"])
    update = reopened["requests"][0]["updateCells"]
    state["sheets"][working_id]["cells"]["5:2"].update(update["rows"][0]["values"][0])
    assert (
        classify_readback(
            reopened, raw_from_state(state), expected_plan_sha256=expected
        )["status"]
        == "PLANNED_OUTPUT_OBSERVED"
    )


@pytest.mark.parametrize(
    "field,value",
    [
        ("evaluation_id", "0" * 64),
        ("source_revision", "0" * 64),
        ("result_revision", "0" * 64),
        ("policy", "another-policy"),
        ("is_final", False),
        ("score_units", "RAW_POINTS"),
        ("total_score", None),
        ("total_score", True),
        ("total_score", 21),
        ("points_possible", 100),
        ("feedback", ""),
    ],
)
def test_stale_or_unfinal_or_incompatible_decision_is_held(scenario, field, value):
    args, _ = scenario
    args["decision"][field] = value
    with pytest.raises(GradebookError):
        prepare(scenario)


@pytest.mark.parametrize(
    "change",
    [
        "leading_zero_lost",
        "pin_join_changed",
        "duplicate_join",
        "held_result",
        "attempt_changed",
        "attempt_unknown",
        "excused",
        "higher",
        "missing_cell",
        "grade_not_current",
        "grade_current_unknown",
        "section_changed",
        "hidden",
        "existing_teacher_score",
        "existing_teacher_note",
        "teacher_formula",
    ],
)
def test_identity_evidence_and_existing_teacher_content_hold(scenario, change):
    args, _ = scenario
    current = args["current"]["cells"]["101:21"]
    if change == "leading_zero_lost":
        args["record"]["pin"] = "42"
    elif change == "pin_join_changed":
        args["pin_binding"]["by_pin"]["0042"] = "102"
    elif change == "duplicate_join":
        args["pin_binding"]["by_pin"]["0043"] = "101"
    elif change == "held_result":
        args["record"]["state"] = "HOLD"
    elif change == "attempt_changed":
        current["attempt"] = 4
    elif change == "attempt_unknown":
        args["record"]["canvas_attempt"] = None
    elif change == "excused":
        current.update(value="EX", excused=True)
    elif change == "higher":
        current.update(value=18, grade="18")
    elif change == "missing_cell":
        args["current"]["cells"].clear()
    elif change == "grade_not_current":
        current["grade_matches_current_submission"] = False
    elif change == "grade_current_unknown":
        current["grade_matches_current_submission"] = None
    elif change == "section_changed":
        args["current"]["students"][0]["sections"] = ["A1"]
    elif change == "hidden":
        current["visible"] = False
    else:
        state = native._state(args["raw"])
        cell = state["sheets"][2]["cells"]["5:2"]
        if change == "existing_teacher_score":
            cell["userEnteredValue"] = {"numberValue": 17}
        elif change == "existing_teacher_note":
            cell["note"] = "Private teacher correction"
        else:
            cell["userEnteredValue"] = {"formulaValue": "=16"}
        args["raw"] = raw_from_state(state)
    with pytest.raises(GradebookError):
        prepare(scenario)


def test_source_callback_is_required_and_cannot_mutate_inputs_or_claim_authority(
    scenario,
):
    args, _ = scenario
    args["source_check"] = None
    with pytest.raises(GradebookError, match="SOURCE_REVALIDATOR_REQUIRED"):
        prepare(scenario)
    args["source_check"] = lambda *unused: True
    with pytest.raises(GradebookError, match="SOURCE_REVALIDATOR_MUST_ASSERT"):
        prepare(scenario)

    def mutates(record, decision, pins):
        record["pin"] = "9999"
        decision["total_score"] = 0
        pins.clear()

    args["source_check"] = mutates
    plan = prepare(scenario)
    assert plan["record"]["pin"] == "0042"
    assert plan["decision"]["total_score"] == 16


def test_changed_teacher_decision_or_destination_cannot_reuse_prepared_plan(scenario):
    args, calls = scenario
    plan = prepare(scenario)
    plan_hash = digest(plan)
    revalidate_transfer(
        plan,
        expected_plan_sha256=plan_hash,
        raw=args["raw"],
        current=args["current"],
        pin_binding=args["pin_binding"],
        source_check=args["source_check"],
    )
    assert len(calls) == 2
    state = native._state(args["raw"])
    state["sheets"][2]["cells"]["5:2"]["note"] = "New teacher edit after preparation"
    with pytest.raises(GradebookError, match="DESTINATION_CHANGED"):
        revalidate_transfer(
            plan,
            expected_plan_sha256=plan_hash,
            raw=raw_from_state(state),
            current=args["current"],
            pin_binding=args["pin_binding"],
            source_check=args["source_check"],
        )

    def revoked(*unused):
        raise ValueError("Private source details must not escape")

    with pytest.raises(GradebookError, match="SOURCE_AUTHORITY_REVALIDATION_HELD"):
        revalidate_transfer(
            plan,
            expected_plan_sha256=plan_hash,
            raw=args["raw"],
            current=args["current"],
            pin_binding=args["pin_binding"],
            source_check=revoked,
        )


def test_harmless_fetch_timestamp_refresh_is_not_a_substantive_change(scenario):
    args, _ = scenario
    plan = prepare(scenario)
    args["current"]["fetched_at"] = "2099-01-01T00:00:00Z"
    revalidate_transfer(
        plan,
        expected_plan_sha256=digest(plan),
        raw=args["raw"],
        current=args["current"],
        pin_binding=args["pin_binding"],
        source_check=args["source_check"],
    )
    assert prepare(scenario) == plan


def test_replay_is_noop_only_for_exact_same_decision_and_full_feedback(scenario):
    args, _ = scenario
    plan = prepare(scenario)
    args["raw"] = observed_after(args, plan)
    replay = prepare(scenario)
    assert replay["requests"] == []
    assert replay["status"] == "NO_CHANGE"
    args["decision"]["decision_revision"] = "teacher-final-v2"
    with pytest.raises(GradebookError):
        prepare(scenario)


def test_interrupted_write_only_classifies_readback_and_never_authorizes_retry(
    scenario,
):
    args, _ = scenario
    plan = prepare(scenario)
    for raw, status in [
        (args["raw"], "BEFORE_STILL_PRESENT"),
        (observed_after(args, plan), "PLANNED_OUTPUT_OBSERVED"),
    ]:
        outcome = classify_readback(plan, raw, expected_plan_sha256=digest(plan))
        assert outcome["status"] == status
        assert outcome["retry_writes"] is False
        assert outcome["canvas_writes"] == outcome["sheets_writes"] == 0
    other = native._state(observed_after(args, plan))
    other["sheets"][1]["cells"]["5:2"]["userEnteredValue"] = {"numberValue": 9}
    assert (
        classify_readback(
            plan, raw_from_state(other), expected_plan_sha256=digest(plan)
        )["status"]
        == "DIVERGED"
    )


def test_plan_tampering_and_unrelated_cell_changes_are_held(scenario):
    args, _ = scenario
    plan = prepare(scenario)
    reference = digest(plan)
    plan["requests"][0]["updateCells"]["fields"] = "*"
    with pytest.raises(GradebookError, match="PLAN_CHANGED"):
        classify_readback(plan, args["raw"], expected_plan_sha256=reference)


def test_bound_fractional_projection_is_retained_without_rescoring_or_rounding(
    scenario,
):
    args, _ = scenario
    args["baseline"]["assignments"][0]["points_possible"] = 100
    args["current"] = copy.deepcopy(args["baseline"])
    args["raw"] = initial_raw(args["baseline"], args["binding"])
    args["record"].update(
        raw_score=31.5,
        raw_maximum=48,
        proposed_score=65.625,
        score_scale="grass_central_unit1_exact_percent_v1",
    )
    args["decision"].update(total_score=65.625, points_possible=100)
    plan = prepare(scenario)
    assert plan["record"]["raw_score"] == 31.5
    assert plan["record"]["raw_maximum"] == 48
    assert plan["record"]["proposed_score"] == 65.625
    assert plan["requests"][0]["updateCells"]["rows"][0]["values"][0][
        "userEnteredValue"
    ] == {"numberValue": 65.625}


def test_authenticated_teacher_final_and_advisory_score_remain_separate(scenario):
    args, _ = scenario
    args["decision"]["total_score"] = 14.25
    plan = prepare(scenario)
    assert plan["record"]["raw_score"] == plan["record"]["proposed_score"] == 16
    assert plan["decision"]["total_score"] == 14.25
    assert plan["requests"][0]["updateCells"]["rows"][0]["values"][0][
        "userEnteredValue"
    ] == {"numberValue": 14.25}


def test_matching_score_still_retains_full_teacher_feedback_separately(scenario):
    args, _ = scenario
    args["decision"]["total_score"] = 10
    plan = prepare(scenario)
    assert len(plan["requests"]) == 1
    assert plan["requests"][0]["updateCells"]["rows"][0]["values"][0]["note"].endswith(
        args["decision"]["feedback"]
    )
    assert (
        plan["score_delivery_authorized"]
        is plan["comment_delivery_authorized"]
        is False
    )


def test_report_timestamps_do_not_change_substantive_selection(scenario):
    args, _ = scenario
    original = prepare(scenario)
    args["record"].update(snapshot_id="new-fetch", evaluated_at="2099-01-01T00:00:00Z")
    args["decision"]["teacher_reviewed_at"] = "2099-01-01T00:00:00Z"
    assert prepare(scenario) == original


def test_async_authority_callback_is_refused_without_running_it(scenario):
    args, _ = scenario

    async def wrong_callback(*unused):
        raise AssertionError("Callback must not run asynchronously")

    args["source_check"] = wrong_callback
    with pytest.raises(GradebookError, match="SOURCE_REVALIDATOR_MUST_ASSERT"):
        prepare(scenario)


def test_changed_pin_authority_and_attempt_hold_prepared_transfer(scenario):
    args, _ = scenario
    plan = prepare(scenario)
    pins = copy.deepcopy(args["pin_binding"])
    pins["registry_sha256"] = "1" * 64
    with pytest.raises(GradebookError, match="PIN_AUTHORITY_CHANGED"):
        revalidate_transfer(
            plan,
            expected_plan_sha256=digest(plan),
            raw=args["raw"],
            current=args["current"],
            pin_binding=pins,
            source_check=args["source_check"],
        )
    args["current"]["cells"]["101:21"]["attempt"] = 4
    with pytest.raises(GradebookError, match="CANVAS_TARGET_CHANGED_AFTER_PREP"):
        revalidate_transfer(
            plan,
            expected_plan_sha256=digest(plan),
            raw=args["raw"],
            current=args["current"],
            pin_binding=args["pin_binding"],
            source_check=args["source_check"],
        )


def preservation_for(args):
    state = json.loads(json.dumps(native._state(args["raw"])))
    cell = state["sheets"]["2"]["cells"]["5:2"]
    return {
        "contract": "EXACT_LOCAL_EDIT_PRESERVATION_V1",
        "authorization_ref": "sha256:" + "9" * 64,
        "selection_sha256": digest(
            {"record": args["record"], "decision": args["decision"]}
        ),
        "spreadsheet_id": args["binding"]["spreadsheet_id"],
        "course_id": args["record"]["course_id"],
        "user_id": args["record"]["user_id"],
        "assignment_id": args["record"]["assignment_id"],
        "baseline_sha256": digest(args["baseline"]),
        "current_basis_sha256": digest(
            {
                "origin": args["current"]["origin"],
                "course_id": args["current"]["course_id"],
                "course_workflow_state": args["current"].get("course_workflow_state"),
                "student": {
                    k: args["current"]["students"][0].get(k) for k in ("id", "sections")
                },
                "assignment": args["current"]["assignments"][0],
                "cell": args["current"]["cells"]["101:21"],
            }
        ),
        "before_state_sha256": digest(state),
        "cell_sha256": digest(cell),
        "prior_value": 14.0,
        "prior_note": cell["note"],
    }


def edited_native(args, value=14):
    state = native._state(args["raw"])
    cell = state["sheets"][2]["cells"]["5:2"]
    cell["userEnteredValue"] = {"numberValue": value}
    cell["note"] = "Original teacher note.\nKeep this exact text."
    cell["userEnteredFormat"] = {"backgroundColor": {"red": 0.25}}
    args["raw"] = raw_from_state(state)
    return copy.deepcopy(native._state(args["raw"])["sheets"][2]["cells"]["5:2"])


def test_exact_operator_preservation_retains_history_and_note_prefix(scenario):
    args, _ = scenario
    old = edited_native(args)
    args["preservation"] = preservation_for(args)
    plan = prepare(scenario)
    assert plan["preservation"] == args["preservation"]
    assert plan["before_state"]["sheets"]["2"]["cells"]["5:2"] == old
    assert (
        plan["after_state"]["sheets"]["2"]["cells"]["5:2"]["userEnteredFormat"]
        == old["userEnteredFormat"]
    )
    update = plan["requests"][0]["updateCells"]
    assert update["fields"] == "userEnteredValue,note"
    assert update["rows"][0]["values"][0]["userEnteredValue"] == {"numberValue": 16}
    assert update["rows"][0]["values"][0]["note"].startswith(old["note"] + "\n\n")
    assert update["rows"][0]["values"][0]["note"].endswith(args["decision"]["feedback"])
    revalidate_transfer(
        plan,
        expected_plan_sha256=digest(plan),
        raw=args["raw"],
        current=args["current"],
        pin_binding=args["pin_binding"],
        source_check=args["source_check"],
    )
    before = copy.deepcopy(plan["before_state"])
    before["sheets"]["2"]["cells"]["5:2"].update(update["rows"][0]["values"][0])
    assert before == plan["after_state"]


def test_fresh_preservation_for_completed_same_decision_is_noop(scenario):
    args, _ = scenario
    edited_native(args)
    args["preservation"] = preservation_for(args)
    completed = prepare(scenario)
    args["raw"] = observed_after(args, completed)
    args["preservation"] = preservation_for(args)
    args["preservation"]["prior_value"] = args["decision"]["total_score"]

    replay = prepare(scenario)

    assert replay["selection_sha256"] == completed["selection_sha256"]
    assert replay["status"] == "NO_CHANGE"
    assert replay["requests"] == []
    assert replay["before_state"] == replay["after_state"] == completed["after_state"]
    revalidate_transfer(
        replay,
        expected_plan_sha256=digest(replay),
        raw=args["raw"],
        current=args["current"],
        pin_binding=args["pin_binding"],
        source_check=args["source_check"],
    )


@pytest.mark.parametrize("changed", ["decision", "feedback", "trailing_text"])
def test_preserved_noop_requires_complete_current_marked_feedback(scenario, changed):
    args, _ = scenario
    edited_native(args)
    args["preservation"] = preservation_for(args)
    completed = prepare(scenario)
    args["raw"] = observed_after(args, completed)
    if changed == "decision":
        args["decision"]["decision_revision"] = "teacher-final-v2"
    elif changed == "feedback":
        args["decision"]["feedback"] += "\nAdditional approved explanation."
    else:
        state = native._state(args["raw"])
        state["sheets"][2]["cells"]["5:2"]["note"] += "\nLater teacher note."
        args["raw"] = raw_from_state(state)
    args["preservation"] = preservation_for(args)
    args["preservation"]["prior_value"] = args["decision"]["total_score"]
    prior_note = args["preservation"]["prior_note"]

    plan = prepare(scenario)

    assert len(plan["requests"]) == 1
    replacement = plan["requests"][0]["updateCells"]["rows"][0]["values"][0]
    assert replacement["note"].startswith(prior_note + "\n\n")
    assert replacement["note"].endswith(args["decision"]["feedback"])


@pytest.mark.parametrize(
    "changed",
    [
        "selection_sha256",
        "spreadsheet_id",
        "course_id",
        "user_id",
        "assignment_id",
        "baseline_sha256",
        "current_basis_sha256",
        "before_state_sha256",
        "cell_sha256",
        "prior_value",
        "prior_note",
        "authorization_ref",
        "extra_field",
    ],
)
def test_operator_preservation_is_exact_not_a_bypass(scenario, changed):
    args, _ = scenario
    edited_native(args)
    args["preservation"] = preservation_for(args)
    args["preservation"][changed] = "changed"
    with pytest.raises(GradebookError, match="EXACT_EDIT_PRESERVATION_CHANGED"):
        prepare(scenario)


def test_operator_preservation_cannot_lower_higher_local_grade(scenario):
    args, _ = scenario
    edited_native(args, 17)
    args["preservation"] = preservation_for(args)
    args["preservation"]["prior_value"] = 17.0
    with pytest.raises(GradebookError, match="HIGHER_LOCAL_SCORE_PRESERVED"):
        prepare(scenario)


@pytest.mark.parametrize(
    "change", ["note", "unrelated_cell", "decision", "formula", "excused"]
)
def test_preservation_still_holds_actual_preimage_or_decision_changes(scenario, change):
    args, _ = scenario
    edited_native(args)
    args["preservation"] = preservation_for(args)
    state = native._state(args["raw"])
    cell = state["sheets"][2]["cells"]["5:2"]
    if change == "note":
        cell["note"] += " changed"
    elif change == "unrelated_cell":
        state["sheets"][2]["cells"].setdefault("6:2", {})["note"] = (
            "Another teacher edit"
        )
    elif change == "decision":
        args["decision"]["decision_revision"] = "teacher-final-revised"
    elif change == "formula":
        cell["userEnteredValue"] = {"formulaValue": "=14"}
    else:
        cell["userEnteredValue"] = {"stringValue": "EX"}
    args["raw"] = raw_from_state(state)
    with pytest.raises(GradebookError):
        prepare(scenario)


def observed_grade_after_blank_baseline(args):
    args["baseline"]["cells"]["101:21"].update(
        value=None,
        grade=None,
        workflow_state="unsubmitted",
        graded_at=None,
        posted_at=None,
    )
    args["current"]["cells"]["101:21"].update(
        value=14,
        grade="14",
        workflow_state="graded",
        graded_at="2026-10-17T10:00:00Z",
        posted_at="2026-10-17T10:00:00Z",
    )
    args["raw"] = initial_raw(args["baseline"], args["binding"])
    edited_native(args, 14)
    args["preservation"] = preservation_for(args)


def test_exact_preservation_reconciles_observed_grade_without_rebasing(scenario):
    args, _ = scenario
    observed_grade_after_blank_baseline(args)
    original_baseline = copy.deepcopy(args["baseline"])
    before = json.loads(json.dumps(native._state(args["raw"])))
    plan = prepare(scenario)
    assert plan["baseline"] == original_baseline
    assert plan["baseline"]["cells"]["101:21"]["value"] is None
    assert plan["current_basis"]["cell"]["value"] == 14
    assert plan["before_state"] == before
    assert plan["baseline_reconciled"] is True
    assert plan["canvas_comparison_reasons"] == [["canvas_changed_since_baseline"]]
    revalidate_transfer(
        plan,
        expected_plan_sha256=digest(plan),
        raw=args["raw"],
        current=args["current"],
        pin_binding=args["pin_binding"],
        source_check=args["source_check"],
    )
    assert args["baseline"] == original_baseline


@pytest.mark.parametrize(
    "changed",
    [
        "attempt",
        "submitted_at",
        "excused",
        "visible",
        "late_policy",
        "local_grade",
        "prior_grade",
    ],
)
def test_exact_baseline_reconciliation_does_not_remove_other_holds(scenario, changed):
    args, _ = scenario
    observed_grade_after_blank_baseline(args)
    if changed == "local_grade":
        edited_native(args, 13)
    elif changed == "prior_grade":
        args["baseline"]["cells"]["101:21"]["value"] = 13
    elif changed == "late_policy":
        args["baseline"]["cells"]["101:21"]["points_deducted"] = 1
        args["current"]["cells"]["101:21"]["points_deducted"] = 1
    else:
        args["baseline"]["cells"]["101:21"][changed] = {
            "attempt": 2,
            "submitted_at": None,
            "excused": True,
            "visible": False,
        }[changed]
    args["preservation"] = preservation_for(args)
    if changed == "local_grade":
        args["preservation"]["prior_value"] = 13
    with pytest.raises(GradebookError):
        prepare(scenario)
