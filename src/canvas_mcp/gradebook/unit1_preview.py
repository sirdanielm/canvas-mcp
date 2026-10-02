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


ROSTER_BINDING_FIELDS = (
    "target_mode",
    "attribution_revision",
    "attribution_sha256",
    "assignment_metadata_sha256",
    "observed_canvas_state_sha256",
)
ROSTER_STATE_FIELDS = ("attempt", "submitted_at", "workflow_state")


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


def _raw_roster_state(raw: Any, uid: str, aid: str) -> dict[str, Any]:
    """Check original GET presence before normalization can fill missing nulls."""
    _need(
        isinstance(raw, dict)
        and str(raw.get("user_id")) == uid
        and str(raw.get("assignment_id")) == aid
        and all(field in raw for field in ROSTER_STATE_FIELDS),
        "RAW_CANVAS_STATE_INVALID",
    )
    attempt, submitted, workflow = (raw[field] for field in ROSTER_STATE_FIELDS)
    _need(
        (attempt is None or (type(attempt) is int and attempt >= 0))
        and (
            submitted is None
            or (
                isinstance(submitted, str)
                and 0 < len(submitted) <= 128
                and submitted.isascii()
            )
        )
        and workflow in ("unsubmitted", "submitted", "graded", "pending_review"),
        "RAW_CANVAS_STATE_INVALID",
    )
    return {field: raw[field] for field in ROSTER_STATE_FIELDS}


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
    raw_canvas_observations: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return a private disabled preview, never a Publisher review/edit envelope.

    V1 retains attempt-bound admission. V2 explicitly binds paper work through
    an independent roster/assignment and observed state, including a null attempt.
    Neither a digest nor attribution provenance authenticates human acceptance.
    Permission claims never establish permission to execute a write.
    """
    _need(
        isinstance(pair, dict)
        and type(pair.get("schema_version")) is int
        and (pair.get("kind"), pair["schema_version"])
        in (
            ("grass_unit1_accepted_pair_v1", 1),
            ("grass_unit1_accepted_pair_v2", 2),
        ),
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
    roster_mode = pair["schema_version"] == 2
    if roster_mode:
        _need(pair.get("target_mode") == "ROSTER_ASSIGNMENT", "TARGET_MODE_INVALID")
        _need(
            all(
                key in pair
                and key in current_binding
                and pair[key] == current_binding[key]
                for key in ROSTER_BINDING_FIELDS
            ),
            "PAIR_BINDING_CHANGED",
        )
        _need(
            isinstance(pair["attribution_revision"], str)
            and 0 < len(pair["attribution_revision"]) <= 256
            and pair["attribution_revision"].isascii()
            and pair["attribution_revision"].strip() == pair["attribution_revision"],
            "PAIR_SCOPE_INVALID",
        )
    else:
        _need(
            pair.get("target_mode", "ATTEMPT_BOUND") == "ATTEMPT_BOUND",
            "TARGET_MODE_INVALID",
        )
    for field in DIGEST_FIELDS + (
        (
            "attribution_sha256",
            "assignment_metadata_sha256",
            "observed_canvas_state_sha256",
        )
        if roster_mode
        else ()
    ):
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
        if roster_mode:
            _need(
                assignment.get("submission_types") == ["on_paper"],
                "ROSTER_ON_PAPER_REQUIRED",
            )
            _need(
                digest(assignment) == pair["assignment_metadata_sha256"],
                "ROSTER_ASSIGNMENT_METADATA_CHANGED",
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
    if not known_attempt and not roster_mode:
        reasons.append("exact_canvas_attempt_required")
    if roster_mode and not (canvas_attempt is None or known_attempt):
        reasons.append("canvas_roster_binding_changed")
    raw_states: dict[str, dict[str, Any]] = {}
    if roster_mode:
        try:
            _need(
                isinstance(raw_canvas_observations, dict)
                and set(raw_canvas_observations) == {"baseline", "current"},
                "RAW_CANVAS_STATE_INVALID",
            )
            assert raw_canvas_observations is not None
            raw_states = {
                name: _raw_roster_state(raw_canvas_observations[name], uid, aid)
                for name in ("baseline", "current")
            }
        except GradebookError:
            reasons.append("raw_canvas_state_evidence_required")
    for name, snapshot in (("baseline", baseline), ("current", current)):
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
        if roster_mode and (
            not isinstance(cell, dict)
            or not all(field in cell for field in ROSTER_STATE_FIELDS)
            or name not in raw_states
            or {field: cell[field] for field in ROSTER_STATE_FIELDS} != raw_states[name]
            or digest({field: cell[field] for field in ROSTER_STATE_FIELDS})
            != pair["observed_canvas_state_sha256"]
            or cell.get("attempt") != canvas_attempt
            or type(cell.get("attempt")) is not type(canvas_attempt)
            or cell.get("submitted_at") != canvas_submitted_at
        ):
            reasons.append("canvas_roster_binding_changed")
        if not isinstance(cell, dict) or cell.get("visible") is not True:
            reasons.append("submission_not_verified")
            continue
        if cell.get("value") == "EX" or cell.get("excused") is True:
            reasons.append("excused_target_protected")
        if (
            known_attempt
            and not roster_mode
            and (
                type(cell.get("attempt")) is not int
                or cell["attempt"] != canvas_attempt
                or cell.get("submitted_at") != canvas_submitted_at
            )
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
        "target_mode": "ROSTER_ASSIGNMENT" if roster_mode else "ATTEMPT_BOUND",
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
