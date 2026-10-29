"""Pure, evidence-linked UNAPPROVED previews using the existing score comparator.

Trusted application code supplies current owner bindings and a synchronous source
check. Producer IDs/digests remain opaque. Canvas hashes identify only this mapped
projection and its private review artifact; they do not admit evidence or approve
academic results. This module constructs no client, transport or publisher.
"""

from __future__ import annotations

import copy
import inspect
import math
import re
from collections import Counter
from collections.abc import Callable
from pathlib import Path
from typing import Any

from .channel_policy import lane_delivery
from .client import GradebookError
from .model import compare_edits, digest, identifier
from .store import Store

CONTRACT = "CANVAS_UNAPPROVED_PROPOSAL_PREVIEW_V1"
LANES = {"GRASS_SUMMATIVE", "SDMGRASS_FORMATIVE"}
REVISIONS = (
    "source_key",
    "evaluation_id",
    "request_revision",
    "source_revision",
    "result_revision",
    "rubric_revision",
    "config_revision",
    "identity_revision",
)
APPROVALS = (
    "teacher_approval",
    "score_approval",
    "comment_approval",
    "publication_allowed",
)
HASH = re.compile(r"[a-f0-9]{64}")
SourceCheck = Callable[
    [list[dict[str, Any]], dict[str, Any], list[dict[str, Any]]], Any
]


def _need(value: Any, code: str) -> None:
    if not value:
        raise GradebookError(code)


def _text(value: Any) -> bool:
    return type(value) is str and bool(value.strip()) and len(value) <= 4096


def _number(value: Any) -> bool:
    return type(value) in (int, float) and math.isfinite(value)


def _check_source(
    source_check: SourceCheck,
    proposals: list[dict[str, Any]],
    pins: dict[str, Any],
    bindings: list[dict[str, Any]],
) -> None:
    _need(callable(source_check), "SOURCE_AUTHORITY_REVALIDATION_HELD")
    try:
        result = source_check(
            copy.deepcopy(proposals), copy.deepcopy(pins), copy.deepcopy(bindings)
        )
    except Exception:
        raise GradebookError("SOURCE_AUTHORITY_REVALIDATION_HELD") from None
    if inspect.iscoroutine(result):
        result.close()
    _need(result is None, "SOURCE_AUTHORITY_REVALIDATION_HELD")


def _edpuzzle(row: dict[str, Any], binding: dict[str, Any] | None) -> bool:
    metadata = (binding or {}).get("assignment_metadata") or {}
    tag = (
        metadata.get("external_tool_tag_attributes")
        if isinstance(metadata, dict)
        else None
    )
    return "edpuzzle" in " ".join(
        str(value).casefold()
        for value in (row.get("provider"), (binding or {}).get("provider"), tag)
    )


def _metadata(binding: dict[str, Any]) -> None:
    """Hold external-tool provenance; deny Edpuzzle at selection and retention."""
    metadata = binding.get("assignment_metadata")
    if not isinstance(metadata, dict):
        raise GradebookError("ASSIGNMENT_METADATA_REQUIRED")
    _need(
        HASH.fullmatch(str(binding.get("assignment_metadata_sha256", "")))
        and digest(metadata) == binding["assignment_metadata_sha256"],
        "ASSIGNMENT_METADATA_CHANGED",
    )
    _need(
        str(metadata.get("id")) == binding.get("assignment_id")
        and str(metadata.get("course_id")) == binding.get("course_id"),
        "ASSIGNMENT_METADATA_CHANGED",
    )
    tag = metadata.get("external_tool_tag_attributes")
    _need(
        binding.get("excluded") is False and not _edpuzzle({}, binding),
        "EXCLUDED_PROVIDER",
    )
    types = metadata.get("submission_types")
    if not isinstance(types, list):
        raise GradebookError("ASSIGNMENT_METADATA_REQUIRED")
    _need(
        types
        and all(type(v) is str for v in types)
        and "external_tool_tag_attributes" in metadata,
        "ASSIGNMENT_METADATA_REQUIRED",
    )
    _need("external_tool" not in types and tag is None, "EXTERNAL_TOOL_REVIEW_REQUIRED")


