"""Pure AUTHOR5 private-proposal EDIT planning, never native grading or delivery.

Trusted owner callbacks must authenticate the actual source, designated UnitSheet
proposal readback and mapped mirror protection/identity. No such implementation,
client, transport registration or authority is supplied here. Canonical native
NULLs/holds stay separate. A prepared request is not permission to execute it.
"""

from __future__ import annotations

import copy
import hashlib
import inspect
import json
import re
from collections.abc import Callable
from dataclasses import asdict
from fractions import Fraction
from typing import Any, cast
from urllib.parse import urlsplit

from . import native
from .client import GradebookError
from .model import digest
from .teacher_edit_transfer import _location
from .unit2_native_whole_source import (
    AUTHOR as NATIVE_AUTHOR,
)
from .unit2_native_whole_source import (
    BODY as NATIVE_BODY,
)
from .unit2_native_whole_source import (
    validate_native_profile,
)
from .unit2_note_draft import EditOnlyAuthorization, _id
from .unit2_reviewed_whole_source import (
    AUTHOR as REVIEWED_AUTHOR,
)
from .unit2_reviewed_whole_source import (
    BODY as REVIEWED_BODY,
)
from .unit2_reviewed_whole_source import (
    validate_reviewed_profile,
)

CONTRACT = "UNIT2_PRIVATE_PROPOSED_EDIT_PLAN_V1"
PROFILE = "QUALIFIED_PRIVATE_WHOLE_PROJECTION_SOURCE_V1"
AUTHOR = "ORIGINAL_AUTHOR_FIVE_FROZEN_RECORDS_COMPACT_FEEDBACK_HANDOFF_V1"
BODY_VERSION = "AUTHOR_FROZEN_AWARD_DERIVED_COMPACT_V1"
ROLE = "PRIVATE_PROPOSED_WHOLE_TEST"
START = "[[UNIT2 PRIVATE PROPOSED EDIT "
END = "[[END UNIT2 PRIVATE PROPOSED EDIT]]"
HASH = re.compile(r"[a-f0-9]{64}")
FLAGS = (
    "teacher_accepted",
    "is_final",
    "publication_allowed",
    "native_adoption_allowed",
    "live_write_allowed",
    "score_delivery_authorized",
    "comment_delivery_authorized",
)
SourceCheck = Callable[[dict[str, Any]], dict[str, Any]]
StageCheck = Callable[[dict[str, Any], dict[str, Any]], object]
TargetCheck = Callable[
    [dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any], str], object
]


def _need(value: object, code: str) -> None:
    if not value:
        raise GradebookError(code)


def _source_digest(value: Any) -> str:
    # The accepted AUTHOR5/R2 profile explicitly uses UTF-8, not model.digest's
    # ASCII JSON representation. Do not strip or change Unicode observations.
    return hashlib.sha256(
        json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode()
    ).hexdigest()


def _reference(ref: Any) -> None:
    _need(
        type(ref) is dict
        and {"path", "sha256"} <= set(ref) <= {"path", "sha256", "bytes"}
        and type(ref["path"]) is str
        and ref["path"].startswith("/")
        and ".." not in ref["path"].split("/")
        and type(ref["sha256"]) is str
        and HASH.fullmatch(ref["sha256"])
        and ("bytes" not in ref or type(ref["bytes"]) is int and ref["bytes"] >= 0),
        "PRIVATE_EDIT_EXACT_REFERENCE_REQUIRED",
    )


def _call(check: Callable[..., object] | None, code: str, *args: Any) -> Any:
    _need(callable(check), code)
    assert check is not None
    try:
        result = check(*(copy.deepcopy(x) for x in args))
        if inspect.isawaitable(result):
            if inspect.iscoroutine(result):
                result.close()
            raise GradebookError(code)
        return copy.deepcopy(result)
    except Exception:
        raise GradebookError(code) from None


