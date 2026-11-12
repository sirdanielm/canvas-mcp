"""Fictional source-owner tests: no live data, writes, or provider calls."""

import copy
import hashlib

import pytest
import test_teacher_edit_transfer as fixtures
from test_gradebook import snapshot as snapshot
from test_gradebook_native import binding as binding
from test_gradebook_native import initial_raw

from canvas_mcp.gradebook.canvas_primary_review import (
    prepare_primary_review_transfer,
    revalidate_primary_review_transfer,
)
from canvas_mcp.gradebook.client import GradebookError
from canvas_mcp.gradebook.model import digest


@pytest.fixture
def case(tmp_path, snapshot, binding):
    args, _ = fixtures.scenario.__wrapped__(snapshot, binding)
    rec = args["record"]
    for snap in (args["baseline"], args["current"]):
        snap["cells"]["101:21"]["workflow_state"] = "submitted"
    proposal = {
        **{
            k: rec[k]
            for k in ("evaluation_id", "source_revision", "result_revision", "policy")
        },
        "proposal_revision": "proposal-" + rec["result_revision"],
        "approval_state": "UNAPPROVED",
        "academic_accepted": False,
        "total_score": 20,
        "points_possible": 20,
        "score_units": "CANVAS_POINTS",
        "feedback": "Private participation evidence reviewed.",
    }
    rec["proposed_score"] = 20
    rec.update(
        policy="2" * 64, source_lane="SDMGRASS_FORMATIVE", delivery_policy="SCORE_ONLY"
    )
    proposal.update(
        policy="2" * 64, source_lane="SDMGRASS_FORMATIVE", delivery_policy="SCORE_ONLY"
    )
    p = tmp_path / "original.jpg"
    p.write_bytes(b"fictional image bytes")
    meta = {
        "id": rec["assignment_id"],
        "course_id": rec["course_id"],
        "submission_types": ["online_upload"],
        "external_tool_tag_attributes": None,
    }
    ab = {
        "course_id": rec["course_id"],
        "assignment_id": rec["assignment_id"],
        "provider": "Canvas",
        "excluded": False,
        "assignment_metadata": meta,
        "assignment_metadata_sha256": digest(meta),
    }
    evidence = {
        "contract": "CANVAS_PRIMARY_VISUAL_ADVISORY_V1",
        "state": "REVIEWED_ADVISORY",
        "teacher_accepted": False,
        "publication_allowed": False,
        "holds": [],
        "source_lane": "CANVAS_CURRENT_UPLOAD_VISUAL_OCR",
        "policy": "ASSIGNED_QUESTION_HALF_FULL_PARTICIPATION",
        "ocr_state": "ALL_SOURCE_FILES_VALIDATED",
        "correct_assignment": True,
        "submission_type": "online_upload",
        "required": 9,
        "attempted_lower_bound": 8,
        "review_sha256": "1" * 64,
        "policy_sha256": "2" * 64,
        "canvas_source_sha256": "3" * 64,
        "assignment_sha256": digest(meta),
        "current_cell_sha256": digest(
            args["current"]["cells"][rec["user_id"] + ":" + rec["assignment_id"]]
        ),
        "record_sha256": digest(rec),
        "proposal_sha256": digest(proposal),
        "originals": [
            {"path": str(p), "sha256": hashlib.sha256(p.read_bytes()).hexdigest()}
        ],
        **{
            k: rec[k]
            for k in ("course_id", "assignment_id", "user_id", "canvas_attempt", "pin")
        },
    }
    for snap in (args["baseline"], args["current"]):
        assignment = next(
            a for a in snap["assignments"] if a["id"] == rec["assignment_id"]
        )
        assignment["assignment_metadata"] = copy.deepcopy(meta)
        assignment["assignment_metadata_sha256"] = digest(meta)
    args["raw"] = initial_raw(args["baseline"], binding)
    expected = copy.deepcopy(evidence)

    def authority(actual):
        if actual != expected:
            raise ValueError("source or review changed")

    args.pop("decision")
    args.pop("source_check")
    protection = {
        "contract": "CANVAS_PRIMARY_TARGET_PROTECTION_V1",
        "population_state": "COMPLETE",
        "population_evidence_sha256": "a" * 64,
        "protected_students": [{"user_id": "202", "evidence_sha256": "b" * 64}],
        "coverage": [],
        "protected_targets": [],
    }

    def protection_authority(registry, target):
        if registry != protection:
            raise ValueError("unverified protection source")

    args.update(
        evidence=evidence,
        proposal=proposal,
        assignment_binding=ab,
        authority=authority,
        protection_registry=protection,
        protection_authority=protection_authority,
    )
    return args


