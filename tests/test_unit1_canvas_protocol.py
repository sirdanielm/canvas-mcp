"""Independent original-GET and form contract canaries, entirely fictional."""

import copy
import hashlib
import json
from dataclasses import asdict, replace
from urllib.parse import parse_qs

import httpx
import pytest

from canvas_mcp.gradebook.client import GradebookError
from canvas_mcp.gradebook.model import digest
from canvas_mcp.gradebook.unit1_canvas_protocol import (
    CanvasTarget,
    OriginalGet,
    build_form_request_spec,
    compare_comment_readback,
    parse_exact_observation,
)


def raw_bytes(value):
    return json.dumps(value, ensure_ascii=False, allow_nan=False).encode("utf-8")


@pytest.mark.parametrize("edge", [" ", "\t", "\n", "\v", "\f", "\0"])
@pytest.mark.parametrize("leading", [True, False])
def test_surrounding_server_whitespace_is_rejected_without_rewriting(
    inputs, edge, leading
):
    payload = edge + "Approved feedback" if leading else "Approved feedback" + edge
    with pytest.raises(GradebookError, match="EXACT_APPROVED_FEEDBACK_REQUIRED"):
        request_spec(observation(inputs), "COMMENT", payload)


def timestamp_readback(inputs, *, posting=False):
    assignment = copy.deepcopy(inputs[1])
    assignment["post_manually"] = False
    initial = copy.deepcopy(inputs[2])
    initial["updated_at"] = "2026-10-02T10:00:00Z"
    before = observation(inputs, assignment=assignment, submission=initial)
    raw = copy.deepcopy(initial)
    raw["updated_at"] = "2026-10-02T10:00:01Z"
    if posting:
        raw["posted_at"] = "2026-10-02T10:00:01Z"
    raw["submission_comments"].append(
        {"id": 502, "author_id": 701, "comment": "Approved feedback"}
    )
    after = observation(inputs, assignment=assignment, submission=raw)
    return before, after, request_spec(before, "COMMENT", "Approved feedback")


@pytest.mark.parametrize("posting", [False, True])
@pytest.mark.parametrize("response_received", [False, True])
def test_expected_timestamp_side_effects_keep_response_and_release_boundaries(
    inputs, posting, response_received
):
    before, after, spec = timestamp_readback(inputs, posting=posting)
    result = compare_comment_readback(
        spec,
        before,
        after,
        publisher_author_id="701",
        response_received=response_received,
        response_comment_id="502" if response_received else None,
    )
    assert result.outcome == (
        "VERIFIED_APPLIED" if response_received else "OBSERVED_APPLIED"
    )
    assert result.stored_verified is response_received
    assert not result.retry_writes and not result.publication_authorized
    assert result.student_visibility == "NOT_ESTABLISHED"
    assert "live_freshness_not_established" in result.holds


def test_interior_and_unicode_whitespace_that_canvas_preserves_is_not_rewritten(inputs):
    for payload in ("First line.\nSecond\tline.", "\u00a0Approved feedback\u00a0"):
        spec = request_spec(observation(inputs), "COMMENT", payload)
        assert spec.payload == payload
        assert parse_qs(spec.encoded_body.decode())["comment[text_comment]"] == [
            payload
        ]


