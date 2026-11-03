"""Pure predecessor note-plan comparator for fictional migration regressions.

Retains the historical algorithm used by compatibility assertions, without its
operator execution, transport, lock, authority-window, or credential plumbing.
"""

from __future__ import annotations

import copy
import hashlib
import json
import math
import os
import re
import stat
from pathlib import Path
from typing import Any

MAX_BYTES = 128 * 1024 * 1024


def need(value: object, code: str) -> None:
    if not value:
        raise ValueError(code)


def canonical(value: Any) -> str:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False
    )


def exact(a: Any, b: Any) -> bool:
    return canonical(a) == canonical(b)


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def read(ref: dict[str, Any]) -> bytes:
    need(
        type(ref) is dict
        and {"path", "sha256"} <= set(ref) <= {"path", "sha256", "bytes"}
        and type(ref["path"]) is str
        and type(ref["sha256"]) is str
        and re.fullmatch(r"[a-f0-9]{64}", ref["sha256"]) is not None,
        "COPY_FILE_PIN_REQUIRED",
    )
    p = Path(ref["path"])
    need(
        p.is_absolute()
        and ".." not in p.parts
        and not any(x.is_symlink() for x in (p, *p.parents)),
        "COPY_DIRECT_FILE_REQUIRED",
    )
    if "bytes" in ref:
        need(
            type(ref["bytes"]) is int and 0 <= ref["bytes"] <= MAX_BYTES,
            "COPY_PIN_SIZE_REQUIRED",
        )
    with os.fdopen(
        os.open(p, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK), "rb"
    ) as stream:
        a = os.fstat(stream.fileno())
        need(
            stat.S_ISREG(a.st_mode)
            and a.st_uid == os.getuid()
            and 0 <= a.st_size <= MAX_BYTES,
            "COPY_OWNED_REGULAR_FILE_REQUIRED",
        )
        raw = stream.read(MAX_BYTES + 1)
        b = os.fstat(stream.fileno())

    def key(s: os.stat_result) -> tuple[int, ...]:
        return (
            s.st_dev,
            s.st_ino,
            s.st_uid,
            s.st_mode,
            s.st_nlink,
            s.st_size,
            s.st_mtime_ns,
            s.st_ctime_ns,
        )

    need(
        key(a) == key(b) == key(p.lstat())
        and len(raw) == a.st_size
        and sha(raw) == ref["sha256"]
        and len(raw) == ref.get("bytes", len(raw)),
        "COPY_PIN_CHANGED",
    )
    return raw


def identifier(value: Any) -> str | None:
    if type(value) is str and re.fullmatch(r"[1-9][0-9]*", value):
        return value
    if (
        type(value) in (int, float)
        and math.isfinite(value)
        and value > 0
        and value == int(value)
    ):
        return str(int(value))
    return None


def grid(sheet: dict[str, Any]) -> dict[tuple[int, int], dict[str, Any]]:
    result = {}
    for block in sheet.get("data", []):
        r0, c0 = block.get("startRow", 0), block.get("startColumn", 0)
        need(
            type(r0) is int and type(c0) is int and min(r0, c0) >= 0,
            "COPY_GRID_OFFSETS_REQUIRED",
        )
        for ri, row in enumerate(block.get("rowData", [])):
            for ci, cell in enumerate(row.get("values", [])):
                key = r0 + ri, c0 + ci
                need(
                    key not in result and type(cell) is dict,
                    "COPY_UNIQUE_RAW_CELLS_REQUIRED",
                )
                result[key] = cell
    return result


def literal(value: dict[str, Any]) -> str | int | float:
    need(
        type(value) is dict
        and len(value) == 1
        and set(value) <= {"stringValue", "numberValue"},
        "COPY_LITERAL_IDENTITY_REQUIRED",
    )
    scalar = next(iter(value.values()))
    need(
        type(scalar) is str
        and bool(scalar.strip())
        or type(scalar) in (int, float)
        and math.isfinite(scalar),
        "COPY_NONEMPTY_LITERAL_IDENTITY_REQUIRED",
    )
    return scalar


