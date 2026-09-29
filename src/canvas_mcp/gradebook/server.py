"""Separate local MCP service with private artifacts and aggregate responses."""

from datetime import UTC, datetime
from typing import Any

from fastmcp import FastMCP
from mcp.types import ToolAnnotations

from .client import GradebookClient, GradebookError
from .ledger import Ledger
from .model import compare_edits, summary
from .publish import Publisher, write_review_html
from .refresh import (
    source_digest,
    verify_refresh_output,
)
from .service import prepare_refresh
from .store import Store
from .workbook import read_workbook_cells


def create_server(
    client: GradebookClient,
    store: Store,
    courses: dict[str, str],
    bindings: dict[str, Any] | None = None,
    enable_push: bool = False,
) -> FastMCP:
    server = FastMCP("canvas-gradebook")
    publisher = Publisher(client, store, Ledger(store.root))

    def resolve(course: str) -> str:
        if course not in courses:
            raise GradebookError("Choose a configured class: " + ", ".join(courses))
        return courses[course]

    @server.tool(annotations=ToolAnnotations(read_only_hint=True))
    async def get_canvas_gradebook(course: str) -> dict[str, Any]:
        """Fetch a complete gradebook for core or advanced into a private local file.

        Returns aggregate counts and snapshot reference only. Never read the raw
        artifact into chat: it contains student records. No Canvas writes.
        """
        try:
            snapshot = await client.snapshot(resolve(course))
            artifact_id, path = store.save("snapshot", snapshot)
            return {
                **summary(snapshot),
                "snapshot_id": artifact_id,
                "local_file": str(path),
                "canvas_writes": 0,
            }
        except GradebookError as exc:
            return {"error": str(exc), "canvas_writes": 0}
        except Exception:
            return {
                "error": "Snapshot failed; no partial snapshot was accepted.",
                "canvas_writes": 0,
            }

    @server.tool(annotations=ToolAnnotations(read_only_hint=True))
    async def preview_gradebook_changes(
        course: str, snapshot_id: str, edits_filename: str
    ) -> dict[str, Any]:
        """Compare a private inbox edit file against its baseline and fresh Canvas.

        Produces a local review artifact, never grades students. Accepts a
        downloaded gradebook .xlsx or a JSON edit file in the local inbox.
        Blank, decreased, excused, stale and non-points edits require review.
        """
        try:
            course_id = resolve(course)
            baseline = store.load("snapshot", snapshot_id)
            if (
                baseline["course_id"] != course_id
                or baseline["origin"] != client.origin
            ):
                raise GradebookError(
                    "Baseline belongs to a different course or Canvas origin."
                )
            tab_names = (bindings or {}).get(course, {}).get("tab_names")
            edits = store.read_edits(edits_filename, baseline, tab_names)
            current = await client.snapshot(course_id)
            review = compare_edits(baseline, current, edits)
            store.save("snapshot", current)
            review_id, path = store.save("review", review)
            return {
                "review_id": review_id,
                "local_file": str(path),
                "review_file": write_review_html(store, review),
                "changes": len(review["changes"]),
                "counts": review["counts"],
                "canvas_writes": 0,
                "publishing_available": enable_push,
            }
        except GradebookError as exc:
            return {"error": str(exc), "canvas_writes": 0}
        except Exception:
            return {
                "error": "Review failed; no Canvas changes were made.",
                "canvas_writes": 0,
            }

    if bindings:

        @server.tool(annotations=ToolAnnotations(read_only_hint=True))
        async def prepare_gradebook_refresh(
            course: str, snapshot_id: str, workbook_filename: str
        ) -> dict[str, Any]:
            """Prepare a private Sheets batch, preserving pending edits by ID.

            First export the configured Google workbook to the private inbox.
            This tool fetches Canvas and creates a plan; it changes neither
            Sheets nor Canvas. Keep editing paused during refresh. Export again
            and call verify_gradebook_refresh(phase='before') immediately before
            sending the private plan's batch_update through Google Drive. Then
            export the result and verify with phase='after'. Never print rows.
            """
            try:
                course_id = resolve(course)
                binding = bindings[course]
                if binding["course_id"] != course_id:
                    raise GradebookError("Workbook binding does not match the course.")
                sheets = read_workbook_cells(
                    store.inbox_file(workbook_filename), binding.get("tab_names")
                )
                if sheets["_Sync"].get("B2") != snapshot_id:
                    raise GradebookError("Baseline does not match the workbook reference.")
                plan = await prepare_refresh(client, store, course, binding, sheets)
                plan_id, path = plan["refresh_id"], plan["local_file"]
                merged_id, current_id = plan["baseline_id"], plan["canvas_snapshot_id"]
                pending = plan["pending_edits"]
                return {
                    "refresh_id": plan_id,
                    "local_file": str(path),
                    "baseline_id": merged_id,
                    "canvas_snapshot_id": current_id,
                    "pending_changes": len(pending),
                    "review_counts": plan["review_counts"],
                    "canvas_writes": 0,
                    "sheets_writes": 0,
                }
            except GradebookError as exc:
                return {"error": str(exc), "canvas_writes": 0, "sheets_writes": 0}
            except Exception:
                return {
                    "error": "Refresh preparation failed; existing workbook retained.",
                    "canvas_writes": 0,
                    "sheets_writes": 0,
                }

        @server.tool(annotations=ToolAnnotations(read_only_hint=True))
        async def verify_gradebook_refresh(
            course: str, refresh_id: str, workbook_filename: str, phase: str
        ) -> dict[str, Any]:
            """Check a new workbook export immediately before or after a refresh.

            phase='before' detects edits since preparation and expires in five
            minutes. Google Sheets has no compare-and-swap transaction across
            export and batchUpdate: do not edit while applying the batch.
            phase='after' checks all Canvas and Working values and saves a
            receipt. A failed readback requires reconciliation, never a blind
            retry of an older batch. Neither phase writes Google or Canvas.
            """
            try:
                plan = store.load("refresh", refresh_id)
                if (plan["course_id"], plan["origin"]) != (
                    resolve(course),
                    client.origin,
                ):
                    raise GradebookError(
                        "Refresh belongs to a different course or origin."
                    )
                if (
                    plan["batch_update"]["spreadsheet_id"]
                    != bindings[course]["spreadsheet_id"]
                ):
                    raise GradebookError("Workbook binding changed.")
                sheets = read_workbook_cells(
                    store.inbox_file(workbook_filename), bindings[course].get("tab_names")
                )
                if phase == "before":
                    age = (
                        datetime.now(UTC) - datetime.fromisoformat(plan["created_at"])
                    ).total_seconds()
                    if not 0 <= age <= 300:
                        raise GradebookError(
                            "Refresh plan expired; prepare a fresh plan."
                        )
                    if source_digest(sheets) != plan["input_digest"]:
                        raise GradebookError(
                            "Workbook changed since preparation; refresh held."
                        )
                    return {
                        "ready_to_apply": True,
                        "refresh_id": refresh_id,
                        "canvas_writes": 0,
                        "sheets_writes": 0,
                    }
                if phase != "after":
                    raise GradebookError("Phase must be before or after.")
                verify_refresh_output(
                    sheets,
                    plan,
                    store.load("snapshot", plan["canvas_snapshot_id"]),
                    store.load("snapshot", plan["baseline_id"]),
                )
                receipt_id, _ = store.save(
                    "receipt",
                    {
                        "refresh_id": refresh_id,
                        "verified_at": datetime.now(UTC).isoformat(),
                        "output_digest": source_digest(sheets),
                        "status": "verified",
                    },
                )
                return {
                    "verified": True,
                    "receipt_id": receipt_id,
                    "baseline_id": plan["baseline_id"],
                    "pending_changes": len(plan["pending_edits"]),
                    "canvas_writes": 0,
                }
            except GradebookError as exc:
                return {"error": str(exc), "canvas_writes": 0}
            except Exception:
                return {
                    "error": "Refresh verification failed; retain both exports for reconciliation.",
                    "canvas_writes": 0,
                }

    @server.tool(annotations=ToolAnnotations(read_only_hint=True))
    async def prepare_gradebook_push(course: str, review_id: str) -> dict[str, Any]:
        """Prepare an exact private teacher review and a ten-minute confirmation.

        Rechecks Canvas, holds unsafe/conflicting changes, and limits a push to
        25 cells. No grades are sent. Open the private review for the teacher;
        never paste student rows into chat. Building or syncing the connector
        does not approve an individual grade plan.
        """
        try:
            return {
                **await publisher.prepare(resolve(course), review_id),
                "publishing_available": enable_push,
            }
        except GradebookError as exc:
            return {"error": str(exc), "canvas_writes": 0}
        except Exception:
            return {
                "error": "Push preparation failed; no Canvas changes were made.",
                "canvas_writes": 0,
            }

    @server.tool(annotations=ToolAnnotations(read_only_hint=True))
    async def get_gradebook_push_status(
        course: str, operation_id: str
    ) -> dict[str, Any]:
        """Read aggregate durable push status. Never retries a grade request."""
        try:
            operation = publisher.ledger.operation(operation_id)
            plan = store.load("push", operation["plan_id"])
            if (plan["course_id"], plan["origin"]) != (resolve(course), client.origin):
                raise GradebookError("Push belongs to a different course or origin.")
            return publisher.ledger.summary(operation_id)
        except GradebookError as exc:
            return {"error": str(exc)}
        except Exception:
            return {"error": "Push status unavailable; do not retry writes."}

    @server.tool(annotations=ToolAnnotations(read_only_hint=True))
    async def reconcile_gradebook_push(
        course: str, operation_id: str
    ) -> dict[str, Any]:
        """Read Canvas after an uncertain request; never send or repeat grades.

        A matching value is recorded as observed_applied, not proof of which
        actor wrote it. Unresolved targets retain their lock against new pushes.
        """
        try:
            return await publisher.reconcile(resolve(course), operation_id)
        except GradebookError as exc:
            return {"error": str(exc), "retry_writes": False}
        except Exception:
            return {
                "error": "Reconciliation unavailable; retain the operation and do not retry writes.",
                "retry_writes": False,
            }

    if enable_push:

        @server.tool(
            annotations=ToolAnnotations(
                read_only_hint=False, destructive_hint=True, idempotent_hint=False
            )
        )
        async def confirm_gradebook_push(
            course: str, operation_id: str, confirmation_token: str
        ) -> dict[str, Any]:
            """Send only the exact teacher-approved plan using its one-use token.

            Requires approval of this operation's private preview. Canvas's
            posting policy may make grades visible. Partial failure stops the
            batch; use status/reconcile, never resend an uncertain request.
            No messages or comments are sent.
            """
            try:
                return await publisher.confirm(
                    resolve(course), operation_id, confirmation_token
                )
            except GradebookError as exc:
                return {
                    "error": str(exc),
                    "operation_id": operation_id,
                    "retry_writes": False,
                }
            except Exception:
                return {
                    "error": "Push stopped; read its durable status before any further action.",
                    "operation_id": operation_id,
                    "retry_writes": False,
                }

    return server