@pytest.mark.parametrize(
    "variant",
    [
        "backward-update",
        "missing-update-before",
        "missing-update-after",
        "null-update-before",
        "null-update-after",
        "bad-update",
        "naive-update",
        "boolean-update",
        "changed-posted-time",
        "cleared-posted-time",
        "missing-posted-time",
        "manual-posting",
        "unknown-posting",
        "early-posting",
        "future-posting",
        "changed-attempt",
        "changed-score",
        "extra-metadata",
    ],
)
def test_timestamp_exceptions_do_not_hide_unknown_or_unrelated_changes(inputs, variant):
    assignment = copy.deepcopy(inputs[1])
    assignment["post_manually"] = False
    initial = copy.deepcopy(inputs[2])
    initial["updated_at"] = "2026-10-02T10:00:00Z"
    if variant in {"changed-posted-time", "cleared-posted-time", "missing-posted-time"}:
        initial["posted_at"] = "2026-10-01T10:00:00Z"
    if variant == "missing-update-before":
        initial.pop("updated_at")
    if variant == "null-update-before":
        initial["updated_at"] = None
    if variant == "manual-posting":
        assignment["post_manually"] = True
    if variant == "unknown-posting":
        assignment.pop("post_manually")
    raw = copy.deepcopy(initial)
    raw["updated_at"] = "2026-10-02T10:00:01Z"
    if variant == "backward-update":
        raw["updated_at"] = "2026-10-02T09:59:59Z"
    if variant == "missing-update-after":
        raw.pop("updated_at")
    if variant == "null-update-after":
        raw["updated_at"] = None
    if variant == "bad-update":
        raw["updated_at"] = "unknown"
    if variant == "naive-update":
        raw["updated_at"] = "2026-10-02T10:00:01"
    if variant == "boolean-update":
        raw["updated_at"] = True
    if variant == "changed-posted-time":
        raw["posted_at"] = "2026-10-02T10:00:01Z"
    if variant == "cleared-posted-time":
        raw["posted_at"] = None
    if variant == "missing-posted-time":
        raw.pop("posted_at")
    if variant in {"manual-posting", "unknown-posting"}:
        raw["posted_at"] = "2026-10-02T10:00:01Z"
    if variant == "early-posting":
        raw["posted_at"] = "2026-10-02T09:59:59Z"
    if variant == "future-posting":
        raw["posted_at"] = "2026-10-02T10:00:02Z"
    if variant == "changed-attempt":
        raw["attempt"] = 1
    if variant == "changed-score":
        raw["score"] = 1
    if variant == "extra-metadata":
        raw["cached_due_date"] = "2026-10-03T00:00:00Z"
    raw["submission_comments"].append(
        {"id": 502, "author_id": 701, "comment": "Approved feedback"}
    )
    before = observation(inputs, assignment=assignment, submission=initial)
    after = observation(inputs, assignment=assignment, submission=raw)
    result = compare_comment_readback(
        request_spec(before, "COMMENT", "Approved feedback"),
        before,
        after,
        publisher_author_id="701",
        response_received=True,
        response_comment_id="502",
    )
    assert result.outcome in {"CONFLICT", "HELD"}
    assert (
        not result.stored_verified
        and not result.retry_writes
        and not result.publication_authorized
    )


def test_timestamp_changes_without_a_new_comment_do_not_verify_delivery(inputs):
    before, _, spec = timestamp_readback(inputs)
    assignment = copy.deepcopy(inputs[1])
    assignment["post_manually"] = False
    raw = copy.deepcopy(inputs[2])
    raw["updated_at"] = "2026-10-02T10:00:01Z"
    after = observation(inputs, assignment=assignment, submission=raw)
    result = compare_comment_readback(
        spec,
        before,
        after,
        publisher_author_id="701",
        response_received=True,
        response_comment_id="502",
    )
    assert (
        result.outcome == "UNCERTAIN"
        and not result.stored_verified
        and not result.retry_writes
    )


@pytest.fixture
def inputs():
    target = CanvasTarget("https://canvas.example.invalid", "101", "201", "301")
    assignment = {
        "id": 201,
        "course_id": 101,
        "published": True,
        "points_possible": 100,
        "grading_type": "points",
        "submission_types": ["on_paper"],
        "moderated_grading": False,
        "anonymous_grading": False,
        "group_category_id": None,
        "use_rubric_for_grading": False,
        "has_sub_assignments": False,
        "rubric_settings": None,
        "due_at": None,
        "grading_standard_id": None,
    }
    submission = {
        "id": 401,
        "assignment_id": 201,
        "user_id": 301,
        "score": None,
        "grade": None,
        "excused": False,
        "assignment_visible": True,
        "attempt": None,
        "submitted_at": None,
        "workflow_state": "unsubmitted",
        "in_closed_grading_period": False,
        "grade_matches_current_submission": True,
        "points_deducted": 0,
        "late_policy_status": None,
        "late": False,
        "missing": False,
        "graded_at": None,
        "posted_at": None,
        "submission_comments": [
            {"id": 501, "author_id": 701, "comment": "Earlier feedback"}
        ],
        "user": {
            "name": "Untrusted fictional student label",
            "email": "fictional@example.invalid",
        },
    }
    return target, assignment, submission


