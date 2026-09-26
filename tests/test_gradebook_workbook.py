"""Workbook identity, edit parsing, and connection installation regressions."""

import importlib.util
from pathlib import Path
from zipfile import ZipFile

import pytest

from canvas_mcp.gradebook.client import GradebookError
from canvas_mcp.gradebook.model import digest
from canvas_mcp.gradebook.workbook import read_workbook_edits


@pytest.fixture
def baseline():
    return {
        "origin": "https://school.example",
        "course_id": "12",
        "students": [
            {"id": "101", "name": "Example One", "sections": ["A1"]},
            {"id": "102", "name": "Example Two", "sections": ["B1"]},
        ],
        "assignments": [{"id": "21"}],
        "cells": {"101:21": {"value": 10}, "102:21": {"value": "EX"}},
    }


def workbook(tmp_path, baseline, working=None, tab_names=None):
    from xml.etree.ElementTree import Element, SubElement, tostring

    ns = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"

    def sheet(cells):
        root = Element("worksheet", xmlns=ns)
        data = SubElement(root, "sheetData")
        row = SubElement(data, "row")
        for address, value in cells.items():
            cell = SubElement(row, "c", r=address, t="inlineStr")
            if isinstance(value, tuple):
                SubElement(cell, "f").text = value[0]
            else:
                SubElement(SubElement(cell, "is"), "t").text = str(value)
        return tostring(root)

    working = working or {
        "C5": "21",
        "A6": "101",
        "B6": "Example One\nA1",
        "C6": "10",
        "A7": "102",
        "B7": "Example Two\nB1",
        "C7": "Excused",
    }
    meta = {"B1": 1, "B2": digest(baseline), "B3": "12", "B4": baseline["origin"]}
    tab_names = tab_names or {"Working": "Working", "_Sync": "_Sync"}
    output = tmp_path / "edits.xlsx"
    with ZipFile(output, "w") as archive:
        archive.writestr(
            "xl/workbook.xml",
            f'<workbook xmlns="{ns}" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets><sheet name="{tab_names["Working"]}" r:id="r1"/><sheet name="{tab_names["_Sync"]}" r:id="r2"/></sheets></workbook>',
        )
        archive.writestr(
            "xl/_rels/workbook.xml.rels",
            '<Relationships><Relationship Id="r1" Target="worksheets/sheet1.xml"/><Relationship Id="r2" Target="worksheets/sheet2.xml"/></Relationships>',
        )
        archive.writestr("xl/worksheets/sheet1.xml", sheet(working))
        archive.writestr("xl/worksheets/sheet2.xml", sheet(meta))
    return output


def test_unmodified_workbook_has_no_edits(tmp_path, baseline):
    assert read_workbook_edits(workbook(tmp_path, baseline), baseline)["edits"] == []


def test_named_course_tabs_keep_baseline_identity_guard(tmp_path, baseline):
    names = {"Canvas": "Core Canvas Mirror", "Working": "Core Canvas Edit", "_Sync": "_Core Sync"}
    path = workbook(tmp_path, baseline, tab_names=names)
    assert read_workbook_edits(path, baseline, names)["edits"] == []
    with pytest.raises(GradebookError, match="requires Working and _Sync"):
        read_workbook_edits(path, baseline)
    wrong = {"Canvas": "Adv Canvas Mirror", "Working": "Adv Canvas Edit", "_Sync": "_Adv Sync"}
    with pytest.raises(GradebookError, match="requires Working and _Sync"):
        read_workbook_edits(path, baseline, wrong)


def test_duplicate_tab_binding_rejected(tmp_path, baseline):
    names = {"Canvas": "same", "Working": "same", "_Sync": "_Sync"}
    with pytest.raises(GradebookError, match="tab binding"):
        read_workbook_edits(workbook(tmp_path, baseline), baseline, names)


def test_reordered_rows_use_ids_not_positions(tmp_path, baseline):
    cells = {
        "C5": "21",
        "A6": "102",
        "B6": "Example Two\nB1",
        "C6": "Excused",
        "A7": "101",
        "B7": "Example One\nA1",
        "C7": "20",
    }
    result = read_workbook_edits(workbook(tmp_path, baseline, cells), baseline)
    assert result["edits"] == [{"user_id": "101", "assignment_id": "21", "value": 20}]


@pytest.mark.parametrize(
    "address,value",
    [("A6", "102"), ("B6", "Wrong Name"), ("C5", "22"), ("C6", ("1+1",))],
)
def test_changed_identity_and_formulas_rejected(tmp_path, baseline, address, value):
    cells = {
        "C5": "21",
        "A6": "101",
        "B6": "Example One\nA1",
        "C6": "10",
        "A7": "102",
        "B7": "Example Two\nB1",
        "C7": "Excused",
    }
    cells[address] = value
    with pytest.raises(GradebookError):
        read_workbook_edits(workbook(tmp_path, baseline, cells), baseline)


