"""Pure, unapproved Unit 2 feedback note staging; no transport or publication.

The synchronous owner verifier must independently qualify the canonical feedback
projection, current source/result, PIN/UID join and actual assignment/submission.
Hashes and supplied JSON flags do not authenticate those facts. The caller owns
the shared lock, durable send intent, one send and uncertain-write reconciliation.
Partial feedback never requires or supplies a numeric total. An unreadable/held
item is conveyed only through the owner-qualified body, never inferred here.
"""

from __future__ import annotations

import copy
import hashlib
import inspect
import json
import re
from collections.abc import Callable
from dataclasses import asdict, dataclass
from typing import Any
from urllib.parse import urlsplit

from . import native
from .client import GradebookError
from .model import digest
from .teacher_edit_transfer import _location

CONTRACT = "UNIT2_UNAPPROVED_NOTE_DRAFT_V1"
START = "[[UNIT2 UNAPPROVED DRAFT "
END = "[[END UNIT2 UNAPPROVED DRAFT]]"
HASH = re.compile(r"[a-f0-9]{64}")
# Admit another source version only after the canonical producer is qualified.
PARTIAL_SOURCE_VERSIONS = frozenset({"UNIT2_COMPACT_FEEDBACK_V2"})
MANUAL_PARTIAL_CONTRACT = "UNIT2_MANUAL_PARTIAL_NOTE_CANDIDATE_V1"
MANUAL_PARTIAL_SOURCE = "UNIT2_MANUAL_PARTIAL_PROPOSAL_SOURCE_V1"
SourceCheck = Callable[..., object]


@dataclass(frozen=True)
class EditOnlyAuthorization:
    """Exact human-authorized staging scope, never academic or delivery approval."""

    origin: str
    course_id: str
    assignment_id: str
    approval_reference: str
    mode: str = "EDIT_ONLY"


def _need(condition: object, code: str) -> None:
    if not condition:
        raise GradebookError(code)


def _state(raw: dict[str, Any]) -> dict[str, Any]:
    return json.loads(json.dumps(native._state(raw), allow_nan=False))  # type: ignore[no-any-return]


def _id(value: object) -> bool:
    return type(value) is str and re.fullmatch(r"[1-9][0-9]*", value) is not None


def _source(check: SourceCheck, *values: dict[str, Any]) -> None:
    try:
        response = check(*(copy.deepcopy(value) for value in values))
        if inspect.iscoroutine(response):
            response.close()
        _need(response is None, "UNIT2_SOURCE_QUALIFICATION_REQUIRED")
    except Exception:
        raise GradebookError("UNIT2_SOURCE_QUALIFICATION_REQUIRED") from None


