"""Prepare and verify one exact teacher decision in native EDIT, without I/O.

The domain owner authenticates the existing proposal/teacher fields through a
trusted synchronous callback. A flag, hash, M-column string or saved proposal
does not supply that authority. No tool, transport, roster, approval table or
retry ledger is registered here. Publication permissions remain independent.
"""

from __future__ import annotations

import copy
import inspect
import json
import math
import re
from collections.abc import Callable
from typing import Any

from . import native
from .client import GradebookError
from .model import compare_edits, digest, grade_value, identifier
from .native_edit_review import extract_native_edits
from .refresh import build_requests

SourceCheck = Callable[[dict[str, Any], dict[str, Any], dict[str, Any]], Any]
CONTRACT = "CENTRAL_TEACHER_EDIT_TRANSFER_V1"
HASH = re.compile(r"[a-f0-9]{64}")
RECORD_FIELDS = (
    "evaluation_id",
    "source_revision",
    "result_revision",
    "source_key",
    "state",
    "policy",
    "section",
    "pin",
    "course_id",
    "user_id",
    "assignment_id",
    "paper_attempt",
    "form",
    "canvas_attempt",
    "raw_score",
    "raw_maximum",
    "proposed_score",
    "score_scale",
)
DECISION_FIELDS = (
    "evaluation_id",
    "source_revision",
    "result_revision",
    "policy",
    "decision_revision",
    "is_final",
    "total_score",
    "points_possible",
    "score_units",
    "feedback",
)


def _need(condition: Any, code: str) -> None:
    if not condition:
        raise GradebookError(code)


def _portable_state(raw: dict[str, Any]) -> dict[str, Any]:
    """Use JSON object keys before hashing/persisting native sheet inventories."""
    return json.loads(json.dumps(native._state(raw), allow_nan=False))  # type: ignore[no-any-return]


def _number(value: Any) -> bool:
    return type(value) in (int, float) and math.isfinite(value)


def _selection(record: dict[str, Any], decision: dict[str, Any]) -> None:
    _need(type(record) is dict and type(decision) is dict, "EXACT_SELECTION_REQUIRED")
    _need(
        all(field in record for field in RECORD_FIELDS),
        "SELECTED_EVALUATION_INCOMPLETE",
    )
    _need(
        all(field in decision for field in DECISION_FIELDS),
        "TEACHER_DECISION_INCOMPLETE",
    )
    for field in ("evaluation_id", "source_revision", "result_revision", "source_key"):
        _need(
            type(record[field]) is str and HASH.fullmatch(record[field]),
            "EXACT_EVALUATION_REVISION_REQUIRED",
        )
    _need(record["state"] == "READY_FOR_REVIEW", "SOURCE_RESULT_HELD")
    _need(
        all(
            type(record[field]) is str and record[field].strip()
            for field in ("policy", "section", "paper_attempt", "form", "score_scale")
        ),
        "EXPLICIT_POLICY_FORM_SCALE_REQUIRED",
    )
    for field in ("course_id", "user_id", "assignment_id"):
        _need(
            type(record[field]) is str and identifier(record[field]) == record[field],
            "EXACT_TEXT_CANVAS_TARGET_REQUIRED",
        )
    _need(
        type(record["pin"]) is str and re.fullmatch(r"[0-9]{4}", record["pin"]),
        "LITERAL_FOUR_DIGIT_PIN_REQUIRED",
    )
    _need(
        type(record["canvas_attempt"]) is int and record["canvas_attempt"] >= 0,
        "OBSERVED_CANVAS_ATTEMPT_REQUIRED",
    )
    _need(
        all(
            _number(record[field])
            for field in ("raw_score", "raw_maximum", "proposed_score")
        )
        and record["raw_maximum"] > 0
        and 0 <= record["raw_score"] <= record["raw_maximum"]
        and record["proposed_score"] >= 0,
        "RAW_AND_CONSUMER_SCORES_REQUIRED",
    )
    _need(
        all(
            decision[field] == record[field]
            for field in (
                "evaluation_id",
                "source_revision",
                "result_revision",
                "policy",
            )
        ),
        "TEACHER_DECISION_REVISION_CHANGED",
    )
    _need(decision["is_final"] is True, "FINAL_TEACHER_DECISION_REQUIRED")
    _need(
        type(decision["decision_revision"]) is str
        and decision["decision_revision"].strip(),
        "TEACHER_DECISION_REVISION_REQUIRED",
    )
    _need(decision["score_units"] == "CANVAS_POINTS", "EXPLICIT_CANVAS_POINTS_REQUIRED")
    _need(
        _number(decision["total_score"])
        and _number(decision["points_possible"])
        and decision["points_possible"] > 0
        and 0 <= decision["total_score"] <= decision["points_possible"],
        "TEACHER_FINAL_SCORE_OUT_OF_RANGE",
    )
    _need(
        type(decision["feedback"]) is str
        and decision["feedback"].strip()
        and len(decision["feedback"]) <= 45_000,
        "EXACT_FULL_TEACHER_FEEDBACK_REQUIRED",
    )


