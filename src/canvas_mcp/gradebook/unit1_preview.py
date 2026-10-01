"""Offline Unit 1 pair projection. No authentication, transport or release port.

Expected hashes/bindings come from independently retained owner records, never
from the pending envelope. They establish comparison integrity, not human consent.
"""

from __future__ import annotations

import copy
import re
from decimal import Decimal, InvalidOperation
from fractions import Fraction
from pathlib import Path
from typing import Any

from .client import GradebookError
from .model import compare_edits, digest, grade_value, identifier
from .publish import require_simple_target
from .store import Store

PERCENT_SCALE = "grass_exam_raw_to_canvas100_v1"
REVISION_FIELDS = (
    "decision_id",
    "source_revision",
    "result_revision",
    "policy_revision",
    "identity_revision",
    "binding_revision",
)
DIGEST_FIELDS = (
    "source_sha256",
    "result_sha256",
    "policy_sha256",
    "identity_sha256",
    "binding_sha256",
    "form_sha256",
)
BINDING_FIELDS = (
    REVISION_FIELDS
    + DIGEST_FIELDS
    + (
        "case_key",
        "academic_assignment_id",
        "origin",
        "course_id",
        "canvas_assignment_id",
        "canvas_user_id",
        "pin",
        "section_id",
        "form_id",
        "paper_attempt",
        "raw_maximum",
        "canvas_maximum",
        "scale_contract",
        "rounding",
    )
)


def _need(condition: bool, code: str) -> None:
    if not condition:
        raise GradebookError(code)


def _decimal(value: Any) -> Decimal:
    _need(isinstance(value, str) and len(value) <= 64, "DECIMAL_STRING_REQUIRED")
    _need(
        bool(re.fullmatch(r"(?:0|[1-9][0-9]*)(?:\.[0-9]+)?", value)),
        "DECIMAL_STRING_REQUIRED",
    )
    try:
        amount = Decimal(value)
    except InvalidOperation:
        raise GradebookError("DECIMAL_STRING_REQUIRED") from None
    _need(amount.is_finite(), "DECIMAL_STRING_REQUIRED")
    return amount


def project_raw_score(pair: dict[str, Any]) -> str:
    """Conformance to the bound native scale; no attempt/mastery policy inference."""
    amount, maximum = _decimal(pair.get("raw_score")), _decimal(pair.get("raw_maximum"))
    canvas_maximum = _decimal(pair.get("canvas_maximum"))
    _need(maximum > 0 and 0 <= amount <= maximum, "RAW_SCORE_OUT_OF_RANGE")
    form = pair.get("form_id", "")
    form_maxima = {
        **{name: Decimal(32) for name in ("CT-A", "CT-B")},
        **{name: Decimal(40) for name in ("C-A", "C-B", "C-C", "C-D")},
        **{name: Decimal(48) for name in ("AD-A", "AD-B", "AD-C", "AD-D")},
    }
    _need(
        isinstance(form, str) and form in form_maxima and maximum == form_maxima[form],
        "PRINTED_FORM_MAXIMUM_MISMATCH",
    )
    if pair.get("scale_contract") == "RAW_IDENTITY":
        _need(
            canvas_maximum == maximum and pair.get("rounding") == "NONE",
            "EXPLICIT_SCORE_SCALE_REQUIRED",
        )
        return format(amount, "f")
    _need(
        pair.get("scale_contract") == PERCENT_SCALE
        and canvas_maximum == 100
        and pair.get("rounding") == "NEAREST_WHOLE_POINT",
        "EXPLICIT_SCORE_SCALE_REQUIRED",
    )
    scaled = Fraction(amount) * 100 / Fraction(maximum)
    whole, remainder = divmod(scaled.numerator, scaled.denominator)
    return str(whole + int(2 * remainder >= scaled.denominator))


