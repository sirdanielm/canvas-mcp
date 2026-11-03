"""Fictional, offline checks for the unregistered Unit 2 private proposal adapter."""

import hashlib
import json
from copy import deepcopy

import pytest

from canvas_mcp.gradebook.model import GradebookError, digest
from canvas_mcp.gradebook.unit2_partial_queue import (
    prepare_comment_plan,
    prepare_reading_request,
)


def fixture_pair():
    binding = {
        key: digest({"fictional": key})
        for key in (
            "packet_id",
            "source_sha256",
            "reading_key",
            "result_key",
            "policy_sha256",
            "candidate_sha256",
            "dashboard_card_sha256",
        )
    }
    binding["form_id"] = "FICTIONAL_FORM"
    return (
        {
            "contract": "UNIT2_MC_COMPONENT_V1",
            "binding": binding,
            "status": "MC_CLEARED",
            "mc_earned": "125/3",
            "mc_possible": "50",
            "frq_status": "PENDING_CLARIFICATION",
            "whole_test_grade": None,
            "feedback": "FICTIONAL existing feedback, retained literally.",
            "unresolved_items": [],
        },
        {
            "origin": "https://canvas.invalid",
            "course_id": "1",
            "assignment_id": "2",
            "user_id": "3",
            "attempt": None,
            "submitted_at": None,
            "submission_types": ["on_paper"],
        },
    )


def source_check(result, target):
    """Fictional fixture qualification, never a production authority callback."""
    assert (result, target) == fixture_pair()


def formatter(representation):
    assert representation["whole_test_numeric"] == "UNCHANGED"
    assert representation["mc_possible"] == "50"
    return (
        "DEMO_NOT_TEACHER_ACCEPTED: MC 125/3 of 50; FRQ pending. "
        + representation["feedback"]
    )


def test_fictional_plan_is_inert_exact_component_and_preserves_inputs():
    result, target = fixture_pair()
    before = deepcopy((result, target))
    plan = prepare_comment_plan(
        result, target, source_check=source_check, formatter=formatter
    )
    assert (result, target) == before
    assert plan["state"] == "UNAPPROVED"
    assert plan["requests"] == []
    assert plan["representation"]["mc_earned"] == "125/3"
    assert plan["representation"]["feedback"] == result["feedback"]
    assert plan["whole_test_grade"] is None
    assert "posted_grade" not in repr(plan)
    for flag in (
        "teacher_acceptance",
        "publication_allowed",
        "score_delivery_authorized",
        "comment_delivery_authorized",
        "publisher_category_admitted",
    ):
        assert plan[flag] is False
    assert plan["plan_id"] == digest({k: v for k, v in plan.items() if k != "plan_id"})
    assert (
        prepare_comment_plan(
            result, target, source_check=source_check, formatter=formatter
        )
        == plan
    )


@pytest.mark.parametrize("value", [True, 41.5, "51", "-1", "1/0", "NaN", None])
def test_invalid_or_inexact_component_fails_closed(value):
    result, target = fixture_pair()
    result["mc_earned"] = value
    with pytest.raises(GradebookError):
        prepare_comment_plan(
            result, target, source_check=lambda *_: None, formatter=formatter
        )


@pytest.mark.parametrize(
    "field,value",
    [
        ("whole_test_grade", "83"),
        ("frq_status", "COMPLETE"),
        ("mc_possible", "100"),
        ("contract", "UNIT1"),
        ("unresolved_items", ["FICTIONAL_MC1"]),
    ],
)
def test_unsupported_partial_result_fails_closed(field, value):
    result, target = fixture_pair()
    result[field] = value
    with pytest.raises(GradebookError):
        prepare_comment_plan(
            result, target, source_check=lambda *_: None, formatter=formatter
        )


def test_held_component_never_formats_or_awards():
    result, target = fixture_pair()
    result.update(status="MC_HELD", mc_earned=None, unresolved_items=["FICTIONAL_MC1"])

    def forbidden(_):
        pytest.fail("Held evidence must not invoke the comment formatter")

    plan = prepare_comment_plan(
        result, target, source_check=lambda *_: None, formatter=forbidden
    )
    assert plan["state"] == "HELD"
    assert "comment_body" not in plan and "representation" not in plan
    assert plan["whole_test_grade"] is None and plan["requests"] == []