def _pins(pin_binding: dict[str, Any], record: dict[str, Any]) -> None:
    _need(
        type(pin_binding) is dict
        and all(
            type(pin_binding.get(field)) is str and HASH.fullmatch(pin_binding[field])
            for field in ("registry_sha256", "roster_sha256")
        ),
        "CANONICAL_PIN_BINDING_REQUIRED",
    )
    by_pin = pin_binding.get("by_pin")
    if not isinstance(by_pin, dict):
        raise GradebookError("CANONICAL_PIN_BINDING_REQUIRED")
    _need(
        type(by_pin) is dict
        and by_pin
        and all(
            type(pin) is str
            and re.fullmatch(r"[0-9]{4}", pin)
            and type(uid) is str
            and identifier(uid) == uid
            for pin, uid in by_pin.items()
        ),
        "CANONICAL_PIN_BINDING_REQUIRED",
    )
    _need(len(set(by_pin.values())) == len(by_pin), "CANONICAL_PIN_JOIN_NOT_UNIQUE")
    _need(by_pin.get(record["pin"]) == record["user_id"], "CANONICAL_PIN_JOIN_CHANGED")


def _source(
    check: SourceCheck,
    record: dict[str, Any],
    decision: dict[str, Any],
    pins: dict[str, Any],
) -> None:
    _need(callable(check), "SOURCE_REVALIDATOR_REQUIRED")
    try:
        outcome = check(
            copy.deepcopy(record), copy.deepcopy(decision), copy.deepcopy(pins)
        )
    except Exception:
        raise GradebookError("SOURCE_AUTHORITY_REVALIDATION_HELD") from None
    if inspect.iscoroutine(outcome):
        outcome.close()
    _need(
        outcome is None,
        "SOURCE_REVALIDATOR_MUST_ASSERT",
    )


def _basis(snapshot: dict[str, Any], record: dict[str, Any]) -> dict[str, Any]:
    uid, aid = record["user_id"], record["assignment_id"]
    students = [s for s in snapshot["students"] if s["id"] == uid]
    assignments = [a for a in snapshot["assignments"] if a["id"] == aid]
    _need(len(students) == len(assignments) == 1, "EXACT_ACTIVE_TARGET_REQUIRED")
    return {
        "origin": snapshot["origin"],
        "course_id": snapshot["course_id"],
        "course_workflow_state": snapshot.get("course_workflow_state"),
        "student": {field: students[0].get(field) for field in ("id", "sections")},
        "assignment": copy.deepcopy(assignments[0]),
        "cell": copy.deepcopy(snapshot["cells"].get(f"{uid}:{aid}")),
    }


def _location(cells: dict[str, Any], record: dict[str, Any]) -> tuple[int, int]:
    rows, columns = [], []
    for address, cell in cells.items():
        row, col = map(int, address.split(":"))
        entered = cell.get("userEnteredValue", {})
        if len(entered) != 1 or set(entered) - {"numberValue", "stringValue"}:
            continue
        value = str(next(iter(entered.values())))
        if col == 0 and row >= 5 and value == record["user_id"]:
            rows.append(row)
        if row == 4 and col >= 2 and value == record["assignment_id"]:
            columns.append(col)
    _need(len(rows) == len(columns) == 1, "EXACT_EDIT_AXIS_REQUIRED")
    return rows[0], columns[0]


def _baseline_note(
    baseline: dict[str, Any], binding: dict[str, Any], record: dict[str, Any]
) -> str:
    requests = build_requests(
        baseline, baseline, digest(baseline), binding, baseline, 0
    )
    block = next(
        r["updateCells"]
        for r in requests
        if "updateCells" in r
        and r["updateCells"].get("start", {}).get("sheetId")
        == binding["sheets"]["Working"]
    )
    row = next(
        i
        for i, item in enumerate(baseline["students"], 5)
        if item["id"] == record["user_id"]
    )
    col = next(
        i
        for i, item in enumerate(baseline["assignments"], 2)
        if item["id"] == record["assignment_id"]
    )
    return str(block["rows"][row]["values"][col].get("note", ""))


