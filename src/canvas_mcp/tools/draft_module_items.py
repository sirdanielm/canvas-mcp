"""Prepared, once-only draft module-item inserts and narrow unpublished edits."""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from ..core.client import fetch_all_paginated_results, make_canvas_request
from ..core.untrusted_content import contains_fence_markers
from .draft_assignments import (
    PLATFORM_HOLD,
    SAFE_TYPES,
    DraftAssignmentService,
    _bound,
    _id,
    _result,
    digest,
    private_storage_supported,
)


def _parent(value: Any, course: str, module: str, published: bool = False) -> bool:
    return (isinstance(value, dict) and "error" not in value
            and type(value.get("id")) in (str, int) and str(value["id"]) == module
            and ("course_id" not in value or str(value["course_id"]) == course)
            and value.get("published") is published)


def _sha256(value: Any) -> bool:
    return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) is not None


def _inventory(value: Any, module: str) -> bool:
    """Require one complete, ordered module inventory, including exact positions."""
    return (isinstance(value, list)
            and all(isinstance(i, dict) and "error" not in i and _id(str(i.get("id", "")))
                    and str(i.get("module_id")) == module
                    and type(i.get("position")) is int and i["position"] == index
                    for index, i in enumerate(value, 1))
            and len({str(i["id"]) for i in value}) == len(value))


def _parent_unchanged(before: dict[str, Any], after: Any, course: str,
                      module: str, published: bool, count: int) -> bool:
    if not _parent(after, course, module, published):
        return False
    # Canvas's derived item count is the only parent field an insertion may change.
    # Requirements, sequencing, dates, published state and unknown fields stay exact.
    if (("items_count" in before) != ("items_count" in after)
            or ("items_count" in after
                and (type(after["items_count"]) is not int or after["items_count"] != count))):
        return False
    return digest({k: v for k, v in before.items() if k != "items_count"}) == digest(
        {k: v for k, v in after.items() if k != "items_count"})


def _item(value: Any, module: str, item_id: str) -> bool:
    return (isinstance(value, dict) and "error" not in value
            and _id(str(value.get("id", ""))) and str(value["id"]) == item_id
            and str(value.get("module_id")) == module and value.get("published") is False
            and value.get("type") in {"SubHeader", "Assignment"})


def _ordinary_assignment(value: Any, course: str, assignment: str) -> bool:
    """Refuse Assignment proxies that Canvas converts to quizzes/discussions/LTI."""
    return (_bound(value, course, assignment)
            and value.get("is_quiz_assignment") is False
            and value.get("discussion_topic") is None
            and isinstance(value.get("submission_types"), list)
            and bool(value["submission_types"])
            and all(isinstance(kind, str) and kind in SAFE_TYPES for kind in value["submission_types"]))


def _preserved_inventory(before: list[dict[str, Any]], after: Any, module: str,
                         item_id: str, position: int, *, edit: dict[str, Any] | None = None) -> bool:
    if not _inventory(after, module):
        return False
    old_ids = [str(i["id"]) for i in before]
    expected_ids = [i for i in old_ids if i != item_id]
    expected_ids.insert(position - 1, item_id)
    if [str(i["id"]) for i in after] != expected_ids:
        return False
    by_id = {str(i["id"]): i for i in after}
    for previous in before:
        expected = dict(previous)
        expected["position"] = expected_ids.index(str(previous["id"])) + 1
        if str(previous["id"]) == item_id and edit is not None:
            expected.update(edit)
        if digest(by_id[str(previous["id"])]) != digest(expected):
            return False
    return True