def _selected(
    row: dict[str, Any],
    binding: dict[str, Any],
    pins: dict[str, Any],
) -> None:
    _need(digest(row) == binding.get("proposal_sha256"), "PROPOSAL_BINDING_CHANGED")
    _need(all(_text(row.get(key)) for key in REVISIONS), "PRODUCER_REFERENCE_REQUIRED")
    _need(
        row.get("source_lane") in LANES and _text(row.get("provider")),
        "SOURCE_LANE_REQUIRED",
    )
    _need(
        row.get("state") == "READY_FOR_REVIEW" and row.get("reasons") == [],
        "SOURCE_RESULT_HELD",
    )
    _need(
        row.get("review_state") in {"READY_FOR_TEACHER_REVIEW", "UNAPPROVED"},
        "PROPOSAL_REVIEW_STATE_HELD",
    )
    _need(
        row.get("publication") == "NOT_AUTHORIZED"
        and all(row.get(key, False) is False for key in APPROVALS),
        "PROPOSAL_AUTHORITY_HELD",
    )
    _need(
        all(_text(row.get(key)) for key in ("policy", "section", "score_scale")),
        "EXPLICIT_POLICY_SCALE_REQUIRED",
    )
    _need(
        all(
            type(row.get(key)) is str and identifier(row[key]) == row[key]
            for key in ("course_id", "user_id", "assignment_id")
        ),
        "EXACT_TARGET_REQUIRED",
    )
    _need(
        type(row.get("canvas_attempt")) is int
        and row["canvas_attempt"] >= 0
        and (row.get("submitted_at") is None or _text(row.get("submitted_at"))),
        "OBSERVED_ATTEMPT_REQUIRED",
    )
    _need(
        all(
            _number(row.get(key))
            for key in ("raw_score", "raw_maximum", "proposed_score", "points_possible")
        )
        and row["raw_maximum"] > 0
        and 0 <= row["raw_score"] <= row["raw_maximum"]
        and row["points_possible"] > 0
        and 0 <= row["proposed_score"] <= row["points_possible"],
        "EXPLICIT_SCORE_PROJECTION_REQUIRED",
    )
    policy = lane_delivery(row["source_lane"], row.get("delivery_policy"))
    _need(
        lane_delivery(binding["source_lane"], binding.get("delivery_policy")) == policy,
        "DELIVERY_POLICY_CHANGED",
    )
    feedback = row.get("feedback")
    if policy == "SCORE_AND_FEEDBACK":
        _need(
            type(feedback) is str
            and bool(feedback.strip())
            and len(feedback) <= 45_000,
            "FULL_FEEDBACK_REQUIRED",
        )
    else:
        # Internal analysis can be retained verbatim without any comment intent.
        _need(
            feedback is None or type(feedback) is str and len(feedback) <= 45_000,
            "FORMATIVE_ANALYSIS_INVALID",
        )
    _need(
        all(
            binding.get(key) == row.get(key)
            for key in (
                "evaluation_id",
                "source_lane",
                "provider",
                "course_id",
                "assignment_id",
                "section",
                "points_possible",
                "canvas_attempt",
                "submitted_at",
            )
        ),
        "PROPOSAL_BINDING_CHANGED",
    )
    _metadata(binding)
    _need(
        binding.get("teacher_correction_present") is False
        and binding.get("teacher_final_present") is False,
        "TEACHER_AUTHORITY_PRESERVED",
    )
    floor: Any = binding.get("assessment_floor")
    _need(
        _number(floor)
        and 0 <= floor <= row["points_possible"]
        and row["proposed_score"] >= floor,
        "ASSESSMENT_SCORE_FLOOR_PRESERVED",
    )
    _need(
        all(
            HASH.fullmatch(str(pins.get(key, "")))
            for key in ("registry_sha256", "roster_sha256")
        )
        and pins.get("identity_revision") == row["identity_revision"],
        "CANONICAL_PIN_BINDING_REQUIRED",
    )
    by_pin = pins.get("by_pin")
    _need(
        type(row.get("pin")) is str
        and re.fullmatch(r"[0-9]{4}", row["pin"])
        and isinstance(by_pin, dict)
        and by_pin.get(row["pin"]) == row["user_id"]
        and all(
            type(pin) is str
            and re.fullmatch(r"[0-9]{4}", pin)
            and type(uid) is str
            and identifier(uid) == uid
            for pin, uid in by_pin.items()
        )
        and len(set(by_pin.values())) == len(by_pin),
        "CANONICAL_PIN_JOIN_CHANGED",
    )


