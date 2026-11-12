"""Inert Canvas-primary visual review adapter for the existing proposal planner.

The installed caller must independently authenticate the review and fresh Canvas
source on every call. This module does not build an owner, create teacher
acceptance, write Sheets, or publish. It cannot turn its own hashes into authority.
"""

from __future__ import annotations

import copy
import hashlib
import inspect
import os
import re
import stat
from collections.abc import Callable
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from .client import GradebookError
from .model import digest
from .proposal_edit_transfer import CONTRACT as TRANSFER_CONTRACT
from .proposal_edit_transfer import PROPOSAL_FIELDS, _note, _selection
from .proposal_preview import _edpuzzle, _metadata
from .teacher_edit_transfer import _prepare_native_transfer

CONTRACT = "CANVAS_PRIMARY_VISUAL_ADVISORY_V1"
HASH = re.compile(r"[a-f0-9]{64}\Z")


def _need(ok: Any, code: str) -> None:
    if not ok:
        raise GradebookError(code)


def _verified(evidence: dict[str, Any], authority: Callable[..., Any]) -> None:
    _need(type(evidence) is dict and callable(authority), "PRIMARY_AUTHORITY_REQUIRED")
    _need(
        evidence.get("contract") == CONTRACT
        and evidence.get("state") == "REVIEWED_ADVISORY"
        and evidence.get("teacher_accepted") is False
        and evidence.get("publication_allowed") is False
        and evidence.get("holds") == [],
        "PRIMARY_REVIEW_HELD",
    )
    _need(
        evidence.get("source_lane") == "CANVAS_CURRENT_UPLOAD_VISUAL_OCR"
        and evidence.get("policy") == "ASSIGNED_QUESTION_HALF_FULL_PARTICIPATION"
        and evidence.get("ocr_state") == "ALL_SOURCE_FILES_VALIDATED"
        and evidence.get("correct_assignment") is True
        and evidence.get("submission_type") == "online_upload",
        "PRIMARY_EVIDENCE_HELD",
    )
    required, attempted = (
        evidence.get("required"),
        evidence.get("attempted_lower_bound"),
    )
    _need(
        type(required) is int
        and required > 0
        and type(attempted) is int
        and 0 <= attempted <= required
        and 2 * attempted >= required,
        "PRIMARY_THRESHOLD_NOT_ESTABLISHED",
    )
    _need(
        all(
            type(evidence.get(k)) is str and HASH.fullmatch(evidence[k])
            for k in (
                "review_sha256",
                "policy_sha256",
                "canvas_source_sha256",
                "assignment_sha256",
                "record_sha256",
                "proposal_sha256",
                "current_cell_sha256",
            )
        ),
        "PRIMARY_BINDING_REQUIRED",
    )
    files = evidence.get("originals")
    _need(type(files) is list and bool(files), "PRIMARY_ORIGINALS_REQUIRED")
    seen = set()
    for item in files:
        _need(
            type(item) is dict
            and set(item) == {"path", "sha256"}
            and type(item["path"]) is str
            and Path(item["path"]).is_absolute()
            and type(item["sha256"]) is str
            and HASH.fullmatch(item["sha256"])
            and item["path"] not in seen,
            "PRIMARY_ORIGINALS_REQUIRED",
        )
        seen.add(item["path"])
        try:
            path = Path(item["path"])
            _need(
                not any(p.is_symlink() for p in (path, *path.parents)),
                "PRIMARY_SOURCE_CHANGED",
            )
            fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
            with os.fdopen(fd, "rb") as stream:
                before = os.fstat(stream.fileno())
                _need(
                    stat.S_ISREG(before.st_mode)
                    and 0 < before.st_size <= 64 * 1024 * 1024,
                    "PRIMARY_SOURCE_CHANGED",
                )
                data = stream.read(64 * 1024 * 1024 + 1)
                after = os.fstat(stream.fileno())

            def identity(x: os.stat_result) -> tuple[int, int, int, int, int]:
                return (x.st_dev, x.st_ino, x.st_size, x.st_mtime_ns, x.st_ctime_ns)

            _need(
                len(data) <= 64 * 1024 * 1024
                and identity(before) == identity(after) == identity(path.stat())
                and hashlib.sha256(data).hexdigest() == item["sha256"],
                "PRIMARY_SOURCE_CHANGED",
            )
        except OSError:
            raise GradebookError("PRIMARY_SOURCE_CHANGED") from None
    # A trusted application owner independently compares the genuine review,
    # policy, live Canvas submission/attempt and identity. A self-hash is not it.
    try:
        result = authority(copy.deepcopy(evidence))
    except Exception:
        raise GradebookError("PRIMARY_AUTHORITY_REVALIDATION_HELD") from None
    if inspect.iscoroutine(result):
        result.close()
    _need(result is None, "PRIMARY_AUTHORITY_REVALIDATION_HELD")


