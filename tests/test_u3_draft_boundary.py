"""Fictional U3-shaped projections at existing generic Canvas boundaries.

This does not implement or authenticate a U3 source adapter. The owner callback
is the source/identity authority; the projection is not a real U3 result.
"""

import copy

import pytest
import test_gradebook_proposal_preview as preview_fixtures
import test_teacher_edit_transfer as transfer_fixtures
from test_gradebook import snapshot as snapshot
from test_gradebook_native import binding as binding

from canvas_mcp.gradebook.client import GradebookError
from canvas_mcp.gradebook.model import digest
from canvas_mcp.gradebook.proposal_edit_transfer import prepare_proposal_transfer
from canvas_mcp.gradebook.proposal_preview import prepare_preview
from canvas_mcp.gradebook.teacher_edit_transfer import prepare_transfer


@pytest.fixture
def projected():
    case = preview_fixtures.scenario.__wrapped__()
    case["proposals"][0]["policy"] = "FICTIONAL_U3_50_25_25"
    preview_fixtures.repin(case)
    return case


@pytest.fixture
def transfer_case(snapshot, binding):
    args, _ = transfer_fixtures.scenario.__wrapped__(snapshot, binding)
    record = args["record"]
    record["policy"] = "FICTIONAL_U3_50_25_25"
    proposal = {
        **{
            k: record[k]
            for k in ("evaluation_id", "source_revision", "result_revision", "policy")
        },
        "proposal_revision": "proposal-" + record["result_revision"],
        "approval_state": "UNAPPROVED",
        "academic_accepted": False,
        "total_score": record["proposed_score"],
        "points_possible": 20,
        "score_units": "CANVAS_POINTS",
        "feedback": "Fictional complete itemized feedback.\nSecond item evidence.",
    }
    args.pop("decision")
    args["proposal"] = proposal
    # This stands in for a separately authenticated source owner. It checks
    # the entire bound input, not flags in an untrusted U3 machine result.
    expected = (
        copy.deepcopy(record),
        copy.deepcopy(proposal),
        copy.deepcopy(args["pin_binding"]),
    )

    def source_check(record, proposal, pins):
        if (record, proposal, pins) != expected:
            raise ValueError("fictional source, result, target or identity changed")

    args["source_check"] = source_check
    return args


def test_complete_pair_is_only_an_unapproved_local_draft(transfer_case):
    plan = prepare_proposal_transfer(**transfer_case)
    update = plan["requests"][0]["updateCells"]["rows"][0]["values"][0]
    assert update["userEnteredValue"] == {"numberValue": 16}
    assert update["note"].endswith(transfer_case["proposal"]["feedback"])
    assert "UNAPPROVED" in update["note"]
    assert plan["record"]["pin"] == "0042" and plan["record"]["user_id"] == "101"
    assert plan["record"]["pin"] != plan["record"]["user_id"]
    assert plan["proposal"]["academic_accepted"] is False
    assert plan["score_delivery_authorized"] is False
    assert plan["comment_delivery_authorized"] is False
    assert plan["canvas_writes"] == plan["sheets_writes"] == 0
    with pytest.raises(GradebookError):
        prepare_transfer(
            transfer_case["record"],
            transfer_case["proposal"],
            **{
                k: v
                for k, v in transfer_case.items()
                if k not in {"record", "proposal"}
            },
        )


@pytest.mark.parametrize(
    "change",
    [
        "held",
        "null_total",
        "unknown_target",
        "duplicate_pin",
        "feedback_missing",
        "changed_source",
    ],
)
def test_local_draft_rejects_unqualified_projection(transfer_case, change):
    if change == "held":
        transfer_case["record"]["state"] = "HELD"
    elif change == "null_total":
        transfer_case["proposal"]["total_score"] = None
    elif change == "unknown_target":
        transfer_case["record"]["user_id"] = ""
    elif change == "duplicate_pin":
        transfer_case["pin_binding"]["by_pin"]["0043"] = "101"
    elif change == "feedback_missing":
        transfer_case["proposal"]["feedback"] = ""
    else:
        transfer_case["record"]["source_revision"] = "0" * 64
        transfer_case["proposal"]["source_revision"] = "0" * 64
    with pytest.raises(GradebookError):
        prepare_proposal_transfer(**transfer_case)


