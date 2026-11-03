"""Pure reviewed private-WHOLE source variant; no native grading or delivery.

The original owner's synchronous checker authenticates current source/identity,
issued form, sealed policy, exact tuple and authority. Hashes/QC file fields do
not supply that authority. The original files and authored feedback stay intact.
"""

from __future__ import annotations

import copy
import hashlib
import inspect
import json
from collections.abc import Callable
from dataclasses import dataclass
from fractions import Fraction
from typing import Any

from .client import GradebookError

AUTHOR = "INDEPENDENT_QC_REVIEWED_PRIVATE_WHOLE_SOURCE_V1"
BODY = "INDEPENDENT_QC_APPROVED_PRIVATE_WHOLE_FEEDBACK_V1"
REQUEST = "INDEPENDENT_QC_REVIEWED_PRIVATE_WHOLE_REQUEST_V1"
QC = "INDEPENDENT_WHOLE_TEST_PRIVATE_ACADEMIC_QC_V1"
PROFILE = "QUALIFIED_PRIVATE_WHOLE_PROJECTION_SOURCE_V1"
ROLE = "PRIVATE_PROPOSED_WHOLE_TEST"


def _need(value: object, code: str) -> None:
    if not value:
        raise GradebookError(code)


def _pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        _need(key not in result, "REVIEWED_WHOLE_DUPLICATE_JSON_KEY")
        result[key] = value
    return result


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


@dataclass(frozen=True)
class ReviewedWholeContext:
    """Constructed by the trusted current owner checker, never request data."""

    identity_binding_sha256: str
    native_context: dict[str, Any]


def prepare_reviewed_source(
    request: dict[str, Any],
    *,
    read_ref: Callable[[dict[str, Any]], bytes],
    current_check: Callable[..., ReviewedWholeContext],
) -> dict[str, Any]:
    selected = copy.deepcopy(request)
    _need(
        type(selected) is dict
        and set(selected)
        == {"contract", "proposal_ref", "binding_ref", "qc_ref", "feedback_ref"}
        and selected["contract"] == REQUEST,
        "REVIEWED_WHOLE_REQUEST_REQUIRED",
    )
    refs = {
        k: copy.deepcopy(selected[k])
        for k in ("proposal_ref", "binding_ref", "qc_ref", "feedback_ref")
    }
    raw: dict[str, bytes] = {}
    for name, ref in refs.items():
        _need(
            type(ref) is dict
            and {"path", "sha256"} <= set(ref) <= {"path", "sha256", "bytes"}
            and type(ref["path"]) is str
            and ref["path"].startswith("/")
            and ".." not in ref["path"].split("/"),
            "REVIEWED_WHOLE_REFERENCE_REQUIRED",
        )
        data = read_ref(copy.deepcopy(ref))
        _need(
            type(data) is bytes
            and len(data) <= 2_000_000
            and hashlib.sha256(data).hexdigest() == ref["sha256"]
            and (
                "bytes" not in ref
                or type(ref["bytes"]) is int
                and ref["bytes"] == len(data)
            ),
            "REVIEWED_WHOLE_BYTES_CHANGED",
        )
        raw[name] = data
    try:
        proposal, binding, qc = (
            json.loads(raw[k], object_pairs_hook=_pairs)
            for k in ("proposal_ref", "binding_ref", "qc_ref")
        )
        body = raw["feedback_ref"].decode("utf-8")
    except (ValueError, UnicodeError):
        raise GradebookError("REVIEWED_WHOLE_INVALID_SOURCE_BYTES") from None
    _need(
        type(qc) is dict
        and qc.get("contract") == QC
        and qc.get("verdict") == "PASS_PRIVATE_PROPOSAL_ONLY"
        and qc.get("substantive_findings") == []
        and qc.get("source_binding") == binding,
        "REVIEWED_WHOLE_INDEPENDENT_QC_REQUIRED",
    )
    _need(
        type(proposal) is dict
        and proposal.get("academic_components_complete") is True
        and type(proposal.get("remaining_academic_null_components")) is int
        and proposal["remaining_academic_null_components"] == 0
        and type(proposal.get("exact_arithmetic")) is dict
        and proposal["exact_arithmetic"] == qc.get("proposed_exact_arithmetic")
        and qc.get("no_rounding_or_floor_applied") is True
        and proposal["exact_arithmetic"].get("rounding_applied") is False,
        "REVIEWED_WHOLE_COMPLETE_SUPPORTED_SOURCE_REQUIRED",
    )
    _need(
        qc.get("feedback", {}).get("approved_body") == refs["feedback_ref"]
        and qc["feedback"].get("exact_UTF8_hash_required_for_downstream_readback")
        is True
        and bool(body.strip()),
        "REVIEWED_WHOLE_EXACT_APPROVED_FEEDBACK_REQUIRED",
    )
    reused, supplemental = (
        proposal.get(k)
        for k in ("reused_numeric_components", "new_numeric_mastery_components")
    )
    _need(
        type(reused) is int
        and type(supplemental) is int
        and reused >= 0
        and supplemental >= 0
        and reused + supplemental > 0
        and type(qc.get("component_review")) is list
        and len(qc["component_review"]) == reused + supplemental,
        "REVIEWED_WHOLE_QC_COVERAGE_REQUIRED",
    )
    exact = proposal["exact_arithmetic"].get("private_proposed_percent")
    try:
        amount = Fraction(exact) if type(exact) is str else None
    except (ValueError, ZeroDivisionError):
        amount = None
    _need(
        amount is not None and 0 <= amount <= 100,
        "REVIEWED_WHOLE_EXACT_PERCENT_REQUIRED",
    )
    try:
        arithmetic = proposal["exact_arithmetic"]
        earned, possible = (
            Fraction(arithmetic[k]) if type(arithmetic.get(k)) is str else None
            for k in ("private_proposed_weighted_earned", "weighted_possible")
        )
    except (ValueError, ZeroDivisionError):
        raise GradebookError("REVIEWED_WHOLE_EXACT_ARITHMETIC_REQUIRED") from None
    _need(
        earned is not None
        and possible is not None
        and possible > 0
        and 0 <= earned <= possible
        and earned * 100 / possible == amount,
        "REVIEWED_WHOLE_EXACT_ARITHMETIC_REQUIRED",
    )
    _need(
        type(binding) is dict
        and type(binding.get("source_reading_result_policy_refs")) is dict
        and type(binding["source_reading_result_policy_refs"].get("result")) is dict,
        "REVIEWED_WHOLE_NATIVE_REFERENCE_REQUIRED",
    )
    context: Any = current_check(
        *(copy.deepcopy(x) for x in (selected, binding, proposal, qc))
    )
    if inspect.isawaitable(context):
        if inspect.iscoroutine(context):
            context.close()
        raise GradebookError("REVIEWED_WHOLE_SYNCHRONOUS_CURRENT_OWNER_REQUIRED")
    _need(
        type(context) is ReviewedWholeContext,
        "REVIEWED_WHOLE_CURRENT_OWNER_CONTEXT_REQUIRED",
    )
    _need(
        type(context.identity_binding_sha256) is str
        and len(context.identity_binding_sha256) == 64
        and all(x in "0123456789abcdef" for x in context.identity_binding_sha256)
        and type(context.native_context) is dict
        and {"grade_preview", "status", "holds"} <= set(context.native_context)
        and type(context.native_context["holds"]) is list,
        "REVIEWED_WHOLE_NATIVE_CONTEXT_REQUIRED",
    )
    return {
        "contract": PROFILE,
        "author_contract": AUTHOR,
        "source_role": ROLE,
        "body_source_role": ROLE,
        "scope": "WHOLE_TEST",
        "qualification": "SOURCE_IDENTITY_FORM_POLICY_CURRENT_CALCULATION_VALID",
        "source_request_sha256": source_digest(selected),
        "original_case_unchanged": selected,
        "proposal_ref": refs["proposal_ref"],
        "native_snapshot_ref": copy.deepcopy(
            binding["source_reading_result_policy_refs"]["result"]
        ),
        "calculation_proof_ref": refs["qc_ref"],
        "body_proof_ref": refs["feedback_ref"],
        "score_text": str(amount),
        "score_units": "percent",
        "feedback": body,
        "actual_authored_body_version": BODY,
        "identity_binding_sha256": context.identity_binding_sha256,
        "native_context": copy.deepcopy(context.native_context),
        "review_state": {"status": "REVIEW_RECORDED", "ref": refs["qc_ref"]},
        "original_feedback_format_status": {
            "actual_authored_source_version": BODY,
            "is_body_QC_passed": True,
            "is_canonical_formatter_output": False,
            "is_maintained_V6_publisher_ready": False,
            "V7_runtime_adoption_claimed": False,
        },
        "source_math_validation": {
            "case": copy.deepcopy(selected),
            "percent_exact": str(amount),
            "body_sha256": hashlib.sha256(raw["feedback_ref"]).hexdigest(),
            "reviewed_whole_component_count": reused + supplemental,
            "independent_QC_ref": refs["qc_ref"],
            "source_proposal_arithmetic_equals_independent_review": True,
        },
        "teacher_accepted": False,
        "live_write_allowed": False,
        "publication_allowed": False,
    }


