"""Independent course-scoped module profile; no generic Canvas writers."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from fastmcp import FastMCP
from mcp.types import ToolAnnotations
from pydantic import StrictBool, StrictInt

from ..core.client import fetch_all_paginated_results, make_canvas_request
from ..core.validation import validate_params
from .draft_assignments import _id, digest
from .draft_module_items import DraftModuleItems, _inventory, _parent
from .module_publication import ModulePublicationService

READERS = frozenset({"module_authoring_status", "inspect_module_authoring", "prepare_module_publication"})
WRITERS = frozenset({"add_draft_module_item", "edit_draft_module_item", "confirm_module_publication"})


def _wire(value: dict[str, Any]) -> dict[str, Any]:
    """Make holds/uncertainty explicit MCP failures while preserving receipt facts."""
    if value.get("status") in {"HELD", "UNKNOWN", "UNVERIFIED"}:
        return {**value, "error": value.get("reason", "Reconcile before another operation")}
    return value


class ModuleAuthoring:
    """Operator-owned scope, shared durable intent history, publication off by default."""

    def __init__(self, *, courses: frozenset[str], journal: Path,
                 publication_enabled: bool = False):
        if not courses or not all(_id(c) for c in courses):
            raise ValueError("Explicit positive course IDs required")
        if not journal.is_absolute() or journal.resolve() != journal.absolute():
            raise ValueError("An absolute non-symlink journal path is required")
        if type(publication_enabled) is not bool:
            raise ValueError("Publication flag must be boolean")
        self.courses = courses
        self.journal = journal
        self.items = DraftModuleItems(journal / "items")
        self.publication_enabled = publication_enabled
        self.publications: dict[tuple[str, str], ModulePublicationService] = {}

    def permits(self, course: str, module: str) -> bool:
        return _id(course) and course in self.courses and _id(module)

    def publication(self, course: str, module: str) -> ModulePublicationService | None:
        if not self.publication_enabled or not self.permits(course, module):
            return None
        key = (course, module)
        if key not in self.publications:
            if len(self.publications) >= 256:
                return None
            self.publications[key] = ModulePublicationService(
                self.journal / "publication", course_id=course, module_id=module, enabled=True)
        return self.publications[key]

    async def inspect(self, course: str, module: str) -> dict[str, Any]:
        if not self.permits(course, module):
            return _wire({"status": "HELD", "reason": "Target outside operator course scope"})
        base = f"/courses/{course}/modules/{module}"
        try:
            parent = await make_canvas_request("get", base)
            if not isinstance(parent, dict) or type(parent.get("published")) is not bool:
                raise ValueError("Parent publication unknown")
            if not _parent(parent, course, module, parent["published"]):
                raise ValueError("Wrong parent")
            items = await fetch_all_paginated_results(base + "/items")
            after = await make_canvas_request("get", base)
            if not _inventory(items, module) or after != parent:
                raise ValueError("Incomplete or changed inventory")
            return {"status": "REVIEW", "course_id": course, "module_id": module,
                    "expected_parent_published": parent["published"],
                    "expected_parent_sha256": digest(parent), "expected_items": items}
        except Exception:
            return {"status": "HELD", "reason": "Exact stable module evidence unavailable"}


def register_module_authoring_tools(mcp: FastMCP, service: ModuleAuthoring) -> None:
    """A hard registry ceiling, separately filtered by operator write policy."""
    @mcp.tool(annotations=ToolAnnotations(read_only_hint=True))
    @validate_params
    async def module_authoring_status() -> dict[str, Any]:
        """Local status only: no credential check, Canvas request or journal mutation."""
        return {"profile": "module-authoring-only", "course_ids": sorted(service.courses),
                "publication_enabled": service.publication_enabled,
                "publication_limit": "Empty container or all children already published; no draft release",
                "human_approval": "Actual publication requires explicit scoped client approval"}

    @mcp.tool(annotations=ToolAnnotations(read_only_hint=True))
    @validate_params
    async def inspect_module_authoring(course_id: str, module_id: str) -> dict[str, Any]:
        """Read exact parent publication and ordered item preimages, without student data."""
        return _wire(await service.inspect(course_id, module_id))

    @mcp.tool(annotations=ToolAnnotations(destructive_hint=False, idempotent_hint=False))
    @validate_params
    async def add_draft_module_item(
        operation_id: str, course_id: str, module_id: str, item_type: str,
        position: StrictInt, expected_items: list[dict[str, Any]],
        expected_parent_sha256: str, expected_parent_published: StrictBool,
        title: str | None = None, assignment_id: str | None = None,
    ) -> dict[str, Any]:
        """Add one unpublished Assignment or SubHeader; preserve parent publication and peers."""
        if not service.permits(course_id, module_id):
            return _wire({"status": "HELD", "reason": "Target outside operator course scope"})
        return _wire(await service.items.execute(
            operation_id=operation_id, course_id=course_id, module_id=module_id,
            item_type=item_type, position=position, expected_items=expected_items,
            existing_item_ids=[str(i.get("id", "")) for i in expected_items],
            expected_parent_sha256=expected_parent_sha256,
            expected_parent_published=expected_parent_published,
            published=False, title=title, assignment_id=assignment_id))

    @mcp.tool(annotations=ToolAnnotations(destructive_hint=True, idempotent_hint=False))
    @validate_params
    async def edit_draft_module_item(
        operation_id: str, course_id: str, module_id: str, item_id: str,
        content: dict[str, Any], expected_item: dict[str, Any],
        expected_items: list[dict[str, Any]], expected_parent_sha256: str,
        expected_parent_published: StrictBool,
    ) -> dict[str, Any]:
        """Edit only an unpublished item's position/indent, or a SubHeader title; never publish."""
        if not service.permits(course_id, module_id):
            return _wire({"status": "HELD", "reason": "Target outside operator course scope"})
        return _wire(await service.items.edit(
            operation_id=operation_id, course_id=course_id, module_id=module_id,
            item_id=item_id, content=content, expected_item=expected_item,
            expected_items=expected_items, expected_parent_sha256=expected_parent_sha256,
            expected_parent_published=expected_parent_published, published=False))

    if not service.publication_enabled:
        return

    @mcp.tool(annotations=ToolAnnotations(read_only_hint=True))
    @validate_params
    async def prepare_module_publication(
        course_id: str, module_id: str, operation_id: str, purpose: str,
    ) -> dict[str, Any]:
        """Preview a container-only publication; token does not establish human approval."""
        publisher = service.publication(course_id, module_id)
        if publisher is None:
            return _wire({"status": "HELD", "reason": "Publication target unavailable"})
        return _wire(await publisher.prepare(operation_id=operation_id, purpose=purpose))

    @mcp.tool(annotations=ToolAnnotations(destructive_hint=True, idempotent_hint=False))
    @validate_params
    async def confirm_module_publication(
        course_id: str, module_id: str, operation_id: str, purpose: str,
        confirmation_token: str,
    ) -> dict[str, Any]:
        """Publish the exact preview only with current explicit target-specific human approval.

        Operator must configure this tool's client approval_mode=prompt. No draft
        children are released; a single uncertain send blocks replay durably.
        """
        publisher = service.publication(course_id, module_id)
        if publisher is None:
            return _wire({"status": "HELD", "reason": "Publication target unavailable"})
        return _wire(await publisher.confirm(operation_id=operation_id, purpose=purpose,
                                       confirmation_token=confirmation_token))
