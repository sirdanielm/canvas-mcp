"""Pure fictional channel contract; no transport, release authority or datastore.

Expected digests must come independently from the owner of an immutable accepted
LocalGrAss decision and its target binding. Comparing hashes proves integrity,
never teacher authentication or RELEASE. Owner digests are opaque references:
this module does not claim cross-language canonical serialization equivalence.
The target's metadata digest must cover every substantive exact-assignment and
source-route field, including due/grading-standard/rubric/special-workflow state.
Its owner retains and verifies that canonical metadata; this code compares the
opaque digest. Dataclass defaults describe fictional fixtures only, never an
inference that missing production flags are safe. Observations and response
evidence are supplied by a test, not read by this code.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, fields
from datetime import datetime
from decimal import Decimal

from .client import GradebookError
from .model import digest


@dataclass(frozen=True)
class TargetBinding:
    target: str
    binding_revision: str
    publisher_author: str
    maximum: str
    attempt: int | None
    submitted_at: str | None
    workflow_state: str
    assignment_metadata_sha256: str
    mode: str = "ROSTER_ASSIGNMENT"
    submission_types: tuple[str, ...] = ("on_paper",)
    score_side_effects: str = "NONE"
    schema_version: int = 1


@dataclass(frozen=True)
class ApprovedComponent:
    decision_sha256: str
    target_binding_sha256: str
    channel: str
    payload: str


@dataclass(frozen=True)
class Comment:
    comment_id: str
    author: str
    body: str


@dataclass(frozen=True)
class SubmissionObservation:
    target: str
    maximum: str
    score: str | None
    attempt: int | None
    submitted_at: str | None
    workflow_state: str
    assignment_metadata_sha256: str
    submission_types: tuple[str, ...] = ("on_paper",)
    grading_type: str = "points"
    published: bool | None = True
    visible: bool | None = True
    teacher_final: bool | None = False
    excused: bool | None = False
    closed_period: bool | None = False
    grade_matches_current_submission: bool | None = True
    points_deducted: str | None = "0"
    late_policy_status: str | None = None
    late: bool | None = False
    moderated_grading: bool | None = False
    anonymous_grading: bool | None = False
    group_assignment: bool | None = False
    rubric_controlled: bool | None = False
    has_sub_assignments: bool | None = False
    grade: str | None = None
    graded_at: str | None = None
    posted_at: str | None = None
    comments: tuple[Comment, ...] = ()
    comments_complete: bool = True


@dataclass(frozen=True)
class ComponentContract:
    binding: TargetBinding
    component: ApprovedComponent
    delivery_id: str
    payload_sha256: str
    synthetic_only: bool = True


@dataclass(frozen=True)
class ChannelVerification:
    delivery_id: str
    channel: str
    outcome: str
    holds: tuple[str, ...]
    stored_verified: bool
    synthetic_only: bool = True
    retry_writes: bool = False
    student_visibility: str = "NOT_ESTABLISHED"


def _need(condition: bool, code: str) -> None:
    if not condition:
        raise GradebookError(code)


def _hash(value: object) -> bool:
    return type(value) is str and re.fullmatch(r"[a-f0-9]{64}", value) is not None


def _reference(value: object) -> bool:
    return (
        type(value) is str
        and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}", value) is not None
    )


def _fictional(value: object) -> bool:
    return (
        type(value) is str
        and re.fullmatch(r"fake:[A-Za-z0-9_-]{1,128}", value) is not None
    )


def _decimal(value: object) -> Decimal:
    if not isinstance(value, str):
        raise GradebookError("DECIMAL_STRING_REQUIRED")
    _need(
        type(value) is str
        and len(value) <= 64
        and re.fullmatch(r"(?:0|[1-9][0-9]*)(?:\.[0-9]+)?", value) is not None,
        "DECIMAL_STRING_REQUIRED",
    )
    # The bounded grammar excludes nonfinite, signed and exponent values.
    return Decimal(value)


def _timestamp(value: object) -> bool:
    if value is None:
        return True
    if (
        not isinstance(value, str)
        or type(value) is not str
        or len(value) > 64
        or "\r" in value
    ):
        return False
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).tzinfo is not None
    except ValueError:
        return False


def _validate_binding(binding: TargetBinding) -> None:
    _need(
        type(binding) is TargetBinding
        and type(binding.schema_version) is int
        and binding.schema_version == 1,
        "FICTIONAL_BINDING_INVALID",
    )
    _need(
        _fictional(binding.target)
        and _fictional(binding.binding_revision)
        and _fictional(binding.publisher_author),
        "FICTIONAL_NAMESPACE_REQUIRED",
    )
    _need(
        binding.mode == "ROSTER_ASSIGNMENT"
        and type(binding.submission_types) is tuple
        and binding.submission_types == ("on_paper",),
        "UNSUPPORTED_TARGET_MODE",
    )
    _need(
        binding.attempt is None
        or type(binding.attempt) is int
        and binding.attempt >= 0,
        "OBSERVED_ATTEMPT_INVALID",
    )
    _need(
        _timestamp(binding.submitted_at)
        and type(binding.workflow_state) is str
        and binding.workflow_state
        in ("unsubmitted", "submitted", "pending_review", "graded"),
        "OBSERVED_SUBMISSION_INVALID",
    )
    _need(
        _hash(binding.assignment_metadata_sha256), "ASSIGNMENT_METADATA_DIGEST_REQUIRED"
    )
    _need(_decimal(binding.maximum) > 0, "MAXIMUM_INVALID")
    _need(
        binding.score_side_effects in ("NONE", "CANVAS_POINTS_GRADED"),
        "UNSUPPORTED_SCORE_SIDE_EFFECTS",
    )


def _validate_component(binding: TargetBinding, component: ApprovedComponent) -> None:
    _need(
        type(component) is ApprovedComponent
        and _hash(component.decision_sha256)
        and _hash(component.target_binding_sha256),
        "COMPONENT_BINDING_INVALID",
    )
    _need(
        component.target_binding_sha256 == digest(asdict(binding)),
        "TARGET_BINDING_INTEGRITY_MISMATCH",
    )
    _need(
        type(component.channel) is str
        and component.channel in ("SCORE", "COMMENT")
        and type(component.payload) is str,
        "COMPONENT_PAYLOAD_INVALID",
    )
    if component.channel == "SCORE":
        _need(
            _decimal(component.payload) <= _decimal(binding.maximum),
            "APPROVED_SCORE_OUT_OF_RANGE",
        )
    else:
        _need(
            0 < len(component.payload) <= 6000
            and bool(component.payload.strip())
            and "\r" not in component.payload,
            "EXACT_NORMALIZED_FEEDBACK_REQUIRED",
        )


def _identity(component: ApprovedComponent) -> dict[str, str | int]:
    return {
        "schema_version": 1,
        "kind": "UNIT1_SYNTHETIC_DELIVERY_IDENTITY",
        "decision_sha256": component.decision_sha256,
        "target_binding_sha256": component.target_binding_sha256,
        "channel": component.channel,
        "payload": component.payload,
    }


def build_component_contract(
    binding: TargetBinding,
    component: ApprovedComponent,
    *,
    expected_decision_sha256: str,
    expected_target_binding_sha256: str,
    expected_payload_sha256: str,
) -> ComponentContract:
    """Compare independently retained owner references; create no approval.

    RELEASE IDs/tokens are absent from the delivery identity. Renewals for the
    same decision/binding/channel/exact payload therefore preserve its identity.
    A future trusted caller must obtain the expected payload digest from the
    saved decision owner, never from the pending component being verified.
    """
    _validate_binding(binding)
    _validate_component(binding, component)
    payload_hash = digest({"channel": component.channel, "payload": component.payload})
    _need(
        _hash(expected_decision_sha256)
        and component.decision_sha256 == expected_decision_sha256,
        "DECISION_INTEGRITY_MISMATCH",
    )
    _need(
        _hash(expected_target_binding_sha256)
        and component.target_binding_sha256 == expected_target_binding_sha256,
        "TARGET_BINDING_INTEGRITY_MISMATCH",
    )
    _need(
        _hash(expected_payload_sha256) and payload_hash == expected_payload_sha256,
        "APPROVED_PAYLOAD_INTEGRITY_MISMATCH",
    )
    return ComponentContract(
        binding, component, digest(_identity(component)), payload_hash
    )


def _validate_contract(contract: ComponentContract) -> None:
    _need(
        type(contract) is ComponentContract and contract.synthetic_only is True,
        "SYNTHETIC_CONTRACT_REQUIRED",
    )
    _validate_binding(contract.binding)
    _validate_component(contract.binding, contract.component)
    _need(
        contract.delivery_id == digest(_identity(contract.component))
        and contract.payload_sha256
        == digest(
            {
                "channel": contract.component.channel,
                "payload": contract.component.payload,
            }
        ),
        "CONTRACT_INTEGRITY_MISMATCH",
    )


def _observation_holds(
    observation: SubmissionObservation, binding: TargetBinding, *, score_after: bool
) -> list[str]:
    _need(
        type(observation) is SubmissionObservation and _fictional(observation.target),
        "SYNTHETIC_OBSERVATION_REQUIRED",
    )
    holds: list[str] = []
    if (
        not _hash(observation.assignment_metadata_sha256)
        or observation.assignment_metadata_sha256 != binding.assignment_metadata_sha256
    ):
        holds.append("assignment_metadata_drift_or_unknown")
    if (
        observation.target,
        observation.maximum,
        observation.attempt,
        observation.submitted_at,
        observation.submission_types,
    ) != (
        binding.target,
        binding.maximum,
        binding.attempt,
        binding.submitted_at,
        binding.submission_types,
    ):
        holds.append("target_binding_drift")
    if observation.attempt is not None and (
        type(observation.attempt) is not int or observation.attempt < 0
    ):
        holds.append("observed_attempt_invalid")
    if not all(
        _timestamp(getattr(observation, field))
        for field in ("submitted_at", "graded_at", "posted_at")
    ):
        holds.append("observed_timestamp_invalid")
    if observation.late_policy_status not in (None, "none"):
        holds.append("late_policy_protected_or_unknown")
    allowed_workflow = {binding.workflow_state}
    if score_after and binding.score_side_effects == "CANVAS_POINTS_GRADED":
        allowed_workflow.add("graded")
    if (
        type(observation.workflow_state) is not str
        or observation.workflow_state not in allowed_workflow
    ):
        holds.append("submission_state_drift")
    if observation.grading_type != "points":
        holds.append("unsupported_grading_type")
    for field in ("published", "visible", "grade_matches_current_submission"):
        if getattr(observation, field) is not True:
            holds.append(field + "_not_verified")
    for field in (
        "late",
        "teacher_final",
        "excused",
        "closed_period",
        "moderated_grading",
        "anonymous_grading",
        "group_assignment",
        "rubric_controlled",
        "has_sub_assignments",
    ):
        if getattr(observation, field) is not False:
            holds.append(field + "_protected_or_unknown")
    try:
        if _decimal(observation.maximum) <= 0 or (
            observation.score is not None
            and _decimal(observation.score) > _decimal(observation.maximum)
        ):
            holds.append("observed_score_invalid")
        if (observation.score is None) != (observation.grade is None) or (
            observation.grade is not None
            and _decimal(observation.grade) != _decimal(observation.score)
        ):
            holds.append("observed_grade_score_conflict")
        if _decimal(observation.points_deducted) != 0:
            holds.append("late_deductions_protected")
    except GradebookError:
        holds.append("observed_numeric_state_unknown")
    return holds


def _result(
    contract: ComponentContract, outcome: str, holds: list[str]
) -> ChannelVerification:
    return ChannelVerification(
        contract.delivery_id,
        contract.component.channel,
        outcome,
        tuple(sorted(set(holds))),
        outcome in ("VERIFIED_APPLIED", "VERIFIED_UNCHANGED"),
    )


def _comment_map(observation: SubmissionObservation) -> dict[str, Comment] | None:
    if (
        observation.comments_complete is not True
        or type(observation.comments) is not tuple
    ):
        return None
    result: dict[str, Comment] = {}
    for comment in observation.comments:
        if (
            type(comment) is not Comment
            or not _reference(comment.comment_id)
            or not _reference(comment.author)
            or type(comment.body) is not str
            or comment.comment_id in result
        ):
            return None
        result[comment.comment_id] = comment
    return result


def verify_component(
    contract: ComponentContract,
    before: SubmissionObservation,
    after: SubmissionObservation,
    *,
    response_received: bool,
    response_comment_id: str | None = None,
) -> ChannelVerification:
    """Compare supplied independent fictional readbacks; never infer a release.

    A lost response can produce only OBSERVED_APPLIED or UNCERTAIN. Neither is
    stored_verified, and every result refuses automatic retransmission. Score
    no-ops do not establish delivery of a separately requested comment. This
    function neither persists receipts nor tracks later drift: callers retain
    historical evidence and compare later observations without replaying writes.
    """
    _validate_contract(contract)
    _need(
        type(response_received) is bool
        and (response_comment_id is None or _reference(response_comment_id))
        and (response_received or response_comment_id is None),
        "RESPONSE_EVIDENCE_INVALID",
    )
    binding, component = contract.binding, contract.component
    score_channel = component.channel == "SCORE"
    holds = _observation_holds(before, binding, score_after=False)
    holds.extend(_observation_holds(after, binding, score_after=score_channel))
    # The score value/grade and explicitly approved grading effects are the only
    # channel-specific state exceptions. Everything else must remain unchanged.
    for record_field in fields(SubmissionObservation):
        field = record_field.name
        if field in ("score", "grade", "comments", "comments_complete"):
            continue
        if (
            field in ("workflow_state", "graded_at")
            and score_channel
            and binding.score_side_effects == "CANVAS_POINTS_GRADED"
            and after.workflow_state == "graded"
        ):
            continue
        if getattr(before, field) != getattr(after, field):
            holds.append("remote_state_drift")
    if holds:
        return _result(contract, "CONFLICT", holds)
    old, new = _comment_map(before), _comment_map(after)
    if old is None or new is None:
        return _result(
            contract, "UNCERTAIN", ["comment_coverage_unverified"]
        )
    if score_channel:
        _need(response_comment_id is None, "UNEXPECTED_COMMENT_RESPONSE")
        if old != new:
            return _result(contract, "CONFLICT", ["score_channel_comment_drift"])
        approved = _decimal(component.payload)
        if before.score is not None and _decimal(before.score) > approved:
            return _result(contract, "CONFLICT", ["higher_score_protected"])
        if after.score is None or _decimal(after.score) != approved:
            return _result(contract, "UNCERTAIN", ["score_readback_mismatch"])
        if after.grade is not None:
            try:
                grade_matches = _decimal(after.grade) == approved
            except GradebookError:
                grade_matches = False
            if not grade_matches:
                return _result(contract, "UNCERTAIN", ["grade_readback_mismatch"])
        if before.score is not None and _decimal(before.score) == approved:
            if before != after:
                return _result(contract, "CONFLICT", ["score_noop_remote_drift"])
            return _result(contract, "VERIFIED_UNCHANGED", [])
        return _result(
            contract,
            "VERIFIED_APPLIED" if response_received else "OBSERVED_APPLIED",
            [] if response_received else ["response_lost"],
        )
    if (before.score, before.grade) != (after.score, after.grade):
        return _result(contract, "CONFLICT", ["comment_channel_score_drift"])
    if any(new.get(key) != comment for key, comment in old.items()):
        return _result(contract, "CONFLICT", ["existing_comment_drift"])
    matches = [
        comment
        for key, comment in new.items()
        if key not in old
        and comment.author == binding.publisher_author
        and comment.body == component.payload
    ]
    if len(matches) > 1:
        return _result(contract, "UNCERTAIN", ["duplicate_new_comment_matches"])
    if not matches:
        return _result(contract, "UNCERTAIN", ["new_comment_not_verified"])
    if response_received:
        if response_comment_id != matches[0].comment_id:
            return _result(contract, "UNCERTAIN", ["response_comment_id_not_verified"])
        return _result(contract, "VERIFIED_APPLIED", [])
    return _result(contract, "OBSERVED_APPLIED", ["response_lost"])