class DraftModuleItems:
    """Insert draft children or narrowly edit one, without writing their parent."""

    def __init__(self, journal: Path):
        self.receipts = DraftAssignmentService(journal)

    async def _fresh(self, base: str, course: str, module: str, parent: dict[str, Any],
                     items: list[dict[str, Any]], assignment: dict[str, Any] | None) -> bool:
        """Recheck all preimages immediately before one send, without claiming CAS.

        Canvas has no atomic conditional module-item write. A concurrent change
        after these GETs is still possible and must fail independent readback.
        """
        current_items = await fetch_all_paginated_results(base + "/items")
        if not _inventory(current_items, module) or digest(current_items) != digest(items):
            return False
        if assignment is not None:
            assignment_id = str(assignment["id"])
            current_assignment = await make_canvas_request("get", f"/courses/{course}/assignments/{assignment_id}")
            if (not _ordinary_assignment(current_assignment, course, assignment_id)
                    or digest(current_assignment) != digest(assignment)):
                return False
        current_parent = await make_canvas_request("get", f"/courses/{course}/modules/{module}")
        return (_parent(current_parent, course, module, parent["published"])
                and digest(current_parent) == digest(parent))

    async def execute(self, *, operation_id: str, course_id: str, module_id: str,
                      item_type: str, position: int, existing_item_ids: list[str],
                      published: bool = False, title: str | None = None,
                      assignment_id: str | None = None,
                      expected_parent_published: bool = False,
                      expected_parent_sha256: str | None = None,
                      expected_items: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        """Insert once. Published parents require an exact reviewed full preimage."""
        if not private_storage_supported():
            return _result("HELD", PLATFORM_HOLD)
        if (published is not False or not _id(course_id) or not _id(module_id)
                or type(expected_parent_published) is not bool
                or (expected_parent_sha256 is not None and not _sha256(expected_parent_sha256))
                or (expected_items is not None and not _inventory(expected_items, module_id))
                or (expected_parent_published and (not _sha256(expected_parent_sha256) or expected_items is None))
                or type(position) is not int or position < 1
                or not isinstance(existing_item_ids, list) or not all(_id(i) for i in existing_item_ids)
                or len(existing_item_ids) != len(set(existing_item_ids))
                or item_type not in {"SubHeader", "Assignment"}
                or (item_type == "Assignment" and (not _id(assignment_id) or title is not None))
                or (item_type == "SubHeader" and (assignment_id is not None or not isinstance(title, str)
                    or not title.strip() or contains_fence_markers(title)))):
            return _result("HELD", "Invalid draft module item request")
        binding = {"course": course_id, "module": module_id, "type": item_type,
                   "position": position, "inventory": existing_item_ids,
                   "title": title, "assignment": assignment_id}
        # Preserve the legacy binding for unchanged, default-unpublished manifests.
        if expected_parent_published or expected_parent_sha256 is not None or expected_items is not None:
            binding.update(parent_published=expected_parent_published,
                           parent_preimage=expected_parent_sha256, expected_items=expected_items)
        intent = self.receipts._claim(operation_id, binding)
        if intent is None:
            return _result("HELD", "Existing or invalid operation; reconcile")
        base = f"/courses/{course_id}/modules/{module_id}"
        try:
            parent = await make_canvas_request("get", base)
            if (not _parent(parent, course_id, module_id, expected_parent_published)
                    or (expected_parent_sha256 is not None and digest(parent) != expected_parent_sha256)):
                return self.receipts._finish(intent, _result("HELD", "Parent state or preimage changed"))
            assignment = None
            if assignment_id is not None:
                assignment = await make_canvas_request("get", f"/courses/{course_id}/assignments/{assignment_id}")
                if not _ordinary_assignment(assignment, course_id, assignment_id):
                    return self.receipts._finish(intent, _result("HELD", "Linked assignment is not exact and unpublished"))
            items = await fetch_all_paginated_results(base + "/items")
            if (not _inventory(items, module_id) or position > len(items) + 1
                    or {str(i["id"]) for i in items} != set(existing_item_ids)
                    or ("items_count" in parent and (type(parent["items_count"]) is not int
                        or parent["items_count"] != len(items)))
                    or (expected_items is not None and (digest(items) != digest(expected_items)
                        or [str(i["id"]) for i in items] != existing_item_ids))
                    or ("items_count" in parent and (type(parent["items_count"]) is not int
                        or parent["items_count"] != len(items)))
                    or any((item_type == "Assignment" and i.get("type") == "Assignment"
                            and str(i.get("content_id")) == assignment_id)
                           or (item_type == "SubHeader" and i.get("type") == "SubHeader"
                               and i.get("title") == title) for i in items)):
                return self.receipts._finish(intent, _result("HELD", "Item inventory changed or target already present"))
            data: dict[str, Any] = {"module_item[type]": item_type, "module_item[published]": "false",
                                    "module_item[position]": position}
            if assignment_id is not None:
                data["module_item[content_id]"] = assignment_id
            else:
                data["module_item[title]"] = title
            if not await self._fresh(base, course_id, module_id, parent, items, assignment):
                return self.receipts._finish(intent, _result("HELD", "Final parent, inventory or linked assignment changed"))
            try:
                response = await make_canvas_request("post", base + "/items", data=data,
                                                     use_form_data=True, retry_rate_limits=False)
            except Exception:
                return self.receipts._finish(intent, _result("UNKNOWN", "Write uncertain; reconcile"))
            if (not isinstance(response, dict) or "error" in response
                    or not _id(str(response.get("id", "")))
                    or str(response["id"]) in existing_item_ids):
                return self.receipts._finish(intent, _result("UNKNOWN", "No reliable created-item identity"))
            item_id = str(response["id"])
            # Save the known ID before any readback, including failures.
            self.receipts._finish(intent.with_name(intent.stem + ".dispatch.json"),
                                  {"item_id": item_id, "module_id": module_id, "course_id": course_id})
            result = {"status": "UNVERIFIED", "item_id": item_id, "reason": "Readback unavailable or mismatched"}
            try:
                item = await make_canvas_request("get", f"/courses/{course_id}/modules/{module_id}/items/{item_id}")
                after_parent = await make_canvas_request("get", base)
                after_items = await fetch_all_paginated_results(base + "/items")
                valid = (_item(item, module_id, item_id) and item.get("type") == item_type
                         and type(item.get("position")) is int and item["position"] == position
                         and _parent_unchanged(parent, after_parent, course_id, module_id,
                                               expected_parent_published, len(items) + 1)
                         and _preserved_inventory(items, after_items, module_id, item_id, position)
                         and digest(after_items[position - 1]) == digest(item))
                if assignment_id is not None:
                    after = await make_canvas_request("get", f"/courses/{course_id}/assignments/{assignment_id}")
                    valid = (valid and str(item.get("content_id")) == assignment_id
                             and _ordinary_assignment(after, course_id, assignment_id)
                             and digest(after) == digest(assignment))
                else:
                    valid = valid and item.get("title") == title
                if valid:
                    result.update(status="VERIFIED_DRAFT", reason="Independent item/parent/content/inventory readback matched")
            except Exception:
                pass  # Durable known identity remains available for reconciliation.
            return self.receipts._finish(intent, result)
        except Exception:
            return _result("UNVERIFIED", "Evidence unavailable; reconcile saved intent")

    async def edit(self, *, operation_id: str, course_id: str, module_id: str,
                   item_id: str, content: dict[str, Any], expected_item: dict[str, Any],
                   expected_items: list[dict[str, Any]], expected_parent_sha256: str,
                   expected_parent_published: bool = False, published: bool = False) -> dict[str, Any]:
        """Edit exact draft position/indent, or a SubHeader title; never its content target."""
        if not private_storage_supported():
            return _result("HELD", PLATFORM_HOLD)
        if (published is not False or not all(_id(i) for i in (course_id, module_id, item_id))
                or type(expected_parent_published) is not bool or not _sha256(expected_parent_sha256)
                or not _item(expected_item, module_id, item_id) or not _inventory(expected_items, module_id)
                or not isinstance(content, dict) or not content or set(content) - {"position", "indent", "title"}
                or ("position" in content and (type(content["position"]) is not int
                    or not 1 <= content["position"] <= len(expected_items)))
                or ("indent" in content and (type(content["indent"]) is not int or not 0 <= content["indent"] <= 5))
                or ("title" in content and (expected_item.get("type") != "SubHeader"
                    or not isinstance(content["title"], str) or not content["title"].strip()
                    or contains_fence_markers(content["title"])))):
            return _result("HELD", "Invalid narrow draft item edit")
        targets = [i for i in expected_items if str(i["id"]) == item_id]
        if len(targets) != 1 or digest(targets[0]) != digest(expected_item):
            return _result("HELD", "Expected item is not the exact inventory member")
        assignment_id = None
        if expected_item["type"] == "Assignment":
            assignment_id = str(expected_item.get("content_id", ""))
            if not _id(assignment_id):
                return _result("HELD", "Exact linked assignment identity required")
        binding = {"action": "edit", "course": course_id, "module": module_id, "item": item_id,
                   "content": content, "expected_item": expected_item, "expected_items": expected_items,
                   "parent_preimage": expected_parent_sha256, "parent_published": expected_parent_published}
        intent = self.receipts._claim(operation_id, binding)
        if intent is None:
            return _result("HELD", "Existing or invalid operation; reconcile")
        base = f"/courses/{course_id}/modules/{module_id}"
        endpoint = base + f"/items/{item_id}"
        try:
            parent = await make_canvas_request("get", base)
            item = await make_canvas_request("get", f"/courses/{course_id}/modules/{module_id}/items/{item_id}")
            items = await fetch_all_paginated_results(base + "/items")
            if (not _parent(parent, course_id, module_id, expected_parent_published)
                    or digest(parent) != expected_parent_sha256
                    or not _item(item, module_id, item_id) or digest(item) != digest(expected_item)
                    or not _inventory(items, module_id) or digest(items) != digest(expected_items)
                    or ("items_count" in parent and (type(parent["items_count"]) is not int
                        or parent["items_count"] != len(items)))):
                return self.receipts._finish(intent, _result("HELD", "Parent, item or inventory preimage changed"))
            assignment = None
            if assignment_id is not None:
                assignment = await make_canvas_request("get", f"/courses/{course_id}/assignments/{assignment_id}")
                if not _ordinary_assignment(assignment, course_id, assignment_id):
                    return self.receipts._finish(intent, _result("HELD", "Linked assignment is not exact and unpublished"))
            if all(k in item and digest(item[k]) == digest(v) for k, v in content.items()):
                return self.receipts._finish(intent, {"status": "VERIFIED_NOOP", "item_id": item_id,
                                                     "reason": "Exact reviewed item already matches"})
            data = {f"module_item[{k}]": v for k, v in content.items()}
            # Canvas publication writes can propagate to other tags for the same
            # asset, even when false. A draft-only edit must omit this field.
            if not await self._fresh(base, course_id, module_id, parent, items, assignment):
                return self.receipts._finish(intent, _result("HELD", "Final parent, inventory or linked assignment changed"))
            try:
                response = await make_canvas_request("put", endpoint, data=data,
                                                     use_form_data=True, retry_rate_limits=False)
            except Exception:
                return self.receipts._finish(intent, _result("UNKNOWN", "Write uncertain; reconcile"))
            if not _item(response, module_id, item_id):
                return self.receipts._finish(intent, _result("UNKNOWN", "No reliable edited-item identity"))
            self.receipts._finish(intent.with_name(intent.stem + ".dispatch.json"),
                                  {"item_id": item_id, "module_id": module_id, "course_id": course_id})
            result = {"status": "UNVERIFIED", "item_id": item_id, "reason": "Readback unavailable or mismatched"}
            try:
                after = await make_canvas_request("get", f"/courses/{course_id}/modules/{module_id}/items/{item_id}")
                after_parent = await make_canvas_request("get", base)
                after_items = await fetch_all_paginated_results(base + "/items")
                position = content.get("position", item["position"])
                valid = (_item(after, module_id, item_id)
                         and _parent_unchanged(parent, after_parent, course_id, module_id,
                                               expected_parent_published, len(items))
                         and _preserved_inventory(items, after_items, module_id, item_id, position, edit=content)
                         and digest(after_items[position - 1]) == digest(after))
                if assignment_id is not None:
                    after_assignment = await make_canvas_request("get", f"/courses/{course_id}/assignments/{assignment_id}")
                    valid = (valid and _ordinary_assignment(after_assignment, course_id, assignment_id)
                             and digest(after_assignment) == digest(assignment))
                if valid:
                    result.update(status="VERIFIED_DRAFT", reason="Exact draft edit and unchanged parent/peers verified")
            except Exception:
                pass  # Known target remains durable and is never retried automatically.
            return self.receipts._finish(intent, result)
        except Exception:
            return _result("UNVERIFIED", "Evidence unavailable; reconcile saved intent")
