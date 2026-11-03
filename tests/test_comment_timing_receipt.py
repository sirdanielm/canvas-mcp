"""Fictional transport: preserve exact evidence of allowed Canvas timing changes."""

import copy

import pytest
from test_gradebook import snapshot as snapshot
from test_gradebook_publish import comment_system as comment_system
from test_gradebook_publish import prepared_comment
from test_gradebook_publish import system as system


@pytest.mark.parametrize("lost_response", [False, True])
async def test_comment_receipt_reports_timing_changes_and_actual_baseline(
    comment_system, lost_response
):
    publisher, state, envelope = comment_system
    state["submission"]["seconds_late"] = 40
    state["after_put"].update(posted_at="2026-09-17T20:00:01Z", seconds_late=43)
    protected = copy.deepcopy(state["submission"])
    proposal = await prepared_comment(comment_system)
    state["submission"]["seconds_late"] = 42
    if lost_response:
        state["behavior"] = "timeout_applied"
    result = await publisher.confirm_comment(
        "12", proposal["operation_id"], proposal["confirmation_token"]
    )
    if lost_response:
        result = await publisher.reconcile_comment("12", proposal["operation_id"])
    receipt = publisher.store.load("receipt", result["readback_receipt_id"])
    assert receipt["comparison_before"] == (
        "original_preview" if lost_response else "send_preflight"
    )
    assert receipt["observed_submission_timing_changes"] == {
        "updated_at": {
            "before_present": True,
            "before": "2026-09-17T20:00:00Z",
            "after_present": True,
            "after": "2026-09-17T20:00:01Z",
        },
        "posted_at": {
            "before_present": True,
            "before": None,
            "after_present": True,
            "after": "2026-09-17T20:00:01Z",
        },
        "seconds_late": {
            "before_present": True,
            "before": 40 if lost_response else 42,
            "after_present": True,
            "after": 43,
        },
    }
    assert receipt["comparison"]["stored_verified"] is (not lost_response)
    assert result["counts"] == {"observed_applied" if lost_response else "verified": 1}
    assert state["forms"] == [
        {
            "comment[text_comment]": [envelope["comment"]],
            "comment[group_comment]": ["false"],
        }
    ]
    for field, value in protected.items():
        if field not in {
            "submission_comments",
            "updated_at",
            "posted_at",
            "seconds_late",
        }:
            assert state["submission"][field] == value
    assert (
        state["submission"]["submission_comments"][:-1]
        == protected["submission_comments"]
    )


@pytest.mark.parametrize("clock_present", [False, True])
async def test_comment_receipt_does_not_invent_changes_for_absent_or_null_fields(
    comment_system, clock_present
):
    publisher, state, _ = comment_system
    if clock_present:
        state["submission"]["seconds_late"] = None
    state["after_put"]["updated_at"] = state["submission"]["updated_at"]
    proposal = await prepared_comment(comment_system)
    result = await publisher.confirm_comment(
        "12", proposal["operation_id"], proposal["confirmation_token"]
    )
    receipt = publisher.store.load("receipt", result["readback_receipt_id"])
    assert receipt["observed_submission_timing_changes"] == {}
    assert ("seconds_late" in state["submission"]) is clock_present
    assert state["submission"]["posted_at"] is None
    assert len(state["forms"]) == 1


async def test_timing_receipt_does_not_promote_score_conflict_to_success(
    comment_system,
):
    publisher, state, _ = comment_system
    state["after_put"]["score"] = 11
    proposal = await prepared_comment(comment_system)
    result = await publisher.confirm_comment(
        "12", proposal["operation_id"], proposal["confirmation_token"]
    )
    receipt = publisher.store.load("receipt", result["readback_receipt_id"])
    assert set(receipt["observed_submission_timing_changes"]) == {"updated_at"}
    assert receipt["comparison"]["outcome"] == "CONFLICT"
    assert receipt["comparison"]["stored_verified"] is False
    assert result["counts"] == {"uncertain": 1}
    assert len(state["forms"]) == 1
