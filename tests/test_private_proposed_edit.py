"""Self-contained fictional AUTHOR5 profile → proposed EDIT plan, no clients."""

import copy
import hashlib
import json
import socket
from typing import Any

import pytest
from test_gradebook import snapshot as snapshot
from test_gradebook_native import binding as binding
from test_gradebook_native import initial_raw

from canvas_mcp.gradebook import unit2_private_proposed_edit as edit
from canvas_mcp.gradebook.client import GradebookError
from canvas_mcp.gradebook.model import digest
from canvas_mcp.gradebook.unit2_note_draft import EditOnlyAuthorization

AUTHOR5_SCHEMA = "ORIGINAL_AUTHOR_FIVE_FROZEN_RECORDS_COMPACT_FEEDBACK_HANDOFF_V1"
AUTHOR5_BODY_VERSION = "AUTHOR_FROZEN_AWARD_DERIVED_COMPACT_V1"
AUTHOR5_REF_ROLES = {
    "packet",
    "source_pdf",
    "head",
    "reading",
    "result",
    "academic",
    "policy",
    "issued_key",
    "mastery_rubric",
}


def source_digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode()
    ).hexdigest()


@pytest.fixture(autouse=True)
def no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    def deny(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("REAL_NETWORK_FORBIDDEN")

    monkeypatch.setattr(socket.socket, "connect", deny)
    monkeypatch.setattr(socket.socket, "connect_ex", deny)
    monkeypatch.setattr(socket, "create_connection", deny)


def cell(raw: Any) -> dict[str, Any]:
    return edit._cell(raw, 2, 5, 2)


@pytest.fixture
def scenario(snapshot: Any, binding: Any) -> dict[str, Any]:
    memory: dict[str, bytes] = {}

    def save(name: str, value: Any) -> dict[str, Any]:
        data = (json.dumps(value, ensure_ascii=False) + "\n").encode()
        path = "/fictional-not-real/" + name
        memory[path] = data
        return {
            "path": path,
            "bytes": len(data),
            "sha256": hashlib.sha256(data).hexdigest(),
        }

    atomic = {
        "criterion_id": "FICTIONAL/MASTERY",
        "status": "PROPOSED",
        "maximum_points": "1/2",
        "proposed_earned_points": "0",
        "proposed_deduction": "0.5",
        "scientific_reason": "Fictional α reason",
    }
    rollup = {
        "PRIVATE_proposed_earned_points": "1",
        "possible_points": "3",
        "PRIVATE_proposed_percent": "100/3",
        "remaining_unsupported_academic_components": 0,
        "state": "PROPOSED_UNAPPLIED",
        "policy_grade_operations": [{"op": "to_percent"}],
        "whole_final_numeric": None,
    }
    proposal = {"criteria": [atomic], "private_academic_rollup": copy.deepcopy(rollup)}
    refs = {role: save(role, {"fictional": role}) for role in AUTHOR5_REF_ROLES}
    request = {
        "binding": {
            "section": "A2",
            "pin": "0042",
            "form_id": "FICTIONAL",
            "attempt": "R1",
            "refs": refs,
        },
        "original_frozen_proposal_ref": save("proposal", proposal),
        "original_frozen_rollup_ref": save("rollup", rollup),
        "original_frozen_records_must_be_read_unchanged": True,
        "all_original_scientific_reasons_evidence_and_holds_preserved_in_original_records": True,
        "complete_private_proposed_score": {
            "earned_points_exact": "1",
            "possible_points_exact": "3",
            "percent_exact": "100/3",
            "academic_supported_complete": True,
            "status": "PROPOSED",
        },
        "compact_feedback": {
            "version": AUTHOR5_BODY_VERSION,
            "text": "  Fictional α proposal.\r\n",
            "basis": "FROZEN_FICTIONAL",
            "format_adoption": "NOT_CANONICAL",
        },
        "preserved_constraints": {
            "native_status": "HELD",
            "native_holds": [{"id": "ORIGINAL_HOLD"}],
            "maintained_native_score_adoption": False,
            "native_NULLs_unchanged": True,
            "no_source_or_teacher_flag_clearance": True,
            "only_proposed_Sheet_local_EDIT_staging_in_scope": True,
            "Canvas_writes": False,
        },
    }
    fmt = {
        "actual_authored_source_version": AUTHOR5_BODY_VERSION,
        "is_canonical_formatter_output": False,
        "is_body_QC_passed": False,
        "is_maintained_V6_publisher_ready": False,
        "V7_runtime_adoption_claimed": False,
        "maintained_contract_ref": save("contract", {"fictional": True}),
    }
    handoff = {
        "schema": AUTHOR5_SCHEMA,
        "case_count": 1,
        "cases": [copy.deepcopy(request)],
        "feedback_format_status": fmt,
    }
    handoff_ref = save("handoff", handoff)
    calls: list[str] = []

    def owner(
        binding: Any, constraints: Any, proposed: Any, rolled: Any
    ) -> dict[str, Any]:
        calls.append("owner")
        return {
            "source_identity_form_policy_current_coverage_verified": True,
            "binding_sha256": source_digest(binding),
            "native_context": {
                "grade_preview": None,
                "status": "HELD",
                "holds": copy.deepcopy(constraints["native_holds"]),
            },
        }

    def source_check(current: Any) -> dict[str, Any]:
        calls.append("source")
        assert current == request
        qualified = owner(
            request["binding"], request["preserved_constraints"], proposal, rollup
        )

        def short(ref: dict[str, Any]) -> dict[str, Any]:
            return {k: ref[k] for k in ("path", "sha256")}

        body = request["compact_feedback"]["text"]
        checked = {
            "case": copy.deepcopy(request),
            "feedback_format_status": copy.deepcopy(fmt),
            "atomic_count_checked": 1,
            "atomic_subset_not_whole_total": True,
            "earned_exact": "1",
            "possible_exact": "3",
            "percent_exact": "100/3",
            "body_sha256": hashlib.sha256(body.encode()).hexdigest(),
        }
        return {
            "contract": "QUALIFIED_PRIVATE_WHOLE_PROJECTION_SOURCE_V1",
            "source_role": "PRIVATE_PROPOSED_WHOLE_TEST",
            "body_source_role": "PRIVATE_PROPOSED_WHOLE_TEST",
            "scope": "WHOLE_TEST",
            "source_request_sha256": source_digest(request),
            "author_contract": AUTHOR5_SCHEMA,
            "proposal_ref": short(request["original_frozen_proposal_ref"]),
            "native_snapshot_ref": short(refs["result"]),
            "calculation_proof_ref": short(request["original_frozen_rollup_ref"]),
            "body_proof_ref": short(handoff_ref),
            "qualification": "SOURCE_IDENTITY_FORM_POLICY_CURRENT_CALCULATION_VALID",
            "score_text": "100/3",
            "score_units": "percent",
            "feedback": body,
            "native_context": qualified["native_context"],
            "identity_binding_sha256": source_digest(request["binding"]),
            "review_state": {"status": "NOT_REVIEWED", "ref": None},
            "actual_authored_body_version": AUTHOR5_BODY_VERSION,
            "original_case_unchanged": copy.deepcopy(request),
            "original_feedback_format_status": copy.deepcopy(fmt),
            "source_math_validation": checked,
            "teacher_accepted": False,
            "live_write_allowed": False,
            "publication_allowed": False,
        }

    stage_ref = save(
        "fictional-staged-four-fields",
        {
            "score": "100/3",
            "body": request["compact_feedback"]["text"],
            "status": "PROPOSED_UNREVIEWED",
        },
    )

    def stage_check(qualified: Any, ref: Any) -> None:
        calls.append("stage")
        assert (
            ref == stage_ref
            and qualified["feedback"] == request["compact_feedback"]["text"]
        )
        assert qualified["score_text"] == "100/3"

    def target_check(
        raw: Any, bound: Any, target: Any, observation: Any, identity: str
    ) -> None:
        calls.append("target")
        assert (
            raw["spreadsheetId"] == bound["spreadsheet_id"]
            and target["user_id"] == "101"
        )
        assert observation["target"] == target and identity == source_digest(
            request["binding"]
        )
        # Fictional owner admission only. Real implementation must authenticate
        # all registered protections/axes and exact-text field compatibility.

    raw = initial_raw(snapshot, binding)
    old = cell(raw)
    old.pop("userEnteredValue", None)
    old["note"] = "Teacher manual prefix\r\n"
    old["chipRuns"] = [{"startIndex": 0, "chip": {"fictional": "preserve"}}]
    raw["developerMetadata"] = [
        {"metadataId": 55, "metadataKey": "fictional", "metadataValue": "keep"}
    ]
    target = {
        "origin": snapshot["origin"],
        "course_id": "12",
        "assignment_id": "21",
        "user_id": "101",
        "attempt": None,
        "submitted_at": None,
        "submission_types": ["on_paper"],
    }
    return {
        "source_request": request,
        "raw": raw,
        "binding": binding,
        "target": target,
        "expected_identity_binding_sha256": source_digest(request["binding"]),
        "canvas_observation": {
            "target": copy.deepcopy(target),
            "grade_observation": "UNGRADED",
            "score": None,
            "grade": None,
            "excused": False,
            "visible": True,
            "closed_period": None,
            "assignment_points_possible": 100,
            "observation_sha256": "a" * 64,
        },
        "unit_sheet_readback_ref": stage_ref,
        "authorization": EditOnlyAuthorization(
            snapshot["origin"], "12", "21", "FICTIONAL_EDIT_ONLY"
        ),
        "prior_outcome": "KNOWN_NOT_SENT",
        "source_check": source_check,
        "staged_source_check": stage_check,
        "target_check": target_check,
        "_calls": calls,
        "_profile_inputs": {
            "memory": memory,
            "handoff_ref": handoff_ref,
            "owner": owner,
        },
    }


def args(scenario: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in scenario.items() if not k.startswith("_")}


def test_real_r2_profile_plans_exact_rational_with_native_null_and_review_pending(
    scenario: Any,
) -> None:
    before = copy.deepcopy(scenario["raw"])
    plan = edit.prepare_private_edit(**args(scenario))
    assert scenario["raw"] == before
    assert scenario["_calls"] == ["source", "owner", "stage", "target"]
    assert plan["source"]["score_text"] == "100/3"
    assert cell(plan["after_raw"])["userEnteredValue"] == {"stringValue": "100/3"}
    assert plan["source"]["native_context"]["grade_preview"] is None
    assert plan["source"]["native_context"]["holds"] == [{"id": "ORIGINAL_HOLD"}]
    assert plan["source"]["review_state"]["status"] == "NOT_REVIEWED"
    assert plan["source"]["actual_authored_body_version"] == AUTHOR5_BODY_VERSION
    assert (
        plan["source"]["original_feedback_format_status"]["is_body_QC_passed"] is False
    )
    assert plan["canvas_requests"] == [] and all(plan[k] is False for k in edit.FLAGS)


def test_one_cell_fieldmask_and_all_other_raw_celldata_metadata_exact(
    scenario: Any,
) -> None:
    plan = edit.prepare_private_edit(**args(scenario))
    q = plan["requests"]
    assert len(q) == 1 and q[0]["updateCells"]["fields"] == "userEnteredValue,note"
    assert q[0]["updateCells"]["start"] == {
        "sheetId": 2,
        "rowIndex": 5,
        "columnIndex": 2,
    }
    restored = copy.deepcopy(plan["after_raw"])
    c = cell(restored)
    c.pop("userEnteredValue")
    c["note"] = cell(plan["before_raw"])["note"]
    assert restored == plan["before_raw"]
    assert cell(plan["after_raw"])["note"].startswith(
        cell(plan["before_raw"])["note"] + "\n\n"
    )
    assert cell(plan["after_raw"])["chipRuns"] == cell(plan["before_raw"])["chipRuns"]


def test_unicode_hash_is_original_author_not_ascii_json(scenario: Any) -> None:
    source = scenario["source_check"](scenario["source_request"])
    assert source["source_request_sha256"] == edit._source_digest(
        scenario["source_request"]
    )
    assert source["source_request_sha256"] != digest(scenario["source_request"])
    edit.prepare_private_edit(**args(scenario))


@pytest.mark.parametrize(
    "callback,error",
    [
        ("source_check", "OWNER_SOURCE"),
        ("staged_source_check", "SHEET_READBACK"),
        ("target_check", "TARGET_GUARD"),
    ],
)
def test_missing_actual_owner_integrations_hold(
    scenario: Any, callback: str, error: str
) -> None:
    scenario[callback] = None
    with pytest.raises(GradebookError, match=error):
        edit.prepare_private_edit(**args(scenario))


@pytest.mark.parametrize("outcome", ["UNKNOWN", "SENDING", "UNCERTAIN", "SENT", None])
def test_prior_unknown_or_sent_never_replayed(scenario: Any, outcome: Any) -> None:
    scenario["prior_outcome"] = outcome
    with pytest.raises(GradebookError, match="RECONCILE_PRIOR"):
        edit.prepare_private_edit(**args(scenario))
    assert scenario["_calls"] == []


@pytest.mark.parametrize(
    "value",
    [
        {"numberValue": 0},
        {"numberValue": 99},
        {"formulaValue": "=KEEP"},
        {"stringValue": ""},
    ],
)
def test_any_preexisting_score_or_formula_is_protected(
    scenario: Any, value: Any
) -> None:
    cell(scenario["raw"])["userEnteredValue"] = value
    with pytest.raises(GradebookError, match="BLANK_DESTINATION"):
        edit.prepare_private_edit(**args(scenario))


@pytest.mark.parametrize(
    "changes",
    [
        {"score": 99},
        {"grade": "99"},
        {"excused": True},
        {"visible": False},
        {"closed_period": True},
        {"assignment_points_possible": 50},
    ],
)
def test_current_canvas_target_guards_unchanged(scenario: Any, changes: Any) -> None:
    scenario["canvas_observation"].update(changes)
    with pytest.raises(GradebookError, match="CURRENT_UNGRADED_100PT"):
        edit.prepare_private_edit(**args(scenario))


@pytest.mark.parametrize(
    "key,value,error",
    [
        ("source_role", "NATIVE", "SOURCE_ROLE"),
        ("scope", "MC_COMPONENT", "SOURCE_ROLE"),
        ("actual_authored_body_version", "UNIT2_COMPACT_FEEDBACK_V7", "AUTHOR_BODY"),
        ("teacher_accepted", True, "GRANT_AUTHORITY"),
        ("identity_binding_sha256", "f" * 64, "IDENTITY"),
    ],
)
def test_role_profile_and_identity_cannot_be_relabelled(
    scenario: Any, key: str, value: Any, error: str
) -> None:
    original = scenario["source_check"]

    def changed(request: Any) -> Any:
        result = original(request)
        result[key] = value
        return result

    scenario["source_check"] = changed
    with pytest.raises(GradebookError, match=error):
        edit.prepare_private_edit(**args(scenario))


def test_revalidation_repeats_all_current_callbacks(scenario: Any) -> None:
    plan = edit.prepare_private_edit(**args(scenario))
    before = len(scenario["_calls"])
    edit.revalidate_private_edit(
        plan,
        raw=scenario["raw"],
        canvas_observation=scenario["canvas_observation"],
        expected_plan_sha256=digest(plan),
        source_check=scenario["source_check"],
        staged_source_check=scenario["staged_source_check"],
        target_check=scenario["target_check"],
        prior_outcome="KNOWN_NOT_SENT",
    )
    assert len(scenario["_calls"]) == before + 4


def test_revalidation_unknown_and_changed_source_fail_closed(scenario: Any) -> None:
    plan = edit.prepare_private_edit(**args(scenario))
    options = {
        k: scenario[k] for k in ["source_check", "staged_source_check", "target_check"]
    }
    with pytest.raises(GradebookError, match="RECONCILE_PRIOR"):
        edit.revalidate_private_edit(
            plan,
            raw=scenario["raw"],
            canvas_observation=scenario["canvas_observation"],
            expected_plan_sha256=digest(plan),
            prior_outcome="UNKNOWN",
            **options,
        )

    def deny(request: Any) -> Any:
        raise ValueError("Fictional stale owner")

    options["source_check"] = deny
    with pytest.raises(GradebookError, match="OWNER_SOURCE"):
        edit.revalidate_private_edit(
            plan,
            raw=scenario["raw"],
            canvas_observation=scenario["canvas_observation"],
            expected_plan_sha256=digest(plan),
            prior_outcome="KNOWN_NOT_SENT",
            **options,
        )


def test_full_preimage_and_readback_include_chips_manual_metadata(
    scenario: Any,
) -> None:
    plan = edit.prepare_private_edit(**args(scenario))
    options = {
        k: scenario[k] for k in ["source_check", "staged_source_check", "target_check"]
    }
    changed = copy.deepcopy(scenario["raw"])
    cell(changed)["chipRuns"] = []
    with pytest.raises(GradebookError, match="STALE_FULL_PREIMAGE"):
        edit.revalidate_private_edit(
            plan,
            raw=changed,
            canvas_observation=scenario["canvas_observation"],
            expected_plan_sha256=digest(plan),
            prior_outcome="KNOWN_NOT_SENT",
            **options,
        )
    assert (
        edit.classify_private_edit_readback(
            plan, plan["after_raw"], expected_plan_sha256=digest(plan)
        )["status"]
        == "PLANNED_OUTPUT_OBSERVED"
    )
    assert (
        edit.classify_private_edit_readback(
            plan, plan["before_raw"], expected_plan_sha256=digest(plan)
        )["status"]
        == "BEFORE_STILL_PRESENT"
    )
    after = copy.deepcopy(plan["after_raw"])
    cell(after)["chipRuns"] = []
    observed = edit.classify_private_edit_readback(
        plan, after, expected_plan_sha256=digest(plan)
    )
    assert observed["status"] == "DIVERGED" and observed["retry_writes"] is False


def test_identical_current_draft_is_noop_not_second_append(scenario: Any) -> None:
    plan = edit.prepare_private_edit(**args(scenario))
    scenario["raw"] = plan["after_raw"]
    again = edit.prepare_private_edit(**args(scenario))
    assert again["status"] == "NO_CHANGE" and again["requests"] == []


def test_conflicting_private_draft_is_not_overwritten(scenario: Any) -> None:
    plan = edit.prepare_private_edit(**args(scenario))
    scenario["raw"] = copy.deepcopy(plan["after_raw"])
    cell(scenario["raw"])["note"] += "\nTeacher later manual suffix"
    with pytest.raises(GradebookError, match="CONFLICTING_DRAFT"):
        edit.prepare_private_edit(**args(scenario))


def test_revalidation_uses_new_canvas_observation(scenario: Any) -> None:
    plan = edit.prepare_private_edit(**args(scenario))
    current = copy.deepcopy(scenario["canvas_observation"])
    current.update(score=90, grade="90")
    with pytest.raises(GradebookError, match="CURRENT_UNGRADED_100PT"):
        edit.revalidate_private_edit(
            plan,
            raw=scenario["raw"],
            canvas_observation=current,
            expected_plan_sha256=digest(plan),
            prior_outcome="KNOWN_NOT_SENT",
            source_check=scenario["source_check"],
            staged_source_check=scenario["staged_source_check"],
            target_check=scenario["target_check"],
        )


@pytest.mark.parametrize(
    "callback,error",
    [("staged_source_check", "SHEET_READBACK"), ("target_check", "TARGET_GUARD")],
)
def test_current_owner_refusal_cannot_be_replaced_by_a_flag(
    scenario: Any, callback: str, error: str
) -> None:
    scenario[callback] = lambda *args: True
    with pytest.raises(GradebookError, match=error):
        edit.prepare_private_edit(**args(scenario))


def test_async_source_callback_is_not_silently_accepted(scenario: Any) -> None:
    async def invalid(request: Any) -> dict[str, Any]:
        return scenario["source_check"](request)

    scenario["source_check"] = invalid
    with pytest.raises(GradebookError, match="OWNER_SOURCE"):
        edit.prepare_private_edit(**args(scenario))


def test_optional_unknown_review_and_canonical_value_are_preserved(
    scenario: Any,
) -> None:
    original = scenario["source_check"]

    def current(request: Any) -> Any:
        out = original(request)
        out["review_state"] = {"status": "UNKNOWN", "ref": None}
        out["native_context"]["grade_preview"] = "81"
        return out

    scenario["source_check"] = current
    plan = edit.prepare_private_edit(**args(scenario))
    assert plan["source"]["review_state"] == {"status": "UNKNOWN", "ref": None}
    assert plan["source"]["native_context"]["grade_preview"] == "81"
    assert cell(plan["after_raw"])["userEnteredValue"] == {"stringValue": "100/3"}


def test_callback_copies_cannot_mutate_the_retained_plan(scenario: Any) -> None:
    original = scenario["staged_source_check"]

    def changing(source: Any, ref: Any) -> None:
        original(source, ref)
        source["native_context"]["holds"].clear()
        source["feedback"] = "not the proposal"
        ref["sha256"] = "f" * 64

    scenario["staged_source_check"] = changing
    plan = edit.prepare_private_edit(**args(scenario))
    assert plan["source"]["native_context"]["holds"] == [{"id": "ORIGINAL_HOLD"}]
    assert "α" in plan["source"]["feedback"]
    assert plan["unit_sheet_readback_ref"] == scenario["unit_sheet_readback_ref"]


def test_type_changed_original_case_cannot_pass_python_bool_int_equality(
    scenario: Any,
) -> None:
    original = scenario["source_check"]

    def changing(request: Any) -> Any:
        out = original(request)
        out["original_case_unchanged"]["complete_private_proposed_score"][
            "academic_supported_complete"
        ] = 1
        return out

    scenario["source_check"] = changing
    with pytest.raises(GradebookError, match="ORIGINAL_CASE_BINDING_CHANGED"):
        edit.prepare_private_edit(**args(scenario))


def test_tampered_request_plan_fails_even_with_a_recomputed_digest(
    scenario: Any,
) -> None:
    plan = edit.prepare_private_edit(**args(scenario))
    plan["requests"][0]["updateCells"]["start"]["columnIndex"] += 1
    with pytest.raises(GradebookError, match="PLAN_CHANGED"):
        edit.revalidate_private_edit(
            plan,
            raw=scenario["raw"],
            canvas_observation=scenario["canvas_observation"],
            expected_plan_sha256=digest(plan),
            prior_outcome="KNOWN_NOT_SENT",
            source_check=scenario["source_check"],
            staged_source_check=scenario["staged_source_check"],
            target_check=scenario["target_check"],
        )


def test_existing_text_incompatible_target_can_hold_without_validation_change(
    scenario: Any,
) -> None:
    def numeric_only(*args: Any) -> None:
        raise ValueError(
            "Fictional existing field cannot represent exact rational text"
        )

    scenario["target_check"] = numeric_only
    before = copy.deepcopy(scenario["raw"])
    with pytest.raises(GradebookError, match="TARGET_GUARD"):
        edit.prepare_private_edit(**args(scenario))
    assert scenario["raw"] == before


@pytest.mark.parametrize(
    "fields",
    [
        {"effectiveValue": {"stringValue": "100/3"}},
        {"formattedValue": "100/3"},
        {"effectiveValue": {"stringValue": "100/3"}, "formattedValue": "100/3"},
    ],
)
def test_matching_target_derived_fields_are_verified_without_mutation(
    scenario: Any, fields: Any
) -> None:
    plan = edit.prepare_private_edit(**args(scenario))
    actual = copy.deepcopy(plan["after_raw"])
    cell(actual).update(fields)
    before = copy.deepcopy((plan, actual))
    result = edit.classify_private_edit_readback(
        plan, actual, expected_plan_sha256=digest(plan)
    )
    assert (
        result["status"] == "PLANNED_OUTPUT_OBSERVED"
        and result["retry_writes"] is False
    )
    assert set(result["verified_target_derived_fields"]) == set(fields)
    assert result["actual_fingerprint"] == digest(actual)
    assert result["comparison_fingerprint"] == plan["after_fingerprint"]
    assert (plan, actual) == before


@pytest.mark.parametrize(
    "fields",
    [
        {"effectiveValue": {"stringValue": "WRONG"}},
        {"effectiveValue": {"numberValue": 100 / 3}},
        {"effectiveValue": {"stringValue": "100/3", "numberValue": 0}},
        {"formattedValue": "33.3333"},
        {"formattedValue": 100 / 3},
        {"effectiveValue": None},
    ],
)
def test_wrong_or_coerced_target_derived_values_remain_diverged(
    scenario: Any, fields: Any
) -> None:
    plan = edit.prepare_private_edit(**args(scenario))
    actual = copy.deepcopy(plan["after_raw"])
    cell(actual).update(fields)
    result = edit.classify_private_edit_readback(
        plan, actual, expected_plan_sha256=digest(plan)
    )
    assert result["status"] == "DIVERGED" and result["retry_writes"] is False


@pytest.mark.parametrize(
    "where",
    [
        "chip",
        "unknown_target_field",
        "workbook_metadata",
        "protection",
        "unrelated_cell",
    ],
)
def test_matching_derived_fields_never_hide_other_changes(
    scenario: Any, where: str
) -> None:
    plan = edit.prepare_private_edit(**args(scenario))
    actual = copy.deepcopy(plan["after_raw"])
    cell(actual).update(effectiveValue={"stringValue": "100/3"}, formattedValue="100/3")
    if where == "chip":
        cell(actual)["chipRuns"] = []
    elif where == "unknown_target_field":
        cell(actual)["effectiveFormat"] = {"numberFormat": {"type": "TEXT"}}
    elif where == "workbook_metadata":
        actual["developerMetadata"][0]["metadataValue"] = "changed"
    elif where == "protection":
        actual["sheets"][0]["protectedRanges"] = [{"fictional": "changed"}]
    else:
        actual["sheets"][0]["data"][0]["rowData"][0]["values"][0]["formattedValue"] = (
            "new unrelated display"
        )
    result = edit.classify_private_edit_readback(
        plan, actual, expected_plan_sha256=digest(plan)
    )
    assert result["status"] == "DIVERGED" and result["retry_writes"] is False


def test_stale_preimage_derived_fields_are_preserved_and_only_new_literal_verified(
    scenario: Any,
) -> None:
    cell(scenario["raw"]).update(
        effectiveValue={"stringValue": "OLD"}, formattedValue="OLD"
    )
    plan = edit.prepare_private_edit(**args(scenario))
    assert cell(plan["before_raw"])["formattedValue"] == "OLD"
    actual = copy.deepcopy(plan["after_raw"])
    cell(actual).update(effectiveValue={"stringValue": "100/3"}, formattedValue="100/3")
    assert (
        edit.classify_private_edit_readback(
            plan, actual, expected_plan_sha256=digest(plan)
        )["status"]
        == "PLANNED_OUTPUT_OBSERVED"
    )
    assert cell(plan["after_raw"])["formattedValue"] == "OLD"
    # The unchanged before response still means before, never a resend grant.
    result = edit.classify_private_edit_readback(
        plan, plan["before_raw"], expected_plan_sha256=digest(plan)
    )
    assert (
        result["status"] == "BEFORE_STILL_PRESENT" and result["retry_writes"] is False
    )


def test_missing_previously_captured_display_field_is_not_silently_dropped(
    scenario: Any,
) -> None:
    cell(scenario["raw"]).update(
        effectiveValue={"stringValue": "OLD"}, formattedValue="OLD"
    )
    plan = edit.prepare_private_edit(**args(scenario))
    actual = copy.deepcopy(plan["after_raw"])
    cell(actual).pop("formattedValue")
    cell(actual)["effectiveValue"] = {"stringValue": "100/3"}
    assert (
        edit.classify_private_edit_readback(
            plan, actual, expected_plan_sha256=digest(plan)
        )["status"]
        == "DIVERGED"
    )
