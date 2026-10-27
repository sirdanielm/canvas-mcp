"""Prepare UNAPPROVED local EDIT score/feedback pairs, never final decisions.

The authenticated source callback and native preservation are mandatory. This
separate protocol cannot be consumed as teacher acceptance or Canvas publication.
"""

from __future__ import annotations

import re
from typing import Any

from .model import digest
from .teacher_edit_transfer import (
    HASH,
    RECORD_FIELDS,
    SourceCheck,
    _basis,
    _need,
    _number,
    _portable_state,
    _prepare_native_transfer,
    _source,
)

CONTRACT = "CENTRAL_UNAPPROVED_EDIT_TRANSFER_V1"
PROPOSAL_FIELDS = (
    "evaluation_id",
    "source_revision",
    "result_revision",
    "policy",
    "proposal_revision",
    "approval_state",
    "academic_accepted",
    "total_score",
    "points_possible",
    "score_units",
    "feedback",
)


def _selection(record: dict[str, Any], proposal: dict[str, Any]) -> None:
    _need(type(record) is dict and type(proposal) is dict, "EXACT_SELECTION_REQUIRED")
    _need(all(k in record for k in RECORD_FIELDS), "SELECTED_EVALUATION_INCOMPLETE")
    _need(set(proposal) == set(PROPOSAL_FIELDS), "UNAPPROVED_PROPOSAL_REQUIRED")
    for field in ("evaluation_id", "source_revision", "result_revision", "source_key"):
        _need(
            type(record[field]) is str and HASH.fullmatch(record[field]),
            "EXACT_EVALUATION_REVISION_REQUIRED",
        )
    _need(record["state"] == "READY_FOR_REVIEW", "SOURCE_RESULT_HELD")
    _need(
        all(
            type(record[k]) is str and record[k].strip()
            for k in ("policy", "section", "paper_attempt", "form", "score_scale")
        ),
        "EXPLICIT_POLICY_FORM_SCALE_REQUIRED",
    )
    _need(
        all(
            type(record[k]) is str and re.fullmatch(r"[1-9][0-9]*", record[k])
            for k in ("course_id", "user_id", "assignment_id")
        ),
        "EXACT_TEXT_CANVAS_TARGET_REQUIRED",
    )
    _need(
        type(record["pin"]) is str and re.fullmatch(r"[0-9]{4}", record["pin"]),
        "LITERAL_FOUR_DIGIT_PIN_REQUIRED",
    )
    _need(
        type(record["canvas_attempt"]) is int
        and record["canvas_attempt"] >= 0
        or record["canvas_attempt"] is None
        and record.get("canvas_attempt_observation") == "UNIT1_PAPER_OBSERVED_NULL"
        and record["paper_attempt"] != "CANVAS_CAPTURE"
        and record["form"] != "NOT_APPLICABLE",
        "OBSERVED_CANVAS_ATTEMPT_REQUIRED",
    )
    _need(
        all(_number(record[k]) for k in ("raw_score", "raw_maximum", "proposed_score"))
        and record["raw_maximum"] > 0
        and 0 <= record["raw_score"] <= record["raw_maximum"]
        and record["proposed_score"] >= 0,
        "RAW_AND_CONSUMER_SCORES_REQUIRED",
    )
    _need(
        all(
            proposal[k] == record[k]
            for k in ("evaluation_id", "source_revision", "result_revision", "policy")
        ),
        "PROPOSAL_REVISION_CHANGED",
    )
    _need(
        proposal["approval_state"] == "UNAPPROVED"
        and proposal["academic_accepted"] is False
        and proposal["proposal_revision"] == "proposal-" + record["result_revision"],
        "UNAPPROVED_PROPOSAL_REQUIRED",
    )
    _need(proposal["score_units"] == "CANVAS_POINTS", "EXPLICIT_CANVAS_POINTS_REQUIRED")
    _need(
        _number(proposal["total_score"])
        and _number(proposal["points_possible"])
        and proposal["points_possible"] > 0
        and 0 <= proposal["total_score"] <= proposal["points_possible"]
        and proposal["total_score"] == record["proposed_score"],
        "PROPOSAL_SCORE_OUT_OF_RANGE",
    )
    _need(
        type(proposal["feedback"]) is str
        and proposal["feedback"].strip()
        and len(proposal["feedback"]) <= 45_000,
        "EXACT_FULL_PROPOSAL_FEEDBACK_REQUIRED",
    )


