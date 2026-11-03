"""Pure native-result admission into the existing whole-proposal profile.

No grading, formatting, I/O, current-authority inference or execution occurs here.
The trusted original owner authenticates current native/head/QC/identity/policy
and separately authenticates the saved renderer replay and source-line fidelity.
Reason-only academic QC never becomes assembled-comment QC by a status flag.
"""

from __future__ import annotations

import copy
import hashlib
import inspect
import json
import re
from collections.abc import Callable
from dataclasses import dataclass
from fractions import Fraction
from typing import Any

from .client import GradebookError
from .unit2_reviewed_whole_source import PROFILE, ROLE, source_digest

AUTHOR = "CURRENT_INDEPENDENT_QC_NATIVE_WHOLE_RESULT_SOURCE_V1"
BODY = "NATIVE_RESULT_EXISTING_FORMATTER_BODY_FIDELITY_VERIFIED_V1"
REQUEST = "CURRENT_NATIVE_WHOLE_RESULT_DELIVERY_REQUEST_V1"
QC = "AUTHENTICATED_CURRENT_INDEPENDENT_WHOLE_TEST_ACADEMIC_QC_V1"
BINDING = "CURRENT_NATIVE_WHOLE_DELIVERY_BINDING_V1"
REFS = (
    "binding_ref",
    "result_ref",
    "projection_ref",
    "qc_ref",
    "deductions_ref",
    "feedback_input_ref",
    "feedback_output_ref",
    "feedback_ref",
)
NATIVE_REFS = (
    "head_ref",
    "packet_ref",
    "reading_ref",
    "policy_ref",
    "judgment_ref",
    "native_review_ref",
    "question_map_ref",
    "raw_ref",
    "raw_receipt_ref",
)
HASH = re.compile(r"[a-f0-9]{64}")


def _need(value: object, code: str) -> None:
    if not value:
        raise GradebookError(code)


def _ref(ref: Any) -> None:
    _need(
        type(ref) is dict
        and {"path", "sha256"} <= set(ref) <= {"path", "bytes", "sha256"}
        and type(ref["path"]) is str
        and ref["path"].startswith("/")
        and ".." not in ref["path"].split("/")
        and type(ref["sha256"]) is str
        and HASH.fullmatch(ref["sha256"]) is not None
        and (
            "bytes" not in ref
            or type(ref["bytes"]) is int
            and 0 <= ref["bytes"] <= 2_000_000
        ),
        "NATIVE_WHOLE_EXACT_REFERENCE_REQUIRED",
    )


def _fraction(value: Any) -> Fraction:
    _need(
        type(value) is str
        and len(value) <= 160
        and re.fullmatch(
            r"(?:0|[1-9][0-9]*)(?:\.[0-9]+)?|(?:0|[1-9][0-9]*)/[1-9][0-9]*", value
        ),
        "NATIVE_WHOLE_EXACT_NONNEGATIVE_RATIONAL_REQUIRED",
    )
    return Fraction(value)


def _pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        _need(key not in result, "NATIVE_WHOLE_DUPLICATE_JSON_KEY")
        result[key] = value
    return result


def _sync(callback: Callable[..., Any], *args: Any) -> Any:
    value = callback(*(copy.deepcopy(x) for x in args))
    if inspect.isawaitable(value):
        if inspect.iscoroutine(value):
            value.close()
        raise GradebookError("NATIVE_WHOLE_SYNCHRONOUS_OWNER_CHECK_REQUIRED")
    return value


@dataclass(frozen=True)
class NativeWholeContext:
    """Trusted current original-owner result; never deserialized from a request."""

    identity_binding_sha256: str
    native_context: dict[str, Any]


@dataclass(frozen=True)
class NativeFeedbackContext:
    """Independent original-owner replay/source-line fidelity result, not QC flags.

    The ref identifies the actual saved fidelity evidence, distinct from the
    reason-only academic QC. It cannot grant target, staging or write authority.
    """

    input_sha256: str
    output_sha256: str
    body_sha256: str
    fidelity_ref: dict[str, Any]


def native_feedback_text(result: dict[str, Any]) -> str:
    """Existing packet_pipeline._build_export feedback rule, no new coaching."""
    rows = result["deductions"]
    return (
        "\n".join(f"{x['item_id']} (-{x['points_lost']}): {x['reason']}" for x in rows)
        or "No question deductions."
    )


