"""Verified description-only edits through the existing assignment API route."""

import math
from collections.abc import Awaitable, Callable
from hashlib import sha256
from typing import Any

from ..core.write_outcome import RequestFailure, WriteOutcome

_UNCHANGED = (
    "id",
    "course_id",
    "name",
    "published",
    "points_possible",
    "submission_types",
    "due_at",
    "unlock_at",
    "lock_at",
)
_OPTIONAL_UNCHANGED = (
    "grading_type",
    "assignment_group_id",
    "peer_reviews",
    "automatic_peer_reviews",
    "allowed_extensions",
    "external_tool_tag_attributes",
)


def _same_metadata(before: Any, after: Any) -> bool:
    """Preserve native types as well as values (False must never equal zero)."""
    if type(before) is not type(after):
        return False
    if isinstance(before, dict):
        return before.keys() == after.keys() and all(
            _same_metadata(value, after[key]) for key, value in before.items()
        )
    if isinstance(before, list):
        return len(before) == len(after) and all(
            _same_metadata(left, right)
            for left, right in zip(before, after, strict=True)
        )
    return bool(before == after)


def description_sha256(description: str) -> str:
    """Hash literal UTF-8 Canvas HTML, without provenance fences."""
    return sha256(description.encode("utf-8")).hexdigest()


async def update_draft_description(
    request: Callable[..., Awaitable[Any]],
    course_id: str | int,
    assignment_id: str | int,
    description: object,
    expected_sha256: object,
) -> str:
    """Check, update once and independently verify; no time-based approval gate."""
    if (
        not isinstance(expected_sha256, str)
        or len(expected_sha256) != 64
        or any(c not in "0123456789abcdef" for c in expected_sha256)
    ):
        return "HELD: expected_description_sha256 must be a lowercase SHA-256 digest. No write attempted."
    if not isinstance(description, str):
        return "HELD: a literal HTML description is required. No write attempted."
    # Numeric IDs keep this narrow route on exactly one assignment endpoint.
    if any(
        type(value) not in (str, int)
        or not str(value).isascii()
        or not str(value).isdigit()
        or not str(value).strip("0")
        for value in (course_id, assignment_id)
    ):
        return "HELD: resolved course and assignment IDs must be numeric. No write attempted."
    endpoint = f"/courses/{course_id}/assignments/{assignment_id}"
    try:
        before = await request("get", endpoint)
    except Exception:
        return "HELD: draft preflight unavailable. No write attempted."
    if (
        not isinstance(before, dict)
        or "error" in before
        or any(key not in before for key in (*_UNCHANGED, "description"))
        or str(before["id"]) != str(assignment_id)
        or str(before["course_id"]) != str(course_id)
        or before["published"] is not False
        or not isinstance(before["description"], str)
        or not isinstance(before["name"], str)
        or type(before["points_possible"]) not in (int, float)
        or not math.isfinite(before["points_possible"])
        or before["points_possible"] < 0
        or not isinstance(before["submission_types"], list)
        or any(not isinstance(value, str) for value in before["submission_types"])
    ):
        return "HELD: exact unpublished draft and complete metadata were not established. No write attempted."
    if before["description"] == description:
        return "ALREADY_CURRENT: GET confirms the unpublished draft already contains this description. No write attempted."
    if description_sha256(before["description"]) != expected_sha256:
        return "HELD: description changed from the expected source. Rebuild this edit from current content; independent drafts may continue. No write attempted."
    try:
        response = await request(
            "put",
            endpoint,
            data={"assignment[description]": description},
            use_form_data=True,
            retry_rate_limits=False,
        )
    except Exception:
        return "UNKNOWN: update may have reached Canvas. Reconcile with GET before any further write; do not replay."
    if isinstance(response, RequestFailure) and response.outcome in (
        WriteOutcome.NOT_DISPATCHED,
        WriteOutcome.REJECTED,
    ):
        return "REJECTED: transport confirms the update was not applied. Resolve the reported access/request failure within the authorized scope."
    if (
        not isinstance(response, dict)
        or "error" in response
        or str(response.get("id")) != str(assignment_id)
    ):
        return "UNKNOWN: update was not confirmed. Reconcile with GET before any further write; do not replay."
    try:
        after = await request("get", endpoint)
    except Exception:
        return "UNKNOWN: update returned but independent GET failed. Reconcile with GET; do not replay."
    if (
        not isinstance(after, dict)
        or "error" in after
        or any(
            key not in after or not _same_metadata(before[key], after[key])
            for key in _UNCHANGED
        )
        or any(
            (key in before) != (key in after)
            or key in before
            and not _same_metadata(before[key], after[key])
            for key in _OPTIONAL_UNCHANGED
        )
        or after.get("description") != description
    ):
        return "UNVERIFIED: GET did not confirm the exact description and unchanged metadata. Inspect current state; do not replay or repair automatically."
    return (
        f"VERIFIED: assignment {assignment_id} description updated; independent GET "
        f"confirmed unpublished state and unchanged metadata. Description SHA-256: {description_sha256(description)}"
    )
