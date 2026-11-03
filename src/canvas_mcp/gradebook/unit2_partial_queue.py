"""Private Unit 2 proposals; no transport, canonical adoption or publication.

Production binding requires the real producer request, independently qualified
teacher/source checks and SDM formatter. Fictional demos establish no acceptance.
Only explicit ``retain_review`` writes, using a caller-selected private Store.
"""

from __future__ import annotations

import hashlib
import inspect
import json
import math
import re
from collections.abc import Callable
from copy import deepcopy
from datetime import datetime
from fractions import Fraction
from pathlib import Path
from typing import Any, cast
from urllib.parse import urlsplit

from canvas_mcp.core.untrusted_content import contains_fence_markers

from .model import GradebookError, digest, identifier
from .store import Store

READING = "UNIT2_READING_QUEUE_V1"
COMMENT = "UNIT2_PARTIAL_COMMENT_PLAN_V1"
_BINDING = {
    "packet_id",
    "source_sha256",
    "reading_key",
    "result_key",
    "policy_sha256",
    "form_id",
    "candidate_sha256",
    "dashboard_card_sha256",
}
_FLAGS = {
    "teacher_acceptance": False,
    "publication_allowed": False,
    "score_delivery_authorized": False,
    "comment_delivery_authorized": False,
}


def _need(condition: bool, message: str) -> None:
    if not condition:
        raise GradebookError(message)


def _portable(value: Any, active: set[int] | None = None) -> None:
    """Reject coercible Python objects, non-string keys, cycles and NaN/Infinity."""
    active = set() if active is None else active
    if value is None or type(value) in (bool, int):
        return
    if type(value) is str:
        value.encode("utf-8")
        return
    if type(value) is float:
        _need(math.isfinite(value), "Non-finite JSON value.")
        return
    _need(type(value) in (list, dict), "Portable JSON is required.")
    _need(id(value) not in active, "Cyclic JSON is forbidden.")
    active.add(id(value))
    if type(value) is dict:
        _need(all(type(k) is str for k in value), "JSON keys must be text.")
        for key, item in value.items():
            _portable(key, active)
            _portable(item, active)
    else:
        for item in value:
            _portable(item, active)
    active.remove(id(value))


def _copy(value: Any) -> Any:
    try:
        _portable(value)
        return deepcopy(value)
    except (TypeError, ValueError, RecursionError, UnicodeError) as exc:
        raise GradebookError("Portable JSON is required.") from exc


def _fields(value: Any, expected: set[str]) -> None:
    _need(type(value) is dict and set(value) == expected, "Exact schema required.")


def _binding(value: Any) -> None:
    _fields(value, _BINDING)
    for key, item in value.items():
        _need(type(item) is str, "Text source bindings required.")
        if key == "form_id":
            _need(bool(item.strip()), "An issued form binding is required.")
        else:
            _need(
                re.fullmatch(r"[a-f0-9]{64}", item) is not None,
                "Exact source digests are required.",
            )


def _check(callback: Callable[..., object], *values: Any) -> None:
    """Checks own genuine authority; a returned bool or awaitable is no approval."""
    _need(callable(callback), "Independent synchronous check required.")
    try:
        result = callback(*[deepcopy(v) for v in values])
    except Exception as exc:
        raise GradebookError("Independent qualification failed.") from exc
    if inspect.isawaitable(result):
        if inspect.iscoroutine(result):
            result.close()
        raise GradebookError("Independent check must be synchronous.")
    _need(result is None, "Independent check must return None.")


def _seal(plan: dict[str, Any], field: str) -> dict[str, Any]:
    plan[field] = digest(plan)
    return plan


