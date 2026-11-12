"""Fictional private target protection; no real student identifiers."""

import copy
import hashlib
import json

import pytest

from canvas_mcp.gradebook.canvas_primary_protection import (
    assert_target_unprotected,
    read_protection_registry,
)
from canvas_mcp.gradebook.client import GradebookError


@pytest.fixture
def protection(tmp_path):
    data = {
        "contract": "CANVAS_PRIMARY_TARGET_PROTECTION_V1",
        "population_state": "COMPLETE",
        "population_evidence_sha256": "a" * 64,
        "protected_students": [
            {"user_id": "101", "evidence_sha256": "b" * 64},
            {"user_id": "102", "evidence_sha256": "c" * 64},
        ],
        "coverage": [
            {
                "course_id": "12",
                "user_id": "101",
                "state": "INCOMPLETE",
                "evidence_sha256": "d" * 64,
            }
        ],
        "protected_targets": [
            {
                "course_id": "12",
                "assignment_id": "21",
                "user_id": "101",
                "evidence_sha256": "e" * 64,
            }
        ],
    }
    p = tmp_path / "policy.json"
    p.write_text(json.dumps(data))
    p.chmod(0o600)
    return data, p, hashlib.sha256(p.read_bytes()).hexdigest()


def authority(expected):
    def verify(actual, target):
        assert actual == expected and set(target) == {
            "course_id",
            "user_id",
            "assignment_id",
        }

    return verify


def test_exact_protected_target_held_regardless_of_grade(protection):
    data, p, pin = protection
    policy = read_protection_registry(p, pin)
    for grade in (None, 0, 5, 20):
        with pytest.raises(GradebookError, match="PROTECTED_TARGET_HELD"):
            assert_target_unprotected(
                policy,
                {"course_id": "12", "assignment_id": "21", "user_id": "101"},
                {"value": grade, "grade": grade},
                authority(data),
            )


def test_unrelated_student_and_other_unprotected_blank_allowed(protection):
    data, p, pin = protection
    policy = read_protection_registry(p, pin)
    assert_target_unprotected(
        policy,
        {"course_id": "12", "assignment_id": "22", "user_id": "999"},
        {"value": 0, "grade": "0"},
        authority(data),
    )
    assert_target_unprotected(
        policy,
        {"course_id": "12", "assignment_id": "22", "user_id": "101"},
        {"value": None, "grade": None},
        authority(data),
    )


def test_monitored_student_zero_requires_complete_scope(protection):
    data, p, pin = protection
    policy = read_protection_registry(p, pin)
    for target in (
        {"course_id": "12", "assignment_id": "22", "user_id": "101"},
        {"course_id": "13", "assignment_id": "22", "user_id": "101"},
        {"course_id": "12", "assignment_id": "22", "user_id": "102"},
    ):
        with pytest.raises(GradebookError, match="PROTECTED_ZERO_PROVENANCE_HELD"):
            assert_target_unprotected(
                policy, target, {"value": 0, "grade": "0"}, authority(data)
            )
    data["coverage"][0]["state"] = "COMPLETE"
    p.write_text(json.dumps(data))
    p.chmod(0o600)
    policy = read_protection_registry(p, hashlib.sha256(p.read_bytes()).hexdigest())
    assert_target_unprotected(
        policy,
        {"course_id": "12", "assignment_id": "22", "user_id": "101"},
        {"value": 0, "grade": "0"},
        authority(data),
    )


@pytest.mark.parametrize(
    "change",
    [
        "missing",
        "tampered",
        "public_mode",
        "incomplete_population",
        "empty_complete",
        "duplicate_subject",
        "duplicate_target",
        "unrecognized_student",
        "invalid_id",
        "missing_authority",
    ],
)
def test_registry_and_authority_fail_closed(protection, change):
    data, p, pin = protection
    if change == "missing":
        p.unlink()
    elif change == "tampered":
        p.write_text("{}")
    elif change == "public_mode":
        p.chmod(0o644)
    else:
        if change == "incomplete_population":
            data["population_state"] = "INCOMPLETE"
        elif change == "empty_complete":
            data["protected_targets"] = []
            data["coverage"][0]["state"] = "COMPLETE"
        elif change == "duplicate_subject":
            data["protected_students"].append(
                copy.deepcopy(data["protected_students"][0])
            )
        elif change == "duplicate_target":
            data["protected_targets"].append(
                copy.deepcopy(data["protected_targets"][0])
            )
        elif change == "unrecognized_student":
            data["protected_targets"][0]["user_id"] = "777"
        elif change == "invalid_id":
            data["protected_students"][0]["user_id"] = "00101"
        if change != "missing_authority":
            p.write_text(json.dumps(data))
            p.chmod(0o600)
            pin = hashlib.sha256(p.read_bytes()).hexdigest()
    with pytest.raises(GradebookError):
        policy = read_protection_registry(p, pin)
        assert_target_unprotected(
            policy,
            {"course_id": "12", "assignment_id": "22", "user_id": "999"},
            {"value": 0, "grade": "0"},
            None if change == "missing_authority" else authority(data),
        )


def test_authority_cannot_mutate_registry_during_check(protection):
    data, p, pin = protection
    policy = read_protection_registry(p, pin)

    def bad(registry, target):
        registry["protected_targets"].clear()

    with pytest.raises(GradebookError, match="PROTECTED_TARGET_HELD"):
        assert_target_unprotected(
            policy,
            {"course_id": "12", "assignment_id": "21", "user_id": "101"},
            {"value": 0, "grade": "0"},
            bad,
        )


def test_duplicate_json_keys_are_invalid(protection):
    _, p, _ = protection
    p.write_text(
        '{"contract":"CANVAS_PRIMARY_TARGET_PROTECTION_V1","contract":"CANVAS_PRIMARY_TARGET_PROTECTION_V1"}'
    )
    p.chmod(0o600)
    with pytest.raises(GradebookError, match="PROTECTION_REGISTRY_HELD"):
        read_protection_registry(p, hashlib.sha256(p.read_bytes()).hexdigest())


def test_duplicate_target_key_in_otherwise_complete_document_holds(protection):
    data, p, _ = protection
    raw = json.dumps(data)
    # Add a later duplicate that would erase known protected cells under last-wins.
    raw = raw[:-1] + ', "protected_targets": []}'
    p.write_text(raw)
    p.chmod(0o600)
    with pytest.raises(GradebookError, match="PROTECTION_REGISTRY_HELD"):
        read_protection_registry(p, hashlib.sha256(p.read_bytes()).hexdigest())


def test_zero_grade_string_holds_even_if_numeric_score_is_blank(protection):
    data, p, pin = protection
    policy = read_protection_registry(p, pin)
    with pytest.raises(GradebookError, match="PROTECTED_ZERO_PROVENANCE_HELD"):
        assert_target_unprotected(
            policy,
            {"course_id": "12", "assignment_id": "22", "user_id": "101"},
            {"value": None, "grade": "0"},
            authority(data),
        )
