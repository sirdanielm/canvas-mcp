"""Read-only U3 feedback staging; no client, inbox, approval, or delivery.

The native owner authenticates the exact-store commit/parts, final producer
source, original response/observation references and target association. A saved
hash, findings row or callback selected by an untrusted tool argument cannot
replace that owner. This module preserves the native record hash as opaque;
the Python staging digest is a different domain from Apps Script canonical JSON.
"""

from __future__ import annotations

import copy
import inspect
import re
from collections.abc import Callable
from datetime import datetime
from typing import Any

from .client import GradebookError
from .model import digest, identifier

CONTRACT = "CANVAS_U3_FEEDBACK_STAGE_V1"
_HASH = re.compile(r"[a-f0-9]{64}")
SourceCheck = Callable[[dict[str, Any]], Any]


def _need(value: Any, code: str) -> None:
    if not value:
        raise GradebookError(code)


def _hash(value: Any) -> bool:
    return type(value) is str and _HASH.fullmatch(value) is not None


def _ref(value: Any) -> bool:
    return (
        type(value) is dict
        and set(value) == {"path", "sha256"}
        and type(value["path"]) is str
        and bool(value["path"].strip())
        and _hash(value["sha256"])
    )


def _pointer(value: Any, pointer: Any) -> None:
    """Check an exact retained JSON pointer without interpreting its science."""
    _need(
        type(pointer) is str and pointer.startswith("/") and len(pointer) <= 4096,
        "U3_FEEDBACK_SOURCE_POINTER",
    )
    for part in pointer[1:].split("/"):
        _need(re.search(r"~(?![01])", part) is None, "U3_FEEDBACK_SOURCE_POINTER")
        key = part.replace("~1", "/").replace("~0", "~")
        if type(value) is dict:
            _need(key in value, "U3_FEEDBACK_SOURCE_POINTER")
            value = value[key]
        elif type(value) is list:
            _need(
                len(key) <= 9 and re.fullmatch(r"0|[1-9][0-9]*", key),
                "U3_FEEDBACK_SOURCE_POINTER",
            )
            _need(int(key) < len(value), "U3_FEEDBACK_SOURCE_POINTER")
            value = value[int(key)]
        else:
            raise GradebookError("U3_FEEDBACK_SOURCE_POINTER")


