"""Fictional offline comparisons; no Canvas/Sheet/model calls."""

import copy
import hashlib

import pytest
from test_gradebook import snapshot as snapshot
from test_gradebook_native import binding as binding
from test_gradebook_native import initial_raw, raw_from_state

from canvas_mcp.gradebook import canvas_primary_current_attempt as m
from canvas_mcp.gradebook import native
from canvas_mcp.gradebook.client import GradebookError
from canvas_mcp.gradebook.model import digest


@pytest.fixture(params=["blank", "zero"])
def case(snapshot, binding, request, tmp_path):
    old = copy.deepcopy(snapshot)
    cur = copy.deepcopy(snapshot)
    key = "101:21"
    cell = old["cells"][key]
    cell.update(
        attempt=None,
        workflow_state="unsubmitted",
        submitted_at=None,
        graded_at=None,
        posted_at=None,
        value=None,
        grade=None,
        visible=True,
        excused=False,
        grade_matches_current_submission=True,
        points_deducted=None,
        late=False,
        late_policy_status=None,
    )
    if request.param == "zero":
        cell.update(
            workflow_state="graded",
            value=0.0,
            grade="0",
            graded_at="2026-11-01T12:00:00Z",
            posted_at="2026-11-01T12:00:00Z",
        )
    cur["cells"][key] = copy.deepcopy(cell)
    cur["cells"][key].update(
        attempt=1,
        workflow_state="submitted",
        submitted_at="2026-11-12T12:00:00Z",
        graded_at="2026-11-01T12:00:00Z",
        posted_at="2026-11-01T12:00:00Z",
        value=0.0,
        grade="0",
        late=True,
        grade_matches_current_submission=False,
    )
    rec = {
        "course_id": "12",
        "assignment_id": "21",
        "user_id": "101",
        "pin": "0042",
        "canvas_attempt": 1,
        "raw_score": 5,
        "raw_maximum": 5,
        "policy": "b" * 64,
        "proposed_score": 20,
        "source_lane": "SDMGRASS_FORMATIVE",
        "delivery_policy": "SCORE_ONLY",
    }
    pro = {
        "policy": "b" * 64,
        "approval_state": "UNAPPROVED",
        "academic_accepted": False,
        "score_units": "CANVAS_POINTS",
        "total_score": 20,
        "points_possible": 20,
        "feedback": "Fictional feedback",
        "source_lane": "SDMGRASS_FORMATIVE",
        "delivery_policy": "SCORE_ONLY",
    }
    meta = {
        "id": 21,
        "course_id": 12,
        "name": "Practice",
        "description": "practice",
        "published": True,
        "grading_type": "points",
        "points_possible": 20,
        "submission_types": ["online_upload"],
        "external_tool_tag_attributes": None,
    }
    ab = {
        "course_id": "12",
        "assignment_id": "21",
        "excluded": False,
        "provider": "Canvas",
        "assignment_metadata": meta,
        "assignment_metadata_sha256": digest(meta),
    }
    evidence = {
        "contract": "CANVAS_PRIMARY_VISUAL_ADVISORY_V1",
        "state": "REVIEWED_ADVISORY",
        "teacher_accepted": False,
        "publication_allowed": False,
        "holds": [],
        "source_lane": "CANVAS_CURRENT_UPLOAD_VISUAL_OCR",
        "policy": "ASSIGNED_QUESTION_HALF_FULL_PARTICIPATION",
        "ocr_state": "ALL_SOURCE_FILES_VALIDATED",
        "correct_assignment": True,
        "submission_type": "online_upload",
        "required": 5,
        "attempted_lower_bound": 5,
        "course_id": "12",
        "assignment_id": "21",
        "user_id": "101",
        "pin": "0042",
        "canvas_attempt": 1,
        "canvas_source_sha256": "a" * 64,
        "review_sha256": "c" * 64,
        "policy_sha256": "b" * 64,
        "assignment_sha256": digest(meta),
        "record_sha256": digest(rec),
        "proposal_sha256": digest(pro),
        "current_cell_sha256": digest(cur["cells"][key]),
    }
    original = tmp_path / "fictional.jpg"
    original.write_bytes(b"fictional")
    evidence["originals"] = [
        {
            "path": str(original),
            "sha256": hashlib.sha256(original.read_bytes()).hexdigest(),
        }
    ]
    registry = {
        "contract": "CANVAS_PRIMARY_TARGET_PROTECTION_V1",
        "population_state": "COMPLETE",
        "population_evidence_sha256": "d" * 64,
        "protected_students": [{"user_id": "202", "evidence_sha256": "e" * 64}],
        "coverage": [],
        "protected_targets": [],
    }
    raw = initial_raw(old, binding)
    args = {
        "evidence": evidence,
        "record": rec,
        "proposal": pro,
        "assignment_binding": ab,
        "binding": binding,
        "raw": raw,
        "baseline": old,
        "current": cur,
        "pin_binding": {"by_pin": {"0042": "101"}},
        "protection_registry": registry,
        "source_authority": lambda e: None,
        "protection_authority": lambda t, c: None,
    }
    evidence["current_attempt_review"] = m.make_binding(
        **{
            k: args[k]
            for k in (
                "evidence",
                "record",
                "proposal",
                "assignment_binding",
                "binding",
                "raw",
                "baseline",
                "current",
                "pin_binding",
                "protection_registry",
            )
        }
    )
    return args


