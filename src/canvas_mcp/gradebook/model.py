"""Deterministic snapshot and three-way grade comparison; no I/O or writes."""

from __future__ import annotations

import hashlib
import json
import math
from collections import Counter
from datetime import UTC, datetime
from typing import Any

from .client import GradebookError


def digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            value, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode()
    ).hexdigest()


def identifier(value: Any) -> str:
    result = str(value)
    if not result.isascii() or not result.isdecimal() or int(result) < 1:
        raise GradebookError("Missing or invalid Canvas identity.")
    return result


def grade_value(value: Any) -> float | str | None:
    if value is None or value == "":
        return None
    if isinstance(value, str) and value.strip().lower() in ("ex", "excused"):
        return "EX"
    if isinstance(value, bool):
        raise GradebookError("A grade cannot be a checkbox value.")
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise GradebookError("Grade must be numeric, blank, or EX.") from exc
    if not math.isfinite(result) or result < 0:
        raise GradebookError("Grade must be finite and nonnegative.")
    return result


def normalize_snapshot(
    origin: str,
    course: dict[str, Any],
    sections: list[dict[str, Any]],
    enrollments: list[dict[str, Any]],
    assignments: list[dict[str, Any]],
    submissions: list[dict[str, Any]],
) -> dict[str, Any]:
    section_names = {identifier(s["id"]): str(s.get("name", "")) for s in sections}
    students: dict[str, dict[str, Any]] = {}
    for enrollment in enrollments:
        if (
            enrollment.get("type") != "StudentEnrollment"
            or enrollment.get("enrollment_state") != "active"
        ):
            continue
        uid = identifier(enrollment.get("user_id"))
        user = enrollment.get("user") or {}
        if identifier(user.get("id")) != uid:
            raise GradebookError("Enrollment identity mismatch.")
        row = students.setdefault(
            uid,
            {
                "id": uid,
                "name": str(user.get("name", "")),
                "sort_name": str(user.get("sortable_name") or user.get("name", "")),
                "sections": [],
            },
        )
        section = section_names.get(str(enrollment.get("course_section_id")), "")
        if section and section not in row["sections"]:
            row["sections"].append(section)
    roster = sorted(
        students.values(), key=lambda r: (r["sort_name"].casefold(), r["id"])
    )
    for row in roster:
        row["sections"].sort()
    columns: list[dict[str, Any]] = []
    assignment_ids: set[str] = set()
    for assignment in assignments:
        if (
            assignment.get("published") is not True
            or assignment.get("grading_type") == "not_graded"
        ):
            continue
        aid = identifier(assignment.get("id"))
        if aid in assignment_ids:
            raise GradebookError("Duplicate Canvas assignment in snapshot.")
        assignment_ids.add(aid)
        columns.append(
            {
                "id": aid,
                "name": str(assignment.get("name", "")),
                "points_possible": assignment.get("points_possible"),
                "grading_type": assignment.get("grading_type"),
                "position": assignment.get("position", 0),
                "due_at": assignment.get("due_at"),
                "html_url": f"{origin}/courses/{course['id']}/assignments/{aid}",
                "omit_from_final_grade": assignment.get("omit_from_final_grade", False),
            }
        )
    columns.sort(key=lambda a: (a["position"] or 0, int(a["id"])))
    cells: dict[str, dict[str, Any]] = {}
    for submission in submissions:
        uid, aid = str(submission.get("user_id")), str(submission.get("assignment_id"))
        if uid not in students or aid not in assignment_ids:
            continue
        key = f"{uid}:{aid}"
        if key in cells:
            raise GradebookError("Duplicate Canvas submission in snapshot.")
        cells[key] = submission_cell(submission)
    return {
        "schema_version": 1,
        "origin": origin,
        "course_id": identifier(course["id"]),
        "course_name": str(course.get("name", "")),
        "course_workflow_state": course.get("workflow_state"),
        "fetched_at": datetime.now(UTC).isoformat(),
        "scope": "Active student enrollments; published graded assignments",
        "students": roster,
        "assignments": columns,
        "cells": cells,
    }


def submission_cell(submission: dict[str, Any]) -> dict[str, Any]:
    score = submission.get("score")
    if score is not None and (
        isinstance(score, bool)
        or not isinstance(score, (int, float))
        or not math.isfinite(score)
    ):
        raise GradebookError("Canvas returned a nonnumeric score.")
    return {
        "value": "EX" if submission.get("excused") is True else score,
        "grade": submission.get("grade"),
        "excused": submission.get("excused") is True,
        "missing": submission.get("missing") is True,
        "late": submission.get("late") is True,
        "visible": submission.get("assignment_visible"),
        "workflow_state": submission.get("workflow_state"),
        "attempt": submission.get("attempt"),
        "submitted_at": submission.get("submitted_at"),
        "graded_at": submission.get("graded_at"),
        "posted_at": submission.get("posted_at"),
        "grade_matches_current_submission": submission.get(
            "grade_matches_current_submission"
        ),
        "late_policy_status": submission.get("late_policy_status"),
        "points_deducted": submission.get("points_deducted"),
    }