def _assignment(binding: dict[str, Any], evidence: dict[str, Any]) -> None:
    """Allow only the existing explicitly reviewed Google LTI exception, not Edpuzzle."""
    metadata = binding.get("assignment_metadata")
    _need(
        type(metadata) is dict
        and "edpuzzle" not in str(metadata.get("name", "")).casefold(),
        "EXCLUDED_PROVIDER",
    )
    try:
        _metadata(binding)
        return
    except GradebookError as error:
        if str(error) != "EXTERNAL_TOOL_REVIEW_REQUIRED":
            raise
    metadata = binding.get("assignment_metadata")
    _need(
        type(metadata) is dict
        and binding.get("excluded") is False
        and not _edpuzzle({}, binding)
        and binding.get("provider") == "GOOGLE_ASSIGNMENTS"
        and type(evidence.get("provider_review_sha256")) is str
        and HASH.fullmatch(evidence["provider_review_sha256"]),
        "PRIMARY_PROVIDER_REVIEW_REQUIRED",
    )
    tag = metadata.get("external_tool_tag_attributes")
    try:
        url = urlsplit(tag["url"])
        valid_url = (
            url.scheme == "https"
            and url.hostname == "assignments.google.com"
            and url.username is None
            and url.password is None
            and url.port in (None, 443)
            and url.path.startswith("/lti/a/")
            and len(url.path) > len("/lti/a/")
        )
    except (KeyError, TypeError, ValueError):
        valid_url = False
    _need(
        metadata.get("submission_types") == ["external_tool"] and valid_url,
        "PRIMARY_PROVIDER_REVIEW_REQUIRED",
    )