def stage_u3_feedback(
    envelope: dict[str, Any],
    findings: dict[str, Any],
    *,
    producer_ref: dict[str, str],
    producer_source_refs: dict[str, dict[str, str]],
    feedback: dict[str, Any] | None = None,
    target: dict[str, Any] | None = None,
    source_check: SourceCheck | None = None,
) -> dict[str, Any]:
    """Preserve one native result and optional exact feedback as an unapproved stage.

    ``source_check`` is trusted application code, never an MCP argument. It must
    authenticate the complete supplied tuple, including genuine committed native
    bytes, current final source, full response/criterion reason locators, canonical
    feedback and any exact identity/attempt association. Returning None is its
    normal synchronous success contract. Nothing here confers publication rights.
    """
    try:
        digest(
            [envelope, findings, producer_ref, producer_source_refs, feedback, target]
        )
    except (ValueError, TypeError, OverflowError, RecursionError):
        raise GradebookError("U3_FINITE_JSON_INPUT_REQUIRED") from None
    _need(
        type(envelope) is dict and set(envelope) == {"contract", "binding", "result"},
        "U3_EXACT_ENVELOPE",
    )
    _need(envelope["contract"] == "U3_EXACT_RETENTION_V1", "U3_EXACT_ENVELOPE")
    _need(_ref(producer_ref), "U3_PRODUCER_REFERENCE")
    _need(
        type(producer_source_refs) is dict
        and set(producer_source_refs) == {"exact_store", "native_projection"}
        and all(_ref(v) for v in producer_source_refs.values()),
        "U3_FINAL_PRODUCER_SOURCE_REFERENCES",
    )
    b, result = envelope["binding"], envelope["result"]
    _need(type(b) is dict and type(result) is dict, "U3_EXACT_ENVELOPE")
    _need(
        all(
            _hash(b.get(k))
            for k in (
                "evidence_key",
                "assignment_context_hash",
                "runtime_sha256",
                "source_binding_id",
                "key_sha256",
            )
        ),
        "U3_SOURCE_BINDING",
    )
    _need(
        all(
            type(b.get(k)) is str and b[k].strip()
            for k in (
                "submission_id",
                "source_object_id",
                "artifact_id",
                "source_version",
                "policy_id",
            )
        ),
        "U3_SOURCE_BINDING",
    )
    _need(
        type(b.get("form_id")) is str
        and re.fullmatch(r"(Core|Advanced)_[A-D]", b["form_id"]),
        "U3_SOURCE_BINDING",
    )
    record, review = result.get("record"), result.get("review")
    _need(
        type(record) is dict
        and record.get("version") == "u3-fleet-exact-result-v7"
        and _hash(result.get("recordHash")),
        "U3_RESULT_VERSION_OR_SEAL",
    )
    scored = record.get("result")
    _need(type(scored) is dict and type(review) is dict, "U3_RESULT_REVIEW")
    _need(
        scored.get("state") in ("HOLD", "PROPOSED")
        and type(scored.get("reasons")) is list
        and type(scored.get("exactScore")) is dict,
        "U3_RESULT_REVIEW",
    )
    expected_review = {
        "state": "HELD" if scored["state"] == "HOLD" else "PROPOSED",
        "reasons": scored["reasons"],
        "exactScore": scored["exactScore"],
        "total": scored.get("total"),
        "maximum": 100,
        "publication": "NOT_AUTHORIZED",
    }
    _need(
        digest(review) == digest(expected_review)
        and type(scored.get("maximum")) is int
        and scored["maximum"] == 100
        and scored.get("publication") == "NOT_AUTHORIZED",
        "U3_RESULT_REVIEW",
    )
    total = scored.get("total")
    _need(
        (scored["state"] == "HOLD" and total is None)
        or (
            scored["state"] == "PROPOSED"
            and type(total) in (int, float)
            and 0 <= total <= 100
        ),
        "U3_RESULT_REVIEW",
    )
    _need(type(findings) is dict, "U3_FINDINGS_BINDING")
    expected_fields = {
        "contract": envelope["contract"],
        "state": review["state"],
        "exact": review["exactScore"],
        "total": total,
        "record_hash": result["recordHash"],
        "source_binding_id": b["source_binding_id"],
        "form_id": b["form_id"],
        "policy_id": b["policy_id"],
        "key_sha256": b["key_sha256"],
        "source_version": b["source_version"],
        "context_hash": b["assignment_context_hash"],
        "publication": "NOT_AUTHORIZED",
    }
    _need(
        all(
            k in findings and digest({k: findings[k]}) == digest({k: v})
            for k, v in expected_fields.items()
        ),
        "U3_FINDINGS_BINDING",
    )
    if "packetOnlyProvisional" in record:
        _need(
            findings.get("packet_only_provisional") == record["packetOnlyProvisional"],
            "U3_PACKET_ONLY_BINDING",
        )

    holds = [
        "DISTINCT_QC_REQUIRED",
        "TEACHER_COMMENT_ACCEPTANCE_REQUIRED",
        "FRESH_CANVAS_ATTEMPT_AND_POSTING_STATE_REQUIRED",
        "COMMENT_CONNECTION_ADOPTION_REQUIRED",
    ]
    if review["state"] == "HELD":
        holds.append("SOURCE_RESULT_HELD")
    if "packetOnlyProvisional" in record:
        # A target supplied alongside an unlinked native packet cannot repair
        # its identity/attempt or silently promote that producer generation.
        holds.append("PACKET_ONLY_IDENTITY_ATTEMPT_UNVERIFIED")
    if feedback is None:
        holds.append("CANONICAL_FULL_FEEDBACK_EXPORT_REQUIRED")
    else:
        _need(
            type(feedback) is dict
            and set(feedback)
            == {"text", "decision_sha256", "source_pointers", "response_refs"},
            "U3_CANONICAL_FEEDBACK",
        )
        text = feedback["text"]
        _need(
            type(text) is str
            and bool(text.strip())
            and _hash(feedback["decision_sha256"]),
            "U3_CANONICAL_FEEDBACK",
        )
        _need(
            type(feedback["source_pointers"]) is list
            and bool(feedback["source_pointers"]),
            "U3_FEEDBACK_SOURCE_POINTER",
        )
        for pointer in feedback["source_pointers"]:
            _pointer(envelope, pointer)
        _need(
            type(feedback["response_refs"]) is list
            and bool(feedback["response_refs"])
            and all(_ref(v) for v in feedback["response_refs"]),
            "U3_FULL_RESPONSE_REFERENCES",
        )
        if len(text) > 6000 or text != text.strip() or "\r" in text:
            holds.append("EXACT_FEEDBACK_PUBLISHER_FORMAT_REVIEW_REQUIRED")
    if target is None:
        holds.extend(
            [
                "EXACT_CANVAS_IDENTITY_ASSOCIATION_REQUIRED",
                "OFFICIAL_CANVAS_ATTEMPT_REQUIRED",
            ]
        )
    else:
        _need(
            type(target) is dict
            and set(target)
            == {
                "origin",
                "course_id",
                "assignment_id",
                "user_id",
                "attempt",
                "submitted_at",
            },
            "U3_EXACT_TARGET",
        )
        _need(
            type(target["origin"]) is str
            and re.fullmatch(r"https://[a-zA-Z0-9.-]+", target["origin"]),
            "U3_EXACT_TARGET",
        )
        for key in ("course_id", "assignment_id", "user_id"):
            _need(type(target[key]) is str, "U3_EXACT_TARGET")
            try:
                canonical = identifier(target[key])
            except (GradebookError, ValueError, TypeError, OverflowError):
                raise GradebookError("U3_EXACT_TARGET") from None
            _need(
                canonical == target[key],
                "U3_EXACT_TARGET",
            )
        _need(
            type(target["attempt"]) is int and target["attempt"] >= 1,
            "U3_OFFICIAL_ATTEMPT",
        )
        try:
            observed = datetime.fromisoformat(
                target["submitted_at"].replace("Z", "+00:00")
            )
            _need(
                observed.tzinfo is not None and observed.utcoffset() is not None,
                "U3_OFFICIAL_ATTEMPT",
            )
        except (AttributeError, TypeError, ValueError):
            raise GradebookError("U3_OFFICIAL_ATTEMPT") from None
    packet = {
        "envelope": copy.deepcopy(envelope),
        "findings": copy.deepcopy(findings),
        "producer_ref": copy.deepcopy(producer_ref),
        "producer_source_refs": copy.deepcopy(producer_source_refs),
        "feedback": copy.deepcopy(feedback),
        "target": copy.deepcopy(target),
    }
    verified = False
    if callable(source_check):
        try:
            answer = source_check(copy.deepcopy(packet))
            if inspect.iscoroutine(answer):
                answer.close()
            verified = answer is None
        except Exception:
            verified = False
    if not verified:
        holds.append(
            "FINAL_NATIVE_SOURCE_COMMIT_FEEDBACK_AND_TARGET_VERIFICATION_REQUIRED"
        )
    return {
        "contract": CONTRACT,
        "state": "HELD_UNAPPROVED",
        "retained": packet,
        "stage_snapshot_sha256": digest(packet),
        "producer_record_hash": result["recordHash"],
        "source_owner_verified": verified,
        "holds": sorted(set(holds)),
        "publisher_category": "UNIT3_FEEDBACK",
        "publisher_envelope": None,
        "teacher_accepted": False,
        "publication_allowed": False,
        "canvas_writes": 0,
        "sheets_writes": 0,
    }
