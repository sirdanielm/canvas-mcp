"""Retained plans, rather than in-memory objects, must survive exact replay."""

import copy
import json

import pytest
from test_gradebook import snapshot as snapshot
from test_gradebook_native import binding as binding
from test_gradebook_native import raw_from_state
from test_teacher_edit_transfer import scenario as scenario

from canvas_mcp.gradebook import native
from canvas_mcp.gradebook.client import GradebookError
from canvas_mcp.gradebook.store import Store
from canvas_mcp.gradebook.teacher_edit_transfer import (
    classify_readback,
    prepare_transfer,
    revalidate_transfer,
)


@pytest.mark.parametrize("working_sheet_id", [2, 12])
def test_saved_reopened_plan_revalidates_and_classifies_complete_output(
    scenario, tmp_path, working_sheet_id
):
    args, _ = scenario

    def remap(value):
        if isinstance(value, dict):
            return {
                key: working_sheet_id if key == "sheetId" and item == 2 else remap(item)
                for key, item in value.items()
            }
        if isinstance(value, list):
            return [remap(item) for item in value]
        return value

    args["raw"] = remap(args["raw"])
    args["binding"]["sheets"]["Working"] = working_sheet_id
    original = copy.deepcopy(args["raw"])
    plan = prepare_transfer(**args)
    store = Store(tmp_path / "private-canvas")
    plan_id, _ = store.save("review", plan)
    retained = store.load("review", plan_id)
    assert retained == plan
    assert store.save("review", prepare_transfer(**args))[0] == plan_id
    revalidate_transfer(
        retained,
        expected_plan_sha256=plan_id,
        raw=args["raw"],
        current=args["current"],
        pin_binding=args["pin_binding"],
        source_check=args["source_check"],
    )
    before = classify_readback(retained, args["raw"], expected_plan_sha256=plan_id)
    assert before["status"] == "BEFORE_STILL_PRESENT"
    state = native._state(args["raw"])
    update = retained["requests"][0]["updateCells"]
    assert update["start"]["sheetId"] == working_sheet_id
    state["sheets"][working_sheet_id]["cells"]["5:2"].update(
        update["rows"][0]["values"][0]
    )
    actual = raw_from_state(state)
    observed = classify_readback(retained, actual, expected_plan_sha256=plan_id)
    assert observed["status"] == "PLANNED_OUTPUT_OBSERVED"
    assert observed["retry_writes"] is False
    assert args["raw"] == original
    assert json.loads(json.dumps(native._state(actual))) == retained["after_state"]


def test_tampered_saved_plan_cannot_be_loaded_as_original_authority(scenario, tmp_path):
    args, _ = scenario
    store = Store(tmp_path / "private-canvas")
    plan_id, path = store.save("review", prepare_transfer(**args))
    body = json.loads(path.read_text(encoding="utf-8"))
    body["decision"]["feedback"] = "Changed after teacher authentication"
    path.write_text(json.dumps(body), encoding="utf-8")
    with pytest.raises(GradebookError, match="integrity"):
        store.load("review", plan_id)
