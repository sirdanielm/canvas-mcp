"""Fictional manual-partial note tests; no student, native or network actions."""

import copy
import hashlib

import pytest
from test_gradebook import snapshot as snapshot
from test_gradebook_native import binding as binding
from test_gradebook_native import raw_from_state
from test_unit2_note_draft import applied
from test_unit2_note_draft import scenario as scenario

from canvas_mcp.gradebook import native
from canvas_mcp.gradebook.client import GradebookError
from canvas_mcp.gradebook.model import digest
from canvas_mcp.gradebook.unit2_note_draft import (
    MANUAL_PARTIAL_CONTRACT,
    MANUAL_PARTIAL_SOURCE,
    classify_readback,
    prepare_note_draft,
    revalidate_note_draft,
)


@pytest.fixture
def manual(scenario):
    value = copy.deepcopy(scenario)
    c = value["candidate"]
    c.update(
        contract=MANUAL_PARTIAL_CONTRACT,
        source_version=MANUAL_PARTIAL_SOURCE,
        component_scope="MANUAL_PARTIAL",
        body="Fictional partial correction; unresolved evidence remains held.",
    )
    c["source_pins"] = dict.fromkeys(
        [
            "source_sha256",
            "reading_sha256",
            "judgment_sha256",
            "policy_sha256",
            "proposal_sha256",
        ],
        "a" * 64,
    )
    c["source_pins"]["body_sha256"] = hashlib.sha256(c["body"].encode()).hexdigest()
    c["manual_context"] = {
        "original_manifest_contract": "ORIGINAL_PACKET_SAVED_PROPOSALS_QC_ADVANCE_V1",
        "whole_test_proposed_score": None,
        "native_context": {"result_key": None, "grade_preview": None, "holds": None},
        "remaining_holds": [
            {"item_id": "FICTIONAL_MC12", "reason": "SOURCE_WORDING_UNKNOWN"}
        ],
        "original_proposal_ref": {
            "path": "/fictional/unchanged-manual-manifest.json",
            "bytes": 123,
            "sha256": "a" * 64,
        },
        "actual_authored_body_version": None,
        "review_state": {"status": "NOT_REVIEWED", "ref": None},
    }
    return value


@pytest.mark.parametrize("value", [{"numberValue": 77}, {"formulaValue": "=1+2"}, {}])
def test_manual_partial_only_changes_note_and_preserves_every_other_cell(manual, value):
    state = native._state(manual["raw"])
    cell = state["sheets"][2]["cells"]["5:2"]
    cell["userEnteredValue"] = value
    cell["note"] = "Existing teacher note\r\nwith trailing space "
    manual["raw"] = raw_from_state(state)
    original = copy.deepcopy(manual)
    plan = prepare_note_draft(**manual)
    assert manual == original
    after = native._state(applied(plan))
    before = native._state(manual["raw"])
    note = after["sheets"][2]["cells"]["5:2"]["note"]
    assert note.startswith(cell["note"] + "\n\n")
    assert (
        "UNAPPROVED manual partial feedback draft. Whole-test proposed score: NULL."
        in note
    )
    assert manual["candidate"]["body"] in note
    before["sheets"][2]["cells"]["5:2"]["note"] = note
    assert before == after
    assert plan["numeric_grade_disposition"] == "UNCHANGED"
    assert plan["candidate"]["manual_context"]["native_context"]["holds"] is None
    assert (
        plan["candidate"]["manual_context"]["remaining_holds"]
        == original["candidate"]["manual_context"]["remaining_holds"]
    )
    assert plan["teacher_accepted"] is False and plan["publication_allowed"] is False


def test_manual_source_does_not_need_a_fabricated_result_or_formatter(manual):
    plan = prepare_note_draft(**manual)
    assert "result_sha256" not in plan["candidate"]["source_pins"]
    assert "formatter_sha256" not in plan["candidate"]["source_pins"]
    assert plan["candidate"]["source_version"] == MANUAL_PARTIAL_SOURCE


@pytest.mark.parametrize(
    "key",
    [
        "source_sha256",
        "reading_sha256",
        "judgment_sha256",
        "policy_sha256",
        "proposal_sha256",
        "body_sha256",
    ],
)
def test_exact_current_manual_lineage_pins_required(manual, key):
    del manual["candidate"]["source_pins"][key]
    with pytest.raises(GradebookError):
        prepare_note_draft(**manual)


