"""Operator-selected, prepared assignment-only MCP profile; no general writers."""
from __future__ import annotations

import hashlib
import json
import os
import stat
from pathlib import Path
from typing import Any

from fastmcp import FastMCP
from mcp.types import ToolAnnotations

from ..core.client import fetch_all_paginated_results, make_canvas_request
from ..core.validation import validate_params
from .draft_assignments import (
    PLATFORM_HOLD,
    DraftAssignmentService,
    _bound,
    _creation_fields,
    _id,
    _result,
    digest,
    private_storage_supported,
)
from .draft_module_items import DraftModuleItems

WRITER = "apply_prepared_draft_assignment"
READER = "inspect_prepared_draft_assignment"
MODULE_WRITER = "apply_prepared_draft_module_item"


class PreparedAssignments:
    """Pinned private manifest; tool input can select but never alter its contents."""

    def __init__(self, manifest: Path, expected_sha256: str, journal: Path):
        self.manifest = manifest
        self.expected_sha256 = expected_sha256
        self.service = DraftAssignmentService(journal)
        self.module_items = DraftModuleItems(journal / "module-items")
        self.entries()  # Refuse invalid source before registering any tool.

    def entries(self) -> dict[str, Any]:
        if not private_storage_supported():
            raise ValueError(PLATFORM_HOLD)
        path = self.manifest
        info = path.stat()
        if (path.resolve() != path.absolute() or not stat.S_ISREG(info.st_mode)
                or info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o600
                or info.st_size > 1024 * 1024):
            raise ValueError("Manifest must be private, operator-owned and regular")
        raw = path.read_bytes()
        if hashlib.sha256(raw).hexdigest() != self.expected_sha256:
            raise ValueError("Prepared manifest changed")
        value = json.loads(raw)
        if not isinstance(value, dict) or (set(value) - {"schema_version", "assignments", "module_items"} or not {"schema_version", "assignments"} <= set(value)) or value["schema_version"] != 1:
            raise ValueError("Unsupported manifest")
        entries = value["assignments"]
        if not isinstance(entries, dict) or (not entries and not value.get("module_items")):
            raise ValueError("Manifest requires named assignments")
        operations = set()
        for entry in entries.values():
            if (not isinstance(entry, dict) or set(entry) - {"operation_id", "course_id", "content", "published",
                    "assignment_id", "expected_sha256", "existing_assignment_ids"}
                    or not {"operation_id", "course_id", "content", "published"} <= set(entry)
                    or entry["published"] is not False or not _id(entry["course_id"])
                    or not isinstance(entry["operation_id"], str) or entry["operation_id"] in operations):
                raise ValueError("Invalid or repeated prepared assignment")
            operations.add(entry["operation_id"])
            if entry.get("assignment_id") is None:
                ids = entry.get("existing_assignment_ids")
                if not isinstance(ids, list) or not all(_id(i) for i in ids) or len(ids) != len(set(ids)):
                    raise ValueError("Creation requires exact reviewed course assignment inventory")
            elif not _id(entry["assignment_id"]) or not isinstance(entry.get("expected_sha256"), str):
                raise ValueError("Update requires exact assignment and preimage")
        modules = value.get("module_items", {})
        if not isinstance(modules, dict):
            raise ValueError("Invalid module item manifest")
        for entry in modules.values():
            if (not isinstance(entry, dict) or set(entry) - {"operation_id", "course_id", "module_id",
                    "item_type", "position", "existing_item_ids", "published", "title", "assignment_id"}
                    or not {"operation_id", "course_id", "module_id", "item_type", "position", "existing_item_ids", "published"} <= set(entry)
                    or entry["published"] is not False or entry["item_type"] not in {"Assignment", "SubHeader"}
                    or entry["operation_id"] in operations):
                raise ValueError("Invalid or repeated module entry")
            operations.add(entry["operation_id"])
        self.prepared_modules = modules
        return entries

    async def inspect(self, key: str) -> dict[str, Any]:
        """Read preconditions without claiming intent or changing any local state."""
        try:
            entry = self.entries()[key]
            course = entry["course_id"]
            assignment = entry.get("assignment_id")
            if assignment is not None:
                value = await make_canvas_request("get", f"/courses/{course}/assignments/{assignment}")
                if not _bound(value, course, assignment):
                    return _result("HELD", "Target is not exact and unpublished")
                return {"status": "REVIEW", "assignment_id": assignment, "preimage_sha256": digest(value),
                        "matches_prepared_preimage": digest(value) == entry["expected_sha256"]}
            if not _creation_fields(entry["content"]):
                return _result("HELD", "Canonical creation metadata incomplete or invalid")
            values = await fetch_all_paginated_results(f"/courses/{course}/assignments")
            if (not isinstance(values, list) or any(not isinstance(v, dict)
                    or not _id(str(v.get("id", ""))) or str(v.get("course_id")) != course
                    for v in values)):
                return _result("HELD", "Complete exact-course assignment inventory unavailable")
            ids = [str(v["id"]) for v in values]
            if (len(ids) != len(set(ids)) or set(ids) != set(entry["existing_assignment_ids"])
                    or any(v.get("name") == entry["content"].get("name") for v in values)):
                return _result("HELD", "Inventory changed or possible existing target; reconcile without creating")
            return {"status": "REVIEW", "inventory_matches": True, "count": len(ids), "prepared_content": entry["content"]}
        except Exception:
            return _result("HELD", "Manifest or read evidence unavailable")

    async def apply(self, key: str) -> dict[str, Any]:
        """Apply one immutable prepared entry; grade and publication changes absent."""
        review = await self.inspect(key)
        if review.get("status") != "REVIEW" or review.get("matches_prepared_preimage") is False:
            return _result("HELD", "Prepared preconditions not met; reconcile")
        # Re-read pinned manifest, never accept model-supplied content or paths.
        try:
            entry = dict(self.entries()[key])
            entry.pop("existing_assignment_ids", None)
            return await self.service.execute(**entry)
        except Exception:
            return _result("HELD", "Prepared execution unavailable; inspect saved intent before retry")


def register_draft_content_tools(mcp: FastMCP, prepared: PreparedAssignments) -> None:
    """Expose one bounded reader and one bounded writer, no grade/publish routes."""
    @mcp.tool(annotations=ToolAnnotations(destructive_hint=False, idempotent_hint=False))
    @validate_params
    async def apply_prepared_draft_module_item(key: str) -> dict[str, Any]:
        """Add a prepared unpublished test header or exact unpublished assignment link."""
        try:
            prepared.entries()
            return await prepared.module_items.execute(**prepared.prepared_modules[key])
        except Exception:
            return _result("HELD", "Prepared module entry unavailable; reconcile any saved intent")

    @mcp.tool(annotations=ToolAnnotations(read_only_hint=True))
    @validate_params
    async def inspect_prepared_draft_assignment(key: str) -> dict[str, Any]:
        """Inspect a named prepared assignment without writing local or Canvas state."""
        return await prepared.inspect(key)

    @mcp.tool(annotations=ToolAnnotations(destructive_hint=False, idempotent_hint=False))
    @validate_params
    async def apply_prepared_draft_assignment(key: str) -> dict[str, Any]:
        """Apply an authorized named draft only; cannot push grades or change Published."""
        return await prepared.apply(key)
