"""Fictional retained U3 shapes, not real native commits or accepted grades."""

import copy

import pytest

from canvas_mcp.gradebook.client import GradebookError
from canvas_mcp.gradebook.model import digest
from canvas_mcp.gradebook.u3_feedback_staging import stage_u3_feedback


@pytest.fixture
def stage_inputs():
    binding = {
        "submission_id": "fictional-packet",
        "source_object_id": "fictional-source",
        "artifact_id": "fictional-artifact",
        "source_version": "fixture-v1",
        "policy_id": "fixture-policy",
        "form_id": "Core_A",
        **{
            k: str(i) * 64
            for i, k in enumerate(
                (
                    "evidence_key",
                    "assignment_context_hash",
                    "runtime_sha256",
                    "source_binding_id",
                    "key_sha256",
                ),
                start=1,
            )
        },
    }
    scored = {
        "state": "HOLD",
        "reasons": ["OFFICIAL_ATTEMPT_UNVERIFIED"],
        "exactScore": {"numerator": None, "denominator": 1},
        "total": None,
        "maximum": 100,
        "publication": "NOT_AUTHORIZED",
    }
    record = {
        "version": "u3-fleet-exact-result-v7",
        "result": scored,
        "observations": [{"id": "MC-1", "reasonSha256": "6" * 64}],
        "packetOnlyProvisional": {
            "state": "PROVISIONAL_UNLINKED",
            "identity": "UNVERIFIED",
            "officialAttempt": "UNVERIFIED",
            "teacherAccepted": False,
            "publicationAllowed": False,
        },
    }
    review = {**copy.deepcopy(scored), "state": "HELD"}
    envelope = {
        "contract": "U3_EXACT_RETENTION_V1",
        "binding": binding,
        "result": {"record": record, "recordHash": "7" * 64, "review": review},
    }
    findings = {
        "contract": "U3_EXACT_RETENTION_V1",
        "state": "HELD",
        "exact": scored["exactScore"],
        "total": None,
        "record_hash": "7" * 64,
        "source_binding_id": binding["source_binding_id"],
        "form_id": binding["form_id"],
        "policy_id": binding["policy_id"],
        "key_sha256": binding["key_sha256"],
        "source_version": binding["source_version"],
        "context_hash": binding["assignment_context_hash"],
        "publication": "NOT_AUTHORIZED",
        "packet_only_provisional": record["packetOnlyProvisional"],
    }
    return {
        "envelope": envelope,
        "findings": findings,
        "producer_ref": {"path": "/fictional/retained.json", "sha256": "8" * 64},
        "producer_source_refs": {
            "exact_store": {
                "path": "/fictional/U3FleetExactStore.gs",
                "sha256": "9" * 64,
            },
            "native_projection": {
                "path": "/fictional/U3NativeReviewGrades.gs",
                "sha256": "a" * 64,
            },
        },
    }


def test_current_packet_only_result_retained_with_precise_holds(stage_inputs):
    before = copy.deepcopy(stage_inputs)
    plan = stage_u3_feedback(**stage_inputs)
    assert stage_inputs == before
    assert plan["retained"]["envelope"] == before["envelope"]
    assert plan["state"] == "HELD_UNAPPROVED"
    assert plan["publisher_envelope"] is None
    assert plan["canvas_writes"] == plan["sheets_writes"] == 0
    assert not plan["teacher_accepted"] and not plan["publication_allowed"]
    assert {
        "SOURCE_RESULT_HELD",
        "PACKET_ONLY_IDENTITY_ATTEMPT_UNVERIFIED",
        "CANONICAL_FULL_FEEDBACK_EXPORT_REQUIRED",
        "EXACT_CANVAS_IDENTITY_ASSOCIATION_REQUIRED",
        "OFFICIAL_CANVAS_ATTEMPT_REQUIRED",
        "FINAL_NATIVE_SOURCE_COMMIT_FEEDBACK_AND_TARGET_VERIFICATION_REQUIRED",
    } <= set(plan["holds"])


def with_feedback(case):
    case["feedback"] = {
        "text": "MC-1: π⁺ remains unclear.\nFRQ: preserve this exact line.\nSecond paragraph — no repair.",
        "decision_sha256": "b" * 64,
        "source_pointers": [
            "/result/record/observations/0/reasonSha256",
            "/result/record/result/reasons/0",
        ],
        "response_refs": [
            {"path": "/fictional/full-response.json", "sha256": "c" * 64}
        ],
    }
    return case


def test_full_feedback_preserved_without_using_summary_as_body(stage_inputs):
    with_feedback(stage_inputs)
    plan = stage_u3_feedback(**stage_inputs)
    assert plan["retained"]["feedback"] == stage_inputs["feedback"]
    assert plan["stage_snapshot_sha256"] == digest(plan["retained"])
    assert plan["producer_record_hash"] == "7" * 64
    assert plan["producer_record_hash"] != plan["stage_snapshot_sha256"]
    assert "CANONICAL_FULL_FEEDBACK_EXPORT_REQUIRED" not in plan["holds"]
    assert plan["publisher_envelope"] is None


