"""Privacy-safe mapped-axis coverage; this does not classify grade proposals."""

from typing import Any

from .client import GradebookError
from .model import identifier

WARNING = (
    "EDIT coverage differs from fresh Canvas. Fresh GET preserves EDIT axes. "
    "Resolve removed targets and use a separately reviewed append plan for "
    "added targets; this review does not add coverage or authorize publication."
)


def coverage_summary(baseline: dict[str, Any], current: dict[str, Any]) -> dict[str, Any]:
    """Count exact populated identity keys, never worksheet dimensions or grades."""
    try:
        if (baseline["course_id"], baseline["origin"]) != (
            current["course_id"], current["origin"]
        ):
            raise ValueError
        axes = []
        for snapshot in (baseline, current):
            if type(snapshot["schema_version"]) is not int or snapshot["schema_version"] != 1:
                raise ValueError
            selected = []
            for key in ("students", "assignments"):
                if not isinstance(snapshot[key], list):
                    raise ValueError
                ids = []
                for item in snapshot[key]:
                    if not isinstance(item, dict) or type(item.get("id")) is not str:
                        raise ValueError
                    ids.append(identifier(item["id"]))
                if len(ids) != len(set(ids)):
                    raise ValueError
                selected.append(set(ids))
            axes.append(selected)
        (old_students, old_assignments), (fresh_students, fresh_assignments) = axes
        shared_targets = len(old_students & fresh_students) * len(
            old_assignments & fresh_assignments
        )
        differs = old_students != fresh_students or old_assignments != fresh_assignments
        return {
            "edit_students": len(old_students),
            "edit_assignments": len(old_assignments),
            "canvas_students": len(fresh_students),
            "canvas_assignments": len(fresh_assignments),
            "added_students": len(fresh_students - old_students),
            "removed_students": len(old_students - fresh_students),
            "added_assignments": len(fresh_assignments - old_assignments),
            "removed_assignments": len(old_assignments - fresh_assignments),
            "mapped_edit_targets": len(old_students) * len(old_assignments),
            "missing_edit_targets": len(fresh_students) * len(fresh_assignments) - shared_targets,
            "edit_targets_removed_from_canvas": len(old_students) * len(old_assignments) - shared_targets,
            "matches_canvas_axes": not differs,
            "warning": WARNING if differs else None,
        }
    except (KeyError, TypeError, ValueError, GradebookError) as exc:
        raise GradebookError("Native review coverage identities are invalid.") from exc
