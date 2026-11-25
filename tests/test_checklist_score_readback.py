"""Fictional independent reads for an already-posted paper checklist score."""

from copy import deepcopy
from typing import Any

import pytest

from canvas_mcp.gradebook.checklist_score_readback import (
    validate_checklist_score_readback,
)
from canvas_mcp.gradebook.client import GradebookError

ORIGIN = "https://canvas.example.test"
TARGET = {"course_id": "2", "assignment_id": "3", "user_id": "4", "points": 5}
BASE = ORIGIN + "/courses/2/assignments/3/submissions/4?preview=1&version="


def observations() -> tuple[dict[str, Any], dict[str, Any]]:
    entry = {
        "assignment_id": 3,
        "user_id": 4,
        "preview_url": BASE + "7",
        "score": 0,
        "grade": "0",
        "entered_score": 0,
        "entered_grade": "0",
        "posted_at": "2026-01-02T12:00:00Z",
        "grader_id": 6,
        "attempt": None,
        "submitted_at": None,
        "workflow_state": "graded",
        "seconds_late": 60,
        "cached_due_date": "2026-01-02T11:59:00Z",
    }
    before = {
        "window": [100, 101],
        "sections": ["9"],
        "actor": "8",
        "assignment": {
            "id": 3,
            "course_id": 2,
            "published": True,
            "points_possible": 5,
        },
        "submission": {
            **entry,
            "submission_history": [entry.copy()],
            "submission_comments": [],
        },
    }
    after = deepcopy(before)
    after["window"] = [110, 111]
    sub = after["submission"]
    for row in [sub, *sub["submission_history"]]:
        row.update(
            preview_url=BASE + "8",
            score=5,
            grade="5",
            entered_score=5,
            entered_grade="5",
            grader_id=8,
            seconds_late=70,
        )
    return before, after


def urls(observation: dict[str, Any], url: str) -> None:
    sub = observation["submission"]
    for row in [sub, *sub["submission_history"]]:
        row["preview_url"] = url


@pytest.mark.parametrize(("suffix", "verdict"), [("7", "unchanged"), ("8", "advanced")])
def test_exact_same_target_can_stay_or_advance_once(suffix: str, verdict: str) -> None:
    before, after = observations()
    urls(after, BASE + suffix)
    assert validate_checklist_score_readback(before, after, TARGET, origin=ORIGIN) == (
        "preview_version_" + verdict
    )


@pytest.mark.parametrize(
    "url",
    [
        BASE + "6",
        BASE + "9",
        BASE + "08",
        BASE + "８",
        BASE + "8&extra=1",
        BASE + "8#",
        BASE.replace("preview=1&version=", "version=8&preview=") + "1",
        BASE.replace("https://", "http://") + "8",
        BASE.replace("canvas.", "other.") + "8",
        BASE.replace(".test", ".test:443") + "8",
        BASE.replace("canvas.", "actor@canvas.") + "8",
        BASE.replace("/2/", "/22/") + "8",
        BASE.replace("/3/", "/33/") + "8",
        BASE.replace("/4?", "/44?") + "8",
        BASE + "%38",
    ],
)
def test_different_target_or_version_is_held(url: str) -> None:
    before, after = observations()
    urls(after, url)
    with pytest.raises(GradebookError):
        validate_checklist_score_readback(before, after, TARGET, origin=ORIGIN)


@pytest.mark.parametrize("side", [0, 1])
@pytest.mark.parametrize(
    ("where", "field", "value"),
    [
        ("top", "user_id", "12"),
        ("history", "assignment_id", "13"),
        ("history", "preview_url", None),
        ("top", "submission_history", []),
        ("assignment", "course_id", "20"),
    ],
)
def test_each_observation_binds_course_assignment_and_history(
    side: int, where: str, field: str, value: Any
) -> None:
    pair = observations()
    obs = pair[side]
    entry = obs["submission"]
    if where == "assignment":
        entry = obs["assignment"]
    elif where == "history":
        entry = entry["submission_history"][0]
    entry[field] = value
    with pytest.raises(GradebookError):
        validate_checklist_score_readback(*pair, TARGET, origin=ORIGIN)


@pytest.mark.parametrize(
    ("where", "field", "value"),
    [
        ("top", "graded_actor", "new"),
        ("top", "posted_at", "changed"),
        ("top", "submission_comments", [{"comment": "different"}]),
        ("top", "grader_id", 99),
        ("top", "grade", "4"),
        ("top", "score", True),
        ("history", "seconds_late", 80),
        ("history", "attempt", 1),
        ("history", "posted_at", None),
        ("assignment", "published", False),
        ("observation", "sections", ["99"]),
        ("observation", "window", [90, 91]),
    ],
)
def test_preview_advance_does_not_clear_other_drift(
    where: str, field: str, value: Any
) -> None:
    before, after = observations()
    entry = {
        "top": after["submission"],
        "history": after["submission"]["submission_history"][0],
        "assignment": after["assignment"],
        "observation": after,
    }[where]
    entry[field] = value
    with pytest.raises(GradebookError):
        validate_checklist_score_readback(before, after, TARGET, origin=ORIGIN)


def test_every_history_entry_is_protected() -> None:
    before, after = observations()
    for obs in (before, after):
        history = obs["submission"]["submission_history"]
        history.append(deepcopy(history[0]))
    after["submission"]["submission_history"][1]["grader_id"] = "18"
    with pytest.raises(GradebookError):
        validate_checklist_score_readback(before, after, TARGET, origin=ORIGIN)


@pytest.mark.parametrize(
    "origin", ["http://canvas.example.test", ORIGIN + "/path", ORIGIN + "?"]
)
def test_a_malformed_configured_origin_does_not_validate_even_matching_links(
    origin: str,
) -> None:
    before, after = observations()
    for obs in (before, after):
        urls(obs, obs["submission"]["preview_url"].replace(ORIGIN, origin))
    with pytest.raises(GradebookError):
        validate_checklist_score_readback(before, after, TARGET, origin=origin)