def _snapshots(
    baseline: dict[str, Any],
    current: dict[str, Any],
    row: dict[str, Any],
    binding: dict[str, Any],
) -> None:
    uid, aid = row["user_id"], row["assignment_id"]
    _need(
        _text(binding.get("origin"))
        and baseline.get("origin") == current.get("origin") == binding["origin"],
        "CANVAS_ORIGIN_CHANGED",
    )
    _need(
        baseline.get("origin") == current.get("origin")
        and baseline.get("course_id") == current.get("course_id") == row["course_id"]
        and current.get("course_workflow_state") == "available",
        "EXACT_ACTIVE_TARGET_REQUIRED",
    )
    for snapshot in (baseline, current):
        students = [s for s in snapshot["students"] if s["id"] == uid]
        assignments = [a for a in snapshot["assignments"] if a["id"] == aid]
        cell = snapshot["cells"].get(f"{uid}:{aid}")
        _need(
            len(students) == len(assignments) == 1
            and row["section"] in students[0].get("sections", [])
            and cell is not None
            and cell.get("visible") is True,
            "EXACT_ACTIVE_TARGET_REQUIRED",
        )
        _need(
            assignments[0].get("points_possible") == row["points_possible"]
            and assignments[0].get("grading_type") == "points",
            "ASSIGNMENT_SCHEMA_CHANGED",
        )
        _need(
            type(cell.get("attempt")) is int
            and cell["attempt"] == row["canvas_attempt"]
            and cell.get("submitted_at") == row["submitted_at"],
            "CANVAS_ATTEMPT_CHANGED",
        )
        _need(
            cell.get("excused") is False and cell.get("value") != "EX",
            "CANVAS_EXCUSAL_PRESERVED",
        )
        _need(
            cell.get("grade_matches_current_submission") is not False,
            "CURRENT_SUBMISSION_REVIEW_REQUIRED",
        )


def _comparison_snapshot(snapshot: dict[str, Any]) -> dict[str, Any]:
    # Only this named observation timestamp is non-substantive. Producer rows,
    # nested timestamps, revisions and foreign hashes are never normalized.
    result = copy.deepcopy(snapshot)
    result.pop("fetched_at", None)
    return result


def prepare_preview(
    proposals: list[dict[str, Any]],
    *,
    baseline: dict[str, Any],
    current: dict[str, Any],
    pin_binding: dict[str, Any],
    assignment_bindings: list[dict[str, Any]],
    source_check: SourceCheck,
) -> dict[str, Any]:
    """Map at most 25 explicitly selected saved rows to a private score review.

    ``proposal_sha256`` pins this Canvas-owned mapped row, not a producer's native
    serialization. The trusted callback must independently assert current saved
    source/request/result/rubric/config/identity/review and target bindings.
    Unknown identity or held inventory is never upgraded into a scored result.
    """
    _need(type(proposals) is list and len(proposals) <= 25, "PROPOSAL_BATCH_LIMIT")
    _need(
        all(type(row) is dict for row in proposals)
        and type(assignment_bindings) is list
        and all(type(binding) is dict for binding in assignment_bindings),
        "PROPOSAL_INVALID",
    )
    ids = [row.get("evaluation_id") for row in proposals]
    _need(all(_text(value) for value in ids), "PRODUCER_REFERENCE_REQUIRED")
    _need(len(set(ids)) == len(ids), "DUPLICATE_PROPOSAL")
    binding_ids = [binding.get("evaluation_id") for binding in assignment_bindings]
    _need(
        all(_text(value) for value in binding_ids)
        and len(set(binding_ids)) == len(binding_ids),
        "DUPLICATE_ASSIGNMENT_BINDING",
    )
    _check_source(source_check, proposals, pin_binding, assignment_bindings)
    old, now = _comparison_snapshot(baseline), _comparison_snapshot(current)
    selected, bindings, edits, holds, already, held_proposals = [], [], [], [], [], []
    excluded_inventory = []
    target_counts = Counter(
        (row["user_id"], row["assignment_id"])
        for row in proposals
        if row["evaluation_id"] in binding_ids
        and type(row.get("user_id")) is str
        and type(row.get("assignment_id")) is str
    )
    for row in proposals:
        binding = None
        try:
            matches = [
                b
                for b in assignment_bindings
                if b["evaluation_id"] == row["evaluation_id"]
            ]
            _need(len(matches) == 1, "PROPOSAL_NOT_IN_SELECTED_SCOPE")
            binding = matches[0]
            _selected(row, binding, pin_binding)
            _snapshots(old, now, row, binding)
            target = (row["user_id"], row["assignment_id"])
            _need(target_counts[target] == 1, "DUPLICATE_TARGET")
            edit = {
                "user_id": target[0],
                "assignment_id": target[1],
                "value": row["proposed_score"],
            }
            envelope = {
                "course_id": old["course_id"],
                "snapshot_id": digest(old),
                "edits": [edit],
            }
            review = compare_edits(old, now, envelope)
            _need(
                all(
                    c["status"] == "ready_for_review" and not c["reasons"]
                    for c in review["changes"]
                ),
                "CANVAS_COMPARISON_HELD",
            )
            if (
                now["cells"][f"{target[0]}:{target[1]}"]["value"]
                == row["proposed_score"]
            ):
                already.append(row["evaluation_id"])
            else:
                _need(bool(review["changes"]), "CANVAS_COMPARISON_HELD")
                edits.append(edit)
            selected.append(copy.deepcopy(row))
            bindings.append(copy.deepcopy(binding))
        except GradebookError as error:
            holds.append({"evaluation_id": row["evaluation_id"], "code": str(error)})
            diagnostic = {
                "code": str(error),
                "review_state": "HELD",
                "documentary_only": True,
                **dict.fromkeys(APPROVALS, False),
            }
            if (
                _edpuzzle(row, binding)
                or binding is None
                or not isinstance(binding.get("assignment_metadata"), dict)
            ):
                # Exclusion/unknown scope keeps references only. Original source
                # records remain upstream; no scored pair is retained here.
                excluded_inventory.append(
                    {
                        "references": {
                            key: copy.deepcopy(row[key])
                            for key in REVISIONS
                            if _text(row.get(key))
                        },
                        **diagnostic,
                    }
                )
            else:
                held_proposals.append(
                    {
                        "proposal": copy.deepcopy(row),
                        "assignment_binding": copy.deepcopy(binding),
                        "edits": [],
                        **diagnostic,
                    }
                )
    envelope = {
        "course_id": old["course_id"],
        "snapshot_id": digest(old),
        "edits": edits,
    }
    review = compare_edits(old, now, envelope)
    review.pop("created_at", None)
    plan = {
        "contract": CONTRACT,
        "review_state": "UNAPPROVED",
        "proposals": selected,
        "assignment_bindings": bindings,
        "delivery_policies": {
            row["evaluation_id"]: lane_delivery(
                row["source_lane"], row.get("delivery_policy")
            )
            for row in selected
        },
        "pin_binding_sha256": digest(pin_binding),
        "baseline": old,
        "current": now,
        "envelope": envelope,
        "review": review,
        "holds": holds,
        "held_proposals": held_proposals,
        "excluded_inventory": excluded_inventory,
        "already_present": already,
        "requests": [],
        "canvas_writes": 0,
        **dict.fromkeys(APPROVALS, False),
    }
    plan["preview_id"] = digest(plan)
    return plan


