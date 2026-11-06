"""Private, observation-only Canvas submission metadata sidecar.

This module does not fetch, persist, display or match student submissions. Its
caller is responsible for private storage and authorized source provenance.
An observed native attachment is never asserted to be the downstream artifact.
"""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlsplit


class CarrierError(ValueError):
    """A generic, non-identifying carrier validation error."""


def _id(value: Any) -> str | None:
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        return None
    result = str(value)
    if (
        len(result) > 25
        or not result.isascii()
        or not result.isdecimal()
        or int(result) < 1
    ):
        return None
    return result


def _attempt(value: Any) -> int | None:
    return value if type(value) is int and value > 0 else None


def _version(attachment: dict[str, Any]) -> dict[str, str] | None:
    # Only directly supplied, typed content digests are retained. Timestamps,
    # names, URLs and IDs do not prove byte identity or version equivalence.
    value = attachment.get("sha256")
    if isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value):
        return {"kind": "reported_unverified_sha256", "value": value}
    return None


def _observation(submission: dict[str, Any]) -> dict[str, Any]:
    submission_id = _id(submission.get("id"))
    attempt = _attempt(submission.get("attempt"))
    kind = submission.get("submission_type")
    supported_types = {
        "online_upload",
        "online_text_entry",
        "online_url",
        "online_quiz",
        "media_recording",
        "student_annotation",
        "basic_lti_launch",
        "external_tool",
    }
    kind = kind if isinstance(kind, str) and kind in supported_types else None
    holds = [
        "SAME_FETCH_PROVENANCE_UNVERIFIED",
        "CURRENT_ATTEMPT_NOT_INDEPENDENTLY_VERIFIED",
        "DOWNSTREAM_ARTIFACT_BINDING_UNVERIFIED",
    ]
    if submission_id is None:
        holds.append("NATIVE_SUBMISSION_ID_UNAVAILABLE")
    if attempt is None:
        holds.append("NATIVE_ATTEMPT_UNAVAILABLE")
    attachments: list[dict[str, Any]] = []
    if kind != "online_upload":
        holds.append("SUBMISSION_TYPE_UNSUPPORTED")
    else:
        raw = submission.get("attachments")
        if not isinstance(raw, list) or not raw:
            holds.append("ATTACHMENTS_UNAVAILABLE")
        else:
            seen: set[str] = set()
            for item in raw:
                if not isinstance(item, dict):
                    holds.append("ATTACHMENTS_MALFORMED")
                    continue
                item_id = _id(item.get("id"))
                if item_id is None:
                    holds.append("ATTACHMENT_ID_UNAVAILABLE")
                    continue
                if item_id in seen:
                    holds.append("DUPLICATE_ATTACHMENT_ID")
                    continue
                seen.add(item_id)
                version = _version(item)
                if version is None:
                    holds.append("ARTIFACT_VERSION_UNAVAILABLE")
                attachments.append(
                    {"canvas_attachment_id": item_id, "observed_version": version}
                )
            if len(attachments) > 1:
                holds.append("MULTIPLE_ATTACHMENTS_REQUIRE_EXACT_BINDING")
    return {
        "reported_submission_object_id": submission_id,
        "observed_attempt": attempt,
        "submission_type": kind,
        "attachments": attachments,
        "status": "HELD_OBSERVATION_ONLY",
        "holds": sorted(set(holds)),
    }


def capture_source_sidecar(
    snapshot: dict[str, Any], submissions: list[dict[str, Any]]
) -> dict[str, Any]:
    """Create a separate sidecar keyed like an existing normalized snapshot.

    It accepts the same response objects already supplied to the snapshot
    producer. It does not assert response completeness, attempt currentness,
    artifact-version authenticity or cross-system equivalence.
    """
    if (
        not isinstance(snapshot, dict)
        or type(snapshot.get("schema_version")) is not int
        or snapshot.get("schema_version") != 1
    ):
        raise CarrierError("Existing snapshot schema required.")
    course = _id(snapshot.get("course_id"))
    origin = snapshot.get("origin")
    cells = snapshot.get("cells")
    if (
        course is None
        or not isinstance(origin, str)
        or not origin
        or not isinstance(cells, dict)
    ):
        raise CarrierError("Snapshot context unavailable.")
    try:
        parsed = urlsplit(origin)
        if (
            any(ord(ch) < 32 or 127 <= ord(ch) <= 159 for ch in origin)
            or parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
            or "@" in parsed.netloc
            or "\\" in parsed.netloc
            or any(ch.isspace() for ch in parsed.netloc)
            or parsed.path not in ("", "/")
        ):
            raise CarrierError("Invalid Canvas origin.")
        _ = parsed.port  # Reject invalid ports without retaining or printing them.
        origin = origin.rstrip("/")
    except ValueError:
        raise CarrierError("Invalid Canvas origin.") from None
    for key in cells:
        if (
            not isinstance(key, str)
            or re.fullmatch(r"[0-9]{1,25}:[0-9]{1,25}", key) is None
        ):
            raise CarrierError("Snapshot cell key is malformed.")
    if not isinstance(submissions, list):
        raise CarrierError("Submission observations must be a list.")
    observed: dict[str, dict[str, Any]] = {}
    for item in submissions:
        if not isinstance(item, dict):
            raise CarrierError("Malformed submission observation.")
        user, assignment = _id(item.get("user_id")), _id(item.get("assignment_id"))
        if user is None or assignment is None:
            raise CarrierError("Submission context unavailable.")
        key = f"{user}:{assignment}"
        if key not in cells:
            # Mirror the existing snapshot's exclusion of out-of-scope records.
            continue
        if key in observed:
            raise CarrierError("Duplicate submission observation.")
        existing = cells[key]
        if not isinstance(existing, dict):
            raise CarrierError("Snapshot cell is malformed.")
        result = _observation(item)
        observed_course = _id(item.get("course_id"))
        if observed_course is None:
            result["holds"] = sorted(
                set(result["holds"]) | {"SUBMISSION_COURSE_UNAVAILABLE"}
            )
        elif observed_course != course:
            result["holds"] = sorted(
                set(result["holds"]) | {"SUBMISSION_COURSE_MISMATCH"}
            )
        snapshot_attempt = _attempt(existing.get("attempt"))
        if snapshot_attempt is None:
            result["holds"] = sorted(
                set(result["holds"]) | {"SNAPSHOT_ATTEMPT_UNAVAILABLE"}
            )
        if (
            snapshot_attempt is not None
            and result["observed_attempt"] is not None
            and snapshot_attempt != result["observed_attempt"]
        ):
            result["holds"] = sorted(
                set(result["holds"]) | {"SNAPSHOT_ATTEMPT_MISMATCH"}
            )
        observed[key] = result
    for key in sorted(cells.keys() - observed.keys()):
        observed[key] = {
            "reported_submission_object_id": None,
            "observed_attempt": None,
            "submission_type": None,
            "attachments": [],
            "status": "HELD_OBSERVATION_ONLY",
            "holds": ["SUBMISSION_OBSERVATION_UNAVAILABLE"],
        }
    return {
        "contract": "CANVAS_SOURCE_OBSERVATION_V1",
        "origin": origin,
        "course_id": course,
        "cells": observed,
        "source_mapping_authority": False,
        "scan_authority": False,
    }
