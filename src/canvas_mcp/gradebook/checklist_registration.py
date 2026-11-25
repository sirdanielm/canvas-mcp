"""Exclusive checklist score tools backed by a trusted, release-specific owner."""

from __future__ import annotations

import inspect
import re
from collections.abc import Callable
from typing import Any, Protocol

from fastmcp import FastMCP
from mcp.types import ToolAnnotations

from .client import GradebookError
from .publish import Publisher


class ChecklistScoreOwner(Protocol):
    """The private owner verifies approval, history and the final transport guard."""

    async def prepare(self, course: str, review_id: str) -> dict[str, Any]:
        raise NotImplementedError

    async def confirm(
        self, course: str, operation_id: str, token: str
    ) -> dict[str, Any]:
        raise NotImplementedError

    def status(self, course: str, operation_id: str) -> dict[str, Any]:
        raise NotImplementedError

    async def reconcile(self, course: str, operation_id: str) -> dict[str, Any]:
        raise NotImplementedError


class ChecklistOwnerFactory(Protocol):
    def __call__(
        self,
        publisher: Publisher,
        *,
        assert_active: Callable[[], None],
        assert_target_authority: Callable[[str, str, dict[str, Any]], None],
    ) -> ChecklistScoreOwner:
        raise NotImplementedError


def _require(condition: bool) -> None:
    if not condition:
        raise GradebookError("Checklist publication scope held.")


def assert_checklist_active(check: Callable[[], object]) -> None:
    try:
        result = check()
    except Exception:
        raise GradebookError("Checklist publication scope held.") from None
    if inspect.iscoroutine(result):
        result.close()
    _require(result is None)


def register_checklist_score_tools(
    server: FastMCP,
    publisher: Publisher,
    courses: dict[str, str],
    owner_factory: ChecklistOwnerFactory,
    active: Callable[[], object],
    source_classifier: Callable[[str, str, Any], bool],
    protected_classifier: Callable[[str, Any], bool],
) -> None:
    """The tool arguments can only select reviews and operations of this owner."""
    configured = dict(courses)
    _require(len(configured) == len(set(configured.values())) == 2)

    def assert_active() -> None:
        assert_checklist_active(active)

    def assert_target_authority(
        course: str, review_id: str, target: dict[str, Any]
    ) -> None:
        assert_active()
        # Store.load verifies the review digest. A new scope cannot select a
        # different student, assignment or qualified owner's protected target.
        review = publisher.store.load("review", review_id)
        _require(
            course in configured.values()
            and review.get("course_id") == course
            and target.get("course_id") == course
            and target.get("review_id") == review_id
        )
        changes = review.get("changes")
        if (
            not isinstance(changes, list)
            or len(changes) != 1
            or not isinstance(changes[0], dict)
        ):
            raise GradebookError("Checklist publication scope held.")
        _require(
            all(
                isinstance(target.get(key), str)
                and bool(target[key])
                and changes[0].get(key) == target[key]
                for key in ("assignment_id", "user_id")
            )
        )
        _require(source_classifier(course, review_id, changes) is True)
        _require(protected_classifier(course, changes) is False)

    try:
        owner = owner_factory(
            publisher,
            assert_active=assert_active,
            assert_target_authority=assert_target_authority,
        )
    except Exception:
        raise GradebookError("Private checklist owner is unavailable.") from None
    _require(
        all(
            callable(getattr(owner, method, None))
            for method in ("prepare", "confirm", "status", "reconcile")
        )
    )

    def course_id(course: str) -> str:
        assert_active()
        return configured[course]

    def operation(value: str) -> str:
        _require(re.fullmatch(r"[a-f0-9]{32}", value) is not None)
        return value

    local_write = ToolAnnotations(read_only_hint=False, destructive_hint=False)

    @server.tool(annotations=local_write)
    async def prepare_gradebook_push(course: str, review_id: str) -> dict[str, Any]:
        """Prepare one approved checklist review in the private ledger; no Canvas write."""
        try:
            _require(re.fullmatch(r"[a-f0-9]{64}", review_id) is not None)
            return await owner.prepare(course_id(course), review_id)
        except Exception:
            return {"error": "Exact checklist review held", "canvas_writes": 0}

    @server.tool(
        annotations=ToolAnnotations(
            read_only_hint=False, destructive_hint=True, idempotent_hint=False
        )
    )
    async def confirm_gradebook_push(
        course: str, operation_id: str, confirmation_token: str
    ) -> dict[str, Any]:
        """Send one approved native operation. An uncertain result requires reconciliation."""
        try:
            _require(re.fullmatch(r"[A-Za-z0-9_-]{43}", confirmation_token) is not None)
            return await owner.confirm(
                course_id(course), operation(operation_id), confirmation_token
            )
        except Exception:
            return {
                "error": "Exact checklist confirmation held; inspect its receipt",
                "retry_writes": False,
            }

    @server.tool(annotations=ToolAnnotations(read_only_hint=True))
    async def get_gradebook_push_status(
        course: str, operation_id: str
    ) -> dict[str, Any]:
        """Read the private ledger receipt for a checklist operation."""
        try:
            return owner.status(course_id(course), operation(operation_id))
        except Exception:
            return {"error": "Exact checklist status unavailable"}

    @server.tool(annotations=local_write)
    async def reconcile_gradebook_push(
        course: str, operation_id: str
    ) -> dict[str, Any]:
        """Read Canvas and reconcile the private receipt without repeating delivery."""
        try:
            return await owner.reconcile(course_id(course), operation(operation_id))
        except Exception:
            return {
                "error": "Exact checklist reconciliation held",
                "retry_writes": False,
            }
