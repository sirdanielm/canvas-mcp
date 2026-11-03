"""Independent fictional observations for the exact two-column GET exception."""

import copy
from typing import Any

import pytest
from test_get_only_materialization_contract import STYLE, materialized
from test_gradebook import snapshot as snapshot
from test_gradebook_get_only_refresh import scenario as scenario
from test_gradebook_native import binding as binding
from test_gradebook_native import raw_from_state

from canvas_mcp.gradebook import native
from canvas_mcp.gradebook.client import GradebookError
from canvas_mcp.gradebook.get_only_refresh import verify_get_only_output
from canvas_mcp.gradebook.model import digest

TAIL = ("6:26", "7:26", "6:27", "7:27")


async def two_columns(scenario: Any, *, malformed: bool = False) -> tuple[Any, ...]:
    before, after, plan, store, binding = await materialized(
        scenario, growth=2, malformed=malformed
    )
    observed = native._state(after)
    # The existing helper observes only the first new column. Independently
    # supply both native observations for the second column, never the verifier.
    style = copy.deepcopy(STYLE)
    if malformed:
        style["textFormat"]["fontFamily"] = True
    for row in (6, 7):
        observed["sheets"][1]["cells"][f"{row}:27"] = {
            "userEnteredFormat": copy.deepcopy(style)
        }
    return before, raw_from_state(observed), plan, store, binding


async def test_four_exact_native_observations_retain_report_and_originals(
    scenario: Any,
) -> None:
    before, after, plan, store, binding = await two_columns(scenario)
    originals = copy.deepcopy((before, after, plan))
    report: dict[str, Any] = {}
    verify_get_only_output(
        before, after, [plan], store, {"core": binding}, postcondition_report=report
    )
    assert (before, after, plan) == originals
    assert report["contract"] == "GET_ONLY_MATERIALIZATION_V1"
    assert report["before_fingerprint"] == native.fingerprint(before)
    assert report["actual_after_fingerprint"] == native.fingerprint(after)
    assert report["plan_sha256s"] == [digest(plan)]
    assert report["original_artifacts_unchanged"] is True
    assert report["replay_authorized"] is False
    differences = report["admitted_differences"]
    assert len(differences) == 4
    assert {d["cell"] for d in differences} == {"AA7", "AA8", "AB7", "AB8"}
    for difference in differences:
        assert difference["sheet_id"] == 1
        assert difference["rule"] == "two-new-columns-four-blank-tail-styles-v1"
        assert difference["expected"] == {}
        assert difference["actual"] == difference["anchor_before"]
        row = int(difference["cell"][2:]) - 1
        column = 26 if difference["cell"].startswith("AA") else 27
        assert (
            difference["actual"]
            == native._state(after)["sheets"][1]["cells"][f"{row}:{column}"]
        )
        assert (
            difference["anchor_before"]
            == native._state(before)["sheets"][1]["cells"][f"{row}:25"]
        )
        assert difference["anchor_cell"] == "Z" + difference["cell"][2:]
    assert native._state(before)["sheets"][2] == native._state(after)["sheets"][2]
    # Mutating the output report cannot mutate captured evidence either.
    differences[0]["actual"]["userEnteredFormat"]["textFormat"]["fontSize"] = 77
    assert (before, after, plan) == originals


@pytest.mark.parametrize("omitted", TAIL)
async def test_each_of_four_native_style_observations_is_required(
    scenario: Any, omitted: str
) -> None:
    before, after, plan, store, binding = await two_columns(scenario)
    state = native._state(after)
    state["sheets"][1]["cells"].pop(omitted)
    after = raw_from_state(state)
    originals = copy.deepcopy((before, after, plan))
    report: dict[str, Any] = {}
    with pytest.raises(GradebookError):
        verify_get_only_output(
            before, after, [plan], store, {"core": binding}, postcondition_report=report
        )
    assert report == {}
    assert (before, after, plan) == originals


@pytest.mark.parametrize(
    "change",
    [
        "style_drift",
        "new_column_note",
        "new_column_literal",
        "new_column_formula",
        "old_cell",
        "extra_tail_row",
        "malformed_anchor",
    ],
)
async def test_two_column_rule_holds_all_unqualified_differences(
    scenario: Any, change: str
) -> None:
    before, after, plan, store, binding = await two_columns(
        scenario, malformed=change == "malformed_anchor"
    )
    state = native._state(after)
    cells = state["sheets"][1]["cells"]
    if change == "style_drift":
        cells["7:27"]["userEnteredFormat"]["textFormat"]["fontSize"] = 11
    elif change == "new_column_note":
        cells["7:27"]["note"] = "Fictional unexpected note"
    elif change == "new_column_literal":
        cells["7:27"]["userEnteredValue"] = {"numberValue": 1}
    elif change == "new_column_formula":
        cells["7:27"]["userEnteredValue"] = {"formulaValue": "=1+1"}
    elif change == "old_cell":
        cells["6:25"]["userEnteredFormat"]["textFormat"]["fontSize"] = 11
    elif change == "extra_tail_row":
        cells["8:27"] = {"userEnteredFormat": copy.deepcopy(STYLE)}
    after = raw_from_state(state)
    originals = copy.deepcopy((before, after, plan))
    report: dict[str, Any] = {}
    with pytest.raises(GradebookError):
        verify_get_only_output(
            before, after, [plan], store, {"core": binding}, postcondition_report=report
        )
    assert report == {}
    assert (before, after, plan) == originals