def rebind(c):
    c["evidence"]["record_sha256"] = digest(c["record"])
    c["evidence"]["proposal_sha256"] = digest(c["proposal"])
    c["evidence"]["current_cell_sha256"] = digest(c["current"]["cells"]["101:21"])
    c["evidence"]["current_attempt_review"] = m.make_binding(
        **{
            k: c[k]
            for k in (
                "evidence",
                "record",
                "proposal",
                "assignment_binding",
                "binding",
                "raw",
                "baseline",
                "current",
                "pin_binding",
                "protection_registry",
            )
        }
    )


def test_projection_is_exact_and_nonmutating(case):
    before = copy.deepcopy(case)
    out = m.prepare_comparison(**case)
    assert out["publication_allowed"] is False
    assert (
        out["comparison_baseline"]["cells"]["101:21"][
            "grade_matches_current_submission"
        ]
        is False
    )
    assert (
        out["comparison_baseline"]["cells"]["101:21"]
        == case["current"]["cells"]["101:21"]
    )
    assert case == before


def test_attempt_two_not_coerced(case):
    case["record"]["canvas_attempt"] = case["evidence"]["canvas_attempt"] = case[
        "current"
    ]["cells"]["101:21"]["attempt"] = 2
    rebind(case)
    out = m.prepare_comparison(**case)
    assert out["comparison_baseline"]["cells"]["101:21"]["attempt"] == 2