def prepare_reading_request(
    choice: dict[str, Any],
    current: dict[str, Any],
    producer_request: dict[str, Any] | None = None,
    *,
    verify_teacher: Callable[..., object],
) -> dict[str, Any]:
    """Retain the frozen GrAss decision verbatim; import remains disabled.

    The trusted source owner supplies current binding/marks and a receipt map
    keyed by decision_id, with decision_sha256 and original plan per receipt.
    Native validation and genuine teacher proof belong to verify_teacher.
    """
    choice, current = _copy(choice), _copy(current)
    if producer_request is None:
        producer_request = deepcopy(choice)
    producer_request = _copy(producer_request)
    _fields(
        choice,
        {
            "contract_id",
            "mode",
            "decision_id",
            "binding",
            "option_marks_before",
            "method",
            "actor",
            "choice",
            "reason",
        },
    )
    _fields(current, {"binding", "option_marks_before", "decision_receipts"})
    fields = {
        "packet_id",
        "source_sha256",
        "reading_key",
        "result_key",
        "form_id",
        "attempt",
        "item_id",
        "policy_sha256",
        "before_item_sha256",
    }
    _fields(choice["binding"], fields)
    _fields(current["binding"], fields)
    _need(
        choice["contract_id"] == "grass.unit2.mc-teacher-decision.v1.1"
        and choice["mode"] in ("DEMO", "TEACHER_PROPOSAL"),
        "Unsupported frozen decision contract.",
    )
    _need(choice["binding"]["attempt"] == "R1", "Only sealed R1 is supported.")
    _need(
        choice["binding"] == current["binding"]
        and choice["option_marks_before"] == current["option_marks_before"],
        "Current source item changed; stale replay is forbidden.",
    )
    event = choice["decision_id"]
    _need(
        type(event) is str and bool(event.strip()) and len(event) <= 256,
        "Exact decision ID required.",
    )
    _need(producer_request == choice, "Frozen producer decision changed.")
    _fields(choice["actor"], {"kind", "attestation"})
    _need(
        choice["mode"] != "DEMO" or choice["actor"]["kind"] == "DEMO",
        "Demo actor required.",
    )
    _check(verify_teacher, choice, current, producer_request)
    decision_sha = hashlib.sha256(
        json.dumps(
            choice,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()
    receipts = current["decision_receipts"]
    _need(type(receipts) is dict, "Trusted decision receipt map required.")
    if event in receipts:
        receipt = receipts[event]
        _fields(receipt, {"decision_sha256", "plan"})
        _need(
            receipt["decision_sha256"] == decision_sha,
            "Decision ID was already used for a different payload.",
        )
        original: dict[str, Any] = _copy(receipt["plan"])
        _need(
            type(original) is dict
            and original.get("contract") == READING
            and original.get("decision_sha256") == decision_sha
            and original.get("source_request") == choice
            and original.get("requests") == []
            and original.get("canonical_import_enabled") is False
            and all(original.get(k) is False for k in _FLAGS)
            and original.get("request_id")
            == digest({k: v for k, v in original.items() if k != "request_id"}),
            "Original decision receipt is unavailable.",
        )
        return original
    return _seal(
        {
            "contract": READING,
            "state": (
                "DEMO_NOT_TEACHER_ACCEPTED"
                if choice["mode"] == "DEMO"
                else "AWAITING_GRASS_CANONICAL_ADOPTION"
            ),
            "source_request": producer_request,
            "choice": choice,
            "decision_sha256": decision_sha,
            "requires_canonical_recompute": True,
            "canonical_import_enabled": False,
            "requests": [],
            **_FLAGS,
        },
        "request_id",
    )


def _target(target: dict[str, Any]) -> None:
    _fields(
        target,
        {
            "origin",
            "course_id",
            "assignment_id",
            "user_id",
            "attempt",
            "submitted_at",
            "submission_types",
        },
    )
    origin = target["origin"]
    _need(type(origin) is str, "HTTPS Canvas origin required.")
    try:
        parsed = urlsplit(origin)
        _ = parsed.port  # Reject malformed ports without network access.
        valid = (
            parsed.scheme == "https"
            and bool(parsed.hostname)
            and parsed.username is None
            and parsed.password is None
            and not parsed.path
            and not parsed.query
            and not parsed.fragment
            and origin == "https://" + parsed.netloc
        )
    except ValueError as exc:
        raise GradebookError("Invalid Canvas origin.") from exc
    _need(valid, "Exact HTTPS origin required.")
    for key in ("course_id", "assignment_id", "user_id"):
        value = target[key]
        _need(
            type(value) is str
            and identifier(value) == value
            and str(int(value)) == value,
            "Canonical text target IDs required.",
        )
    kinds = target["submission_types"]
    _need(
        type(kinds) is list
        and bool(kinds)
        and all(type(v) is str and bool(v.strip()) for v in kinds)
        and len(kinds) == len(set(kinds)),
        "Observed submission types required.",
    )
    attempt, submitted = target["attempt"], target["submitted_at"]
    if attempt is None:
        _need(
            kinds == ["on_paper"] and submitted is None,
            "Only observed on-paper work may have no attempt.",
        )
    else:
        _need(type(attempt) is int and attempt >= 0, "Invalid observed attempt.")
        if attempt == 0:
            _need(submitted is None, "Unsubmitted attempt has conflicting timestamp.")
        else:
            _need(
                type(submitted) is str and bool(submitted), "Submission time required."
            )
            try:
                stamp = datetime.fromisoformat(submitted.replace("Z", "+00:00"))
            except ValueError as exc:
                raise GradebookError("Invalid submission time.") from exc
            _need(stamp.tzinfo is not None, "Aware submission time required.")


def prepare_comment_plan(
    result: dict[str, Any],
    target: dict[str, Any],
    *,
    source_check: Callable[..., object],
    formatter: Callable[[dict[str, Any]], object],
) -> dict[str, Any]:
    """Prepare private MC-only representation; admit no publisher category.

    The real source check owns sealed R1 policy, identity and current result/target
    qualification. The existing SDM formatter owns feedback wording.
    """
    result, target = _copy(result), _copy(target)
    _fields(
        result,
        {
            "contract",
            "binding",
            "status",
            "mc_earned",
            "mc_possible",
            "frq_status",
            "whole_test_grade",
            "feedback",
            "unresolved_items",
        },
    )
    _binding(result["binding"])
    _target(target)
    _need(
        result["contract"] == "UNIT2_MC_COMPONENT_V1"
        and result["status"] in ("MC_CLEARED", "MC_HELD")
        and result["mc_possible"] == "50"
        and result["frq_status"] == "PENDING_CLARIFICATION"
        and result["whole_test_grade"] is None,
        "Unsupported partial result.",
    )
    feedback, holds = result["feedback"], result["unresolved_items"]
    _need(
        type(feedback) is str and bool(feedback.strip()) and len(feedback) <= 45000,
        "Complete private feedback is required.",
    )
    _need(type(holds) is list, "Explicit unresolved-item list required.")
    if result["status"] == "MC_HELD":
        _need(
            bool(holds) and result["mc_earned"] is None,
            "Held MC must retain unresolved evidence and no numeric award.",
        )
    else:
        earned = result["mc_earned"]
        _need(
            not holds
            and type(earned) is str
            and re.fullmatch(r"[+-]?\d+(?:/\d+|\.\d+)?", earned) is not None,
            "Cleared MC requires an exact rational string and no holds.",
        )
        try:
            amount = Fraction(earned)
        except (ValueError, ZeroDivisionError) as exc:
            raise GradebookError("Invalid exact MC component.") from exc
        _need(0 <= amount <= 50, "MC component outside its sealed bound.")
    _check(source_check, result, target)
    plan = {
        "contract": COMMENT,
        "state": "HELD" if holds else "UNAPPROVED",
        "target": target,
        "source_binding": result["binding"],
        "source_result_sha256": digest(result),
        "whole_test_grade": None,
        "publisher_category_admitted": False,
        "requests": [],
        **_FLAGS,
    }
    if holds:
        plan.update({"holds": holds, "feedback": feedback})
    else:
        representation = {
            "contract": "UNIT2_R1_MC_ONLY_V1",
            "mc_earned": result["mc_earned"],
            "mc_possible": "50",
            "frq_status": "PENDING_CLARIFICATION",
            "whole_test_numeric": "UNCHANGED",
            "feedback": feedback,
        }
        _need(callable(formatter), "Existing SDM formatter required.")
        try:
            body = formatter(deepcopy(representation))
        except Exception as exc:
            raise GradebookError("Existing SDM formatter failed.") from exc
        if inspect.isawaitable(body):
            if inspect.iscoroutine(body):
                body.close()
            raise GradebookError("Formatter must be synchronous.")
        _need(
            type(body) is str
            and bool(body)
            and body == body.strip()
            and len(body) <= 6000
            and not contains_fence_markers(body),
            "Exact normalized formatter feedback required.",
        )
        plan.update(
            {
                "representation": representation,
                "comment_body": body,
                "proposed_category": "UNIT2_R1_MC_ONLY_V1",
            }
        )
    return _seal(plan, "plan_id")


def prepare_shortened_comment_plan(
    result: dict[str, Any],
    target: dict[str, Any],
    *,
    formatter_input: dict[str, Any],
    trusted_projection: dict[str, Any],
    formatter_path: Path,
    formatter_sha256: str,
    node_path: Path,
    feedback_contract_path: Path,
    feedback_contract_sha256: str,
    source_check: Callable[..., object],
) -> dict[str, Any]:
    """Consume the canonical GrAss compact formatter without duplicating rules.

    The independent owner check receives result, target, formatter input and
    trusted projection. It owns identity, current native awards and source/key
    qualification. Matching supplied JSON alone establishes no authority.
    """
    from .unit2_feedback import derive_projection

    result, target, formatter_input, trusted_projection = (
        _copy(value) for value in (result, target, formatter_input, trusted_projection)
    )
    _check(source_check, result, target, formatter_input, trusted_projection)
    if result.get("status") == "MC_HELD":
        return prepare_comment_plan(
            result,
            target,
            source_check=lambda *_: None,
            formatter=lambda _: None,
        )
    _target(target)
    _need(
        type(feedback_contract_sha256) is str
        and re.fullmatch(r"[a-f0-9]{64}", feedback_contract_sha256) is not None,
        "Exact canonical feedback contract digest required.",
    )
    try:
        raw = feedback_contract_path.read_bytes()
        _need(
            len(raw) <= 100_000
            and hashlib.sha256(raw).hexdigest() == feedback_contract_sha256,
            "Canonical feedback contract changed.",
        )
        contract = json.loads(raw)
    except (OSError, ValueError) as exc:
        raise GradebookError("Canonical feedback contract unavailable.") from exc
    _need(
        type(contract) is dict
        and contract.get("source_version") == "UNIT2_COMPACT_FEEDBACK_V2"
        and contract.get("export") == "formatFeedback(input, trustedProjection)",
        "Supported canonical compact feedback contract required.",
    )
    projection = derive_projection(
        formatter_input,
        trusted_projection,
        formatter_path=formatter_path,
        formatter_sha256=formatter_sha256,
        node_path=node_path,
    )
    _need(
        type(result.get("binding")) is dict,
        "Qualified native component source binding required.",
    )
    _need(
        projection.get("source_version") == contract["source_version"]
        and projection.get("form") == result["binding"]["form_id"]
        and projection.get("source_binding", {}).get("source_sha256")
        == result["binding"]["source_sha256"]
        and projection.get("source_binding", {}).get("reading_key")
        == result["binding"]["reading_key"]
        and projection.get("existing_feedback_body") == result["feedback"]
        and projection.get("component_possible") == "50"
        and projection.get("whole_final_numeric") is None
        and projection.get("whole_final_disposition") == "UNCHANGED"
        and projection.get("publication_allowed") is False
        and projection.get("staging_allowed") is False
        and projection.get("status") == "MC_COMPLETE",
        "Formatter projection differs from the qualified native component.",
    )
    try:
        _need(
            Fraction(projection["known_earned"]) == Fraction(result["mc_earned"]),
            "Native and formatter MC components disagree.",
        )
    except (ValueError, TypeError, KeyError, ZeroDivisionError) as exc:
        raise GradebookError(
            "Exact native and formatter MC components required."
        ) from exc
    lines, body = projection.get("compact_lines"), projection.get("compact_text")
    teacher_lines = projection.get("teacher_review_lines")
    teacher_text = projection.get("teacher_review_text")
    _need(
        type(lines) is list
        and bool(lines)
        and all(type(line) is str for line in lines)
        and type(body) is str
        and body == "\n".join(lines),
        "Canonical compact text and lines must match exactly.",
    )
    lines = cast(list[str], lines)
    _need(
        type(teacher_lines) is list
        and bool(teacher_lines)
        and all(type(line) is str for line in teacher_lines)
        and type(teacher_text) is str
        and teacher_text == "\n".join(teacher_lines)
        and lines[0] == teacher_lines[0] == projection.get("identity_row")
        and type(projection.get("deduction_row_count")) is int
        and projection["deduction_row_count"] == len(lines) - 1
        and type(projection.get("teacher_review_row_count")) is int
        and projection["teacher_review_row_count"] == len(teacher_lines) - 1
        and type(projection.get("feedback_required")) is bool
        and projection["feedback_required"] == (len(lines) > 1)
        and type(projection.get("teacher_review_required")) is bool
        and projection["teacher_review_required"] == (len(teacher_lines) > 1)
        and not set(lines[1:]).intersection(teacher_lines[1:]),
        "Separate canonical student and teacher channels required.",
    )
    plan = prepare_comment_plan(
        result,
        target,
        source_check=lambda *_: None,
        formatter=lambda _: body,
    )
    plan.pop("plan_id")
    plan["feedback_required"] = projection["feedback_required"]
    plan["teacher_review"] = {
        "lines": teacher_lines,
        "text": teacher_text,
        "required": projection["teacher_review_required"],
        "row_count": projection["teacher_review_row_count"],
    }
    if not plan["feedback_required"]:
        plan["state"] = "NO_COMMENT_REQUIRED"
        plan.pop("comment_body")
    plan["feedback_provenance"] = {
        "policy_id": contract["source_version"],
        "policy_sha256": feedback_contract_sha256,
        "projection_sha256": hashlib.sha256(
            json.dumps(
                projection,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
                allow_nan=False,
            ).encode("utf-8")
        ).hexdigest(),
        "formatter_sha256": formatter_sha256,
        "formatter_input_sha256": digest(formatter_input),
        "header_sha256": digest(formatter_input.get("identity")),
    }
    return _seal(plan, "plan_id")


def retain_review(store: Store, plan: dict[str, Any]) -> tuple[str, Path]:
    """Explicit idempotent private review retention; never canonical adoption."""
    plan = _copy(plan)
    _need(
        type(plan) is dict and plan.get("contract") in (READING, COMMENT),
        "Unsupported private queue contract.",
    )
    field = "request_id" if plan["contract"] == READING else "plan_id"
    common = {"contract", "state", "requests", *_FLAGS, field}
    if plan["contract"] == READING:
        _fields(
            plan,
            common
            | {
                "source_request",
                "choice",
                "requires_canonical_recompute",
                "decision_sha256",
                "canonical_import_enabled",
            },
        )
    else:
        extra = (
            {"holds", "feedback"}
            if plan.get("state") == "HELD"
            else {"representation", "comment_body", "proposed_category"}
        )
        if plan.get("state") == "NO_COMMENT_REQUIRED":
            _need(
                plan.get("feedback_required") is False and "teacher_review" in plan,
                "Explicit no-comment disposition required.",
            )
            extra.discard("comment_body")
        if "teacher_review" in plan or "feedback_required" in plan:
            extra.update({"teacher_review", "feedback_required"})
            teacher = plan.get("teacher_review")
            _fields(teacher, {"lines", "text", "required", "row_count"})
            teacher = cast(dict[str, Any], teacher)
            _need(
                type(teacher["lines"]) is list
                and bool(teacher["lines"])
                and all(type(line) is str for line in teacher["lines"])
                and teacher["text"] == "\n".join(teacher["lines"])
                and type(teacher["row_count"]) is int
                and teacher["row_count"] == len(teacher["lines"]) - 1
                and type(teacher["required"]) is bool
                and teacher["required"] == (teacher["row_count"] > 0)
                and type(plan.get("feedback_required")) is bool
                and plan["feedback_required"] == (plan.get("state") == "UNAPPROVED"),
                "Separate private teacher review required.",
            )
        if "feedback_provenance" in plan:
            extra.add("feedback_provenance")
            provenance = plan["feedback_provenance"]
            _fields(
                provenance,
                {
                    "policy_id",
                    "policy_sha256",
                    "projection_sha256",
                    "formatter_sha256",
                    "formatter_input_sha256",
                    "header_sha256",
                },
            )
            _need(
                type(provenance["policy_id"]) is str
                and re.fullmatch(r"[A-Za-z0-9_.:-]{1,100}", provenance["policy_id"])
                is not None,
                "Source formatter policy identity required.",
            )
            _need(
                all(
                    type(value) is str and re.fullmatch(r"[a-f0-9]{64}", value)
                    for key, value in provenance.items()
                    if key != "policy_id"
                ),
                "Exact feedback provenance digests required.",
            )
        _fields(
            plan,
            common
            | extra
            | {
                "target",
                "source_binding",
                "source_result_sha256",
                "whole_test_grade",
                "publisher_category_admitted",
            },
        )
    fingerprint = plan.get(field)
    unsigned = {k: v for k, v in plan.items() if k != field}
    _need(
        type(fingerprint) is str and fingerprint == digest(unsigned),
        "Private proposal fingerprint changed.",
    )
    _need(
        plan.get("requests") == [] and all(plan.get(k) is False for k in _FLAGS),
        "Private proposals cannot authorize or dispatch delivery.",
    )
    _need(
        "posted_grade" not in plan
        and "postedgrade" not in plan
        and plan.get("whole_test_grade") is None,
        "A whole-test grade is forbidden.",
    )
    if plan["contract"] == READING:
        _need(
            plan.get("state") == "AWAITING_GRASS_CANONICAL_ADOPTION"
            and plan.get("requires_canonical_recompute") is True
            and plan.get("canonical_import_enabled") is False,
            "Canonical adoption must remain pending.",
        )
    else:
        _need(
            plan.get("state") in ("HELD", "UNAPPROVED", "NO_COMMENT_REQUIRED")
            and plan.get("publisher_category_admitted") is False,
            "Comment delivery remains unadmitted.",
        )
        _need(
            plan["state"] != "HELD" or "comment_body" not in plan,
            "Held evidence cannot create a comment body.",
        )
    return store.save("review", plan)