def validate_formatter_mapping(
    result: dict[str, Any],
    projection: dict[str, Any],
    inputs: dict[str, Any],
    output: dict[str, Any],
    body: str,
) -> None:
    """Bind the existing V3 display to every native MC/FRQ criterion and export.

    Replay and correction-authority authentication remain the independent owner
    feedback_check. Equality with supplied input alone never proves provenance.
    """
    _need(
        inputs.get("existing_feedback_body") == native_feedback_text(result)
        and projection.get("feedback") == inputs["existing_feedback_body"]
        and output.get("existing_feedback_body") == inputs["existing_feedback_body"],
        "NATIVE_WHOLE_ALL_ORIGINAL_DEDUCTIONS_REQUIRED",
    )
    _need(
        output.get("source_version") == "UNIT2_COMPACT_FEEDBACK_V3"
        and output.get("source_binding") == inputs.get("source_binding")
        and output.get("compact_text") == body
        and output.get("compact_lines") == body.split("\n")
        and type(output.get("student_hold_row_count")) is int
        and output["student_hold_row_count"] == 0
        and type(output.get("teacher_review_row_count")) is int
        and output["teacher_review_row_count"] == 0
        and output.get("teacher_review_required") is False
        and output.get("whole_final_numeric") is None
        and output.get("whole_final_disposition") == "UNCHANGED"
        and all(
            output.get(k) is False
            for k in (
                "publication_allowed",
                "staging_allowed",
                "canvas_write_allowed",
                "automatic_grading_allowed",
                "teacher_acceptance_allowed",
            )
        ),
        "NATIVE_WHOLE_EXISTING_COMPLETE_FORMATTER_BODY_REQUIRED",
    )
    source = inputs.get("source_binding", {})
    _need(
        all(
            source.get(k) == result[k]
            for k in (
                "packet_id",
                "source_sha256",
                "reading_key",
                "form_id",
                "policy_sha256",
                "academic_sha256",
            )
        ),
        "NATIVE_WHOLE_FORMATTER_SOURCE_CHANGED",
    )
    native_mc = [x for x in result["items"] if x["kind"] == "MC"]
    native_frq = [x for x in result["items"] if x["kind"] == "FRQ"]
    mc: Any = inputs.get("items")
    parts: Any = inputs.get("frq_parts")
    _need(
        type(mc) is list and type(parts) is list and len(mc) == len(native_mc),
        "NATIVE_WHOLE_FORMATTER_COMPLETE_ITEMS_REQUIRED",
    )
    mapped_mc: list[str] = []
    for row in mc:
        binding = row.get("source_binding", {})
        found = [x for x in native_mc if x["item_id"] == binding.get("item_id")]
        _need(len(found) == 1, "NATIVE_WHOLE_FORMATTER_MC_IDENTITY_REQUIRED")
        item = found[0]
        _need(
            _fraction(row.get("native_earned_points"))
            == _fraction(item["earned_points"])
            and _fraction(row.get("possible_points"))
            == _fraction(item["maximum_points"])
            and row.get("student_choice") == item.get("recorded_choice"),
            "NATIVE_WHOLE_FORMATTER_MC_AWARD_CHANGED",
        )
        mapped_mc.append(item["item_id"])
    _need(
        len(set(mapped_mc)) == len(native_mc),
        "NATIVE_WHOLE_FORMATTER_MC_COVERAGE_REQUIRED",
    )
    expected: list[tuple[str, dict[str, Any]]] = [
        (x["item_id"], criterion) for x in native_frq for criterion in x["criteria"]
    ]
    observed: list[tuple[str, dict[str, Any]]] = []
    seen: set[tuple[str, str]] = set()
    for part in parts:
        binding = part.get("source_binding", {})
        key = (binding.get("item_id"), part.get("part_id"))
        _need(
            all(type(x) is str for x in key) and key not in seen,
            "NATIVE_WHOLE_FORMATTER_FRQ_IDENTITY_REQUIRED",
        )
        seen.add(key)
        criteria = binding.get("native_criteria")
        _need(
            type(criteria) is list
            and bool(criteria)
            and all(x.get("part_id") == part.get("part_id") for x in criteria),
            "NATIVE_WHOLE_FORMATTER_FRQ_CRITERIA_REQUIRED",
        )
        _need(
            sum((_fraction(x["earned_points"]) for x in criteria), Fraction())
            == _fraction(part.get("earned_points"))
            and sum((_fraction(x["maximum_points"]) for x in criteria), Fraction())
            == _fraction(part.get("possible_points")),
            "NATIVE_WHOLE_FORMATTER_FRQ_AWARD_CHANGED",
        )
        observed.extend((binding["item_id"], x) for x in criteria)
    _need(
        sorted(source_digest(x) for x in observed)
        == sorted(source_digest(x) for x in expected),
        "NATIVE_WHOLE_FORMATTER_ALL_CRITERIA_REQUIRED",
    )


