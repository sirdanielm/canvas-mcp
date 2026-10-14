"""Complete native review path for explicitly versioned sparse Edit layouts."""

import copy
import json

import pytest
from test_gradebook import snapshot as snapshot
from test_gradebook_native import binding as binding
from test_gradebook_native import raw_from_state
from test_gradebook_native_edit_review import Canvas
from test_gradebook_sparse_edit_axis_refresh import dense_scenario as dense_scenario
from test_gradebook_sparse_edit_axis_refresh import prepared
from test_gradebook_sparse_edit_axis_refresh import scenario as scenario

from canvas_mcp.gradebook import native
from canvas_mcp.gradebook.client import GradebookError
from canvas_mcp.gradebook.model import digest
from canvas_mcp.gradebook.native_edit_review import extract_native_edits, prepare_review
from canvas_mcp.gradebook.sparse_edit_axis_refresh import extract_sparse_edits
from canvas_mcp.gradebook.store import Store


def test_opt_in_sparse_adapter_matches_pure_dense_projection(scenario):
    _, binding, _, _ = scenario
    plan, after = prepared(scenario)
    before = copy.deepcopy(after)
    expected = extract_sparse_edits(after, binding, plan["merged_baseline"])
    assert extract_native_edits(after, binding, plan["merged_baseline"]) == expected
    assert after == before
    assert "formulaValue" not in json.dumps(expected)
    assert "Private fictional helper" not in json.dumps(expected)


@pytest.mark.asyncio
async def test_sparse_review_retains_old_conflict_context_and_fetches_once(
    scenario, tmp_path
):
    _, binding, original, current = scenario
    plan, after = prepared(scenario)
    store = Store(tmp_path)
    store.save("snapshot", original)
    store.save("snapshot", current)
    store.save("snapshot", plan["merged_baseline"])
    client = Canvas(current)
    before = copy.deepcopy(after)
    result = await prepare_review(client, store, "core", binding, after)
    assert client.reads == ["12"]
    assert result["baseline_id"] == digest(plan["merged_baseline"])
    assert result["changes"] == 1
    assert result["counts"] == {"review_required": 1}
    review = store.load("review", result["review_id"])
    change = review["changes"][0]
    assert (change["baseline"], change["current"], change["proposed"]) == (10, 18, 20)
    assert "canvas_changed_since_baseline" in change["reasons"]
    assert result["canvas_writes"] == result["sheets_writes"] == 0
    assert after == before
    assert "user_id" not in json.dumps(result)
    assert "assignment_id" not in json.dumps(result)
    assert (
        "Private fictional helper"
        not in (store.root / ("review-" + result["review_id"] + ".html")).read_text()
    )


@pytest.mark.asyncio
async def test_new_sparse_numeric_proposal_uses_exact_fresh_target_context(
    scenario, tmp_path
):
    _, binding, _, current = scenario
    plan, after = prepared(scenario)
    state = native._state(after)
    state["sheets"][2]["cells"]["6:2"]["userEnteredValue"] = {"numberValue": 5}
    after = raw_from_state(state)
    store = Store(tmp_path)
    store.save("snapshot", plan["merged_baseline"])
    result = await prepare_review(Canvas(current), store, "core", binding, after)
    review = store.load("review", result["review_id"])
    new = next(change for change in review["changes"] if change["user_id"] == "102")
    assert (new["baseline"], new["current"], new["proposed"]) == (0, 0, 5)
    assert (
        store.load("snapshot", result["baseline_id"])["cells"]["102:21"]
        == current["cells"]["102:21"]
    )
    assert new["status"] == "ready_for_review"
    assert new["reasons"] == []
    assert result["canvas_writes"] == 0


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "change", ["mapped_formula", "layout_mode", "unknown_aid", "protection"]
)
async def test_sparse_mapped_corruption_holds_before_get_or_new_artifacts(
    scenario, tmp_path, change
):
    _, binding, _, current = scenario
    plan, after = prepared(scenario)
    baseline = copy.deepcopy(plan["merged_baseline"])
    state = native._state(after)
    if change == "mapped_formula":
        state["sheets"][2]["cells"]["6:4"]["userEnteredValue"] = {"formulaValue": "=20"}
    elif change == "layout_mode":
        baseline["working_layout"]["mode"] = "private-sentinel"
        state["sheets"][3]["cells"]["1:1"]["userEnteredValue"] = {
            "stringValue": digest(baseline)
        }
    elif change == "unknown_aid":
        state["sheets"][2]["cells"]["4:3"] = {
            "userEnteredValue": {"stringValue": "999"}
        }
    else:
        state["sheets"][2]["protectedRanges"][0]["unprotectedRanges"][0][
            "endColumnIndex"
        ] = 4
    store = Store(tmp_path)
    store.save("snapshot", baseline)
    files = set(store.root.iterdir())
    client = Canvas(current)
    with pytest.raises(GradebookError) as error:
        await prepare_review(client, store, "core", binding, raw_from_state(state))
    assert "private-sentinel" not in str(error.value)
    assert client.reads == []
    assert set(store.root.iterdir()) == files
