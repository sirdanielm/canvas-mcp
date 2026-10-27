"""One exact private review authorizes resumable, bounded publisher chunks.

The manifest and each child plan are content addressed. An approval token is
consumed once; later chunks use the same unrevoked, unexpired grant, never a
newly inferred academic decision. Every dispatch still uses the ordinary
single-use ledger, fresh target checks and uncertain-write reconciliation.
"""

from __future__ import annotations

import hashlib
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .client import GradebookError
from .model import compare_edits, digest
from .publish import (
    COMMENT_PLAN,
    Publisher,
    context,
    require_simple_target,
    target_key,
    write_review_html,
)
from .scoped_review import validated_review

BATCH_PLAN = "GRADEBOOK_REVIEWED_BATCH_V1"


class BatchPublisher:
    def __init__(self, publisher: Publisher) -> None:
        self.publisher = publisher
        self.store = publisher.store
        self.ledger = publisher.ledger

    @staticmethod
    def _window(approval_seconds: int) -> None:
        if type(approval_seconds) is not int or not 600 <= approval_seconds <= 28800:
            raise GradebookError("Batch approval window must be 600–28800 seconds.")

    def _display_digest(self, filename: str) -> str:
        path = Path(filename)
        if path.is_symlink() or path.parent.resolve() != self.store.root:
            raise GradebookError(
                "Batch review display is not the bound private artifact."
            )
        try:
            return hashlib.sha256(path.read_bytes()).hexdigest()
        except OSError as exc:
            raise GradebookError("Batch review display is unavailable.") from exc

    def _check_displays(self, manifest: dict[str, Any]) -> None:
        if [self._display_digest(p) for p in manifest["review_files"]] != manifest[
            "review_sha256"
        ]:
            raise GradebookError(
                "Reviewed batch display changed; no remaining dispatch is authorized."
            )

    def _manifest(self, course_id: str, batch_id: str) -> tuple[str, dict[str, Any]]:
        batch = self.ledger.batch(batch_id)
        manifest_id = batch["manifest_id"]
        manifest = self.store.load("push", manifest_id)
        if (
            manifest.get("kind") != BATCH_PLAN
            or type(manifest.get("schema_version")) is not int
            or manifest["schema_version"] != 1
            or manifest.get("channel") not in ("SCORE", "COMMENT")
            or not isinstance(manifest.get("plan_ids"), list)
            or not isinstance(manifest.get("review_files"), list)
            or not isinstance(manifest.get("review_sha256"), list)
            or not manifest["review_files"]
            or len(manifest["review_files"]) != len(manifest["review_sha256"])
            or (manifest.get("course_id"), manifest.get("origin"))
            != (course_id, self.publisher.client.origin)
            or manifest.get("plan_ids") != [c["plan_id"] for c in batch["chunks"]]
        ):
            raise GradebookError(
                "Batch manifest does not match this course, origin and chunk set."
            )
        return manifest_id, manifest

    def _save(
        self,
        course_id: str,
        channel: str,
        plans: list[str],
        displays: list[str],
        held: int,
        approval_seconds: int,
        held_proposals: list[dict[str, str]] | None = None,
    ) -> dict[str, Any]:
        manifest = {
            "kind": BATCH_PLAN,
            "schema_version": 1,
            "course_id": course_id,
            "origin": self.publisher.client.origin,
            "channel": channel,
            "plan_ids": plans,
            "review_files": displays,
            "review_sha256": [self._display_digest(p) for p in displays],
            "held": held,
            "created_at": datetime.now(UTC).isoformat(),
            "approval_seconds": approval_seconds,
            "held_proposals": held_proposals or [],
        }
        manifest_id, path = self.store.save("push", manifest)
        batch_id, token = self.ledger.prepare_batch(
            manifest_id, plans, approval_seconds
        )
        return {
            "ready_for_confirmation": True,
            "batch_id": batch_id,
            "manifest_id": manifest_id,
            "manifest_file": str(path),
            "review_files": displays,
            "confirmation_token": token,
            "expires_at": self.ledger.batch(batch_id)["expires"],
            "chunks": len(plans),
            "held": held,
            "channel": channel,
            "canvas_writes": 0,
            "notice": "Review this exact private manifest and every linked payload. One approval covers its unchanged bounded chunks until expiry or revocation; held targets are excluded.",
        }

    async def prepare_scores(
        self, course_id: str, review_id: str, approval_seconds: int = 7200
    ) -> dict[str, Any]:
        self._window(approval_seconds)
        review, baseline, _, checked = validated_review(
            self.store, course_id, self.publisher.client.origin, review_id
        )
        original_holds = {
            (c["user_id"], c["assignment_id"]): c
            for c in checked["changes"]
            if c["status"] != "ready_for_review" or c["reasons"]
        }
        if not isinstance(review.get("changes"), list) or len(review["changes"]) > 1000:
            raise GradebookError("A reviewed batch is limited to 1000 proposals.")
        current = await self.publisher.client.snapshot(course_id)
        if current.get("course_workflow_state") != "available":
            raise GradebookError("Only an active available course can accept a batch.")
        self.store.save("snapshot", current)
        envelope = {
            "course_id": course_id,
            "snapshot_id": digest(baseline),
            "edits": [
                {
                    "user_id": c["user_id"],
                    "assignment_id": c["assignment_id"],
                    "value": c["proposed"],
                }
                for c in review["changes"]
            ],
        }
        fresh = compare_edits(baseline, current, envelope)
        items = []
        for change in fresh["changes"]:
            prior = original_holds.get((change["user_id"], change["assignment_id"]))
            if prior is not None:
                change.update(
                    status="review_required",
                    reasons=sorted(set(change["reasons"] + prior["reasons"])),
                )
            if change["status"] != "ready_for_review" or change["reasons"]:
                continue
            try:
                ctx = await context(
                    self.publisher.client,
                    course_id,
                    change["user_id"],
                    change["assignment_id"],
                )
                if ctx["submission"] != current["cells"].get(
                    change["user_id"] + ":" + change["assignment_id"]
                ):
                    raise GradebookError("Target changed during preparation.")
                require_simple_target(ctx, change["proposed"])
            except GradebookError as exc:
                change.update(
                    status="review_required",
                    reasons=["target_preflight_held: " + str(exc)],
                )
                continue
            items.append({**change, "expected": ctx})
        fresh["counts"] = dict(Counter(c["status"] for c in fresh["changes"]))
        fresh_id, _ = self.store.save("review", fresh)
        display = write_review_html(self.store, fresh)
        held = fresh["counts"].get("review_required", 0)
        if not items:
            return {
                "ready_for_confirmation": False,
                "held": held,
                "review_file": display,
                "canvas_writes": 0,
            }
        plans = []
        for offset in range(0, len(items), 25):
            plan = {
                "schema_version": 1,
                "origin": self.publisher.client.origin,
                "course_id": course_id,
                "review_id": fresh_id,
                "current_id": digest(current),
                "created_at": datetime.now(UTC).isoformat(),
                "items": items[offset : offset + 25],
            }
            plan_id, _ = self.store.save("push", plan)
            plans.append(plan_id)
        return self._save(course_id, "SCORE", plans, [display], held, approval_seconds)

    async def prepare_comments(
        self,
        course_id: str,
        proposals: list[dict[str, str]],
        approval_seconds: int = 7200,
    ) -> dict[str, Any]:
        self._window(approval_seconds)
        if not 1 <= len(proposals) <= 1000:
            raise GradebookError(
                "A comment batch requires 1–1000 exact proposal references."
            )
        plans, displays, targets = [], [], set()
        held_proposals = []
        for proposal in proposals:
            if not isinstance(proposal, dict) or set(proposal) != {
                "filename",
                "envelope_sha256",
            }:
                raise GradebookError(
                    "Comment references require filename and envelope_sha256 only."
                )
            try:
                prepared = await self.publisher.prepare_comment(
                    course_id,
                    proposal["filename"],
                    proposal["envelope_sha256"],
                    issue_confirmation=False,
                )
            except GradebookError as exc:
                held_proposals.append({**proposal, "reason": str(exc)})
                continue
            plan = self.store.load("push", prepared["plan_id"])
            key = target_key(self.publisher.client.origin, course_id, plan["envelope"])
            if key in targets:
                raise GradebookError(
                    "Duplicate comment batch target; review one exact comment per target."
                )
            targets.add(key)
            plans.append(prepared["plan_id"])
            displays.append(prepared["review_file"])
        if not plans:
            receipt_id, path = self.store.save(
                "receipt",
                {
                    "kind": "GRADEBOOK_COMMENT_BATCH_HELD_V1",
                    "held_proposals": held_proposals,
                    "course_id": course_id,
                    "origin": self.publisher.client.origin,
                },
            )
            return {
                "ready_for_confirmation": False,
                "held": len(held_proposals),
                "held_receipt_id": receipt_id,
                "held_file": str(path),
                "canvas_writes": 0,
            }
        return self._save(
            course_id,
            "COMMENT",
            plans,
            displays,
            len(held_proposals),
            approval_seconds,
            held_proposals,
        )

    def authorize(self, course_id: str, batch_id: str, token: str) -> dict[str, Any]:
        _, manifest = self._manifest(course_id, batch_id)
        self._check_displays(manifest)
        self.ledger.authorize_batch(batch_id, token)
        return self.status(course_id, batch_id)

    def revoke(self, course_id: str, batch_id: str) -> dict[str, Any]:
        self._manifest(course_id, batch_id)
        self.ledger.revoke_batch(batch_id)
        return self.status(course_id, batch_id)

    def status(self, course_id: str, batch_id: str) -> dict[str, Any]:
        manifest_id, manifest = self._manifest(course_id, batch_id)
        batch = self.ledger.batch(batch_id)
        chunks = [
            (
                {"chunk_index": c["position"], **self.ledger.summary(c["operation_id"])}
                if c["operation_id"]
                else {"chunk_index": c["position"], "status": "pending"}
            )
            for c in batch["chunks"]
        ]
        return {
            "batch_id": batch_id,
            "manifest_id": manifest_id,
            "status": batch["status"],
            "channel": manifest["channel"],
            "expires_at": batch["expires"],
            "held": manifest["held"],
            "chunks": chunks,
            "retry_writes": False,
        }

    async def execute_chunk(
        self, course_id: str, batch_id: str, chunk_index: int
    ) -> dict[str, Any]:
        manifest_id, manifest = self._manifest(course_id, batch_id)
        if type(chunk_index) is not int or not 0 <= chunk_index < len(
            manifest["plan_ids"]
        ):
            raise GradebookError("Invalid reviewed chunk index.")
        with self.ledger.exclusive(batch_id):
            batch = self.ledger.require_batch(batch_id, manifest_id)
            self._check_displays(manifest)
            chunk = batch["chunks"][chunk_index]
            plan = self.store.load("push", chunk["plan_id"])
            if chunk["operation_id"]:
                operation_id = chunk["operation_id"]
                if self.ledger.operation(operation_id)["status"] != "prepared":
                    return self.ledger.summary(operation_id)
                token = self.ledger.unstarted_chunk_token(
                    batch_id, manifest_id, operation_id
                )
            else:
                if manifest["channel"] == "COMMENT":
                    if plan.get("kind") != COMMENT_PLAN:
                        raise GradebookError(
                            "Comment manifest contains a different channel."
                        )
                    targets = [
                        target_key(
                            self.publisher.client.origin, course_id, plan["envelope"]
                        )
                    ]
                    options: dict[str, Any] = {
                        "comment_delivery_ids": [plan["delivery_id"]]
                    }
                else:
                    if plan.get("kind") is not None:
                        raise GradebookError(
                            "Score manifest contains a different channel."
                        )
                    targets = [
                        target_key(self.publisher.client.origin, course_id, c)
                        for c in plan["items"]
                    ]
                    options = {}
                operation_id, token = self.ledger.prepare(
                    chunk["plan_id"], targets, **options
                )
                self.ledger.attach_batch_chunk(
                    batch_id, manifest_id, chunk_index, operation_id
                )

            def check() -> dict[str, Any]:
                return self.ledger.require_batch(batch_id, manifest_id)

            if manifest["channel"] == "COMMENT":
                return await self.publisher.confirm_comment(
                    course_id, operation_id, token, authorization_check=check
                )
            return await self.publisher.confirm(
                course_id,
                operation_id,
                token,
                independent_targets=True,
                authorization_check=check,
            )
