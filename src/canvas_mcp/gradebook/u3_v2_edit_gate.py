"""Pure source-owned destination gate for an unapproved v2 EDIT note.

This does not authenticate U3 evidence, PIN identity, teacher approval, or any
Canvas operation. A trusted application must independently supply those owners,
verify the registered workbook and fresh target, and hold the journal lock.
"""

from __future__ import annotations

import copy
from collections.abc import Callable
from typing import Any

from . import native
from .client import GradebookError
from .edit_axis_refresh import _raw
from .model import digest
from .sparse_edit_axis_refresh import (
    _AXIS_OBSERVED_FORMAT_SCOPE,
    extract_sparse_edits,
    verify_sparse_edit_axis_output,
)
from .teacher_edit_transfer import _location


def qualify_v2_note_destination(
    *,
    before_raw: dict[str, Any],
    plan: dict[str, Any],
    expected_plan_sha256: str,
    raw: dict[str, Any],
    binding: dict[str, Any],
    target: dict[str, str],
    observed_format_authority: Callable[..., Any] | None = None,
) -> dict[str, Any]:
    """Reconstruct the exact predecessor plan, then check current native state.

    This is strictly an EDIT destination/format check, not evidence admission.
    Neither a pinned plan nor a returned location grants write authority.
    """
    if (
        type(plan) is not dict
        or type(expected_plan_sha256) is not str
        or digest(plan) != expected_plan_sha256
        or type(target) is not dict
        or set(target) != {"user_id", "assignment_id"}
        or any(type(v) is not str for v in target.values())
        or type(binding) is not dict
        or plan.get("binding_digest") != digest(binding)
        or plan.get("current_rows_only_assignment_id") != target["assignment_id"]
    ):
        raise GradebookError("U3_V2_EXACT_DESTINATION_REQUIRED")
    observed = plan.get("observed_format") is not None
    if observed != callable(observed_format_authority):
        raise GradebookError("U3_V2_FORMAT_AUTHORITY_REQUIRED")
    baseline = plan.get("merged_baseline")
    if (
        type(baseline) is not dict
        or baseline.get("working_layout", {}).get("schema_version") != 2
        or digest(baseline) != plan.get("baseline_id")
        or target in baseline["working_layout"].get("excluded_targets", [])
        or target["user_id"]
        not in {x["id"] for x in plan["current_snapshot"]["students"]}
    ):
        raise GradebookError("U3_V2_TARGET_EXCLUDED_OR_CHANGED")
    projected = native._state(before_raw)
    native._apply_requests(projected, plan["batch_update"]["requests"], binding)
    after = _raw(projected)
    kwargs = (
        {
            "_observed_format_authorities": {plan["course"]: observed_format_authority},
            "_observed_format_scope": _AXIS_OBSERVED_FORMAT_SCOPE,
        }
        if observed
        else {}
    )
    verify_sparse_edit_axis_output(
        before_raw, after, [plan], {plan["course"]: binding}, **kwargs
    )
    # A current reader must preserve the entire predecessor-derived protection
    # and rule records, not only the score ranges checked by sparse ownership.
    expected_state = native._state(after)
    state = native._state(raw)
    for sid in binding["sheets"].values():
        for field in ("protectedRanges", "conditionalFormats"):
            if state["sheets"][sid][field] != expected_state["sheets"][sid][field]:
                raise GradebookError("U3_V2_PROTECTION_OR_RULE_CHANGED")
    if observed:
        sid = binding["sheets"]["Working"]

        def rule(work: dict[str, Any]) -> Any:
            sheets = [s for s in work["sheets"] if s["properties"]["sheetId"] == sid]
            if len(sheets) != 1 or len(sheets[0].get("conditionalFormats", [])) != 1:
                raise GradebookError("U3_V2_SUCCESSOR_RULE_CHANGED")
            return sheets[0]["conditionalFormats"][0]

        if digest(rule(raw)) != digest(rule(after)):
            raise GradebookError("U3_V2_SUCCESSOR_RULE_CHANGED")
    edits = extract_sparse_edits(raw, binding, baseline, _observed_green=observed)
    sheet = state["sheets"][binding["sheets"]["Working"]]
    row, col = _location(sheet["cells"], target)
    return {
        "contract": "U3_V2_DESTINATION_ONLY_V1",
        "plan_sha256": expected_plan_sha256,
        "baseline_sha256": digest(baseline),
        "input_fingerprint": native.fingerprint(raw),
        "target": copy.deepcopy(target),
        "row": row,
        "column": col,
        "edits": edits,
        "teacher_accepted": False,
        "publication_allowed": False,
        "canvas_writes": 0,
        "sheets_writes": 0,
    }
