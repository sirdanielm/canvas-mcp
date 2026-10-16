"""Durable private score/body staging, without release or send authority."""

from __future__ import annotations

import copy
import hashlib
import html
import json
import math
import os
import re
import tempfile
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

from .client import GradebookError
from .model import digest
from .store import Store

CANDIDATE_POINTS_FIELD = (
    "candidate_publish_points_" "preserving_higher_canvas"
)
TEACHER_PREVIEW_REQUIRED = (
    "exact_teacher_preview_" "approval_required"
)


def _need(condition: bool) -> None:
    if not condition:
        raise GradebookError("Paired proposal evidence is invalid; staging held.")


def _sha(value: Any) -> bool:
    return type(value) is str and re.fullmatch(r"[0-9a-f]{64}", value) is not None


def _number(value: Any) -> bool:
    return type(value) in (int, float) and 0 <= value <= 100 and math.isfinite(value)


def _reference(value: Any) -> bool:
    return (type(value) is dict and type(value.get("path")) is str
            and Path(value["path"]).is_absolute() and _sha(value.get("sha256")))


def load_paired_proposal(path: Path, expected_sha256: str) -> dict[str, Any]:
    """Read exactly one owner-supplied private proposal, without following links."""
    _need(_sha(expected_sha256) and path.is_absolute() and not path.is_symlink())
    try:
        raw = path.read_bytes()
        _need(len(raw) <= 20_000_000 and hashlib.sha256(raw).hexdigest() == expected_sha256)
        value = json.loads(raw)
    except (OSError, ValueError):
        raise GradebookError("Paired proposal is unavailable; staging held.") from None
    _need(type(value) is dict)
    return cast(dict[str, Any], value)


def build_paired_readiness(
    proposal: dict[str, Any], *, proposal_sha256: str,
) -> dict[str, Any]:
    """Validate the 166 saved pairs; no saved observation becomes live authority.

    This deliberately has no route-enablement, qualification, approval, token,
    or publisher argument. Existing owner-controlled send gates remain required.
    Source references are retained as documentary pins, not requalified here.
    """
    _need(type(proposal) is dict and _sha(proposal_sha256))
    records = proposal.get("records_private")
    _need(type(records) is list and len(records) == 166)
    records = cast(list[Any], records)
    targets: set[tuple[str, str, str]] = set()
    summary: Counter[str] = Counter()
    checked = []
    for record in records:
        _need(type(record) is dict)
        target = tuple(record.get(k) for k in ("course_id", "assignment_id", "canvas_user_id"))
        _need(all(type(v) is str and 1 <= len(v) <= 20
                  and v.isascii() and v.isdecimal() and int(v) > 0
                  for v in target) and target not in targets)
        targets.add(target)
        _need(type(record.get("student_pin")) is str
              and re.fullmatch(r"[0-9]{4}", record["student_pin"]) is not None)
        _need(record.get("course_lane") in ("core", "advanced", "Core", "Advanced"))
        source, candidate = (record.get("source_final_percent"),
                             record.get(CANDIDATE_POINTS_FIELD))
        _need(_number(source) and _number(candidate) and candidate >= source)
        body = record.get("feedback_exact")
        _need(type(body) is str and bool(body.strip()) and "\x00" not in body)
        try:
            encoded = body.encode("utf-8")
        except UnicodeError:
            raise GradebookError("Paired feedback encoding is invalid; staging held.") from None
        _need(len(encoded) <= 100_000)
        _need(_sha(record.get("feedback_sha256"))
              and hashlib.sha256(encoded).hexdigest() == record["feedback_sha256"]
              and type(record.get("feedback_utf8_bytes")) is int
              and record["feedback_utf8_bytes"] == len(encoded))
        _need(record.get("exact_source_joined_pair") is True
              and record.get("exact_saved_uid_current_pin_binding") is True)
        for flag in ("broader_history_provisional", "teacher_final_approval",
                     "canvas_delivery_verified", "feedback_delivery_verified"):
            _need(type(record.get(flag)) is bool)
        _need(record["teacher_final_approval"] is False)
        _need(all(_reference(record.get(k))
                  for k in ("grade_source_ref", "feedback_body_source_ref")))
        scope = record.get("independent_scope_ref")
        _need(scope is None or (type(scope) is dict
              and _reference(scope.get("latest_independent_review_ref"))))
        _need(type(record.get("current_status_exact")) is str)
        try:
            stamp = datetime.fromisoformat(record["latest_saved_canvas_fetched_at"])
            _need(stamp.tzinfo is not None and stamp <= datetime.now(UTC))
        except (KeyError, TypeError, ValueError):
            raise GradebookError("Saved paired observation time is invalid; staging held.") from None
        cell = record.get("latest_saved_canvas_cell")
        _need(cell is None or type(cell) is dict)
        blockers = ["current_source_qualification_required", "registered_paired_route_required",
                    TEACHER_PREVIEW_REQUIRED]
        if cell is None or cell.get("visible") is not True:
            blockers.append("submission_evidence_required")
        if cell and (cell.get("excused") is True or cell.get("value") == "EX"):
            blockers.append("excused_target_protected")
        if cell and cell.get("grade_matches_current_submission") is False:
            blockers.append("newer_submission_review_required")
        if cell and cell.get("points_deducted"):
            blockers.append("late_policy_review_required")
        if cell and _number(cell.get("value")) and candidate < cell["value"]:
            blockers.append("decrease_held")
        for reason in blockers:
            summary[reason] += 1
        summary["broader_history_provisional"] += record["broader_history_provisional"]
        summary["score_observed_equal"] += bool(cell and cell.get("value") == candidate)
        checked.append({"pair": copy.deepcopy(record), "pair_sha256": digest(record),
                        "state": "STAGED_NO_SEND", "blockers": blockers})
    aggregate = {"pairs_staged": len(checked), "approval_ready": 0, "send_ready": 0,
                 "teacher_approval": False, "canvas_writes": 0,
                 "operations_prepared": 0, "leases_created": 0,
                 "saved_observations_only": True, "blocker_counts": dict(summary)}
    return {"schema_version": 1, "kind": "UNIT1_PAIRED_NO_SEND_REVIEW",
            "created_at": datetime.now(UTC).isoformat(),
            "proposal_file_sha256": proposal_sha256,
            "proposal_content_sha256": digest(proposal),
            "records_private": checked, "aggregate_summary": aggregate,
            "approval_contract": copy.deepcopy(proposal.get("approval_contract")),
            "limitations": copy.deepcopy(proposal.get("limitations"))}