def _qualified(
    request: dict[str, Any], source_check: SourceCheck | None
) -> dict[str, Any]:
    source = _call(source_check, "PRIVATE_EDIT_OWNER_SOURCE_CHECK_REQUIRED", request)
    reviewed = type(source) is dict and source.get("author_contract") == REVIEWED_AUTHOR
    native = type(source) is dict and source.get("author_contract") == NATIVE_AUTHOR
    if reviewed:
        validate_reviewed_profile(request, source)
    if native:
        validate_native_profile(request, source)
    expected_body_version = (
        NATIVE_BODY if native else REVIEWED_BODY if reviewed else BODY_VERSION
    )
    _need(
        type(source) is dict
        and source.get("contract") == PROFILE
        and source.get("author_contract") in {AUTHOR, REVIEWED_AUTHOR, NATIVE_AUTHOR}
        and source.get("source_role") == source.get("body_source_role") == ROLE
        and source.get("scope") == "WHOLE_TEST"
        and source.get("qualification")
        == "SOURCE_IDENTITY_FORM_POLICY_CURRENT_CALCULATION_VALID",
        "PRIVATE_EDIT_SOURCE_ROLE_REQUIRED",
    )
    _need(
        source.get("source_request_sha256") == _source_digest(request)
        and _source_digest(source.get("original_case_unchanged"))
        == _source_digest(request),
        "PRIVATE_EDIT_ORIGINAL_CASE_BINDING_CHANGED",
    )
    _need(
        source.get("actual_authored_body_version") == expected_body_version,
        "PRIVATE_EDIT_AUTHOR_BODY_VERSION_REQUIRED",
    )
    fmt = source.get("original_feedback_format_status")
    _need(
        type(fmt) is dict
        and fmt.get("actual_authored_source_version") == expected_body_version
        and fmt.get("is_canonical_formatter_output") is native
        and all(
            fmt.get(k) is False
            for k in (
                "is_maintained_V6_publisher_ready",
                "V7_runtime_adoption_claimed",
            )
        )
        and type(fmt.get("is_body_QC_passed")) is bool,
        "PRIVATE_EDIT_TRUTHFUL_FORMAT_PROVENANCE_REQUIRED",
    )
    _need(
        all(
            source.get(k) is False
            for k in ("teacher_accepted", "live_write_allowed", "publication_allowed")
        ),
        "PRIVATE_EDIT_SOURCE_CANNOT_GRANT_AUTHORITY",
    )
    for key in (
        "proposal_ref",
        "native_snapshot_ref",
        "calculation_proof_ref",
        "body_proof_ref",
    ):
        _reference(source.get(key))
    score = source.get("score_text")
    _need(
        type(score) is str
        and re.fullmatch(
            r"(?:0|[1-9][0-9]*)(?:\.[0-9]+)?|(?:0|[1-9][0-9]*)/[1-9][0-9]*", score
        )
        and len(score) <= 160
        and source.get("score_units") == "percent",
        "PRIVATE_EDIT_EXACT_PERCENT_REQUIRED",
    )
    exact = Fraction(score)
    _need(
        0 <= exact <= 100 and ("/" not in score or str(exact) == score),
        "PRIVATE_EDIT_REDUCED_PERCENT_REQUIRED",
    )
    body = source.get("feedback")
    _need(
        type(body) is str
        and bool(body.strip())
        and START not in body
        and END not in body,
        "PRIVATE_EDIT_EXACT_WHOLE_BODY_REQUIRED",
    )
    try:
        body_hash = hashlib.sha256(body.encode("utf-8")).hexdigest()
    except UnicodeError:
        raise GradebookError("PRIVATE_EDIT_EXACT_WHOLE_BODY_REQUIRED") from None
    math = source.get("source_math_validation")
    _need(
        type(math) is dict
        and math.get("body_sha256") == body_hash
        and _source_digest(math.get("case")) == _source_digest(request)
        and (reviewed or native or math.get("atomic_subset_not_whole_total") is True)
        and math.get("percent_exact") == score,
        "PRIVATE_EDIT_AUTHORED_MATH_BODY_BINDING_REQUIRED",
    )
    ctx = source.get("native_context")
    _need(
        type(ctx) is dict
        and "grade_preview" in ctx
        and type(ctx.get("holds")) is list
        and "status" in ctx,
        "PRIVATE_EDIT_NATIVE_CONTEXT_REQUIRED",
    )
    review = source.get("review_state")
    _need(
        type(review) is dict
        and set(review) == {"status", "ref"}
        and review["status"] in {"NOT_REVIEWED", "UNKNOWN", "REVIEW_RECORDED"},
        "PRIVATE_EDIT_REVIEW_STATE_REQUIRED",
    )
    if review["status"] == "REVIEW_RECORDED":
        _reference(review["ref"])
    else:
        _need(review["ref"] is None, "PRIVATE_EDIT_REVIEW_STATE_REQUIRED")
    return cast(dict[str, Any], source)


