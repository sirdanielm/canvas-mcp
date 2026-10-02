"""Independent fictional channel requirements; no clients, stores or writes."""

from dataclasses import asdict, replace

import pytest

from canvas_mcp.gradebook.client import GradebookError
from canvas_mcp.gradebook.model import digest
from canvas_mcp.gradebook.unit1_delivery_contract import (
    ApprovedComponent,
    Comment,
    SubmissionObservation,
    TargetBinding,
    build_component_contract,
    verify_component,
)


@pytest.fixture
def inputs():
    binding = TargetBinding(
        target="fake:unit1-case",
        binding_revision="fake:binding-v1",
        publisher_author="fake:publisher",
        maximum="100",
        attempt=None,
        submitted_at=None,
        workflow_state="unsubmitted",
        assignment_metadata_sha256="c" * 64,
    )
    before = SubmissionObservation(
        target=binding.target,
        maximum="100",
        score="40",
        attempt=None,
        submitted_at=None,
        workflow_state="unsubmitted",
        assignment_metadata_sha256="c" * 64,
    )
    return binding, before


def contract_for(binding, channel="SCORE", payload="50", decision="a" * 64):
    component = ApprovedComponent(
        decision_sha256=decision,
        target_binding_sha256=digest(asdict(binding)),
        channel=channel,
        payload=payload,
    )
    return build_component_contract(
        binding,
        component,
        expected_decision_sha256=decision,
        expected_target_binding_sha256=digest(asdict(binding)),
        expected_payload_sha256=digest({"channel": channel, "payload": payload}),
    )


def verify(inputs, channel="SCORE", payload="50", **changes):
    binding, before = inputs
    contract = contract_for(binding, channel, payload)
    after = replace(before, score=payload) if channel == "SCORE" else before
    after = replace(after, **changes)
    return verify_component(contract, before, after, response_received=True)


def test_score_identity_is_stable_without_release_tokens_and_input_mutation(inputs):
    binding, before = inputs
    component = contract_for(binding)
    repeated = contract_for(binding)
    assert component == repeated
    assert component.delivery_id == digest(
        {
            "schema_version": 1,
            "kind": "UNIT1_SYNTHETIC_DELIVERY_IDENTITY",
            "decision_sha256": "a" * 64,
            "target_binding_sha256": digest(asdict(binding)),
            "channel": "SCORE",
            "payload": "50",
        }
    )
    assert "release" not in asdict(component)
    result = verify_component(
        component, before, replace(before, score="50"), response_received=True
    )
    assert result.outcome == "VERIFIED_APPLIED"
    assert result.stored_verified is True
    assert result.synthetic_only is True
    assert result.retry_writes is False
    assert result.student_visibility == "NOT_ESTABLISHED"
    assert before.score == "40" and binding.attempt is None


def test_decision_target_channel_and_exact_payload_change_identity(inputs):
    binding, _ = inputs
    base = contract_for(binding)
    others = [
        contract_for(binding, decision="b" * 64),
        contract_for(replace(binding, binding_revision="fake:binding-v2")),
        contract_for(binding, payload="51"),
        contract_for(binding, channel="COMMENT", payload="50"),
    ]
    assert len({base.delivery_id, *(item.delivery_id for item in others)}) == 5


@pytest.mark.parametrize("which", ["decision", "binding", "payload"])
def test_independent_expected_digest_mismatch_fails(inputs, which):
    binding, _ = inputs
    component = ApprovedComponent(
        "a" * 64, digest(asdict(binding)), "COMMENT", "Approved\ntext"
    )
    kwargs = {
        "expected_decision_sha256": "a" * 64,
        "expected_target_binding_sha256": digest(asdict(binding)),
        "expected_payload_sha256": digest(
            {"channel": "COMMENT", "payload": component.payload}
        ),
    }
    key = {
        "decision": "expected_decision_sha256",
        "binding": "expected_target_binding_sha256",
        "payload": "expected_payload_sha256",
    }[which]
    kwargs[key] = "b" * 64
    with pytest.raises(GradebookError):
        build_component_contract(binding, component, **kwargs)


@pytest.mark.parametrize(
    "target", ["123", "https://school.instructure.com/", "fake:", "fake:../case"]
)
def test_production_or_invalid_target_namespace_is_rejected(inputs, target):
    binding, _ = inputs
    with pytest.raises(GradebookError):
        contract_for(replace(binding, target=target))


