"""Actual pinned native/compact-formatter/queue proof, wholly fictional inputs."""

import hashlib
import os
from copy import deepcopy
from fractions import Fraction
from pathlib import Path

import pytest
from test_unit2_grass_bridge import build_fixture

from canvas_mcp.gradebook.model import GradebookError, digest
from canvas_mcp.gradebook.unit2_grass_bridge import recompute_fictional
from canvas_mcp.gradebook.unit2_partial_queue import prepare_shortened_comment_plan


def integration_fixture(*, all_correct=False):
    names = (
        "UNIT2_GRASS_BRIDGE_SOURCE",
        "UNIT2_NATIVE_PIPELINE_SOURCE",
        "UNIT2_COMPACT_FORMATTER_SOURCE",
        "UNIT2_COMPACT_CONTRACT_SOURCE",
        "UNIT2_NODE_PATH",
    )
    if not all(os.environ.get(name) for name in names):
        pytest.skip("Explicit reviewed source paths required")
    bp, pp, fp, cp, np = (Path(os.environ[name]) for name in names)
    values = build_fixture(bp, pp)
    if all_correct:
        for letter, mark in values["reading"]["items"][0]["option_marks"].items():
            mark["state"] = "CLEAR_MARK" if letter == "D" else "UNMARKED"
    native = recompute_fictional(**values)
    after = native["after_result"]
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
    binding.update(
        {
            key: values["snapshot"]["binding"][key]
            for key in (
                "packet_id",
                "source_sha256",
                "reading_key",
                "result_key",
                "policy_sha256",
                "form_id",
            )
        }
    )
    rows = [row for row in after["items"] if row["kind"] == "MC"]
    earned = sum(
        (Fraction(row["earned_points"]) * Fraction(row["weight"]) for row in rows),
        Fraction(),
    )
    result = {
        "contract": "UNIT2_MC_COMPONENT_V1",
        "binding": binding,
        "status": "MC_CLEARED",
        "mc_earned": str(earned),
        "mc_possible": "50",
        "frq_status": "PENDING_CLARIFICATION",
        "whole_test_grade": None,
        "feedback": "Full fictional audit retained: café.",
        "unresolved_items": [],
    }
    items = [
        {
            "item": int(row["item_id"][2:]),
            "possible_points": row["maximum_points"],
            "read_status": "READABLE",
            "student_choice": row["recorded_choice"],
            "key_choice": "D",
            "native_earned_points": row["earned_points"],
        }
        for row in rows
    ]
    projection = {
        "kind": "R1_MC_COMPONENT",
        "form_verified": True,
        "form": binding["form_id"],
        "identity": {
            "verified": True,
            "pin": "0001",
            "section": "DEMO",
            "test_form": binding["form_id"],
        },
        "source_binding": {
            "source_sha256": binding["source_sha256"],
            "reading_key": binding["reading_key"],
            "key_sha256": digest(values["form"]),
            "key_lookup_after_reading": True,
        },
        "component_possible": "50",
        "expected_items": [
            {"item": row["item"], "possible_points": row["possible_points"]}
            for row in items
        ],
        "items": items,
        "existing_feedback_body": result["feedback"],
        "frq_parts": [
            {
                "question": 1,
                "part_id": "a",
                "read_status": "UNREADABLE",
                "literal_text": None,
                "observation": None,
                "short_correction": None,
                "possible_points": "50",
                "earned_points": None,
            }
        ],
    }
    target = {
        "origin": "https://canvas.invalid",
        "course_id": "1",
        "assignment_id": "2",
        "user_id": "3",
        "attempt": None,
        "submitted_at": None,
        "submission_types": ["on_paper"],
    }
    kwargs = {
        "formatter_input": projection,
        "trusted_projection": deepcopy(projection),
        "formatter_path": fp,
        "formatter_sha256": hashlib.sha256(fp.read_bytes()).hexdigest(),
        "node_path": np,
        "feedback_contract_path": cp,
        "feedback_contract_sha256": hashlib.sha256(cp.read_bytes()).hexdigest(),
        "source_check": lambda *_: None,
    }
    return native, result, target, kwargs


