"""Read-only worker CLI regressions using fictional local collaborators."""

import copy
import importlib.util
import sys
from pathlib import Path

import pytest
from test_gradebook_native import initial_raw
from test_gradebook_worker_integration import (
    BINDINGS,
    fixture_records,
    fixture_snapshot,
)

from canvas_mcp.gradebook.client import GradebookError
from canvas_mcp.gradebook.native import validate_workbook
from canvas_mcp.gradebook.store import Store

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "gradebook_get_only_cli_under_test", ROOT / "scripts/sdm_gradebook_worker.py"
)
cli = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = cli
spec.loader.exec_module(cli)


def test_worker_google_factory_reduces_quota_load_without_expanding_safety_caps(
    monkeypatch, tmp_path
):
    calls = []

    def google(workbook_id, credential_path, **options):
        calls.append((workbook_id, credential_path, options))
        return object()

    monkeypatch.setattr(cli, "GoogleSheets", google)
    config = {"credential_path": str(tmp_path / "unused.json"), "profile": "gradebook"}
    bound = {"core": {"spreadsheet_id": "fictional-workbook"}}

    cli.google_client(config, bound)

    assert calls == [
        (
            "fictional-workbook",
            tmp_path / "unused.json",
            {
                "profile": "gradebook",
                "sheet_cell_limits": {"Unit1 LI Records": 58_000},
                "max_chunk_cells": 100_000,
                "read_interval_seconds": 5.0,
            },
        )
    ]


@pytest.fixture
def preserved_edit_scenario(tmp_path, monkeypatch):
    old = {
        "core": fixture_snapshot(fixture_records(12, 101, 21, 10)),
        "advanced": fixture_snapshot(fixture_records(13, 201, 31, 12)),
    }
    raw = initial_raw(old["core"], BINDINGS["core"])
    raw["sheets"].extend(
        initial_raw(old["advanced"], BINDINGS["advanced"])["sheets"][:3]
    )
    records = fixture_records(12, 101, 21, 18)
    additional = copy.deepcopy(records["enrollments"][0])
    additional["user_id"] = additional["user"]["id"] = 102
    additional["user"]["name"] = "Fictional Additional Student"
    records["enrollments"].append(additional)
    assignment = copy.deepcopy(records["assignments"][0])
    assignment.update(id=22, name="Fictional Additional Activity", position=2)
    records["assignments"].append(assignment)
    current = fixture_snapshot(records)
    current_get = next(
        sheet
        for sheet in initial_raw(current, BINDINGS["core"])["sheets"]
        if sheet["properties"]["sheetId"] == 1
    )
    raw["sheets"] = [
        current_get if sheet["properties"]["sheetId"] == 1 else sheet
        for sheet in raw["sheets"]
    ]
    edit = next(sheet for sheet in raw["sheets"] if sheet["properties"]["sheetId"] == 2)
    edit["data"][0]["rowData"][5]["values"][2]["userEnteredValue"] = {"numberValue": 20}
    edit["data"][0]["rowData"][5]["values"][2]["note"] = "Teacher feedback retained"
    # A teacher's helper formula lies outside the connector's score rectangle.
    while len(edit["data"][0]["rowData"][0]["values"]) < 6:
        edit["data"][0]["rowData"][0]["values"].append({})
    edit["data"][0]["rowData"][0]["values"][5] = {
        "userEnteredValue": {"formulaValue": "=SUM(C6:C7)"},
        "note": "Retain this helper",
    }
    path = tmp_path / "worker.json"
    state_dir = tmp_path / "state"
    cli.configure(path, state_dir=state_dir)
    store = Store(state_dir)
    for baseline in old.values():
        store.save("snapshot", baseline)
    monkeypatch.setattr(cli, "bindings", lambda: copy.deepcopy(BINDINGS))
    monkeypatch.setattr(cli, "COURSES", {"core": "12", "advanced": "13"})
    monkeypatch.setattr(cli, "ORIGIN", "https://school.example")
    return raw, path, state_dir


async def test_get_only_doctor_accepts_current_get_with_preserved_edit_helpers(
    preserved_edit_scenario, monkeypatch
):
    raw, config_path, state_dir = preserved_edit_scenario
    before = copy.deepcopy(raw)
    before_files = {p.name: p.read_bytes() for p in state_dir.iterdir() if p.is_file()}
    reads = []

    class Google:
        async def read_workbook(self):
            reads.append("read")
            return copy.deepcopy(raw)

        async def batch(self, requests):
            pytest.fail("Doctor must not write Sheets")

        async def send_preflighted_batch(self, requests):
            pytest.fail("Doctor must not write grade data")

        async def close(self):
            reads.append("close")

    monkeypatch.setattr(cli, "google_client", lambda *_: Google())
    monkeypatch.setattr(
        cli, "canvas_client", lambda: pytest.fail("Doctor needs no Canvas")
    )
    monkeypatch.setattr(
        cli, "edits_from_cells", lambda *_: pytest.fail("GET-only must not parse Edit")
    )
    args = cli.parser().parse_args(
        ["--config", str(config_path), "--get-only", "doctor"]
    )

    result = await cli.execute(args)

    assert result["state"] == "READY"
    assert result["canvas_writes"] == result["sheets_writes"] == 0
    assert reads == ["read", "close"]
    assert raw == before
    assert {
        p.name: p.read_bytes() for p in state_dir.iterdir() if p.is_file()
    } == before_files


async def test_default_doctor_still_holds_the_same_preserved_edit_fixture(
    preserved_edit_scenario,
):
    raw, _, state_dir = preserved_edit_scenario
    before = copy.deepcopy(raw)

    class Google:
        async def read_workbook(self):
            return copy.deepcopy(raw)

    with pytest.raises(GradebookError, match="formulas"):
        validate_workbook(raw, BINDINGS)
    with pytest.raises(GradebookError, match="formulas"):
        await cli.doctor(Google(), Store(state_dir), BINDINGS)
    assert raw == before
