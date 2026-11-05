"""Isolated private observation persistence; never grants source authority."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import urlsplit

from .client import GradebookError


class SidecarStore(Protocol):
    """Minimal private-store interface without a runtime import dependency."""

    root: Path

    def load(self, kind: str, artifact_id: str) -> dict[str, Any]: ...

    def save(self, kind: str, value: dict[str, Any]) -> tuple[str, Path]: ...


MAX_BYTES = 1_000_000
MAX_CELLS = 2500
MAX_ATTACHMENTS = 100
HASH = re.compile(r"[0-9a-f]{64}\Z")
ID = re.compile(r"[0-9]{1,25}\Z")
CELL = re.compile(r"[0-9]{1,25}:[0-9]{1,25}\Z")
HOLD_VOCABULARY = {
    "SAME_FETCH_PROVENANCE_UNVERIFIED",
    "CURRENT_ATTEMPT_NOT_INDEPENDENTLY_VERIFIED",
    "DOWNSTREAM_ARTIFACT_BINDING_UNVERIFIED",
    "NATIVE_SUBMISSION_ID_UNAVAILABLE",
    "NATIVE_ATTEMPT_UNAVAILABLE",
    "SUBMISSION_TYPE_UNSUPPORTED",
    "ATTACHMENTS_UNAVAILABLE",
    "ATTACHMENTS_MALFORMED",
    "ATTACHMENT_ID_UNAVAILABLE",
    "DUPLICATE_ATTACHMENT_ID",
    "ARTIFACT_VERSION_UNAVAILABLE",
    "MULTIPLE_ATTACHMENTS_REQUIRE_EXACT_BINDING",
    "SUBMISSION_COURSE_UNAVAILABLE",
    "SUBMISSION_COURSE_MISMATCH",
    "SNAPSHOT_ATTEMPT_UNAVAILABLE",
    "SNAPSHOT_ATTEMPT_MISMATCH",
    "SUBMISSION_OBSERVATION_UNAVAILABLE",
}
REQUIRED_HOLDS = {
    "SAME_FETCH_PROVENANCE_UNVERIFIED",
    "CURRENT_ATTEMPT_NOT_INDEPENDENTLY_VERIFIED",
    "DOWNSTREAM_ARTIFACT_BINDING_UNVERIFIED",
}
KINDS = {
    "online_upload",
    "online_text_entry",
    "online_url",
    "online_quiz",
    "media_recording",
    "student_annotation",
    "basic_lti_launch",
    "external_tool",
    None,
}


def _safe_origin(value: Any) -> bool:
    if (
        not isinstance(value, str)
        or not value.isascii()
        or not value
        or any(ord(ch) <= 32 or ord(ch) == 127 for ch in value)
        or any(ch in value for ch in ("?", "#", "@", "\\"))
    ):
        return False
    try:
        parsed = urlsplit(value)
        host = parsed.hostname
        if (
            parsed.scheme != "https"
            or not host
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
            or parsed.path not in ("", "/")
            or not re.fullmatch(r"[A-Za-z0-9.-]+", host)
            or len(host) > 253
            or parsed.netloc.endswith(":")
            or any(
                not re.fullmatch(
                    r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?", label
                )
                for label in host.split(".")
            )
        ):
            return False
        port = parsed.port
        return port is None or 1 <= port <= 65535
    except ValueError:
        return False


def _id_or_none(value: Any) -> bool:
    return value is None or (
        isinstance(value, str) and bool(ID.fullmatch(value)) and int(value) > 0
    )


def _validate(sidecar: Any, snapshot: dict[str, Any]) -> bool:
    """Validate exact allowed data shape, returning whether observations are incomplete."""

    def fail() -> None:
        raise GradebookError("Invalid source observation sidecar.")

    if not isinstance(sidecar, dict) or set(sidecar) != {
        "contract",
        "origin",
        "course_id",
        "cells",
        "source_mapping_authority",
        "scan_authority",
    }:
        fail()
    if (
        snapshot.get("schema_version") != 1
        or type(snapshot.get("schema_version")) is not int
        or not _id_or_none(sidecar.get("course_id"))
        or sidecar.get("course_id") is None
        or sidecar["contract"] != "CANVAS_SOURCE_OBSERVATION_V1"
        or sidecar["source_mapping_authority"] is not False
        or sidecar["scan_authority"] is not False
        or not _safe_origin(sidecar["origin"])
        or not _safe_origin(snapshot.get("origin"))
        or sidecar["origin"] != snapshot["origin"].rstrip("/")
        or sidecar["course_id"] != str(snapshot.get("course_id", ""))
    ):
        fail()
    cells, base = sidecar["cells"], snapshot.get("cells")
    if (
        not isinstance(cells, dict)
        or not isinstance(base, dict)
        or len(cells) > MAX_CELLS
        or set(cells) != set(base)
    ):
        raise GradebookError("Invalid source observation sidecar.")
    incomplete = not cells
    for key, item in cells.items():
        if (
            not isinstance(key, str)
            or not CELL.fullmatch(key)
            or not isinstance(item, dict)
            or set(item)
            != {
                "reported_submission_object_id",
                "observed_attempt",
                "submission_type",
                "attachments",
                "status",
                "holds",
            }
        ):
            fail()
        holds, attachments = item["holds"], item["attachments"]
        if (
            item["status"] != "HELD_OBSERVATION_ONLY"
            or not _id_or_none(item["reported_submission_object_id"])
            or not (
                item["observed_attempt"] is None
                or type(item["observed_attempt"]) is int
                and 0 < item["observed_attempt"] < 2**63
            )
            or not isinstance(item["submission_type"], (str, type(None)))
            or item["submission_type"] not in KINDS
            or not isinstance(holds, list)
            or not holds
            or len(holds) > 40
            or any(not isinstance(h, str) or h not in HOLD_VOCABULARY for h in holds)
            or len(set(holds)) != len(holds)
            or not isinstance(attachments, list)
            or len(attachments) > MAX_ATTACHMENTS
        ):
            fail()
        missing = "SUBMISSION_OBSERVATION_UNAVAILABLE" in holds
        if not missing and not REQUIRED_HOLDS.issubset(holds):
            fail()
        if missing and (
            item["reported_submission_object_id"] is not None
            or item["observed_attempt"] is not None
            or item["submission_type"] is not None
            or attachments
        ):
            fail()
        if item["submission_type"] != "online_upload" and attachments:
            fail()
        for attachment in attachments:
            if (
                not isinstance(attachment, dict)
                or set(attachment) != {"canvas_attachment_id", "observed_version"}
                or not _id_or_none(attachment["canvas_attachment_id"])
                or attachment["canvas_attachment_id"] is None
            ):
                fail()
            version = attachment["observed_version"]
            if version is not None and (
                not isinstance(version, dict)
                or set(version) != {"kind", "value"}
                or version["kind"] != "reported_unverified_sha256"
                or not isinstance(version["value"], str)
                or not HASH.fullmatch(version["value"])
            ):
                fail()
        attachment_ids = [entry["canvas_attachment_id"] for entry in attachments]
        snapshot_attempt = (
            base[key].get("attempt") if isinstance(base[key], dict) else None
        )
        incomplete |= (
            bool(set(holds) - REQUIRED_HOLDS)
            or missing
            or item["reported_submission_object_id"] is None
            or type(item["observed_attempt"]) is not int
            or item["submission_type"] != "online_upload"
            or not attachments
            or len(set(attachment_ids)) != len(attachment_ids)
            or len(attachments) != 1
            or any(entry["observed_version"] is None for entry in attachments)
            or type(snapshot_attempt) is not int
            or snapshot_attempt != item["observed_attempt"]
        )
    return incomplete


def validate_envelope_for_save(store: SidecarStore, envelope: dict[str, Any]) -> None:
    if (
        not isinstance(envelope, dict)
        or set(envelope) != {"contract", "snapshot_id", "observation"}
        or envelope["contract"] != "CANVAS_SOURCE_SIDECAR_STORE_V1"
        or not isinstance(envelope["snapshot_id"], str)
        or not HASH.fullmatch(envelope["snapshot_id"])
    ):
        raise GradebookError("Invalid source observation sidecar.")
    snapshot = store.load("snapshot", envelope["snapshot_id"])
    _validate(envelope["observation"], snapshot)
    try:
        encoded = json.dumps(envelope, ensure_ascii=True, allow_nan=False).encode(
            "utf-8"
        )
    except (TypeError, ValueError):
        raise GradebookError("Invalid source observation sidecar.") from None
    if len(encoded) > MAX_BYTES:
        raise GradebookError("Source observation sidecar exceeds size limit.")


def save_source_sidecar(
    store: SidecarStore, snapshot_id: str, sidecar: dict[str, Any]
) -> str:
    """Store separately by content hash, explicitly anchored to a saved snapshot."""
    envelope = {
        "contract": "CANVAS_SOURCE_SIDECAR_STORE_V1",
        "snapshot_id": snapshot_id,
        "observation": sidecar,
    }
    artifact_id, _ = store.save("source_sidecar", envelope)
    return artifact_id


def read_source_sidecar(
    store: SidecarStore, snapshot_id: str, sidecar_id: str | None
) -> dict[str, Any]:
    """Report reference uncertainty, unvalidated ID mismatch, incomplete or held observations."""
    snapshot = store.load("snapshot", snapshot_id)
    if sidecar_id is None:
        return {"state": "REFERENCE_UNKNOWN"}
    if not isinstance(sidecar_id, str) or not HASH.fullmatch(sidecar_id):
        return {"state": "INCOMPLETE"}
    try:
        envelope = store.load("source_sidecar", sidecar_id)
        if (
            set(envelope) != {"contract", "snapshot_id", "observation"}
            or envelope["contract"] != "CANVAS_SOURCE_SIDECAR_STORE_V1"
            or not isinstance(envelope["snapshot_id"], str)
            or not HASH.fullmatch(envelope["snapshot_id"])
        ):
            return {"state": "INCOMPLETE"}
        if envelope["snapshot_id"] != snapshot_id:
            # The referenced snapshot and observation have not been validated here.
            return {"state": "SNAPSHOT_ID_MISMATCH_UNVALIDATED"}
        incomplete = _validate(envelope["observation"], snapshot)
    except (OSError, GradebookError, TypeError, ValueError):
        return {"state": "INCOMPLETE"}
    return {
        "state": "INCOMPLETE" if incomplete else "HELD",
        "observation": envelope["observation"],
    }
