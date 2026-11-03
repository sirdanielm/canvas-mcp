"""Provider-scoped protection regression tests; fictional HTTP only."""

import copy
import hashlib
import json
import re
from urllib.parse import parse_qsl

import httpx
import pytest
from test_gradebook import snapshot as snapshot
from test_gradebook_publish import comment_system as comment_system
from test_gradebook_publish import prepared_comment
from test_gradebook_publish import system as system
from test_unit1_canvas_protocol import inputs as inputs

from canvas_mcp.gradebook.client import GradebookClient, GradebookError
from canvas_mcp.gradebook.model import digest
from canvas_mcp.gradebook.publish import comment_state
from canvas_mcp.gradebook.unit1_canvas_protocol import (
    OriginalGet,
    parse_exact_observation,
)


def provider_observation(inputs, *, assignment=None, submission=None,
                         query="include%5B%5D=checkpoints", comment_only=True):
    target, original_assignment, original_submission = inputs
    assignment = copy.deepcopy(original_assignment if assignment is None else assignment)
    submission = copy.deepcopy(original_submission if submission is None else submission)
    a_body = json.dumps(assignment).encode()
    s_body = json.dumps(submission).encode()
    root = target.origin + "/api/v1/courses/101/assignments/201"
    return parse_exact_observation(
        target,
        OriginalGet("GET", root + ("?" + query if query else ""), 200, a_body),
        OriginalGet("GET", root + "/submissions/301?include%5B%5D=visibility&include%5B%5D=submission_comments", 200, s_body, True),
        expected_assignment_body_sha256=hashlib.sha256(a_body).hexdigest(),
        expected_submission_body_sha256=hashlib.sha256(s_body).hexdigest(),
        comment_only=comment_only,
    )


def current_provider_fields(inputs):
    assignment, submission = copy.deepcopy(inputs[1:])
    assignment["in_closed_grading_period"] = False
    submission.pop("in_closed_grading_period", None)
    return assignment, submission


def test_comment_accepts_explicit_assignment_open_without_fabricating_submission_flag(inputs):
    assignment, submission = current_provider_fields(inputs)
    observed = provider_observation(inputs, assignment=assignment, submission=submission)
    assert set(observed.holds) == {"teacher_final_authority_not_connected", "comment_only_observation"}
    assert observed.assignment_field("in_closed_grading_period").value is False
    assert observed.assignment_field("in_closed_grading_period").present
    assert not observed.submission_field("in_closed_grading_period").present
    assert observed.submission_field("in_closed_grading_period").value is None
    assert observed.assignment_body_sha256 == hashlib.sha256(json.dumps(assignment).encode()).hexdigest()


@pytest.mark.parametrize("field", ["has_sub_assignments", "in_closed_grading_period"])
@pytest.mark.parametrize("value", ["ABSENT", None, True, 0, "false"])
def test_assignment_unknown_null_or_protected_state_remains_held(inputs, field, value):
    assignment, submission = current_provider_fields(inputs)
    if value == "ABSENT":
        assignment.pop(field, None)
    else:
        assignment[field] = value
    observed = provider_observation(inputs, assignment=assignment, submission=submission)
    assert "assignment_" + field + "_protected_or_unknown" in observed.holds
    assert observed.assignment_field(field).present is (value != "ABSENT")


@pytest.mark.parametrize("value", ["ABSENT", None, True, False, 0, "false"])
def test_comment_excusal_policy_is_not_an_admission_gate(inputs, value):
    assignment, submission = current_provider_fields(inputs)
    if value == "ABSENT":
        submission.pop("excused")
    else:
        submission["excused"] = value
    observed = provider_observation(inputs, assignment=assignment, submission=submission)
    assert "submission_excused_protected_or_unknown" not in observed.holds
    assert observed.submission_field("excused").present is (value != "ABSENT")
    assert observed.submission_field("excused").value == (None if value == "ABSENT" else value)