def test_actual_native_compact_formatter_and_inert_queue():
    native, result, target, kwargs = integration_fixture()
    before = deepcopy((result, target, kwargs["formatter_input"]))
    plan = prepare_shortened_comment_plan(result, target, **kwargs)
    assert (result, target, kwargs["formatter_input"]) == before
    assert plan["comment_body"].splitlines()[0] == "0001 | DEMO | FICTIONAL_DEMO_FORM"
    assert "MC1: read-A | key-D | -2.5" in plan["comment_body"]
    assert "FRQ1a: read-unreadable | held" not in plan["comment_body"]
    assert "FRQ1a: read-unreadable | held" in plan["teacher_review"]["text"]
    assert "-0" not in plan["comment_body"]
    assert plan["representation"]["mc_earned"] == "95/2"
    assert plan["representation"]["feedback"] == result["feedback"]
    assert native["after_result"]["grade_preview"] is None
    assert plan["requests"] == [] and plan["whole_test_grade"] is None
    assert (
        plan["publisher_category_admitted"] is False
        and plan["publication_allowed"] is False
    )
    assert "posted_grade" not in repr(plan)
    assert plan["feedback_provenance"]["policy_id"] == "UNIT2_COMPACT_FEEDBACK_V2"
    changed = deepcopy(result)
    changed["mc_earned"] = "50"
    with pytest.raises(GradebookError, match="disagree"):
        prepare_shortened_comment_plan(changed, target, **kwargs)


def test_held_component_never_loads_formatter():
    _, result, target, kwargs = integration_fixture()
    result.update(status="MC_HELD", mc_earned=None, unresolved_items=["MC13"])
    kwargs["formatter_path"] = kwargs["feedback_contract_path"] = Path("unopened")
    plan = prepare_shortened_comment_plan(result, target, **kwargs)
    assert plan["state"] == "HELD" and "comment_body" not in plan


def test_all_correct_mc_retains_teacher_hold_without_student_comment():
    _, result, target, kwargs = integration_fixture(all_correct=True)
    plan = prepare_shortened_comment_plan(result, target, **kwargs)
    assert plan["state"] == "NO_COMMENT_REQUIRED"
    assert plan["feedback_required"] is False
    assert "comment_body" not in plan
    assert plan["teacher_review"]["required"] is True
    assert plan["teacher_review"]["row_count"] == 1
    assert plan["whole_test_grade"] is None and plan["requests"] == []


def test_v1_contract_is_not_silently_admitted(tmp_path):
    import json

    _, result, target, kwargs = integration_fixture()
    contract = json.loads(kwargs["feedback_contract_path"].read_bytes())
    contract["source_version"] = "UNIT2_COMPACT_FEEDBACK_V1"
    old = tmp_path / "v1.json"
    old.write_text(json.dumps(contract), encoding="utf-8")
    kwargs.update(
        feedback_contract_path=old,
        feedback_contract_sha256=hashlib.sha256(old.read_bytes()).hexdigest(),
    )
    with pytest.raises(GradebookError, match="Supported canonical"):
        prepare_shortened_comment_plan(result, target, **kwargs)


@pytest.mark.parametrize(
    "field,value",
    [
        ("teacher_review_text", "Mixed or stale teacher content"),
        ("teacher_review_row_count", True),
        ("deduction_row_count", 0),
        ("feedback_required", False),
        ("teacher_review_required", False),
    ],
)
def test_separate_v2_channel_metadata_is_required(monkeypatch, field, value):
    from canvas_mcp.gradebook import unit2_feedback

    _, result, target, kwargs = integration_fixture()
    projection = unit2_feedback.derive_projection(
        kwargs["formatter_input"],
        kwargs["trusted_projection"],
        formatter_path=kwargs["formatter_path"],
        formatter_sha256=kwargs["formatter_sha256"],
        node_path=kwargs["node_path"],
    )
    projection[field] = value
    monkeypatch.setattr(
        unit2_feedback, "derive_projection", lambda *_, **__: deepcopy(projection)
    )
    with pytest.raises(GradebookError, match="Separate canonical"):
        prepare_shortened_comment_plan(result, target, **kwargs)


def test_private_retention_validates_no_comment_teacher_metadata_without_store_writes():
    from unittest.mock import Mock

    from canvas_mcp.gradebook.store import Store
    from canvas_mcp.gradebook.unit2_partial_queue import retain_review

    _, result, target, kwargs = integration_fixture(all_correct=True)
    plan = prepare_shortened_comment_plan(result, target, **kwargs)
    store = Mock(spec=Store)
    store.save.return_value = (
        "fictional-artifact",
        Path("/fictional/no-file-written.json"),
    )
    assert retain_review(store, plan) == store.save.return_value
    store.save.assert_called_once_with("review", plan)
    store.reset_mock()
    bad = deepcopy(plan)
    bad["teacher_review"]["required"] = False
    bad["plan_id"] = digest({k: v for k, v in bad.items() if k != "plan_id"})
    with pytest.raises(GradebookError, match="Separate private teacher"):
        retain_review(store, bad)
    store.save.assert_not_called()