def validate_manual_partial_candidate(candidate: dict[str, Any]) -> None:
    """Validate representation only; the original owner authenticates real sources."""
    expected = {
        "contract",
        "source_version",
        "component_scope",
        "body",
        "source_pins",
        "target",
        "teacher_accepted",
        "publication_allowed",
        "manual_context",
    }
    _need(
        type(candidate) is dict
        and set(candidate) == expected
        and candidate["contract"] == MANUAL_PARTIAL_CONTRACT
        and candidate["source_version"] == MANUAL_PARTIAL_SOURCE
        and candidate["component_scope"] == "MANUAL_PARTIAL"
        and candidate["teacher_accepted"] is False
        and candidate["publication_allowed"] is False,
        "UNIT2_MANUAL_PARTIAL_CANDIDATE_REQUIRED",
    )
    body, pins = candidate["body"], candidate["source_pins"]
    _need(
        type(body) is str
        and 0 < len(body) <= 6000
        and body.strip() == body
        and START not in body
        and END not in body,
        "UNIT2_CANONICAL_BODY_REQUIRED",
    )
    required = {
        "source_sha256",
        "reading_sha256",
        "judgment_sha256",
        "policy_sha256",
        "proposal_sha256",
        "body_sha256",
    }
    _need(
        type(pins) is dict
        and required <= set(pins)
        and all(
            type(k) is str
            and k.endswith("_sha256")
            and type(v) is str
            and HASH.fullmatch(v)
            for k, v in pins.items()
        ),
        "UNIT2_SOURCE_PINS_REQUIRED",
    )
    context = candidate["manual_context"]
    _need(
        type(context) is dict
        and set(context)
        == {
            "whole_test_proposed_score",
            "native_context",
            "remaining_holds",
            "original_proposal_ref",
            "actual_authored_body_version",
            "review_state",
            "original_manifest_contract",
        }
        and context["original_manifest_contract"]
        == "ORIGINAL_PACKET_SAVED_PROPOSALS_QC_ADVANCE_V1"
        and context["whole_test_proposed_score"] is None
        and type(context["native_context"]) is dict
        and "grade_preview" in context["native_context"]
        and "holds" in context["native_context"]
        and "result_key" in context["native_context"]
        and type(context["remaining_holds"]) is list,
        "UNIT2_MANUAL_PARTIAL_CONTEXT_REQUIRED",
    )
    native_context = context["native_context"]
    if native_context["result_key"] is None:
        _need(
            native_context["grade_preview"] is None
            and native_context["holds"] is None
            and "result_sha256" not in pins,
            "UNIT2_ABSENT_NATIVE_RESULT_MUST_REMAIN_ABSENT",
        )
    else:
        _need(
            type(native_context["result_key"]) is str
            and HASH.fullmatch(native_context["result_key"])
            and type(native_context["holds"]) is list,
            "UNIT2_MANUAL_PARTIAL_CONTEXT_REQUIRED",
        )
    # This is a staging role, not an assertion of canonical formatter output.
    version = context["actual_authored_body_version"]
    _need(
        version is None or (type(version) is str and bool(version.strip())),
        "UNIT2_MANUAL_BODY_PROVENANCE_REQUIRED",
    )
    ref = context["original_proposal_ref"]
    _need(
        type(ref) is dict
        and set(ref) == {"path", "bytes", "sha256"}
        and type(ref["path"]) is str
        and ref["path"].startswith("/")
        and type(ref["bytes"]) is int
        and ref["bytes"] > 0
        and ref["sha256"] == pins["proposal_sha256"]
        and hashlib.sha256(body.encode("utf-8")).hexdigest() == pins["body_sha256"],
        "UNIT2_MANUAL_SOURCE_BODY_BINDING_REQUIRED",
    )
    review = context["review_state"]
    _need(
        type(review) is dict
        and set(review) == {"status", "ref"}
        and review["status"] in {"NOT_REVIEWED", "UNKNOWN", "REVIEW_RECORDED"}
        and (
            (review["status"] == "REVIEW_RECORDED" and type(review["ref"]) is dict)
            or (review["status"] != "REVIEW_RECORDED" and review["ref"] is None)
        ),
        "UNIT2_MANUAL_REVIEW_STATE_REQUIRED",
    )
    # Preserve exact original context; no result key, formatter output or
    # complete whole-test calculation is invented by this adapter.
    json.dumps(context, allow_nan=False)


