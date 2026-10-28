"""Synthetic native postconditions and durable receipts; no live services."""

import copy
from typing import Any

import pytest
import test_gradebook_get_only_worker as get_worker_fixtures
import test_gradebook_worker_integration as full_worker_fixtures
from test_gradebook import snapshot as snapshot
from test_gradebook_get_only_refresh import scenario as scenario
from test_gradebook_native import binding as binding
from test_gradebook_native import raw_from_state

from canvas_mcp.gradebook import native
from canvas_mcp.gradebook.client import GradebookError
from canvas_mcp.gradebook.get_only_refresh import (
    prepare_get_only_refresh,
    verify_get_only_output,
)
from canvas_mcp.gradebook.model import digest
from canvas_mcp.gradebook.store import Store

worker_scenario = get_worker_fixtures.scenario
full_worker_scenario = full_worker_fixtures.scenario
STYLE = {
    "textFormat": {"fontFamily": "Arial", "fontSize": 10, "foregroundColor": {"red": 0.2}},
    "verticalAlignment": "BOTTOM",
}


async def materialized(scenario: Any, *, growth: int = 1, malformed: bool = False) -> tuple[Any, ...]:
    before, canvas, store, binding = scenario
    state = native._state(before)
    style = copy.deepcopy(STYLE)
    if malformed:
        style["textFormat"]["fontFamily"] = True
    for row in (6, 7):
        state["sheets"][1]["cells"][f"{row}:25"] = {"userEnteredFormat": copy.deepcopy(style)}
    before = raw_from_state(state)
    original = canvas.current["assignments"][0]
    for aid in range(22, 45 + growth):
        canvas.current["assignments"].append({**original, "id": str(aid), "name": "Fictional activity"})
        canvas.current["cells"][f"101:{aid}"] = copy.deepcopy(canvas.current["cells"]["101:21"])
    plan = await prepare_get_only_refresh(canvas, store, "core", binding, before)
    after_state = native._state(before)
    native._apply_requests(after_state, plan["batch_update"]["requests"], binding)
    # Independent observations: new Sheets dimensions and blank-tail formatting.
    for column in range(26, 26 + growth):
        after_state["sheets"][1]["columnMetadata"][str(column)] = {"pixelSize": 100}
    for row in (6, 7):
        after_state["sheets"][1]["cells"][f"{row}:26"] = {"userEnteredFormat": copy.deepcopy(style)}
    return before, raw_from_state(after_state), plan, store, binding


async def test_exact_blank_tail_styles_are_reported_without_mutating_evidence(scenario: Any) -> None:
    before, after, plan, store, binding = await materialized(scenario)
    originals = copy.deepcopy((before, after, plan))
    report: dict[str, Any] = {}
    verify_get_only_output(before, after, [plan], store, {"core": binding}, postcondition_report=report)
    assert (before, after, plan) == originals
    assert report["contract"] == "GET_ONLY_MATERIALIZATION_V1"
    assert report["before_fingerprint"] == native.fingerprint(before)
    assert report["actual_after_fingerprint"] == native.fingerprint(after)
    assert report["plan_sha256s"] == [digest(plan)]
    assert report["original_artifacts_unchanged"] is True
    assert report["replay_authorized"] is False
    assert {item["cell"] for item in report["admitted_differences"]} == {"AA7", "AA8"}
    for item in report["admitted_differences"]:
        assert item["sheet_id"] == 1 and item["expected"] == {}
        assert item["actual"] == item["anchor_before"]
        assert item["rule"] == "new-column-blank-tail-style-v1"
    assert native._state(before)["sheets"][2] == native._state(after)["sheets"][2]


@pytest.mark.parametrize("change", [
    "third_tail_row", "different_font", "extra_style", "tail_note", "tail_value",
    "existing_column", "wrong_width", "new_hidden", "edit_note", "score", "protection",
])
async def test_blank_tail_rule_never_admits_other_differences(scenario: Any, change: str) -> None:
    before, after, plan, store, binding = await materialized(scenario)
    state = native._state(after)
    sheet = state["sheets"][1]
    if change == "third_tail_row":
        sheet["cells"]["8:26"] = copy.deepcopy(sheet["cells"]["6:26"])
    elif change == "different_font":
        sheet["cells"]["6:26"]["userEnteredFormat"]["textFormat"]["fontSize"] = 12
    elif change == "extra_style":
        sheet["cells"]["6:26"]["userEnteredFormat"]["textFormat"]["bold"] = True
    elif change in {"tail_note", "tail_value"}:
        sheet["cells"]["6:26"]["note" if change == "tail_note" else "userEnteredValue"] = (
            "Unexpected fictional note" if change == "tail_note" else {"numberValue": 1}
        )
    elif change == "existing_column":
        sheet["cells"]["6:25"]["userEnteredFormat"]["textFormat"]["fontSize"] = 12
    elif change == "wrong_width":
        sheet["columnMetadata"]["26"]["pixelSize"] = 101
    elif change == "new_hidden":
        sheet["columnMetadata"]["26"]["hiddenByUser"] = True
    elif change == "edit_note":
        state["sheets"][2]["cells"]["5:2"]["note"] = "Changed teacher feedback"
    elif change == "score":
        sheet["cells"]["5:2"]["userEnteredValue"] = {"numberValue": 19}
    else:
        sheet["protectedRanges"] = []
    with pytest.raises(GradebookError):
        verify_get_only_output(before, raw_from_state(state), [plan], store, {"core": binding})