def prepare_native_source(
    request: dict[str, Any],
    *,
    read_ref: Callable[[dict[str, Any]], bytes],
    current_check: Callable[..., NativeWholeContext],
    feedback_check: Callable[..., NativeFeedbackContext],
) -> dict[str, Any]:
    selected = copy.deepcopy(request)
    _need(
        type(selected) is dict
        and set(selected) == {"contract", *REFS}
        and selected["contract"] == REQUEST,
        "NATIVE_WHOLE_REQUEST_REQUIRED",
    )
    raw: dict[str, bytes] = {}

    def read(name: str, ref: Any) -> bytes:
        _ref(ref)
        data = read_ref(copy.deepcopy(ref))
        _need(
            type(data) is bytes
            and len(data) <= 2_000_000
            and hashlib.sha256(data).hexdigest() == ref["sha256"]
            and ("bytes" not in ref or len(data) == ref["bytes"]),
            "NATIVE_WHOLE_SOURCE_BYTES_CHANGED",
        )
        raw[name] = data
        _need(
            sum(map(len, raw.values())) <= 20_000_000,
            "NATIVE_WHOLE_SOURCE_BUDGET_EXCEEDED",
        )
        return data

    def parse(data: bytes) -> Any:
        try:
            return json.loads(
                data,
                object_pairs_hook=_pairs,
                parse_constant=lambda _: (_ for _ in ()).throw(ValueError()),
            )
        except (ValueError, UnicodeError):
            raise GradebookError("NATIVE_WHOLE_INVALID_JSON") from None

    docs = {
        name: parse(read(name, selected[name]))
        for name in REFS
        if name != "feedback_ref"
    }
    try:
        body = read("feedback_ref", selected["feedback_ref"]).decode("utf-8")
    except UnicodeError:
        raise GradebookError("NATIVE_WHOLE_INVALID_UTF8_BODY") from None
    binding, result, projection, qc, deductions = (
        docs[k]
        for k in (
            "binding_ref",
            "result_ref",
            "projection_ref",
            "qc_ref",
            "deductions_ref",
        )
    )
    _need(
        type(binding) is dict
        and set(binding)
        == {
            "contract",
            "source_reading_result_policy_refs",
            "packet_id",
            "source_sha256",
            "identity",
        }
        and binding["contract"] == BINDING
        and type(binding["source_reading_result_policy_refs"]) is dict
        and set(binding["source_reading_result_policy_refs"])
        == {*NATIVE_REFS, "result_ref"},
        "NATIVE_WHOLE_BINDING_REQUIRED",
    )
    refs = binding["source_reading_result_policy_refs"]
    _need(
        refs["result_ref"] == selected["result_ref"],
        "NATIVE_WHOLE_RESULT_REFERENCE_CHANGED",
    )
    native = {name: parse(read(name, refs[name])) for name in NATIVE_REFS}
    head, packet, policy = (native[k] for k in ("head_ref", "packet_ref", "policy_ref"))
    _need(
        binding["packet_id"] == packet.get("packet_id")
        and binding["source_sha256"] == packet.get("source_sha256")
        and binding["identity"]
        == {k: packet.get(k) for k in ("pin", "section", "form_id", "attempt")},
        "NATIVE_WHOLE_TYPED_SOURCE_IDENTITY_BINDING_REQUIRED",
    )
    _need(
        type(result) is dict
        and type(result.get("schema_version")) is int
        and result["schema_version"] == 1
        and result.get("status") == "PROPOSED_REVIEW_REQUIRED"
        and result.get("holds") == []
        and result.get("teacher_acceptance") == "NOT_ACCEPTED"
        and result.get("publication_status") == "NOT_AUTHORIZED"
        and result.get("grade_preview") is not None
        and type(result.get("items")) is list
        and bool(result["items"])
        and type(result.get("deductions")) is list,
        "NATIVE_WHOLE_COMPLETE_UNACCEPTED_RESULT_REQUIRED",
    )
    summary = projection.get("summary_row", {})
    _need(
        head.get("status") in {"PROPOSED_REVIEW_REQUIRED", "QC_CLEARED"}
        and native["native_review_ref"].get("decision") in {None, "QC_CLEARED"}
        and projection.get("status") in {"PROPOSED_REVIEW_REQUIRED", "QC_CLEARED"}
        and summary.get("teacher_accepted_grade") == ""
        and summary.get("canvas_status") == "NOT_AUTHORIZED"
        and type(summary.get("holds")) is int
        and summary["holds"] == 0,
        "NATIVE_WHOLE_EFFECTIVE_TEACHER_OR_HOLD_STATE_REQUIRED",
    )
    amount = _fraction(result["grade_preview"])
    earned, possible = (
        _fraction(result[k]) for k in ("known_weighted_earned", "weighted_possible")
    )
    _need(
        0 <= amount <= 100 and 0 <= earned <= possible and possible > 0,
        "NATIVE_WHOLE_NATIVE_PERCENT_REQUIRED",
    )
    _need(
        all(
            result.get(k) == packet.get(k)
            for k in (
                "packet_id",
                "source_sha256",
                "academic_sha256",
                "assessment_id",
                "form_id",
            )
        )
        and result.get("reading_key") == head.get("reading_key")
        and result.get("judgment_key") == head.get("judgment_key")
        and result.get("policy_sha256") == refs["policy_ref"]["sha256"]
        and policy.get("status") == "SEALED",
        "NATIVE_WHOLE_CURRENT_SOURCE_POLICY_REQUIRED",
    )
    item_ids = [x["item_id"] for x in result["items"]]
    _need(
        len(set(item_ids)) == len(item_ids)
        and all(type(x) is str and bool(x) for x in item_ids),
        "NATIVE_WHOLE_UNIQUE_ITEMS_REQUIRED",
    )
    for item in result["items"]:
        _need(
            item.get("kind") in {"MC", "FRQ"}
            and type(item.get("criteria")) is list
            and _fraction(item.get("earned_points"))
            <= _fraction(item.get("maximum_points")),
            "NATIVE_WHOLE_COMPLETE_ITEM_REQUIRED",
        )
        criteria = item["criteria"]
        ids = [x.get("criterion_id") for x in criteria]
        _need(
            len(set(ids)) == len(ids) and all(type(x) is str and bool(x) for x in ids),
            "NATIVE_WHOLE_UNIQUE_CRITERIA_REQUIRED",
        )
        for criterion in criteria:
            _need(
                _fraction(criterion.get("earned_points"))
                <= _fraction(criterion.get("maximum_points")),
                "NATIVE_WHOLE_COMPLETE_CRITERION_REQUIRED",
            )
    for deduction in result["deductions"]:
        _need(
            type(deduction) is dict
            and {"item_id", "points_lost", "reason"}
            <= set(deduction)
            <= {"item_id", "criterion_id", "points_lost", "reason"}
            and deduction["item_id"] in item_ids
            and _fraction(deduction["points_lost"]) > 0
            and type(deduction["reason"]) is str
            and bool(deduction["reason"].strip()),
            "NATIVE_WHOLE_LITERAL_DEDUCTION_REQUIRED",
        )
    traces = result.get("operation_traces")
    _need(
        type(traces) is list
        and bool(traces)
        and [x.get("operation") for x in traces] == policy.get("grade_operations")
        and _fraction(traces[0].get("before")) == earned
        and _fraction(traces[-1].get("after")) == amount
        and all(
            _fraction(a.get("after")) == _fraction(b.get("before"))
            for a, b in zip(traces, traces[1:], strict=False)
        ),
        "NATIVE_WHOLE_SEALED_OPERATION_TRACE_REQUIRED",
    )
    _need(
        type(qc) is dict
        and qc.get("contract") == QC
        and qc.get("verdict") == "PASS_CURRENT_SAVED_RESULT_ACADEMIC_QC"
        and qc.get("findings") == []
        and qc.get("exact_result_binding")
        == {"current_result_key": head.get("result_key"), **refs}
        and type(qc.get("current_actor_proof")) is dict
        and bool(qc["current_actor_proof"]),
        "NATIVE_WHOLE_CURRENT_RESULT_SPECIFIC_INDEPENDENT_QC_REQUIRED",
    )
    arithmetic = qc.get("rational_arithmetic", {})
    _need(
        _fraction(arithmetic.get("weighted_earned_exact")) == earned
        and _fraction(arithmetic.get("weighted_possible_exact")) == possible
        and _fraction(arithmetic.get("percentage_exact")) == earned * 100 / possible
        and arithmetic.get("matches_saved_preview") is True
        and arithmetic.get("rounding_or_floor_or_award_changes") is False,
        "NATIVE_WHOLE_INDEPENDENT_EXACT_ARITHMETIC_REQUIRED",
    )
    matrix, scope = qc.get("component_matrix"), qc.get("review_scope", {})
    expected_count = sum(len(x["criteria"]) or 1 for x in result["items"])
    _need(
        type(matrix) is list
        and len(matrix) == expected_count
        and scope.get("total_components") == expected_count
        and scope.get("required_items") == len(result["items"])
        and scope.get("deduction_feedback_entries") == len(result["deductions"])
        and all(x.get("verdict") == "SUPPORTED" for x in matrix)
        and {x.get("item_id") for x in matrix}
        == {x["item_id"] for x in result["items"]},
        "NATIVE_WHOLE_FULL_INDEPENDENT_COVERAGE_REQUIRED",
    )
    _need(
        deductions == result["deductions"]
        and qc.get("feedback", {}).get("reviewed_exact_saved_deduction_data")
        == selected["deductions_ref"]
        and qc["feedback"].get("all_deduction_scopes_amounts_and_reasons_supported")
        is True
        and qc["feedback"].get("deduction_text_changes") is False,
        "NATIVE_WHOLE_EXACT_REVIEWED_DEDUCTIONS_REQUIRED",
    )
    _need(
        projection.get("items") == result["items"]
        and projection.get("holds") == []
        and projection.get("packet_id") == result["packet_id"]
        and projection.get("result_key") == head.get("result_key")
        and projection.get("source_sha256") == result["source_sha256"]
        and projection.get("summary_row", {}).get("grade_preview")
        == result["grade_preview"],
        "NATIVE_WHOLE_EXACT_NATIVE_EXPORT_REQUIRED",
    )
    inputs, output = docs["feedback_input_ref"], docs["feedback_output_ref"]
    validate_formatter_mapping(result, projection, inputs, output, body)
    _need(
        inputs["source_binding"].get("result_key") == head.get("result_key")
        and all(
            inputs["source_binding"].get(k) == refs[n]["sha256"]
            for k, n in (
                ("packet_json_sha256", "packet_ref"),
                ("reading_json_sha256", "reading_ref"),
                ("result_json_sha256", "result_ref"),
            )
        ),
        "NATIVE_WHOLE_FORMATTER_NATIVE_BYTES_CHANGED",
    )
    context = _sync(current_check, selected, binding, native, result, qc)
    _need(
        type(context) is NativeWholeContext
        and type(context.identity_binding_sha256) is str
        and HASH.fullmatch(context.identity_binding_sha256)
        and context.native_context
        == {k: result[k] for k in ("grade_preview", "status", "holds")},
        "NATIVE_WHOLE_AUTHENTIC_CURRENT_OWNER_REQUIRED",
    )
    fidelity = _sync(
        feedback_check, selected, binding, result, projection, inputs, output, body
    )
    _need(
        type(fidelity) is NativeFeedbackContext
        and (fidelity.input_sha256, fidelity.output_sha256, fidelity.body_sha256)
        == tuple(
            selected[k]["sha256"]
            for k in ("feedback_input_ref", "feedback_output_ref", "feedback_ref")
        ),
        "NATIVE_WHOLE_INDEPENDENT_RENDERER_FIDELITY_REQUIRED",
    )
    _ref(fidelity.fidelity_ref)
    read("fidelity_ref", fidelity.fidelity_ref)
    profile = {
        "contract": PROFILE,
        "author_contract": AUTHOR,
        "source_role": ROLE,
        "body_source_role": ROLE,
        "scope": "WHOLE_TEST",
        "qualification": "SOURCE_IDENTITY_FORM_POLICY_CURRENT_CALCULATION_VALID",
        "source_request_sha256": source_digest(selected),
        "original_case_unchanged": selected,
        "proposal_ref": selected["result_ref"],
        "native_snapshot_ref": selected["result_ref"],
        "calculation_proof_ref": selected["qc_ref"],
        "body_proof_ref": selected["feedback_ref"],
        "score_text": str(amount),
        "score_units": "percent",
        "feedback": body,
        "actual_authored_body_version": BODY,
        "identity_binding_sha256": context.identity_binding_sha256,
        "native_context": copy.deepcopy(context.native_context),
        "review_state": {"status": "REVIEW_RECORDED", "ref": selected["qc_ref"]},
        "original_feedback_format_status": {
            "actual_authored_source_version": BODY,
            "is_body_QC_passed": False,
            "is_canonical_formatter_output": True,
            "is_maintained_V6_publisher_ready": False,
            "V7_runtime_adoption_claimed": False,
            "original_formatter_version": output["source_version"],
            "new_comment_assembly": False,
            "reason_only_academic_QC_is_not_assembled_body_QC": True,
            "independent_renderer_fidelity_ref": copy.deepcopy(fidelity.fidelity_ref),
        },
        "source_math_validation": {
            "case": selected,
            "percent_exact": str(amount),
            "native_weighted_earned_exact": str(earned),
            "native_weighted_possible_exact": str(possible),
            "raw_native_percent_exact": str(earned * 100 / possible),
            "native_operation_traces": copy.deepcopy(result.get("operation_traces")),
            "body_sha256": selected["feedback_ref"]["sha256"],
            "independent_QC_ref": selected["qc_ref"],
            "native_result_unchanged": True,
            "reason_entries_preserved_in_native_export": len(deductions),
        },
        "teacher_accepted": False,
        "live_write_allowed": False,
        "publication_allowed": False,
    }
    validate_native_profile(selected, profile)
    return profile