def prepare_note_draft(
    candidate: dict[str, Any],
    *,
    raw: dict[str, Any],
    binding: dict[str, Any],
    target: dict[str, Any],
    identity_binding: dict[str, Any],
    authorization: EditOnlyAuthorization,
    source_check: SourceCheck,
) -> dict[str, Any]:
    """Plan one NOTE-only mutation, preserving every selected native field.

    A formula or numeric value in the target cell remains byte-for-byte in the
    native projection. An observed paper NULL attempt remains NULL. This does
    not waive any numeric-grade, teacher-acceptance or publisher gate.
    """
    candidate, binding, target, identity_binding = (
        copy.deepcopy(value) for value in (candidate, binding, target, identity_binding)
    )
    manual_partial = (
        type(candidate) is dict and candidate.get("contract") == MANUAL_PARTIAL_CONTRACT
    )
    _need(
        type(candidate) is dict
        and set(candidate)
        == {
            "contract",
            "source_version",
            "component_scope",
            "body",
            "source_pins",
            "target",
            "teacher_accepted",
            "publication_allowed",
        }
        | ({"manual_context"} if manual_partial else set()),
        "UNIT2_CANDIDATE_SCHEMA_REQUIRED",
    )
    legacy_mc = (
        candidate["contract"] == "UNIT2_MC_NOTE_CANDIDATE_V1"
        and candidate["source_version"] == "UNIT2_COMPACT_FEEDBACK_V2"
        and candidate["component_scope"] == "MC_ONLY"
    )
    partial_feedback = (
        candidate["contract"] == "UNIT2_PARTIAL_FEEDBACK_NOTE_CANDIDATE_V1"
        and type(candidate["source_version"]) is str
        and candidate["source_version"] in PARTIAL_SOURCE_VERSIONS
        and candidate["component_scope"] == "MC_AND_FRQ_PARTIAL"
    )
    manual_feedback = (
        manual_partial
        and candidate["source_version"] == MANUAL_PARTIAL_SOURCE
        and candidate["component_scope"] == "MANUAL_PARTIAL"
    )
    _need(
        (legacy_mc or partial_feedback or manual_feedback)
        and candidate["teacher_accepted"] is False
        and candidate["publication_allowed"] is False,
        "UNIT2_UNAPPROVED_MC_CANDIDATE_REQUIRED",
    )
    body = candidate["body"]
    _need(
        type(body) is str
        and 0 < len(body) <= 6000
        and body.strip() == body
        and START not in body
        and END not in body,
        "UNIT2_CANONICAL_BODY_REQUIRED",
    )
    pins = candidate["source_pins"]
    required_pins = (
        {
            "source_sha256",
            "reading_sha256",
            "judgment_sha256",
            "policy_sha256",
            "proposal_sha256",
            "body_sha256",
        }
        if manual_feedback
        else {
            "source_sha256",
            "result_sha256",
            "policy_sha256",
            "formatter_sha256",
            "contract_sha256",
            "projection_sha256",
        }
    )
    _need(
        type(pins) is dict
        and required_pins <= set(pins)
        and all(
            type(key) is str
            and key.endswith("_sha256")
            and type(value) is str
            and HASH.fullmatch(value)
            for key, value in pins.items()
        ),
        "UNIT2_SOURCE_PINS_REQUIRED",
    )
    if manual_feedback:
        validate_manual_partial_candidate(candidate)
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
            "submission_types",
        }
        and candidate["target"] == target,
        "UNIT2_EXACT_TARGET_REQUIRED",
    )
    origin = target["origin"]
    _need(
        type(origin) is str
        and urlsplit(origin).scheme == "https"
        and bool(urlsplit(origin).netloc)
        and not urlsplit(origin).username
        and not urlsplit(origin).password
        and not urlsplit(origin).query
        and not urlsplit(origin).fragment
        and urlsplit(origin).path in ("", "/")
        and all(_id(target[key]) for key in ("course_id", "assignment_id", "user_id")),
        "UNIT2_EXACT_TARGET_REQUIRED",
    )
    _need(
        type(target["submission_types"]) is list
        and bool(target["submission_types"])
        and all(type(value) is str for value in target["submission_types"]),
        "UNIT2_SUBMISSION_OBSERVATION_REQUIRED",
    )
    if target["attempt"] is None:
        _need(
            target["submission_types"] == ["on_paper"]
            and target["submitted_at"] is None,
            "UNIT2_PAPER_NULL_OBSERVATION_REQUIRED",
        )
    else:
        _need(
            type(target["attempt"]) is int
            and target["attempt"] >= 1
            and (target["submitted_at"] is None or type(target["submitted_at"]) is str),
            "UNIT2_CURRENT_ATTEMPT_REQUIRED",
        )
    _need(
        type(identity_binding) is dict
        and set(identity_binding)
        == {
            "pin",
            "user_id",
            "registry_sha256",
            "roster_sha256",
        }
        and identity_binding["user_id"] == target["user_id"]
        and type(identity_binding["pin"]) is str
        and re.fullmatch(r"[0-9]{4}", identity_binding["pin"])
        and all(
            type(identity_binding[key]) is str and HASH.fullmatch(identity_binding[key])
            for key in ("registry_sha256", "roster_sha256")
        ),
        "UNIT2_EXACT_IDENTITY_REQUIRED",
    )
    _need(
        type(authorization) is EditOnlyAuthorization
        and authorization.mode == "EDIT_ONLY"
        and (authorization.origin, authorization.course_id, authorization.assignment_id)
        == (origin, target["course_id"], target["assignment_id"])
        and type(authorization.approval_reference) is str
        and 0 < len(authorization.approval_reference) <= 300,
        "UNIT2_EDIT_ONLY_AUTHORIZATION_REQUIRED",
    )
    _source(source_check, candidate, target, identity_binding)
    before = _state(raw)
    _need(
        before["spreadsheetId"] == binding.get("spreadsheet_id")
        and str(binding.get("course_id")) == target["course_id"]
        and type(binding.get("sheets")) is dict
        and type(binding.get("tab_names")) is dict,
        "UNIT2_BOUND_WORKBOOK_REQUIRED",
    )
    _need(
        set(binding["sheets"])
        == set(binding["tab_names"])
        == {"Canvas", "Working", "_Sync"}
        and all(type(sid) is int for sid in binding["sheets"].values())
        and len(set(binding["sheets"].values())) == 3,
        "UNIT2_BOUND_WORKBOOK_REQUIRED",
    )
    for role, sid in binding["sheets"].items():
        _need(
            str(sid) in before["sheets"]
            and before["sheets"][str(sid)]["properties"]["title"]
            == binding["tab_names"][role],
            "UNIT2_BOUND_TAB_CHANGED",
        )
    sid = binding["sheets"]["Working"]
    cells = before["sheets"][str(sid)]["cells"]
    row, col = _location(cells, target)
    address = f"{row}:{col}"
    old_note = cells.get(address, {}).get("note", "")
    _need(type(old_note) is str, "UNIT2_NATIVE_NOTE_REQUIRED")
    selection = {
        "candidate": candidate,
        "target": target,
        "identity_binding": identity_binding,
        "authorization": asdict(authorization),
        "binding": binding,
    }
    selection_sha256 = digest(selection)
    label = (
        "UNAPPROVED manual partial feedback draft. Whole-test proposed score: NULL."
        if manual_feedback
        else "UNAPPROVED MC-only draft for teacher review."
        if legacy_mc
        else "UNAPPROVED partial MC/FRQ feedback draft for teacher review."
    )
    block = (
        START + selection_sha256 + "]]\n" + label + " Overall grade unchanged.\n"
        "No academic acceptance or Canvas delivery authorized.\n" + body + "\n" + END
    )
    after = copy.deepcopy(before)
    requests = []
    if START in old_note or END in old_note:
        _need(
            old_note == block or old_note.endswith("\n\n" + block),
            "UNIT2_CONFLICTING_DRAFT_HELD",
        )
        _need(
            old_note.count(START) == old_note.count(END) == 1,
            "UNIT2_CONFLICTING_DRAFT_HELD",
        )
        status = "NO_CHANGE"
    else:
        note = old_note + ("\n\n" if old_note else "") + block
        _need(len(note) <= 50_000, "UNIT2_NOTE_CAPACITY_HELD")
        after["sheets"][str(sid)]["cells"].setdefault(address, {})["note"] = note
        requests = [
            {
                "updateCells": {
                    "start": {"sheetId": sid, "rowIndex": row, "columnIndex": col},
                    "rows": [{"values": [{"note": note}]}],
                    "fields": "note",
                }
            }
        ]
        status = "PREPARED_LOCAL_EDIT_NOTE_ONLY"
    return {
        "contract": CONTRACT,
        "status": status,
        **selection,
        "selection_sha256": selection_sha256,
        "before_state": before,
        "after_state": after,
        "before_fingerprint": digest(before),
        "after_fingerprint": digest(after),
        "requests": requests,
        "canvas_requests": [],
        "numeric_grade_disposition": "UNCHANGED",
        "teacher_accepted": False,
        "publication_allowed": False,
        "score_delivery_authorized": False,
        "comment_delivery_authorized": False,
        "canvas_writes": 0,
        "sheets_writes": 0,
    }


