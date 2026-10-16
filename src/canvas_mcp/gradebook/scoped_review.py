"""Small private review scopes; held proposals remain in their parent review."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from .client import GradebookError
from .model import compare_edits, digest
from .publish import write_review_html
from .store import Store


def select_ready_batch(
    store: Store, course_id: str, origin: str, review_id: str, batch_index: int = 0
) -> dict[str, Any]:
    if type(batch_index) is not int or batch_index < 0:
        raise GradebookError("Review batch index must be a nonnegative integer.")
    parent = store.load("review", review_id)
    if "unit1_pair_score_intent" in parent:
        raise GradebookError("Source-owned intents already have their exact approved batch.")
    required = {"schema_version", "course_id", "baseline_id", "current_id",
                "created_at", "changes", "counts", "canvas_writes"}
    if (not required.issubset(parent) or type(parent.get("schema_version")) is not int
            or parent["schema_version"] != 1 or parent["course_id"] != course_id
            or type(parent.get("canvas_writes")) is not int or parent["canvas_writes"] != 0
            or not isinstance(parent.get("changes"), list) or len(parent["changes"]) > 10_000
            or not isinstance(parent.get("counts"), dict)
            or any(not isinstance(c, dict) or not {"user_id", "assignment_id", "proposed"}.issubset(c)
                   for c in parent["changes"])):
        raise GradebookError("Parent review metadata differs from its read-only scope.")
    try:
        created_at = datetime.fromisoformat(parent["created_at"])
    except (TypeError, ValueError) as exc:
        raise GradebookError("Parent review source time is invalid.") from exc
    if (created_at.tzinfo is None
            or (datetime.now(UTC) - created_at).total_seconds() < -30):
        raise GradebookError("Parent review source time is invalid.")
    baseline = store.load("snapshot", parent["baseline_id"])
    current = store.load("snapshot", parent["current_id"])
    if any(
        (s.get("course_id"), s.get("origin")) != (course_id, origin)
        for s in (baseline, current)
    ):
        raise GradebookError("Review batch course or origin differs.")
    envelope = {
        "course_id": course_id,
        "snapshot_id": digest(baseline),
        "edits": [
            {
                "user_id": c["user_id"],
                "assignment_id": c["assignment_id"],
                "value": c["proposed"],
            }
            for c in parent["changes"]
        ],
    }
    checked = compare_edits(baseline, current, envelope)
    if parent["changes"] != checked["changes"] or parent["counts"] != checked["counts"]:
        raise GradebookError(
            "Parent review classification differs from its captured evidence."
        )
    ready = [
        c
        for c in checked["changes"]
        if c["status"] == "ready_for_review" and c["reasons"] == []
    ]
    selected = ready[batch_index * 25 : (batch_index + 1) * 25]
    if not selected:
        raise GradebookError("This review has no ready rows in the requested batch.")
    child = {
        **{k: parent[k] for k in required - {"changes", "counts", "canvas_writes"}},
        "changes": selected,
        "counts": {"ready_for_review": len(selected)},
        "parent_review_id": review_id,
        "scope_method": "READY_ROWS_ONLY",
        "canvas_writes": 0,
        "teacher_approval": False,
    }
    pagination = {
        "remaining_ready": max(0, len(ready) - (batch_index + 1) * 25),
        "ready_before_batch": batch_index * 25,
        "unselected_ready": len(ready) - len(selected),
    }
    child_id, path = store.save("review", child)
    receipt_id, _ = store.save(
        "receipt",
        {
            "kind": "SCOPED_REVIEW",
            "parent_review_id": review_id,
            "child_review_id": child_id,
            "baseline_id": parent["baseline_id"],
            "current_id": parent["current_id"],
            "batch_index": batch_index,
            "selected": len(selected),
            "held_in_parent": checked["counts"].get("review_required", 0),
            **pagination,
            "canvas_writes": 0,
            "teacher_approval": False,
            "original_source_time_preserved": True,
        },
    )
    return {
        "review_id": child_id,
        "review_file": write_review_html(store, child),
        "local_file": str(path),
        "receipt_id": receipt_id,
        "selected": len(selected),
        "held_in_parent": checked["counts"].get("review_required", 0),
        **pagination,
        "canvas_writes": 0,
        "teacher_approval": False,
    }
