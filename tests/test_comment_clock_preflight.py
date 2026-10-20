"""Only the elapsed late clock may advance across an exact comment preview."""

import copy
import json
from datetime import UTC, datetime, timedelta

import pytest

from canvas_mcp.gradebook.client import GradebookError
from canvas_mcp.gradebook.publish import comment_clock_limit, comment_target_unchanged


def state(**fields):
    return {
        "assignment": {"url": "https://fictional.example/assignment", "body": '{"id":1}'},
        "submission": {
            "url": "https://fictional.example/submission",
            "coverage_complete": True,
            "body": json.dumps({"score": 10, "grade": "10", "late": True, **fields}),
        },
    }


def test_only_elapsed_clock_advances_without_rewriting_observations():
    before, after = state(seconds_late=100), state(seconds_late=130)
    retained = copy.deepcopy((before, after))
    assert comment_target_unchanged(before, after, max_clock_advance_seconds=30)
    assert (before, after) == retained
    assert not comment_target_unchanged(before, after, max_clock_advance_seconds=29)


@pytest.mark.parametrize("value", [99, True, 101.0, None, -1, "101"])
def test_counter_type_or_reverse_change_is_held(value):
    assert not comment_target_unchanged(
        state(seconds_late=100), state(seconds_late=value), max_clock_advance_seconds=5
    )


@pytest.mark.parametrize("value", [True, 1.0, -1, "1"])
def test_invalid_unchanged_counter_is_held_before_send(value):
    assert not comment_target_unchanged(
        state(seconds_late=value), state(seconds_late=value), max_clock_advance_seconds=5
    )


def test_presence_null_and_all_other_values_remain_exact():
    assert comment_target_unchanged(state(), state(), max_clock_advance_seconds=5)
    assert comment_target_unchanged(
        state(seconds_late=None), state(seconds_late=None), max_clock_advance_seconds=5
    )
    assert not comment_target_unchanged(
        state(), state(seconds_late=None), max_clock_advance_seconds=5
    )
    for field, value in [("score", 11), ("grade", "11"), ("late", 1), ("new_field", False)]:
        assert not comment_target_unchanged(
            state(seconds_late=100), state(seconds_late=101, **{field: value}),
            max_clock_advance_seconds=5,
        )
    changed = state(seconds_late=101)
    changed["assignment"]["body"] = '{"id":2}'
    assert not comment_target_unchanged(state(seconds_late=100), changed, max_clock_advance_seconds=5)
    changed = state(seconds_late=101)
    changed["submission"]["coverage_complete"] = False
    assert not comment_target_unchanged(state(seconds_late=100), changed, max_clock_advance_seconds=5)


@pytest.mark.parametrize("value", [-1, True, 1.0])
def test_invalid_clock_bound_is_rejected(value):
    assert not comment_target_unchanged(state(), state(), max_clock_advance_seconds=value)


@pytest.mark.parametrize("value", ["not-a-date", "2026-01-01", None])
def test_invalid_observation_time_cannot_extend_a_preview(value):
    with pytest.raises(GradebookError, match="observation time"):
        comment_clock_limit(value)


def test_future_time_is_held_and_elapsed_time_has_only_five_seconds_skew():
    with pytest.raises(GradebookError, match="observation time"):
        comment_clock_limit((datetime.now(UTC) + timedelta(hours=1)).isoformat())
    limit = comment_clock_limit((datetime.now(UTC) - timedelta(seconds=30)).isoformat())
    assert 35 <= limit <= 36