def _note(prefix: str, selection_sha256: str, feedback: str) -> str:
    return (
        prefix
        + ("\n\n" if prefix else "")
        + "Teacher-reviewed final content transferred to local EDIT. "
        + "Canvas score and feedback delivery require separate authorization.\n"
        + "Exact selection: "
        + selection_sha256
        + "\n\n"
        + feedback
    )


def prepare_transfer(
    record: dict[str, Any],
    decision: dict[str, Any],
    *,
    raw: dict[str, Any],
    binding: dict[str, Any],
    baseline: dict[str, Any],
    current: dict[str, Any],
    pin_binding: dict[str, Any],
    source_check: SourceCheck,
) -> dict[str, Any]:
    """Return a single Working-cell batch and complete expected native readback.

    source_check must independently authenticate current source/result/policy,
    identity and the substantive teacher decision in existing proposal fields.
    It must never interpret arbitrary M-column text as acceptance. This pure
    function cannot establish liveness or authenticate its own input record.
    """
    _selection(record, decision)
    _pins(pin_binding, record)
    _source(source_check, record, decision, pin_binding)
    # Only substantive fields bind a decision. Fetch/report timestamps do not
    # silently revoke or renew it; original audit metadata stays with its owner.
    selected = {field: copy.deepcopy(record[field]) for field in RECORD_FIELDS}
    final = {field: copy.deepcopy(decision[field]) for field in DECISION_FIELDS}
    _need(
        (baseline["origin"], baseline["course_id"])
        == (current["origin"], current["course_id"])
        and current["course_id"] == record["course_id"] == str(binding["course_id"]),
        "CANVAS_SCOPE_CHANGED",
    )
    extract_native_edits(raw, binding, baseline)
    before = native._state(raw)
    _need(
        before["spreadsheetId"] == binding["spreadsheet_id"],
        "WORKBOOK_IDENTITY_CHANGED",
    )
    context = _basis(current, record)
    prior_context = _basis(baseline, record)
    _need(
        context["course_workflow_state"] == "available"
        and record["section"] in context["student"]["sections"],
        "CURRENT_SECTION_TARGET_CHANGED",
    )
    for context_item in (context, prior_context):
        assignment = context_item["assignment"]
        _need(
            assignment["grading_type"] == "points"
            and assignment["points_possible"] == decision["points_possible"],
            "ASSIGNMENT_SCORE_SCHEMA_CHANGED",
        )
    cell = context["cell"]
    _need(
        type(cell) is dict and cell.get("visible") is True,
        "CANVAS_TARGET_UNKNOWN_OR_HIDDEN",
    )
    _need(
        type(cell.get("attempt")) is int
        and cell["attempt"] == record["canvas_attempt"],
        "OBSERVED_CANVAS_ATTEMPT_CHANGED",
    )
    _need(
        cell.get("excused") is False and cell.get("value") != "EX",
        "CANVAS_EXCUSAL_PRESERVED",
    )
    _need(
        cell.get("grade_matches_current_submission") is True,
        "CURRENT_CANVAS_GRADE_UNKNOWN",
    )
    _need(cell == prior_context["cell"], "CANVAS_TARGET_CHANGED_SINCE_BASELINE")
    score = decision["total_score"]
    value = grade_value(cell.get("value"))
    _need(
        value is None or _number(value) and value <= score,
        "HIGHER_CANVAS_SCORE_PRESERVED",
    )
    review = compare_edits(
        baseline,
        current,
        {
            "course_id": record["course_id"],
            "snapshot_id": digest(baseline),
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
        all(
            item["status"] == "ready_for_review" and not item["reasons"]
            for item in review["changes"]
        ),
        "CANVAS_COMPARISON_HELD",
    )
    sid = binding["sheets"]["Working"]
    working = before["sheets"][sid]
    _need(
        working["properties"]["title"] == binding["tab_names"]["Working"],
        "EDIT_TAB_CHANGED",
    )
    row, col = _location(working["cells"], record)
    address = f"{row}:{col}"
    old = working["cells"].get(address, {})
    old_value = grade_value(next(iter(old.get("userEnteredValue", {}).values()), None))
    old_note = old.get("note", "")
    canonical_note = _baseline_note(baseline, binding, record)
    selection_sha256 = digest({"record": selected, "decision": final})
    notes = [
        _note(prefix, selection_sha256, final["feedback"])
        for prefix in (canonical_note, "")
    ]
    after = copy.deepcopy(before)
    requests = []
    if old_value == score and old_note in notes:
        status = "NO_CHANGE"
    else:
        _need(
            old_value in (grade_value(prior_context["cell"]["value"]), score),
            "EXISTING_TEACHER_EDIT_PRESERVED",
        )
        _need(old_note in ("", canonical_note), "EXISTING_TEACHER_NOTE_PRESERVED")
        replacement = {
            "userEnteredValue": {"numberValue": score},
            "note": _note(old_note, selection_sha256, final["feedback"]),
        }
        after["sheets"][sid]["cells"].setdefault(address, {}).update(replacement)
        requests = [
            {
                "updateCells": {
                    "start": {"sheetId": sid, "rowIndex": row, "columnIndex": col},
                    "rows": [{"values": [replacement]}],
                    "fields": "userEnteredValue,note",
                }
            }
        ]
        status = "PREPARED_LOCAL_EDIT_ONLY"
    return {
        "contract": CONTRACT,
        "status": status,
        "record": selected,
        "decision": final,
        "selection_sha256": selection_sha256,
        "binding": copy.deepcopy(binding),
        "baseline": copy.deepcopy(baseline),
        "current_basis": context,
        "pin_binding_sha256": digest(pin_binding),
        "before_state": json.loads(json.dumps(before, allow_nan=False)),
        "after_state": json.loads(json.dumps(after, allow_nan=False)),
        "requests": requests,
        "score_delivery_authorized": False,
        "comment_delivery_authorized": False,
        "canvas_writes": 0,
        "sheets_writes": 0,
    }


def _plan(plan: dict[str, Any], expected_plan_sha256: str) -> None:
    _need(
        type(expected_plan_sha256) is str
        and HASH.fullmatch(expected_plan_sha256)
        and digest(plan) == expected_plan_sha256
        and plan.get("contract") == CONTRACT,
        "EXACT_TRANSFER_PLAN_CHANGED",
    )
    _need(
        plan.get("score_delivery_authorized") is False
        and plan.get("comment_delivery_authorized") is False,
        "TRANSFER_IS_NOT_PUBLICATION_AUTHORITY",
    )


def revalidate_transfer(
    plan: dict[str, Any],
    *,
    expected_plan_sha256: str,
    raw: dict[str, Any],
    current: dict[str, Any],
    pin_binding: dict[str, Any],
    source_check: SourceCheck,
) -> None:
    """Assert the pinned source/decision and complete destination before a write.

    This is a preflight for an existing owner, not a transport or atomic lock.
    The owner must keep the workbook idle, retain the plan before sending once,
    and use readback only after any uncertain outcome.
    """
    _plan(plan, expected_plan_sha256)
    _need(digest(pin_binding) == plan["pin_binding_sha256"], "PIN_AUTHORITY_CHANGED")
    _source(source_check, plan["record"], plan["decision"], pin_binding)
    _need(_portable_state(raw) == plan["before_state"], "TRANSFER_DESTINATION_CHANGED")
    _need(
        _basis(current, plan["record"]) == plan["current_basis"],
        "CANVAS_TARGET_CHANGED_AFTER_PREP",
    )
    fresh = prepare_transfer(
        plan["record"],
        plan["decision"],
        raw=raw,
        binding=plan["binding"],
        baseline=plan["baseline"],
        current=current,
        pin_binding=pin_binding,
        source_check=lambda *unused: None,
    )
    _need(fresh == plan, "EXACT_TRANSFER_PLAN_CHANGED")


def classify_readback(
    plan: dict[str, Any],
    raw: dict[str, Any],
    *,
    expected_plan_sha256: str,
) -> dict[str, Any]:
    """Classify captured native evidence; absence never permits a blind replay."""
    _plan(plan, expected_plan_sha256)
    actual = _portable_state(raw)
    status = (
        "PLANNED_OUTPUT_OBSERVED"
        if actual == plan["after_state"]
        else "BEFORE_STILL_PRESENT" if actual == plan["before_state"] else "DIVERGED"
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
    }