def summary(snapshot: dict[str, Any]) -> dict[str, Any]:
    cells = list(snapshot["cells"].values())
    return {
        "course_id": snapshot["course_id"],
        "fetched_at": snapshot["fetched_at"],
        "students": len(snapshot["students"]),
        "assignments": len(snapshot["assignments"]),
        "recorded_cells": len(cells),
        "numeric_scores": sum(isinstance(c["value"], (int, float)) for c in cells),
        "excused": sum(c["excused"] for c in cells),
        "missing": sum(c["missing"] for c in cells),
        "late": sum(c["late"] for c in cells),
    }


def compare_edits(
    baseline: dict[str, Any], current: dict[str, Any], envelope: dict[str, Any]
) -> dict[str, Any]:
    """Build a review only. Blank edits never silently clear or zero grades."""
    if (baseline["course_id"], baseline["origin"]) != (
        current["course_id"],
        current["origin"],
    ):
        raise GradebookError("Snapshot course or Canvas origin changed.")
    if envelope.get("course_id") != baseline["course_id"] or envelope.get(
        "snapshot_id"
    ) != digest(baseline):
        raise GradebookError("Edits do not belong to this course and baseline.")
    edits = envelope.get("edits")
    if not isinstance(edits, list) or len(edits) > 10000:
        raise GradebookError("Invalid edit list or more than 10,000 edits.")
    assignments = {a["id"]: a for a in current["assignments"]}
    old_assignments = {a["id"]: a for a in baseline["assignments"]}
    roster = {s["id"] for s in current["students"]}
    old_roster = {s["id"] for s in baseline["students"]}
    seen: set[str] = set()
    changes = []
    for edit in edits:
        if not isinstance(edit, dict) or set(edit) != {
            "user_id",
            "assignment_id",
            "value",
        }:
            raise GradebookError("Invalid edit record.")
        uid, aid = identifier(edit["user_id"]), identifier(edit["assignment_id"])
        key = f"{uid}:{aid}"
        if key in seen:
            raise GradebookError("Duplicate edit target.")
        seen.add(key)
        proposed = grade_value(edit["value"])
        before = baseline["cells"].get(key)
        now = current["cells"].get(key)
        reasons = []
        if (
            uid not in roster
            or uid not in old_roster
            or aid not in assignments
            or aid not in old_assignments
        ):
            reasons.append("target_not_in_both_snapshots")
        elif before is None or now is None or now.get("visible") is False:
            reasons.append("submission_not_verified")
        elif proposed == before["value"]:
            continue  # No local edit: the current Canvas value wins on refresh.
        elif proposed == now["value"]:
            # A confirmed push or another authorized grader already achieved
            # the proposed value. Rebase this cell without another write.
            continue
        else:
            if before != now:
                reasons.append("canvas_changed_since_baseline")
            old, new = old_assignments[aid], assignments[aid]
            if (old["points_possible"], old["grading_type"]) != (
                new["points_possible"],
                new["grading_type"],
            ):
                reasons.append("assignment_grading_changed")
            if new["grading_type"] != "points":
                reasons.append("non_points_assignment_requires_review")
            if proposed is None:
                reasons.append("blank_does_not_clear_grade")
            if before["value"] == "EX" and proposed != "EX":
                reasons.append("removes_excusal")
            if isinstance(proposed, (int, float)):
                if isinstance(now["value"], (int, float)) and proposed < now["value"]:
                    reasons.append("decreases_grade")
                maximum = new["points_possible"]
                if maximum is None or proposed > maximum:
                    reasons.append("points_possible_requires_review")
                if now.get("points_deducted"):
                    reasons.append("late_policy_requires_review")
        changes.append(
            {
                "user_id": uid,
                "assignment_id": aid,
                "baseline": before["value"] if before else None,
                "current": now["value"] if now else None,
                "proposed": proposed,
                "status": "review_required" if reasons else "ready_for_review",
                "reasons": reasons,
            }
        )
    return {
        "schema_version": 1,
        "course_id": baseline["course_id"],
        "baseline_id": digest(baseline),
        "current_id": digest(current),
        "created_at": datetime.now(UTC).isoformat(),
        "changes": changes,
        "counts": dict(Counter(c["status"] for c in changes)),
        "canvas_writes": 0,
    }