def observation(inputs, *, assignment=None, submission=None, coverage=True):
    target, original_assignment, original_submission = inputs
    assignment = original_assignment if assignment is None else assignment
    submission = original_submission if submission is None else submission
    a_body, s_body = raw_bytes(assignment), raw_bytes(submission)
    a_get = OriginalGet(
        "GET", target.origin + "/api/v1/courses/101/assignments/201", 200, a_body
    )
    s_get = OriginalGet(
        "GET",
        target.origin
        + "/api/v1/courses/101/assignments/201/submissions/301?include%5B%5D=visibility&include%5B%5D=submission_comments",
        200,
        s_body,
        coverage,
    )
    return parse_exact_observation(
        target,
        a_get,
        s_get,
        expected_assignment_body_sha256=hashlib.sha256(a_body).hexdigest(),
        expected_submission_body_sha256=hashlib.sha256(s_body).hexdigest(),
    )


def request_spec(obs, channel="SCORE", payload="50"):
    component = {
        "schema_version": 1,
        "kind": "UNIT1_CANVAS_COMPONENT",
        "decision_sha256": "a" * 64,
        "target_binding_sha256": "b" * 64,
        "target": asdict(obs.target),
        "channel": channel,
        "payload": payload,
        "publisher_author_id": "701",
    }
    return build_form_request_spec(
        obs,
        decision_sha256="a" * 64,
        target_binding_sha256="b" * 64,
        channel=channel,
        payload=payload,
        publisher_author_id="701",
        expected_retained_observation_sha256=digest(asdict(obs)),
        expected_component_sha256=digest(component),
    )


def test_raw_null_zero_missing_are_distinct_and_identity_data_is_not_retained(inputs):
    obs = observation(inputs)
    assert (
        obs.submission_field("attempt").present
        and obs.submission_field("attempt").value is None
    )
    assert (
        obs.submission_field("score").present
        and obs.submission_field("score").value is None
    )
    changed = copy.deepcopy(inputs[2])
    changed["attempt"] = 0
    changed["score"] = 0
    zero = observation(inputs, submission=changed)
    assert (
        zero.submission_field("attempt").value == 0
        and zero.submission_field("score").value == 0
    )
    missing = copy.deepcopy(inputs[2])
    del missing["attempt"]
    held = observation(inputs, submission=missing)
    assert (
        not held.submission_field("attempt").present
        and "submission_attempt_unknown" in held.holds
    )
    assert (
        obs.submission_state_sha256
        != zero.submission_state_sha256
        != held.submission_state_sha256
    )
    assert "name" not in repr(obs) and "fictional@example.invalid" not in repr(obs)
    assert "teacher_final_authority_not_connected" in obs.holds


@pytest.mark.parametrize(
    "owner,key",
    [
        ("assignment", "published"),
        ("assignment", "moderated_grading"),
        ("assignment", "anonymous_grading"),
        ("assignment", "group_category_id"),
        ("assignment", "use_rubric_for_grading"),
        ("assignment", "has_sub_assignments"),
        ("submission", "excused"),
        ("submission", "assignment_visible"),
        ("submission", "in_closed_grading_period"),
        ("submission", "late"),
        ("submission", "points_deducted"),
        ("submission", "grade_matches_current_submission"),
    ],
)
def test_missing_optional_protection_never_defaults_safe(inputs, owner, key):
    raw = copy.deepcopy(inputs[1] if owner == "assignment" else inputs[2])
    del raw[key]
    obs = observation(inputs, **{owner: raw})
    assert obs.holds
    field = (
        obs.assignment_field(key)
        if owner == "assignment"
        else obs.submission_field(key)
    )
    assert field.present is False and field.value is None
    assert any(key in hold for hold in obs.holds)


@pytest.mark.parametrize(
    "owner,key,value",
    [
        ("assignment", "published", False),
        ("assignment", "moderated_grading", True),
        ("assignment", "group_category_id", 12),
        ("submission", "assignment_visible", False),
        ("submission", "excused", True),
        ("submission", "in_closed_grading_period", True),
        ("submission", "late", True),
        ("submission", "points_deducted", 1),
        ("submission", "late_policy_status", "late"),
    ],
)
def test_known_protection_values_are_retained_and_held(inputs, owner, key, value):
    raw = copy.deepcopy(inputs[1] if owner == "assignment" else inputs[2])
    raw[key] = value
    obs = observation(inputs, **{owner: raw})
    field = (
        obs.assignment_field(key)
        if owner == "assignment"
        else obs.submission_field(key)
    )
    assert (
        field.present
        and field.value == value
        and any(key in hold for hold in obs.holds)
    )


