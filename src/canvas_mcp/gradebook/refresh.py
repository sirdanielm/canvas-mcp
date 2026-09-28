"""Three-way refresh planning for course-bound Google gradebook tabs.

This module performs no Google writes. The connected Drive adapter executes a
prepared batch only after a second read confirms the mapped tabs' literal cells
have not changed.
"""

from __future__ import annotations

import copy
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from .client import GradebookError
from .model import compare_edits, digest
from .workbook import column_name

COLORS = {
    "ink": "2D3B45",
    "blue": "0869B2",
    "header": "F2F3F4",
    "line": "DFE3E6",
    "late": "E2F2FC",
    "excused": "FFF2CC",
    "missing": "FCE4E8",
    "edited": "DDF3E4",
}


def rgb(hex_value: str) -> dict[str, float]:
    return dict(
        zip(
            ("red", "green", "blue"),
            (int(hex_value[i : i + 2], 16) / 255 for i in (0, 2, 4)),
            strict=True,
        )
    )


def cell(value: Any, fmt: dict[str, Any] | None = None) -> dict[str, Any]:
    result: dict[str, Any] = {}
    if value is not None:
        # stringValue is literal; Canvas-authored labels cannot become formulas.
        result["userEnteredValue"] = (
            {"numberValue": value}
            if isinstance(value, (int, float))
            else {"stringValue": str(value)}
        )
    if fmt:
        result["userEnteredFormat"] = fmt
    return result