def test_valid_is_only_an_unapproved_existing_native_plan(case):
    result = prepare_primary_review_transfer(**case)
    assert len(result["transfer"]["requests"]) == 1
    assert result["canvas_writes"] == result["sheets_writes"] == 0
    assert result["teacher_accepted"] is result["publication_allowed"] is False
    assert result["transfer"]["proposal"]["total_score"] == 20
    assert result["transfer"]["delivery_policy"] == "SCORE_ONLY"
    assert (
        result["transfer"]["requests"][0]["updateCells"]["fields"] == "userEnteredValue"
    )
    revalidate_primary_review_transfer(
        result,
        expected_plan_sha256=digest(result),
        authority=case["authority"],
        protection_registry=case["protection_registry"],
        protection_authority=case["protection_authority"],
        raw=case["raw"],
        current=case["current"],
        pin_binding=case["pin_binding"],
    )


@pytest.mark.parametrize(
    "change",
    [
        "held",
        "wrong_assignment",
        "partial_ocr",
        "threshold",
        "null_score",
        "changed_bytes",
        "duplicate_pin",
        "edpuzzle",
        "changed_attempt",
        "stale_grade",
        "no_authority",
    ],
)
def test_rejects_unqualified_or_changed_case(case, change):
    if change == "held":
        case["evidence"]["holds"] = ["MISSING_PAGE"]
    elif change == "wrong_assignment":
        case["evidence"]["correct_assignment"] = False
    elif change == "partial_ocr":
        case["evidence"]["ocr_state"] = "HELD"
    elif change == "threshold":
        case["evidence"]["attempted_lower_bound"] = 4
    elif change == "null_score":
        case["proposal"]["total_score"] = None
    elif change == "changed_bytes":
        open(case["evidence"]["originals"][0]["path"], "wb").write(b"changed")
    elif change == "duplicate_pin":
        case["pin_binding"]["by_pin"]["9999"] = case["record"]["user_id"]
    elif change == "edpuzzle":
        case["assignment_binding"]["provider"] = "Edpuzzle"
    elif change == "changed_attempt":
        case["current"]["cells"][
            f"{case['record']['user_id']}:{case['record']['assignment_id']}"
        ]["attempt"] += 1
    elif change == "stale_grade":
        case["current"]["cells"][
            f"{case['record']['user_id']}:{case['record']['assignment_id']}"
        ]["grade_matches_current_submission"] = False
    else:
        case["authority"] = None
    with pytest.raises(GradebookError):
        prepare_primary_review_transfer(**case)


def test_revalidation_rejects_changed_source_and_plan(case):
    plan = prepare_primary_review_transfer(**case)
    expected = digest(plan)
    plan["evidence"]["attempted_lower_bound"] = 9
    with pytest.raises(GradebookError, match="PRIMARY_PLAN_CHANGED"):
        revalidate_primary_review_transfer(
            plan,
            expected_plan_sha256=expected,
            authority=case["authority"],
            protection_registry=case["protection_registry"],
            protection_authority=case["protection_authority"],
            raw=case["raw"],
            current=case["current"],
            pin_binding=case["pin_binding"],
        )