@pytest.mark.parametrize(
    "owner,key,value",
    [
        ("assignment", "id", 202),
        ("assignment", "course_id", 102),
        ("submission", "assignment_id", 202),
        ("submission", "user_id", 302),
        ("submission", "user_id", True),
    ],
)
def test_exact_target_identity_never_cross_binds(inputs, owner, key, value):
    raw = copy.deepcopy(inputs[1] if owner == "assignment" else inputs[2])
    raw[key] = value
    with pytest.raises(GradebookError):
        observation(inputs, **{owner: raw})


@pytest.mark.parametrize(
    "field,value",
    [
        ("origin", "http://canvas.example.invalid"),
        ("origin", "https://user:secret@canvas.example.invalid"),
        ("origin", "https://canvas.example.invalid/api"),
        ("course_id", "001"),
        ("user_id", "../301"),
        ("mode", "ATTEMPT_BOUND"),
        ("schema_version", True),
    ],
)
def test_target_rejects_invalid_scope_and_unsupported_attempt_mode(
    inputs, field, value
):
    target, assignment, submission = inputs
    with pytest.raises(GradebookError):
        observation((replace(target, **{field: value}), assignment, submission))


def test_original_get_rejects_foreign_origin_path_method_and_response(inputs):
    target, assignment, submission = inputs
    a_body, s_body = raw_bytes(assignment), raw_bytes(submission)
    a_get = OriginalGet(
        "GET", target.origin + "/api/v1/courses/101/assignments/201", 200, a_body
    )
    s_get = OriginalGet(
        "GET",
        target.origin
        + "/api/v1/courses/101/assignments/201/submissions/301?include[]=visibility&include[]=submission_comments",
        200,
        s_body,
        True,
    )
    kwargs = {
        "expected_assignment_body_sha256": hashlib.sha256(a_body).hexdigest(),
        "expected_submission_body_sha256": hashlib.sha256(s_body).hexdigest(),
    }
    for bad in [
        replace(
            s_get,
            url=s_get.url.replace("canvas.example.invalid", "foreign.example.invalid"),
        ),
        replace(s_get, url=s_get.url.replace("/301?", "/302?")),
        replace(s_get, url=s_get.url + "#fragment"),
        replace(s_get, url=s_get.url + "&foreign=1"),
        replace(s_get, method="PUT"),
        replace(s_get, status_code=404),
        replace(s_get, url=s_get.url.split("?")[0]),
    ]:
        with pytest.raises(GradebookError):
            parse_exact_observation(target, a_get, bad, **kwargs)


@pytest.mark.parametrize(
    "body", [b"[]", b'{"id":201,"id":202}', b'{"id":NaN}', b"not-json", b"\xff"]
)
def test_original_json_ambiguity_and_schema_fail_closed(inputs, body):
    target, _, submission = inputs
    s_body = raw_bytes(submission)
    with pytest.raises(GradebookError):
        parse_exact_observation(
            target,
            OriginalGet(
                "GET", target.origin + "/api/v1/courses/101/assignments/201", 200, body
            ),
            OriginalGet(
                "GET",
                target.origin
                + "/api/v1/courses/101/assignments/201/submissions/301?include[]=visibility&include[]=submission_comments",
                200,
                s_body,
                True,
            ),
            expected_assignment_body_sha256=hashlib.sha256(body).hexdigest(),
            expected_submission_body_sha256=hashlib.sha256(s_body).hexdigest(),
        )


def test_independent_source_hash_mismatch_is_rejected(inputs):
    target, assignment, submission = inputs
    a_body, s_body = raw_bytes(assignment), raw_bytes(submission)
    with pytest.raises(GradebookError):
        parse_exact_observation(
            target,
            OriginalGet(
                "GET",
                target.origin + "/api/v1/courses/101/assignments/201",
                200,
                a_body,
            ),
            OriginalGet(
                "GET",
                target.origin
                + "/api/v1/courses/101/assignments/201/submissions/301?include[]=visibility&include[]=submission_comments",
                200,
                s_body,
                True,
            ),
            expected_assignment_body_sha256="0" * 64,
            expected_submission_body_sha256=hashlib.sha256(s_body).hexdigest(),
        )


