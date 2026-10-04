"""Disabled Canvas protocol material: original GET parsing and form specifications.

This module performs no I/O, authenticates no actor, creates no approval/release,
and sends nothing. All raw bodies, coverage evidence, and independent expected
hashes must come from their respective trusted owners. A matching digest proves
integrity only. The separate fake-target verifier is deliberately not widened.
Private observations retain only exact operational fields, never user objects,
author names, emails, filenames or other author-controlled identity labels.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any, cast
from urllib.parse import parse_qsl, urlencode, urlsplit

from canvas_mcp.gradebook.client import GradebookError
from canvas_mcp.gradebook.model import digest, identifier

MAX_BODY_BYTES = 1_048_576
ASSIGNMENT_FIELDS = (
    "id",
    "course_id",
    "published",
    "points_possible",
    "grading_type",
    "moderated_grading",
    "anonymous_grading",
    "group_category_id",
    "use_rubric_for_grading",
    "has_sub_assignments",
    "due_at",
    "grading_standard_id",
    "submission_types",
    "omit_from_final_grade",
    "post_manually",
)
SUBMISSION_FIELDS = (
    "id",
    "assignment_id",
    "user_id",
    "score",
    "grade",
    "excused",
    "assignment_visible",
    "attempt",
    "submitted_at",
    "workflow_state",
    "graded_at",
    "posted_at",
    "updated_at",
    "grade_matches_current_submission",
    "late_policy_status",
    "points_deducted",
    "late",
    "missing",
    "in_closed_grading_period",
)
Scalar = str | int | float | bool | None


@dataclass(frozen=True)
class CanvasTarget:
    origin: str = field(repr=False)
    course_id: str = field(repr=False)
    assignment_id: str = field(repr=False)
    user_id: str = field(repr=False)
    mode: str = "ROSTER_ASSIGNMENT"
    schema_version: int = 1


@dataclass(frozen=True)
class OriginalGet:
    method: str
    url: str = field(repr=False)
    status_code: int
    body: bytes = field(repr=False)
    comment_coverage_complete: bool | None = None


@dataclass(frozen=True)
class RawField:
    present: bool
    value: Scalar | tuple[str, ...] = field(repr=False)


@dataclass(frozen=True)
class CanvasComment:
    comment_id: str = field(repr=False)
    author_id: str = field(repr=False)
    body: str = field(repr=False)
    metadata_sha256: str


@dataclass(frozen=True)
class ExactObservation:
    target: CanvasTarget = field(repr=False)
    assignment_body_sha256: str
    submission_body_sha256: str
    assignment_metadata_sha256: str
    submission_metadata_sha256: str
    comment_metadata_sha256: str
    submission_state_sha256: str
    assignment_fields: tuple[tuple[str, RawField], ...] = field(repr=False)
    submission_fields: tuple[tuple[str, RawField], ...] = field(repr=False)
    comments: tuple[CanvasComment, ...] = field(repr=False)
    comment_coverage_complete: bool | None
    holds: tuple[str, ...]
    observation_sha256: str
    disabled: bool = True
    provenance: str = "RAW_GET_AUTHORITY_UNVERIFIED"

    def assignment_field(self, name: str) -> RawField:
        return _lookup(self.assignment_fields, name)

    def submission_field(self, name: str) -> RawField:
        return _lookup(self.submission_fields, name)


@dataclass(frozen=True)
class FormRequestSpec:
    target: CanvasTarget = field(repr=False)
    decision_sha256: str
    target_binding_sha256: str
    component_sha256: str
    retained_observation_sha256: str
    channel: str
    publisher_author_id: str = field(repr=False)
    payload: str = field(repr=False)
    method: str
    url: str = field(repr=False)
    form_fields: tuple[tuple[str, str], ...] = field(repr=False)
    encoded_body: bytes = field(repr=False)
    holds: tuple[str, ...]
    executable: bool = False
    execution_ready: bool = False
    publication_ready: bool = False
    retry_writes: bool = False
    provenance: str = "DISABLED_FORM_NO_RELEASE"


@dataclass(frozen=True)
class CommentReadback:
    component_sha256: str
    outcome: str
    holds: tuple[str, ...]
    stored_verified: bool
    retry_writes: bool = False
    publication_authorized: bool = False
    student_visibility: str = "NOT_ESTABLISHED"
    provenance: str = "READBACK_AUTHORITY_UNVERIFIED"


def _need(condition: bool, code: str) -> None:
    if not condition:
        raise GradebookError(code)


def _hash(value: object) -> bool:
    return type(value) is str and re.fullmatch(r"[a-f0-9]{64}", value) is not None


def _id(value: object) -> str:
    _need(type(value) in (str, int), "CANVAS_ID_INVALID")
    _need(len(str(value)) <= 20, "CANVAS_ID_INVALID")
    result = identifier(value)
    _need(str(int(result)) == result, "CANVAS_ID_INVALID")
    return result


def _validate_target(target: CanvasTarget) -> None:
    _need(
        type(target) is CanvasTarget
        and type(target.schema_version) is int
        and target.schema_version == 1,
        "TARGET_SCHEMA_INVALID",
    )
    _need(target.mode == "ROSTER_ASSIGNMENT", "TARGET_MODE_UNSUPPORTED")
    for name in ("course_id", "assignment_id", "user_id"):
        value = getattr(target, name)
        _need(type(value) is str and _id(value) == value, "CANVAS_ID_INVALID")
    _need(
        type(target.origin) is str
        and target.origin.isascii()
        and all(33 <= ord(char) <= 126 for char in target.origin),
        "CANVAS_ORIGIN_INVALID",
    )
    try:
        origin = urlsplit(target.origin)
        _need(
            origin.scheme == "https"
            and bool(origin.hostname)
            and origin.username is None
            and origin.password is None
            and origin.path == ""
            and not origin.query
            and not origin.fragment
            and origin.port is None
            and "%" not in origin.netloc
            and "\\" not in target.origin,
            "CANVAS_ORIGIN_INVALID",
        )
        hostname = origin.hostname or ""
        _need(
            target.origin == "https://" + hostname
            and len(hostname) <= 253
            and all(
                re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", label) is not None
                for label in hostname.split(".")
            ),
            "CANVAS_ORIGIN_INVALID",
        )
    except ValueError:
        raise GradebookError("CANVAS_ORIGIN_INVALID") from None


def _assignment_path(target: CanvasTarget) -> str:
    return f"/api/v1/courses/{target.course_id}/assignments/{target.assignment_id}"


def _submission_path(target: CanvasTarget) -> str:
    return _assignment_path(target) + "/submissions/" + target.user_id


def _parse_source(
    target: CanvasTarget, source: OriginalGet, expected_hash: str, *, submission: bool
) -> dict[str, Any]:
    _need(
        type(source) is OriginalGet
        and source.method == "GET"
        and type(source.status_code) is int
        and source.status_code == 200
        and type(source.body) is bytes
        and 0 < len(source.body) <= MAX_BODY_BYTES,
        "ORIGINAL_GET_INVALID",
    )
    _need(
        _hash(expected_hash)
        and hashlib.sha256(source.body).hexdigest() == expected_hash,
        "ORIGINAL_GET_INTEGRITY_MISMATCH",
    )
    _need(
        type(source.url) is str
        and source.url.isascii()
        and "\\" not in source.url
        and "#" not in source.url
        and (submission or "?" not in source.url)
        and all(33 <= ord(char) <= 126 for char in source.url),
        "ORIGINAL_GET_TARGET_MISMATCH",
    )
    try:
        url = urlsplit(source.url)
        origin = urlsplit(target.origin)
        _need(
            (url.scheme, url.netloc) == (origin.scheme, origin.netloc)
            and url.username is None
            and url.password is None
            and not url.fragment
            and url.path
            == (_submission_path(target) if submission else _assignment_path(target)),
            "ORIGINAL_GET_TARGET_MISMATCH",
        )
        query = parse_qsl(
            url.query, keep_blank_values=True, strict_parsing=True, max_num_fields=8
        )
        expected = (
            [("include[]", "visibility"), ("include[]", "submission_comments")]
            if submission
            else []
        )
        _need(sorted(query) == sorted(expected), "ORIGINAL_GET_QUERY_UNSUPPORTED")
    except ValueError:
        raise GradebookError("ORIGINAL_GET_TARGET_MISMATCH") from None
    _need(
        source.comment_coverage_complete is None
        or type(source.comment_coverage_complete) is bool,
        "COMMENT_COVERAGE_EVIDENCE_INVALID",
    )

    def pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in items:
            _need(key not in result, "ORIGINAL_JSON_AMBIGUOUS")
            result[key] = value
        return result

    def constant(_: str) -> None:
        raise GradebookError("ORIGINAL_JSON_INVALID")

    def exact_float(lexeme: str) -> float:
        value = float(lexeme)
        _need(
            math.isfinite(value) and Decimal(lexeme) == Decimal(str(value)),
            "ORIGINAL_JSON_NUMBER_UNSAFE",
        )
        return value

    try:
        result = json.loads(
            source.body.decode("utf-8"),
            object_pairs_hook=pairs,
            parse_constant=constant,
            parse_float=exact_float,
        )
        _need(type(result) is dict, "ORIGINAL_JSON_SCHEMA_INVALID")
        digest(result)  # Canonical JSON rejects nonfinite exponent results, too.
    except (ValueError, UnicodeError, RecursionError):
        raise GradebookError("ORIGINAL_JSON_INVALID") from None
    return cast(dict[str, Any], result)


def _raw_fields(
    raw: dict[str, Any], names: tuple[str, ...]
) -> tuple[tuple[str, RawField], ...]:
    fields: list[tuple[str, RawField]] = []
    for name in names:
        value = raw.get(name)
        if name == "submission_types" and type(value) is list:
            _need(
                all(type(item) is str for item in value),
                "ORIGINAL_FIELD_SCHEMA_INVALID",
            )
            value = tuple(value)
        _need(
            value is None or type(value) in (str, int, float, bool, tuple),
            "ORIGINAL_FIELD_SCHEMA_INVALID",
        )
        if type(value) is float:
            _need(math.isfinite(value), "ORIGINAL_FIELD_SCHEMA_INVALID")
        fields.append((name, RawField(name in raw, value)))
    return tuple(fields)


def _lookup(fields: tuple[tuple[str, RawField], ...], name: str) -> RawField:
    for key, value in fields:
        if key == name:
            return value
    raise GradebookError("OBSERVATION_FIELD_UNSUPPORTED")


def _numeric(value: object) -> Decimal | None:
    if type(value) not in (int, float) or type(value) is bool:
        return None
    if type(value) is float and not math.isfinite(value):
        return None
    number = Decimal(str(value))
    return number if number >= 0 else None


def _timestamp(value: object) -> bool:
    if value is None:
        return True
    if not isinstance(value, str) or type(value) is not str or len(value) > 64:
        return False
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).tzinfo is not None
    except ValueError:
        return False


def _observation_holds(
    assignment: dict[str, Any],
    submission: dict[str, Any],
    *,
    comment_only: bool = False,
) -> list[str]:
    holds = ["teacher_final_authority_not_connected"]
    for name in ("published",):
        if assignment.get(name) is not True:
            holds.append("assignment_" + name + "_not_verified")
    for name in (
        "moderated_grading",
        "anonymous_grading",
        "use_rubric_for_grading",
        "has_sub_assignments",
    ):
        if comment_only and name == "use_rubric_for_grading":
            continue
        if assignment.get(name) is not False:
            holds.append("assignment_" + name + "_protected_or_unknown")
    if (
        "group_category_id" not in assignment
        or assignment["group_category_id"] is not None
    ):
        holds.append("assignment_group_category_id_held")
    if assignment.get("grading_type") != "points":
        holds.append("assignment_grading_type_unsupported")
    maximum = _numeric(assignment.get("points_possible"))
    if maximum is None or maximum <= 0:
        holds.append("assignment_points_possible_unknown")
    rubric = assignment.get("rubric_settings")
    if not comment_only and (
        "rubric_settings" not in assignment
        or (
            rubric is not None
            and (type(rubric) is not dict or rubric.get("use_for_grading") is not False)
        )
    ):
        holds.append("assignment_rubric_settings_held")
    for name in ("assignment_visible", "grade_matches_current_submission"):
        if comment_only and name == "grade_matches_current_submission":
            continue
        if submission.get(name) is not True:
            holds.append("submission_" + name + "_not_verified")
    for name in ("excused", "late", "in_closed_grading_period"):
        if comment_only and name == "late":
            continue
        if submission.get(name) is not False:
            holds.append("submission_" + name + "_protected_or_unknown")
    if not comment_only and (
        "late_policy_status" not in submission
        or submission["late_policy_status"] not in (None, "none")
    ):
        holds.append("submission_late_policy_status_held")
    if not comment_only and _numeric(submission.get("points_deducted")) != Decimal(0):
        holds.append("submission_points_deducted_held")
    for name in ("attempt", "submitted_at", "workflow_state", "score", "grade"):
        if name not in submission:
            holds.append("submission_" + name + "_unknown")
    if "attempt" in submission and not (
        submission["attempt"] is None
        or type(submission["attempt"]) is int
        and submission["attempt"] >= 0
    ):
        holds.append("submission_attempt_invalid")
    for name in ("submitted_at", "graded_at", "posted_at"):
        if name not in submission or not _timestamp(submission[name]):
            holds.append("submission_" + name + "_unknown")
    if "updated_at" in submission and (
        submission["updated_at"] is None or not _timestamp(submission["updated_at"])
    ):
        holds.append("submission_updated_at_unknown")
    if submission.get("workflow_state") not in (
        "unsubmitted",
        "submitted",
        "pending_review",
        "graded",
    ):
        holds.append("submission_workflow_state_unsupported")
    score = submission.get("score")
    numeric_score = _numeric(score)
    if score is not None and (
        numeric_score is None or maximum is not None and numeric_score > maximum
    ):
        holds.append("submission_score_invalid")
    grade = submission.get("grade")
    if grade is not None and (
        type(grade) is not str
        or re.fullmatch(r"(?:0|[1-9][0-9]*)(?:\.[0-9]+)?", grade) is None
    ):
        holds.append("submission_grade_unsupported")
    elif (score is None) != (grade is None):
        holds.append("submission_grade_score_inconsistent")
    elif (
        grade is not None
        and numeric_score is not None
        and Decimal(grade) != numeric_score
    ):
        holds.append("submission_grade_score_inconsistent")
    if comment_only:
        # A comment owns no grade or late-policy field. These values remain
        # protected by exact metadata/readback comparison, including nulls.
        for name in ("late", "missing"):
            if type(submission.get(name)) is not bool:
                holds.append("submission_" + name + "_unknown")
        if (
            "grade_matches_current_submission" not in submission
            or submission["grade_matches_current_submission"] is not None
            and type(submission["grade_matches_current_submission"]) is not bool
        ):
            holds.append(
                "submission_" + "grade_matches_current_submission" + "_unknown"
            )
        if "late_policy_status" not in submission or submission[
            "late_policy_status"
        ] not in (None, "none", "late", "missing", "extended"):
            holds.append("submission_late_policy_status_unknown")
        if "points_deducted" not in submission or (
            submission["points_deducted"] is not None
            and _numeric(submission["points_deducted"]) is None
        ):
            holds.append("submission_points_deducted_unknown")
        holds.append("comment_only_observation")
    return holds


def _comments(
    raw: dict[str, Any], coverage: bool | None
) -> tuple[tuple[CanvasComment, ...], bool | None]:
    values = raw.get("submission_comments")
    if type(values) is not list:
        return (), False if coverage is True else coverage
    comments: list[CanvasComment] = []
    seen: set[str] = set()
    for value in values:
        if (
            type(value) is not dict
            or type(value.get("comment")) is not str
            or len(value["comment"]) > MAX_BODY_BYTES
        ):
            return (), False
        try:
            cid, author = _id(value.get("id")), _id(value.get("author_id"))
        except GradebookError:
            return (), False
        if cid in seen:
            return (), False
        seen.add(cid)
        comments.append(CanvasComment(cid, author, value["comment"], digest(value)))
    return tuple(comments), coverage


def _observation_identity(observation: ExactObservation) -> dict[str, Any]:
    value = asdict(observation)
    value.pop("observation_sha256")
    return value


def parse_exact_observation(
    target: CanvasTarget,
    assignment_get: OriginalGet,
    submission_get: OriginalGet,
    *,
    expected_assignment_body_sha256: str,
    expected_submission_body_sha256: str,
    comment_only: bool = False,
) -> ExactObservation:
    """Parse supplied original GET bytes without inventing null/false state.

    The independent expected body hashes must be obtained from retained reader
    evidence. Coverage is a reader claim, never inferred from an array or hash.
    An explicit null attempt is legitimate roster state, not a Canvas attempt.
    ATTEMPT_BOUND remains unsupported without an independent source-link port.
    """
    _validate_target(target)
    assignment = _parse_source(
        target, assignment_get, expected_assignment_body_sha256, submission=False
    )
    submission = _parse_source(
        target, submission_get, expected_submission_body_sha256, submission=True
    )
    _need(
        _id(assignment.get("id")) == target.assignment_id
        and _id(assignment.get("course_id")) == target.course_id
        and _id(submission.get("assignment_id")) == target.assignment_id
        and _id(submission.get("user_id")) == target.user_id,
        "ORIGINAL_GET_IDENTITY_MISMATCH",
    )
    if "course_id" in submission:
        _need(
            _id(submission["course_id"]) == target.course_id,
            "ORIGINAL_GET_IDENTITY_MISMATCH",
        )
    _id(submission.get("id"))
    _need(type(comment_only) is bool, "OBSERVATION_PURPOSE_INVALID")
    supported = (
        ("on_paper",),
        ("online_upload",),
        ("online_text_entry",),
        ("online_url",),
    )
    _need(
        type(assignment.get("submission_types")) is list
        and (
            tuple(assignment["submission_types"]) in supported
            if comment_only
            else assignment["submission_types"] == ["on_paper"]
        ),
        "COMMENT_SUBMISSION_TYPE_UNSUPPORTED"
        if comment_only
        else "ROSTER_ON_PAPER_REQUIRED",
    )
    a_fields, s_fields = (
        _raw_fields(assignment, ASSIGNMENT_FIELDS),
        _raw_fields(submission, SUBMISSION_FIELDS),
    )
    comments, coverage = _comments(submission, submission_get.comment_coverage_complete)
    holds = _observation_holds(assignment, submission, comment_only=comment_only)
    if coverage is not True:
        holds.append("comment_coverage_unverified")
    # The complete original non-comment metadata is retained as a digest only.
    # Whitelisting fields for private inspection must never hide remote drift.
    metadata = {
        key: value for key, value in submission.items() if key != "submission_comments"
    }
    result = ExactObservation(
        target,
        expected_assignment_body_sha256,
        expected_submission_body_sha256,
        digest(assignment),
        digest(metadata),
        digest(
            {
                key: value
                for key, value in metadata.items()
                if key not in {"updated_at", "posted_at"}
            }
        ),
        digest(
            {
                "fields": [[name, asdict(value)] for name, value in s_fields],
                "comments": [asdict(value) for value in comments],
                "comment_coverage_complete": coverage,
            }
        ),
        a_fields,
        s_fields,
        comments,
        coverage,
        tuple(sorted(set(holds))),
        "",
    )
    return ExactObservation(
        **{**vars(result), "observation_sha256": digest(_observation_identity(result))}
    )


def _validate_observation(observation: ExactObservation) -> None:
    _need(
        type(observation) is ExactObservation
        and observation.disabled is True
        and observation.provenance == "RAW_GET_AUTHORITY_UNVERIFIED",
        "DISABLED_OBSERVATION_REQUIRED",
    )
    _validate_target(observation.target)
    _need(
        _hash(observation.observation_sha256)
        and digest(_observation_identity(observation))
        == observation.observation_sha256,
        "OBSERVATION_INTEGRITY_MISMATCH",
    )


def _payload(channel: str, payload: str) -> None:
    _need(
        type(channel) is str
        and channel in ("SCORE", "COMMENT")
        and type(payload) is str,
        "COMPONENT_SCHEMA_INVALID",
    )
    if channel == "SCORE":
        _need(
            0 < len(payload) <= 64
            and re.fullmatch(r"(?:0|[1-9][0-9]*)(?:\.[0-9]+)?", payload) is not None,
            "APPROVED_SCORE_INVALID",
        )
    else:
        _need(
            0 < len(payload) <= 6000
            and bool(payload.strip())
            and "\r" not in payload
            and payload == payload.strip("\0\t\n\v\f\r "),
            "EXACT_APPROVED_FEEDBACK_REQUIRED",
        )
        try:
            payload.encode("utf-8")
        except UnicodeEncodeError:
            raise GradebookError("EXACT_APPROVED_FEEDBACK_REQUIRED") from None


def _component(
    target: CanvasTarget,
    decision: str,
    binding: str,
    channel: str,
    payload: str,
    publisher_author_id: str,
    comment_attempt: int | None = None,
) -> dict[str, Any]:
    value: dict[str, Any] = {
        "schema_version": 1,
        "kind": "UNIT1_CANVAS_COMPONENT",
        "decision_sha256": decision,
        "target_binding_sha256": binding,
        "target": asdict(target),
        "channel": channel,
        "payload": payload,
        "publisher_author_id": publisher_author_id,
    }
    if comment_attempt is not None:
        value["comment_attempt"] = comment_attempt
    return value


def _form_fields(
    channel: str, payload: str, comment_attempt: int | None = None
) -> tuple[tuple[str, str], ...]:
    fields: tuple[tuple[str, str], ...] = (
        (("submission[posted_grade]", payload),)
        if channel == "SCORE"
        else (("comment[text_comment]", payload), ("comment[group_comment]", "false"))
    )
    if comment_attempt is not None:
        _need(
            channel == "COMMENT"
            and type(comment_attempt) is int
            and comment_attempt > 0,
            "COMMENT_ATTEMPT_INVALID",
        )
        fields += (("comment[attempt]", str(comment_attempt)),)
    return fields


def build_form_request_spec(
    observation: ExactObservation,
    *,
    decision_sha256: str,
    target_binding_sha256: str,
    channel: str,
    payload: str,
    publisher_author_id: str,
    expected_retained_observation_sha256: str,
    expected_component_sha256: str,
    comment_attempt: int | None = None,
) -> FormRequestSpec:
    """Describe one disabled mutation; no permission flag or send method exists.

    Expected observation/component hashes come from independent retained owners.
    Component hashes bind exact target/channel/text and the accepted decision and
    target-binding references. This does not verify acceptance or RELEASE.
    No authorization header or publication/posting/status setting belongs to this
    narrow protocol. Comment-only upload delivery may bind the observed positive
    attempt; that does not establish academic source admission.
    """
    _validate_observation(observation)
    _payload(channel, payload)
    _need(
        channel == "COMMENT" or "comment_only_observation" not in observation.holds,
        "COMMENT_OBSERVATION_CANNOT_GRADE",
    )
    if comment_attempt is not None:
        _need(
            channel == "COMMENT"
            and type(comment_attempt) is int
            and comment_attempt > 0
            and observation.submission_field("attempt")
            == RawField(True, comment_attempt)
            and observation.assignment_field("submission_types").value != ("on_paper",),
            "COMMENT_ATTEMPT_BINDING_MISMATCH",
        )
    _need(
        type(publisher_author_id) is str
        and _id(publisher_author_id) == publisher_author_id,
        "PUBLISHER_AUTHOR_INVALID",
    )
    _need(
        _hash(decision_sha256) and _hash(target_binding_sha256),
        "OWNER_REFERENCE_INVALID",
    )
    _need(
        _hash(expected_retained_observation_sha256)
        and digest(asdict(observation)) == expected_retained_observation_sha256,
        "RETAINED_OBSERVATION_MISMATCH",
    )
    component_hash = digest(
        _component(
            observation.target,
            decision_sha256,
            target_binding_sha256,
            channel,
            payload,
            publisher_author_id,
            comment_attempt,
        )
    )
    _need(
        _hash(expected_component_sha256)
        and component_hash == expected_component_sha256,
        "APPROVED_COMPONENT_MISMATCH",
    )
    holds = list(observation.holds) + [
        "release_authority_not_connected",
        "live_freshness_not_established",
    ]
    if channel == "SCORE":
        maximum = observation.assignment_field("points_possible")
        amount = Decimal(payload)
        numeric_maximum = _numeric(maximum.value)
        _need(
            maximum.present
            and numeric_maximum is not None
            and amount <= numeric_maximum,
            "APPROVED_SCORE_OUT_OF_RANGE",
        )
        score = observation.submission_field("score")
        numeric_score = _numeric(score.value)
        _need(
            not (
                score.present and numeric_score is not None and amount < numeric_score
            ),
            "HIGHER_CANVAS_SCORE_PROTECTED",
        )
    form = _form_fields(channel, payload, comment_attempt)
    return FormRequestSpec(
        observation.target,
        decision_sha256,
        target_binding_sha256,
        component_hash,
        digest(asdict(observation)),
        channel,
        publisher_author_id,
        payload,
        "PUT",
        observation.target.origin + _submission_path(observation.target),
        form,
        urlencode(form).encode("ascii"),
        tuple(sorted(set(holds))),
    )


def _validate_spec(spec: FormRequestSpec) -> None:
    _need(
        type(spec) is FormRequestSpec
        and spec.executable is False
        and spec.execution_ready is False
        and spec.publication_ready is False
        and spec.retry_writes is False
        and spec.provenance == "DISABLED_FORM_NO_RELEASE",
        "DISABLED_SPEC_REQUIRED",
    )
    _validate_target(spec.target)
    _payload(spec.channel, spec.payload)
    comment_attempt = None
    if len(spec.form_fields) == 3:
        key, value = spec.form_fields[2]
        _need(
            key == "comment[attempt]"
            and re.fullmatch(r"[1-9][0-9]*", value) is not None,
            "COMMENT_ATTEMPT_INVALID",
        )
        comment_attempt = int(value)
    _need(
        type(spec.publisher_author_id) is str
        and _id(spec.publisher_author_id) == spec.publisher_author_id,
        "PUBLISHER_AUTHOR_INVALID",
    )
    _need(
        _hash(spec.decision_sha256)
        and _hash(spec.target_binding_sha256)
        and _hash(spec.retained_observation_sha256)
        and spec.component_sha256
        == digest(
            _component(
                spec.target,
                spec.decision_sha256,
                spec.target_binding_sha256,
                spec.channel,
                spec.payload,
                spec.publisher_author_id,
                comment_attempt,
            )
        )
        and spec.method == "PUT"
        and spec.url == spec.target.origin + _submission_path(spec.target)
        and spec.form_fields
        == _form_fields(spec.channel, spec.payload, comment_attempt)
        and spec.encoded_body == urlencode(spec.form_fields).encode("ascii"),
        "SPEC_INTEGRITY_MISMATCH",
    )


def _comment_timestamps_match(
    before: ExactObservation, after: ExactObservation
) -> bool:
    """Allow only bounded comment side effects; preserve missing and null state."""
    old_update, new_update = (
        value.submission_field("updated_at") for value in (before, after)
    )
    if old_update.present != new_update.present:
        return False
    if old_update.value != new_update.value:
        if (
            type(old_update.value) is not str
            or type(new_update.value) is not str
            or not _timestamp(old_update.value)
            or not _timestamp(new_update.value)
        ):
            return False
        if datetime.fromisoformat(
            new_update.value.replace("Z", "+00:00")
        ) < datetime.fromisoformat(old_update.value.replace("Z", "+00:00")):
            return False
    old_post, new_post = (
        value.submission_field("posted_at") for value in (before, after)
    )
    if old_post == new_post:
        return True
    posting = before.assignment_field("post_manually")
    if (
        not old_post.present
        or not new_post.present
        or old_post.value is not None
        or type(new_post.value) is not str
        or not _timestamp(new_post.value)
        or not posting.present
        or posting.value is not False
        or type(old_update.value) is not str
        or type(new_update.value) is not str
        or not _timestamp(old_update.value)
        or not _timestamp(new_update.value)
    ):
        return False
    start = datetime.fromisoformat(old_update.value.replace("Z", "+00:00"))
    posted = datetime.fromisoformat(new_post.value.replace("Z", "+00:00"))
    end = datetime.fromisoformat(new_update.value.replace("Z", "+00:00"))
    return start <= posted <= end


def compare_comment_readback(
    spec: FormRequestSpec,
    before: ExactObservation,
    after: ExactObservation,
    *,
    publisher_author_id: str,
    response_received: bool,
    response_comment_id: str | None = None,
) -> CommentReadback:
    """Pure comment evidence comparison, never permission or automatic recovery.

    Caller-supplied response evidence has no human authority. A response-linked
    new comment can establish stored state, while a lost response remains merely
    OBSERVED_APPLIED. Both retain publication_authorized=False. No second request
    can be generated here, and no historical delivery receipt is fabricated.
    """
    _validate_spec(spec)
    _need(
        spec.channel == "COMMENT"
        and type(response_received) is bool
        and (
            response_comment_id is None
            or type(response_comment_id) is str
            and _id(response_comment_id) == response_comment_id
        )
        and (response_received or response_comment_id is None),
        "COMMENT_RESPONSE_EVIDENCE_INVALID",
    )
    _need(type(publisher_author_id) is str, "COMMENT_RESPONSE_EVIDENCE_INVALID")
    author = _id(publisher_author_id)
    _need(author == spec.publisher_author_id, "PUBLISHER_AUTHOR_MISMATCH")
    _validate_observation(before)
    _validate_observation(after)
    _need(
        spec.retained_observation_sha256 == digest(asdict(before)),
        "RETAINED_OBSERVATION_MISMATCH",
    )

    def result(outcome: str, holds: tuple[str, ...]) -> CommentReadback:
        return CommentReadback(
            spec.component_sha256,
            outcome,
            tuple(
                sorted(
                    set(holds)
                    | {
                        "teacher_final_authority_not_connected",
                        "release_authority_not_connected",
                        "live_freshness_not_established",
                    }
                )
            ),
            outcome == "VERIFIED_APPLIED",
        )

    if (
        before.target != spec.target
        or after.target != spec.target
        or before.assignment_metadata_sha256 != after.assignment_metadata_sha256
        or before.comment_metadata_sha256 != after.comment_metadata_sha256
        or tuple(
            value
            for value in before.submission_fields
            if value[0] not in {"updated_at", "posted_at"}
        )
        != tuple(
            value
            for value in after.submission_fields
            if value[0] not in {"updated_at", "posted_at"}
        )
        or not _comment_timestamps_match(before, after)
    ):
        return result("CONFLICT", ("remote_target_or_state_drift",))
    if (
        before.comment_coverage_complete is not True
        or after.comment_coverage_complete is not True
    ):
        return result("UNCERTAIN", ("comment_coverage_unverified",))
    operational_holds = tuple(
        sorted(
            (set(before.holds) | set(after.holds))
            - {"teacher_final_authority_not_connected", "comment_only_observation"}
        )
    )
    if operational_holds:
        return result("HELD", operational_holds)
    old = {value.comment_id: value for value in before.comments}
    new = {value.comment_id: value for value in after.comments}
    if len(old) != len(before.comments) or len(new) != len(after.comments):
        return result("UNCERTAIN", ("comment_ids_ambiguous",))
    if any(new.get(key) != value for key, value in old.items()):
        return result("CONFLICT", ("existing_comment_drift",))
    matches = [
        value
        for key, value in new.items()
        if key not in old and value.author_id == author and value.body == spec.payload
    ]
    if len(matches) != 1:
        return result("UNCERTAIN", ("new_comment_missing_or_ambiguous",))
    if response_received:
        if response_comment_id != matches[0].comment_id:
            return result("UNCERTAIN", ("response_comment_id_not_verified",))
        return result("VERIFIED_APPLIED", ())
    return result("OBSERVED_APPLIED", ("response_lost",))