def _cell(raw: dict[str, Any], sid: int, row: int, col: int) -> dict[str, Any]:
    sheet = next(s for s in raw["sheets"] if s["properties"]["sheetId"] == sid)
    blocks = []
    for block in sheet.get("data", []):
        r0, c0 = block.get("startRow", 0), block.get("startColumn", 0)
        if r0 <= row < r0 + len(block.get("rowData", [])) and c0 <= col:
            values = block["rowData"][row - r0].get("values", [])
            if col - c0 < len(values):
                return cast(dict[str, Any], values[col - c0])
            blocks.append(block)
    # A blank trailing cell may be omitted by Sheets. Extend only the existing
    # captured row inside the authenticated mapped grid, never a tab or grid.
    _need(bool(blocks), "PRIVATE_EDIT_TARGET_ROW_NOT_CAPTURED")
    block = max(blocks, key=lambda b: b.get("startColumn", 0))
    values = block["rowData"][row - block.get("startRow", 0)].setdefault("values", [])
    values.extend(
        {} for _ in range(col - block.get("startColumn", 0) + 1 - len(values))
    )
    return cast(dict[str, Any], values[col - block.get("startColumn", 0)])


def _encoded_score(score: str, representation: str) -> dict[str, Any]:
    """Encode an already-qualified percent; never derive or round a score."""
    if representation == "EXACT_PERCENT_TEXT_NO_DERIVATION":
        return {"stringValue": score}
    _need(
        representation == "EXACT_BINARY64_PERCENT_NO_DERIVATION",
        "PRIVATE_EDIT_SCORE_REPRESENTATION_REQUIRED",
    )
    exact = Fraction(score)
    number = float(exact)
    _need(
        Fraction.from_float(number) == exact,
        "PRIVATE_EDIT_EXACT_NUMBER_UNREPRESENTABLE_POLICY_REQUIRED",
    )
    return {"numberValue": int(number) if number.is_integer() else number}


FINAL_NEAREST = "OWNER_AUTHENTICATED_FINAL_NEAREST_PERCENT"


def _final_rounding_value(
    source: dict[str, Any], target: dict[str, Any], proof: dict[str, Any]
) -> int:
    """Same exact non-tie arithmetic as the native route, without relabelling it.

    Shape/binding is not authority: prepare/revalidate separately invoke the
    original owner's assertion for the actual source and applicable directive.
    """
    _need(
        type(proof) is dict
        and set(proof)
        == {
            "contract",
            "mode",
            "boundary",
            "tie_breaker",
            "floor_status",
            "source_request_sha256",
            "source_profile_sha256",
            "target",
            "authority_ref",
        }
        and proof["contract"] == "UNIT2_PRIVATE_FINAL_ROUNDING_V1"
        and proof["mode"] == "NEAREST_WHOLE_PERCENT"
        and proof["boundary"] == "COMPLETE_ELIGIBLE_PRIVATE_WHOLE"
        and proof["tie_breaker"] == "UNSPECIFIED"
        and proof["floor_status"] in {"NONE_APPLICABLE", "ALREADY_APPLIED_IN_SOURCE"}
        and proof["source_request_sha256"] == source["source_request_sha256"]
        and proof["source_profile_sha256"] == _source_digest(source)
        and proof["target"] == target,
        "PRIVATE_FINAL_ROUNDING_BINDING_REQUIRED",
    )
    _reference(proof["authority_ref"])
    exact = Fraction(source["score_text"])
    whole, remainder = divmod(exact.numerator, exact.denominator)
    _need(2 * remainder != exact.denominator, "PRIVATE_FINAL_ROUNDING_TIE_HELD")
    return whole + (1 if 2 * remainder > exact.denominator else 0)