def validate_native_profile(request: dict[str, Any], source: dict[str, Any]) -> None:
    _need(
        source.get("contract") == PROFILE
        and source.get("author_contract") == AUTHOR
        and source.get("actual_authored_body_version") == BODY
        and source.get("source_request_sha256") == source_digest(request)
        and source.get("original_case_unchanged") == request
        and request.get("contract") == REQUEST
        and set(request) == {"contract", *REFS},
        "NATIVE_WHOLE_PROFILE_BINDING_REQUIRED",
    )
    _need(
        all(
            source.get(k) == request[n]
            for k, n in (
                ("proposal_ref", "result_ref"),
                ("native_snapshot_ref", "result_ref"),
                ("calculation_proof_ref", "qc_ref"),
                ("body_proof_ref", "feedback_ref"),
            )
        )
        and source.get("source_role") == source.get("body_source_role") == ROLE
        and source.get("review_state")
        == {"status": "REVIEW_RECORDED", "ref": request["qc_ref"]},
        "NATIVE_WHOLE_PROFILE_SOURCE_QC_REQUIRED",
    )
    native = source.get("native_context", {})
    math = source.get("source_math_validation", {})
    _need(
        native.get("holds") == []
        and native.get("status") == "PROPOSED_REVIEW_REQUIRED"
        and _fraction(native.get("grade_preview"))
        == _fraction(source.get("score_text"))
        and math.get("case") == request
        and math.get("percent_exact") == source["score_text"]
        and math.get("native_result_unchanged") is True
        and math.get("independent_QC_ref") == request["qc_ref"]
        and type(source.get("feedback")) is str
        and bool(source["feedback"].strip())
        and math.get("body_sha256")
        == hashlib.sha256(source["feedback"].encode()).hexdigest()
        == request["feedback_ref"]["sha256"]
        and all(
            source.get(k) is False
            for k in ("teacher_accepted", "live_write_allowed", "publication_allowed")
        ),
        "NATIVE_WHOLE_PROFILE_NATIVE_BODY_OR_AUTHORITY_CHANGED",
    )
    fmt = source.get("original_feedback_format_status", {})
    _need(
        fmt.get("new_comment_assembly") is False
        and fmt.get("is_canonical_formatter_output") is True
        and fmt.get("original_formatter_version") == "UNIT2_COMPACT_FEEDBACK_V3"
        and fmt.get("is_body_QC_passed") is False
        and fmt.get("reason_only_academic_QC_is_not_assembled_body_QC") is True,
        "NATIVE_WHOLE_PROFILE_TRUTHFUL_BODY_PROVENANCE_REQUIRED",
    )
    _ref(fmt.get("independent_renderer_fidelity_ref"))
