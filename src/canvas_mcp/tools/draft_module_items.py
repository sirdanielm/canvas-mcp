"""Narrow unpublished SubHeader/Assignment item service, no publication tools."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from ..core.client import fetch_all_paginated_results, make_canvas_request
from ..core.untrusted_content import contains_fence_markers
from .draft_assignments import DraftAssignmentService, _bound, _id, _result


def _parent(value: Any, course: str, module: str) -> bool:
    return (isinstance(value, dict) and "error" not in value
            and type(value.get("id")) in (str, int) and str(value["id"]) == module
            and ("course_id" not in value or str(value["course_id"]) == course)
            and value.get("published") is False)


class DraftModuleItems:
    """Only append a prepared positioned item; never update an existing module."""

    def __init__(self, journal: Path):
        self.receipts = DraftAssignmentService(journal)

    async def execute(self, *, operation_id: str, course_id: str, module_id: str,
                      item_type: str, position: int, existing_item_ids: list[str],
                      published: bool = False, title: str | None = None,
                      assignment_id: str | None = None) -> dict[str, Any]:
        if (published is not False or not _id(course_id) or not _id(module_id)
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
        intent = self.receipts._claim(operation_id, binding)
        if intent is None:
            return _result("HELD", "Existing or invalid operation; reconcile")
        base = f"/courses/{course_id}/modules/{module_id}"
        try:
            parent = await make_canvas_request("get", base)
            if not _parent(parent, course_id, module_id):
                return self.receipts._finish(intent, _result("HELD", "Parent is not exact and unpublished"))
            assignment = None
            if assignment_id is not None:
                assignment = await make_canvas_request("get", f"/courses/{course_id}/assignments/{assignment_id}")
                if not _bound(assignment, course_id, assignment_id):
                    return self.receipts._finish(intent, _result("HELD", "Linked assignment is not exact and unpublished"))
            items = await fetch_all_paginated_results(base + "/items")
            if (not isinstance(items, list) or any(not isinstance(i, dict) or not _id(str(i.get("id", "")))
                    or str(i.get("module_id")) != module_id for i in items)
                    or len(items) != len(existing_item_ids)
                    or {str(i["id"]) for i in items} != set(existing_item_ids)
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
            try:
                response = await make_canvas_request("post", base + "/items", data=data,
                                                     use_form_data=True, retry_rate_limits=False)
            except Exception:
                return self.receipts._finish(intent, _result("UNKNOWN", "Write uncertain; reconcile"))
            if (not isinstance(response, dict) or "error" in response
                    or not _id(str(response.get("id", "")))):
                return self.receipts._finish(intent, _result("UNKNOWN", "No reliable created-item identity"))
            item_id = str(response["id"])
            # Save the known ID before any readback, including failures.
            self.receipts._finish(intent.with_name(intent.stem + ".dispatch.json"),
                                  {"item_id": item_id, "module_id": module_id, "course_id": course_id})
            result = {"status": "UNVERIFIED", "item_id": item_id, "reason": "Readback unavailable or mismatched"}
            try:
                item = await make_canvas_request("get", f"/courses/{course_id}/modules/{module_id}/items/{item_id}")
                after_parent = await make_canvas_request("get", base)
                valid = (isinstance(item, dict) and str(item.get("id")) == item_id
                         and str(item.get("module_id")) == module_id and item.get("published") is False
                         and item.get("type") == item_type and type(item.get("position")) is int
                         and item["position"] == position and _parent(after_parent, course_id, module_id))
                if assignment_id is not None:
                    after = await make_canvas_request("get", f"/courses/{course_id}/assignments/{assignment_id}")
                    valid = valid and str(item.get("content_id")) == assignment_id and _bound(after, course_id, assignment_id)
                else:
                    valid = valid and item.get("title") == title
                if valid:
                    result.update(status="VERIFIED_DRAFT", reason="Independent item/parent/content readback matched")
            except Exception:
                pass  # Durable known identity remains available for reconciliation.
            return self.receipts._finish(intent, result)
        except Exception:
            return _result("UNVERIFIED", "Evidence unavailable; reconcile saved intent")
