"""Pure rounding with fictional records; source acceptance never transfers."""

import copy
import hashlib
import json
from decimal import Decimal

import pytest
from test_gradebook import snapshot as snapshot

from canvas_mcp.gradebook.client import GradebookError
from canvas_mcp.gradebook.model import compare_edits, digest, submission_cell
from canvas_mcp.gradebook.percent_rounding import (
    plan_percent_rounding,
    round_score_percent,
)
from canvas_mcp.gradebook.publish import require_simple_target

KEY = "12:101:21"


def record(value=74.5, maximum=100):
    return {
        "course_id": "12",
        "user_id": "101",
        "assignment_id": "21",
        "value": value,
        "points_possible": maximum,
        "grading_type": "points",
        "feedback": "Entire fictional feedback\r\n  preserve spaces and café 🧪\n",
        "context": {
            "attempt": None,
            "submitted_at": None,
            "visible": True,
            "submission_types": ["on_paper"],
            "flags": {"missing": False},
        },
        "source_qualification": {"accepted": True, "original_pair_ref": "a" * 64},
    }


def plan(records, **options):
    args = {
        "assignment_scope": {"12": {"21"}},
        "eligible_targets": set(records),
        "protected_targets": set(),
        "policy_ref": "fictional-user-rounding-decision",
    }
    args.update(options)
    return plan_percent_rounding(records, **args)


@pytest.mark.parametrize(
    "score,maximum,percent,points",
    [
        ("74.5", 100, 75, 75),
        ("2.5", 100, 3, 3),
        ("3.5", 100, 4, 4),
        ("74.4999999999999999", 100, 74, 74),
        ("0.5", 100, 1, 1),
        ("0.4999999999", 100, 0, 0),
        (0, 100, 0, 0),
        (100, 100, 100, 100),
        ("18.625", 25, 75, 18.75),
        ("7.425", 15, 50, 7.5),
        (74.5, 100, 75, 75),
        (Decimal("74.5"), Decimal("100"), 75, 75),
    ],
)
def test_whole_percent_uses_decimal_half_up_not_integer_points_or_bankers(
    score, maximum, percent, points
):
    out = round_score_percent(score, maximum)
    assert out["rounded_percent"] == percent
    assert out["rounded_points"] == points
    assert Decimal(out["rounded_points_decimal"]) == Decimal(str(points))


@pytest.mark.parametrize(
    "score,maximum",
    [
        (True, 100),
        (1, False),
        (-1, 100),
        (1, 0),
        (101, 100),
        ("NaN", 100),
        ("Infinity", 100),
        ("=1+1", 100),
        ([], 100),
        ("1e-101", 100),
        (1, "1e101"),
        ("private sentinel", 100),
    ],
)
def test_invalid_math_is_held_without_private_error_text(score, maximum):
    with pytest.raises(GradebookError) as error:
        round_score_percent(score, maximum)
    assert "private sentinel" not in str(error.value)


def test_draft_keeps_full_original_evidence_and_does_not_inherit_acceptance():
    records = {KEY: record()}
    preimage = copy.deepcopy(records)
    out = plan(records)
    proposal = out["proposals"][KEY]
    assert records == preimage and out["original_records"] == preimage
    assert proposal["value"] == 75 and out["counts"]["rounded"] == 1
    for field in (
        "course_id",
        "user_id",
        "assignment_id",
        "points_possible",
        "feedback",
        "context",
    ):
        assert proposal[field] == preimage[KEY][field]
    assert (
        proposal["feedback_sha256"]
        == hashlib.sha256(preimage[KEY]["feedback"].encode("utf-8")).hexdigest()
    )
    assert proposal["original_record_sha256"] == digest(preimage[KEY])
    assert proposal["context_sha256"] == digest(preimage[KEY]["context"])
    assert out["policy_sha256"] == digest(out["policy"])
    assert out["input_sha256"] == digest(preimage)
    assert proposal["source_approved_derivative_binding"] is False
    assert proposal["teacher_approval"] is False
    assert "source_qualification" not in proposal
    assert proposal["reasons"] == ["rounded_derivative_requires_source_binding"]
    assert out["canvas_writes"] == out["sheets_writes"] == 0
    assert out == plan(records)


@pytest.mark.parametrize("value", [None, "", "EX", "Excused", " ex ", 0, 75])
def test_blank_excusal_zero_and_already_whole_scores_stay_exact(value):
    source = record(value)
    out = plan({KEY: source})
    assert out["proposals"][KEY]["value"] == value
    assert out["proposals"][KEY]["feedback"] == source["feedback"]
    assert out["counts"]["unchanged"] == 1


