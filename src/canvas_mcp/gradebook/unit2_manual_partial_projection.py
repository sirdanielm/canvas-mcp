"""Pure manual-partial Q:R:S plan. No client, file access or live execution.

This is a new partial designation, not the existing WHOLE P:S permission.
The original owner must authenticate the real manifest and unique source row.
"""

from __future__ import annotations

import copy
import json
import re
from typing import Any, cast

from .model import digest
from .unit2_note_draft import (
    SourceCheck,
    _need,
    _source,
    validate_manual_partial_candidate,
)

CONTRACT = "UNIT2_MANUAL_PARTIAL_THREE_FIELD_PLAN_V1"
DESIGNATION = "OWNER_DESIGNATED_FOR_MANUAL_PARTIAL_PROPOSALS"
FIELDS = ("proposed_feedback", "proposal_ref", "proposal_status")


def _ref(value: Any) -> None:
    _need(
        type(value) is dict
        and set(value) == {"path", "bytes", "sha256"}
        and type(value["path"]) is str
        and value["path"].startswith("/")
        and type(value["bytes"]) is int
        and value["bytes"] > 0
        and type(value["sha256"]) is str
        and re.fullmatch(r"[a-f0-9]{64}", value["sha256"]),
        "UNIT2_PARTIAL_EXACT_REFERENCE_REQUIRED",
    )


def _cell(value: Any) -> tuple[int, int]:
    _need(type(value) is str, "UNIT2_PARTIAL_DATA_CELL_REQUIRED")
    m = re.fullmatch(r"([A-Z]+)([1-9][0-9]*)", value)
    _need(m is not None, "UNIT2_PARTIAL_DATA_CELL_REQUIRED")
    assert m is not None
    col = 0
    for letter in m[1]:
        col = col * 26 + ord(letter) - 64
    return int(m[2]), col


