"""Validate and verify bounded native Sheets reads without any network calls.

Only literal cell maps leave this adapter. Native readback additionally checks
notes, validation, cell formatting except generated borders, dimensions,
protections, conditional rules, and preservation of every unrelated tab.
Reference tabs retain their complete selected native fields, including borders.
"""

from __future__ import annotations

import copy
import math
import re
from typing import Any, NoReturn, cast

from .client import GradebookError
from .model import digest
from .refresh import build_requests, source_digest, verify_refresh_output
from .workbook import column_name

ROLES = {"Canvas", "Working", "_Sync"}
CELL_FIELDS = {"userEnteredValue", "userEnteredFormat", "note", "dataValidation"}
MAX_NATIVE_CELLS = 500_000


def _fail(message: str) -> NoReturn:
    raise GradebookError(message)


def _clean(value: Any) -> Any:
    """Remove API-only defaults and metadata; retain meaningful native fields."""
    if isinstance(value, list):
        return [_clean(v) for v in value]
    if not isinstance(value, dict):
        if isinstance(value, float) and math.isfinite(value) and value.is_integer():
            return int(value)
        return value
    result = {}
    for key, item in value.items():
        if key in {"developerMetadata", "requestingUserCanEdit"}:
            continue
        item = _clean(item)
        if item == {} and key in {
            "backgroundColor",
            "foregroundColor",
            "color",
            "tabColor",
            "rgbColor",
        }:
            item = {"red": 0, "green": 0, "blue": 0}
        if item in ({}, [], None) or (key == "note" and item == ""):
            continue
        if (
            key
            in {
                "hidden",
                "hiddenByUser",
                "hiddenByFilter",
                "warningOnly",
                "bold",
                "italic",
                "strikethrough",
                "underline",
                "showCustomUi",
            }
            and item is False
        ):
            continue
        if key in {"frozenRowCount", "frozenColumnCount"} and item == 0:
            continue
        result[key] = item
    # Sheets may return both deprecated rgbColor fields and ColorStyle aliases.
    for name in ("backgroundColor", "foregroundColor", "color", "tabColor"):
        style = result.get(name + "Style", {})
        if isinstance(style, dict) and "rgbColor" in style:
            result[name] = style["rgbColor"]
            result.pop(name + "Style", None)
        if isinstance(result.get(name), dict):
            color = result[name]
            result[name] = {
                channel: round(float(color.get(channel, 0)), 5)
                for channel in ("red", "green", "blue")
            }
            if color.get("alpha", 1) != 1:
                result[name]["alpha"] = round(float(color["alpha"]), 5)
    if "sheetId" in result and any(
        k in result
        for k in ("startRowIndex", "endRowIndex", "startColumnIndex", "endColumnIndex")
    ):
        result.setdefault("startRowIndex", 0)
        result.setdefault("startColumnIndex", 0)
    return result


