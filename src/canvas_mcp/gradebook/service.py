"""Shared refresh planning, with the same merge rules as the interactive MCP.

This service performs Canvas GETs and writes immutable private local artifacts.
It has no Google transport and imports no Canvas publisher.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from .client import GradebookClient, GradebookError
from .model import digest, identifier
from .refresh import build_requests, merge_refresh, source_digest
from .store import Store
from .workbook import edits_from_cells


async def prepare_refresh(
    client: GradebookClient,
    store: Store,
    course: str,
    binding: dict[str, Any],
    cells: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    """Prepare one course; the caller applies neither course until both pass.

    ``cells`` are the three role-keyed literal-cell maps from a verified native
    read or the existing XLSX reader. B2 chooses the original trusted baseline,
    not a new snapshot, so pending proposals retain their conflict evidence.
    The returned refresh_id/local_file are handles; they are not part of the
    immutable plan stored under that refresh_id.
    """
    if not isinstance(course, str) or not course:
        raise GradebookError("Refresh course alias is invalid.")
    if set(cells) != {"Canvas", "Working", "_Sync"}:
        raise GradebookError("Refresh requires all three bound gradebook tabs.")
    course_id = identifier(binding.get("course_id"))
    snapshot_id = cells["_Sync"].get("B2")
    if not isinstance(snapshot_id, str):
        raise GradebookError(
            "The workbook's trusted baseline reference is unavailable."
        )
    baseline = store.load("snapshot", snapshot_id)
    if (baseline.get("course_id"), baseline.get("origin")) != (
        course_id,
        client.origin,
    ):
        raise GradebookError("Baseline does not match this course and origin.")
    edits = edits_from_cells(cells, baseline)
    current = await client.snapshot(course_id)
    if (current.get("course_id"), current.get("origin")) != (
        course_id,
        client.origin,
    ):
        raise GradebookError("Fresh snapshot does not match this course and origin.")
    merged, display, review = merge_refresh(baseline, current, edits)
    current_id, _ = store.save("snapshot", current)
    merged_id, _ = store.save("snapshot", merged)
    review_id, _ = store.save("review", review)
    pending = [
        {
            "user_id": c["user_id"],
            "assignment_id": c["assignment_id"],
            "value": c["proposed"],
        }
        for c in review["changes"]
    ]
    plan = {
        "schema_version": 1,
        "course": course,
        "course_id": course_id,
        "origin": client.origin,
        "created_at": datetime.now(UTC).isoformat(),
        "binding_digest": digest(binding),
        "input_digest": source_digest(cells),
        "previous_baseline_id": snapshot_id,
        "canvas_snapshot_id": current_id,
        "baseline_id": merged_id,
        "review_id": review_id,
        "pending_edits": pending,
        "review_counts": review["counts"],
        "batch_update": {
            "spreadsheet_id": binding["spreadsheet_id"],
            "requests": build_requests(
                current, display, merged_id, binding, baseline, len(pending)
            ),
        },
    }
    plan_id, path = store.save("refresh", plan)
    return {**plan, "refresh_id": plan_id, "local_file": str(path)}
