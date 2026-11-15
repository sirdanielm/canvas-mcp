"""Unapproved-only stale-zero comparison, usable only through the primary owner.

No clients, writer, publisher, teacher decision, or authority are supplied here.
Application owners must independently revalidate real source, current protected
population, target, native preimage and permissions at every use. The original
baseline, current Canvas cell, raw preimage and false grade flag are never changed.
"""

from __future__ import annotations

import copy
import math
import re
from collections.abc import Callable
from datetime import datetime
from typing import Any

from canvas_mcp.gradebook import native
from canvas_mcp.gradebook.canvas_primary_protection import assert_target_unprotected
from canvas_mcp.gradebook.canvas_primary_review import _assignment, _verified
from canvas_mcp.gradebook.client import GradebookError
from canvas_mcp.gradebook.model import digest
from canvas_mcp.gradebook.proposal_preview import _edpuzzle
from canvas_mcp.gradebook.teacher_edit_transfer import _location

CONTRACT = "CANVAS_PRIMARY_STALE_ZERO_ATTEMPT_REVIEW_V1"
_ALLOWED_CHANGED = {
    "attempt",
    "grade",
    "grade_matches_current_submission",
    "graded_at",
    "late",
    "points_deducted",
    "posted_at",
    "submitted_at",
    "value",
    "workflow_state",
}
_REQUIRED = {
    "attempt",
    "workflow_state",
    "submitted_at",
    "graded_at",
    "posted_at",
    "value",
    "grade",
    "visible",
    "excused",
    "grade_matches_current_submission",
    "points_deducted",
    "late_policy_status",
    "late",
    "missing",
}


def _need(ok: bool, code: str) -> None:
    if not ok:
        raise GradebookError(code)


def _time(value: Any) -> datetime:
    _need(type(value) is str and bool(value.strip()), "STALE_ZERO_TIME_HELD")
    try:
        v = datetime.fromisoformat(value.replace("Z", "+00:00"))
        _need(
            v.tzinfo is not None and v.utcoffset() is not None, "STALE_ZERO_TIME_HELD"
        )
        return v
    except (ValueError, OverflowError) as exc:
        raise GradebookError("STALE_ZERO_TIME_HELD") from exc


def _zero_number(value: Any) -> bool:
    return type(value) in (int, float) and value == 0


def _zero_grade(value: Any) -> bool:
    return value == "0" or _zero_number(value)


def _edit_preimage(
    raw: dict[str, Any],
    binding: dict[str, Any],
    record: dict[str, Any],
    old: dict[str, Any],
) -> dict[str, Any]:
    """Bind actual literal EDIT value to the ORIGINAL baseline, not a projection."""
    state = native._state(raw)
    _need(
        state["spreadsheetId"] == binding["spreadsheet_id"],
        "STALE_ZERO_EDIT_SCOPE_HELD",
    )
    sheet = state["sheets"][binding["sheets"]["Working"]]
    row, col = _location(sheet["cells"], record)
    cell = sheet["cells"].get(f"{row}:{col}", {})
    entered = cell.get("userEnteredValue", {})
    old_blank = old.get("value") is None
    _need(
        type(entered) is dict
        and (
            not entered
            if old_blank
            else set(entered) == {"numberValue"}
            and _zero_number(entered["numberValue"])
            and _zero_number(old.get("value"))
        ),
        "STALE_ZERO_EDIT_PRESERVATION_HELD",
    )
    return {
        "sheet_id": binding["sheets"]["Working"],
        "row": row,
        "column": col,
        "cell_sha256": digest(cell),
        "original_value_sha256": digest(old.get("value")),
    }


def make_binding(
    *,
    evidence: dict[str, Any],
    record: dict[str, Any],
    proposal: dict[str, Any],
    assignment_binding: dict[str, Any],
    binding: dict[str, Any],
    raw: dict[str, Any],
    baseline: dict[str, Any],
    current: dict[str, Any],
    pin_binding: dict[str, Any],
    protection_registry: dict[str, Any],
) -> dict[str, Any]:
    """Produce pins only; this is not evidence, review, or authorization."""
    key = record["user_id"] + ":" + record["assignment_id"]
    old = baseline["cells"].get(key)
    _need(type(old) is dict, "STALE_ZERO_CONTEXT_HELD")
    edit = _edit_preimage(raw, binding, record, old)
    return {
        "contract": CONTRACT,
        "scope": "UNAPPROVED_EDIT_ONLY",
        "origin": current["origin"],
        "course_id": record["course_id"],
        "assignment_id": record["assignment_id"],
        "user_id": record["user_id"],
        "pin": record["pin"],
        "attempt": record["canvas_attempt"],
        "baseline_sha256": digest(baseline),
        "baseline_cell_sha256": digest(old),
        "current_cell_sha256": digest(current["cells"].get(key)),
        "native_raw_sha256": digest(raw),
        "native_edit_preimage": edit,
        "pin_binding_sha256": digest(pin_binding),
        "protection_registry_sha256": digest(protection_registry),
        "assignment_binding_sha256": digest(assignment_binding),
        "workbook_binding_sha256": digest(binding),
        "record_sha256": digest(record),
        "proposal_sha256": digest(proposal),
        "source_sha256": evidence["canvas_source_sha256"],
        "review_sha256": evidence["review_sha256"],
        "policy_sha256": evidence["policy_sha256"],
        "publication_allowed": False,
    }


