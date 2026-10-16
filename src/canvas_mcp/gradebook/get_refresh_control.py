"""Aggregate MCP control for the installed protected GET worker."""

from __future__ import annotations

import re
from collections.abc import Callable
from datetime import datetime
from typing import Any

from .client import GradebookError
from .get_refresh_request import request_get_refresh
from .model import digest
from .store import Store
from .worker import UUID, RefreshJournal


def _verified_time(value: Any) -> str:
    """Return an evidence timestamp only after checking its complete type."""
    try:
        if not isinstance(value, str):
            raise ValueError
        parsed = datetime.fromisoformat(value)
        if parsed.tzinfo is None:
            raise ValueError
    except (TypeError, ValueError) as exc:
        raise GradebookError("GET receipt evidence time is invalid.") from exc
    return value


class GetRefreshControl:
    """No Canvas transport; queue once, then inspect immutable local receipts."""

    def __init__(
        self,
        google_factory: Callable[[], Any],
        store: Store,
        bindings: dict[str, Any],
        instance_id: str,
    ) -> None:
        self.google_factory = google_factory
        self.store = store
        self.bindings = bindings
        self.instance_id = instance_id

    async def request(self) -> dict[str, Any]:
        google = self.google_factory()
        try:
            return dict(
                await request_get_refresh(
                    google,
                    self.store,
                    self.bindings,
                    self.instance_id,
                )
            )
        finally:
            await google.close()

    async def review(self, client: Any, course: str) -> dict[str, Any]:
        """Read native mapped EDIT grades and fresh Canvas; create a private review."""
        if course not in self.bindings:
            raise GradebookError("Choose a configured gradebook course.")
        from .native_edit_review import prepare_review

        google = self.google_factory()
        try:
            raw = await google.read_workbook()
            return dict(
                await prepare_review(
                    client,
                    self.store,
                    course,
                    self.bindings[course],
                    raw,
                )
            )
        finally:
            await google.close()

    async def status(self, request_id: str) -> dict[str, Any]:
        if not isinstance(request_id, str) or not UUID.fullmatch(request_id):
            raise GradebookError("Refresh request ID must be a canonical UUID.")
        books = {b["spreadsheet_id"] for b in self.bindings.values()}
        if len(books) != 1:
            raise GradebookError("GET status requires one configured workbook.")
        journal = RefreshJournal(self.store.root, next(iter(books)))
        operation = journal.get(request_id)
        result: dict[str, Any] = {
            "request_id": request_id,
            "state": operation["status"] if operation else "NOT_FOUND",
            "source": "local_journal",
            "canvas_writes": 0,
            "retry_writes": False,
        }
        if operation is None:
            return result
        payload = operation["payload"]
        if (
            type(payload.get("refresh_mode_schema")) is not int
            or payload.get("refresh_mode_schema") != 1
            or payload.get("refresh_mode") != "GET_ONLY"
        ):
            raise GradebookError("Operation is not a pinned GET-only refresh.")
        result["refresh_mode"] = "GET_ONLY"
        if operation["status"] != "VERIFIED":
            return result
        receipt_id = payload.get("receipt_id")
        receipt = self.store.load("receipt", receipt_id)
        manifest = self.store.load("refresh", payload.get("manifest_id"))
        request = payload.get("request")
        plans = manifest.get("plans")
        summaries = receipt.get("summary")
        if (
            type(receipt.get("worker_schema")) is not int
            or receipt.get("worker_schema") != 1
            or receipt.get("request_id") != request_id
            or receipt.get("manifest_id") != payload.get("manifest_id")
            or type(receipt.get("canvas_writes")) is not int
            or receipt.get("canvas_writes") != 0
            or manifest.get("refresh_mode") != "GET_ONLY"
            or not isinstance(request, dict)
            or request.get("id") != request_id
            or request.get("workbook_id") not in books
            or manifest.get("request") != request
            or manifest.get("binding_digest") != digest(self.bindings)
            or not isinstance(plans, dict)
            or set(plans) != set(self.bindings)
            or not isinstance(summaries, dict)
            or set(summaries) != set(self.bindings)
        ):
            raise GradebookError("GET receipt binding or preservation mode differs.")
        verified_at = _verified_time(receipt.get("verified_at"))
        clean_summary = {}
        fetched_at = {}
        for course, binding in self.bindings.items():
            summary = summaries[course]
            plan = plans[course]
            if (
                not isinstance(summary, dict)
                or not isinstance(plan, dict)
                or plan.get("mode") != "GET_ONLY"
                or plan.get("edit_preserved") is not True
                or not isinstance(plan.get("baseline_id"), str)
                or not re.fullmatch(r"[a-f0-9]{64}", plan["baseline_id"])
                or plan.get("baseline_id") != plan.get("previous_baseline_id")
                or not isinstance(plan.get("canvas_snapshot_id"), str)
                or not re.fullmatch(r"[a-f0-9]{64}", plan["canvas_snapshot_id"])
                or summary.get("edit_preserved") is not True
                or summary.get("pending_edits") is not None
                or any(
                    type(summary.get(k)) is not int or summary[k] < 1
                    for k in ("students", "assignments")
                )
            ):
                raise GradebookError("GET receipt does not verify EDIT preservation.")
            snapshot = self.store.load("snapshot", plan["canvas_snapshot_id"])
            if snapshot.get("course_id") != binding["course_id"]:
                raise GradebookError("GET receipt snapshot course differs.")
            clean_summary[course] = {
                "students": summary["students"],
                "assignments": summary["assignments"],
                "edit_preserved": True,
            }
            fetched_at[course] = _verified_time(snapshot.get("fetched_at"))
        return {
            **result,
            "receipt_id": receipt_id,
            "verified_at": verified_at,
            "fetched_at": fetched_at,
            "summary": clean_summary,
            "finalized": payload.get("finalized") is True,
        }