def _rebind_fake_owner(case):
    """Represent a genuine fresh owner response, not a self-authorizing receipt."""
    case["evidence"]["current_cell_sha256"] = digest(
        case["current"]["cells"][
            case["record"]["user_id"] + ":" + case["record"]["assignment_id"]
        ]
    )
    expected = copy.deepcopy(case["evidence"])

    def authority(actual):
        if actual != expected:
            raise ValueError("changed owner evidence")

    case["authority"] = authority
    case["raw"] = initial_raw(case["baseline"], case["binding"])


def test_exact_reviewed_stale_grade_flag_is_preserved_not_rewritten(case):
    key = case["record"]["user_id"] + ":" + case["record"]["assignment_id"]
    for snap in (case["baseline"], case["current"]):
        snap["cells"][key]["grade_matches_current_submission"] = False
        snap["cells"][key]["value"] = 0
        snap["cells"][key]["grade"] = "0"
    _rebind_fake_owner(case)
    plan = prepare_primary_review_transfer(**case)
    assert (
        plan["transfer"]["current_basis"]["cell"]["grade_matches_current_submission"]
        is False
    )
    assert plan["transfer"]["current_basis"]["cell"]["value"] == 0
    assert len(plan["transfer"]["requests"]) == 1
    revalidate_primary_review_transfer(
        plan,
        expected_plan_sha256=digest(plan),
        authority=case["authority"],
        protection_registry=case["protection_registry"],
        protection_authority=case["protection_authority"],
        raw=case["raw"],
        current=case["current"],
        pin_binding=case["pin_binding"],
    )


def test_unknown_grade_flag_stays_held_even_with_owner(case):
    key = case["record"]["user_id"] + ":" + case["record"]["assignment_id"]
    case["current"]["cells"][key]["grade_matches_current_submission"] = None
    _rebind_fake_owner(case)
    with pytest.raises(GradebookError, match="PRIMARY_CURRENT_ATTEMPT_CHANGED"):
        prepare_primary_review_transfer(**case)


def test_higher_canvas_grade_preserved(case):
    key = case["record"]["user_id"] + ":" + case["record"]["assignment_id"]
    for snap in (case["baseline"], case["current"]):
        snap["cells"][key]["value"] = 21
        snap["cells"][key]["grade"] = "21"
    _rebind_fake_owner(case)
    with pytest.raises(GradebookError, match="HIGHER_CANVAS_SCORE_PRESERVED"):
        prepare_primary_review_transfer(**case)


def test_fresh_source_authority_failure_holds(case):
    plan = prepare_primary_review_transfer(**case)

    def changed(_):
        raise ValueError("current source changed")

    with pytest.raises(GradebookError, match="PRIMARY_AUTHORITY_REVALIDATION_HELD"):
        revalidate_primary_review_transfer(
            plan,
            expected_plan_sha256=digest(plan),
            authority=changed,
            protection_registry=case["protection_registry"],
            protection_authority=case["protection_authority"],
            raw=case["raw"],
            current=case["current"],
            pin_binding=case["pin_binding"],
        )


def _google_lti(case, url="https://assignments.google.com/lti/a/example"):
    metadata = case["assignment_binding"]["assignment_metadata"]
    metadata.update(
        submission_types=["external_tool"], external_tool_tag_attributes={"url": url}
    )
    case["assignment_binding"]["provider"] = "GOOGLE_ASSIGNMENTS"
    case["assignment_binding"]["assignment_metadata_sha256"] = digest(metadata)
    case["evidence"]["assignment_sha256"] = digest(metadata)
    case["evidence"]["provider_review_sha256"] = "9" * 64
    for snap in (case["baseline"], case["current"]):
        assignment = next(
            a for a in snap["assignments"] if a["id"] == case["record"]["assignment_id"]
        )
        assignment["assignment_metadata"] = copy.deepcopy(metadata)
        assignment["assignment_metadata_sha256"] = digest(metadata)
    _rebind_fake_owner(case)