def prepare_private_edit(
    source_request: dict[str, Any],
    *,
    raw: dict[str, Any],
    binding: dict[str, Any],
    target: dict[str, Any],
    expected_identity_binding_sha256: str,
    canvas_observation: dict[str, Any],
    unit_sheet_readback_ref: dict[str, Any],
    authorization: EditOnlyAuthorization,
    prior_outcome: str,
    source_check: SourceCheck | None,
    staged_source_check: StageCheck | None,
    target_check: TargetCheck | None,
    score_representation: str = "EXACT_PERCENT_TEXT_NO_DERIVATION",
    final_rounding_proof: dict[str, Any] | None = None,
    rounding_check: Callable[..., object] | None = None,
) -> dict[str, Any]:
    """Prepare one literal exact-percent-text + note update, not a final grade.

    target_check owns fresh registered mirror axes/protection, Canvas metadata
    and the existing field's compatibility with literal proposal text. Original
    writer staged_source_check must verify its designated four proposal fields
    and actual readback, not canonical G/K or the PIN-accounting tab.
    For exact-number opt-in, the same trusted target checker must qualify the
    NUMBER encoding. Capture/readback must use the identical stable native
    input-field mask, including all protected fields but no output-only derived
    fields at the target. Exact source rational text is retained in source/note.
    """
    request, before, bound, selected, observed, stage_ref = (
        copy.deepcopy(x)
        for x in (
            source_request,
            raw,
            binding,
            target,
            canvas_observation,
            unit_sheet_readback_ref,
        )
    )
    _need(prior_outcome == "KNOWN_NOT_SENT", "PRIVATE_EDIT_RECONCILE_PRIOR_OUTCOME")
    source = _qualified(request, source_check)
    rounded_final = score_representation == FINAL_NEAREST
    proof = copy.deepcopy(final_rounding_proof)
    if not rounded_final:
        _need(
            proof is None and rounding_check is None,
            "PRIVATE_EXPLICIT_FINAL_ROUNDING_MODE_REQUIRED",
        )
        value = _encoded_score(source["score_text"], score_representation)
    _reference(stage_ref)
    _need(
        _call(
            staged_source_check,
            "PRIVATE_EDIT_REAL_SHEET_READBACK_REQUIRED",
            source,
            stage_ref,
        )
        is None,
        "PRIVATE_EDIT_REAL_SHEET_READBACK_REQUIRED",
    )
    _need(
        type(selected) is dict
        and all(
            _id(selected.get(k)) for k in ("course_id", "user_id", "assignment_id")
        ),
        "PRIVATE_EDIT_EXACT_TARGET_REQUIRED",
    )
    _need(type(selected.get("origin")) is str, "PRIVATE_EDIT_EXACT_TARGET_REQUIRED")
    origin = urlsplit(selected["origin"])
    _need(
        origin.scheme == "https"
        and origin.hostname
        and not origin.username
        and not origin.password
        and origin.path in {"", "/"}
        and not origin.query
        and not origin.fragment,
        "PRIVATE_EDIT_EXACT_TARGET_REQUIRED",
    )
    _need(
        type(expected_identity_binding_sha256) is str
        and HASH.fullmatch(expected_identity_binding_sha256)
        and source.get("identity_binding_sha256") == expected_identity_binding_sha256,
        "PRIVATE_EDIT_CURRENT_IDENTITY_REQUIRED",
    )
    _need(
        type(authorization) is EditOnlyAuthorization
        and authorization.mode == "EDIT_ONLY"
        and (authorization.origin, authorization.course_id, authorization.assignment_id)
        == (selected["origin"], selected["course_id"], selected["assignment_id"])
        and type(authorization.approval_reference) is str
        and 0 < len(authorization.approval_reference.strip()) <= 300,
        "PRIVATE_EDIT_ONLY_AUTHORIZATION_REQUIRED",
    )
    _need(
        type(observed) is dict
        and observed.get("target") == selected
        and observed.get("grade_observation") == "UNGRADED"
        and observed.get("score") is None
        and observed.get("grade") is None
        and observed.get("excused") is False
        and observed.get("visible") is True
        and observed.get("closed_period") is not True
        and (
            observed.get("closed_period") is None
            or type(observed["closed_period"]) is bool
        )
        and type(observed.get("assignment_points_possible")) in (int, float)
        and observed["assignment_points_possible"] == 100
        and type(observed.get("observation_sha256")) is str
        and HASH.fullmatch(observed["observation_sha256"]),
        "PRIVATE_EDIT_CURRENT_UNGRADED_100PT_TARGET_REQUIRED",
    )
    state = native._state(before)
    _need(
        type(bound) is dict
        and bound.get("spreadsheet_id") == state["spreadsheetId"]
        and str(bound.get("course_id")) == selected["course_id"]
        and set(bound.get("sheets", {}))
        == set(bound.get("tab_names", {}))
        == {"Canvas", "Working", "_Sync"}
        and len(set(bound["sheets"].values())) == 3,
        "PRIVATE_EDIT_REGISTERED_MIRROR_REQUIRED",
    )
    for role, sid in bound["sheets"].items():
        _need(
            type(sid) is int
            and sid in state["sheets"]
            and state["sheets"][sid]["properties"]["title"] == bound["tab_names"][role],
            "PRIVATE_EDIT_BOUND_TAB_CHANGED",
        )
    _need(
        _call(
            target_check,
            "PRIVATE_EDIT_CURRENT_TARGET_GUARD_REQUIRED",
            before,
            bound,
            selected,
            observed,
            expected_identity_binding_sha256,
        )
        is None,
        "PRIVATE_EDIT_CURRENT_TARGET_GUARD_REQUIRED",
    )
    if rounded_final:
        intended_final = _final_rounding_value(
            source, selected, cast(dict[str, Any], proof)
        )
        _need(
            _call(
                rounding_check,
                "PRIVATE_FINAL_ROUNDING_AUTHORITY_REQUIRED",
                source,
                selected,
                proof,
            )
            is None,
            "PRIVATE_FINAL_ROUNDING_AUTHORITY_REQUIRED",
        )
        value = {"numberValue": intended_final}
    sid = bound["sheets"]["Working"]
    row, col = _location(state["sheets"][sid]["cells"], selected)
    # _cell may extend an omitted blank representation, so never mutate before.
    after = copy.deepcopy(before)
    old = copy.deepcopy(_cell(after, sid, row, col))
    if score_representation in {"EXACT_BINARY64_PERCENT_NO_DERIVATION", FINAL_NEAREST}:
        _need(
            not ({"effectiveValue", "formattedValue", "effectiveFormat"} & set(old)),
            "PRIVATE_EDIT_NUMERIC_STABLE_FIELD_MASK_REQUIRED",
        )
    note = old.get("note", "")
    _need(type(note) is str, "PRIVATE_EDIT_NATIVE_NOTE_REQUIRED")
    selection: dict[str, Any] = {
        "source_request": request,
        "source": source,
        "binding": bound,
        "target": selected,
        "expected_identity_binding_sha256": expected_identity_binding_sha256,
        "canvas_observation": observed,
        "unit_sheet_readback_ref": stage_ref,
        "authorization": asdict(authorization),
    }
    if rounded_final:
        selection["final_rounding_proof"] = proof
    block_id = digest(
        {k: selection[k] for k in ("source", "target", "unit_sheet_readback_ref")}
    )
    block = (
        START
        + block_id
        + "]]\nUNAPPROVED private whole-test proposal: "
        + source["score_text"]
        + (
            " percent (original exact evidence; final nearest-percent staging: "
            + str(intended_final)
            + "; no component or native change).\n"
            if rounded_final
            else " percent (exact text; no rounding/floor/second conversion).\n"
            if score_representation == "EXACT_PERCENT_TEXT_NO_DERIVATION"
            else " percent (exact numeric encoding; original rational text retained; "
            "no rounding/floor/second conversion).\n"
        )
        + "Canonical native score/holds unchanged. Not accepted; no Canvas delivery.\n"
        + "Review: "
        + source["review_state"]["status"]
        + ". Body provenance: "
        + (
            NATIVE_BODY
            if source["author_contract"] == NATIVE_AUTHOR
            else REVIEWED_BODY
            if source["author_contract"] == REVIEWED_AUTHOR
            else BODY_VERSION
        )
        + ".\n"
        + source["feedback"]
        + "\n"
        + END
    )
    if START in note or END in note:
        _need(
            old.get("userEnteredValue") == value
            and note.endswith(block)
            and note.count(START) == note.count(END) == 1,
            "PRIVATE_EDIT_CONFLICTING_DRAFT_HELD",
        )
        requests: list[dict[str, Any]] = []
        after = copy.deepcopy(before)
    else:
        _need(
            not old.get("userEnteredValue"), "PRIVATE_EDIT_BLANK_DESTINATION_REQUIRED"
        )
        updated = note + ("\n\n" if note else "") + block
        _need(len(updated) <= 50000, "PRIVATE_EDIT_NOTE_CAPACITY_HELD")
        replacement = {"userEnteredValue": value, "note": updated}
        _cell(after, sid, row, col).update(replacement)
        requests = [
            {
                "updateCells": {
                    "start": {"sheetId": sid, "rowIndex": row, "columnIndex": col},
                    "rows": [{"values": [replacement]}],
                    "fields": "userEnteredValue,note",
                }
            }
        ]
    return {
        "contract": CONTRACT,
        "source_role": ROLE,
        **selection,
        "status": "PREPARED_NOT_EXECUTED" if requests else "NO_CHANGE",
        "before_raw": before,
        "after_raw": after,
        "before_fingerprint": digest(before),
        "after_fingerprint": digest(after),
        "requests": requests,
        "canvas_requests": [],
        "score_representation": score_representation,
        **(
            {
                "staged_final_percent": intended_final,
                "original_exact_percent": source["score_text"],
            }
            if rounded_final
            else {}
        ),
        "retry_writes": False,
        **dict.fromkeys(FLAGS, False),
        "canvas_writes": 0,
        "sheets_writes": 0,
    }


