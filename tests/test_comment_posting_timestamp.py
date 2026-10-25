"""Pure fictional readback evidence; no clients, network, stores, or live data."""

import copy
import hashlib
from typing import Any

import pytest
from test_unit1_canvas_protocol import inputs as inputs
from test_unit1_canvas_protocol import observation, raw_bytes, request_spec

from canvas_mcp.gradebook.client import GradebookError
from canvas_mcp.gradebook.unit1_canvas_protocol import (
    CanvasTarget,
    CommentReadback,
    compare_comment_readback,
)

Inputs = tuple[CanvasTarget, dict[str, Any], dict[str, Any]]
WINDOW = ("2026-10-20T12:00:00Z", "2026-10-20T12:00:20Z")
ABSENT = object()


def posting_pair(
    inputs: Inputs, posted: Any = "2026-10-20T12:00:10Z"
) -> tuple[Any, ...]:
    assignment = copy.deepcopy(inputs[1])
    assignment["post_manually"] = False
    initial = copy.deepcopy(inputs[2])
    initial["updated_at"] = "2026-09-17T20:00:00Z"
    final = copy.deepcopy(initial)
    final["posted_at"] = posted
    final["submission_comments"].append(
        {"id": 502, "author_id": 701, "comment": "Approved feedback"}
    )
    return assignment, initial, final


def compare_posting(
    inputs: Inputs,
    pair: tuple[Any, ...],
    *,
    window: Any = WINDOW,
    response_received: bool = True,
    response_comment_id: str | None = "502",
) -> CommentReadback:
    assignment, initial, final = pair
    before = observation(inputs, assignment=assignment, submission=initial)
    after = observation(inputs, assignment=assignment, submission=final)
    return compare_comment_readback(
        request_spec(before, "COMMENT", "Approved feedback"),
        before,
        after,
        publisher_author_id="701",
        response_received=response_received,
        response_comment_id=response_comment_id,
        posting_observation_window=window,
    )


def test_automatic_posting_with_stable_update_requires_observed_window(
    inputs: Inputs,
) -> None:
    pair = posting_pair(inputs)
    retained = copy.deepcopy(pair)
    assert compare_posting(inputs, pair, window=None).outcome == "CONFLICT"
    result = compare_posting(inputs, pair)
    assert result.outcome == "VERIFIED_APPLIED" and result.stored_verified
    assert pair == retained
    assignment, initial, final = pair
    before = observation(inputs, assignment=assignment, submission=initial)
    after = observation(inputs, assignment=assignment, submission=final)
    assert before.submission_field("updated_at") == after.submission_field("updated_at")
    assert before.submission_metadata_sha256 != after.submission_metadata_sha256
    assert (
        before.submission_body_sha256 == hashlib.sha256(raw_bytes(initial)).hexdigest()
    )
    assert after.submission_body_sha256 == hashlib.sha256(raw_bytes(final)).hexdigest()
    assert not result.retry_writes and not result.publication_authorized
    assert result.student_visibility == "NOT_ESTABLISHED"


def test_stable_update_posting_does_not_upgrade_a_lost_response(inputs: Inputs) -> None:
    result = compare_posting(
        inputs, posting_pair(inputs), response_received=False, response_comment_id=None
    )
    assert result.outcome == "OBSERVED_APPLIED" and not result.stored_verified
    assert not result.retry_writes and not result.publication_authorized


@pytest.mark.parametrize("response_received", [True, False])
def test_omitted_update_requires_explicit_window_without_inventing_a_timestamp(
    inputs: Inputs, response_received: bool
) -> None:
    pair = posting_pair(inputs)
    pair[1].pop("updated_at")
    pair[2].pop("updated_at")
    retained = copy.deepcopy(pair)
    response_id = "502" if response_received else None
    assert (
        compare_posting(
            inputs,
            pair,
            window=None,
            response_received=response_received,
            response_comment_id=response_id,
        ).outcome
        == "CONFLICT"
    )
    result = compare_posting(
        inputs,
        pair,
        response_received=response_received,
        response_comment_id=response_id,
    )
    assert result.outcome == (
        "VERIFIED_APPLIED" if response_received else "OBSERVED_APPLIED"
    )
    assert result.stored_verified is response_received
    assert pair == retained
    for submission in pair[1:]:
        assert "updated_at" not in submission
        parsed = observation(inputs, assignment=pair[0], submission=submission)
        assert not parsed.submission_field("updated_at").present
        assert (
            parsed.submission_body_sha256
            == hashlib.sha256(raw_bytes(submission)).hexdigest()
        )


@pytest.mark.parametrize(
    "value", [None, True, 0, 100, "invalid", "2026-09-17T20:00:00"]
)
def test_explicit_unknown_or_malformed_update_remains_held(
    inputs: Inputs, value: Any
) -> None:
    pair = posting_pair(inputs)
    pair[1]["updated_at"] = pair[2]["updated_at"] = value
    result = compare_posting(inputs, pair)
    assert not result.stored_verified and result.outcome in {"CONFLICT", "HELD"}