def test_exact_google_assignment_review_is_only_unapproved_draft(case):
    _google_lti(case)
    plan = prepare_primary_review_transfer(**case)
    assert plan["publication_allowed"] is False
    assert plan["transfer"]["score_delivery_authorized"] is False
    revalidate_primary_review_transfer(
        plan,
        expected_plan_sha256=digest(plan),
        authority=case["authority"],
        protection_registry=case["protection_registry"],
        protection_authority=case["protection_authority"],
        raw=case["raw"],
        current=case["current"],
        pin_binding=case["pin_binding"],
    )


@pytest.mark.parametrize(
    "url",
    [
        "https://assignments.google.com.evil.test/lti/a/x",
        "http://assignments.google.com/lti/a/x",
        "https://edpuzzle.com/lti/a/x",
    ],
)
def test_unapproved_or_edpuzzle_lti_rejected(case, url):
    _google_lti(case, url)
    with pytest.raises(GradebookError):
        prepare_primary_review_transfer(**case)


@pytest.mark.parametrize("change", ["missing_lane", "wrong_lane", "wrong_policy"])
def test_wrong_participation_lane_or_policy_held(case, change):
    if change == "missing_lane":
        del case["proposal"]["delivery_policy"]
    elif change == "wrong_lane":
        case["proposal"]["source_lane"] = "GRASS_SUMMATIVE"
    else:
        case["record"]["policy"] = "3" * 64
    with pytest.raises(GradebookError):
        prepare_primary_review_transfer(**case)


def test_edpuzzle_in_assignment_name_excluded(case):
    metadata = case["assignment_binding"]["assignment_metadata"]
    metadata["name"] = "Edpuzzle activity"
    case["assignment_binding"]["assignment_metadata_sha256"] = digest(metadata)
    with pytest.raises(GradebookError, match="EXCLUDED_PROVIDER"):
        prepare_primary_review_transfer(**case)


@pytest.fixture
def first_submission_case(case):
    from test_gradebook_native import initial_raw

    from canvas_mcp.gradebook.canvas_primary_review import (
        first_submission_review_binding,
    )

    key = case["record"]["user_id"] + ":" + case["record"]["assignment_id"]
    before = case["baseline"]["cells"][key]
    before.update(
        attempt=None,
        workflow_state="unsubmitted",
        submitted_at=None,
        graded_at=None,
        value=None,
        grade=None,
        visible=True,
        excused=False,
        grade_matches_current_submission=True,
        points_deducted=None,
        late=False,
    )
    case["current"]["cells"][key] = copy.deepcopy(before)
    case["current"]["cells"][key].update(
        attempt=1,
        workflow_state="submitted",
        submitted_at="2026-11-12T12:00:00Z",
        late=True,
        points_deducted=0,
    )
    case["record"]["canvas_attempt"] = 1
    case["evidence"]["canvas_attempt"] = 1
    case["evidence"]["record_sha256"] = digest(case["record"])
    case["evidence"]["current_cell_sha256"] = digest(case["current"]["cells"][key])
    case["raw"] = initial_raw(case["baseline"], case["binding"])
    case["evidence"]["first_submission_review"] = first_submission_review_binding(
        evidence=case["evidence"],
        record=case["record"],
        assignment_binding=case["assignment_binding"],
        raw=case["raw"],
        baseline=case["baseline"],
        current=case["current"],
        pin_binding=case["pin_binding"],
    )
    expected = copy.deepcopy(case["evidence"])

    def genuine_source_assertion(actual):
        if actual != expected:
            raise ValueError("changed reviewed source")

    case["authority"] = genuine_source_assertion
    return case