def prepare_partial_projection(
    candidate: dict[str, Any],
    designation: dict[str, Any],
    snapshot: dict[str, Any],
    *,
    source_check: SourceCheck,
) -> dict[str, Any]:
    """No score write. A plan neither designates a row nor authenticates an author."""
    candidate, mapping, target = map(copy.deepcopy, (candidate, designation, snapshot))
    validate_manual_partial_candidate(candidate)
    _need(
        mapping.get("status") == DESIGNATION
        and mapping.get("source_role") == "MANUAL_PARTIAL"
        and mapping.get("tab") == "Grades",
        "UNIT2_PARTIAL_FIELDS_NOT_DESIGNATED",
    )
    for key in ("designation_ref", "structure_snapshot_ref"):
        _ref(mapping.get(key))
    _ref(target.get("snapshot_ref"))
    _need(
        type(mapping.get("workbook_id")) is str
        and bool(mapping["workbook_id"])
        and type(mapping.get("sheet_id")) is int
        and mapping["sheet_id"] >= 0
        and all(
            target.get(k) == mapping[k] for k in ("workbook_id", "sheet_id", "tab")
        ),
        "UNIT2_PARTIAL_TARGET_MISMATCH",
    )
    fields = mapping.get("fields")
    _need(
        type(fields) is dict and set(fields) == set(FIELDS),
        "UNIT2_PARTIAL_THREE_FIELDS_REQUIRED",
    )
    fields = cast(dict[str, Any], fields)
    locations = [
        _cell(mapping.get("protected_whole_score_cell")),
        *[_cell(fields[k]) for k in FIELDS],
    ]
    _need(
        [col for _, col in locations] == [16, 17, 18, 19]
        and len({row for row, _ in locations}) == 1,
        "UNIT2_PARTIAL_PS_SCOPE_REQUIRED",
    )
    bounds = mapping.get("grid_bounds")
    _need(
        type(bounds) is dict
        and set(bounds) == {"first_data_row", "row_count", "column_count"}
        and all(type(n) is int for n in bounds.values())
        and 1 < bounds["first_data_row"] <= bounds["row_count"]
        and all(
            bounds["first_data_row"] <= row <= bounds["row_count"]
            and col <= bounds["column_count"]
            for row, col in locations
        ),
        "UNIT2_PARTIAL_RESERVED_OR_OUTSIDE_GRID",
    )
    _need(
        target.get("grid_bounds") == bounds
        and target.get("structure_snapshot_ref") == mapping["structure_snapshot_ref"]
        and target.get("designation_sha256") == digest(mapping)
        and target.get("prior_outcome") == "KNOWN_NOT_SENT",
        "UNIT2_PARTIAL_CURRENT_STRUCTURE_PREIMAGE_REQUIRED",
    )
    row_binding = target.get("source_row_binding")
    _need(
        type(row_binding) is dict
        and row_binding == mapping.get("source_row_binding")
        and row_binding.get("status") == "CURRENT_UNIQUE_SOURCE_ROW_VERIFIED"
        and row_binding.get("row") == locations[0][0]
        and row_binding.get("candidate_sha256") == digest(candidate)
        and row_binding.get("source_sha256")
        == candidate["source_pins"]["source_sha256"]
        and row_binding.get("reading_sha256")
        == candidate["source_pins"]["reading_sha256"],
        "UNIT2_PARTIAL_CURRENT_UNIQUE_SOURCE_ROW_REQUIRED",
    )
    row_binding = cast(dict[str, Any], row_binding)
    _ref(row_binding.get("ref"))
    # This callback, not a self-supplied row/status/hash, owns actual provenance,
    # source currentness, row identity, field compatibility and designation.
    _source(source_check, candidate, mapping, target)
    cells = target.get("cells")
    names = [mapping["protected_whole_score_cell"], *[fields[k] for k in FIELDS]]
    _need(
        type(cells) is dict and set(cells) == set(names),
        "UNIT2_PARTIAL_FULL_CELL_PREIMAGES_REQUIRED",
    )
    cells = cast(dict[str, Any], cells)
    content = {
        "userEnteredValue",
        "effectiveValue",
        "formattedValue",
        "note",
        "textFormatRuns",
        "chipRuns",
        "hyperlink",
    }
    for name in names:
        _need(
            type(cells[name]) is dict and not content.intersection(cells[name]),
            "UNIT2_PARTIAL_OCCUPIED_CELL_HELD",
        )
    review = candidate["manual_context"]["review_state"]
    values = [
        candidate["body"],
        json.dumps(
            candidate["manual_context"]["original_proposal_ref"],
            sort_keys=True,
            separators=(",", ":"),
        ),
        "PARTIAL_REVIEW_RECORDED"
        if review["status"] == "REVIEW_RECORDED"
        else "PARTIAL_NOT_REVIEWED"
        if review["status"] == "NOT_REVIEWED"
        else "PARTIAL_REVIEW_UNKNOWN",
    ]
    changes = []
    for field, value in zip(FIELDS, values, strict=True):
        name = fields[field]
        after = copy.deepcopy(cells[name])
        after["userEnteredValue"] = {"stringValue": value}
        changes.append({"cell": name, "before": cells[name], "after": after})
    plan = {
        "contract": CONTRACT,
        "source_role": "MANUAL_PARTIAL",
        "disposition": "PREPARED_NOT_EXECUTABLE",
        "candidate": candidate,
        "designation": mapping,
        "target_snapshot_ref": target["snapshot_ref"],
        "whole_test_proposed_score": None,
        "protected_whole_score_cell": {
            "cell": names[0],
            "before": cells[names[0]],
            "after": copy.deepcopy(cells[names[0]]),
        },
        "changes": changes,
        "requests": [],
        "native_context_preserved": candidate["manual_context"]["native_context"],
        "remaining_component_holds": candidate["manual_context"]["remaining_holds"],
        "review_state": review,
        "teacher_accepted": False,
        "native_adoption_allowed": False,
        "live_write_allowed": False,
        "publication_allowed": False,
        "required_execution_guards": [
            "Exact operation authority and independently qualified partial designation",
            "Current original-owner source and unique source-row requalification",
            "Fresh full CellData/protection/text-compatibility and structural ownership check",
            "Once-only journal and full readback; uncertain outcomes GET only",
        ],
    }
    return {**plan, "plan_sha256": digest(plan)}
