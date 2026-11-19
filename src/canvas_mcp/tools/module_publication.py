"""Opt-in, prepared container-only publication; no generic module updater.

The client must obtain current target-specific human publication approval.
Confirmation tokens bind the preview, not the fact of human approval. Operator
registration/allowlists remain a separate boundary. Draft-containing modules are
unsupported: every existing item and linked ordinary assignment must already be
explicitly published, even if Canvas ignores ``skip_content_tags``.
"""
from __future__ import annotations

import copy
import json
import re
from pathlib import Path
from typing import Any

from ..core.client import fetch_all_paginated_results, make_canvas_request
from ..core.untrusted_content import contains_fence_markers
from ..core.write_confirmation import ConfirmationClaim, ConfirmationGuard
from ..core.write_outcome import WriteOutcome
from .draft_assignments import (
    PLATFORM_HOLD,
    PROTECTED,
    SAFE_TYPES,
    DraftAssignmentService,
    _id,
    digest,
    private_storage_supported,
)

# Only the intentional publication state and its timestamp may change. Linked
# content, items and every other returned module field must match in full.
_REQUIRED_PARENT_FIELDS = frozenset({
    "id", "name", "position", "unlock_at", "require_sequential_progress",
    "prerequisite_module_ids", "publish_final_grade", "published", "items_count",
})
_ITEM_TYPES = frozenset({"Assignment", "SubHeader", "ExternalUrl"})
_EFFECT = "Publish only this module container; preserve every item and linked assignment"


def _reply(status: str, reason: str, **facts: Any) -> dict[str, Any]:
    return {"status": status, "reason": reason, **facts}


def _exact_id(value: Any, expected: str) -> bool:
    return type(value) in (str, int) and _id(str(value)) and str(value) == expected