def _note(prefix: str, selection_sha256: str, feedback: str) -> str:
    return (
        prefix
        + ("\n\n" if prefix else "")
        + "UNAPPROVED advisory proposal staged to local EDIT. "
        + "No teacher acceptance or Canvas publication is authorized.\n"
        + "Exact proposal selection: "
        + selection_sha256
        + "\n\n"
        + feedback
    )


def prepare_proposal_transfer(
    record: dict[str, Any], proposal: dict[str, Any], **context: Any
) -> dict[str, Any]:
    """Use shared preservation while retaining a distinct unapproved contract."""
    _selection(record, proposal)
    preservation = context.pop("preservation", None)
    return _prepare_native_transfer(
        record,
        proposal,
        **context,
        preservation=preservation,
        selection_fields=PROPOSAL_FIELDS,
        selection_key="proposal",
        note_factory=_note,
        contract=CONTRACT,
    )


def _plan(plan: dict[str, Any], expected_plan_sha256: str) -> None:
    _need(
        type(expected_plan_sha256) is str
        and HASH.fullmatch(expected_plan_sha256)
        and digest(plan) == expected_plan_sha256
        and plan.get("contract") == CONTRACT,
        "EXACT_PROPOSAL_PLAN_CHANGED",
    )
    _selection(plan["record"], plan["proposal"])
    _need(
        plan.get("score_delivery_authorized") is False
        and plan.get("comment_delivery_authorized") is False
        and plan.get("canvas_writes") == plan.get("sheets_writes") == 0,
        "PROPOSAL_IS_NOT_PUBLICATION_AUTHORITY",
    )


def revalidate_proposal_transfer(
    plan: dict[str, Any],
    *,
    expected_plan_sha256: str,
    raw: dict[str, Any],
    current: dict[str, Any],
    pin_binding: dict[str, Any],
    source_check: SourceCheck,
) -> None:
    _plan(plan, expected_plan_sha256)
    _need(digest(pin_binding) == plan["pin_binding_sha256"], "PIN_AUTHORITY_CHANGED")
    _source(source_check, plan["record"], plan["proposal"], pin_binding)
    _need(_portable_state(raw) == plan["before_state"], "TRANSFER_DESTINATION_CHANGED")
    _need(
        _basis(current, plan["record"]) == plan["current_basis"],
        "CANVAS_TARGET_CHANGED_AFTER_PREP",
    )
    fresh = prepare_proposal_transfer(
        plan["record"],
        plan["proposal"],
        raw=raw,
        binding=plan["binding"],
        baseline=plan["baseline"],
        current=current,
        pin_binding=pin_binding,
        source_check=lambda *unused: None,
        preservation=plan.get("preservation"),
    )
    _need(fresh == plan, "EXACT_PROPOSAL_PLAN_CHANGED")


def classify_proposal_readback(
    plan: dict[str, Any], raw: dict[str, Any], *, expected_plan_sha256: str
) -> dict[str, Any]:
    _plan(plan, expected_plan_sha256)
    actual = _portable_state(raw)
    status = (
        "PLANNED_OUTPUT_OBSERVED"
        if actual == plan["after_state"]
        else "BEFORE_STILL_PRESENT"
        if actual == plan["before_state"]
        else "DIVERGED"
    )
    return {
        "contract": CONTRACT,
        "status": status,
        "plan_sha256": expected_plan_sha256,
        "actual_fingerprint": digest(actual),
        "retry_writes": False,
        "canvas_writes": 0,
        "sheets_writes": 0,
        "score_delivery_verified": False,
        "comment_delivery_verified": False,
        "approval_state": "UNAPPROVED",
        "academic_accepted": False,
    }