def prepare_primary_review_transfer(
    *,
    evidence: dict[str, Any],
    record: dict[str, Any],
    proposal: dict[str, Any],
    assignment_binding: dict[str, Any],
    authority: Callable[..., Any],
    **context: Any,
) -> dict[str, Any]:
    """Plan one unapproved local draft through the existing exact native planner.

    authority is supplied by trusted application composition, not request JSON.
    The owner must independently verify current receipt bytes, target and policy.
    An exact reviewed current-attempt receipt may permit a stale prior grade;
    the original false flag remains unchanged in the retained plan.
    """
    _verified(evidence, authority)
    _assignment(assignment_binding, evidence)
    _need(
        all(
            str(evidence.get(k)) == str(record.get(k))
            for k in ("course_id", "assignment_id", "user_id", "canvas_attempt", "pin")
        ),
        "PRIMARY_TARGET_CHANGED",
    )
    _need(
        assignment_binding.get("course_id") == record["course_id"]
        and assignment_binding.get("assignment_id") == record["assignment_id"]
        and assignment_binding.get("assignment_metadata_sha256")
        == evidence["assignment_sha256"],
        "PRIMARY_ASSIGNMENT_CHANGED",
    )
    _need(
        digest(record) == evidence["record_sha256"]
        and digest(proposal) == evidence["proposal_sha256"],
        "PRIMARY_SELECTION_CHANGED",
    )
    matches = [
        a
        for a in context["current"]["assignments"]
        if a.get("id") == record["assignment_id"]
    ]
    _need(
        len(matches) == 1
        and matches[0].get("assignment_metadata")
        == assignment_binding["assignment_metadata"]
        and matches[0].get("assignment_metadata_sha256")
        == evidence["assignment_sha256"],
        "PRIMARY_ASSIGNMENT_CHANGED",
    )
    cell = context["current"]["cells"].get(
        record["user_id"] + ":" + record["assignment_id"]
    )
    _need(
        type(cell) is dict
        and digest(cell) == evidence["current_cell_sha256"]
        and cell.get("workflow_state") == "submitted"
        and type(cell.get("submitted_at")) is str
        and bool(cell["submitted_at"].strip())
        and type(cell.get("attempt")) is int
        and cell["attempt"] == record["canvas_attempt"]
        and cell.get("grade_matches_current_submission") in (True, False)
        and type(cell.get("grade_matches_current_submission")) is bool,
        "PRIMARY_CURRENT_ATTEMPT_CHANGED",
    )
    _need(
        record.get("policy") == proposal.get("policy") == evidence["policy_sha256"]
        and record.get("source_lane")
        == proposal.get("source_lane")
        == "SDMGRASS_FORMATIVE"
        and record.get("delivery_policy")
        == proposal.get("delivery_policy")
        == "SCORE_ONLY",
        "PRIMARY_PARTICIPATION_POLICY_MISMATCH",
    )
    _need(
        proposal.get("total_score") == proposal.get("points_possible")
        and record.get("proposed_score") == proposal.get("points_possible"),
        "PRIMARY_POLICY_SCORE_MISMATCH",
    )
    selected = copy.deepcopy(evidence)

    def source_check(
        actual_record: dict[str, Any],
        actual_proposal: dict[str, Any],
        pins: dict[str, Any],
    ) -> None:
        _need(
            actual_record == record and actual_proposal == proposal,
            "PRIMARY_SELECTION_CHANGED",
        )
        _verified(selected, authority)
        _need(
            pins.get("by_pin", {}).get(record["pin"]) == record["user_id"],
            "PRIMARY_PIN_CHANGED",
        )

    _selection(record, proposal)
    preservation = context.pop("preservation", None)
    transfer = _prepare_native_transfer(
        record,
        proposal,
        source_check=source_check,
        preservation=preservation,
        selection_fields=PROPOSAL_FIELDS,
        selection_key="proposal",
        note_factory=_note,
        contract=TRANSFER_CONTRACT,
        reviewed_current_attempt=True,
        **context,
    )
    return {
        "contract": CONTRACT,
        "evidence": selected,
        "assignment_binding": copy.deepcopy(assignment_binding),
        "transfer": transfer,
        "teacher_accepted": False,
        "publication_allowed": False,
        "canvas_writes": 0,
        "sheets_writes": 0,
    }


def revalidate_primary_review_transfer(
    plan: dict[str, Any],
    *,
    expected_plan_sha256: str,
    authority: Callable[..., Any],
    raw: dict[str, Any],
    current: dict[str, Any],
    pin_binding: dict[str, Any],
) -> None:
    _need(
        type(plan) is dict
        and type(expected_plan_sha256) is str
        and HASH.fullmatch(expected_plan_sha256)
        and digest(plan) == expected_plan_sha256
        and plan.get("contract") == CONTRACT,
        "PRIMARY_PLAN_CHANGED",
    )
    evidence, transfer = plan["evidence"], plan["transfer"]
    _verified(evidence, authority)
    _assignment(plan["assignment_binding"], evidence)
    record, proposal = transfer["record"], transfer["proposal"]
    # Rebuild through the same receipt/authority and existing native planner;
    # no fabricated snapshot or rewritten grade-match flag is used.
    rebuilt = prepare_primary_review_transfer(
        evidence=evidence,
        record=record,
        proposal=proposal,
        assignment_binding=plan["assignment_binding"],
        authority=authority,
        raw=raw,
        binding=transfer["binding"],
        baseline=transfer["baseline"],
        current=current,
        pin_binding=pin_binding,
        preservation=transfer.get("preservation"),
    )
    _need(rebuilt == plan, "PRIMARY_PLAN_CHANGED")
