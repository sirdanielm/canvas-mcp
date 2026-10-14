"""Scoped display regressions; fictional students and no external transports."""

from __future__ import annotations

import copy
from typing import Any

import pytest
from test_gradebook import snapshot as snapshot
from test_gradebook_native import binding as binding
from test_gradebook_native import initial_raw, raw_from_state

from canvas_mcp.gradebook import native
from canvas_mcp.gradebook.client import GradebookError
from canvas_mcp.gradebook.get_only_refresh import (
    _requests,
    prepare_get_only_refresh,
    verify_get_only_output,
)
from canvas_mcp.gradebook.model import digest
from canvas_mcp.gradebook.refresh import build_requests
from canvas_mcp.gradebook.store import Store

BOOK = "13ps0FZLBj2qpclMNKo7Eb95kE4Sb_fgf9s7Ki2_KoNc"
ORIGIN = "https://fcps.instructure.com"
NUMBER0 = {"type": "NUMBER", "pattern": "0"}


@pytest.fixture
def scoped(snapshot: dict[str, Any], binding: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    current, bound = copy.deepcopy(snapshot), copy.deepcopy(binding)
    current.update(origin=ORIGIN, course_id="363308")
    current["assignments"][0].update(id="4099721", points_possible=100)
    item = current["cells"].pop("101:21")
    item.update(value=85.6, grade="85.6")
    current["cells"]["101:4099721"] = item
    bound.update(course_id="363308", spreadsheet_id=BOOK)
    return current, bound


def rendered(current: dict[str, Any], bound: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    before = initial_raw(current, bound)
    requests = _requests(current, digest(current), bound, native._state(before))
    update = next(r["updateCells"] for r in requests if "updateCells" in r
                  and r["updateCells"]["start"]["sheetId"] == bound["sheets"]["Canvas"])
    return requests, update["rows"][5]["values"][2]


@pytest.mark.parametrize("course,assignment", [("363308", "4099721"), ("374070", "4099724")])
@pytest.mark.parametrize("value", [85, 85.6])
def test_exact_unit1_numeric_display_preserves_score(
    scoped: tuple[dict[str, Any], dict[str, Any]], course: str, assignment: str, value: int | float,
) -> None:
    current, bound = scoped
    old = current["cells"].pop("101:4099721")
    old.update(value=value, grade=str(value))
    current.update(course_id=course)
    current["assignments"][0]["id"] = assignment
    current["cells"][f"101:{assignment}"] = old
    bound["course_id"] = course
    requests, output = rendered(current, bound)
    assert output["userEnteredFormat"]["numberFormat"] == NUMBER0
    assert output["userEnteredValue"] == {"numberValue": value}
    assert len(requests) == 9


@pytest.mark.parametrize("change", [
    "origin", "book", "course", "binding_course", "assignment", "cross_pair", "maximum", "grading_type", "bool_maximum",
])
def test_other_scopes_retain_canonical_format(
    scoped: tuple[dict[str, Any], dict[str, Any]], change: str,
) -> None:
    current, bound = scoped
    if change == "origin":
        current["origin"] = "https://other.example"
    elif change == "book":
        bound["spreadsheet_id"] = "fictional-other-book"
    elif change == "course":
        current["course_id"] = bound["course_id"] = "12"
    elif change == "binding_course":
        bound["course_id"] = "12"
    elif change in {"assignment", "cross_pair"}:
        aid = "21" if change == "assignment" else "4099724"
        current["assignments"][0]["id"] = aid
        current["cells"][f"101:{aid}"] = current["cells"].pop("101:4099721")
    elif change == "maximum":
        current["assignments"][0]["points_possible"] = 20
    elif change == "bool_maximum":
        current["assignments"][0]["points_possible"] = True
    else:
        current["assignments"][0]["grading_type"] = "percent"
    _, output = rendered(current, bound)
    assert "numberFormat" not in output["userEnteredFormat"]


def test_actual_workbook_identity_must_also_match(
    scoped: tuple[dict[str, Any], dict[str, Any]],
) -> None:
    current, bound = scoped
    state = native._state(initial_raw(current, bound))
    state["spreadsheetId"] = "fictional-other-book"
    requests = _requests(current, digest(current), bound, state)
    update = next(r["updateCells"] for r in requests if "updateCells" in r
                  and r["updateCells"]["start"]["sheetId"] == bound["sheets"]["Canvas"])
    assert "numberFormat" not in update["rows"][5]["values"][2]["userEnteredFormat"]


def test_generic_full_sync_renderer_keeps_original_formats(
    scoped: tuple[dict[str, Any], dict[str, Any]],
) -> None:
    current, bound = scoped
    requests = build_requests(current, current, digest(current), bound, current, 0)
    for request in requests:
        update = request.get("updateCells")
        if update and update["start"]["sheetId"] in (bound["sheets"]["Canvas"], bound["sheets"]["Working"]):
            assert "numberFormat" not in update["rows"][5]["values"][2]["userEnteredFormat"]


@pytest.mark.parametrize("value", [None, "EX", "Excused", "85.6", True])
def test_blank_excused_string_and_bool_are_not_formatted(
    scoped: tuple[dict[str, Any], dict[str, Any]], value: Any,
) -> None:
    current, bound = scoped
    current["cells"]["101:4099721"]["value"] = value
    _, output = rendered(current, bound)
    assert "numberFormat" not in output["userEnteredFormat"]


def test_other_hundred_point_assignment_is_unchanged(
    scoped: tuple[dict[str, Any], dict[str, Any]],
) -> None:
    current, bound = scoped
    other = copy.deepcopy(current["assignments"][0])
    other.update(id="22", name="Fictional other assessment")
    current["assignments"].append(other)
    current["cells"]["101:22"] = copy.deepcopy(current["cells"]["101:4099721"])
    requests, _ = rendered(current, bound)
    update = next(r["updateCells"] for r in requests if "updateCells" in r
                  and r["updateCells"]["start"]["sheetId"] == bound["sheets"]["Canvas"])
    assert update["rows"][5]["values"][2]["userEnteredFormat"]["numberFormat"] == NUMBER0
    assert "numberFormat" not in update["rows"][5]["values"][3]["userEnteredFormat"]
    assert all("numberFormat" not in c["userEnteredFormat"] for row in update["rows"][:5] for c in row["values"])


class ReadOnlyCanvas:
    def __init__(self, current: dict[str, Any]) -> None:
        self.origin = current["origin"]
        self.current = copy.deepcopy(current)
        self.reads: list[str] = []

    async def snapshot(self, course_id: str) -> dict[str, Any]:
        self.reads.append(course_id)
        return copy.deepcopy(self.current)


@pytest.mark.asyncio
async def test_normal_get_readback_keeps_format_edit_notes_formulas_and_b2(
    scoped: tuple[dict[str, Any], dict[str, Any]], tmp_path: Any,
) -> None:
    current, bound = scoped
    store = Store(tmp_path)
    store.save("snapshot", current)
    before_state = native._state(initial_raw(current, bound))
    before_state["sheets"][1]["cells"]["5:2"]["userEnteredFormat"]["numberFormat"] = {
        "type": "NUMBER", "pattern": "0.000",
    }
    edit = before_state["sheets"][2]
    edit["cells"]["5:2"]["note"] = "Fictional complete teacher feedback\nKeep exact."
    edit["cells"]["20:10"] = {"userEnteredValue": {"formulaValue": "=1+1"}, "note": "Fictional helper"}
    before = raw_from_state(before_state)
    canvas = ReadOnlyCanvas(current)
    plan = await prepare_get_only_refresh(canvas, store, "core", bound, before)
    after_state = native._state(before)
    native._apply_requests(after_state, plan["batch_update"]["requests"], bound)
    after = raw_from_state(after_state)
    verify_get_only_output(before, after, [plan], store, {"core": bound})
    assert canvas.reads == ["363308"]
    assert len(plan["batch_update"]["requests"]) == 9
    assert after_state["sheets"][1]["cells"]["5:2"]["userEnteredFormat"]["numberFormat"] == NUMBER0
    assert after_state["sheets"][1]["cells"]["5:2"]["userEnteredValue"] == {"numberValue": 85.6}
    assert after_state["sheets"][2] == before_state["sheets"][2]
    assert after_state["sheets"][4] == before_state["sheets"][4]
    assert after_state["sheets"][3]["cells"]["1:1"] == before_state["sheets"][3]["cells"]["1:1"]
    second = await prepare_get_only_refresh(canvas, store, "core", bound, after)
    later = native._state(after)
    native._apply_requests(later, second["batch_update"]["requests"], bound)
    verify_get_only_output(after, raw_from_state(later), [second], store, {"core": bound})
    assert later["sheets"][1]["cells"]["5:2"]["userEnteredFormat"]["numberFormat"] == NUMBER0
    assert later["sheets"][2] == before_state["sheets"][2]
    # A later read cannot silently accept a different display than its canonical projection.
    after_state["sheets"][1]["cells"]["5:2"]["userEnteredFormat"]["numberFormat"]["pattern"] = "0.00"
    with pytest.raises(GradebookError):
        verify_get_only_output(before, raw_from_state(after_state), [plan], store, {"core": bound})