def write_paired_review(
    output_dir: Path, proposal: dict[str, Any], *, proposal_sha256: str,
) -> dict[str, Any]:
    """Save a private immutable draft and exact score/body HTML; return aggregates."""
    review = build_paired_readiness(proposal, proposal_sha256=proposal_sha256)
    store = Store(output_dir)
    receipt_id, path = store.save("receipt", review)
    rows = []
    for item in review["records_private"]:
        pair = item["pair"]
        rows.append("<tr><td>" + html.escape(pair["student_pin"]) + "</td><td>"
                    + html.escape(pair["course_lane"]) + "</td><td>"
                    + html.escape(str(pair[CANDIDATE_POINTS_FIELD]))
                    + "</td><td><pre>" + html.escape(pair["feedback_exact"])
                    + "</pre></td><td>" + html.escape(", ".join(item["blockers"])) + "</td></tr>")
    content = ("<!doctype html><html><head><meta charset='utf-8'>"
               "<meta http-equiv='Content-Security-Policy' content=\"default-src 'none'\">"
               "<title>Private Unit 1 paired review</title></head><body>"
               "<h1>166 score and feedback pairs staged — no send authority</h1>"
               "<p>Saved observations only. This review is a draft. No teacher approval, "
               "current source qualification, send token, or delivery claim is created. "
               "The score and feedback routes require their existing exact review, fresh "
               "Canvas/source checks, finite release, and durable delivery controls.</p>"
               "<table><thead><tr><th>PIN</th><th>Course</th><th>Candidate points</th>"
               "<th>Exact feedback</th><th>Required controls</th></tr></thead><tbody>"
               + "".join(rows) + "</tbody></table></body></html>").encode("utf-8")
    html_path = store.root / f"paired-review-{receipt_id}.html"
    fd, temporary = tempfile.mkstemp(prefix=".paired-pending-", dir=store.root)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.link(temporary, html_path)
        except FileExistsError:
            _need(not html_path.is_symlink() and html_path.read_bytes() == content)
        directory = os.open(store.root, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        Path(temporary).unlink(missing_ok=True)
    return {**review["aggregate_summary"], "receipt_id": receipt_id,
            "local_file": str(path), "review_file": str(html_path),
            "review_file_sha256": hashlib.sha256(content).hexdigest()}