@pytest.mark.parametrize("value", [None, True, 0, "false"])
def test_conflicting_or_invalid_legacy_submission_closed_state_remains_held(inputs, value):
    assignment, submission = current_provider_fields(inputs)
    submission["in_closed_grading_period"] = value
    observed = provider_observation(inputs, assignment=assignment, submission=submission)
    assert "submission_in_closed_grading_period_protected_or_unknown" in observed.holds


@pytest.mark.parametrize("query", ["include[]=can_edit", "include[]=checkpoints&include[]=checkpoints", "include[]=checkpoints&x=1"])
def test_comment_query_allowance_does_not_accept_other_fields_or_duplicates(inputs, query):
    with pytest.raises(GradebookError):
        provider_observation(inputs, query=query)


def test_checkpoint_query_is_not_added_to_score_protocol(inputs):
    with pytest.raises(GradebookError):
        provider_observation(inputs, comment_only=False)


async def test_exact_comment_transport_requests_checkpoints_and_keeps_original_bytes(inputs):
    assignment, submission = current_provider_fields(inputs)
    assignment["description"] = "Fictional Unicode π"
    a_body = b"\n " + json.dumps(assignment, ensure_ascii=False).encode() + b"\n"
    s_body = json.dumps(submission).encode()
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(200, content=s_body if "/submissions/" in request.url.path else a_body)

    client = GradebookClient(inputs[0].origin, "fictional", transport=httpx.MockTransport(handler))
    try:
        observed = await comment_state(client, inputs[0])
    finally:
        await client.close()
    assert [r.method for r in requests] == ["GET", "GET"]
    assert parse_qsl(requests[0].url.query.decode()) == [("include[]", "checkpoints")]
    assert parse_qsl(requests[1].url.query.decode()) == [("include[]", "visibility"), ("include[]", "submission_comments")]
    assert observed["assignment"]["body"].encode() == a_body
    assert observed["submission"]["body"].encode() == s_body


async def test_held_prepare_retains_original_receipt_without_plan_token_or_send(comment_system):
    publisher, state, envelope = comment_system
    state["assignment"]["in_closed_grading_period"] = False
    state["assignment"].pop("has_sub_assignments")
    state["submission"].pop("in_closed_grading_period")
    state["submission"]["excused"] = None
    with pytest.raises(GradebookError) as error:
        await prepared_comment(comment_system)
    match = re.search(r"receipt-([a-f0-9]{64})\.json", str(error.value))
    assert match, "Held preview must expose only a private immutable receipt reference."
    receipt = publisher.store.load("receipt", match.group(1))
    assert receipt["kind"] == "GRADEBOOK_COMMENT_PREVIEW_HOLD_V1"
    assert receipt["envelope_sha256"] == digest(envelope)
    assert json.loads(receipt["state"]["assignment"]["body"]) == state["assignment"]
    assert json.loads(receipt["state"]["submission"]["body"]) == state["submission"]
    fields = receipt["protection_fields"]
    assert fields["assignment.has_sub_assignments"] == "ABSENT"
    assert fields["assignment.in_closed_grading_period"] == "PRESENT_FALSE"
    assert fields["submission.excused"] == "PRESENT_NULL"
    assert fields["submission.in_closed_grading_period"] == "ABSENT"
    assert not list(publisher.store.root.glob("push-*.json"))
    with publisher.ledger.connect() as db:
        assert db.execute("select count(*) from operations").fetchone()[0] == 0
    assert state["forms"] == []
    assert "Earlier feedback" not in str(error.value)


