"""Fictional clock-drift regressions; all HTTP uses controlled MockTransport."""

import copy
import hashlib
import json
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest
from test_gradebook_publish import comment_system as comment_system
from test_gradebook_publish import prepared_comment
from test_gradebook_publish import snapshot as snapshot
from test_gradebook_publish import system as system
from test_unit1_canvas_protocol import inputs as inputs
from test_unit1_canvas_protocol import observation, raw_bytes, request_spec

from canvas_mcp.gradebook.client import GradebookError
from canvas_mcp.gradebook.ledger import Ledger
from canvas_mcp.gradebook.publish import (
    Publisher,
    comment_clock_limit,
    comment_target_unchanged,
)
from canvas_mcp.gradebook.store import Store
from canvas_mcp.gradebook.unit1_canvas_protocol import (
    CanvasTarget,
    CommentReadback,
    compare_comment_readback,
)

Inputs = tuple[CanvasTarget, dict[str, Any], dict[str, Any]]
ABSENT = object()


def clock_pair(
    inputs: Inputs, old: Any = 100, new: Any = 102
) -> tuple[Any, Any, Any, dict[str, Any], dict[str, Any]]:
    initial = copy.deepcopy(inputs[2])
    if old is not ABSENT:
        initial["seconds_late"] = old
    final = copy.deepcopy(initial)
    if new is ABSENT:
        final.pop("seconds_late", None)
    else:
        final["seconds_late"] = new
    final["submission_comments"].append(
        {"id": 502, "author_id": 701, "comment": "Approved feedback"}
    )
    before = observation(inputs, submission=initial)
    after = observation(inputs, submission=final)
    return (
        before,
        after,
        request_spec(before, "COMMENT", "Approved feedback"),
        initial,
        final,
    )


def compared(pair: tuple[Any, ...], **kwargs: Any) -> CommentReadback:
    before, after, spec = pair[:3]
    return compare_comment_readback(
        spec,
        before,
        after,
        publisher_author_id="701",
        response_received=True,
        response_comment_id="502",
        **kwargs,
    )


def test_bounded_comment_clock_advance_preserves_original_evidence(
    inputs: Inputs,
) -> None:
    pair = clock_pair(inputs)
    result = compared(pair, max_clock_advance_seconds=2)
    assert result.outcome == "VERIFIED_APPLIED" and result.stored_verified
    before, after, _, initial, final = pair
    assert (
        before.submission_body_sha256 == hashlib.sha256(raw_bytes(initial)).hexdigest()
    )
    assert after.submission_body_sha256 == hashlib.sha256(raw_bytes(final)).hexdigest()
    assert before.submission_metadata_sha256 != after.submission_metadata_sha256
    assert before.comment_metadata_sha256 == after.comment_metadata_sha256
    assert before.submission_field("seconds_late").value == 100
    assert after.submission_field("seconds_late").value == 102
    assert not result.retry_writes and not result.publication_authorized


def test_comment_clock_is_strict_without_explicit_elapsed_bound(inputs: Inputs) -> None:
    assert compared(clock_pair(inputs)).outcome == "CONFLICT"


@pytest.mark.parametrize("bound", [True, -1, float("nan"), float("inf"), "2", None])
def test_invalid_comment_clock_bounds_fail_closed(inputs: Inputs, bound: Any) -> None:
    with pytest.raises(GradebookError, match="COMMENT_CLOCK_BOUND_INVALID"):
        compared(clock_pair(inputs), max_clock_advance_seconds=bound)


@pytest.mark.parametrize(
    "old,new",
    [
        (100, 99),
        (100, 103),
        (100, None),
        (None, 100),
        (100, ABSENT),
        (ABSENT, 100),
        (None, ABSENT),
        (True, 1),
        (1, True),
        (True, True),
        (100.0, 100),
        (100, 100.0),
        (100.0, 100.0),
        (-1, -1),
        (-1, 0),
        ("100", "100"),
    ],
)
def test_comment_clock_cannot_hide_unknown_regressing_or_excessive_values(
    inputs: Inputs, old: Any, new: Any
) -> None:
    result = compared(clock_pair(inputs, old, new), max_clock_advance_seconds=2)
    assert result.outcome == "CONFLICT" and not result.stored_verified