def test_reviewed_first_submission_retains_original_baseline(first_submission_case):
    from canvas_mcp.gradebook.teacher_edit_transfer import _first_submission_projection

    before = copy.deepcopy(first_submission_case["baseline"])
    plan = prepare_primary_review_transfer(**first_submission_case)
    transfer = plan["transfer"]
    projected = _first_submission_projection(
        before, first_submission_case["current"], first_submission_case["record"]
    )
    assert transfer["baseline"] == before == first_submission_case["baseline"]
    assert transfer["first_submission_comparison_sha256"] == digest(projected)
    assert transfer["current_basis"]["cell"]["attempt"] == 1
    assert transfer["requests"][0]["updateCells"]["fields"] == "userEnteredValue"
    revalidate_primary_review_transfer(
        plan,
        expected_plan_sha256=digest(plan),
        authority=first_submission_case["authority"],
        protection_registry=first_submission_case["protection_registry"],
        protection_authority=first_submission_case["protection_authority"],
        raw=first_submission_case["raw"],
        current=first_submission_case["current"],
        pin_binding=first_submission_case["pin_binding"],
    )


@pytest.mark.parametrize(
    "change",
    [
        "no_permit",
        "tampered_permit",
        "new_attempt",
        "deduction",
        "excused",
        "positive_grade",
        "current_match_false",
        "non_first",
        "baseline_changed",
        "native_changed",
    ],
)
def test_first_submission_scope_and_preimage_changes_hold(
    first_submission_case, change
):
    c = first_submission_case
    cell = c["current"]["cells"]["101:21"]
    if change == "no_permit":
        del c["evidence"]["first_submission_review"]
    elif change == "tampered_permit":
        c["evidence"]["first_submission_review"]["baseline_sha256"] = "0" * 64
    elif change == "new_attempt":
        cell["attempt"] = 2
    elif change == "deduction":
        cell["points_deducted"] = 1
    elif change == "excused":
        cell["excused"] = True
    elif change == "positive_grade":
        cell["value"] = 20
    elif change == "current_match_false":
        cell["grade_matches_current_submission"] = False
    elif change == "non_first":
        c["baseline"]["cells"]["101:21"]["attempt"] = 1
    elif change == "baseline_changed":
        c["baseline"]["cells"]["101:21"]["late"] = True
    else:
        c["raw"]["sheets"][0]["properties"]["title"] = "changed"
    if change in {
        "new_attempt",
        "deduction",
        "excused",
        "positive_grade",
        "current_match_false",
        "non_first",
    }:
        # Rebind a genuine hypothetical fresh authority and permit to the changed
        # context: the transition policy itself must reject, not just old hashes.
        from test_gradebook_native import initial_raw

        from canvas_mcp.gradebook.canvas_primary_review import (
            first_submission_review_binding,
        )

        if change == "new_attempt":
            c["record"]["canvas_attempt"] = 2
            c["evidence"]["canvas_attempt"] = 2
            c["evidence"]["record_sha256"] = digest(c["record"])
        c["evidence"]["current_cell_sha256"] = digest(cell)
        c["raw"] = initial_raw(c["baseline"], c["binding"])
        c["evidence"]["first_submission_review"] = first_submission_review_binding(
            evidence=c["evidence"],
            record=c["record"],
            assignment_binding=c["assignment_binding"],
            raw=c["raw"],
            baseline=c["baseline"],
            current=c["current"],
            pin_binding=c["pin_binding"],
        )
        expected = copy.deepcopy(c["evidence"])

        def changed_source_authority(actual):
            if actual != expected:
                raise ValueError("source changed")

        c["authority"] = changed_source_authority
    with pytest.raises(GradebookError):
        prepare_primary_review_transfer(**c)


def test_primary_planner_cannot_bypass_exact_protected_target(case):
    protected = copy.deepcopy(case["protection_registry"])
    protected["protected_students"].append(
        {"user_id": "101", "evidence_sha256": "c" * 64}
    )
    protected["protected_targets"].append(
        {
            "course_id": "12",
            "assignment_id": "21",
            "user_id": "101",
            "evidence_sha256": "d" * 64,
        }
    )
    case["protection_registry"] = protected

    def trusted_policy(registry, target):
        assert registry == protected

    case["protection_authority"] = trusted_policy
    with pytest.raises(GradebookError, match="PROTECTED_TARGET_HELD"):
        prepare_primary_review_transfer(**case)