def save_preview(store: Store, plan: dict[str, Any]) -> tuple[str, Path]:
    """Retain a deterministic private review through the existing immutable Store."""
    _need(
        plan.get("contract") == CONTRACT
        and plan.get("preview_id")
        == digest({key: value for key, value in plan.items() if key != "preview_id"})
        and plan.get("review_state") == "UNAPPROVED"
        and plan.get("requests") == []
        and plan.get("canvas_writes") == 0
        and all(plan.get(key) is False for key in APPROVALS),
        "PROPOSAL_PREVIEW_CHANGED",
    )
    _need(
        plan.get("delivery_policies")
        == {
            row["evaluation_id"]: lane_delivery(
                row["source_lane"], row.get("delivery_policy")
            )
            for row in plan["proposals"]
        },
        "DELIVERY_POLICY_CHANGED",
    )
    for binding in plan["assignment_bindings"]:
        _metadata(binding)
    eligible_ids = {row["evaluation_id"] for row in plan["proposals"]}
    for row in plan["proposals"]:
        matches = [
            binding
            for binding in plan["assignment_bindings"]
            if binding.get("evaluation_id") == row["evaluation_id"]
        ]
        _need(len(matches) == 1 and not _edpuzzle(row, matches[0]), "EXCLUDED_PROVIDER")
        _need(
            digest(row) == matches[0].get("proposal_sha256"), "PROPOSAL_BINDING_CHANGED"
        )
    for held in plan["held_proposals"]:
        _need(
            not _edpuzzle(held["proposal"], held.get("assignment_binding")),
            "EXCLUDED_PROVIDER",
        )
        _need(
            held.get("documentary_only") is True
            and held.get("review_state") == "HELD"
            and held.get("edits") == []
            and all(held.get(key) is False for key in APPROVALS)
            and held["proposal"]["evaluation_id"] not in eligible_ids,
            "PROPOSAL_PREVIEW_CHANGED",
        )
    for excluded in plan["excluded_inventory"]:
        _need(
            set(excluded)
            == {"references", "code", "review_state", "documentary_only", *APPROVALS}
            and set(excluded["references"]) <= set(REVISIONS)
            and all(_text(value) for value in excluded["references"].values())
            and excluded.get("documentary_only") is True
            and excluded.get("review_state") == "HELD"
            and all(excluded.get(key) is False for key in APPROVALS),
            "PROPOSAL_PREVIEW_CHANGED",
        )
    return store.save("review", plan)
