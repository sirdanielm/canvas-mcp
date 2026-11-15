"""Offline intent for source-owned formative publication, never a publisher.

A trusted owner must revalidate all source, protection, approval and destination
inputs when preparing and sending through the existing Publisher/ledger. This
module cannot issue a confirmation token, send a grade or create approval.
"""

from __future__ import annotations

import copy
import inspect
from collections.abc import Callable
from typing import Any

from .canvas_primary_owner import CanvasPrimaryEditConnection
from .client import GradebookError
from .model import compare_edits, digest, grade_value
from .teacher_edit_transfer import _pins

CONTRACT = "CANVAS_PRIMARY_SCORE_PUBLICATION_INTENT_V1"


def _need(value: Any, code: str) -> None:
    if not value:
        raise GradebookError(code)


def _assert(callback: Callable[..., Any], code: str, *args: Any) -> None:
    _need(callable(callback), code)
    try:
        result = callback(*(copy.deepcopy(arg) for arg in args))
    except Exception:
        raise GradebookError(code) from None
    if inspect.iscoroutine(result):
        result.close()
    _need(result is None, code)


def _lower_or_blank(cell: dict[str, Any], score: Any) -> None:
    _need("value" in cell and "grade" in cell, "PRIMARY_LOWER_OR_BLANK_REQUIRED")
    value, grade = grade_value(cell["value"]), grade_value(cell["grade"])
    _need(
        type(score) in (int, float)
        and (value is None or type(value) in (int, float) and value < score)
        and (grade is None if value is None else grade == value),
        "PRIMARY_LOWER_OR_BLANK_REQUIRED",
    )