def test_blank_edit_remains_explicit_blank(tmp_path, baseline):
    cells = {
        "C5": "21",
        "A6": "101",
        "B6": "Example One\nA1",
        "A7": "102",
        "B7": "Example Two\nB1",
        "C7": "Excused",
    }
    result = read_workbook_edits(workbook(tmp_path, baseline, cells), baseline)
    assert result["edits"][0]["value"] is None


def test_install_preserves_existing_config_and_is_idempotent(tmp_path):
    spec = importlib.util.spec_from_file_location(
        "gradebook_installer",
        Path(__file__).parents[1] / "scripts/install_gradebook_connection.py",
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    config = tmp_path / "config.toml"
    original = 'model = "example"\n[mcp_servers.existing]\ncommand = "existing"\n'
    config.write_text(original)
    assert "Installed" in module.install(config)
    content = config.read_text()
    assert content.startswith(original)
    assert "already matches" in module.install(config)
    assert config.read_text() == content
    assert len(list(tmp_path.glob("config.before-gradebook-*.toml"))) == 1


def test_install_refuses_conflicting_entry(tmp_path):
    spec = importlib.util.spec_from_file_location(
        "gradebook_installer",
        Path(__file__).parents[1] / "scripts/install_gradebook_connection.py",
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    config = tmp_path / "config.toml"
    original = '[mcp_servers.canvas-gradebook]\ncommand = "different"\n'
    config.write_text(original)
    with pytest.raises(ValueError):
        module.install(config)
    assert config.read_text() == original


def test_protection_preserves_values_and_unlocks_only_grade_cells(tmp_path):
    import xml.etree.ElementTree as ET

    spec = importlib.util.spec_from_file_location(
        "gradebook_protection",
        Path(__file__).parents[1] / "scripts/protect_gradebook_workbook.py",
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    ns = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
    output = tmp_path / "protection.xlsx"
    sheet = f'<worksheet xmlns="{ns}"><cols><col min="1" max="1"/></cols><sheetData><row r="5"><c r="C5"><v>21</v></c></row><row r="6"><c r="A6"><v>101</v></c><c r="C6"><v>10</v></c><c r="D6"/></row></sheetData></worksheet>'
    with ZipFile(output, "w") as archive:
        archive.writestr(
            "xl/styles.xml",
            f'<styleSheet xmlns="{ns}"><cellXfs count="1"><xf/></cellXfs></styleSheet>',
        )
        archive.writestr(
            "xl/workbook.xml",
            f'<workbook xmlns="{ns}"><sheets><sheet name="Canvas"/><sheet name="Working"/><sheet name="_Sync"/></sheets></workbook>',
        )
        for index in (1, 2, 3):
            archive.writestr(f"xl/worksheets/sheet{index}.xml", sheet)
    module.protect(output)
    with ZipFile(output) as archive:
        canvas = ET.fromstring(archive.read("xl/worksheets/sheet1.xml"))
        working = ET.fromstring(archive.read("xl/worksheets/sheet2.xml"))
        styles = ET.fromstring(archive.read("xl/styles.xml")).find(f"{{{ns}}}cellXfs")
        assert canvas.find(f"{{{ns}}}sheetProtection") is not None
        assert working.find(f"{{{ns}}}sheetProtection") is not None
        for tab in (canvas, working):
            assert [v.text for v in tab.iter(f"{{{ns}}}v")] == ["21", "101", "10"]
        cells = {c.get("r"): c for c in working.iter(f"{{{ns}}}c")}
        assert cells["A6"].get("s") is None
        assert cells["C5"].get("s") is None
        for address in ("C6", "D6"):
            assert (
                styles[int(cells[address].get("s"))]
                .find(f"{{{ns}}}protection")
                .get("locked")
                == "0"
            )


def test_gradebook_upgrade_preserves_other_tables(tmp_path):
    spec = importlib.util.spec_from_file_location(
        "gradebook_installer_upgrade",
        Path(__file__).parents[1] / "scripts/install_gradebook_connection.py",
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    desired = (
        Path(__file__).parents[1] / "config/sdm-gradebook.toml.example"
    ).read_text()
    before = (
        desired[: desired.index("enabled_tools = ")]
        + 'enabled_tools = ["get_canvas_gradebook", "preview_gradebook_changes"]\n'
    )
    prefix = 'model = "unchanged"\n[mcp_servers.existing]\ncommand = "retain"\n'
    suffix = "\n[features]\nunchanged = true\n"
    config = tmp_path / "config.toml"
    config.write_text(prefix + before + suffix)
    with pytest.raises(ValueError):
        module.install(config)
    assert "Installed" in module.install(config, upgrade=True)
    assert config.read_text().startswith(prefix)
    assert config.read_text().endswith(suffix)
    assert "prepare_gradebook_refresh" in config.read_text()
    assert "confirm_gradebook_push" not in config.read_text()
