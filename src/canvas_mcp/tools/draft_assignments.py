"""Draft-assignment service for the opt-in prepared-content profile.

The operator-owned adapter must supply a private, durable journal directory.
The journal records hashes and outcomes, never credentials or assignment content.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
import stat
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from ..core.client import fetch_all_paginated_results, make_canvas_request
from ..core.untrusted_content import contains_fence_markers

PROTECTED = ("published", "submission_types", "points_possible", "grading_type",
             "due_at", "unlock_at", "lock_at", "assignment_group_id", "peer_reviews",
             "automatic_peer_reviews")
SAFE_TYPES = {"on_paper", "none", "online_text_entry", "online_url", "online_upload"}


PLATFORM_HOLD = "Prepared draft content requires POSIX ownership, permissions and directory fsync; Windows is unsupported"


def private_storage_supported() -> bool:
    """Do not substitute Windows mode bits for an independently verified ACL."""
    return sys.platform != "win32" and os.name == "posix" and callable(getattr(os, "getuid", None))


def digest(value: Any) -> str:
    """Canonical exact preimage digest for a read assignment."""
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                     ensure_ascii=False).encode()).hexdigest()


def _creation_fields(content: dict[str, Any]) -> bool:
    required = {"name", "description", "submission_type", "points_possible", "assignment_group_id", "due_at"}
    if not required <= content.keys():
        return False
    points = content["points_possible"]
    if type(points) not in (int, float) or not math.isfinite(points) or points < 0 or not _id(content["assignment_group_id"]):
        return False
    due = content["due_at"]
    if due is None:
        return True  # Explicitly reviewed no-due-date, not an inferred date.
    if not isinstance(due, str) or re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z", due) is None:
        return False
    try:
        datetime.fromisoformat(due.replace("Z", "+00:00"))
    except ValueError:
        return False
    return True


def _sync_directory(path: Path) -> None:
    """Persist receipt directory entries as well as their file contents."""
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _result(status: str, reason: str, assignment_id: str | None = None) -> dict[str, Any]:
    return {"status": status, "reason": reason, "assignment_id": assignment_id}


def _id(value: Any) -> bool:
    return isinstance(value, str) and re.fullmatch(r"[1-9][0-9]*", value) is not None


def _bound(value: Any, course: str, assignment: str | None = None) -> bool:
    return (isinstance(value, dict) and "error" not in value
            and type(value.get("course_id")) in (int, str)
            and str(value["course_id"]) == course
            and type(value.get("id")) in (int, str) and _id(str(value["id"]))
            and (assignment is None or str(value["id"]) == assignment)
            and value.get("published") is False)


class DraftAssignmentService:
    """Narrow service behind the separate prepared-content MCP profile.

    Numeric IDs only. Updates change name/description, never grade metadata.
    Never retries an operation ID, including across restarts or uncertain writes.
    """

    def __init__(self, journal: Path):
        self.journal = journal

    def initialize_journal(self) -> None:
        """Initialize the exact operator-selected journal, never repair existing paths."""
        if not private_storage_supported():
            raise ValueError(PLATFORM_HOLD)
        if self.journal.resolve() != self.journal.absolute():
            raise ValueError("Journal must be an operator-owned real directory")
        self.journal.mkdir(mode=0o700, parents=True, exist_ok=True)
        info = self.journal.lstat()
        if (self.journal.resolve() != self.journal.absolute()
                or not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid()
                or stat.S_IMODE(info.st_mode) != 0o700):
            raise ValueError("Journal must be an operator-owned real directory")
        _sync_directory(self.journal.parent)

    def _claim(self, operation: str, binding: dict[str, Any]) -> Path | None:
        if not private_storage_supported():
            raise ValueError(PLATFORM_HOLD)
        if re.fullmatch(r"[A-Za-z0-9_-]{1,100}", operation) is None:
            return None
        self.initialize_journal()
        path = self.journal / (operation + ".json")
        try:
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            return None
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump({"status": "INTENT", "binding_sha256": digest(binding)}, stream)
            stream.flush()
            os.fsync(stream.fileno())
        # Bind identical request content across caller-selected operation IDs.
        # A partial claim is deliberately retained on failure, never replayed.
        try:
            binding_fd = os.open(self.journal / ("binding-" + digest(binding) + ".claim"),
                                 os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            return None
        with os.fdopen(binding_fd, "w", encoding="utf-8") as stream:
            stream.write(operation)
            stream.flush()
            os.fsync(stream.fileno())
        # Persist the directory entry before allowing a network write.
        directory = os.open(self.journal, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
        return path

    @staticmethod
    def _finish(path: Path, result: dict[str, Any]) -> dict[str, Any]:
        # Exclusive result creation preserves intent even if finishing is interrupted.
        with path.with_suffix(".result.json").open("x", encoding="utf-8") as stream:
            json.dump(result, stream)
            stream.flush()
            os.fsync(stream.fileno())
        _sync_directory(path.parent)
        return result

    async def execute(self, *, operation_id: str, course_id: str,
                      content: dict[str, Any], published: bool = False,
                      assignment_id: str | None = None,
                      expected_sha256: str | None = None) -> dict[str, Any]:
        """Create a draft, or update an exact fresh unpublished preimage.

        Explicit true, coercible booleans, unknown fields and side-effect controls
        are rejected before any request. An intent claim precedes every request.
        Existing intent IDs require reconciliation, never another write.
        """
        if not private_storage_supported():
            return _result("HELD", PLATFORM_HOLD)
        allowed = {"name", "description"} if assignment_id is not None else {
            "name", "description", "submission_type", "points_possible", "assignment_group_id", "due_at"}
        if (published is not False or not _id(course_id)
                or (assignment_id is not None and not _id(assignment_id))
                or not isinstance(content, dict) or not content or set(content) - allowed
                or any(not isinstance(v, str) or contains_fence_markers(v)
                       for k, v in content.items() if k not in {"points_possible", "due_at"})
                or (assignment_id is None and not _creation_fields(content))
                or ("name" in content and not content["name"].strip())
                or (assignment_id is None and not content.get("name"))
                or content.get("submission_type", "on_paper") not in SAFE_TYPES
                or (assignment_id is not None and (not isinstance(expected_sha256, str)
                    or re.fullmatch(r"[0-9a-f]{64}", expected_sha256) is None))):
            return _result("HELD", "Invalid draft-only request")
        binding = {"course": course_id, "assignment": assignment_id,
                   "content": content, "preimage": expected_sha256}
        path = self._claim(operation_id, binding)
        if path is None:
            return _result("HELD", "Invalid or already-used operation ID; reconcile saved intent")
        endpoint = f"/courses/{course_id}/assignments"
        before = None
        saved_id = assignment_id
        try:
            if assignment_id is None:
                groups = await fetch_all_paginated_results(f"/courses/{course_id}/assignment_groups")
                group_id = content["assignment_group_id"]
                if (not isinstance(groups, list) or any(not isinstance(g, dict) or not _id(str(g.get("id", "")))
                        or ("course_id" in g and str(g["course_id"]) != course_id) for g in groups)
                        or sum(str(g["id"]) == group_id for g in groups) != 1):
                    return self._finish(path, _result("HELD", "Assignment group not verified in exact course"))
            if assignment_id is not None:
                endpoint = f"/courses/{course_id}/assignments/{assignment_id}"
                before = await make_canvas_request("get", f"/courses/{course_id}/assignments/{assignment_id}")
                if (not _bound(before, course_id, assignment_id)
                        or digest(before) != expected_sha256
                        or any(k not in before for k in PROTECTED)
                        or before.get("is_quiz_assignment") is not False
                        or before.get("discussion_topic") is not None
                        or not isinstance(before.get("submission_types"), list)
                        or not before["submission_types"]
                        or not all(t in SAFE_TYPES for t in before["submission_types"])):
                    return self._finish(path, _result("HELD", "Preimage is not exact, ordinary and unpublished"))
            data = {f"assignment[{k}]": v for k, v in content.items() if k != "submission_type"}
            if assignment_id is None:
                data["assignment[published]"] = "false"
                data["assignment[grading_type]"] = "points"
                data["assignment[post_to_sis]"] = "false"
                data["assignment[due_at]"] = content["due_at"] or ""
                data["assignment[submission_types][]"] = content.get("submission_type", "on_paper")
                data["assignment[peer_reviews]"] = "false"
                data["assignment[automatic_peer_reviews]"] = "false"
            try:
                response = await make_canvas_request("put" if assignment_id else "post", endpoint,
                                                    data=data, use_form_data=True,
                                                    retry_rate_limits=False)
            except Exception:
                return self._finish(path, _result("UNKNOWN", "Write outcome uncertain; reconcile before retry"))
            if not _bound(response, course_id, assignment_id):
                return self._finish(path, _result("UNKNOWN", "Write response lacks exact draft identity; reconcile"))
            saved_id = str(response["id"])
            with path.with_suffix(".dispatch.json").open("x", encoding="utf-8") as stream:
                json.dump({"assignment_id": saved_id, "course_id": course_id}, stream)
                stream.flush()
                os.fsync(stream.fileno())
            _sync_directory(path.parent)
            readback = await make_canvas_request("get", f"/courses/{course_id}/assignments/{saved_id}")
            valid = (_bound(readback, course_id, saved_id)
                     and all(k in readback and (str(readback[k]) == v if k == "assignment_group_id" else readback[k] == v)
                             for k, v in content.items() if k != "submission_type"))
            if valid and before is not None:
                valid = all(k in readback and readback[k] == before[k] for k in PROTECTED)
            elif valid:
                valid = (readback.get("submission_types") == [content.get("submission_type", "on_paper")]
                         and readback.get("peer_reviews") is False
                         and readback.get("automatic_peer_reviews") is False
                         and readback.get("is_quiz_assignment") is False
                         and readback.get("discussion_topic") is None
                         and readback.get("grading_type") == "points"
                         and type(readback.get("points_possible")) in (int, float)
                         and math.isfinite(readback["points_possible"])
                         and readback.get("has_overrides") is False
                         and readback.get("post_to_sis") is False
                         and "unlock_at" in readback and readback["unlock_at"] is None
                         and "lock_at" in readback and readback["lock_at"] is None)
            return self._finish(path, _result("VERIFIED_DRAFT" if valid else "UNVERIFIED",
                                             "Independent readback matched" if valid else "Readback mismatch; reconcile",
                                             saved_id))
        except Exception:
            # Conservative even when the failure preceded dispatch; intent remains blocked.
            return _result("UNVERIFIED", "Evidence unavailable; reconcile saved intent", saved_id)