@pytest.mark.parametrize("case", ["two_new_columns", "malformed_anchor"])
async def test_unqualified_materialization_stays_held(scenario: Any, case: str) -> None:
    before, after, plan, store, binding = await materialized(
        scenario, growth=2 if case == "two_new_columns" else 1, malformed=case == "malformed_anchor"
    )
    with pytest.raises(GradebookError):
        verify_get_only_output(before, after, [plan], store, {"core": binding})


async def test_worker_persists_exact_admitted_difference_report(worker_scenario: Any) -> None:
    worker, google, source, request, _ = worker_scenario
    state = native._state(google.raw)
    for row in (7, 8):
        state["sheets"][1]["cells"][f"{row}:25"] = {"userEnteredFormat": copy.deepcopy(STYLE)}
    updated = raw_from_state(state)
    updated["developerMetadata"] = google.raw["developerMetadata"]
    google.raw = updated
    original_before = copy.deepcopy(google.raw)
    assignments = source.records["12"]["assignments"]
    for aid in range(23, 46):
        assignments.append({**assignments[0], "id": aid, "name": "Fictional expansion", "position": aid})
    original_send = google.send_preflighted_batch

    async def observed_materialization(requests: Any) -> Any:
        result = await original_send(requests)
        observed = native._state(google.raw)
        observed["sheets"][1]["columnMetadata"]["26"] = {"pixelSize": 100}
        for row in (7, 8):
            observed["sheets"][1]["cells"][f"{row}:26"] = {"userEnteredFormat": copy.deepcopy(STYLE)}
        after = raw_from_state(observed)
        after["developerMetadata"] = google.raw["developerMetadata"]
        google.raw = after
        return result

    google.send_preflighted_batch = observed_materialization
    result = await worker.step()
    assert result["state"] == "VERIFIED" and result["canvas_writes"] == 0
    operation = worker.journal.get(request["id"])
    receipt_id = operation["payload"]["receipt_id"]
    retained = Store(worker.store.root).load("receipt", receipt_id)
    report = retained["native_postcondition"]
    assert report["contract"] == "GET_ONLY_MATERIALIZATION_V1"
    assert {item["cell"] for item in report["admitted_differences"]} == {"AA8", "AA9"}
    assert report["before_fingerprint"] == native.fingerprint(original_before)
    assert report["actual_after_fingerprint"] == native.fingerprint(google.raw)
    assert native._state(original_before)["sheets"][2] == native._state(google.raw)["sheets"][2]
    assert all(r.method == "GET" for r in source.requests)
    assert len(google.grade_batches) == 1
    assert (await worker.step())["state"] == "IDLE"
    assert len(google.grade_batches) == 1
    assert Store(worker.store.root).load("receipt", receipt_id) == retained


async def test_full_sync_receipts_do_not_claim_get_postconditions(full_worker_scenario: Any) -> None:
    worker, _, _, request, _ = full_worker_scenario
    assert (await worker.step())["state"] == "VERIFIED"
    operation = worker.journal.get(request["id"])
    receipt = worker.store.load("receipt", operation["payload"]["receipt_id"])
    assert "native_postcondition" not in receipt


@pytest.mark.parametrize("get_only", [False, True])
async def test_reconcile_verifier_and_receipt_follow_saved_mode_during_option_drift(
    worker_scenario: Any, full_worker_scenario: Any, get_only: bool,
) -> None:
    worker, google, source, request, _ = (
        worker_scenario if get_only else full_worker_scenario
    )
    read_workbook = google.read_workbook

    async def read_with_changed_worker_option() -> Any:
        observed = await read_workbook()
        if google.grade_batches:
            # A current option cannot reinterpret an already applied operation.
            worker.get_only = not get_only
        return observed

    google.read_workbook = read_with_changed_worker_option

    result = await worker.step()

    assert result["state"] == "VERIFIED" and result["canvas_writes"] == 0
    assert worker.get_only is not get_only
    operation = worker.journal.get(request["id"])
    assert operation["payload"]["finalized"] is True
    manifest = worker.store.load("refresh", operation["payload"]["manifest_id"])
    assert manifest["refresh_mode"] == ("GET_ONLY" if get_only else "FULL_SYNC")
    receipt = worker.store.load("receipt", operation["payload"]["receipt_id"])
    if get_only:
        assert receipt["native_postcondition"]["contract"] == "GET_ONLY_MATERIALIZATION_V1"
        assert all(summary["pending_edits"] is None and summary["edit_preserved"] is True
                   for summary in receipt["summary"].values())
    else:
        assert "native_postcondition" not in receipt
        assert all(type(summary["pending_edits"]) is int and "edit_preserved" not in summary
                   for summary in receipt["summary"].values())
    assert len(google.grade_batches) == 1
    assert source.requests and all(request.method == "GET" for request in source.requests)