def test_extra_assignment_metadata_drift_changes_digest(inputs):
    raw = copy.deepcopy(inputs[1])
    raw["due_at"] = "2026-10-02T15:00:00Z"
    first, second = observation(inputs), observation(inputs, assignment=raw)
    assert first.assignment_metadata_sha256 != second.assignment_metadata_sha256


@pytest.mark.parametrize(
    "channel,payload,expected",
    [
        ("SCORE", "50.5", b"submission%5Bposted_grade%5D=50.5"),
        (
            "COMMENT",
            "Approved feedback + &\n\u03bc",
            b"comment%5Btext_comment%5D=Approved+feedback+%2B+%26%0A%CE%BC&comment%5Bgroup_comment%5D=false",
        ),
    ],
)
def test_actual_httpx_form_request_matches_independent_contract(
    inputs, channel, payload, expected
):
    spec = request_spec(observation(inputs), channel, payload)
    requests = []

    def handle(request):
        requests.append(request)
        assert request.method == "PUT"
        assert (
            str(request.url)
            == "https://canvas.example.invalid/api/v1/courses/101/assignments/201/submissions/301"
        )
        assert request.headers["content-type"] == "application/x-www-form-urlencoded"
        assert "authorization" not in request.headers
        assert request.content == expected
        return httpx.Response(200, json={"fictional": True})

    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        request = httpx.Request(spec.method, spec.url, data=dict(spec.form_fields))
        client.send(request)
    assert len(requests) == 1
    assert spec.encoded_body == expected
    assert spec.executable is False and spec.retry_writes is False
    assert "teacher_final_authority_not_connected" in spec.holds
    assert "release_authority_not_connected" in spec.holds
    fields = parse_qs(expected.decode())
    assert "comment[attempt]" not in fields
    assert (
        "submission[excuse]" not in fields
        and "submission[workflow_state]" not in fields
    )


@pytest.mark.parametrize(
    "channel,payload",
    [
        ("COMMENT", "line\r\nnext"),
        ("COMMENT", ""),
        ("COMMENT", "x" * 6001),
        ("SCORE", "EX"),
        ("SCORE", "-1"),
        ("SCORE", "101"),
        ("SCORE", "NaN"),
        ("BOTH", "50"),
    ],
)
def test_unsupported_payload_never_builds_request(inputs, channel, payload):
    with pytest.raises(GradebookError):
        request_spec(observation(inputs), channel, payload)


def test_approved_component_and_retained_observation_digests_are_independent(inputs):
    obs = observation(inputs)
    for observation_hash, component_hash in [
        ("0" * 64, "a" * 64),
        (digest(asdict(obs)), "0" * 64),
    ]:
        with pytest.raises(GradebookError):
            build_form_request_spec(
                obs,
                decision_sha256="a" * 64,
                target_binding_sha256="b" * 64,
                channel="SCORE",
                payload="50",
                publisher_author_id="701",
                expected_retained_observation_sha256=observation_hash,
                expected_component_sha256=component_hash,
            )


def comment_readback(inputs, *, duplicate=False, author=701, coverage=True):
    before = observation(inputs)
    raw = copy.deepcopy(inputs[2])
    raw["submission_comments"].append(
        {"id": 502, "author_id": author, "comment": "Approved feedback"}
    )
    if duplicate:
        raw["submission_comments"].append(
            {"id": 503, "author_id": author, "comment": "Approved feedback"}
        )
    after = observation(inputs, submission=raw, coverage=coverage)
    return before, after, request_spec(before, "COMMENT", "Approved feedback")


def test_response_linked_comment_is_independently_observed_but_no_release_is_created(
    inputs,
):
    before, after, spec = comment_readback(inputs)
    result = compare_comment_readback(
        spec,
        before,
        after,
        publisher_author_id="701",
        response_received=True,
        response_comment_id="502",
    )
    assert result.outcome == "VERIFIED_APPLIED" and result.stored_verified
    assert result.retry_writes is False and result.publication_authorized is False
    assert result.student_visibility == "NOT_ESTABLISHED"