@pytest.mark.parametrize(
    "change",
    [
        {"submission_types": ["online_upload"]},
        {"attempt": True},
        {"attempt": 1},
        {"origin": "http://canvas.invalid"},
        {"origin": "https://canvas.invalid:99999"},
        {"course_id": "01"},
    ],
)
def test_unqualified_target_fails_closed(change):
    result, target = fixture_pair()
    target.update(change)
    with pytest.raises(GradebookError):
        prepare_comment_plan(
            result, target, source_check=lambda *_: None, formatter=formatter
        )


@pytest.mark.parametrize("body", ["", " padded ", "x" * 6001, None, True])
def test_formatter_output_must_be_exact_bounded_text(body):
    with pytest.raises(GradebookError):
        prepare_comment_plan(
            *fixture_pair(), source_check=source_check, formatter=lambda _: body
        )


def test_callbacks_are_synchronous_and_cannot_return_approval_booleans():
    async def asynchronous(*_):
        return None

    for check in (asynchronous, lambda *_: True, lambda *_: False):
        with pytest.raises(GradebookError):
            prepare_comment_plan(
                *fixture_pair(), source_check=check, formatter=formatter
            )
    with pytest.raises(GradebookError):
        prepare_comment_plan(
            *fixture_pair(), source_check=source_check, formatter=asynchronous
        )


def test_callbacks_receive_disposable_copies():
    result, target = fixture_pair()
    before = deepcopy((result, target))

    def mutate_source(candidate, observed):
        candidate["mc_earned"] = "0"
        observed["course_id"] = "999"

    plan = prepare_comment_plan(
        result, target, source_check=mutate_source, formatter=formatter
    )
    assert (result, target) == before
    assert plan["target"]["course_id"] == "1"
    assert plan["representation"]["mc_earned"] == "125/3"


def decision_fixture():
    marks = {
        option: {
            "state": "UNCLEAR" if option == "D" else "UNMARKED",
            "observation": "Fictional captured observation",
        }
        for option in "ABCD"
    }
    binding = {
        key: digest({"fictional": key})
        for key in (
            "packet_id",
            "source_sha256",
            "reading_key",
            "result_key",
            "policy_sha256",
            "before_item_sha256",
        )
    }
    binding.update(form_id="FICTIONAL_FORM", attempt="R1", item_id="MC13")
    choice = {
        "contract_id": "grass.unit2.mc-teacher-decision.v1.1",
        "mode": "DEMO",
        "decision_id": "fictional-decision-1",
        "binding": binding,
        "option_marks_before": marks,
        "method": {
            "kind": "DEMO",
            "measurement_status": "UNAVAILABLE",
            "measurements": dict.fromkeys("ABCD"),
            "sidecar_sha256": None,
        },
        "actor": {"kind": "DEMO", "attestation": "Fictional demonstration only"},
        "choice": "D",
        "reason": "Fictional explicit decision; café",
    }
    current = {
        "binding": deepcopy(binding),
        "option_marks_before": deepcopy(marks),
        "decision_receipts": {},
    }
    return choice, current


def test_frozen_demo_request_and_exact_unicode_replay():
    choice, current = decision_fixture()
    plan = prepare_reading_request(choice, current, verify_teacher=lambda *_: None)
    assert plan["state"] == "DEMO_NOT_TEACHER_ACCEPTED"
    assert plan["requests"] == [] and plan["teacher_acceptance"] is False
    sha = hashlib.sha256(
        json.dumps(
            choice, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode("utf-8")
    ).hexdigest()
    current["decision_receipts"][choice["decision_id"]] = {
        "decision_sha256": sha,
        "plan": plan,
    }
    assert (
        prepare_reading_request(choice, current, verify_teacher=lambda *_: None) == plan
    )
    changed = deepcopy(choice)
    changed["choice"] = "A"
    with pytest.raises(GradebookError):
        prepare_reading_request(changed, current, verify_teacher=lambda *_: None)
    current["binding"]["result_key"] = "0" * 64
    with pytest.raises(GradebookError):
        prepare_reading_request(choice, current, verify_teacher=lambda *_: None)


@pytest.mark.parametrize("field", ["binding", "option_marks_before"])
def test_frozen_current_state_drift_fails_closed(field):
    choice, current = decision_fixture()
    if field == "binding":
        current[field]["before_item_sha256"] = "0" * 64
    else:
        current[field]["D"]["observation"] = "Changed fictional observation"
    with pytest.raises(GradebookError):
        prepare_reading_request(choice, current, verify_teacher=lambda *_: None)