@pytest.mark.parametrize("value", [ABSENT, None, 0, 100])
@pytest.mark.parametrize("bound", [0, 2])
def test_unchanged_legacy_clock_state_stays_compatible(
    inputs: Inputs, value: Any, bound: int
) -> None:
    assert compared(
        clock_pair(inputs, value, value), max_clock_advance_seconds=bound
    ).stored_verified


@pytest.mark.parametrize(
    "scope,field,value",
    [
        ("assignment", "points_possible", 101),
        ("submission", "score", 1),
        ("submission", "excused", True),
        ("submission", "attempt", 1),
        ("submission", "points_deducted", 1),
        ("submission", "late_policy_status", "late"),
        ("submission", "missing", True),
        ("submission", "in_closed_grading_period", True),
        ("submission", "user", {"name": "changed fictional metadata"}),
    ],
)
def test_clock_exception_preserves_every_other_remote_field(
    inputs: Inputs, scope: str, field: str, value: Any
) -> None:
    before, _, spec, _, final = clock_pair(inputs)
    assignment = copy.deepcopy(inputs[1])
    (assignment if scope == "assignment" else final)[field] = value
    after = observation(inputs, assignment=assignment, submission=final)
    result = compared((before, after, spec), max_clock_advance_seconds=2)
    assert result.outcome == "CONFLICT" and not result.stored_verified


def private_state(submission: dict[str, Any]) -> dict[str, Any]:
    return {
        "assignment": {
            "url": "https://canvas.example.invalid/assignment",
            "body": "{}",
        },
        "submission": {
            "url": "https://canvas.example.invalid/submission",
            "body": json.dumps(submission),
            "coverage_complete": True,
        },
    }


def test_preflight_allows_only_bounded_clock_and_preserves_raw_inputs() -> None:
    expected = private_state({"seconds_late": 100, "protected": {"value": True}})
    fresh = private_state({"seconds_late": 102, "protected": {"value": True}})
    retained = copy.deepcopy((expected, fresh))
    assert comment_target_unchanged(expected, fresh, max_clock_advance_seconds=2)
    assert (expected, fresh) == retained
    assert not comment_target_unchanged(expected, fresh, max_clock_advance_seconds=1)
    fresh["submission"]["body"] = json.dumps(
        {"seconds_late": 102, "protected": {"value": 1}}
    )
    assert not comment_target_unchanged(expected, fresh, max_clock_advance_seconds=2)


@pytest.mark.parametrize(
    "old,new",
    [(100, 99), (100, None), (None, 100), (True, 1), (100, 100.0), (-1, -1)],
)
def test_preflight_clock_rejects_types_nulls_and_reversal(old: Any, new: Any) -> None:
    assert not comment_target_unchanged(
        private_state({"seconds_late": old}),
        private_state({"seconds_late": new}),
        max_clock_advance_seconds=5,
    )


@pytest.mark.parametrize("old,new", [(100, ABSENT), (ABSENT, 100), (None, ABSENT)])
def test_preflight_preserves_counter_presence(old: Any, new: Any) -> None:
    expected = {} if old is ABSENT else {"seconds_late": old}
    fresh = {} if new is ABSENT else {"seconds_late": new}
    assert not comment_target_unchanged(
        private_state(expected), private_state(fresh), max_clock_advance_seconds=5
    )


@pytest.mark.parametrize(
    "scope,key,value",
    [
        ("assignment", "body", '{"changed":true}'),
        ("submission", "url", "https://other.invalid"),
        ("submission", "coverage_complete", False),
    ],
)
def test_preflight_keeps_assignment_and_get_wrappers_exact(
    scope: str, key: str, value: Any
) -> None:
    expected = private_state({"seconds_late": 100})
    fresh = private_state({"seconds_late": 101})
    fresh[scope][key] = value
    assert not comment_target_unchanged(expected, fresh, max_clock_advance_seconds=5)


@pytest.mark.parametrize("value", ["invalid", "2026-10-01T00:00:00", None])
def test_elapsed_clock_rejects_unknown_observation_time(value: Any) -> None:
    with pytest.raises(GradebookError):
        comment_clock_limit(value)