def validate_reviewed_profile(request: dict[str, Any], source: dict[str, Any]) -> None:
    """Shape/math/body binding; current authority remains the owner callback."""
    _need(
        source.get("contract") == PROFILE
        and source.get("author_contract") == AUTHOR
        and source.get("source_role") == source.get("body_source_role") == ROLE
        and source.get("scope") == "WHOLE_TEST"
        and source.get("qualification")
        == "SOURCE_IDENTITY_FORM_POLICY_CURRENT_CALCULATION_VALID"
        and source.get("source_request_sha256") == source_digest(request)
        and source.get("original_case_unchanged") == request
        and source.get("actual_authored_body_version") == BODY,
        "REVIEWED_WHOLE_PROFILE_BINDING_REQUIRED",
    )
    _need(
        all(
            source.get(k) is False
            for k in ("teacher_accepted", "live_write_allowed", "publication_allowed")
        ),
        "REVIEWED_WHOLE_CANNOT_GRANT_AUTHORITY",
    )
    _need(
        source.get("proposal_ref") == request.get("proposal_ref")
        and source.get("calculation_proof_ref") == request.get("qc_ref")
        and source.get("body_proof_ref") == request.get("feedback_ref"),
        "REVIEWED_WHOLE_PROFILE_REFERENCE_BINDING_REQUIRED",
    )
    math = source.get("source_math_validation", {})
    _need(
        math.get("case") == request
        and math.get("percent_exact") == source.get("score_text")
        and math.get("body_sha256")
        == hashlib.sha256(source["feedback"].encode()).hexdigest()
        and type(math.get("reviewed_whole_component_count")) is int
        and math["reviewed_whole_component_count"] > 0
        and math.get("source_proposal_arithmetic_equals_independent_review") is True
        and source.get("review_state")
        == {"status": "REVIEW_RECORDED", "ref": source.get("calculation_proof_ref")}
        and math.get("independent_QC_ref") == source.get("calculation_proof_ref"),
        "REVIEWED_WHOLE_PROFILE_QC_MATH_BODY_REQUIRED",
    )