def prepare_comparison(
    *,
    evidence: dict[str, Any],
    record: dict[str, Any],
    proposal: dict[str, Any],
    assignment_binding: dict[str, Any],
    binding: dict[str, Any],
    raw: dict[str, Any],
    baseline: dict[str, Any],
    current: dict[str, Any],
    pin_binding: dict[str, Any],
    protection_registry: dict[str, Any],
    source_authority: Callable[..., Any],
    protection_authority: Callable[..., Any],
) -> dict[str, Any]:
    """Project one exact stale-zero target for comparison only; return no plan."""
    _need(
        type(evidence) is dict and type(record) is dict and type(proposal) is dict,
        "STALE_ZERO_INPUT_HELD",
    )
    _need(
        evidence.get("contract") == "CANVAS_PRIMARY_VISUAL_ADVISORY_V1"
        and evidence.get("state") == "REVIEWED_ADVISORY"
        and evidence.get("teacher_accepted") is False
        and evidence.get("publication_allowed") is False
        and evidence.get("holds") == []
        and evidence.get("source_lane") == "CANVAS_CURRENT_UPLOAD_VISUAL_OCR"
        and evidence.get("policy") == "ASSIGNED_QUESTION_HALF_FULL_PARTICIPATION"
        and evidence.get("ocr_state") == "ALL_SOURCE_FILES_VALIDATED"
        and evidence.get("correct_assignment") is True
        and evidence.get("submission_type") == "online_upload",
        "STALE_ZERO_REVIEW_HELD",
    )
    _need(
        evidence.get("first_submission_review") is None,
        "STALE_ZERO_REVIEW_VARIANT_HELD",
    )
    _assignment(assignment_binding, evidence)
    required = evidence.get("required")
    attempted = evidence.get("attempted_lower_bound")
    _need(
        type(required) is int
        and required > 0
        and type(attempted) is int
        and 0 <= attempted <= required
        and 2 * attempted >= required,
        "STALE_ZERO_REVIEW_HELD",
    )
    _need(
        all(
            type(record.get(k)) is str
            and record[k].isdigit()
            and int(record[k]) > 0
            and evidence.get(k) == record[k]
            for k in ("course_id", "assignment_id", "user_id")
        )
        and type(record.get("pin")) is str
        and re.fullmatch(r"[0-9]{4}", record["pin"]) is not None
        and evidence.get("pin") == record["pin"]
        and pin_binding.get("by_pin", {}).get(record["pin"]) == record["user_id"],
        "STALE_ZERO_IDENTITY_HELD",
    )
    _need(
        (baseline.get("origin"), baseline.get("course_id"))
        == (current.get("origin"), record["course_id"])
        and current.get("course_id") == record["course_id"]
        and raw.get("spreadsheetId") == binding.get("spreadsheet_id")
        and str(binding.get("course_id")) == record["course_id"]
        and assignment_binding.get("course_id") == record["course_id"]
        and assignment_binding.get("assignment_id") == record["assignment_id"]
        and digest(assignment_binding.get("assignment_metadata"))
        == evidence.get("assignment_sha256")
        and assignment_binding.get("assignment_metadata_sha256")
        == evidence.get("assignment_sha256"),
        "STALE_ZERO_SCOPE_HELD",
    )
    meta = assignment_binding.get("assignment_metadata")
    _need(
        type(meta) is dict
        and assignment_binding.get("excluded") is False
        and not _edpuzzle({}, assignment_binding)
        and str(meta.get("id")) == record["assignment_id"]
        and str(meta.get("course_id")) == record["course_id"]
        and meta.get("published") is True
        and meta.get("grading_type") == "points"
        and meta.get("points_possible") == proposal.get("points_possible")
        and "edpuzzle"
        not in (
            str(meta.get("name", "")) + " " + str(meta.get("description", ""))
        ).casefold(),
        "STALE_ZERO_ASSIGNMENT_HELD",
    )
    _need(
        digest(record) == evidence.get("record_sha256")
        and digest(proposal) == evidence.get("proposal_sha256")
        and record.get("policy")
        == proposal.get("policy")
        == evidence.get("policy_sha256")
        and proposal.get("approval_state") == "UNAPPROVED"
        and proposal.get("academic_accepted") is False
        and proposal.get("score_units") == "CANVAS_POINTS"
        and record.get("source_lane")
        == proposal.get("source_lane")
        == "SDMGRASS_FORMATIVE"
        and record.get("delivery_policy")
        == proposal.get("delivery_policy")
        == "SCORE_ONLY"
        and type(proposal.get("total_score")) in (int, float)
        and math.isfinite(proposal["total_score"])
        and proposal["total_score"] > 0
        and proposal["total_score"]
        == proposal.get("points_possible")
        == record.get("proposed_score")
        and type(proposal.get("feedback")) is str
        and bool(proposal["feedback"].strip()),
        "STALE_ZERO_SELECTION_HELD",
    )
    _need(
        type(record.get("raw_score")) is int
        and record["raw_score"] == attempted
        and type(record.get("raw_maximum")) is int
        and record["raw_maximum"] == required
        and type(record.get("canvas_attempt")) is int
        and record["canvas_attempt"] in (1, 2)
        and evidence.get("canvas_attempt") == record["canvas_attempt"],
        "STALE_ZERO_SELECTION_HELD",
    )
    target = {k: record[k] for k in ("course_id", "user_id", "assignment_id")}
    key = record["user_id"] + ":" + record["assignment_id"]
    old = baseline.get("cells", {}).get(key)
    cell = current.get("cells", {}).get(key)
    _need(
        type(old) is dict
        and type(cell) is dict
        and _REQUIRED <= set(old)
        and _REQUIRED <= set(cell),
        "STALE_ZERO_CONTEXT_HELD",
    )
    _need(
        old["attempt"] is None
        and old["submitted_at"] is None
        and old["grade_matches_current_submission"] is True
        and type(cell["attempt"]) is int
        and cell["attempt"] == record["canvas_attempt"]
        and cell["workflow_state"] == "submitted"
        and cell["grade_matches_current_submission"] is False
        and _zero_number(cell["value"])
        and _zero_grade(cell["grade"]),
        "STALE_ZERO_ATTEMPT_HELD",
    )
    _need(
        all(
            x["visible"] is True
            and x["excused"] is False
            and (x["points_deducted"] is None or _zero_number(x["points_deducted"]))
            for x in (old, cell)
        ),
        "STALE_ZERO_ELIGIBILITY_HELD",
    )
    _need(
        old.get("late_policy_status") is None
        and cell.get("late_policy_status") is None
        and type(old.get("late")) is bool
        and type(cell.get("late")) is bool
        and old.get("missing") is False
        and cell.get("missing") is False,
        "STALE_ZERO_LATE_POLICY_HELD",
    )
    _need(
        _time(cell["graded_at"]) < _time(cell["submitted_at"])
        and _time(cell["posted_at"]) < _time(cell["submitted_at"]),
        "STALE_ZERO_TIME_HELD",
    )
    old_blank = (
        old["value"] is None
        and old["grade"] is None
        and old["graded_at"] is None
        and old["posted_at"] is None
        and old["workflow_state"] == "unsubmitted"
    )
    old_zero = (
        _zero_number(old["value"])
        and _zero_grade(old["grade"])
        and old["workflow_state"] == "graded"
        and old["value"] == cell["value"]
        and old["grade"] == cell["grade"]
        and old["graded_at"] == cell["graded_at"]
        and old["posted_at"] == cell["posted_at"]
    )
    _need(old_blank or old_zero, "STALE_ZERO_PRIOR_HELD")
    changed = {
        k
        for k in set(old) | set(cell)
        if k not in old or k not in cell or old[k] != cell[k]
    }
    _need(
        {
            "attempt",
            "workflow_state",
            "submitted_at",
            "grade_matches_current_submission",
        }
        <= changed
        <= _ALLOWED_CHANGED,
        "STALE_ZERO_CHANGED_FIELDS_HELD",
    )
    _need(
        evidence.get("current_cell_sha256") == digest(cell)
        and evidence.get("current_attempt_review")
        == make_binding(
            evidence=evidence,
            record=record,
            proposal=proposal,
            assignment_binding=assignment_binding,
            binding=binding,
            raw=raw,
            baseline=baseline,
            current=current,
            pin_binding=pin_binding,
            protection_registry=protection_registry,
        ),
        "STALE_ZERO_REVIEW_BINDING_HELD",
    )
    # Neither user-provided hashes nor this projection are authority. Both
    # callbacks belong to trusted app owners and must revalidate synchronously.
    _verified(evidence, source_authority)
    assert_target_unprotected(protection_registry, target, cell, protection_authority)
    _need(
        all(
            x["user_id"] != target["user_id"]
            for x in protection_registry["protected_students"]
        ),
        "STALE_ZERO_SWEEP_PROTECTED_STUDENT_HELD",
    )
    projected = copy.deepcopy(baseline)
    projected["cells"][key] = copy.deepcopy(cell)
    return {
        "comparison_baseline": projected,
        "original_baseline_sha256": digest(baseline),
        "native_edit_preimage": _edit_preimage(raw, binding, record, old),
        "publication_allowed": False,
    }
