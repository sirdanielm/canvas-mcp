"""Fictional capture/PIN boundary checks; no live endpoints or student data."""

import hashlib
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from canvas_mcp.gradebook.capture import build_case_receipt, save_capture
from canvas_mcp.gradebook.client import GradebookError
from canvas_mcp.gradebook.model import digest
from canvas_mcp.gradebook.store import Store


@pytest.fixture
def captured(tmp_path):
    store = Store(tmp_path / "store")
    snapshot = {
        "schema_version": 1,
        "origin": "https://canvas.example.invalid",
        "course_id": "101",
        "fetched_at": "2026-10-01T10:00:00+00:00",
        "scope": "Active student enrollments; published graded assignments",
        "students": [{"id": "201", "name": "Fictional Teacher Fixture"}],
        "assignments": [{"id": "301"}],
        "cells": {"201:301": {"visible": True, "attempt": 1}},
    }
    registry = tmp_path / "pin-registry.json"
    roster = tmp_path / "roster.json"
    registry.write_bytes(b"fictional independently bound registry")
    roster.write_bytes(b"fictional independently retained roster")
    registry_hash = hashlib.sha256(registry.read_bytes()).hexdigest()
    roster_hash = hashlib.sha256(roster.read_bytes()).hexdigest()
    binding = {
        "roster_sheet": "Student Info",
        "roster_sha256": roster_hash,
        "email_column": "Email",
    }
    rows = [
        {
            "Canvas ID": "201",
            "Email": "fictional@example.invalid",
            "Student Number": "0042",
        }
    ]
    shared = SimpleNamespace(
        binding=lambda _: (binding, roster, roster.read_bytes(), registry_hash),
        read_table=lambda *args: (["Canvas ID", "Email", "Student Number"], rows),
        roster_index=lambda *args: ({"fictional@example.invalid": "0042"}, {}),
    )
    receipt_id = save_capture(store, snapshot)
    kwargs = {
        "expected_origin": snapshot["origin"],
        "expected_course_id": "101",
        "assignment_id": "301",
        "academic_assignment_id": "academic-fictional-2.2b",
        "user_id": "201",
        "case_id": "case-fictional",
        "sources": [
            {
                "source_ref": "page-1",
                "relative_path": "original.bin",
                "sha256": "a" * 64,
                "size_bytes": 4,
                "schema_version": 1,
            }
        ],
        "records": [{"record_key": "record-1", "source_refs": ["page-1"]}],
        "expected_record_keys": ["record-1"],
        "registry_path": registry,
        "shared_tool": Path("unused-fictional-tool.py"),
    }
    return store, snapshot, receipt_id, shared, kwargs, rows, roster


def build(fixture, **changes):
    store, _, receipt_id, shared, kwargs, _, _ = fixture
    with patch(
        "canvas_mcp.gradebook.capture.load_shared_pin_module", return_value=shared
    ):
        return build_case_receipt(store, receipt_id, **dict(kwargs, **changes))


def test_join_preserves_leading_zeros_excludes_raw_identity_and_is_deterministic(
    captured,
):
    result = build(captured)
    assert result == build(captured)
    assert result["identity"]["student_pin"] == "0042"
    assert result["identity"]["state"] == "RESOLVED"
    assert result["capture_revision"] == captured[2]
    assert set(result) == {
        "schema_version",
        "producer",
        "course_id",
        "assignment_id",
        "canvas_assignment_id",
        "case_id",
        "capture_revision",
        "capture_state",
        "identity",
        "expected_record_keys",
        "records",
        "sources",
        "scoring_manifest",
    }
    assert "fictional@example.invalid" not in str(result)
    assert "Fictional Teacher Fixture" not in str(result)
    assert "user_id" not in result


@pytest.mark.parametrize(
    "changes,code",
    [
        ({"expected_course_id": "102"}, "CAPTURE_SCOPE_MISMATCH"),
        (
            {"expected_origin": "https://wrong.example.invalid"},
            "CAPTURE_SCOPE_MISMATCH",
        ),
        ({"assignment_id": "302"}, "CAPTURE_TARGET_MISMATCH"),
        ({"user_id": "202"}, "CAPTURE_TARGET_MISMATCH"),
        (
            {"expected_record_keys": ["record-1", "missing-record"]},
            "SOURCE_COVERAGE_MISMATCH",
        ),
        (
            {"records": [{"record_key": "record-1", "source_refs": ["other-page"]}]},
            "SOURCE_COVERAGE_MISMATCH",
        ),
    ],
)
def test_exact_scope_and_coverage_hold(captured, changes, code):
    with pytest.raises(GradebookError, match=code):
        build(captured, **changes)