def compile_copy(
    manifest: dict[str, Any],
    raw: dict[str, Any],
    bindings: dict[str, Any],
    *,
    workbook_id: str,
    origin: str,
    verify_pins: bool = True,
) -> dict[str, Any]:
    """Pure literal body/address/manual-preservation composition; no admission."""
    need(
        type(manifest) is dict
        and type(manifest.get("candidates")) is list
        and 0 < len(manifest["candidates"]) <= 10000,
        "COPY_NONEMPTY_CANDIDATES_REQUIRED",
    )
    need(raw.get("spreadsheetId") == workbook_id, "COPY_WORKBOOK_CHANGED")
    sheets = {}
    for sheet in raw["sheets"]:
        sid = sheet["properties"]["sheetId"]
        need(type(sid) is int and sid not in sheets, "COPY_UNIQUE_SHEET_REQUIRED")
        sheets[sid] = sheet
    allowed = {b["sheets"]["Working"]: b for b in bindings.values()}
    after = copy.deepcopy(raw)
    after_sheets = {s["properties"]["sheetId"]: s for s in after["sheets"]}
    cached_grids, after_grids, seen, requests, checked = {}, {}, set(), [], set()
    noops = 0
    for item in manifest["candidates"]:
        need(type(item) is dict, "COPY_LITERAL_CANDIDATE_REQUIRED")
        loc, target = item["location"], item["target"]
        need(
            type(loc) is dict
            and set(loc) == {"sheetId", "rowIndex", "columnIndex"}
            and all(type(v) is int and v >= 0 for v in loc.values()),
            "COPY_EXACT_LOCATION_REQUIRED",
        )
        sid, row, col = (loc[k] for k in ("sheetId", "rowIndex", "columnIndex"))
        address = sid, row, col
        need(
            address not in seen and sid in allowed and sid in sheets,
            "COPY_UNIQUE_EDIT_DESTINATION_REQUIRED",
        )
        seen.add(address)
        binding = allowed[sid]
        need(
            binding["spreadsheet_id"] == workbook_id
            and target["origin"] == origin
            and identifier(target["course_id"]) == identifier(binding["course_id"])
            and identifier(target["user_id"]) is not None
            and identifier(target["assignment_id"]) is not None
            and sheets[sid]["properties"]["title"] == binding["tab_names"]["Working"],
            "COPY_REGISTERED_EDIT_TARGET_REQUIRED",
        )
        if sid not in cached_grids:
            cached_grids[sid], after_grids[sid] = (
                grid(sheets[sid]),
                grid(after_sheets[sid]),
            )
        cells = cached_grids[sid]
        need(
            (row, col) in cells and exact(cells[row, col], item["before_cell"]),
            "COPY_ENTIRE_TARGET_PREIMAGE_CHANGED",
        )
        old = item["before_note"]
        need(
            type(old) is str and cells[row, col].get("note", "") == old,
            "COPY_NOTE_PREIMAGE_CHANGED",
        )
        body, updated = item["body"], item["after_note"]
        need(
            type(body) is str
            and bool(body)
            and type(updated) is str
            and sha(body.encode()) == item["body_sha256"]
            and updated.count(body) == 1,
            "COPY_EXACT_BODY_REQUIRED",
        )
        preservation = item["preservation"]
        if (
            item.get("copy_boundary_kind")
            == "PRESERVE_ALL_OLD_NOTE_APPEND_CURRENT_BODY"
        ):
            need(
                exact(preservation, {"prefix": old, "old_body": "", "suffix": ""})
                and old.count(body) == 0
                and updated
                == old
                + "\n\n[UNIT2 CLEANED FEEDBACK BEGIN]\n"
                + body
                + "\n[UNIT2 CLEANED FEEDBACK END]\n",
                "COPY_MANUAL_BYTES_CHANGED",
            )
        else:
            need(
                type(preservation) is dict
                and set(preservation) == {"prefix", "old_body", "suffix"}
                and all(type(v) is str for v in preservation.values())
                and old
                == preservation["prefix"]
                + preservation["old_body"]
                + preservation["suffix"]
                and updated == preservation["prefix"] + body + preservation["suffix"],
                "COPY_MANUAL_BYTES_CHANGED",
            )
        identity = item["identity_binding"]
        row_keys, column_keys = identity["row_keys"], identity["column_keys"]
        need(
            type(row_keys) is list
            and type(column_keys) is list
            and row_keys
            and column_keys
            and all(
                type(x) is dict
                and set(x) == {"column_index", "userEnteredValue"}
                and type(x["column_index"]) is int
                and x["column_index"] >= 0
                for x in row_keys
            )
            and all(
                type(x) is dict
                and set(x) == {"row_index", "userEnteredValue"}
                and type(x["row_index"]) is int
                and x["row_index"] >= 0
                for x in column_keys
            )
            and len({x["column_index"] for x in row_keys}) == len(row_keys)
            and len({x["row_index"] for x in column_keys}) == len(column_keys),
            "COPY_LITERAL_JOIN_AXES_REQUIRED",
        )
        for axis in [*row_keys, *column_keys]:
            literal(axis["userEnteredValue"])
        need(
            any(
                identifier(literal(x["userEnteredValue"]))
                == identifier(target["user_id"])
                for x in row_keys
            )
            and any(
                identifier(literal(x["userEnteredValue"]))
                == identifier(target["assignment_id"])
                for x in column_keys
            ),
            "COPY_TARGET_IDS_MUST_MATCH_JOIN_AXES",
        )
        rows = {r for r, _ in cells}
        cols = {c for _, c in cells}
        row_matches = [
            r
            for r in rows
            if all(
                exact(
                    cells.get((r, x["column_index"]), {}).get("userEnteredValue", {}),
                    x["userEnteredValue"],
                )
                for x in row_keys
            )
        ]
        col_matches = [
            c
            for c in cols
            if all(
                exact(
                    cells.get((x["row_index"], c), {}).get("userEnteredValue", {}),
                    x["userEnteredValue"],
                )
                for x in column_keys
            )
        ]
        need(
            row_matches == [row] and col_matches == [col],
            "COPY_CURRENT_IDENTITY_JOIN_NOT_UNIQUE",
        )
        if verify_pins:
            refs = [
                item["body_ref"],
                item["source_record_ref"],
                item["capture_ref"],
                *item["pins"],
            ]
            for ref in refs:
                key = canonical(ref)
                if key not in checked:
                    read(ref)
                    checked.add(key)
            need(read(item["body_ref"]) == body.encode(), "COPY_BODY_FILE_CHANGED")
        if updated == old:
            noops += 1
            continue
        after_grids[sid][row, col]["note"] = updated
        requests.append(
            {
                "updateCells": {
                    "range": {
                        "sheetId": sid,
                        "startRowIndex": row,
                        "endRowIndex": row + 1,
                        "startColumnIndex": col,
                        "endColumnIndex": col + 1,
                    },
                    "rows": [{"values": [{"note": updated}]}],
                    "fields": "note",
                }
            }
        )
    if "requests" in manifest:
        need(exact(manifest["requests"], requests), "COPY_MANIFEST_REQUESTS_CHANGED")
    return {
        "requests": requests,
        "after_raw": after,
        "candidate_count": len(seen),
        "note_change_count": len(requests),
        "already_present_count": noops,
        "body_pins_verified": verify_pins,
        "canvas_writes": 0,
        "numeric_writes": 0,
    }