@pytest.mark.parametrize(
    "field,value",
    [
        ("mode", "ATTEMPT_BOUND"),
        ("submission_types", ("online_upload",)),
        ("submission_types", ("on_paper", "online_upload")),
        ("publisher_author", "real-teacher"),
        ("attempt", True),
        ("attempt", -1),
        ("maximum", "0"),
        ("maximum", "NaN"),
    ],
)
def test_unsupported_binding_shapes_fail(inputs, field, value):
    binding, _ = inputs
    with pytest.raises(GradebookError):
        contract_for(replace(binding, **{field: value}))


@pytest.mark.parametrize("text", ["", "  ", "line\r\nnext", "line\rnext", "x" * 6001])
def test_feedback_is_validated_without_normalizing_approved_text(inputs, text):
    binding, _ = inputs
    with pytest.raises(GradebookError):
        contract_for(binding, channel="COMMENT", payload=text)


@pytest.mark.parametrize("score", ["", "NaN", "-1", "101", "1e2", "true"])
def test_invalid_and_over_maximum_approved_scores_fail(inputs, score):
    binding, _ = inputs
    with pytest.raises(GradebookError):
        contract_for(binding, payload=score)


def test_score_noop_is_independent_of_pending_feedback(inputs):
    binding, before = inputs
    same = contract_for(binding, payload="40")
    result = verify_component(same, before, before, response_received=False)
    assert result.outcome == "VERIFIED_UNCHANGED" and result.stored_verified
    pending = contract_for(binding, channel="COMMENT", payload="Approved feedback")
    feedback = verify_component(pending, before, before, response_received=False)
    assert feedback.outcome == "UNCERTAIN" and not feedback.stored_verified


def test_decimal_score_equivalence_uses_exact_arithmetic(inputs):
    result = verify(inputs, score="50.000")
    assert result.outcome == "VERIFIED_APPLIED"


def test_lost_score_response_is_observed_only_and_never_retryable(inputs):
    binding, before = inputs
    result = verify_component(
        contract_for(binding),
        before,
        replace(before, score="50"),
        response_received=False,
    )
    assert result.outcome == "OBSERVED_APPLIED"
    assert not result.stored_verified and not result.retry_writes


@pytest.mark.parametrize(
    "field,value",
    [
        ("visible", False),
        ("visible", None),
        ("teacher_final", True),
        ("teacher_final", None),
        ("excused", True),
        ("excused", None),
        ("closed_period", True),
        ("closed_period", None),
        ("grade_matches_current_submission", False),
        ("grade_matches_current_submission", None),
        ("points_deducted", "1"),
        ("points_deducted", None),
        ("published", False),
        ("published", None),
        ("moderated_grading", True),
        ("anonymous_grading", True),
        ("group_assignment", True),
        ("rubric_controlled", True),
        ("has_sub_assignments", True),
        ("grading_type", "letter_grade"),
        ("maximum", "90"),
        ("attempt", 1),
        ("submitted_at", "2026-10-01T12:00:00Z"),
        ("workflow_state", "submitted"),
        ("late_policy_status", "late"),
        ("submission_types", ("online_upload",)),
        ("target", "fake:other-target"),
    ],
)
def test_readback_protection_and_context_drift_hold(inputs, field, value):
    result = verify(inputs, **{field: value})
    assert not result.stored_verified and result.holds and not result.retry_writes


def test_unsafe_baseline_and_higher_existing_score_hold(inputs):
    binding, before = inputs
    for bad in [
        replace(before, visible=None),
        replace(before, score="70"),
        replace(before, teacher_final=True),
    ]:
        result = verify_component(
            contract_for(binding),
            bad,
            replace(before, score="50"),
            response_received=True,
        )
        assert result.holds and not result.stored_verified


def test_score_mismatch_is_uncertain(inputs):
    result = verify(inputs, score="49")
    assert result.outcome == "UNCERTAIN" and not result.stored_verified


def comment_case(inputs, old_text="Earlier feedback"):
    binding, before = inputs
    old = Comment("old-id", binding.publisher_author, old_text)
    before = replace(before, comments=(old,))
    new = Comment("new-id", binding.publisher_author, "Approved\nfeedback ")
    after = replace(before, comments=(old, new))
    contract = contract_for(binding, channel="COMMENT", payload=new.body)
    return contract, before, after


def test_new_response_linked_comment_verifies_exact_text_and_keeps_existing_feedback(
    inputs,
):
    contract, before, after = comment_case(inputs)
    result = verify_component(
        contract, before, after, response_received=True, response_comment_id="new-id"
    )
    assert result.outcome == "VERIFIED_APPLIED" and result.stored_verified
    assert after.comments[0] == before.comments[0]


def test_lost_comment_response_unique_new_match_is_only_observed(inputs):
    contract, before, after = comment_case(inputs)
    result = verify_component(contract, before, after, response_received=False)
    assert result.outcome == "OBSERVED_APPLIED"
    assert not result.stored_verified and not result.retry_writes