class ModulePublicationService:
    """One fixed course/module, default off, preview then one guarded PUT.

    The constructor is operator-owned configuration, never arbitrary tool input.
    No grade, comment, enrollment, requirement, item or assignment writes exist.
    A durable existing journal blocks replay across tokens/process restarts.
    """

    def __init__(self, journal: Path, *, course_id: str, module_id: str,
                 enabled: bool = False):
        if not _id(course_id) or not _id(module_id):
            raise ValueError("Publication requires fixed numeric course/module IDs")
        if type(enabled) is not bool:
            raise ValueError("Publication enablement must be an operator boolean")
        self.course_id = course_id
        self.module_id = module_id
        self.enabled = enabled
        self.receipts = DraftAssignmentService(journal)
        self.guard = ConfirmationGuard(nothing_done="Nothing was published.")

    @property
    def _base(self) -> str:
        return f"/courses/{self.course_id}/modules/{self.module_id}"

    def _inputs(self, operation_id: str, purpose: str) -> bool:
        return (isinstance(operation_id, str)
                and re.fullmatch(r"[A-Za-z0-9_-]{1,100}", operation_id) is not None
                and isinstance(purpose, str) and 0 < len(purpose.strip()) <= 1000
                and not contains_fence_markers(purpose))

    def _parent(self, value: Any, count: int | None = None) -> dict[str, Any]:
        if (not isinstance(value, dict) or "error" in value
                or not _REQUIRED_PARENT_FIELDS <= value.keys()
                or not _exact_id(value["id"], self.module_id)
                or ("course_id" in value and not _exact_id(value["course_id"], self.course_id))
                or type(value["published"]) is not bool
                or type(value["position"]) is not int or value["position"] < 1
                or type(value["items_count"]) is not int or value["items_count"] < 0
                or (count is not None and value["items_count"] != count)
                or not (value["publish_final_grade"] is False or value["publish_final_grade"] is None)
                or ("workflow_state" in value and value["workflow_state"] not in {"active", "unpublished"})
                or not isinstance(value["name"], str)
                or type(value["require_sequential_progress"]) is not bool
                or not isinstance(value["prerequisite_module_ids"], list)
                or any(type(i) not in (str, int) or not _id(str(i))
                       for i in value["prerequisite_module_ids"])):
            raise ValueError("Exact module identity/settings/visibility unavailable")
        return {key: copy.deepcopy(field) for key, field in value.items()
                if key not in {"updated_at", "workflow_state"}}

    async def _snapshot(self) -> dict[str, Any]:
        parent = self._parent(await make_canvas_request("get", f"/courses/{self.course_id}/modules/{self.module_id}"))
        items = await fetch_all_paginated_results(self._base + "/items")
        if not isinstance(items, list):
            raise ValueError("Complete module inventory unavailable")
        ids: list[str] = []
        assignments: dict[str, Any] = {}
        for position, item in enumerate(items, 1):
            if (not isinstance(item, dict) or "error" in item
                    or type(item.get("id")) not in (str, int) or not _id(str(item["id"]))
                    or not _exact_id(item.get("module_id"), self.module_id)
                    or item.get("published") is not True
                    or item.get("type") not in _ITEM_TYPES
                    or type(item.get("position")) is not int or item["position"] != position):
                raise ValueError("Draft, unsupported or ambiguous module item; publication held")
            ids.append(str(item["id"]))
            if item["type"] == "Assignment":
                assignment_id = item.get("content_id")
                if type(assignment_id) not in (str, int) or not _id(str(assignment_id)):
                    raise ValueError("Linked assignment identity unavailable")
                key = str(assignment_id)
                assignment = await make_canvas_request(
                    "get", f"/courses/{self.course_id}/assignments/{key}")
                if (not isinstance(assignment, dict) or "error" in assignment
                        or not _exact_id(assignment.get("id"), key)
                        or not _exact_id(assignment.get("course_id"), self.course_id)
                        or assignment.get("published") is not True
                        or assignment.get("is_quiz_assignment") is not False
                        or assignment.get("discussion_topic") is not None
                        or not (set(PROTECTED) | {"name", "description"}) <= assignment.keys()
                        or not isinstance(assignment.get("submission_types"), list)
                        or not assignment["submission_types"]
                        or any(t not in SAFE_TYPES for t in assignment["submission_types"])):
                    raise ValueError("Linked assignment is not exact, ordinary and already published")
                if key in assignments:
                    raise ValueError("Repeated linked assignment; reconcile module inventory")
                assignments[key] = copy.deepcopy(assignment)
            elif item["type"] == "ExternalUrl" and not isinstance(item.get("external_url"), str):
                raise ValueError("External link metadata unavailable")
            elif item["type"] == "SubHeader" and not isinstance(item.get("title"), str):
                raise ValueError("Header metadata unavailable")
        if len(ids) != len(set(ids)):
            raise ValueError("Repeated module item identity")
        # Recheck parent after all paginated items/content reads, before claiming.
        after_parent = self._parent(await make_canvas_request("get", f"/courses/{self.course_id}/modules/{self.module_id}"), len(items))
        if parent != after_parent:
            raise ValueError("Module changed during inspection")
        return {"parent": parent, "items": copy.deepcopy(items), "assignments": assignments}

    def _fingerprint(self, operation_id: str, purpose: str, snapshot: dict[str, Any]) -> str:
        return self.guard.fingerprint("module-container-publication", json.dumps({
            "operation_id": operation_id, "course_id": self.course_id,
            "module_id": self.module_id, "purpose": purpose, "effect": _EFFECT,
            "snapshot": snapshot,
        }, sort_keys=True, separators=(",", ":"), ensure_ascii=False))

    async def prepare(self, *, operation_id: str, purpose: str) -> dict[str, Any]:
        """Preview only. Obtain explicit current approval through client tool approval.

        The returned token binds exact effects/target/state and is not human
        authorization. This method performs only GETs and no journal mutation.
        """
        if self.enabled is not True:
            return _reply("HELD", "Module publication profile is disabled")
        if not private_storage_supported():
            return _reply("HELD", PLATFORM_HOLD)
        if not self._inputs(operation_id, purpose):
            return _reply("HELD", "Invalid publication operation or purpose")
        try:
            snapshot = await self._snapshot()
            if snapshot["parent"]["published"] is not False:
                return _reply("HELD", "Module is already published; reconcile prior effects")
            return _reply("REVIEW", "Show exact preview and obtain current scoped client approval before confirm",
                          course_id=self.course_id, module_id=self.module_id, purpose=purpose,
                          effect=_EFFECT, expected_parent_published=False,
                          intended_parent_published=True, item_count=len(snapshot["items"]),
                          items=[{k: item[k] for k in ("id", "type", "position", "published", "content_id", "title")
                                  if k in item} for item in snapshot["items"]],
                          linked_assignment_ids=list(snapshot["assignments"]),
                          snapshot_sha256=digest(snapshot),
                          confirmation_token=self.guard.issue(self._fingerprint(operation_id, purpose, snapshot)),
                          approval_requirement="Explicit target-specific publication approval in the MCP client; token alone is insufficient")
        except Exception:
            return _reply("HELD", "Exact safe publication evidence unavailable; no write attempted")

    async def confirm(self, *, operation_id: str, purpose: str,
                      confirmation_token: str) -> dict[str, Any]:
        """Publish only after explicit current scoped approval in the MCP client.

        This method cannot attest human approval. The operator must separately
        expose it through a client approval boundary; no boolean can replace it.
        """
        if self.enabled is not True:
            return _reply("HELD", "Module publication profile is disabled")
        if not private_storage_supported():
            return _reply("HELD", PLATFORM_HOLD)
        if not self._inputs(operation_id, purpose):
            return _reply("HELD", "Invalid publication operation or purpose")
        try:
            snapshot = await self._snapshot()
        except Exception:
            # An authentic token cannot be restored by reverting invalid state.
            self.guard.check(confirmation_token, self.guard.fingerprint("unsafe-publication-state"))
            return _reply("HELD", "Fresh safe publication state unavailable; preview again after reconciliation")
        claim = self.guard.claim(confirmation_token, self._fingerprint(operation_id, purpose, snapshot))
        if not isinstance(claim, ConfirmationClaim):
            return _reply("HELD", claim)
        # No await between exact snapshot validation, token claim and durable intent.
        try:
            if snapshot["parent"]["published"] is not False:
                return _reply("HELD", "Module is already published; reconcile prior effects")
            intent = self.receipts._claim(operation_id, {
                "course_id": self.course_id, "module_id": self.module_id,
                "effect": _EFFECT,
            })
            if intent is None:
                return _reply("HELD", "Existing publication intent; reconcile, never retry")
            self.receipts._finish(intent.with_name(intent.stem + ".dispatch.json"), {
                "course_id": self.course_id, "module_id": self.module_id,
                "effect": _EFFECT, "preimage_sha256": digest(snapshot),
            })
            try:
                response = await make_canvas_request(
                    "put", self._base,
                    data={"module[published]": "true", "module[skip_content_tags]": "true"},
                    use_form_data=True, retry_rate_limits=False)
            except Exception:
                return self.receipts._finish(intent, _reply("UNKNOWN", "Publication dispatch uncertain; reconcile without retry",
                                                           course_id=self.course_id, module_id=self.module_id))
            if (not isinstance(response, dict) or "error" in response
                    or not _exact_id(response.get("id"), self.module_id)):
                return self.receipts._finish(intent, _reply("UNKNOWN", "No reliable publication response; reconcile without retry",
                                                           course_id=self.course_id, module_id=self.module_id))
            result = _reply("UNVERIFIED", "Independent full readback unavailable or mismatched; reconcile without retry",
                            course_id=self.course_id, module_id=self.module_id)
            try:
                after = await self._snapshot()
                expected = copy.deepcopy(snapshot)
                expected["parent"]["published"] = True
                if after == expected:
                    result = _reply("VERIFIED_PUBLISHED", "Independent parent/items/linked-content readback matched",
                                    course_id=self.course_id, module_id=self.module_id,
                                    item_count=len(after["items"]), snapshot_sha256=digest(after))
            except Exception:
                pass  # The durable intent prohibits replay even when GET fails.
            return self.receipts._finish(intent, result)
        except Exception:
            return _reply("UNKNOWN", "Publication journal or dispatch evidence incomplete; reconcile saved intent")
        finally:
            # Never release a token after a confirm attempt, including uncertainty.
            claim.finish(WriteOutcome.MAY_HAVE_WRITTEN)
