"""Compare independent Canvas observations of an approved posted checklist score.

The caller authenticates the teacher, section, assignment policy, approval and
native send receipt. This pure comparison neither sends a grade nor attributes
a write based on a matching score.
"""

from __future__ import annotations

import math
import re
from decimal import Decimal, InvalidOperation
from typing import Any, Literal
from urllib.parse import urlsplit

from .client import GradebookError
from .model import digest

PreviewTransition = Literal["preview_version_unchanged", "preview_version_advanced"]
_ID = re.compile(r"[1-9][0-9]*")
# These are the only fields permitted to vary in each raw submission record.
# Score, preview and elapsed clock fields have separate semantic checks below.
_SCORE_FIELDS = {
    "score",
    "grade",
    "entered_score",
    "entered_grade",
    "published_score",
    "published_grade",
}
_GRADE_METADATA = {"graded_at", "grader_id", "updated_at"}


def _require(ok: bool) -> None:
    if not ok:
        raise GradebookError(
            "Checklist score readback differs from the approved target."
        )


def _window(observation: dict[str, Any]) -> tuple[float, float]:
    start, end = observation["window"]
    _require(all(type(v) in (int, float) and math.isfinite(v) for v in (start, end)))
    _require(start <= end)
    return start, end


def _preview(
    observation: dict[str, Any], course: str, assignment: str, student: str, origin: str
) -> tuple[int, list[dict[str, Any]]]:
    binding = observation["assignment"]
    _require(str(binding["id"]) == assignment and str(binding["course_id"]) == course)
    submission = observation["submission"]
    history = submission["submission_history"]
    _require(isinstance(history, list) and bool(history))
    url = submission["preview_url"]
    prefix = f"{origin}/courses/{course}/assignments/{assignment}/submissions/{student}?preview=1&version="
    _require(isinstance(url, str) and url.startswith(prefix))
    version = url[len(prefix) :]
    _require(_ID.fullmatch(version) is not None)
    records = [submission, *history]
    for row in records:
        _require(
            isinstance(row, dict)
            and row["preview_url"] == url
            and str(row["assignment_id"]) == assignment
            and str(row["user_id"]) == student
            and row["attempt"] is None
            and row["submitted_at"] is None
        )
    return int(version), records


def _check_scores(record: dict[str, Any], points: int | float) -> None:
    _require(type(record["score"]) in (int, float) and record["score"] == points)
    _require(record["grade"] is not None)
    for field in _SCORE_FIELDS.intersection(record):
        value = record[field]
        _require(
            type(value) in (int, float, str)
            and Decimal(str(value)) == Decimal(str(points))
        )


def _check_elapsed(
    old: dict[str, Any], new: dict[str, Any], low: int, high: int
) -> None:
    _require(("seconds_late" in old) == ("seconds_late" in new))
    previous, current = old.get("seconds_late"), new.get("seconds_late")
    if digest(previous) == digest(current):
        return
    if type(previous) is not int or type(current) is not int:
        raise GradebookError("Checklist late clock does not match the read windows.")
    _require(0 <= previous <= current)
    _require(
        bool(old.get("cached_due_date"))
        and old.get("seconds_late_override") is None
        and new.get("seconds_late_override") is None
    )
    # The clock may have started at a due date between the two reads.
    _require((0 if previous == 0 else low) <= current - previous <= high)


def validate_checklist_score_readback(
    before: dict[str, Any],
    after: dict[str, Any],
    target: dict[str, Any],
    *,
    origin: str,
) -> PreviewTransition:
    """Verify a posted zero-to-full-credit change and return the preview transition.

    Compare one pre-send observation with the independent post-send readback
    using the trusted Canvas HTTPS origin. Each observation includes the raw
    assignment, submission, comments, history, teacher, sections and read window.
    The caller compares the same readback with both the original and final
    pre-send observations and requires the same preview transition from each.
    """
    try:
        parsed = urlsplit(origin)
        _require(
            bool(parsed.hostname)
            and parsed.scheme == "https"
            and parsed.username is None
            and parsed.password is None
            and origin == f"https://{parsed.netloc}"
            and not any(c.isspace() or ord(c) < 32 for c in origin)
        )
        course, assignment, student = (
            target[k] for k in ("course_id", "assignment_id", "user_id")
        )
        _require(
            all(
                isinstance(v, str) and _ID.fullmatch(v) is not None
                for v in (course, assignment, student)
            )
        )
        points = target["points"]
        _require(type(points) in (int, float) and math.isfinite(points) and points > 0)
        maximum = before["assignment"]["points_possible"]
        _require(
            type(maximum) in (int, float)
            and maximum == points
            and before["assignment"]["published"] is True
        )
        _require(digest(before["assignment"]) == digest(after["assignment"]))
        teacher = before["actor"]
        _require(
            isinstance(teacher, str)
            and _ID.fullmatch(teacher) is not None
            and after["actor"] == teacher
        )
        sections = before["sections"]
        _require(
            isinstance(sections, list)
            and bool(sections)
            and all(
                isinstance(s, str) and _ID.fullmatch(s) is not None for s in sections
            )
            and digest(sections) == digest(after["sections"])
        )
        start, end = _window(before)
        later_start, later_end = _window(after)
        _require(end <= later_start)
        low, high = math.floor(later_start - end), math.ceil(later_end - start)

        old_version, old_rows = _preview(before, course, assignment, student, origin)
        new_version, new_rows = _preview(after, course, assignment, student, origin)
        _require(
            new_version in (old_version, old_version + 1)
            and len(old_rows) == len(new_rows)
        )
        _require(isinstance(old_rows[0]["submission_comments"], list))
        _require(
            bool(old_rows[0]["posted_at"]) and old_rows[0]["workflow_state"] == "graded"
        )
        for index, (old, new) in enumerate(zip(old_rows, new_rows, strict=True)):
            _check_scores(old, 0)
            _check_scores(new, points)
            _require(str(new["grader_id"]) == teacher)
            _require((_SCORE_FIELDS & old.keys()) == (_SCORE_FIELDS & new.keys()))
            ignored = _SCORE_FIELDS | _GRADE_METADATA | {"preview_url", "seconds_late"}
            if index == 0:
                # The history is compared record by record in this same loop.
                ignored.add("submission_history")
            _require(
                digest({k: v for k, v in old.items() if k not in ignored})
                == digest({k: v for k, v in new.items() if k not in ignored})
            )
            _check_elapsed(old, new, low, high)
    except (
        AttributeError,
        InvalidOperation,
        KeyError,
        TypeError,
        ValueError,
        OverflowError,
    ):
        raise GradebookError(
            "Checklist score readback evidence is incomplete or invalid."
        ) from None
    return (
        "preview_version_unchanged"
        if new_version == old_version
        else "preview_version_advanced"
    )