def test_target_or_source_flag_does_not_promote_unlinked_packet(stage_inputs):
    stage_inputs["target"] = {
        "origin": "https://canvas.example.edu",
        "course_id": "11",
        "assignment_id": "22",
        "user_id": "33",
        "attempt": 2,
        "submitted_at": "2026-11-14T12:00:00Z",
    }
    stage_inputs["source_check"] = lambda packet: True
    plan = stage_u3_feedback(**stage_inputs)
    assert plan["source_owner_verified"] is False
    assert "PACKET_ONLY_IDENTITY_ATTEMPT_UNVERIFIED" in plan["holds"]
    assert plan["publisher_envelope"] is None


def test_trusted_owner_checks_entire_tuple_and_still_grants_no_delivery(stage_inputs):
    with_feedback(stage_inputs)
    expected = copy.deepcopy(stage_inputs)
    calls = []

    def fictional_owner(packet):
        assert packet == {**expected, "target": None}
        calls.append(packet)
        packet["envelope"]["binding"]["submission_id"] = "only-the-copy"

    plan = stage_u3_feedback(**stage_inputs, source_check=fictional_owner)
    assert len(calls) == 1 and plan["source_owner_verified"] is True
    assert stage_inputs["envelope"]["binding"]["submission_id"] == "fictional-packet"
    assert not plan["publication_allowed"] and plan["publisher_envelope"] is None
    assert "TEACHER_COMMENT_ACCEPTANCE_REQUIRED" in plan["holds"]


@pytest.mark.parametrize("answer", [False, True, {"approved": True}, 0, "PASS"])
def test_saved_or_untyped_approval_cannot_authenticate_source(stage_inputs, answer):
    assert (
        stage_u3_feedback(**stage_inputs, source_check=lambda packet: answer)[
            "source_owner_verified"
        ]
        is False
    )


def test_async_or_throwing_owner_remains_held(stage_inputs):
    async def async_owner(packet):
        return None

    def failed_owner(packet):
        raise RuntimeError("private payload must not escape")

    for checker in (async_owner, failed_owner):
        plan = stage_u3_feedback(**stage_inputs, source_check=checker)
        assert not plan["source_owner_verified"]
        assert "private payload" not in str(plan)


@pytest.mark.parametrize(
    "field",
    [
        "record_hash",
        "source_binding_id",
        "form_id",
        "policy_id",
        "key_sha256",
        "source_version",
        "context_hash",
        "exact",
        "total",
        "state",
        "publication",
    ],
)
def test_changed_review_binding_rejects(stage_inputs, field):
    stage_inputs["findings"][field] = "changed"
    with pytest.raises(GradebookError, match="U3_FINDINGS_BINDING"):
        stage_u3_feedback(**stage_inputs)


@pytest.mark.parametrize(
    "pointer",
    [
        "/result/record/observations/9",
        "/result/record/missing",
        "/result/record/observations/-1",
        "/result/~bad",
        "relative",
        "/result/record/observations/00",
    ],
)
def test_missing_or_ambiguous_reason_locator_rejects(stage_inputs, pointer):
    with_feedback(stage_inputs)["feedback"]["source_pointers"] = [pointer]
    with pytest.raises(GradebookError, match="U3_FEEDBACK_SOURCE_POINTER"):
        stage_u3_feedback(**stage_inputs)


@pytest.mark.parametrize("text", [" x\n", "a\rb", "x" * 6001])
def test_publisher_format_mismatch_preserved_and_held_not_rewritten(stage_inputs, text):
    with_feedback(stage_inputs)["feedback"]["text"] = text
    plan = stage_u3_feedback(**stage_inputs)
    assert plan["retained"]["feedback"]["text"] == text
    assert "EXACT_FEEDBACK_PUBLISHER_FORMAT_REVIEW_REQUIRED" in plan["holds"]


@pytest.mark.parametrize(
    "attempt,time",
    [
        (True, "2026-11-14T12:00:00Z"),
        (0, "2026-11-14T12:00:00Z"),
        (1, "2026-11-14T12:00:00"),
        (1, None),
    ],
)
def test_guessed_attempt_and_naive_time_reject(stage_inputs, attempt, time):
    stage_inputs["target"] = {
        "origin": "https://canvas.example.edu",
        "course_id": "11",
        "assignment_id": "22",
        "user_id": "33",
        "attempt": attempt,
        "submitted_at": time,
    }
    with pytest.raises(GradebookError, match="U3_OFFICIAL_ATTEMPT"):
        stage_u3_feedback(**stage_inputs)


def test_read_only_module_imports_no_publisher_store_or_transport():
    import ast
    import inspect
    from pathlib import Path

    tree = ast.parse(
        Path(inspect.getfile(stage_u3_feedback)).read_text(encoding="utf-8")
    )
    assert not any(
        isinstance(n, ast.ImportFrom)
        and n.module in {"publish", "store", "server", "ledger"}
        for n in ast.walk(tree)
    )


def test_direct_library_nonfinite_value_returns_fixed_hold_error(stage_inputs):
    stage_inputs["findings"]["extra"] = float("inf")
    with pytest.raises(GradebookError, match="U3_FINITE_JSON_INPUT_REQUIRED"):
        stage_u3_feedback(**stage_inputs)