def test_lost_response_unique_new_comment_is_qualified_and_never_resendable(inputs):
    before, after, spec = comment_readback(inputs)
    result = compare_comment_readback(
        spec, before, after, publisher_author_id="701", response_received=False
    )
    assert result.outcome == "OBSERVED_APPLIED" and not result.stored_verified
    assert result.retry_writes is False and not result.publication_authorized


@pytest.mark.parametrize(
    "variant",
    [
        "old",
        "duplicate",
        "foreign-author",
        "incomplete",
        "deleted-old",
        "changed-score",
        "changed-target",
        "wrong-id",
    ],
)
def test_comment_ambiguity_and_state_drift_never_report_complete(inputs, variant):
    before, after, spec = comment_readback(
        inputs,
        duplicate=variant == "duplicate",
        author=702 if variant == "foreign-author" else 701,
        coverage=False if variant == "incomplete" else True,
    )
    if variant == "old":
        raw = copy.deepcopy(inputs[2])
        raw["submission_comments"][0]["comment"] = "Approved feedback"
        before = after = observation(inputs, submission=raw)
        spec = request_spec(before, "COMMENT", "Approved feedback")
    if variant in ("deleted-old", "changed-score"):
        raw = copy.deepcopy(inputs[2])
        raw["submission_comments"].append(
            {"id": 502, "author_id": 701, "comment": "Approved feedback"}
        )
        if variant == "deleted-old":
            raw["submission_comments"] = raw["submission_comments"][1:]
        else:
            raw["score"] = 1
        after = observation(inputs, submission=raw)
    if variant == "changed-target":
        after = replace(after, target=replace(after.target, user_id="302"))
        with pytest.raises(GradebookError, match="OBSERVATION_INTEGRITY_MISMATCH"):
            compare_comment_readback(
                spec,
                before,
                after,
                publisher_author_id="701",
                response_received=True,
                response_comment_id="502",
            )
        return
    result = compare_comment_readback(
        spec,
        before,
        after,
        publisher_author_id="701",
        response_received=True,
        response_comment_id="999" if variant == "wrong-id" else "502",
    )
    assert not result.stored_verified and not result.retry_writes


def test_component_identity_stays_stable_across_disabled_spec_rebuilds(inputs):
    obs = observation(inputs)
    first, second = request_spec(obs, "COMMENT", "Approved feedback"), request_spec(
        obs, "COMMENT", "Approved feedback"
    )
    assert first.component_sha256 == second.component_sha256
    assert "release_token" not in asdict(first)


@pytest.mark.parametrize(
    "key,value",
    [
        ("excused", True),
        ("late", True),
        ("assignment_visible", None),
        ("points_deducted", False),
        ("grade", "EX"),
    ],
)
def test_operational_protections_cannot_verify_comment_readback(inputs, key, value):
    raw = copy.deepcopy(inputs[2])
    raw[key] = value
    held_inputs = (inputs[0], inputs[1], raw)
    before, after, spec = comment_readback(held_inputs)
    assert any(key in hold for hold in before.holds)
    result = compare_comment_readback(
        spec,
        before,
        after,
        publisher_author_id="701",
        response_received=True,
        response_comment_id="502",
    )
    assert result.outcome == "HELD" and not result.stored_verified
    assert any(key in hold for hold in result.holds)
    assert not result.retry_writes


def test_unselected_submission_metadata_drift_blocks_comment_verification(inputs):
    before, _, spec = comment_readback(inputs)
    raw = copy.deepcopy(inputs[2])
    raw["cached_due_date"] = "2026-10-03T00:00:00Z"
    raw["submission_comments"].append(
        {"id": 502, "author_id": 701, "comment": "Approved feedback"}
    )
    after = observation(inputs, submission=raw)
    result = compare_comment_readback(
        spec,
        before,
        after,
        publisher_author_id="701",
        response_received=True,
        response_comment_id="502",
    )
    assert result.outcome == "CONFLICT" and not result.stored_verified