def test_elapsed_clock_uses_actual_age_and_rejects_future_time(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixed = datetime(2026, 10, 20, tzinfo=UTC)

    class ObservedTime(datetime):
        @classmethod
        def now(cls, tz: Any = None) -> datetime:
            return fixed

    monkeypatch.setattr("canvas_mcp.gradebook.publish.datetime", ObservedTime)
    assert comment_clock_limit((fixed - timedelta(seconds=2.1)).isoformat()) == 8
    assert comment_clock_limit(fixed.isoformat()) == 5
    with pytest.raises(GradebookError):
        comment_clock_limit((fixed + timedelta(seconds=10)).isoformat())


async def install_clock_transport(comment_system: tuple[Any, ...]) -> None:
    publisher, state, _ = comment_system
    state["submission"]["seconds_late"] = 100
    transport = publisher.client.http._transport

    async def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET" and "/submissions/" in request.url.path:
            state["submission"]["seconds_late"] += 1
        return await transport.handle_async_request(request)

    publisher.client.http = httpx.AsyncClient(transport=httpx.MockTransport(handler))


async def test_preview_preflight_and_post_put_clock_ticks_verify_once(
    comment_system: tuple[Any, ...],
) -> None:
    publisher, state, envelope = comment_system
    await install_clock_transport(comment_system)
    proposal = await prepared_comment(comment_system)
    result = await publisher.confirm_comment(
        "12", proposal["operation_id"], proposal["confirmation_token"]
    )
    assert result["counts"] == {"verified": 1}
    receipt = publisher.store.load("receipt", result["readback_receipt_id"])
    assert receipt["comparison"]["stored_verified"] is True
    assert receipt["comparison_before"] == "send_preflight"
    assert json.loads(receipt["before"]["submission"]["body"])["seconds_late"] == 101
    assert (
        json.loads(receipt["send_preflight"]["submission"]["body"])["seconds_late"]
        == 102
    )
    assert json.loads(receipt["after"]["submission"]["body"])["seconds_late"] == 103
    assert state["submission"]["seconds_late"] == 103
    assert state["forms"] == [
        {
            "comment[text_comment]": [envelope["comment"]],
            "comment[group_comment]": ["false"],
        }
    ]
    assert state["submission"]["score"] == 10 and state["submission"]["grade"] == "10"


async def test_elapsed_clock_cannot_upgrade_lost_response_to_verified(
    comment_system: tuple[Any, ...],
) -> None:
    publisher, state, _ = comment_system
    await install_clock_transport(comment_system)
    proposal = await prepared_comment(comment_system)
    state["behavior"] = "timeout_applied"
    result = await publisher.confirm_comment(
        "12", proposal["operation_id"], proposal["confirmation_token"]
    )
    assert result["counts"] == {"uncertain": 1}
    result = await publisher.reconcile_comment("12", proposal["operation_id"])
    assert result["counts"] == {"observed_applied": 1}
    receipt = publisher.store.load("receipt", result["readback_receipt_id"])
    assert receipt["comparison"]["outcome"] == "OBSERVED_APPLIED"
    assert receipt["comparison"]["stored_verified"] is False
    assert receipt["response_comment_id"] is None
    assert len(state["forms"]) == 1
    with pytest.raises(GradebookError, match="already consumed"):
        await publisher.confirm_comment(
            "12", proposal["operation_id"], proposal["confirmation_token"]
        )
    assert len(state["forms"]) == 1


async def test_clock_ticks_survive_response_checkpoint_restart_without_resend(
    comment_system: tuple[Any, ...],
) -> None:
    publisher, state, _ = comment_system
    await install_clock_transport(comment_system)
    proposal = await prepared_comment(comment_system)
    state["fail_readback"] = True
    with pytest.raises(GradebookError, match="Canvas read failed"):
        await publisher.confirm_comment(
            "12", proposal["operation_id"], proposal["confirmation_token"]
        )
    operation = publisher.ledger.operation(proposal["operation_id"])
    assert operation["status"] == "uncertain"
    assert operation["items"][0]["response_comment_id"] == "502"
    assert len(state["forms"]) == 1
    state["fail_readback"] = False
    restarted = Publisher(
        publisher.client, Store(publisher.store.root), Ledger(publisher.store.root)
    )
    result = await restarted.reconcile_comment("12", proposal["operation_id"])
    assert result["counts"] == {"verified": 1}
    assert state["submission"]["seconds_late"] == 104
    receipt = restarted.store.load("receipt", result["readback_receipt_id"])
    assert receipt["comparison"]["outcome"] == "VERIFIED_APPLIED"
    assert receipt["response_comment_id"] == "502"
    assert len(state["forms"]) == 1
    assert state["submission"]["score"] == 10 and state["submission"]["grade"] == "10"