@pytest.mark.parametrize(
    "change",
    [
        "true_flag",
        "attempt_bool",
        "future_grade",
        "unknown_time",
        "naive_time",
        "prior_positive",
        "current_positive",
        "hidden",
        "excused",
        "deduction",
        "late_override",
        "changed_missing",
        "wrong_target",
        "wrong_pin",
        "protected",
        "source_denied",
        "higher_edit",
        "formula_edit",
        "note_drift",
        "unbound_review",
        "edpuzzle",
    ],
)
def test_unsafe_states_hold(case, change):
    cell = case["current"]["cells"]["101:21"]
    old = case["baseline"]["cells"]["101:21"]
    if change == "true_flag":
        cell["grade_matches_current_submission"] = True
    elif change == "attempt_bool":
        cell["attempt"] = True
    elif change == "future_grade":
        cell["graded_at"] = "2026-11-13T00:00:00Z"
    elif change == "unknown_time":
        cell["graded_at"] = None
    elif change == "naive_time":
        cell["graded_at"] = "2026-11-01T12:00:00"
    elif change == "prior_positive":
        old["value"] = 5
    elif change == "current_positive":
        cell["value"] = 20
    elif change == "hidden":
        cell["visible"] = False
    elif change == "excused":
        cell["excused"] = True
    elif change == "deduction":
        cell["points_deducted"] = 2
    elif change == "late_override":
        cell["late_policy_status"] = "late"
    elif change == "changed_missing":
        cell["missing"] = not cell["missing"]
    elif change == "wrong_target":
        case["evidence"]["user_id"] = "999"
    elif change == "wrong_pin":
        case["pin_binding"]["by_pin"]["0042"] = "999"
    elif change == "protected":
        case["protection_authority"] = lambda *args: (_ for _ in ()).throw(
            ValueError("protected")
        )
    elif change == "source_denied":
        case["source_authority"] = lambda *args: (_ for _ in ()).throw(
            ValueError("source")
        )
    elif change in ("higher_edit", "formula_edit", "note_drift"):
        state = native._state(case["raw"])
        target = state["sheets"][case["binding"]["sheets"]["Working"]][
            "cells"
        ].setdefault("5:2", {})
        if change == "higher_edit":
            target["userEnteredValue"] = {"numberValue": 15}
        elif change == "formula_edit":
            target["userEnteredValue"] = {"formulaValue": "=0"}
        else:
            target["note"] = "teacher note changed"
        case["raw"] = raw_from_state(state)
    elif change == "unbound_review":
        case["evidence"]["current_attempt_review"]["native_raw_sha256"] = "0" * 64
    else:
        case["assignment_binding"]["provider"] = "Edpuzzle"
    if change not in (
        "note_drift",
        "unbound_review",
        "wrong_target",
        "wrong_pin",
        "protected",
        "source_denied",
        "higher_edit",
        "formula_edit",
        "edpuzzle",
    ):
        try:
            rebind(case)
        except GradebookError:
            pass
    with pytest.raises((GradebookError, ValueError, KeyError)):
        m.prepare_comparison(**case)


def test_existing_compare_checks_only_the_reviewed_projection(case):
    from canvas_mcp.gradebook.model import compare_edits

    original = copy.deepcopy(case["baseline"])
    out = m.prepare_comparison(**case)
    projected = out["comparison_baseline"]
    envelope = {
        "course_id": projected["course_id"],
        "snapshot_id": digest(projected),
        "edits": [{"user_id": "101", "assignment_id": "21", "value": 20}],
    }
    review = compare_edits(projected, case["current"], envelope)
    assert (
        len(review["changes"]) == 1
        and review["changes"][0]["status"] == "ready_for_review"
        and review["changes"][0]["reasons"] == []
    )
    assert (
        case["baseline"] == original
        and case["baseline"]["cells"]["101:21"]["grade_matches_current_submission"]
        is True
    )


def test_first_submission_review_cannot_coexist(case):
    case["evidence"]["first_submission_review"] = {"contract": "not-current-attempt"}
    with pytest.raises(GradebookError, match="STALE_ZERO_REVIEW_VARIANT_HELD"):
        m.prepare_comparison(**case)


def test_monitored_student_zero_stays_held_even_with_fake_allow_authority(case):
    case["protection_registry"]["protected_students"][0]["user_id"] = "101"
    rebind(case)
    with pytest.raises(
        GradebookError,
        match="PROTECTED_ZERO_PROVENANCE_HELD|STALE_ZERO_SWEEP_PROTECTED_STUDENT_HELD",
    ):
        m.prepare_comparison(**case)


def test_original_file_bytes_are_independently_checked(case):
    from pathlib import Path

    Path(case["evidence"]["originals"][0]["path"]).write_bytes(b"changed")
    with pytest.raises(GradebookError, match="PRIMARY_SOURCE_CHANGED"):
        m.prepare_comparison(**case)


@pytest.mark.parametrize("field", ["late_policy_status", "late", "missing"])
def test_missing_context_in_both_cells_is_not_treated_as_clear(case, field):
    del case["baseline"]["cells"]["101:21"][field]
    del case["current"]["cells"]["101:21"][field]
    rebind(case)
    with pytest.raises(GradebookError, match="STALE_ZERO_CONTEXT_HELD"):
        m.prepare_comparison(**case)