@pytest.mark.parametrize(
    "origin",
    [
        "https://canvas.example.invalid\0",
        "https://canvas.example.invalid\x7f",
        "https://canvas.example.invalid:443",
        "https://canvas.example.invalid.",
        "https://canvas.example.invalid%40other.invalid",
        "https://Canvas.example.invalid",
        "https://canvas_example.invalid",
        "https://canvas.example.invalid?",
    ],
)
def test_origin_requires_canonical_https_dns_authority(inputs, origin):
    with pytest.raises(GradebookError, match="CANVAS_ORIGIN_INVALID"):
        observation((replace(inputs[0], origin=origin), inputs[1], inputs[2]))


def test_higher_existing_score_is_rejected_independent_of_disconnected_authority(
    inputs,
):
    raw = copy.deepcopy(inputs[2])
    raw["score"] = 90
    raw["grade"] = "90"
    with pytest.raises(GradebookError, match="HIGHER_CANVAS_SCORE_PROTECTED"):
        request_spec(observation(inputs, submission=raw), "SCORE", "50")


def test_form_spec_serialization_is_never_execution_or_publication_readiness(inputs):
    spec = request_spec(observation(inputs), "SCORE", "0")
    assert spec.execution_ready is False and spec.publication_ready is False
    assert "release_authority_not_connected" in spec.holds


@pytest.mark.parametrize(
    "field,value",
    [
        ("executable", True),
        ("retry_writes", True),
        ("method", "POST"),
        ("url", "https://foreign.example.invalid/"),
        ("form_fields", (("comment[attempt]", "1"),)),
        ("encoded_body", b"submission[posted_grade]=100"),
    ],
)
def test_tampered_request_spec_is_rejected_before_readback(inputs, field, value):
    before, after, spec = comment_readback(inputs)
    with pytest.raises(GradebookError):
        compare_comment_readback(
            replace(spec, **{field: value}),
            before,
            after,
            publisher_author_id="701",
            response_received=True,
            response_comment_id="502",
        )


@pytest.mark.parametrize("coverage", [None, False])
def test_coverage_unknown_is_retained_without_inference_from_comment_array(
    inputs, coverage
):
    obs = observation(inputs, coverage=coverage)
    assert obs.comment_coverage_complete is coverage
    assert "comment_coverage_unverified" in obs.holds


@pytest.mark.parametrize("value", [None, False, "0"])
def test_invalid_deduction_scalar_never_becomes_safe_zero(inputs, value):
    raw = copy.deepcopy(inputs[2])
    raw["points_deducted"] = value
    obs = observation(inputs, submission=raw)
    assert obs.submission_field("points_deducted").value is value
    assert "submission_points_deducted_held" in obs.holds


def test_duplicate_comment_ids_force_coverage_hold(inputs):
    raw = copy.deepcopy(inputs[2])
    raw["submission_comments"].append(copy.deepcopy(raw["submission_comments"][0]))
    obs = observation(inputs, submission=raw)
    assert obs.comment_coverage_complete is False
    assert "comment_coverage_unverified" in obs.holds


def test_non_unicode_scalar_feedback_is_refused_without_rewriting(inputs):
    with pytest.raises(GradebookError, match="EXACT_APPROVED_FEEDBACK_REQUIRED"):
        request_spec(observation(inputs), "COMMENT", "Malformed \ud800 feedback")


@pytest.mark.parametrize(
    "query",
    [
        "include[]=visibility&include[]=submission_comments&include[]=read_status",
        "include[]=visibility&include[]=visibility",
        "include[]=visibility&include[]=submission_comments&include[]=submission_comments",
    ],
)
def test_original_get_cannot_mark_read_or_infer_duplicate_query_coverage(inputs, query):
    target, assignment, submission = inputs
    a_body, s_body = raw_bytes(assignment), raw_bytes(submission)
    with pytest.raises(GradebookError):
        parse_exact_observation(
            target,
            OriginalGet(
                "GET",
                target.origin + "/api/v1/courses/101/assignments/201",
                200,
                a_body,
            ),
            OriginalGet(
                "GET",
                target.origin
                + "/api/v1/courses/101/assignments/201/submissions/301?"
                + query,
                200,
                s_body,
                True,
            ),
            expected_assignment_body_sha256=hashlib.sha256(a_body).hexdigest(),
            expected_submission_body_sha256=hashlib.sha256(s_body).hexdigest(),
        )