def test_protected_source_qualified_target_is_never_rounded_or_requalified():
    source = record()
    out = plan({KEY: source}, protected_targets={KEY})
    proposal = out["proposals"][KEY]
    assert proposal["value"] == source["value"] and proposal["state"] == "held"
    assert proposal["reasons"] == ["source_qualified_owner_rounding_required"]
    assert (
        out["original_records"][KEY]["source_qualification"]
        == source["source_qualification"]
    )


@pytest.mark.parametrize(
    "change,reason",
    [
        ("authority", "score_authority_not_established"),
        ("non_points", "non_points_assignment_requires_review"),
        ("over_maximum", "invalid_score_or_maximum"),
    ],
)
def test_unverified_authority_or_invalid_grading_does_not_produce_rounded_score(
    change, reason
):
    source = record()
    args = {}
    if change == "authority":
        args["eligible_targets"] = set()
    elif change == "non_points":
        source["grading_type"] = "letter_grade"
    else:
        source["value"] = 100.5
    out = plan({KEY: source}, **args)
    assert out["proposals"][KEY]["value"] == source["value"]
    assert out["proposals"][KEY]["reasons"] == [reason]
    assert out["counts"]["held"] == 1


def test_scope_is_explicit_and_unselected_assignment_never_changes():
    source = record()
    out = plan({KEY: source}, assignment_scope={"12": {"22"}})
    assert out["proposals"][KEY]["value"] == 74.5
    assert out["counts"]["out_of_scope"] == 1
    assert out["proposals"][KEY]["rounding"] is None


@pytest.mark.parametrize(
    "change", ["identity", "key", "feedback", "context", "scope", "eligible", "policy"]
)
def test_ambiguous_mapping_or_missing_paired_evidence_rejects_plan_privately(change):
    source = record()
    records = {KEY: source}
    args = {}
    if change == "identity":
        source["user_id"] = "private sentinel"
    elif change == "key":
        records = {"private sentinel": source}
    elif change == "feedback":
        del source["feedback"]
    elif change == "context":
        source["context"] = []
    elif change == "scope":
        args["assignment_scope"] = {}
    elif change == "eligible":
        args["eligible_targets"] = {"private sentinel"}
    else:
        args["policy_ref"] = ""
    with pytest.raises(GradebookError) as error:
        plan(records, **args)
    assert "private sentinel" not in str(error.value)


def test_rounding_cannot_clear_the_canonical_decrease_guard(snapshot):
    baseline = copy.deepcopy(snapshot)
    baseline["cells"]["101:21"].update(value=69.2, grade="69.2")
    baseline["assignments"][0]["points_possible"] = 100
    out = plan({KEY: record(69.4)})
    review = compare_edits(
        baseline,
        baseline,
        {
            "course_id": "12",
            "snapshot_id": digest(baseline),
            "edits": [
                {
                    "user_id": "101",
                    "assignment_id": "21",
                    "value": out["proposals"][KEY]["value"],
                }
            ],
        },
    )
    assert review["counts"] == {"review_required": 1}
    assert review["changes"][0]["reasons"] == ["decreases_grade"]
    assert review["canvas_writes"] == 0
    assert json.loads(json.dumps(out)) == out


def test_canonical_paper_placeholder_needs_visibility_not_a_fabricated_online_attempt():
    context = {
        "assignment": {
            "published": True,
            "grading_type": "points",
            "points_possible": 100,
            "submission_types": ["on_paper"],
            "moderated_grading": False,
            "anonymous_grading": False,
            "group_category_id": None,
            "has_sub_assignments": False,
            "use_rubric_for_grading": False,
        },
        "submission": submission_cell(
            {
                "score": None,
                "workflow_state": "unsubmitted",
                "attempt": None,
                "submitted_at": None,
                "assignment_visible": True,
            }
        ),
        "closed_period": False,
    }
    before = copy.deepcopy(context)
    require_simple_target(context, 75)
    assert context == before
    context["submission"]["visible"] = None
    with pytest.raises(GradebookError, match="visibility"):
        require_simple_target(context, 75)


def test_absent_paper_endpoint_evidence_cannot_be_manufactured_by_rounding(snapshot):
    baseline = copy.deepcopy(snapshot)
    baseline["cells"] = {}
    review = compare_edits(
        baseline,
        baseline,
        {
            "course_id": "12",
            "snapshot_id": digest(baseline),
            "edits": [{"user_id": "101", "assignment_id": "21", "value": 15}],
        },
    )
    assert review["counts"] == {"review_required": 1}
    assert review["changes"][0]["reasons"] == ["submission_not_verified"]
    assert review["canvas_writes"] == 0