@pytest.mark.parametrize("scope,field", [
    ("assignment", "has_sub_assignments"),
    ("assignment", "in_closed_grading_period"),
    ("submission", "excused"),
])
@pytest.mark.parametrize("value,label", [
    ("ABSENT", "ABSENT"), (None, "PRESENT_NULL"), (True, "PRESENT_TRUE"),
    (0, "WRONG_TYPE"), ("false", "WRONG_TYPE"),
])
async def test_diagnostic_keeps_absent_null_true_and_wrong_type_distinct(
    comment_system, scope, field, value, label
):
    publisher, state, _ = comment_system
    state["assignment"]["in_closed_grading_period"] = False
    if scope == "submission" and field == "excused":
        # Excusal is not a comment gate; retain its raw diagnostic value
        # while a separate real protection keeps this held.
        state["assignment"]["has_sub_assignments"] = True
    if value == "ABSENT":
        state[scope].pop(field)
    else:
        state[scope][field] = value
    with pytest.raises(GradebookError) as error:
        await prepared_comment(comment_system)
    match = re.search(r"receipt-([a-f0-9]{64})\.json", str(error.value))
    assert match
    receipt = publisher.store.load("receipt", match.group(1))
    assert receipt["protection_fields"][scope + "." + field] == label
    assert json.loads(receipt["state"][scope]["body"]) == state[scope]
    with publisher.ledger.connect() as db:
        assert db.execute("select count(*) from operations").fetchone()[0] == 0
    assert state["forms"] == []


@pytest.mark.parametrize("field", ["has_sub_assignments", "in_closed_grading_period"])
@pytest.mark.parametrize("value", ["ABSENT", None, True, 0, "false"])
async def test_fresh_assignment_protection_change_before_confirm_sends_nothing(
    comment_system, field, value
):
    publisher, state, _ = comment_system
    state["assignment"]["in_closed_grading_period"] = False
    proposal = await prepared_comment(comment_system)
    if value == "ABSENT":
        state["assignment"].pop(field)
    else:
        state["assignment"][field] = value
    with pytest.raises(GradebookError, match="protected_or_unknown"):
        await publisher.confirm_comment("12", proposal["operation_id"], proposal["confirmation_token"])
    assert publisher.ledger.summary(proposal["operation_id"])["counts"] == {"not_sent": 1}
    assert state["forms"] == []


async def test_assignment_closed_drift_at_comment_readback_remains_uncertain(comment_system):
    publisher, state, _ = comment_system
    state["assignment"]["in_closed_grading_period"] = False
    proposal = await prepared_comment(comment_system)
    original_handler = publisher.client.http._transport.handler

    def handler(request):
        response = original_handler(request)
        if request.method == "PUT":
            state["assignment"]["in_closed_grading_period"] = True
        return response

    publisher.client.http._transport.handler = handler
    before_score = state["submission"]["score"]
    result = await publisher.confirm_comment("12", proposal["operation_id"], proposal["confirmation_token"])
    assert result["counts"] == {"uncertain": 1}
    assert len(state["forms"]) == 1
    assert state["submission"]["score"] == before_score
    assert state["submission"]["submission_comments"][0]["comment"] == "Earlier feedback"


@pytest.mark.parametrize("excusal", [False, None, True, "ABSENT"])
async def test_provider_shape_complete_prepare_confirm_and_stored_readback(comment_system, excusal):
    """Realistic ungraded paper shape; no invented Submission closed flag."""
    publisher, state, envelope = comment_system
    state["assignment"]["in_closed_grading_period"] = False
    state["submission"].pop("in_closed_grading_period")
    state["submission"].update(
        score=None, grade=None, attempt=None, submitted_at=None, excused=excusal,
        graded_at=None, workflow_state="unsubmitted",
        grade_matches_current_submission=None, points_deducted=None,
    )
    if excusal == "ABSENT":
        state["submission"].pop("excused")
    envelope.update(category="UNIT2_FEEDBACK", attempt=None, submitted_at=None,
                    comment="0123 | A2 | Core_A\nMC8: read-A | key-D | -2.5")
    before = copy.deepcopy(state["submission"])
    proposal = await prepared_comment(comment_system)
    assert state["forms"] == [] and proposal["canvas_writes"] == 0
    operation = publisher.ledger.operation(proposal["operation_id"])
    plan = publisher.store.load("push", operation["plan_id"])
    assert plan["envelope_sha256"] == digest(envelope)
    assert "in_closed_grading_period" not in json.loads(plan["expected"]["submission"]["body"])
    result = await publisher.confirm_comment("12", proposal["operation_id"], proposal["confirmation_token"])
    assert result["counts"] == {"verified": 1}
    assert state["forms"] == [{
        "comment[text_comment]": [envelope["comment"]],
        "comment[group_comment]": ["false"],
    }]
    receipt = publisher.store.load("receipt", result["readback_receipt_id"])
    assert receipt["comparison"]["stored_verified"] is True
    assert receipt["response_comment_id"] == "502"
    after = json.loads(receipt["after"]["submission"]["body"])
    assert "in_closed_grading_period" not in after
    for field in ("score", "grade", "excused", "attempt", "submitted_at"):
        assert (field in after) is (field in before)
        if field in before:
            assert after[field] == before[field]
    assert after["submission_comments"][0] == before["submission_comments"][0]
    assert after["submission_comments"][1]["comment"] == envelope["comment"]
    assert publisher.ledger.operation(proposal["operation_id"])["items"][0]["response_comment_id"] == "502"