def _plan(plan: dict[str, Any], expected_plan_sha256: str) -> None:
    _need(
        digest(plan) == expected_plan_sha256
        and plan.get("contract") == CONTRACT
        and plan.get("source_role") == ROLE
        and plan.get("canvas_requests") == []
        and all(plan.get(k) is False for k in FLAGS),
        "PRIVATE_EDIT_PLAN_CHANGED",
    )


def revalidate_private_edit(
    plan: dict[str, Any],
    *,
    raw: dict[str, Any],
    canvas_observation: dict[str, Any],
    expected_plan_sha256: str,
    source_check: SourceCheck | None,
    staged_source_check: StageCheck | None,
    target_check: TargetCheck | None,
    prior_outcome: str,
    rounding_check: Callable[..., object] | None = None,
) -> None:
    _plan(plan, expected_plan_sha256)
    _need(digest(raw) == plan["before_fingerprint"], "PRIVATE_EDIT_STALE_FULL_PREIMAGE")
    fresh = prepare_private_edit(
        plan["source_request"],
        raw=raw,
        binding=plan["binding"],
        target=plan["target"],
        expected_identity_binding_sha256=plan["expected_identity_binding_sha256"],
        canvas_observation=canvas_observation,
        unit_sheet_readback_ref=plan["unit_sheet_readback_ref"],
        authorization=EditOnlyAuthorization(**plan["authorization"]),
        prior_outcome=prior_outcome,
        source_check=source_check,
        staged_source_check=staged_source_check,
        target_check=target_check,
        score_representation=plan["score_representation"],
        final_rounding_proof=plan.get("final_rounding_proof"),
        rounding_check=rounding_check,
    )
    _need(digest(fresh) == expected_plan_sha256, "PRIVATE_EDIT_PLAN_CHANGED")