def test_old_identical_comment_cannot_satisfy_new_append(inputs):
    contract, before, _ = comment_case(inputs, old_text="Approved\nfeedback ")
    for response in (True, False):
        result = verify_component(
            contract,
            before,
            before,
            response_received=response,
            response_comment_id="old-id" if response else None,
        )
        assert result.outcome == "UNCERTAIN" and not result.stored_verified


@pytest.mark.parametrize("response_id", [None, "old-id", "other-id"])
def test_response_requires_exact_new_comment_id(inputs, response_id):
    contract, before, after = comment_case(inputs)
    result = verify_component(
        contract, before, after, response_received=True, response_comment_id=response_id
    )
    assert result.outcome == "UNCERTAIN" and not result.stored_verified


@pytest.mark.parametrize(
    "field,value",
    [
        ("author", "fake:other-author"),
        ("body", "Approved\nfeedback"),
        ("body", "Approved\r\nfeedback "),
    ],
)
def test_comment_author_and_body_must_match_exactly(inputs, field, value):
    contract, before, after = comment_case(inputs)
    after = replace(
        after,
        comments=(after.comments[0], replace(after.comments[1], **{field: value})),
    )
    result = verify_component(
        contract, before, after, response_received=True, response_comment_id="new-id"
    )
    assert not result.stored_verified and result.outcome == "UNCERTAIN"


def test_duplicate_new_matches_hold_even_with_response_id(inputs):
    contract, before, after = comment_case(inputs)
    after = replace(
        after,
        comments=after.comments
        + (replace(after.comments[1], comment_id="second-new-id"),),
    )
    result = verify_component(
        contract, before, after, response_received=True, response_comment_id="new-id"
    )
    assert (
        result.outcome == "UNCERTAIN"
        and "duplicate_new_comment_matches" in result.holds
    )


@pytest.mark.parametrize("side", ["before", "after"])
def test_incomplete_comment_coverage_and_duplicate_ids_hold(inputs, side):
    contract, before, after = comment_case(inputs)
    observations = {"before": before, "after": after}
    observations[side] = replace(observations[side], comments_complete=False)
    result = verify_component(
        contract,
        observations["before"],
        observations["after"],
        response_received=True,
        response_comment_id="new-id",
    )
    assert result.outcome == "UNCERTAIN" and not result.stored_verified
    observations[side] = replace(
        observations[side],
        comments_complete=True,
        comments=observations[side].comments * 2,
    )
    result = verify_component(
        contract,
        observations["before"],
        observations["after"],
        response_received=True,
        response_comment_id="new-id",
    )
    assert result.outcome == "UNCERTAIN" and not result.stored_verified


def test_deleted_or_changed_old_feedback_is_remote_drift(inputs):
    contract, before, after = comment_case(inputs)
    for comments in [
        (after.comments[1],),
        (replace(after.comments[0], body="Edited"), after.comments[1]),
    ]:
        result = verify_component(
            contract,
            before,
            replace(after, comments=comments),
            response_received=True,
            response_comment_id="new-id",
        )
        assert result.outcome == "CONFLICT" and "existing_comment_drift" in result.holds


def test_comment_channel_does_not_hide_a_score_change(inputs):
    contract, before, after = comment_case(inputs)
    result = verify_component(
        contract,
        before,
        replace(after, score="41"),
        response_received=True,
        response_comment_id="new-id",
    )
    assert result.outcome == "CONFLICT" and not result.stored_verified


def test_tampered_contract_delivery_identity_is_rejected(inputs):
    binding, before = inputs
    contract = replace(contract_for(binding), delivery_id="b" * 64)
    with pytest.raises(GradebookError):
        verify_component(
            contract, before, replace(before, score="50"), response_received=True
        )


@pytest.mark.parametrize("channel,payload", [("SCORE", "50"), ("COMMENT", "Feedback")])
@pytest.mark.parametrize("status", ["late", "missing", "bogus", ""])
def test_unchanged_unsafe_late_policy_is_held(inputs, channel, payload, status):
    binding, before = inputs
    before = replace(before, late_policy_status=status)
    after = (
        replace(before, score="50")
        if channel == "SCORE"
        else replace(
            before, comments=(Comment("new-id", binding.publisher_author, payload),)
        )
    )
    result = verify_component(
        contract_for(binding, channel, payload),
        before,
        after,
        response_received=True,
        response_comment_id="new-id" if channel == "COMMENT" else None,
    )
    assert result.holds and not result.stored_verified


