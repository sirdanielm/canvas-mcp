"""Pure, private rounding proposals; no source acceptance or publication authority."""

from __future__ import annotations

import copy
import hashlib
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation, localcontext
from typing import Any

from .client import GradebookError
from .model import digest, grade_value, identifier

MAX_RECORDS = 10_000
OWNER_ROUNDING_REQUIRED = (
    "source_qualified_owner_" "rounding_required"
)
DERIVATIVE_BINDING_REQUIRED = (
    "rounded_derivative_" "requires_source_binding"
)
REQUIRED = {
    "course_id",
    "user_id",
    "assignment_id",
    "value",
    "points_possible",
    "grading_type",
    "feedback",
    "context",
}


def _decimal(value: Any) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, (int, float, str, Decimal)):
        raise GradebookError("Rounding requires a finite numeric score and maximum.")
    try:
        result = Decimal(str(value))
        if not result.is_finite() or result < 0:
            raise ValueError
        exponent = result.as_tuple().exponent
        if (
            type(exponent) is not int
            or len(result.as_tuple().digits) > 100
            or abs(exponent) > 100
        ):
            raise ValueError
        return result
    except (InvalidOperation, TypeError, ValueError):
        raise GradebookError(
            "Rounding requires bounded finite nonnegative decimals."
        ) from None


def round_score_percent(value: Any, points_possible: Any) -> dict[str, Any]:
    """Nearest whole percentage, with exact Decimal half-up tie behavior."""
    score, maximum = _decimal(value), _decimal(points_possible)
    if maximum <= 0 or score > maximum:
        raise GradebookError(
            "Rounding requires a positive maximum and an in-range score."
        )
    # Bounded 100-digit inputs/exponents are evaluated with ample guard digits
    # so exact halves and neighboring finite decimals remain distinguishable.
    with localcontext() as ctx:
        ctx.prec = 512
        percent = (score * Decimal(100) / maximum).quantize(
            Decimal(1), rounding=ROUND_HALF_UP
        )
        rounded = percent * maximum / Decimal(100)
    literal: int | float = (
        int(rounded) if rounded == rounded.to_integral_value() else float(rounded)
    )
    canonical = grade_value(literal)
    if (
        not isinstance(canonical, float)
        or Decimal(format(canonical, ".15g")) != rounded
    ):
        raise GradebookError(
            "Rounded points cannot be represented by the canonical grade value."
        )
    return {
        "rounded_percent": int(percent),
        "rounded_points": literal,
        "rounded_points_decimal": format(rounded, "f"),
        "original_points_decimal": format(score, "f"),
        "maximum_decimal": format(maximum, "f"),
        "changed": rounded != score,
    }


def plan_percent_rounding(
    records: dict[str, dict[str, Any]],
    *,
    assignment_scope: dict[str, set[str]],
    eligible_targets: set[str],
    protected_targets: set[str],
    policy_ref: str,
) -> dict[str, Any]:
    """Keep original paired evidence intact and derive explicitly scoped proposals.

    Record keys are course:user:assignment Canvas IDs. The caller must supply
    exact eligible/protected sets from its own authority checks. No scope or
    eligibility is inferred. Existing qualifications describe original records;
    every changed derivative still needs an independently bound source approval.
    """
    try:
        if (
            not isinstance(records, dict)
            or not 1 <= len(records) <= MAX_RECORDS
            or not isinstance(assignment_scope, dict)
            or not assignment_scope
            or type(eligible_targets) is not set
            or type(protected_targets) is not set
            or not isinstance(policy_ref, str)
            or not policy_ref.strip()
            or len(policy_ref) > 1024
            or not eligible_targets <= set(records)
            or not protected_targets <= set(records)
        ):
            raise ValueError
        scope = {}
        for course, assignments in assignment_scope.items():
            if (
                type(course) is not str
                or identifier(course) != course
                or type(assignments) is not set
                or not assignments
                or any(
                    type(aid) is not str or identifier(aid) != aid
                    for aid in assignments
                )
            ):
                raise ValueError
            scope[course] = sorted(assignments)
        policy = {
            "schema_version": 1,
            "mode": "NEAREST_WHOLE_PERCENT",
            "rounding": "ROUND_HALF_UP",
            "step_percent": "1",
            "assignment_scope": scope,
            "policy_ref": policy_ref,
        }
        policy_sha = digest(policy)
        selection = {
            "eligible_targets": sorted(eligible_targets),
            "protected_targets": sorted(protected_targets),
        }
        originals = copy.deepcopy(records)
        input_sha = digest(originals)
        proposals = {}
        counts = {"rounded": 0, "unchanged": 0, "held": 0, "out_of_scope": 0}
        for key in sorted(originals):
            record = originals[key]
            if (
                not isinstance(record, dict)
                or not REQUIRED <= set(record)
                or any(
                    type(record[field]) is not str
                    or identifier(record[field]) != record[field]
                    for field in ("course_id", "user_id", "assignment_id")
                )
                or key
                != ":".join(
                    record[field] for field in ("course_id", "user_id", "assignment_id")
                )
                or type(record["feedback"]) is not str
                or not isinstance(record["context"], dict)
            ):
                raise ValueError
            proposal = {field: copy.deepcopy(record[field]) for field in REQUIRED}
            proposal.update(
                original_record_sha256=digest(record),
                policy_sha256=policy_sha,
                feedback_sha256=hashlib.sha256(
                    record["feedback"].encode("utf-8")
                ).hexdigest(),
                context_sha256=digest(record["context"]),
                teacher_approval=False,
                source_approved_derivative_binding=False,
            )
            reasons, rounding = [], None
            if record["assignment_id"] not in scope.get(record["course_id"], []):
                state = "out_of_scope"
            elif key in protected_targets:
                state, reasons = "held", [OWNER_ROUNDING_REQUIRED]
            elif key not in eligible_targets:
                state, reasons = "held", ["score_authority_not_established"]
            elif record["grading_type"] != "points":
                state, reasons = "held", ["non_points_assignment_requires_review"]
            elif (
                record["value"] is None
                or record["value"] == ""
                or (
                    isinstance(record["value"], str)
                    and record["value"].strip().lower() in {"ex", "excused"}
                )
            ):
                state = "unchanged"
            else:
                try:
                    rounding = round_score_percent(
                        record["value"], record["points_possible"]
                    )
                except GradebookError:
                    state, reasons = "held", ["invalid_score_or_maximum"]
                else:
                    state = "rounded" if rounding["changed"] else "unchanged"
                    if rounding["changed"]:
                        proposal["value"] = rounding["rounded_points"]
                        reasons = [DERIVATIVE_BINDING_REQUIRED]
            proposal.update(state=state, reasons=reasons, rounding=rounding)
            proposals[key] = proposal
            counts[state] += 1
        return {
            "schema_version": 1,
            "kind": "PERCENT_ROUNDING_DRAFT",
            "policy": policy,
            "policy_sha256": policy_sha,
            "authority_selection": selection,
            "authority_selection_sha256": digest(selection),
            "input_sha256": input_sha,
            "original_records": originals,
            "proposals": proposals,
            "counts": counts,
            "teacher_approval": False,
            "source_approved_derivative_binding": False,
            "canvas_writes": 0,
            "sheets_writes": 0,
        }
    except (KeyError, TypeError, ValueError, GradebookError):
        raise GradebookError(
            "Rounding plan identities, scope or private evidence are invalid."
        ) from None