def _verified_target_display(
    plan: dict[str, Any], raw: dict[str, Any]
) -> tuple[dict[str, Any] | None, list[str]]:
    """Compare only exact literal-text derived fields at the planned target.

    Preserve the actual response and immutable preimages. For comparison only,
    restore the plan's representation of effectiveValue/formattedValue AFTER
    checking each observed field equals the exact string we intended to write.
    No other field, cell, chip, format, protection or metadata is discarded.
    A field captured in the plan but missing in readback still differs.
    """
    try:
        sid = plan["binding"]["sheets"]["Working"]
        expected_raw = copy.deepcopy(plan["after_raw"])
        state = native._state(expected_raw)
        row, col = _location(state["sheets"][sid]["cells"], plan["target"])
        expected = _cell(expected_raw, sid, row, col)
        value = expected.get("userEnteredValue")
        if plan.get("score_representation") == FINAL_NEAREST:
            final = _final_rounding_value(
                plan["source"], plan["target"], plan["final_rounding_proof"]
            )
            if (
                type(plan.get("staged_final_percent")) is not int
                or plan["staged_final_percent"] != final
                or plan.get("original_exact_percent") != plan["source"]["score_text"]
                or value != {"numberValue": final}
            ):
                return None, []
            return copy.deepcopy(raw), []
        if plan.get("score_representation") == "EXACT_BINARY64_PERCENT_NO_DERIVATION":
            if value != _encoded_score(
                plan["source"]["score_text"], plan["score_representation"]
            ):
                return None, []
            # Numeric captures/readbacks use one stable input-field mask.
            # No output-only display field is discarded or normalized.
            return copy.deepcopy(raw), []
        if not (
            type(value) is dict
            and set(value) == {"stringValue"}
            and type(value["stringValue"]) is str
            and value["stringValue"] == plan["source"]["score_text"]
        ):
            return None, []
        comparison = copy.deepcopy(raw)
        selected = _cell(comparison, sid, row, col)
        if selected.get("userEnteredValue") != value or selected.get(
            "note"
        ) != expected.get("note"):
            return None, []
        verified = []
        allowed = {"effectiveValue": value, "formattedValue": value["stringValue"]}
        for key, intended in allowed.items():
            if key not in selected:
                continue
            if _source_digest(selected[key]) != _source_digest(intended):
                return None, []
            verified.append(key)
            if key in expected:
                selected[key] = copy.deepcopy(expected[key])
            else:
                selected.pop(key)
        return comparison, verified
    except (GradebookError, KeyError, TypeError, ValueError, StopIteration):
        return None, []


def classify_private_edit_readback(
    plan: dict[str, Any],
    raw: dict[str, Any],
    *,
    expected_plan_sha256: str,
) -> dict[str, Any]:
    _plan(plan, expected_plan_sha256)
    current = digest(raw)
    comparison, verified = _verified_target_display(plan, raw)
    compared = digest(comparison) if comparison is not None else None
    status = (
        "PLANNED_OUTPUT_OBSERVED"
        if compared == plan["after_fingerprint"]
        else "BEFORE_STILL_PRESENT"
        if current == plan["before_fingerprint"]
        else "DIVERGED"
    )
    return {
        "contract": CONTRACT,
        "status": status,
        "plan_sha256": expected_plan_sha256,
        "actual_fingerprint": current,
        "comparison_fingerprint": compared,
        "verified_target_derived_fields": verified,
        "readback_field_contract": "PRIVATE_EDIT_EXACT_LITERAL_TARGET_DISPLAY_V1",
        "retry_writes": False,
        **dict.fromkeys(FLAGS, False),
        "canvas_writes": 0,
        "sheets_writes": 0,
    }