@pytest.mark.parametrize(
    "mutation,code",
    [
        (lambda snap: snap["students"].append({"id": "202"}), "CAPTURE_INCOMPLETE"),
        (
            lambda snap: snap["cells"]["201:301"].update(visible=False),
            "CAPTURE_TARGET_HELD",
        ),
        (
            lambda snap: snap["cells"]["201:301"].update(attempt=None),
            "CAPTURE_TARGET_HELD",
        ),
    ],
)
def test_missing_population_visibility_or_attempt_holds(captured, mutation, code):
    store, snapshot, _, shared, kwargs, _, _ = captured
    mutation(snapshot)
    receipt_id = save_capture(store, snapshot)
    with patch(
        "canvas_mcp.gradebook.capture.load_shared_pin_module", return_value=shared
    ):
        with pytest.raises(GradebookError, match=code):
            build_case_receipt(store, receipt_id, **kwargs)


def test_working_baseline_cannot_be_used_as_get_receipt(captured):
    store, snapshot, _, shared, kwargs, _, _ = captured
    wrong, _ = store.save(
        "receipt",
        {
            "schema_version": 1,
            "kind": "WORKBOOK_BASELINE",
            "snapshot_id": digest(snapshot),
        },
    )
    with patch(
        "canvas_mcp.gradebook.capture.load_shared_pin_module", return_value=shared
    ):
        with pytest.raises(GradebookError, match="CAPTURE_SCOPE_MISMATCH"):
            build_case_receipt(store, wrong, **kwargs)


def test_conflicting_canvas_identity_holds(captured):
    captured[5].append(dict(captured[5][0]))
    with pytest.raises(GradebookError, match="CANVAS_PIN_JOIN_CONFLICT"):
        build(captured)


def test_changed_roster_during_join_holds(captured):
    shared, roster = captured[3], captured[6]

    def index(*args):
        roster.write_bytes(b"changed bytes")
        return {"fictional@example.invalid": "0042"}, {}

    shared.roster_index = index
    with pytest.raises(GradebookError, match="PIN_AUTHORITY_CHANGED"):
        build(captured)


@pytest.mark.parametrize(
    "path", ["../outside.bin", "/outside.bin", "a//b", "a\\b", "a\nb"]
)
def test_unsafe_original_paths_hold(captured, path):
    source = dict(captured[4]["sources"][0], relative_path=path)
    with pytest.raises(GradebookError, match="SOURCE_CATALOG_INVALID"):
        build(captured, sources=[source])


def test_duplicate_source_assignment_holds(captured):
    records = [{"record_key": "record-1", "source_refs": ["page-1", "page-1"]}]
    with pytest.raises(GradebookError, match="SOURCE_COVERAGE_MISMATCH"):
        build(captured, records=records)


def test_unicode_intake_hash_uses_explicit_canonical_v1_without_changing_store_ids(
    captured,
):
    from canvas_mcp.gradebook.capture import intake_digest

    source = dict(captured[4]["sources"][0], relative_path="original-é.bin")
    receipt = build(captured, sources=[source])
    import json

    expected = hashlib.sha256(
        json.dumps(
            receipt,
            sort_keys=True,
            ensure_ascii=False,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()
    assert intake_digest(receipt) == expected
    assert intake_digest(receipt) != digest(receipt)


@pytest.mark.parametrize("value", [1.0, {"float": 1.0}, {1: "wrong"}])
def test_intake_hash_does_not_coerce_floats_or_object_keys(value):
    from canvas_mcp.gradebook.capture import intake_digest

    with pytest.raises(GradebookError, match="INTAKE_DIGEST_VALUE_INVALID"):
        intake_digest(value)


def test_academic_identity_is_independent_of_canvas_destination(captured):
    receipt = build(captured)
    assert receipt["assignment_id"] == "academic-fictional-2.2b"
    assert receipt["canvas_assignment_id"] == "301"
    assert receipt["assignment_id"] != receipt["canvas_assignment_id"]
    with pytest.raises(GradebookError, match="ACADEMIC_ASSIGNMENT_INVALID"):
        build(captured, academic_assignment_id="")