@pytest.mark.parametrize("value", [0, "0", "100/3", False])
def test_partial_scope_cannot_supply_whole_test_score(manual, value):
    manual["candidate"]["manual_context"]["whole_test_proposed_score"] = value
    with pytest.raises(GradebookError):
        prepare_note_draft(**manual)


@pytest.mark.parametrize("key,value", [("holds", []), ("grade_preview", 0)])
def test_absent_native_result_not_replaced_with_manual_component_holds(
    manual, key, value
):
    manual["candidate"]["manual_context"]["native_context"][key] = value
    with pytest.raises(GradebookError):
        prepare_note_draft(**manual)


def test_absent_native_result_pin_not_fabricated(manual):
    manual["candidate"]["source_pins"]["result_sha256"] = "a" * 64
    with pytest.raises(GradebookError):
        prepare_note_draft(**manual)


def test_actual_existing_native_result_and_holds_can_be_preserved(manual):
    manual["candidate"]["manual_context"]["native_context"] = {
        "result_key": "b" * 64,
        "grade_preview": None,
        "holds": [{"reason": "FICTIONAL_NATIVE_HOLD"}],
    }
    plan = prepare_note_draft(**manual)
    assert (
        plan["candidate"]["manual_context"]["native_context"]
        == manual["candidate"]["manual_context"]["native_context"]
    )


def test_body_bytes_and_original_proposal_ref_are_bound(manual):
    manual["candidate"]["body"] += " altered"
    with pytest.raises(GradebookError):
        prepare_note_draft(**manual)


def test_manual_cannot_be_relabeled_canonical_v2(manual):
    manual["candidate"]["source_version"] = "UNIT2_COMPACT_FEEDBACK_V2"
    with pytest.raises(GradebookError):
        prepare_note_draft(**manual)


def test_wrong_original_manifest_family_is_held(manual):
    manual["candidate"]["manual_context"]["original_manifest_contract"] = (
        "UNRELATED_AUTHOR"
    )
    with pytest.raises(GradebookError):
        prepare_note_draft(**manual)


def test_not_reviewed_is_truthful_and_not_a_visibility_gate(manual):
    plan = prepare_note_draft(**manual)
    assert plan["candidate"]["manual_context"]["review_state"] == {
        "status": "NOT_REVIEWED",
        "ref": None,
    }
    assert plan["requests"]


def test_source_owner_checker_remains_mandatory_and_cannot_mutate_snapshot(manual):
    seen = []

    def check(candidate, *_):
        seen.append(copy.deepcopy(candidate))
        candidate["manual_context"]["original_proposal_ref"]["path"] = (
            "/fictional/unread-other.json"
        )

    manual["source_check"] = check
    plan = prepare_note_draft(**manual)
    assert plan["candidate"] == seen[0]
    manual["source_check"] = lambda *_: True
    with pytest.raises(GradebookError):
        prepare_note_draft(**manual)


def test_manual_exact_preimage_readback_and_no_blind_retry(manual):
    plan = prepare_note_draft(**manual)
    pin = digest(plan)
    revalidate_note_draft(
        plan,
        raw=manual["raw"],
        expected_plan_sha256=pin,
        source_check=manual["source_check"],
    )
    assert (
        classify_readback(plan, applied(plan), expected_plan_sha256=pin)["status"]
        == "PLANNED_OUTPUT_OBSERVED"
    )
    result = classify_readback(plan, manual["raw"], expected_plan_sha256=pin)
    assert (
        result["status"] == "BEFORE_STILL_PRESENT" and result["retry_writes"] is False
    )
    changed = native._state(applied(plan))
    changed["sheets"][2]["cells"]["5:2"]["userEnteredValue"] = {"numberValue": 0}
    assert (
        classify_readback(plan, raw_from_state(changed), expected_plan_sha256=pin)[
            "status"
        ]
        == "DIVERGED"
    )


def test_same_manual_note_no_duplicate_append(manual):
    plan = prepare_note_draft(**manual)
    manual["raw"] = applied(plan)
    repeated = prepare_note_draft(**manual)
    assert repeated["status"] == "NO_CHANGE" and repeated["requests"] == []
