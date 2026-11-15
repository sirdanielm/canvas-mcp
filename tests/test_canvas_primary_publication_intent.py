"""Fictional inert publication intent, no live client or Canvas mutation."""

import pytest
from test_canvas_primary_owner import connection as connection
from test_canvas_primary_review import case as case
from test_gradebook import snapshot as snapshot
from test_gradebook_native import binding as binding
from test_gradebook_native import raw_from_state

from canvas_mcp.gradebook import native
from canvas_mcp.gradebook.canvas_primary_publication_intent import (
    prepare_publication_intent,
)
from canvas_mcp.gradebook.client import GradebookError
from canvas_mcp.gradebook.model import digest


@pytest.fixture
async def ready(connection, case):
    await connection.refresh_source("fictional-canvas")
    stage = connection.prepare(
        **{k: case[k] for k in ("raw", "binding", "baseline", "current", "pin_binding")}
    )
    stage_id = digest(stage)
    state = native._state(case["raw"])
    update = stage["transfer"]["requests"][0]["updateCells"]
    start = update["start"]
    state["sheets"][start["sheetId"]]["cells"][
        f"{start['rowIndex']}:{start['columnIndex']}"
    ].update(update["rows"][0]["values"][0])
    receipt = {
        "contract": connection.contract,
        "plan_id": stage_id,
        "status": "PLANNED_OUTPUT_OBSERVED",
        "canvas_writes": 0,
        "publication_allowed": False,
    }

    def verify_stage(plan, actual):
        if plan != stage or actual != receipt:
            raise ValueError("not retained stage")

    def approval(intent):
        assert (
            intent["approval_scope"] == "LOWER_OR_BLANK_ONLY"
            and intent["target"]["user_id"] == "101"
        )

    return {
        "connection": connection,
        "stage_plan": stage,
        "expected_stage_plan_sha256": stage_id,
        "stage_receipt": receipt,
        "raw": raw_from_state(state),
        "current": case["current"],
        "pin_binding": case["pin_binding"],
        "verify_stage_receipt": verify_stage,
        "verify_approval_scope": approval,
    }


def test_current_operation_review_is_distinct_from_original_sync(ready):
    result = prepare_publication_intent(**ready)
    intent = result["intent"]
    assert intent["original_sync_baseline_sha256"] == digest(
        ready["stage_plan"]["transfer"]["baseline"]
    )
    assert intent["operation_current_baseline_sha256"] == digest(ready["current"])
    assert intent["score_only"] is True and intent["user_approval_created"] is False
    assert intent["canvas_writes"] == result["canvas_writes"] == 0
    assert intent["publication_allowed"] is result["publication_allowed"] is False
    assert result["review"]["changes"][0]["status"] == "ready_for_review"


@pytest.mark.parametrize(
    "change",
    [
        "missing_approval",
        "bad_receipt",
        "missing_receipt_authority",
        "destination_changed",
        "source_changed",
        "source_seal_missing",
        "same_grade",
        "higher_grade",
        "inconsistent_grade",
        "protected_target",
        "student_info_changed",
    ],
)
def test_inert_intent_holds_unqualified_context(ready, change):
    c = ready
    if change == "missing_approval":
        c["verify_approval_scope"] = None
    elif change == "bad_receipt":
        c["stage_receipt"]["status"] = "SENDING"
    elif change == "missing_receipt_authority":
        c["verify_stage_receipt"] = None
    elif change == "destination_changed":
        c["raw"]["sheets"][0]["properties"]["title"] = "tampered"
    elif change == "source_changed":
        c["current"]["cells"]["101:21"]["attempt"] = 4
    elif change == "source_seal_missing":
        c["connection"]._source_fresh = False
    elif change == "same_grade":
        c["current"]["cells"]["101:21"]["value"] = 20
    elif change == "higher_grade":
        c["current"]["cells"]["101:21"]["value"] = 21
    elif change == "inconsistent_grade":
        c["current"]["cells"]["101:21"]["grade"] = "0"
    elif change == "protected_target":
        c["connection"].authority.expected_registry["protected_targets"].append(
            {
                "course_id": "12",
                "assignment_id": "21",
                "user_id": "101",
                "evidence_sha256": "a" * 64,
            }
        )
    else:
        state = native._state(c["raw"])
        state["sheets"][99]["cells"]["1:1"]["userEnteredValue"]["stringValue"] = "9999"
        c["raw"] = raw_from_state(state)
    with pytest.raises(GradebookError):
        prepare_publication_intent(**c)


@pytest.mark.parametrize(
    ("value", "grade", "allowed"),
    [
        (None, None, True),
        (0, "0", True),
        (10, "10", True),
        (20, "20", False),
        (21, "21", False),
        (None, "0", False),
        (0, None, False),
        ("EX", "EX", False),
    ],
)
def test_lower_or_blank_policy_is_not_just_a_receipt_hash(value, grade, allowed):
    from canvas_mcp.gradebook.canvas_primary_publication_intent import _lower_or_blank

    cell = {"value": value, "grade": grade}
    if allowed:
        _lower_or_blank(cell, 20)
    else:
        with pytest.raises(GradebookError):
            _lower_or_blank(cell, 20)


@pytest.mark.parametrize("mutation", ["registry_pin", "duplicate_user"])
def test_current_pin_binding_drift_holds(ready, mutation):
    if mutation == "registry_pin":
        ready["pin_binding"]["registry_sha256"] = "0" * 64
    else:
        ready["pin_binding"]["by_pin"]["9999"] = "101"
    with pytest.raises(GradebookError):
        prepare_publication_intent(**ready)