def test_explicit_null_excusal_is_preserved_as_present_raw_provider_value(inputs):
    assignment, submission = current_provider_fields(inputs)
    submission["excused"] = None
    observed = provider_observation(inputs, assignment=assignment, submission=submission)
    assert set(observed.holds) == {"teacher_final_authority_not_connected", "comment_only_observation"}
    assert observed.submission_field("excused").present is True
    assert observed.submission_field("excused").value is None
    assert observed.submission_body_sha256 == hashlib.sha256(json.dumps(submission).encode()).hexdigest()


@pytest.mark.parametrize("value", ["ABSENT", None, True, 0, "false"])
def test_numeric_protocol_still_holds_excusal_unknown_or_protected(inputs, value):
    assignment, submission = current_provider_fields(inputs)
    if value == "ABSENT":
        submission.pop("excused")
    else:
        submission["excused"] = value
    submission["in_closed_grading_period"] = False
    observed = provider_observation(inputs, assignment=assignment, submission=submission,
                                    query="", comment_only=False)
    assert "submission_excused_protected_or_unknown" in observed.holds


@pytest.mark.parametrize("changed", [True, "ABSENT", 0, "false", False])
async def test_null_excusal_drift_before_confirm_never_sends(comment_system, changed):
    publisher, state, _ = comment_system
    state["assignment"]["in_closed_grading_period"] = False
    state["submission"].pop("in_closed_grading_period")
    state["submission"]["excused"] = None
    proposal = await prepared_comment(comment_system)
    if changed == "ABSENT":
        state["submission"].pop("excused")
    else:
        state["submission"]["excused"] = changed
    with pytest.raises(GradebookError):
        await publisher.confirm_comment("12", proposal["operation_id"], proposal["confirmation_token"])
    assert publisher.ledger.summary(proposal["operation_id"])["counts"] == {"not_sent": 1}
    assert state["forms"] == []


@pytest.mark.parametrize("changed", [True, False])
async def test_null_excusal_drift_after_single_send_remains_uncertain(comment_system, changed):
    publisher, state, _ = comment_system
    state["assignment"]["in_closed_grading_period"] = False
    state["submission"].pop("in_closed_grading_period")
    state["submission"]["excused"] = None
    proposal = await prepared_comment(comment_system)
    original_handler = publisher.client.http._transport.handler
    before = copy.deepcopy(state["submission"])
    def handler(request):
        response = original_handler(request)
        if request.method == "PUT":
            state["submission"]["excused"] = changed
        return response
    publisher.client.http._transport.handler = handler
    result = await publisher.confirm_comment("12", proposal["operation_id"], proposal["confirmation_token"])
    assert result["counts"] == {"uncertain": 1}
    assert len(state["forms"]) == 1
    assert state["submission"]["score"] == before["score"]
    assert state["submission"]["grade"] == before["grade"]
    assert state["submission"]["submission_comments"][0] == before["submission_comments"][0]
