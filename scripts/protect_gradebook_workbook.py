"""Add XLSX protection/hidden metadata not exposed by the artifact renderer.

Only sheet metadata and cell lock styles are changed; values are untouched.
This is an accidental-edit safeguard, not a security boundary against owners.
"""

from __future__ import annotations

import copy
import os
import re
import sys
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
ET.register_namespace("", NS)


def protect(path: Path) -> None:
    with ZipFile(path) as source:
        payloads = {
            info.filename: source.read(info.filename) for info in source.infolist()
        }
    styles = ET.fromstring(payloads["xl/styles.xml"])
    xfs = styles.find(f"{{{NS}}}cellXfs")
    assert xfs is not None
    unlocked: dict[str, str] = {}
    for index in (1, 2, 3):
        name = f"xl/worksheets/sheet{index}.xml"
        sheet = ET.fromstring(payloads[name])
        if index in (1, 2):
            cols = sheet.find(f"{{{NS}}}cols")
            assert cols is not None
            for col in cols:
                if col.attrib.get("min") == "1":
                    # Builder writes column A as its own dimension range.
                    assert col.attrib.get("max") == "1"
                    col.set("hidden", "1")
            for row in sheet.findall(f"{{{NS}}}sheetData/{{{NS}}}row"):
                if row.attrib["r"] == "5":
                    row.set("hidden", "1")
            if index == 2:
                for cell in sheet.findall(f"{{{NS}}}sheetData/{{{NS}}}row/{{{NS}}}c"):
                    match = re.fullmatch(r"([A-Z]+)([0-9]+)", cell.attrib["r"])
                    if match and match[1] not in ("A", "B") and int(match[2]) >= 6:
                        old = cell.attrib.get("s", "0")
                        if old not in unlocked:
                            style = copy.deepcopy(xfs[int(old)])
                            for existing in list(style.findall(f"{{{NS}}}protection")):
                                style.remove(existing)
                            style.set("applyProtection", "1")
                            ET.SubElement(style, f"{{{NS}}}protection", locked="0")
                            unlocked[old] = str(len(xfs))
                            xfs.append(style)
                        cell.set("s", unlocked[old])
        data = sheet.find(f"{{{NS}}}sheetData")
        assert data is not None
        old_protection = sheet.find(f"{{{NS}}}sheetProtection")
        if old_protection is not None:
            sheet.remove(old_protection)
        sheet.insert(
            list(sheet).index(data) + 1,
            ET.Element(
                f"{{{NS}}}sheetProtection",
                {
                    "sheet": "1",
                    "objects": "1",
                    "scenarios": "1",
                    "selectLockedCells": "0",
                    "selectUnlockedCells": "0",
                },
            ),
        )
        payloads[name] = ET.tostring(sheet, encoding="utf-8", xml_declaration=True)
    xfs.set("count", str(len(xfs)))
    payloads["xl/styles.xml"] = ET.tostring(
        styles, encoding="utf-8", xml_declaration=True
    )
    workbook = ET.fromstring(payloads["xl/workbook.xml"])
    for sheet in workbook.findall(f"{{{NS}}}sheets/{{{NS}}}sheet"):
        if sheet.attrib["name"] == "_Sync":
            sheet.set("state", "hidden")
    payloads["xl/workbook.xml"] = ET.tostring(
        workbook, encoding="utf-8", xml_declaration=True
    )
    fd, temporary = tempfile.mkstemp(dir=path.parent, suffix=".xlsx")
    os.close(fd)
    try:
        with ZipFile(temporary, "w", compression=ZIP_DEFLATED) as target:
            for name, data in payloads.items():
                target.writestr(name, data)
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


if __name__ == "__main__":
    for filename in sys.argv[1:]:
        protect(Path(filename))
        print("Protected workbook metadata and preserved grade values.")