def merge_refresh(
    baseline: dict[str, Any], current: dict[str, Any], edits: dict[str, Any]
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    """Preserve the original per-cell baseline for every pending local edit.

    Rebasing a pending cell onto fresh Canvas would erase evidence of a
    conflict. The new working baseline therefore has explicit provenance and
    retains the old cell for pending edits; all untouched cells use fresh data.
    """
    review = compare_edits(baseline, current, edits)
    changes = review["changes"]
    if changes:
        old_ids = {s["id"] for s in baseline["students"]}
        new_ids = {s["id"] for s in current["students"]}
        old_schema = {
            a["id"]: (a["points_possible"], a["grading_type"])
            for a in baseline["assignments"]
        }
        new_schema = {
            a["id"]: (a["points_possible"], a["grading_type"])
            for a in current["assignments"]
        }
        if old_ids != new_ids or old_schema != new_schema:
            raise GradebookError(
                "Roster or assignment schema changed while edits are pending. "
                "Review or archive those edits before refreshing; nothing was replaced."
            )
        if any(
            "submission_not_verified" in c["reasons"]
            or "target_not_in_both_snapshots" in c["reasons"]
            for c in changes
        ):
            raise GradebookError("A pending edit target is unavailable; refresh held.")
    merged = copy.deepcopy(current)
    display = copy.deepcopy(current)
    if changes:
        merged["working_baseline"] = {
            "previous_baseline_id": digest(baseline),
            "canvas_snapshot_id": digest(current),
            "retained_cells": [],
        }
        for change in changes:
            key = f"{change['user_id']}:{change['assignment_id']}"
            merged["cells"][key] = copy.deepcopy(baseline["cells"][key])
            merged["working_baseline"]["retained_cells"].append(key)
            display["cells"][key]["value"] = change["proposed"]
    return merged, display, review


def build_requests(
    current: dict[str, Any],
    working: dict[str, Any],
    baseline_id: str,
    binding: dict[str, Any],
    previous: dict[str, Any],
    pending: int,
) -> list[dict[str, Any]]:
    """Bounded, atomic Sheets batch: values, appearance, identity and protection."""
    count, columns = len(current["students"]), len(current["assignments"]) + 2
    if not count or columns < 3 or count > 995 or columns > 258:
        raise GradebookError("Workbook shape needs an explicit grid expansion.")
    last_row, last_col = count + 5, column_name(columns)
    clear_rows = max(last_row, len(previous["students"]) + 5)
    clear_cols = max(columns, len(previous["assignments"]) + 2)
    stamp = (
        datetime.fromisoformat(current["fetched_at"])
        .astimezone(ZoneInfo("America/New_York"))
        .strftime("%b %d, %Y %I:%M %p %Z")
    )
    requests: list[dict[str, Any]] = []
    base_format: dict[str, Any] = {
        "textFormat": {
            "fontFamily": "Arial",
            "fontSize": 11,
            "foregroundColor": rgb(COLORS["ink"]),
        },
        "verticalAlignment": "MIDDLE",
    }
    for title, snapshot in (("Canvas", current), ("Working", working)):
        sid = binding["sheets"][title]
        requests.append({
            "updateSheetProperties": {
                "properties": {"sheetId": sid, "gridProperties": {"columnCount": max(26, clear_cols)}},
                "fields": "gridProperties.columnCount",
            }
        })
        grid = {
            "sheetId": sid,
            "startRowIndex": 0,
            "endRowIndex": clear_rows,
            "startColumnIndex": 0,
            "endColumnIndex": clear_cols,
        }
        requests.append(
            {
                "repeatCell": {
                    "range": grid,
                    "cell": {"userEnteredFormat": base_format},
                    "fields": "userEnteredValue,userEnteredFormat,note,dataValidation",
                }
            }
        )
        rows: list[dict[str, Any]] = []
        for r in range(last_row):
            values: list[dict[str, Any]] = [cell(None) for _ in range(columns)]
            if r == 0:
                values[1] = cell(
                    f"{binding['label']} Chemistry — {title}",
                    {
                        "textFormat": {
                            "fontFamily": "Arial",
                            "fontSize": 16,
                            "foregroundColor": rgb(COLORS["blue"]),
                        }
                    },
                )
            elif r == 1:
                values[1] = cell(
                    (
                        "Canvas snapshot · read only"
                        if title == "Canvas"
                        else "Edit scores here · changes stay local"
                    ),
                    {"wrapStrategy": "WRAP"},
                )
                values[2] = cell(f"Refreshed {stamp}")
                if columns > 6:
                    values[6] = cell("Blue: late   Yellow: excused   Pink: missing")
            elif r in (2, 3, 4):
                values[1] = cell(
                    ["Student Name", "Points possible", "Assignment IDs"][r - 2]
                )
                if r == 4:
                    values[0] = cell("Canvas user ID")
                for c, assignment in enumerate(snapshot["assignments"], 2):
                    values[c] = cell(
                        assignment[["name", "points_possible", "id"][r - 2]],
                        {"horizontalAlignment": "CENTER", "wrapStrategy": "WRAP"},
                    )
            else:
                student = snapshot["students"][r - 5]
                values[0] = cell(student["id"])
                values[1] = cell(
                    student["name"] + "\n" + ", ".join(student["sections"]),
                    {
                        "textFormat": {
                            "fontFamily": "Arial",
                            "fontSize": 11,
                            "foregroundColor": rgb(COLORS["blue"]),
                        },
                        "wrapStrategy": "WRAP",
                    },
                )
                for c, assignment in enumerate(snapshot["assignments"], 2):
                    item = snapshot["cells"].get(
                        f"{student['id']}:{assignment['id']}", {}
                    )
                    shade = (
                        "excused"
                        if item.get("excused")
                        else (
                            "missing"
                            if item.get("missing")
                            else (
                                "late"
                                if item.get("late")
                                else "header" if (r - 5) % 2 else None
                            )
                        )
                    )
                    fmt: dict[str, Any] = {
                        "horizontalAlignment": "CENTER",
                    }
                    if shade:
                        fmt["backgroundColor"] = rgb(COLORS[shade])
                    value = item.get("value")
                    values[c] = cell("Excused" if value == "EX" else value, fmt)
                    values[c]["note"] = "\n".join(
                        f"{label}: {item.get(key) if item.get(key) is not None else 'Not recorded'}"
                        for label, key in (
                            ("Canvas status", "workflow_state"),
                            ("Attempt", "attempt"),
                            ("Submitted UTC", "submitted_at"),
                            ("Graded UTC", "graded_at"),
                            ("Late", "late"),
                            ("Missing", "missing"),
                            ("Excused", "excused"),
                            ("Grade matches current submission", "grade_matches_current_submission"),
                        )
                    )
            for value in values:
                custom = value.get("userEnteredFormat", {})
                value["userEnteredFormat"] = {
                    **base_format,
                    **custom,
                    "textFormat": {
                        **base_format["textFormat"],
                        **custom.get("textFormat", {}),
                    },
                }
            if r >= 5 and (r - 5) % 2:
                values[1]["userEnteredFormat"]["backgroundColor"] = rgb(
                    COLORS["header"]
                )
            rows.append({"values": values})
        requests.append(
            {
                "updateCells": {
                    "start": {"sheetId": sid},
                    "rows": rows,
                    "fields": "userEnteredValue,userEnteredFormat,note",
                }
            }
        )
        requests.extend(
            [
                {
                    "updateDimensionProperties": {
                        "range": {
                            "sheetId": sid,
                            "dimension": "ROWS",
                            "startIndex": 0,
                            "endIndex": last_row,
                        },
                        "properties": {"pixelSize": 48},
                        "fields": "pixelSize",
                    }
                },
                {
                    "updateDimensionProperties": {
                        "range": {
                            "sheetId": sid,
                            "dimension": "ROWS",
                            "startIndex": 2,
                            "endIndex": 3,
                        },
                        "properties": {"pixelSize": 88},
                        "fields": "pixelSize",
                    }
                },
                {
                    "repeatCell": {
                        "range": {
                            "sheetId": sid,
                            "startRowIndex": 2,
                            "endRowIndex": 4,
                            "startColumnIndex": 1,
                            "endColumnIndex": columns,
                        },
                        "cell": {
                            "userEnteredFormat": {
                                "backgroundColor": rgb(COLORS["header"]),
                                "textFormat": {
                                    "fontFamily": "Arial",
                                    "fontSize": 11,
                                    "bold": True,
                                },
                            }
                        },
                        "fields": "userEnteredFormat.backgroundColor,userEnteredFormat.textFormat",
                    }
                },
                {
                    "updateBorders": {
                        "range": {
                            "sheetId": sid,
                            "startRowIndex": 2,
                            "endRowIndex": last_row,
                            "startColumnIndex": 1,
                            "endColumnIndex": columns,
                        },
                        **{
                            k: {"style": "SOLID", "color": rgb(COLORS["line"])}
                            for k in (
                                "top",
                                "bottom",
                                "left",
                                "right",
                                "innerHorizontal",
                                "innerVertical",
                            )
                        },
                    }
                },
            ]
        )
    sid = binding["sheets"]["Working"]
    requests.append({
        "setDataValidation": {
            "range": {"sheetId": sid, "startRowIndex": 5, "endRowIndex": last_row,
                      "startColumnIndex": 2, "endColumnIndex": columns},
            "rule": {
                "condition": {"type": "CUSTOM_FORMULA", "values": [{
                    "userEnteredValue": '=OR(ISBLANK(C6),AND(ISNUMBER(C6),C6>=0),AND(ISTEXT(C6),REGEXMATCH(LOWER(TRIM(C6)),"^(ex|excused)$")))'
                }]},
                "strict": True,
                "inputMessage": "Enter literal points, EX, or blank. Preview before pushing; blank never clears Canvas.",
            },
        }
    })
    requests.append(
        {
            "updateProtectedRange": {
                "protectedRange": {
                    "protectedRangeId": binding["working_protection_id"],
                    "unprotectedRanges": [
                        {
                            "sheetId": sid,
                            "startRowIndex": 5,
                            "endRowIndex": last_row,
                            "startColumnIndex": 2,
                            "endColumnIndex": columns,
                        }
                    ],
                },
                "fields": "unprotectedRanges",
            }
        }
    )
    canvas_title = binding.get("tab_names", {}).get("Canvas", "Canvas")
    # Escape both A1 sheet-name quotes and the enclosing formula string.
    canvas_ref = ("'" + canvas_title.replace("'", "''") + "'!").replace('"', '""')
    original = (
        f"INDEX(INDIRECT(\"{canvas_ref}$C$6:${last_col}${last_row}\"),"
        f"MATCH($A6,INDIRECT(\"{canvas_ref}$A$6:$A${last_row}\"),0),"
        f"MATCH(C$5,INDIRECT(\"{canvas_ref}$C$5:${last_col}$5\"),0))"
    )
    requests.append(
        {
            "updateConditionalFormatRule": {
                "sheetId": sid,
                "index": 0,
                "rule": {
                    "ranges": [
                        {
                            "sheetId": sid,
                            "startRowIndex": 5,
                            "endRowIndex": last_row,
                            "startColumnIndex": 2,
                            "endColumnIndex": columns,
                        }
                    ],
                    "booleanRule": {
                        "condition": {
                            "type": "CUSTOM_FORMULA",
                            "values": [
                                {
                                    "userEnteredValue": f"=OR(ISBLANK(C6)<>ISBLANK({original}),C6<>{original})"
                                }
                            ],
                        },
                        "format": {
                            "backgroundColor": rgb(COLORS["edited"]),
                            "textFormat": {"bold": True},
                        },
                    },
                },
            }
        }
    )
    meta: list[list[Any]] = [
        ["Schema version", 1],
        ["Snapshot ID", baseline_id],
        ["Canvas course ID", current["course_id"]],
        ["Canvas origin", current["origin"]],
        ["Snapshot time", current["fetched_at"]],
        ["Scope", current["scope"]],
        ["Canvas writes", "Explicit reviewed push only; editing does not send"],
        ["Source", f"{current['origin']}/courses/{current['course_id']}/gradebook"],
        ["Canvas snapshot ID", digest(current)],
        ["Pending at refresh", pending],
    ]
    requests.append(
        {
            "updateCells": {
                "start": {"sheetId": binding["sheets"]["_Sync"]},
                "rows": [{"values": [cell(v) for v in row]} for row in meta],
                "fields": "userEnteredValue",
            }
        }
    )
    return requests


def source_digest(sheets: dict[str, dict[str, Any]]) -> str:
    """Ignore formatting-only empty cells, but cover every literal input value."""
    return digest(
        {
            tab: {a: v for a, v in cells.items() if v is not None}
            for tab, cells in sheets.items()
        }
    )


def verify_refresh_output(
    sheets: dict[str, dict[str, Any]],
    plan: dict[str, Any],
    current: dict[str, Any],
    baseline: dict[str, Any],
) -> None:
    from .workbook import edits_from_cells

    actual = edits_from_cells(sheets, baseline)
    if sorted(actual["edits"], key=digest) != sorted(plan["pending_edits"], key=digest):
        raise GradebookError(
            "Working readback differs; preserve both exports and reconcile."
        )
    canvas = copy.deepcopy(sheets)
    if "Canvas" not in canvas:
        raise GradebookError("Canvas tab is missing after refresh.")
    canvas["Working"] = canvas["Canvas"]
    canvas["_Sync"]["B2"] = digest(current)
    if edits_from_cells(canvas, current)["edits"]:
        raise GradebookError(
            "Canvas tab readback differs from the saved Canvas snapshot."
        )
    if sheets["_Sync"].get("B9") != digest(current):
        raise GradebookError("Canvas snapshot reference failed readback.")
