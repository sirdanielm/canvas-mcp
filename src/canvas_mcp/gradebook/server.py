"""Separate local MCP service with private artifacts and aggregate responses."""

import asyncio
from datetime import UTC, datetime
from typing import Any

from fastmcp import FastMCP
from fastmcp.server.middleware import Middleware
from mcp.types import ToolAnnotations

from .batch_publish import BatchPublisher
from .capture import save_capture
from .client import GradebookClient, GradebookError
from .ledger import Ledger
from .model import compare_edits, summary
from .publish import Publisher, write_review_html
from .refresh import (
    source_digest,
    verify_refresh_output,
)
from .runtime_diagnostics import capture_comment_runtime
from .service import prepare_refresh
from .store import Store
from .text_comments_mcp import QualifiedTextRelease, register_submission_comment_tools
from .workbook import read_workbook_cells


class CanonicalClientToolLock(Middleware):
    """Serialize same-server calls only when comment hooks share its client."""

    def __init__(self) -> None:
        self._lock = asyncio.Lock()

    async def on_call_tool(self, context: Any, call_next: Any) -> Any:
        async with self._lock:
            return await call_next(context)


def create_server(
    client: GradebookClient,
    store: Store,
    courses: dict[str, str],
    bindings: dict[str, Any] | None = None,
    enable_push: bool = False,
    enable_comments: bool = False,
    get_refresh_control: Any | None = None,
    unit1_score_handler_factory: Any | None = None,
    comment_releases: dict[str, QualifiedTextRelease] | None = None,
    comment_release_factory: Any | None = None,
    unit1_pair_score_handler_factory: Any | None = None,
    enable_qualified_comments: bool = False,
    source_score_scope: Any | None = None,
    comment_approval_seconds: int = 600,
    protected_score_scope: Any | None = None,
) -> FastMCP:
    server = FastMCP("canvas-gradebook")
    publisher_options = (
        {} if type(comment_approval_seconds) is int and comment_approval_seconds == 600
        else {"comment_approval_seconds": comment_approval_seconds}
    )
    publisher = Publisher(client, store, Ledger(store.root), **publisher_options)
    batches = BatchPublisher(publisher)
    comment_runtime = capture_comment_runtime(Publisher)
    unit1_score_handler: Any | None = None
    pair_score_handler: Any | None = None
    source_handlers_initialized = not enable_push

    def ensure_source_handlers() -> None:
        nonlocal unit1_score_handler, pair_score_handler, source_handlers_initialized
        if source_handlers_initialized:
            return
        # Optional owner pins must not prevent read tools from starting. Build
        # both owners before caching either; a held owner blocks every push.
        legacy = (unit1_score_handler_factory(publisher)
                  if unit1_score_handler_factory is not None else None)
        paired = (unit1_pair_score_handler_factory(publisher)
                  if unit1_pair_score_handler_factory is not None else None)
        unit1_score_handler, pair_score_handler = legacy, paired
        source_handlers_initialized = True
    def scope_requires_owner(course_id: str, review_id: str | None, items: Any) -> bool:
        # Unknown configured owner scope retains the previous global hold.
        if source_score_scope is None or unit1_pair_score_handler_factory is not None:
            return True
        if not callable(source_score_scope):
            raise GradebookError("Trusted source owner scope is unavailable.")
        try:
            required = source_score_scope(course_id, review_id, items)
        except Exception:
            raise GradebookError("Trusted source owner scope is unavailable.") from None
        if type(required) is not bool:
            raise GradebookError("Trusted source owner scope is invalid.")
        return required

    # None means the trusted owner has no genuinely qualified text release.
    # It never enables tools from cold data or manufactures a release map.
    if enable_qualified_comments is True and comment_releases is None and comment_release_factory is not None:
        comment_releases = comment_release_factory(publisher)
    if enable_qualified_comments is True and comment_releases is not None:
        register_submission_comment_tools(server, comment_releases, enabled=True)
        # The unchanged comment protocol temporarily adds HTTP request hooks.
        # Protect every tool using this canonical client, without editing guards.
        server.add_middleware(CanonicalClientToolLock())


    def resolve(course: str) -> str:
        if course not in courses:
            raise GradebookError("Choose a configured class: " + ", ".join(courses))
        return courses[course]

    if get_refresh_control is not None:

        @server.tool(
            annotations=ToolAnnotations(
                read_only_hint=False,
                destructive_hint=False,
                idempotent_hint=False,
            )
        )
        async def request_gradebook_get_refresh() -> dict[str, Any]:
            """Queue one fresh Canvas read into both protected GET tabs.

            Keep the workbook idle until the returned request is VERIFIED.
            Preserves every EDIT score, formula, note and original baseline.
            Poll get_gradebook_get_refresh_status with the request_id. Never
            resend an uncertain request. No Canvas writes or EDIT changes.
            """
            try:
                return dict(await get_refresh_control.request())
            except GradebookError as exc:
                return {"error": str(exc), "canvas_writes": 0, "retry_writes": False}
            except Exception:
                return {
                    "error": "GET request unavailable; inspect stored status before retrying.",
                    "canvas_writes": 0,
                    "retry_writes": False,
                }

        @server.tool(annotations=ToolAnnotations(read_only_hint=True))
        async def get_gradebook_get_refresh_status(request_id: str) -> dict[str, Any]:
            """Inspect this request's durable aggregate GET refresh receipt.

            VERIFIED includes source times and complete EDIT preservation.
            Intermediate local journal phases do not prove worker liveness.
            Reads local artifacts only. Never queues, releases, or resends.
            """
            try:
                return dict(await get_refresh_control.status(request_id))
            except GradebookError as exc:
                return {"error": str(exc), "canvas_writes": 0, "retry_writes": False}
            except Exception:
                return {
                    "error": "GET status unavailable; no action was retried.",
                    "canvas_writes": 0,
                    "retry_writes": False,
                }

        @server.tool(annotations=ToolAnnotations(read_only_hint=True))
        async def review_gradebook_edits(course: str) -> dict[str, Any]:
            """Compare current native EDIT scores with fresh Canvas by exact IDs.

            Preserves helper formulas and notes while validating mapped score
            cells against their original trusted baseline. Returns aggregate
            counts and a private teacher review. No grades or comments are sent.
            A Canvas push still requires its exact preview and confirmation.
            """
            try:
                return dict(await get_refresh_control.review(client, course))
            except GradebookError as exc:
                return {"error": str(exc), "canvas_writes": 0}
            except Exception:
                return {
                    "error": "Native EDIT review held; no grades or comments were sent.",
                    "canvas_writes": 0,
                }

    if get_refresh_control is not None:

        @server.tool(annotations=ToolAnnotations(read_only_hint=True))
        async def select_gradebook_review_batch(
            course: str,
            review_id: str,
            batch_index: int = 0,
        ) -> dict[str, Any]:
            """Make a private scope of up to 25 ready rows from an existing review.

            Independently checks classifications against captured evidence. Held
            rows remain unresolved in the parent. Does not refresh source times,
            approve teacher decisions, prepare a publisher, or send Canvas changes.
            Review the private scope before separately preparing/confirming a push.
            """
            try:
                from .scoped_review import select_ready_batch

                return select_ready_batch(
                    store, resolve(course), client.origin, review_id, batch_index
                )
            except GradebookError as exc:
                return {"error": str(exc), "canvas_writes": 0}
            except Exception:
                return {
                    "error": "Review scope held; no grade operation was prepared.",
                    "canvas_writes": 0,
                }

    def contains_protected_target(course_id: str, items: Any) -> bool:
        # Private targets belong to trusted owner configuration, never source.
        # No configured extra target policy means no extra target declaration;
        # a configured policy must answer an exact boolean or retain a hold.
        if protected_score_scope is None:
            return False
        if not callable(protected_score_scope):
            raise GradebookError("Trusted protected target scope is unavailable.")
        try:
            protected = protected_score_scope(course_id, items)
        except Exception:
            raise GradebookError("Trusted protected target scope is unavailable.") from None
        if type(protected) is not bool:
            raise GradebookError("Trusted protected target scope is invalid.")
        return protected

    def source_handler_for_operation(
        course_id: str, operation_id: str, *, sending: bool = False,
    ) -> Any:
        operation = publisher.ledger.operation(operation_id)
        plan = store.load("push", operation["plan_id"])
        if "unit1_pair_score_intent" in plan and "owner_binding" not in plan:
            raise GradebookError("The exact paired source owner is required for this operation.")
        if "owner_binding" in plan:
            ensure_source_handlers()
            if pair_score_handler is None or not pair_score_handler.matches_plan(course_id, plan):
                raise GradebookError("The exact paired source owner is required for this operation.")
            return pair_score_handler
        if (plan.get("course_id"), plan.get("origin")) != (course_id, client.origin):
            raise GradebookError("Push belongs to a different course or origin.")
        protected = contains_protected_target(course_id, plan.get("items"))
        if "manual_four_authority" not in plan and not protected:
            if sending and scope_requires_owner(course_id, None, plan.get("items")):
                ensure_source_handlers()
                if (pair_score_handler is not None
                        and pair_score_handler.protects_items(course_id, plan.get("items"))):
                    raise GradebookError("Unit 1 targets require the paired source-approved intent.")
                if source_score_scope is not None and unit1_pair_score_handler_factory is None:
                    raise GradebookError("The exact source-approved operation is required.")
            return None
        ensure_source_handlers()
        if "manual_four_authority" not in plan or unit1_score_handler is None or not unit1_score_handler.matches_plan(course_id, plan):
            raise GradebookError("Unit1 source-qualified handler is not configured for this operation.")
        return unit1_score_handler

    @server.tool(annotations=ToolAnnotations(read_only_hint=True))
    async def get_canvas_gradebook(course: str) -> dict[str, Any]:
        """Fetch a complete gradebook for core or advanced into a private local file.

        Returns aggregate counts and snapshot reference only. Never read the raw
        artifact into chat: it contains student records. No Canvas writes.
        """
        try:
            snapshot = await client.snapshot(resolve(course))
            artifact_id, path = store.save("snapshot", snapshot)
            capture_receipt_id = save_capture(store, snapshot)
            return {
                **summary(snapshot),
                "snapshot_id": artifact_id,
                "capture_receipt_id": capture_receipt_id,
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
                    raise GradebookError(
                        "Baseline does not match the workbook reference."
                    )
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
                    store.inbox_file(workbook_filename),
                    bindings[course].get("tab_names"),
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
            course_id = resolve(course)
            if scope_requires_owner(course_id, review_id, None):
                ensure_source_handlers()
            # Historical source handlers may use an exact manifest reference,
            # rather than a canonical Store review. Preserve that old route
            # when no newer paired authority owns the Unit 1 assignment scope.
            if unit1_score_handler is not None and unit1_score_handler.recognizes_review(review_id):
                if pair_score_handler is not None:
                    raise GradebookError("The current paired source-approved intent is required.")
                prepared = await unit1_score_handler.prepare(publisher, course_id, review_id)
                return {**prepared, "publishing_available": enable_push}
            review = store.load("review", review_id)
            scoped = scope_requires_owner(course_id, review_id, review.get("changes"))
            if (scoped or contains_protected_target(course_id, review.get("changes"))
                    or any(key in review for key in (
                        "unit1_pair_score_intent", "manual_four_authority", "owner_binding",
                    ))):
                ensure_source_handlers()
            if "unit1_pair_score_intent" in review:
                if pair_score_handler is None or not pair_score_handler.recognizes_review(review_id):
                    raise GradebookError("The exact paired source owner is required for this intent.")
                prepared = await pair_score_handler.prepare(publisher, course_id, review_id)
            elif (pair_score_handler is not None
                  and pair_score_handler.protects_items(course_id, review.get("changes"))):
                raise GradebookError("Unit 1 targets require the paired source-approved intent.")
            elif unit1_score_handler is not None and unit1_score_handler.recognizes_review(review_id):
                prepared = await unit1_score_handler.prepare(publisher, course_id, review_id)
            else:
                if any(key in review for key in ("manual_four_authority", "owner_binding")):
                    raise GradebookError("The exact source-approved review is required.")
                if (contains_protected_target(course_id, review.get("changes"))
                        or scoped and source_score_scope is not None
                        and unit1_pair_score_handler_factory is None):
                    raise GradebookError("Exact source-qualified review reference required.")
                prepared = await publisher.prepare(course_id, review_id)
            return {**prepared, "publishing_available": enable_push}
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
            if "owner_binding" in plan:
                handler = source_handler_for_operation(resolve(course), operation_id)
                return dict(handler.status(resolve(course), operation_id))
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
            course_id = resolve(course)
            handler = source_handler_for_operation(course_id, operation_id)
            if handler is not None:
                return dict(await handler.reconcile(publisher, course_id, operation_id))
            return await publisher.reconcile(course_id, operation_id)
        except GradebookError as exc:
            return {"error": str(exc), "retry_writes": False}
        except Exception:
            return {
                "error": "Reconciliation unavailable; retain the operation and do not retry writes.",
                "retry_writes": False,
            }

    @server.tool(annotations=ToolAnnotations(read_only_hint=True))
    async def prepare_gradebook_comment_push(
        course: str, comments_filename: str, expected_envelope_sha256: str
    ) -> dict[str, Any]:
        """Preview one exact source-bound inbox proposal; no comment is sent.

        The expected digest must come from the retained proposal owner. Open the
        private artifact for teacher review; hashes do not approve feedback or
        accept an academic score. No real student payloads belong in tool args.
        """
        try:
            return {
                **await publisher.prepare_comment(
                    resolve(course), comments_filename, expected_envelope_sha256
                ),
                "publishing_available": enable_comments,
                "loaded_comment_runtime": comment_runtime.as_dict(),
            }
        except GradebookError as exc:
            return {"error": str(exc), "canvas_writes": 0,
                    "loaded_comment_runtime": comment_runtime.as_dict()}
        except Exception:
            return {
                "error": "Comment preview failed; nothing sent.",
                "canvas_writes": 0,
                "loaded_comment_runtime": comment_runtime.as_dict(),
            }

    @server.tool(annotations=ToolAnnotations(read_only_hint=True))
    async def reconcile_gradebook_comment_push(
        course: str, operation_id: str
    ) -> dict[str, Any]:
        """GET-only comment reconciliation; retain locks and never repeat an append."""
        try:
            return await publisher.reconcile_comment(resolve(course), operation_id)
        except GradebookError as exc:
            return {"error": str(exc), "retry_writes": False, "canvas_writes": 0}
        except Exception:
            return {
                "error": "Comment readback unavailable; do not retry.",
                "retry_writes": False,
                "canvas_writes": 0,
            }

    if enable_comments:

        @server.tool(
            annotations=ToolAnnotations(
                read_only_hint=False, destructive_hint=True, idempotent_hint=False
            )
        )
        async def confirm_gradebook_comment_push(
            course: str, operation_id: str, confirmation_token: str
        ) -> dict[str, Any]:
            """Append only the exact teacher-reviewed comment using its one-use token.

            Requires separate approval of this operation's private preview.
            Sends no score, excusal or policy change. Canvas posting policy may
            make feedback or an existing grade visible. A lost reply never
            permits another append; inspect status and reconcile with GET only.
            """
            try:
                return await publisher.confirm_comment(
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
                    "error": "Comment stopped; inspect durable status before any action.",
                    "operation_id": operation_id,
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
                course_id = resolve(course)
                if source_score_scope is None or unit1_pair_score_handler_factory is not None:
                    ensure_source_handlers()
                handler = source_handler_for_operation(course_id, operation_id, sending=True)
                if handler is not None:
                    return dict(await handler.confirm(publisher, course_id, operation_id, confirmation_token))
                return await publisher.confirm(course_id, operation_id, confirmation_token)
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

    def require_generic_score_scope(course_id: str, review_id: str | None, items: Any) -> None:
        """Batch paths must not bypass the separately qualified source owner."""
        scoped = scope_requires_owner(course_id, review_id, items)
        if scoped:
            ensure_source_handlers()
        if (contains_protected_target(course_id, items)
                or pair_score_handler is not None and pair_score_handler.protects_items(course_id, items)
                or scoped and source_score_scope is not None and unit1_pair_score_handler_factory is None):
            raise GradebookError("Score batch requires the exact source-owned publication route.")

    @server.tool(annotations=ToolAnnotations(read_only_hint=True))
    async def prepare_gradebook_score_batch(
        course: str, review_id: str, approval_seconds: int = 7200
    ) -> dict[str, Any]:
        """Review one immutable score manifest, excluding held targets.

        At most 1000 proposals, split into <=25-target single-use chunks.
        Approve every exact payload in the private review once. No Canvas writes.
        The bounded grant expires after the requested 600–28800 seconds.
        """
        try:
            course_id = resolve(course)
            if scope_requires_owner(course_id, review_id, None):
                ensure_source_handlers()
            review = store.load("review", review_id)
            if any(key in review for key in ("unit1_pair_score_intent", "owner_binding", "manual_four_authority")):
                raise GradebookError("Score batch requires the exact source-owned publication route.")
            require_generic_score_scope(course_id, review_id, review.get("changes"))
            return {
                **await batches.prepare_scores(
                    course_id, review_id, approval_seconds
                ),
                "publishing_available": enable_push,
            }
        except GradebookError as exc:
            return {"error": str(exc), "canvas_writes": 0}
        except Exception:
            return {
                "error": "Batch preparation held; no Canvas changes were made.",
                "canvas_writes": 0,
            }

    @server.tool(annotations=ToolAnnotations(read_only_hint=True))
    async def prepare_gradebook_comment_batch(
        course: str, proposals: list[dict[str, str]], approval_seconds: int = 7200
    ) -> dict[str, Any]:
        """Review exact private comment references in one immutable manifest.

        Each reference has filename and envelope_sha256 from its source owner.
        Held proposals stay excluded. Review all private payloads once; hashes
        establish no academic acceptance. No grades, comments or messages sent.
        """
        try:
            return {
                **await batches.prepare_comments(
                    resolve(course), proposals, approval_seconds
                ),
                "publishing_available": enable_comments,
            }
        except GradebookError as exc:
            return {"error": str(exc), "canvas_writes": 0}
        except Exception:
            return {
                "error": "Comment batch preparation held; nothing sent.",
                "canvas_writes": 0,
            }

    @server.tool(annotations=ToolAnnotations(read_only_hint=True))
    async def get_gradebook_batch_status(course: str, batch_id: str) -> dict[str, Any]:
        """Read the durable manifest/grant and per-chunk aggregate status only."""
        try:
            return batches.status(resolve(course), batch_id)
        except GradebookError as exc:
            return {"error": str(exc), "retry_writes": False}

    @server.tool(
        annotations=ToolAnnotations(read_only_hint=False, destructive_hint=False)
    )
    async def revoke_gradebook_batch(course: str, batch_id: str) -> dict[str, Any]:
        """Revoke remaining dispatch authority. Never reverses or retries writes."""
        try:
            return batches.revoke(resolve(course), batch_id)
        except GradebookError as exc:
            return {"error": str(exc), "retry_writes": False}

    if enable_push or enable_comments:

        def enabled_batch(course_id: str, batch_id: str) -> None:
            _, manifest = batches._manifest(course_id, batch_id)
            if not (enable_push if manifest["channel"] == "SCORE" else enable_comments):
                raise GradebookError("This batch publication channel is not enabled.")
            if manifest["channel"] == "SCORE":
                for plan_id in manifest["plan_ids"]:
                    plan = store.load("push", plan_id)
                    if ((plan.get("course_id"), plan.get("origin")) != (course_id, client.origin)
                            or any(key in plan for key in ("unit1_pair_score_intent", "owner_binding", "manual_four_authority"))):
                        raise GradebookError("Score batch requires the exact source-owned publication route.")
                    require_generic_score_scope(course_id, plan.get("review_id"), plan.get("items"))

        @server.tool(
            annotations=ToolAnnotations(
                read_only_hint=False, destructive_hint=False, idempotent_hint=False
            )
        )
        async def authorize_gradebook_batch(
            course: str, batch_id: str, confirmation_token: str
        ) -> dict[str, Any]:
            """Consume approval of the exact private batch manifest once; send nothing.

            Only use after the teacher approved all linked unchanged payloads.
            Future bounded chunks reuse this grant until expiry/revocation,
            while retaining exact source/target checks and single-use sends.
            """
            try:
                course_id = resolve(course)
                enabled_batch(course_id, batch_id)
                return {
                    **batches.authorize(course_id, batch_id, confirmation_token),
                    "canvas_writes": 0,
                }
            except GradebookError as exc:
                return {"error": str(exc), "canvas_writes": 0}

        @server.tool(
            annotations=ToolAnnotations(
                read_only_hint=False, destructive_hint=True, idempotent_hint=False
            )
        )
        async def execute_gradebook_batch_chunk(
            course: str, batch_id: str, chunk_index: int
        ) -> dict[str, Any]:
            """Dispatch one exact chunk covered by an existing approved manifest.

            Rechecks current scope, targets, source and original payload. Holds
            affect only their independent targets. A previously claimed chunk
            returns status, never resends. Use existing reconciliation tools
            for uncertain operation IDs returned by batch status.
            """
            try:
                course_id = resolve(course)
                enabled_batch(course_id, batch_id)
                return await batches.execute_chunk(course_id, batch_id, chunk_index)
            except GradebookError as exc:
                return {"error": str(exc), "batch_id": batch_id, "retry_writes": False}
            except Exception:
                return {
                    "error": "Chunk stopped; inspect batch and operation status before continuing.",
                    "batch_id": batch_id,
                    "retry_writes": False,
                }

    return server