@pytest.mark.parametrize("suffix", ["?", "#", "?include[]=visibility"])
def test_original_assignment_get_has_no_query_or_fragment_delimiter(inputs, suffix):
    target, assignment, submission = inputs
    a_body, s_body = raw_bytes(assignment), raw_bytes(submission)
    with pytest.raises(GradebookError):
        parse_exact_observation(
            target,
            OriginalGet(
                "GET",
                target.origin + "/api/v1/courses/101/assignments/201" + suffix,
                200,
                a_body,
            ),
            OriginalGet(
                "GET",
                target.origin
                + "/api/v1/courses/101/assignments/201/submissions/301?include[]=visibility&include[]=submission_comments",
                200,
                s_body,
                True,
            ),
            expected_assignment_body_sha256=hashlib.sha256(a_body).hexdigest(),
            expected_submission_body_sha256=hashlib.sha256(s_body).hexdigest(),
        )


@pytest.mark.parametrize(
    "lexeme,accepted",
    [
        ("50.0000000000000001", False),
        ("1e309", False),
        ("0.1", True),
        ("0.5", True),
        ("50.0", True),
    ],
)
def test_original_numeric_lexeme_cannot_silently_round(inputs, lexeme, accepted):
    target, assignment, submission = inputs
    a_body = raw_bytes(assignment)
    s_body = raw_bytes(submission).replace(
        b'"score": null', ('"score": ' + lexeme).encode("ascii")
    )
    args = (
        target,
        OriginalGet(
            "GET", target.origin + "/api/v1/courses/101/assignments/201", 200, a_body
        ),
        OriginalGet(
            "GET",
            target.origin
            + "/api/v1/courses/101/assignments/201/submissions/301?include[]=visibility&include[]=submission_comments",
            200,
            s_body,
            True,
        ),
    )
    kwargs = {
        "expected_assignment_body_sha256": hashlib.sha256(a_body).hexdigest(),
        "expected_submission_body_sha256": hashlib.sha256(s_body).hexdigest(),
    }
    if accepted:
        obs = parse_exact_observation(*args, **kwargs)
        assert obs.submission_field("score").value == float(lexeme)
    else:
        with pytest.raises(GradebookError, match="ORIGINAL_JSON_NUMBER_UNSAFE"):
            parse_exact_observation(*args, **kwargs)


def test_target_identifiers_have_a_bounded_canonical_length(inputs):
    with pytest.raises(GradebookError, match="CANVAS_ID_INVALID"):
        observation((replace(inputs[0], user_id="1" * 21), inputs[1], inputs[2]))


def test_publisher_author_cannot_change_after_component_approval(inputs):
    before, after, spec = comment_readback(inputs, author=702)
    with pytest.raises(GradebookError, match="PUBLISHER_AUTHOR_MISMATCH"):
        compare_comment_readback(
            spec,
            before,
            after,
            publisher_author_id="702",
            response_received=True,
            response_comment_id="502",
        )


def test_old_comment_metadata_drift_blocks_even_when_id_author_body_match(inputs):
    raw = copy.deepcopy(inputs[2])
    raw["submission_comments"][0]["attachments"] = [
        {"id": 801, "filename": "Fictional-private-label"}
    ]
    bound_inputs = (inputs[0], inputs[1], raw)
    before = observation(bound_inputs)
    spec = request_spec(before, "COMMENT", "Approved feedback")
    changed = copy.deepcopy(raw)
    changed["submission_comments"][0]["attachments"] = []
    changed["submission_comments"].append(
        {"id": 502, "author_id": 701, "comment": "Approved feedback"}
    )
    after = observation(bound_inputs, submission=changed)
    result = compare_comment_readback(
        spec,
        before,
        after,
        publisher_author_id="701",
        response_received=True,
        response_comment_id="502",
    )
    assert result.outcome == "CONFLICT" and not result.stored_verified
    assert "Fictional-private-label" not in repr(before)


def test_every_comment_result_retains_authority_and_visibility_limits(inputs):
    before, after, spec = comment_readback(inputs)
    result = compare_comment_readback(
        spec,
        before,
        after,
        publisher_author_id="701",
        response_received=True,
        response_comment_id="502",
    )
    assert result.stored_verified
    assert "teacher_final_authority_not_connected" in result.holds
    assert "release_authority_not_connected" in result.holds
    assert "live_freshness_not_established" in result.holds
    assert not result.publication_authorized
    assert result.student_visibility == "NOT_ESTABLISHED"