def _state(raw: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(raw, dict) or not isinstance(raw.get("spreadsheetId"), str):
        _fail("Native workbook identity is unavailable.")
    sheets = raw.get("sheets")
    if not isinstance(sheets, list) or not 1 <= len(sheets) <= 50:
        _fail("Native workbook sheet inventory is unavailable or exceeds the bound.")
    result: dict[str, Any] = {"spreadsheetId": raw["spreadsheetId"], "sheets": {}}
    count = 0
    titles: set[str] = set()
    for sheet in sheets:
        props = sheet.get("properties", {})
        sid, title = props.get("sheetId"), props.get("title")
        if (
            isinstance(sid, bool)
            or not isinstance(sid, int)
            or sid < 0
            or sid in result["sheets"]
        ):
            _fail("Native workbook contains invalid or duplicate sheet identities.")
        if not isinstance(title, str) or not title or title in titles:
            _fail("Native workbook contains invalid or duplicate sheet names.")
        titles.add(title)
        grid = props.get("gridProperties", {})
        if props.get("sheetType", "GRID") != "GRID" or any(
            isinstance(grid.get(k), bool)
            or not isinstance(grid.get(k), int)
            or grid[k] < 1
            for k in ("rowCount", "columnCount")
        ):
            _fail("Native workbook requires bounded grid sheets.")
        projected = {
            k: _clean(sheet.get(k, {} if k == "basicFilter" else []))
            for k in ("protectedRanges", "conditionalFormats", "basicFilter")
        }
        projected.update(
            properties=_clean(props), cells={}, rowMetadata={}, columnMetadata={}
        )
        projected["properties"].setdefault("sheetType", "GRID")
        for block in sheet.get("data", []):
            r0, c0 = block.get("startRow", 0), block.get("startColumn", 0)
            if not isinstance(r0, int) or not isinstance(c0, int) or min(r0, c0) < 0:
                _fail("Native workbook contains an invalid grid offset.")
            for r, row in enumerate(block.get("rowData", []), r0):
                if r >= grid["rowCount"]:
                    _fail("Native workbook data extends beyond its row capacity.")
                for c, cell in enumerate(row.get("values", []), c0):
                    count += 1
                    if c >= grid["columnCount"] or count > MAX_NATIVE_CELLS:
                        _fail("Native workbook data exceeds its supported bound.")
                    key = f"{r}:{c}"
                    item = _clean({k: cell[k] for k in CELL_FIELDS if k in cell})
                    if key in projected["cells"]:
                        _fail("Native workbook has overlapping cell ranges.")
                    if item:
                        projected["cells"][key] = item
            for name, offset, limit in (
                ("rowMetadata", r0, grid["rowCount"]),
                ("columnMetadata", c0, grid["columnCount"]),
            ):
                for i, metadata in enumerate(block.get(name, []), offset):
                    if i >= limit:
                        _fail("Native dimension metadata exceeds the grid.")
                    item = _clean(metadata)
                    if item:
                        if str(i) in projected[name]:
                            _fail("Native workbook has overlapping dimension metadata.")
                        projected[name][str(i)] = item
        projected["protectedRanges"].sort(key=lambda p: p.get("protectedRangeId", -1))
        result["sheets"][sid] = projected
    return result


def _literal_cells(sheet: dict[str, Any]) -> dict[str, Any]:
    result = {}
    for address, cell in sheet["cells"].items():
        value = cell.get("userEnteredValue", {})
        if "formulaValue" in value:
            _fail("Bound gradebook cells must contain literal values, not formulas.")
        if set(value) - {"numberValue", "stringValue", "boolValue"} or len(value) > 1:
            _fail("Bound gradebook contains an unsupported cell value.")
        if value:
            r, c = (int(v) for v in address.split(":"))
            result[f"{column_name(c + 1)}{r + 1}"] = next(iter(value.values()))
    return result


def _whole_sheet(protection: dict[str, Any], sid: int) -> bool:
    target = protection.get("range", {})
    return (
        target.get("sheetId") == sid
        and set(target) <= {"sheetId", "startRowIndex", "startColumnIndex"}
        and not target.get("startRowIndex", 0)
        and not target.get("startColumnIndex", 0)
        and not protection.get("warningOnly", False)
        and "namedRangeId" not in protection
    )


def _shape(cells: dict[str, Any]) -> tuple[int, int]:
    rows = [
        int(a[1:])
        for a, value in cells.items()
        if re.fullmatch(r"A[0-9]+", a) and int(a[1:]) >= 6 and value is not None
    ]
    columns = [
        a[:-1]
        for a, value in cells.items()
        if re.fullmatch(r"[A-Z]+5", a) and a not in ("A5", "B5") and value is not None
    ]
    if not rows or not columns or len(rows) > 995 or len(columns) > 256:
        _fail("Bound gradebook has an unsupported populated shape.")
    if sorted(rows) != list(range(6, 6 + len(rows))) or set(columns) != {
        column_name(i) for i in range(3, 3 + len(columns))
    }:
        _fail("Bound gradebook rows or assignment columns are not contiguous.")
    return len(rows) + 5, len(columns) + 2


def _rule(binding: dict[str, Any], last_row: int, columns: int) -> dict[str, Any]:
    """Obtain the owned highlight rule from the canonical request builder."""
    synthetic = {
        "students": [
            {"id": str(i + 1), "name": "", "sections": []} for i in range(last_row - 5)
        ],
        "assignments": [
            {"id": str(i + 1), "name": "", "points_possible": 0}
            for i in range(columns - 2)
        ],
        "cells": {},
        "fetched_at": "2026-01-01T00:00:00+00:00",
        "course_id": binding["course_id"],
        "origin": "https://example.invalid",
        "scope": "validation",
    }
    requests = build_requests(synthetic, synthetic, "validation", binding, synthetic, 0)
    return cast(
        dict[str, Any],
        _clean(
            next(
                r["updateConditionalFormatRule"]["rule"]
                for r in requests
                if "updateConditionalFormatRule" in r
            )
        ),
    )


def validate_workbook(
    raw: dict[str, Any], bindings: dict[str, Any]
) -> dict[str, dict[str, dict[str, Any]]]:
    state = _state(raw)
    if not isinstance(bindings, dict) or not 1 <= len(bindings) <= 10:
        _fail("Native workbook requires a bounded configured course inventory.")
    result = {}
    claimed: set[int] = set()
    for course, binding in bindings.items():
        if (
            binding.get("spreadsheet_id") != state["spreadsheetId"]
            or set(binding.get("sheets", {})) != ROLES
            or set(binding.get("tab_names", {})) != ROLES
        ):
            _fail("Native workbook does not match the configured binding.")
        mapped = {}
        for role in sorted(ROLES):
            sid = binding["sheets"][role]
            sheet = state["sheets"].get(sid)
            if (
                sid in claimed
                or sheet is None
                or sheet["properties"]["title"] != binding["tab_names"][role]
            ):
                _fail("A configured gradebook sheet identity or name changed.")
            claimed.add(sid)
            mapped[role] = _literal_cells(sheet)
            if role == "_Sync":
                if not sheet["properties"].get("hidden", False):
                    _fail("The gradebook metadata sheet is no longer hidden.")
            else:
                grid = sheet["properties"]["gridProperties"]
                if (
                    grid.get("frozenRowCount", 0) != 5
                    or grid.get("frozenColumnCount", 0) != 2
                ):
                    _fail("Gradebook frozen identity headers changed.")
                if not sheet["rowMetadata"].get("4", {}).get(
                    "hiddenByUser", False
                ) or not sheet["columnMetadata"].get("0", {}).get(
                    "hiddenByUser", False
                ):
                    _fail("Gradebook identity row or column is no longer hidden.")
            if role in {"Canvas", "_Sync"} and not any(
                _whole_sheet(p, sid) and not p.get("unprotectedRanges")
                for p in sheet["protectedRanges"]
            ):
                _fail(
                    "A protected mirror or metadata sheet is no longer fully protected."
                )
        last_row, columns = _shape(mapped["Working"])
        if _shape(mapped["Canvas"]) != (last_row, columns):
            _fail("Mirror and Edit grids have different populated shapes.")
        edit = state["sheets"][binding["sheets"]["Working"]]
        sid = binding["sheets"]["Working"]
        protection = [
            p
            for p in edit["protectedRanges"]
            if p.get("protectedRangeId") == binding.get("working_protection_id")
        ]
        expected_range = {
            "sheetId": sid,
            "startRowIndex": 5,
            "endRowIndex": last_row,
            "startColumnIndex": 2,
            "endColumnIndex": columns,
        }
        if (
            len(protection) != 1
            or not _whole_sheet(protection[0], sid)
            or protection[0].get("unprotectedRanges") != [expected_range]
        ):
            _fail("The Edit protection or editable score rectangle changed.")
        if not edit["conditionalFormats"] or edit["conditionalFormats"][0] != _rule(
            binding, last_row, columns
        ):
            _fail("The owned Edit comparison highlight rule changed.")
        for role in ("Canvas", "Working"):
            sheet = state["sheets"][binding["sheets"][role]]
            grid = sheet["properties"]["gridProperties"]
            if grid["rowCount"] < last_row or grid["columnCount"] < columns:
                _fail("A gradebook sheet has insufficient grid capacity.")
            for address, item in sheet["cells"].items():
                r, c = map(int, address.split(":"))
                if (r >= last_row or c >= columns) and any(
                    k in item for k in ("userEnteredValue", "note")
                ):
                    _fail("Data or notes exist outside the owned gradebook grid.")
        result[course] = mapped
    return result


def fingerprint(raw: dict[str, Any]) -> str:
    """Include all selected native fields; request queue metadata is excluded."""
    return digest(_state(raw))


def _masked(target: dict[str, Any], source: dict[str, Any], fields: str) -> None:
    for field in fields.split(","):
        parts = field.split(".")
        dest, src = target, source
        for part in parts[:-1]:
            dest = dest.setdefault(part, {})
            src = src.get(part, {})
        if parts[-1] in src:
            dest[parts[-1]] = copy.deepcopy(src[parts[-1]])
        else:
            dest.pop(parts[-1], None)


def _range(
    state: dict[str, Any], value: dict[str, Any], allowed: set[int]
) -> tuple[dict[str, Any], range, range]:
    sid = value.get("sheetId")
    if sid not in allowed:
        _fail("Refresh request targets a sheet outside its binding.")
    sheet = state["sheets"][sid]
    grid = sheet["properties"]["gridProperties"]
    r0, c0 = value.get("startRowIndex", 0), value.get("startColumnIndex", 0)
    r1, c1 = value.get("endRowIndex", grid["rowCount"]), value.get(
        "endColumnIndex", grid["columnCount"]
    )
    if not (0 <= r0 <= r1 <= grid["rowCount"] and 0 <= c0 <= c1 <= grid["columnCount"]):
        _fail("Refresh request exceeds the existing grid capacity.")
    return sheet, range(r0, r1), range(c0, c1)


def _apply_requests(
    state: dict[str, Any], requests: list[dict[str, Any]], binding: dict[str, Any]
) -> None:
    """Project only the existing canonical builder's explicitly allowed writes."""
    allowed = set(binding["sheets"].values())
    for request in requests:
        if len(request) != 1:
            _fail("Refresh contains an invalid request.")
        kind, data = next(iter(request.items()))
        if kind == "updateSheetProperties":
            props = data["properties"]
            sid = props["sheetId"]
            if sid not in allowed or data["fields"] != "gridProperties.columnCount":
                _fail("Refresh attempts an unsupported sheet property change.")
            current = state["sheets"][sid]["properties"]
            if (
                props["gridProperties"]["columnCount"]
                < current["gridProperties"]["columnCount"]
            ):
                _fail("Automatic refresh must not shrink existing columns.")
            _masked(current, props, data["fields"])
        elif kind in {"repeatCell", "setDataValidation"}:
            sheet, rows, cols = _range(state, data["range"], allowed)
            fields = data.get("fields", "dataValidation")
            if any(f.split(".")[0] not in CELL_FIELDS for f in fields.split(",")):
                _fail("Refresh attempts an unsupported cell-field change.")
            source = data.get("cell", {"dataValidation": data.get("rule", {})})
            for r in rows:
                for c in cols:
                    _masked(sheet["cells"].setdefault(f"{r}:{c}", {}), source, fields)
        elif kind == "updateCells":
            start = data["start"]
            if start["sheetId"] not in allowed:
                _fail("Refresh cell update targets another sheet.")
            sheet = state["sheets"][start["sheetId"]]
            fields = data["fields"]
            if any(f.split(".")[0] not in CELL_FIELDS for f in fields.split(",")):
                _fail("Refresh attempts an unsupported cell-field change.")
            for r, row in enumerate(data["rows"], start.get("rowIndex", 0)):
                for c, item in enumerate(
                    row.get("values", []), start.get("columnIndex", 0)
                ):
                    _range(
                        state,
                        {
                            "sheetId": start["sheetId"],
                            "startRowIndex": r,
                            "endRowIndex": r + 1,
                            "startColumnIndex": c,
                            "endColumnIndex": c + 1,
                        },
                        allowed,
                    )
                    _masked(sheet["cells"].setdefault(f"{r}:{c}", {}), item, fields)
        elif kind == "updateDimensionProperties":
            target = data["range"]
            if (
                target["sheetId"] not in allowed
                or data["fields"] != "pixelSize"
                or target["dimension"] not in {"ROWS", "COLUMNS"}
            ):
                _fail("Refresh attempts an unsupported dimension change.")
            sheet = state["sheets"][target["sheetId"]]
            key = "rowMetadata" if target["dimension"] == "ROWS" else "columnMetadata"
            limit = sheet["properties"]["gridProperties"][
                "rowCount" if key == "rowMetadata" else "columnCount"
            ]
            if not 0 <= target.get("startIndex", 0) <= target["endIndex"] <= limit:
                _fail("Refresh dimension change exceeds the grid.")
            for i in range(target.get("startIndex", 0), target["endIndex"]):
                _masked(
                    sheet[key].setdefault(str(i), {}), data["properties"], "pixelSize"
                )
        elif kind == "updateProtectedRange":
            value = data["protectedRange"]
            if (
                data["fields"] != "unprotectedRanges"
                or value["protectedRangeId"] != binding["working_protection_id"]
            ):
                _fail("Refresh attempts an unsupported protection change.")
            protections = state["sheets"][binding["sheets"]["Working"]][
                "protectedRanges"
            ]
            matches = [
                p
                for p in protections
                if p.get("protectedRangeId") == value["protectedRangeId"]
            ]
            if len(matches) != 1:
                _fail("Refresh protection target is unavailable.")
            _masked(matches[0], value, data["fields"])
        elif kind == "updateConditionalFormatRule":
            if data["sheetId"] != binding["sheets"]["Working"] or data["index"] != 0:
                _fail("Refresh attempts an unowned conditional-rule change.")
            state["sheets"][data["sheetId"]]["conditionalFormats"][0] = copy.deepcopy(
                data["rule"]
            )
        elif kind == "updateBorders":
            _range(state, data["range"], allowed)
            # Google may expose a shared border on either neighboring cell.
            # Border placement is excluded only on the connector-owned tabs.
        else:
            _fail("Refresh contains an unsupported Sheets operation.")


def _comparable(state: dict[str, Any], owned: set[int]) -> dict[str, Any]:
    result = copy.deepcopy(state)
    for sid, sheet in result["sheets"].items():
        for address in list(sheet["cells"]):
            item = sheet["cells"][address]
            if sid in owned:
                item.get("userEnteredFormat", {}).pop("borders", None)
            item = _clean(item)
            if item:
                sheet["cells"][address] = item
            else:
                del sheet["cells"][address]
    return cast(dict[str, Any], _clean(result))


def verify_native_output(
    before: dict[str, Any],
    after: dict[str, Any],
    plans: Any,
    store: Any,
    bindings: dict[str, Any],
) -> None:
    """Verify both canonical values and selected native structure after a batch."""
    before_cells = validate_workbook(before, bindings)
    cells = validate_workbook(after, bindings)
    expected = _state(before)
    iterable = list(plans.values()) if isinstance(plans, dict) else list(plans)
    if len(iterable) != len(bindings) or {p.get("course") for p in iterable} != set(
        bindings
    ):
        _fail(
            "Native verification requires exactly one plan for every configured course."
        )
    for plan in iterable:
        binding = bindings[plan["course"]]
        if (
            plan.get("binding_digest") != digest(binding)
            or plan["batch_update"]["spreadsheet_id"] != before["spreadsheetId"]
        ):
            _fail("Refresh binding changed before native verification.")
        if plan.get("input_digest") != source_digest(before_cells[plan["course"]]):
            _fail("Refresh plan does not match the preserved native input.")
        verify_refresh_output(
            cells[plan["course"]],
            plan,
            store.load("snapshot", plan["canvas_snapshot_id"]),
            store.load("snapshot", plan["baseline_id"]),
        )
        _apply_requests(expected, plan["batch_update"]["requests"], binding)
    owned = {sid for binding in bindings.values() for sid in binding["sheets"].values()}
    if _comparable(expected, owned) != _comparable(_state(after), owned):
        _fail(
            "Native refresh readback differs; preserve evidence and do not retry writes."
        )