def build_pair_preview(
    pair: dict[str, Any],
    *,
    expected_pair_sha256: str,
    current_binding: dict[str, Any],
    baseline: dict[str, Any],
    current: dict[str, Any],
    canvas_attempt: int | None,
    canvas_submitted_at: str | None,
    teacher_final: bool | None,
    score_permission: bool,
    feedback_permission: bool,
    target_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return a private disabled preview, never a Publisher review/edit envelope.

    Paper review has no Canvas-attempt precondition. This projection holds the
    publication side when exact attempt linkage is unknown. Permission claims do
    not authenticate acceptance or establish permission to execute a write.
    """
    _need(
        isinstance(pair, dict)
        and pair.get("kind") == "grass_unit1_accepted_pair_v1"
        and type(pair.get("schema_version")) is int
        and pair["schema_version"] == 1,
        "PAIR_SCHEMA_INVALID",
    )
    _need(
        isinstance(expected_pair_sha256, str)
        and bool(re.fullmatch(r"[a-f0-9]{64}", expected_pair_sha256))
        and digest(pair) == expected_pair_sha256,
        "PAIR_INTEGRITY_MISMATCH",
    )
    _need(
        isinstance(current_binding, dict)
        and all(
            key in pair and key in current_binding and pair[key] == current_binding[key]
            for key in BINDING_FIELDS
        ),
        "PAIR_BINDING_CHANGED",
    )
    for field in DIGEST_FIELDS:
        _need(
            isinstance(pair[field], str)
            and bool(re.fullmatch(r"[a-f0-9]{64}", pair[field])),
            "PAIR_REVISION_INVALID",
        )
    for field in REVISION_FIELDS + (
        "case_key",
        "academic_assignment_id",
        "section_id",
        "form_id",
        "paper_attempt",
    ):
        _need(
            isinstance(pair[field], str)
            and 0 < len(pair[field]) <= 256
            and pair[field].isascii()
            and pair[field].strip() == pair[field],
            "PAIR_SCOPE_INVALID",
        )
    _need(
        isinstance(pair["pin"], str) and bool(re.fullmatch(r"[0-9]{4}", pair["pin"])),
        "TEXT_PIN_REQUIRED",
    )
    for field in ("course_id", "canvas_assignment_id", "canvas_user_id"):
        _need(
            isinstance(pair[field], str) and identifier(pair[field]) == pair[field],
            "PAIR_TARGET_INVALID",
        )
    _need(pair.get("score_units") == "CANVAS_POINTS", "TEACHER_SCORE_UNITS_REQUIRED")
    feedback = pair.get("feedback")
    _need(
        isinstance(feedback, str)
        and bool(feedback.strip())
        and len(feedback) <= 6000
        and "\r" not in feedback,
        "EXACT_NORMALIZED_FEEDBACK_REQUIRED",
    )
    projected = project_raw_score(pair)
    _need(
        pair.get("canonical_projected_score") == projected,
        "CANONICAL_PROJECTION_MISMATCH",
    )
    score, maximum = _decimal(pair.get("score")), _decimal(pair["canvas_maximum"])
    _need(0 <= score <= maximum, "TEACHER_SCORE_OUT_OF_RANGE")
    _need(
        type(score_permission) is bool
        and type(feedback_permission) is bool
        and (teacher_final is None or type(teacher_final) is bool),
        "PROTECTION_STATE_INVALID",
    )
    target = (pair["origin"], pair["course_id"])
    _need(
        (baseline.get("origin"), baseline.get("course_id")) == target
        and (current.get("origin"), current.get("course_id")) == target,
        "SNAPSHOT_TARGET_MISMATCH",
    )
    uid, aid = pair["canvas_user_id"], pair["canvas_assignment_id"]
    key = uid + ":" + aid
    reasons: list[str] = []
    if current.get("course_workflow_state") != "available":
        reasons.append("course_not_available")
    if teacher_final is not False:
        reasons.append(
            "teacher_final_protected"
            if teacher_final is True
            else "teacher_final_state_unknown"
        )
    if not score_permission:
        reasons.append("score_permission_required")
    if target_context is None:
        reasons.append("exact_assignment_context_required")
    else:
        assignment = target_context.get("assignment", {})
        _need(
            isinstance(assignment, dict)
            and str(assignment.get("id")) == aid
            and str(assignment.get("course_id")) == pair["course_id"],
            "EXACT_ASSIGNMENT_TARGET_MISMATCH",
        )
        if target_context.get("submission") != current.get("cells", {}).get(key):
            reasons.append("exact_assignment_snapshot_conflict")
        if assignment.get("points_possible") != float(maximum):
            reasons.append("assignment_score_scale_changed")
        try:
            require_simple_target(target_context, pair["score"])
        except (GradebookError, KeyError, TypeError):
            reasons.append("exact_assignment_context_held")
    known_attempt = type(canvas_attempt) is int and canvas_attempt >= 0
    if not known_attempt:
        reasons.append("exact_canvas_attempt_required")
    for snapshot in (baseline, current):
        assignments = [a for a in snapshot.get("assignments", []) if a.get("id") == aid]
        if (
            len(assignments) != 1
            or assignments[0].get("points_possible") != float(maximum)
            or assignments[0].get("grading_type") != "points"
        ):
            reasons.append("assignment_score_scale_changed")
        if uid not in {student.get("id") for student in snapshot.get("students", [])}:
            reasons.append("target_not_in_both_snapshots")
        cell = snapshot.get("cells", {}).get(key)
        if not isinstance(cell, dict) or cell.get("visible") is not True:
            reasons.append("submission_not_verified")
            continue
        if cell.get("value") == "EX" or cell.get("excused") is True:
            reasons.append("excused_target_protected")
        if known_attempt and (
            type(cell.get("attempt")) is not int
            or cell["attempt"] != canvas_attempt
            or cell.get("submitted_at") != canvas_submitted_at
        ):
            reasons.append("canvas_attempt_binding_changed")
    comparison = compare_edits(
        baseline,
        current,
        {
            "course_id": pair["course_id"],
            "snapshot_id": digest(baseline),
            "edits": [{"user_id": uid, "assignment_id": aid, "value": pair["score"]}],
        },
    )
    for change in comparison["changes"]:
        reasons.extend(change["reasons"])
    # compare_edits deliberately treats an unchanged baseline edit as a no-op.
    # Independently keep a later, higher Canvas score protected in this receipt.
    value = grade_value(current.get("cells", {}).get(key, {}).get("value"))
    if baseline.get("cells", {}).get(key) != current.get("cells", {}).get(key):
        reasons.append("canvas_changed_since_baseline")
    if (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and score < Decimal(str(value))
    ):
        reasons.append("higher_canvas_score_protected")
    reasons = sorted(set(reasons))
    score_status = (
        "HELD"
        if reasons
        else (
            "NO_SCORE_CHANGE"
            if value is not None and value != "EX" and Decimal(str(value)) == score
            else "CANDIDATE_FOR_PREVIEW"
        )
    )
    return {
        "schema_version": 1,
        "kind": "UNIT1_PAIR_OFFLINE_PREVIEW",
        "pair_sha256": expected_pair_sha256,
        "accepted_pair": copy.deepcopy(pair),
        "baseline_snapshot_id": digest(baseline),
        "current_snapshot_id": digest(current),
        "canvas_attempt": canvas_attempt,
        "canvas_submitted_at": canvas_submitted_at,
        "exact_target_context_sha256": (
            digest(target_context) if target_context else None
        ),
        "canonical_projected_score": projected,
        "score": {
            "status": score_status,
            "holds": reasons,
            "delivery": "NOT_SENT",
            "permission_claim": score_permission,
        },
        "feedback": {
            "delivery": "NOT_SENT",
            "permission_claim": feedback_permission,
            "holds": [] if feedback_permission else ["feedback_permission_required"],
        },
        "publication_ready": False,
        "verified_pair": False,
        "canvas_writes": 0,
        "release_holds": [
            "teacher_acceptance_unverified",
            "release_authentication_not_connected",
            "feedback_transport_not_connected",
            "live_freshness_not_established",
        ],
        "privacy": "PRIVATE_STUDENT_RECORD",
    }


def retain_pair_preview(store: Store, preview: dict[str, Any]) -> tuple[str, Path]:
    """Retain a disabled immutable receipt; never save it as a score review."""
    _need(
        preview.get("kind") == "UNIT1_PAIR_OFFLINE_PREVIEW"
        and preview.get("publication_ready") is False
        and preview.get("verified_pair") is False
        and preview.get("canvas_writes") == 0,
        "DISABLED_PREVIEW_REQUIRED",
    )
    return store.save("receipt", preview)
