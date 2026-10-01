"""Independent fictional Unit1 pair examples; no service/client is instantiated."""

import copy
import json
import stat

import pytest

from canvas_mcp.gradebook.client import GradebookError
from canvas_mcp.gradebook.model import digest
from canvas_mcp.gradebook.store import Store
from canvas_mcp.gradebook.unit1_preview import (
    BINDING_FIELDS,
    DIGEST_FIELDS,
    PERCENT_SCALE,
    build_pair_preview,
    project_raw_score,
    retain_pair_preview,
)


@pytest.fixture
def inputs():
    pair = {
        "schema_version": 1,
        "kind": "grass_unit1_accepted_pair_v1",
        "case_key": "fictional-case",
        "academic_assignment_id": "fictional-unit1",
        "origin": "https://canvas.example.invalid",
        "course_id": "101",
        "canvas_assignment_id": "201",
        "canvas_user_id": "301",
        "pin": "0042",
        "section_id": "fictional-section",
        "form_id": "CT-A",
        "paper_attempt": "R2",
        "raw_score": "16",
        "raw_maximum": "32",
        "canvas_maximum": "100",
        "scale_contract": PERCENT_SCALE,
        "rounding": "NEAREST_WHOLE_POINT",
        "canonical_projected_score": "50",
        "score": "50",
        "score_units": "CANVAS_POINTS",
        "feedback": "Teacher-approved fictional feedback, paper R2.",
        **{
            field: character * 64
            for field, character in zip(
                (
                    "decision_id",
                    "source_revision",
                    "result_revision",
                    "policy_revision",
                    "identity_revision",
                    "binding_revision",
                    "form_sha256",
                ),
                "abcdefa",
                strict=True,
            )
        },
        **dict.fromkeys(DIGEST_FIELDS, "b" * 64),
    }
    pair["identity_revision"] = "identity-" + "a" * 64
    pair["policy_revision"] = "unit1-policy-review-v1"
    pair["binding_revision"] = "binding-" + "c" * 64
    snapshot = {
        "schema_version": 1,
        "origin": pair["origin"],
        "course_id": "101",
        "course_workflow_state": "available",
        "fetched_at": "2026-10-01T20:00:00Z",
        "students": [{"id": "301"}],
        "assignments": [
            {"id": "201", "points_possible": 100, "grading_type": "points"}
        ],
        "cells": {
            "301:201": {
                "value": 40,
                "excused": False,
                "visible": True,
                "attempt": 1,
                "submitted_at": "2026-09-30T12:00:00Z",
            }
        },
    }
    return pair, {
        "expected_pair_sha256": digest(pair),
        "current_binding": {key: pair[key] for key in BINDING_FIELDS},
        "baseline": snapshot,
        "current": copy.deepcopy(snapshot),
        "canvas_attempt": 1,
        "canvas_submitted_at": "2026-09-30T12:00:00Z",
        "teacher_final": False,
        "score_permission": True,
        "feedback_permission": True,
        "target_context": {
            "assignment": {
                "id": 201,
                "course_id": 101,
                "published": True,
                "points_possible": 100,
                "grading_type": "points",
                "moderated_grading": False,
                "anonymous_grading": False,
                "group_category_id": None,
                "has_sub_assignments": False,
                "use_rubric_for_grading": False,
            },
            "submission": copy.deepcopy(snapshot["cells"]["301:201"]),
            "closed_period": False,
        },
    }


def test_pair_projection_is_disabled_private_and_preserves_exact_values(
    inputs, tmp_path
):
    pair, kwargs = inputs
    before = copy.deepcopy((pair, kwargs))
    preview = build_pair_preview(pair, **kwargs)
    assert preview["accepted_pair"] == pair
    assert preview["accepted_pair"]["pin"] == "0042"
    assert preview["score"]["status"] == "CANDIDATE_FOR_PREVIEW"
    assert preview["feedback"]["delivery"] == "NOT_SENT"
    assert preview["publication_ready"] is False and preview["verified_pair"] is False
    assert preview["canvas_writes"] == 0
    assert (
        not {"edits", "confirmation_token", "review_id", "operation_id"}
        & preview.keys()
    )
    assert (pair, kwargs) == before
    store = Store(tmp_path)
    receipt, path = retain_pair_preview(store, preview)
    assert store.load("receipt", receipt) == preview
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert retain_pair_preview(store, preview)[0] == receipt
    assert len(list(tmp_path.glob("receipt-*.json"))) == 1


