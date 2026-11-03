"""Fictional pure Q:R:S planning. No real target designation or I/O."""

import copy

import pytest
from test_gradebook import snapshot as snapshot
from test_gradebook_native import binding as binding
from test_unit2_manual_partial_note_draft import manual as manual
from test_unit2_note_draft import scenario as scenario

from canvas_mcp.gradebook.client import GradebookError
from canvas_mcp.gradebook.model import digest
from canvas_mcp.gradebook.unit2_manual_partial_projection import (
    prepare_partial_projection,
)


def ref(label):
    return {"path": "/fictional/" + label, "bytes": 12, "sha256": "f" * 64}


@pytest.fixture
def destination(manual):
    c = manual["candidate"]
    row = {
        "status": "CURRENT_UNIQUE_SOURCE_ROW_VERIFIED",
        "row": 7,
        "candidate_sha256": digest(c),
        "source_sha256": c["source_pins"]["source_sha256"],
        "reading_sha256": c["source_pins"]["reading_sha256"],
        "ref": ref("row-binding.json"),
    }
    mapping = {
        "status": "OWNER_DESIGNATED_FOR_MANUAL_PARTIAL_PROPOSALS",
        "source_role": "MANUAL_PARTIAL",
        "workbook_id": "fictional-unit2-sheet",
        "sheet_id": 123,
        "tab": "Grades",
        "designation_ref": ref("partial-designation.json"),
        "structure_snapshot_ref": ref("structure.json"),
        "fields": {
            "proposed_feedback": "Q7",
            "proposal_ref": "R7",
            "proposal_status": "S7",
        },
        "protected_whole_score_cell": "P7",
        "grid_bounds": {"first_data_row": 7, "row_count": 406, "column_count": 26},
        "source_row_binding": row,
    }
    target = {
        k: copy.deepcopy(mapping[k])
        for k in [
            "workbook_id",
            "sheet_id",
            "tab",
            "structure_snapshot_ref",
            "grid_bounds",
            "source_row_binding",
        ]
    }
    target.update(
        snapshot_ref=ref("typed-snapshot.json"),
        designation_sha256=digest(mapping),
        prior_outcome="KNOWN_NOT_SENT",
        cells={
            "P7": {"userEnteredFormat": {"numberFormat": {"type": "TEXT"}}},
            "Q7": {},
            "R7": {},
            "S7": {},
        },
    )
    return {
        "candidate": c,
        "designation": mapping,
        "snapshot": target,
        "source_check": lambda *_: None,
    }


def reseal(value):
    value["snapshot"]["designation_sha256"] = digest(value["designation"])


def test_distinct_partial_contract_preserves_score_blank_and_source(destination):
    before = copy.deepcopy(destination)
    plan = prepare_partial_projection(**destination)
    assert destination == before
    assert [x["cell"] for x in plan["changes"]] == ["Q7", "R7", "S7"]
    assert (
        plan["protected_whole_score_cell"]["after"]
        == destination["snapshot"]["cells"]["P7"]
    )
    assert plan["whole_test_proposed_score"] is None
    assert (
        plan["changes"][0]["after"]["userEnteredValue"]["stringValue"]
        == destination["candidate"]["body"]
    )
    assert (
        plan["changes"][2]["after"]["userEnteredValue"]["stringValue"]
        == "PARTIAL_NOT_REVIEWED"
    )
    assert plan["requests"] == [] and plan["live_write_allowed"] is False
    assert (
        plan["remaining_component_holds"]
        == destination["candidate"]["manual_context"]["remaining_holds"]
    )
    assert plan["native_context_preserved"]["holds"] is None
    assert plan["teacher_accepted"] is False and plan["publication_allowed"] is False


def test_existing_whole_designation_is_not_partial_authority(destination):
    destination["designation"]["status"] = "OWNER_DESIGNATED_FOR_PROPOSALS"
    reseal(destination)
    with pytest.raises(GradebookError):
        prepare_partial_projection(**destination)


@pytest.mark.parametrize(
    "name,value",
    [
        ("P7", {"userEnteredValue": {"numberValue": 0}}),
        ("P7", {"userEnteredValue": {"stringValue": ""}}),
        ("Q7", {"note": "teacher"}),
        ("Q7", {"userEnteredValue": {"formulaValue": "=1"}}),
        ("R7", {"chipRuns": []}),
        ("S7", {"textFormatRuns": []}),
    ],
)
def test_occupied_or_ambiguous_cell_never_cleared(destination, name, value):
    destination["snapshot"]["cells"][name] = value
    with pytest.raises(GradebookError):
        prepare_partial_projection(**destination)


def test_current_unique_source_row_is_not_inferred(destination):
    destination["snapshot"].pop("source_row_binding")
    with pytest.raises(GradebookError):
        prepare_partial_projection(**destination)


def test_wrong_source_row_or_candidate_held(destination):
    destination["designation"]["source_row_binding"]["candidate_sha256"] = "c" * 64
    destination["snapshot"]["source_row_binding"] = copy.deepcopy(
        destination["designation"]["source_row_binding"]
    )
    reseal(destination)
    with pytest.raises(GradebookError):
        prepare_partial_projection(**destination)


@pytest.mark.parametrize("prior", ["UNKNOWN", "SEND_UNCERTAIN", "SENT"])
def test_uncertain_prior_action_never_replanned(destination, prior):
    destination["snapshot"]["prior_outcome"] = prior
    with pytest.raises(GradebookError):
        prepare_partial_projection(**destination)


def test_header_row_rejected_after_rehash(destination):
    m = destination["designation"]
    m["fields"] = {k: v.replace("7", "6") for k, v in m["fields"].items()}
    m["protected_whole_score_cell"] = "P6"
    reseal(destination)
    with pytest.raises(GradebookError):
        prepare_partial_projection(**destination)


def test_wider_column_scope_rejected_after_rehash(destination):
    destination["designation"]["fields"]["proposed_feedback"] = "T7"
    reseal(destination)
    with pytest.raises(GradebookError):
        prepare_partial_projection(**destination)


def test_unreviewed_and_unknown_not_visibility_gates(destination):
    destination["candidate"]["manual_context"]["review_state"] = {
        "status": "UNKNOWN",
        "ref": None,
    }
    digest_now = digest(destination["candidate"])
    destination["designation"]["source_row_binding"]["candidate_sha256"] = digest_now
    destination["snapshot"]["source_row_binding"]["candidate_sha256"] = digest_now
    reseal(destination)
    plan = prepare_partial_projection(**destination)
    assert (
        plan["changes"][2]["after"]["userEnteredValue"]["stringValue"]
        == "PARTIAL_REVIEW_UNKNOWN"
    )


def test_owner_callback_authenticates_designation_and_source_without_mutation(
    destination,
):
    seen = []

    def verify(c, m, s):
        seen.append((copy.deepcopy(c), copy.deepcopy(m), copy.deepcopy(s)))
        c["body"] = "changed"
        m["fields"]["proposed_feedback"] = "A7"
        s["cells"]["P7"] = {}

    destination["source_check"] = verify
    plan = prepare_partial_projection(**destination)
    assert plan["candidate"] == seen[0][0] and plan["designation"] == seen[0][1]
    destination["source_check"] = lambda *_: True
    with pytest.raises(GradebookError):
        prepare_partial_projection(**destination)