@pytest.mark.parametrize("flag", [True, "yes", None, 1])
def test_response_evidence_requires_boolean(inputs, flag):
    binding, before = inputs
    if flag is True:
        assert verify_component(
            contract_for(binding),
            before,
            replace(before, score="50"),
            response_received=flag,
        ).stored_verified
    else:
        with pytest.raises(GradebookError):
            verify_component(
                contract_for(binding),
                before,
                replace(before, score="50"),
                response_received=flag,
            )


def test_score_channel_preserves_comments_and_requires_complete_coverage(inputs):
    binding, before = inputs
    old = Comment("old-id", binding.publisher_author, "Earlier feedback")
    before = replace(before, comments=(old,))
    contract = contract_for(binding)
    for after in [
        replace(before, score="50", comments=()),
        replace(before, score="50", comments=(replace(old, body="Changed"),)),
        replace(before, score="50", comments_complete=False),
    ]:
        result = verify_component(contract, before, after, response_received=True)
        assert not result.stored_verified and result.holds


def test_explicit_score_grading_effect_allows_only_graded_workflow_and_timestamp(
    inputs,
):
    binding, before = inputs
    after = replace(
        before,
        score="50",
        grade="50",
        workflow_state="graded",
        graded_at="2026-10-01T12:00:00Z",
    )
    strict = verify_component(
        contract_for(binding), before, after, response_received=True
    )
    assert not strict.stored_verified
    approved = replace(binding, score_side_effects="CANVAS_POINTS_GRADED")
    result = verify_component(
        contract_for(approved), before, after, response_received=True
    )
    assert result.outcome == "VERIFIED_APPLIED" and result.stored_verified
    for bad in [
        replace(after, workflow_state="submitted"),
        replace(after, attempt=1),
        replace(after, visible=False),
        replace(after, graded_at="not-a-date"),
        replace(after, posted_at="2026-10-01T12:00:00Z"),
    ]:
        assert not verify_component(
            contract_for(approved), before, bad, response_received=True
        ).stored_verified


def test_comment_cannot_apply_score_workflow_or_timestamp_effect(inputs):
    binding, before = inputs
    binding = replace(binding, score_side_effects="CANVAS_POINTS_GRADED")
    component = contract_for(binding, channel="COMMENT", payload="Feedback")
    after = replace(
        before,
        workflow_state="graded",
        graded_at="2026-10-01T12:00:00Z",
        comments=(Comment("new-id", binding.publisher_author, "Feedback"),),
    )
    assert not verify_component(
        component, before, after, response_received=True, response_comment_id="new-id"
    ).stored_verified


@pytest.mark.parametrize("grade", ["EX", "invalid", "50", True])
def test_inconsistent_baseline_grade_never_verifies(inputs, grade):
    binding, before = inputs
    bad = replace(before, grade=grade)
    result = verify_component(
        contract_for(binding),
        bad,
        replace(before, score="50", grade="50"),
        response_received=True,
    )
    assert result.holds and not result.stored_verified


def test_unsupported_initial_workflow_is_rejected(inputs):
    binding, _ = inputs
    with pytest.raises(GradebookError):
        contract_for(replace(binding, workflow_state="deleted"))


@pytest.mark.parametrize(
    "field",
    [
        "moderated_grading",
        "anonymous_grading",
        "group_assignment",
        "rubric_controlled",
        "has_sub_assignments",
    ],
)
def test_unknown_special_grading_protection_held_even_without_drift(inputs, field):
    binding, before = inputs
    before = replace(before, **{field: None})
    result = verify_component(
        contract_for(binding),
        before,
        replace(before, score="50"),
        response_received=True,
    )
    assert result.holds and not result.stored_verified


@pytest.mark.parametrize("late", [True, None])
def test_late_flag_is_held_even_without_deductions_or_policy_status(inputs, late):
    binding, before = inputs
    before = replace(before, late=late)
    result = verify_component(
        contract_for(binding),
        before,
        replace(before, score="50"),
        response_received=True,
    )
    assert result.holds and not result.stored_verified


@pytest.mark.parametrize("changed", ["d" * 64, "", None])
def test_extra_assignment_and_source_route_metadata_drift_is_held(inputs, changed):
    binding, before = inputs
    for initial in (before, replace(before, assignment_metadata_sha256=changed)):
        after = replace(initial, score="50", assignment_metadata_sha256=changed)
        result = verify_component(
            contract_for(binding), initial, after, response_received=True
        )
        assert result.holds and not result.stored_verified


def test_metadata_digest_is_mandatory_in_target_binding(inputs):
    binding, _ = inputs
    with pytest.raises(GradebookError):
        contract_for(replace(binding, assignment_metadata_sha256=""))