def prepare_publication_intent(
    *,
    connection: CanvasPrimaryEditConnection,
    stage_plan: dict[str, Any],
    expected_stage_plan_sha256: str,
    stage_receipt: dict[str, Any],
    raw: dict[str, Any],
    current: dict[str, Any],
    pin_binding: dict[str, Any],
    verify_stage_receipt: Callable[..., Any],
    verify_approval_scope: Callable[..., Any],
) -> dict[str, Any]:
    """Prepare an inert, exact-current review; no source or user approval inferred.

    The supplied callbacks are trusted application authorities, not tool or
    request arguments. The publisher must recheck them against fresh inputs.
    """
    _need(isinstance(connection, CanvasPrimaryEditConnection), "PRIMARY_OWNER_REQUIRED")
    connection.validate_plan(
        stage_plan, expected_plan_sha256=expected_stage_plan_sha256
    )
    _need(
        stage_plan.get("primary_plan", {}).get("evidence") == connection.evidence
        and stage_plan.get("assignment_bindings_sha256")
        == connection.assignment_sha256,
        "PRIMARY_PUBLICATION_SOURCE_CHANGED",
    )
    _need(
        type(stage_receipt) is dict
        and stage_receipt.get("contract") == connection.contract
        and stage_receipt.get("plan_id") == expected_stage_plan_sha256
        and stage_receipt.get("status") == "PLANNED_OUTPUT_OBSERVED"
        and stage_receipt.get("canvas_writes") == 0
        and stage_receipt.get("publication_allowed") is False,
        "PRIMARY_STAGING_RECEIPT_REQUIRED",
    )
    _assert(
        verify_stage_receipt, "PRIMARY_STAGING_RECEIPT_HELD", stage_plan, stage_receipt
    )
    observed = connection.classify(
        stage_plan, raw, expected_plan_sha256=expected_stage_plan_sha256
    )
    _need(
        observed.get("status") == "PLANNED_OUTPUT_OBSERVED",
        "PRIMARY_STAGED_PREIMAGE_CHANGED",
    )
    connection._registered()
    connection._current_student_info(raw, stage_plan["binding"])
    protection = connection._protect(current)
    connection.assignment_targets(
        course_id=current["course_id"], pin_binding=pin_binding
    )
    record = stage_plan["transfer"]["record"]
    proposal = stage_plan["transfer"]["proposal"]
    evidence = stage_plan["primary_plan"]["evidence"]
    _pins(pin_binding, record)
    _need(
        digest(pin_binding) == stage_plan["transfer"]["pin_binding_sha256"],
        "PRIMARY_PUBLICATION_PIN_CHANGED",
    )
    _need(
        record == connection.record
        and proposal == connection.proposal
        and stage_plan["primary_plan"].get("protection_registry_sha256")
        == digest(protection)
        and stage_plan["transfer"].get("status") == "PREPARED_LOCAL_EDIT_ONLY"
        and len(stage_plan["transfer"].get("requests", [])) == 1
        and stage_plan["transfer"]["requests"][0].get("updateCells", {}).get("fields")
        == "userEnteredValue",
        "PRIMARY_STAGING_BINDING_HELD",
    )
    target = {k: record[k] for k in ("course_id", "user_id", "assignment_id")}
    key = record["user_id"] + ":" + record["assignment_id"]
    cell = current.get("cells", {}).get(key)
    _need(
        current.get("course_workflow_state") == "available"
        and type(cell) is dict
        and digest(cell) == evidence["current_cell_sha256"]
        and type(cell.get("attempt")) is int
        and cell["attempt"] == record["canvas_attempt"]
        and cell.get("workflow_state") == "submitted"
        and cell.get("visible") is True
        and cell.get("excused") is False
        and cell.get("grade_matches_current_submission") is True
        and (
            cell.get("points_deducted") is None
            or type(cell.get("points_deducted")) in (int, float)
            and cell["points_deducted"] == 0
        ),
        "PRIMARY_PUBLICATION_CURRENT_HELD",
    )
    assignments = [
        a
        for a in current.get("assignments", [])
        if a.get("id") == record["assignment_id"]
    ]
    _need(
        len(assignments) == 1
        and assignments[0].get("assignment_metadata_sha256")
        == evidence["assignment_sha256"]
        and digest(assignments[0].get("assignment_metadata"))
        == evidence["assignment_sha256"],
        "PRIMARY_PUBLICATION_ASSIGNMENT_CHANGED",
    )
    score = proposal.get("total_score")
    _lower_or_blank(cell, score)
    original_baseline = stage_plan["transfer"]["baseline"]
    first = evidence.get("first_submission_review")
    if first is not None:
        _need(
            type(first) is dict
            and first.get("baseline_sha256") == digest(original_baseline),
            "PRIMARY_ORIGINAL_BASELINE_CHANGED",
        )
    operation_baseline = copy.deepcopy(current)
    baseline_id = digest(operation_baseline)
    review = compare_edits(
        operation_baseline,
        current,
        {
            "course_id": record["course_id"],
            "snapshot_id": baseline_id,
            "edits": [
                {
                    "user_id": record["user_id"],
                    "assignment_id": record["assignment_id"],
                    "value": score,
                }
            ],
        },
    )
    _need(
        len(review["changes"]) == 1
        and review["changes"][0]["status"] == "ready_for_review"
        and not review["changes"][0]["reasons"],
        "PRIMARY_PUBLICATION_COMPARISON_HELD",
    )
    intent = {
        "contract": CONTRACT,
        "target": target,
        "score": score,
        "score_only": True,
        "stage_plan_sha256": expected_stage_plan_sha256,
        "stage_receipt_sha256": digest(stage_receipt),
        "original_sync_baseline_sha256": digest(original_baseline),
        "first_submission_review_sha256": digest(first) if first is not None else None,
        "operation_current_baseline_sha256": baseline_id,
        "source_evidence_sha256": digest(evidence),
        "protection_registry_sha256": digest(protection),
        "review_sha256": digest(review),
        "approval_scope": "LOWER_OR_BLANK_ONLY",
        "user_approval_created": False,
        "canvas_writes": 0,
        "publication_allowed": False,
    }
    _assert(verify_approval_scope, "PRIMARY_PUBLICATION_APPROVAL_HELD", intent)
    return {
        "contract": CONTRACT,
        "intent": intent,
        "operation_current_baseline": operation_baseline,
        "review": review,
        "canvas_writes": 0,
        "publication_allowed": False,
    }