@pytest.mark.parametrize(
    "form,raw,maximum,expected",
    [
        ("CT-A", "16", "32", "50"),
        ("C-B", "20", "40", "50"),
        ("AD-C", "24", "48", "50"),
        ("CT-A", "16.5", "32", "52"),
        ("C-A", "20.2", "40", "51"),
        ("AD-A", "0", "48", "0"),
    ],
)
def test_printed_form_specific_scale_examples(inputs, form, raw, maximum, expected):
    pair, _ = inputs
    pair.update(form_id=form, raw_score=raw, raw_maximum=maximum)
    assert project_raw_score(pair) == expected


def test_raw_identity_is_explicit_and_preserves_half_points(inputs):
    pair, _ = inputs
    pair.update(
        raw_score="16.5",
        canvas_maximum="32",
        scale_contract="RAW_IDENTITY",
        rounding="NONE",
    )
    assert project_raw_score(pair) == "16.5"


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("16.15" + "9" * 58, "50"),
        ("16.16", "51"),
        ("16.16" + "0" * 57 + "1", "51"),
    ],
)
def test_long_decimals_just_below_at_and_above_rounding_boundary(inputs, raw, expected):
    pair, _ = inputs
    pair["raw_score"] = raw
    assert project_raw_score(pair) == expected


@pytest.mark.parametrize(
    "field,value",
    [
        ("raw_score", True),
        ("raw_score", 16.5),
        ("raw_score", "NaN"),
        ("raw_score", "-1"),
        ("raw_score", "33"),
        ("raw_maximum", "40"),
        ("canvas_maximum", "40"),
        ("scale_contract", "INFERRED_PERCENT"),
        ("rounding", "BANKERS"),
        ("form_id", "CORE"),
        ("form_id", "CT-UNKNOWN"),
        ("form_id", "CT-Z"),
        ("form_id", "C-Z"),
        ("form_id", "AD-Z"),
        ("form_id", "A-A"),
    ],
)
def test_unknown_units_forms_and_invalid_numeric_values_fail(inputs, field, value):
    pair, _ = inputs
    pair[field] = value
    with pytest.raises(GradebookError):
        project_raw_score(pair)


@pytest.mark.parametrize(
    "field",
    [
        "decision_id",
        "source_revision",
        "result_revision",
        "policy_revision",
        "identity_revision",
        "binding_revision",
        "form_sha256",
        "canvas_user_id",
        "canvas_assignment_id",
        "course_id",
        "paper_attempt",
    ],
)
def test_changed_substantive_basis_is_rejected_even_for_unchanged_score(inputs, field):
    pair, kwargs = inputs
    kwargs["baseline"]["cells"]["301:201"]["value"] = 50
    kwargs["current"]["cells"]["301:201"]["value"] = 50
    kwargs["current_binding"][field] = "changed"
    with pytest.raises(GradebookError, match="PAIR_BINDING_CHANGED"):
        build_pair_preview(pair, **kwargs)


def test_tampered_feedback_fails_independent_receipt_hash(inputs):
    pair, kwargs = inputs
    pair["feedback"] = "Unaccepted replacement"
    with pytest.raises(GradebookError, match="PAIR_INTEGRITY_MISMATCH"):
        build_pair_preview(pair, **kwargs)


def test_paper_r2_review_does_not_infer_canvas_attempt_two(inputs):
    pair, kwargs = inputs
    preview = build_pair_preview(
        pair, **dict(kwargs, canvas_attempt=None, canvas_submitted_at=None)
    )
    assert preview["accepted_pair"]["paper_attempt"] == "R2"
    assert preview["canvas_attempt"] is None
    assert "exact_canvas_attempt_required" in preview["score"]["holds"]
    assert preview["publication_ready"] is False
    wrong = build_pair_preview(pair, **dict(kwargs, canvas_attempt=2))
    assert "canvas_attempt_binding_changed" in wrong["score"]["holds"]
    assert (
        build_pair_preview(pair, **kwargs)["score"]["status"] == "CANDIDATE_FOR_PREVIEW"
    )


@pytest.mark.parametrize("flag", [True, None])
def test_teacher_final_and_unknown_protection_hold(inputs, flag):
    pair, kwargs = inputs
    assert (
        build_pair_preview(pair, **dict(kwargs, teacher_final=flag))["score"]["status"]
        == "HELD"
    )


