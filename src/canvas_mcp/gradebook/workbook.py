"""Read a downloaded Working tab into a keyed edit proposal, never formulas."""

from __future__ import annotations

import posixpath
import re
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any
from zipfile import BadZipFile, ZipFile

from .client import GradebookError
from .model import digest, grade_value

NS = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"


def column_name(index: int) -> str:
    value = ""
    while index:
        index, remainder = divmod(index - 1, 26)
        value = chr(65 + remainder) + value
    return value


def read_workbook_cells(
    path: Path, tab_names: dict[str, str] | None = None
) -> dict[str, dict[str, Any]]:
    """Read only literal cells from the three connector-owned sheets."""
    names = tab_names if tab_names is not None else {
        key: key for key in ("Canvas", "Working", "_Sync")
    }
    if (
        set(names) != {"Canvas", "Working", "_Sync"}
        or any(not isinstance(v, str) or not v.strip() for v in names.values())
        or len(set(names.values())) != 3
    ):
        raise GradebookError("Invalid gradebook tab binding.")
    roles = {name: role for role, name in names.items()}
    try:
        with ZipFile(path) as archive:
            if sum(i.file_size for i in archive.infolist()) > 50_000_000:
                raise GradebookError("Workbook exceeds the supported size.")
            strings = []
            if "xl/sharedStrings.xml" in archive.namelist():
                for item in ET.fromstring(archive.read("xl/sharedStrings.xml")):
                    strings.append("".join(item.itertext()))
            relationships = {
                r.attrib["Id"]: r.attrib["Target"]
                for r in ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
                if r.attrib.get("TargetMode") != "External"
            }
            sheets: dict[str, dict[str, Any]] = {}
            for sheet in ET.fromstring(archive.read("xl/workbook.xml")).findall(
                "m:sheets/m:sheet", NS
            ):
                name = sheet.attrib["name"]
                if name not in roles:
                    continue
                name = roles[name]
                if name in sheets:
                    raise GradebookError("Duplicate gradebook tab name.")
                target = relationships[sheet.attrib[f"{{{REL}}}id"]]
                filename = posixpath.normpath(
                    target.lstrip("/") if target.startswith("/") else "xl/" + target
                )
                if not filename.startswith("xl/worksheets/") or ".." in filename:
                    raise GradebookError(
                        "Workbook has an invalid worksheet relationship."
                    )
                cells: dict[str, Any] = {}
                for cell in ET.fromstring(archive.read(filename)).findall(
                    ".//m:sheetData/m:row/m:c", NS
                ):
                    address = cell.attrib["r"]
                    if address in cells:
                        raise GradebookError("Duplicate workbook cell address.")
                    if cell.find("m:f", NS) is not None:
                        raise GradebookError(
                            "Working and metadata cells must contain values, not formulas."
                        )
                    kind = cell.attrib.get("t")
                    raw = cell.findtext("m:v", default="", namespaces=NS)
                    if kind == "s":
                        value: Any = strings[int(raw)]
                    elif kind == "inlineStr":
                        value = "".join(cell.find("m:is", NS).itertext())  # type: ignore[union-attr]
                    elif kind in ("str", "e"):
                        value = raw
                    elif kind == "b":
                        value = raw == "1"
                    else:
                        value = float(raw) if raw else None
                        if isinstance(value, float) and value.is_integer():
                            value = int(value)
                    cells[address] = value
                sheets[name] = cells
    except (
        BadZipFile,
        KeyError,
        IndexError,
        ValueError,
        ET.ParseError,
        OSError,
    ) as exc:
        raise GradebookError(
            "Workbook is invalid or does not match the gradebook template."
        ) from exc
    return sheets


def read_workbook_edits(
    path: Path, baseline: dict[str, Any], tab_names: dict[str, str] | None = None
) -> dict[str, Any]:
    """Validate the downloaded schema against an immutable local baseline.

    Protection is a convenience, not a trust boundary. Sorting complete rows
    is supported because IDs travel with the labels and grades.
    """
    return edits_from_cells(read_workbook_cells(path, tab_names), baseline)


def edits_from_cells(
    sheets: dict[str, dict[str, Any]], baseline: dict[str, Any]
) -> dict[str, Any]:
    if not {"Working", "_Sync"}.issubset(sheets):
        raise GradebookError("Workbook requires Working and _Sync tabs.")
    meta, working = sheets["_Sync"], sheets["Working"]
    if (
        str(meta.get("B1")),
        str(meta.get("B2")),
        str(meta.get("B3")),
        meta.get("B4"),
    ) != ("1", digest(baseline), baseline["course_id"], baseline["origin"]):
        raise GradebookError("Workbook does not belong to this course and baseline.")
    expected_assignments = {a["id"] for a in baseline["assignments"]}
    columns: dict[str, str] = {}
    for address, value in working.items():
        match = re.fullmatch(r"([A-Z]+)5", address)
        if match and match[1] not in ("A", "B") and value is not None:
            aid = str(value)
            if aid in columns.values() or aid not in expected_assignments:
                raise GradebookError("Assignment headers changed or duplicated.")
            columns[match[1]] = aid
    if set(columns.values()) != expected_assignments:
        raise GradebookError("Workbook assignment headers are incomplete.")
    for address, value in working.items():
        match = re.fullmatch(r"([A-Z]+)([0-9]+)", address)
        if value is not None and match and int(match[2]) >= 6:
            if match[1] not in {"A", "B", *columns}:
                raise GradebookError("Data appears outside the verified grade columns.")
    students = {s["id"]: s for s in baseline["students"]}
    seen = set()
    edits = []
    row_numbers = sorted(
        {
            int(m.group(1))
            for address, value in working.items()
            if value is not None
            and (m := re.fullmatch(r"[A-Z]+([0-9]+)", address))
            and int(m.group(1)) >= 6
        }
    )
    for row in row_numbers:
        uid = str(working.get(f"A{row}", ""))
        if uid not in students or uid in seen:
            raise GradebookError("Student IDs changed, duplicated, or were removed.")
        seen.add(uid)
        expected_label = (
            students[uid]["name"] + "\n" + ", ".join(students[uid]["sections"])
        )
        actual_label = str(working.get(f"B{row}", ""))
        if actual_label not in (expected_label, "'" + expected_label):
            raise GradebookError(
                "Student label and ID no longer match; restore the complete row."
            )
        for column, aid in columns.items():
            value = grade_value(working.get(f"{column}{row}"))
            if value != baseline["cells"].get(f"{uid}:{aid}", {}).get("value"):
                edits.append({"user_id": uid, "assignment_id": aid, "value": value})
    if seen != set(students):
        raise GradebookError("Workbook roster is incomplete.")
    return {
        "course_id": baseline["course_id"],
        "snapshot_id": digest(baseline),
        "edits": edits,
    }