@pytest.mark.parametrize(
    "old,new",
    [
        (ABSENT, None),
        (None, ABSENT),
        (ABSENT, "2026-09-17T20:00:00Z"),
        ("2026-09-17T20:00:00Z", ABSENT),
        (None, "2026-09-17T20:00:00Z"),
        ("2026-09-17T20:00:00Z", None),
    ],
)
def test_posting_window_cannot_change_update_presence_or_value(
    inputs: Inputs, old: Any, new: Any
) -> None:
    pair = posting_pair(inputs)
    for submission, value in zip(pair[1:], (old, new), strict=True):
        if value is ABSENT:
            submission.pop("updated_at")
        else:
            submission["updated_at"] = value
    assert not compare_posting(inputs, pair).stored_verified


@pytest.mark.parametrize(
    "variant",
    [
        "manual-policy",
        "outside-window",
        "wrong-response",
        "score-drift",
        "no-new-comment",
    ],
)
def test_omitted_update_preserves_all_other_posting_and_delivery_guards(
    inputs: Inputs, variant: str
) -> None:
    pair = posting_pair(inputs)
    pair[1].pop("updated_at")
    pair[2].pop("updated_at")
    if variant == "manual-policy":
        pair[0]["post_manually"] = True
    elif variant == "outside-window":
        pair[2]["posted_at"] = "2026-10-20T12:00:26Z"
    elif variant == "score-drift":
        pair[2]["score"] = 1
    elif variant == "no-new-comment":
        pair[2]["submission_comments"].pop()
    assert not compare_posting(
        inputs,
        pair,
        response_comment_id="999" if variant == "wrong-response" else "502",
    ).stored_verified


@pytest.mark.parametrize(
    "window",
    [
        [],
        list(WINDOW),
        "2026-10-20T12:00:00Z",
        (),
        (WINDOW[0],),
        (*WINDOW, WINDOW[1]),
        (None, WINDOW[1]),
        (WINDOW[0], True),
        (0, WINDOW[1]),
        ("invalid", WINDOW[1]),
        ("2026-10-20T12:00:00", WINDOW[1]),
        (WINDOW[0], "2026-10-20T12:00:20"),
        (WINDOW[1], WINDOW[0]),
    ],
)
def test_posting_window_requires_exact_aware_chronological_pair(
    inputs: Inputs, window: Any
) -> None:
    with pytest.raises(GradebookError, match="COMMENT_POSTING_WINDOW_INVALID"):
        compare_posting(inputs, posting_pair(inputs), window=window)


@pytest.mark.parametrize(
    "posted,verified",
    [
        ("2026-10-20T11:59:55Z", True),
        ("2026-10-20T11:59:54.999Z", False),
        ("2026-10-20T12:00:25Z", True),
        ("2026-10-20T12:00:25.001Z", False),
        ("2026-10-20T08:00:10-04:00", True),
        ("2026-10-20T12:00:10", False),
        ("invalid", False),
        (True, False),
        (100, False),
    ],
)
def test_posting_timestamp_has_only_five_seconds_of_clock_skew(
    inputs: Inputs, posted: Any, verified: bool
) -> None:
    result = compare_posting(inputs, posting_pair(inputs, posted))
    assert result.stored_verified is verified


@pytest.mark.parametrize(
    "scope,field,value",
    [
        ("assignment", "post_manually", True),
        ("assignment", "post_manually", None),
        ("assignment", "post_manually", 0),
        ("assignment", "post_manually", ABSENT),
        ("initial", "posted_at", "2026-09-17T20:00:00Z"),
        ("initial", "posted_at", ABSENT),
        ("final", "posted_at", ABSENT),
        ("initial", "updated_at", None),
        ("initial", "updated_at", ABSENT),
        ("initial", "updated_at", True),
        ("initial", "updated_at", "2026-09-17T20:00:00"),
        ("final", "updated_at", None),
        ("final", "updated_at", ABSENT),
        ("final", "updated_at", True),
        ("final", "updated_at", "2026-09-17T20:00:01Z"),
        ("final", "score", 1),
        ("final", "excused", True),
        ("final", "attempt", 1),
        ("final", "points_deducted", 1),
        ("final", "late_policy_status", "late"),
        ("final", "extra_metadata", "changed"),
    ],
)
def test_posting_fallback_preserves_policy_presence_update_and_other_fields(
    inputs: Inputs, scope: str, field: str, value: Any
) -> None:
    pair = posting_pair(inputs)
    record = pair[{"assignment": 0, "initial": 1, "final": 2}[scope]]
    if value is ABSENT:
        record.pop(field, None)
    else:
        record[field] = value
    result = compare_posting(inputs, pair)
    assert not result.stored_verified and result.outcome in {"CONFLICT", "HELD"}


@pytest.mark.parametrize(
    "variant",
    [
        "wrong-response",
        "wrong-body",
        "wrong-author",
        "no-new-comment",
        "duplicate",
        "old-comment-drift",
    ],
)
def test_posting_fallback_preserves_exact_comment_and_response_evidence(
    inputs: Inputs, variant: str
) -> None:
    pair = posting_pair(inputs)
    comments = pair[2]["submission_comments"]
    if variant == "wrong-body":
        comments[-1]["comment"] += " changed"
    elif variant == "wrong-author":
        comments[-1]["author_id"] = 777
    elif variant == "no-new-comment":
        comments.pop()
    elif variant == "duplicate":
        comments.append({**comments[-1], "id": 503})
    elif variant == "old-comment-drift":
        comments[0]["comment"] += " changed"
    result = compare_posting(
        inputs,
        pair,
        response_comment_id="999" if variant == "wrong-response" else "502",
    )
    assert not result.stored_verified
    assert result.outcome in {"CONFLICT", "UNCERTAIN"}