def test_complete_projected_pair_preview_has_no_publication_authority(projected):
    plan = prepare_preview(**projected)
    assert len(plan["envelope"]["edits"]) == 1
    assert plan["proposals"][0]["feedback"] == projected["proposals"][0]["feedback"]
    assert plan["review_state"] == "UNAPPROVED"
    assert plan["requests"] == [] and plan["canvas_writes"] == 0
    assert all(
        plan[k] is False
        for k in (
            "teacher_approval",
            "score_approval",
            "comment_approval",
            "publication_allowed",
        )
    )


@pytest.mark.parametrize(
    "change",
    ["held", "partial_reason", "null_score", "candidate_only", "feedback_missing"],
)
def test_incomplete_or_identity_candidate_only_is_documentary_hold(projected, change):
    row = projected["proposals"][0]
    if change == "held":
        row["state"] = "HELD"
    elif change == "partial_reason":
        row["reasons"] = ["FRQ_MASTERY_UNKNOWN"]
    elif change == "null_score":
        row["proposed_score"] = None
    elif change == "candidate_only":
        row["user_id"] = ""
    else:
        row["feedback"] = ""
    preview_fixtures.repin(projected)
    plan = prepare_preview(**projected)
    assert plan["envelope"]["edits"] == []
    assert plan["held_proposals"][0]["review_state"] == "HELD"
    assert plan["held_proposals"][0]["documentary_only"] is True
    assert plan["publication_allowed"] is False and plan["canvas_writes"] == 0


def test_duplicate_target_is_not_silently_selected(projected):
    duplicate = copy.deepcopy(projected["proposals"][0])
    duplicate["evaluation_id"] = "fictional-distinct-result"
    binding = copy.deepcopy(projected["assignment_bindings"][0])
    binding["evaluation_id"] = duplicate["evaluation_id"]
    binding["proposal_sha256"] = digest(duplicate)
    projected["proposals"].append(duplicate)
    projected["assignment_bindings"].append(binding)
    plan = prepare_preview(**projected)
    assert not plan["envelope"]["edits"]
    assert [x["code"] for x in plan["holds"]] == [
        "DUPLICATE_TARGET",
        "DUPLICATE_TARGET",
    ]
    assert plan["publication_allowed"] is False


def test_preview_rejects_source_change_even_if_candidate_is_rehashed(projected):
    original = copy.deepcopy(projected["proposals"])

    def source_check(rows, *_):
        if rows != original:
            raise ValueError("fictional retained source changed")

    projected["source_check"] = source_check
    projected["proposals"][0]["source_revision"] = "changed-source"
    preview_fixtures.repin(projected)
    with pytest.raises(GradebookError, match="SOURCE_AUTHORITY_REVALIDATION_HELD"):
        prepare_preview(**projected)


def test_candidate_identity_with_plausible_user_id_needs_owner_admission(projected):
    # The generic receiver does not know U3 candidate identity semantics.
    # This controlled owner callback models the required fail-closed boundary;
    # it is not evidence that a production U3 adapter already exists.
    row = projected["proposals"][0]
    row["identity_status"] = "U3_PIN_SIS_CANDIDATE"
    preview_fixtures.repin(projected)

    def source_check(rows, *_):
        if any(
            r.get("identity_status") != "EXACT_CANVAS_IDENTITY_CONFIRMED" for r in rows
        ):
            raise ValueError("candidate is not a qualified Canvas identity")

    projected["source_check"] = source_check
    with pytest.raises(GradebookError, match="SOURCE_AUTHORITY_REVALIDATION_HELD"):
        prepare_preview(**projected)


def test_raw_u3_held_result_is_not_a_generic_proposal(projected):
    projected["proposals"] = [
        {
            "contract": "U3_EXACT_RETENTION_V1",
            "state": "HELD",
            "total": None,
            "identity_status": "U3_PIN_SIS_CANDIDATE",
            "publication": "NOT_AUTHORIZED",
        }
    ]
    with pytest.raises(GradebookError, match="PRODUCER_REFERENCE_REQUIRED"):
        prepare_preview(**projected)


@pytest.mark.parametrize(
    "field",
    ["teacher_approval", "score_approval", "comment_approval", "publication_allowed"],
)
def test_producer_flags_cannot_grant_final_or_publication_authority(projected, field):
    projected["proposals"][0][field] = True
    preview_fixtures.repin(projected)
    plan = prepare_preview(**projected)
    assert plan["envelope"]["edits"] == []
    assert plan["holds"][0]["code"] == "PROPOSAL_AUTHORITY_HELD"
    assert plan["publication_allowed"] is False and plan["canvas_writes"] == 0