def test_higher_scores_excused_targets_and_changed_maximum_preserved(inputs):
    pair, kwargs = inputs
    kwargs["current"]["cells"]["301:201"]["value"] = 70
    assert (
        "higher_canvas_score_protected"
        in build_pair_preview(pair, **kwargs)["score"]["holds"]
    )
    kwargs["current"]["cells"]["301:201"].update(value="EX", excused=True)
    assert (
        "excused_target_protected"
        in build_pair_preview(pair, **kwargs)["score"]["holds"]
    )
    kwargs["current"] = copy.deepcopy(kwargs["baseline"])
    kwargs["current"]["assignments"][0]["points_possible"] = 40
    assert (
        "assignment_score_scale_changed"
        in build_pair_preview(pair, **kwargs)["score"]["holds"]
    )


def test_score_match_keeps_feedback_pending_and_permissions_independent(inputs):
    pair, kwargs = inputs
    kwargs["baseline"]["cells"]["301:201"]["value"] = 50
    kwargs["current"]["cells"]["301:201"]["value"] = 50
    kwargs["target_context"]["submission"]["value"] = 50
    preview = build_pair_preview(pair, **dict(kwargs, feedback_permission=False))
    assert preview["score"]["status"] == "NO_SCORE_CHANGE"
    assert preview["feedback"]["delivery"] == "NOT_SENT"
    assert preview["feedback"]["holds"] == ["feedback_permission_required"]
    assert preview["verified_pair"] is False
    preview = build_pair_preview(pair, **dict(kwargs, score_permission=False))
    assert "score_permission_required" in preview["score"]["holds"]
    assert preview["feedback"]["holds"] == []


def test_teacher_override_never_replaced_by_raw_projection(inputs):
    pair, kwargs = inputs
    pair["score"] = "60"
    kwargs["expected_pair_sha256"] = digest(pair)
    preview = build_pair_preview(pair, **kwargs)
    assert preview["canonical_projected_score"] == "50"
    assert preview["accepted_pair"]["score"] == "60"
    assert preview["publication_ready"] is False
    assert "teacher_acceptance_unverified" in preview["release_holds"]


def test_permission_claims_never_unlock_publication(inputs):
    pair, kwargs = inputs
    result = build_pair_preview(pair, **kwargs)
    assert result["release_holds"] == [
        "teacher_acceptance_unverified",
        "release_authentication_not_connected",
        "feedback_transport_not_connected",
        "live_freshness_not_established",
    ]
    assert "Synthetic Student" not in json.dumps(result)


def test_owner_revision_tokens_and_separate_digests_are_preserved(inputs):
    pair, kwargs = inputs
    result = build_pair_preview(pair, **kwargs)
    assert result["accepted_pair"]["identity_revision"] == "identity-" + "a" * 64
    assert result["accepted_pair"]["policy_revision"] == "unit1-policy-review-v1"
    assert result["accepted_pair"]["identity_sha256"] == "b" * 64


@pytest.mark.parametrize("now", [40, None, 60])
def test_accepted_score_equal_baseline_never_hides_later_canvas_change(inputs, now):
    pair, kwargs = inputs
    kwargs["baseline"]["cells"]["301:201"]["value"] = 50
    kwargs["current"]["cells"]["301:201"]["value"] = now
    kwargs["target_context"]["submission"]["value"] = now
    preview = build_pair_preview(pair, **kwargs)
    assert preview["score"]["status"] == "HELD"
    assert "canvas_changed_since_baseline" in preview["score"]["holds"]
    assert preview["feedback"]["delivery"] == "NOT_SENT"


def test_unknown_or_disagreeing_exact_visibility_holds_without_losing_review_pair(
    inputs,
):
    pair, kwargs = inputs
    held = build_pair_preview(pair, **dict(kwargs, target_context=None))
    assert "exact_assignment_context_required" in held["score"]["holds"]
    assert held["accepted_pair"] == pair
    kwargs["target_context"]["submission"]["visible"] = False
    held = build_pair_preview(pair, **kwargs)
    assert "exact_assignment_snapshot_conflict" in held["score"]["holds"]
    assert "exact_assignment_context_held" in held["score"]["holds"]
    assert held["publication_ready"] is False


@pytest.mark.parametrize(
    "field,value",
    [
        ("published", False),
        ("moderated_grading", True),
        ("anonymous_grading", True),
        ("group_category_id", 10),
        ("use_rubric_for_grading", True),
    ],
)
def test_exact_assignment_special_workflows_remain_held(inputs, field, value):
    pair, kwargs = inputs
    kwargs["target_context"]["assignment"][field] = value
    assert (
        "exact_assignment_context_held"
        in build_pair_preview(pair, **kwargs)["score"]["holds"]
    )