def _plan(plan: dict[str, Any], expected_plan_sha256: str) -> None:
    _need(
        type(expected_plan_sha256) is str
        and HASH.fullmatch(expected_plan_sha256)
        and digest(plan) == expected_plan_sha256
        and plan.get("contract") == CONTRACT,
        "UNIT2_NOTE_PLAN_CHANGED",
    )
    _need(
        all(
            plan.get(key) is False
            for key in (
                "teacher_accepted",
                "publication_allowed",
                "score_delivery_authorized",
                "comment_delivery_authorized",
            )
        )
        and plan.get("canvas_requests") == []
        and plan.get("numeric_grade_disposition") == "UNCHANGED",
        "UNIT2_NOTE_PLAN_CHANGED",
    )


def revalidate_note_draft(
    plan: dict[str, Any],
    *,
    raw: dict[str, Any],
    expected_plan_sha256: str,
    source_check: SourceCheck,
) -> None:
    """Require the exact preimage and independent owner requalification before send."""
    _plan(plan, expected_plan_sha256)
    _need(_state(raw) == plan["before_state"], "UNIT2_STALE_PREIMAGE_HELD")
    fresh = prepare_note_draft(
        plan["candidate"],
        raw=raw,
        binding=plan["binding"],
        target=plan["target"],
        identity_binding=plan["identity_binding"],
        authorization=EditOnlyAuthorization(**plan["authorization"]),
        source_check=source_check,
    )
    _need(fresh == plan, "UNIT2_NOTE_PLAN_CHANGED")


def classify_readback(
    plan: dict[str, Any],
    raw: dict[str, Any],
    *,
    expected_plan_sha256: str,
) -> dict[str, Any]:
    """Classify complete native state; uncertainty never permits a blind retry."""
    _plan(plan, expected_plan_sha256)
    actual = _state(raw)
    status = (
        "PLANNED_OUTPUT_OBSERVED"
        if actual == plan["after_state"]
        else "BEFORE_STILL_PRESENT"
        if actual == plan["before_state"]
        else "DIVERGED"
    )
    return {
        "contract": CONTRACT,
        "status": status,
        "plan_sha256": expected_plan_sha256,
        "actual_fingerprint": digest(actual),
        "retry_writes": False,
        "teacher_accepted": False,
        "score_delivery_verified": False,
        "comment_delivery_verified": False,
        "canvas_writes": 0,
        "sheets_writes": 0,
    }
