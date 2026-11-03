"""Real authenticated fictional application, score-only native batch and readback."""

import copy
import json

import httpx
import pytest
import test_localgrass_application as cases
from test_gradebook import snapshot as snapshot
from test_gradebook_native import binding as binding
from test_gradebook_native import raw_from_state
from test_localgrass_edit_owner import composed as composed
from test_localgrass_teacher_edit import integrated as integrated

from canvas_mcp.gradebook import localgrass_application as app
from canvas_mcp.gradebook import native
from canvas_mcp.gradebook.client import GradebookError
from canvas_mcp.gradebook.worker import RefreshJournalBusy

configured = cases.configured


@pytest.mark.parametrize(
    "lane,policy",
    [
        ("SDMGRASS_FORMATIVE", "SCORE_ONLY"),
        ("GRASS_SUMMATIVE", "SCORE_AND_FEEDBACK"),
    ],
)
async def test_pinned_application_binds_lane_to_authenticated_existing_owner(
    configured, lane, policy
):
    c, value, path, kwargs, owners = configured
    value.update(source_lane=lane, delivery_policy=policy)
    path.write_bytes(cases.encoded(value))
    factory = app.build_owner_factory(*owners(), **kwargs())
    owner = factory(c.domain.token, c.domain.csrf)
    prepared = await owner.prepare()
    plan = c.store.load("review", prepared["plan_id"])
    transfer = plan["transfer"]
    assert transfer["record"]["source_lane"] == lane
    assert transfer["decision"]["delivery_policy"] == policy
    assert (
        transfer["decision"]["decision_revision"] == c.domain.acceptance["decision_id"]
    )
    fields = transfer["requests"][0]["updateCells"]["fields"]
    assert fields == (
        "userEnteredValue" if policy == "SCORE_ONLY" else "userEnteredValue,note"
    )
    assert c.calls["posts"] == []
    assert (
        plan["score_delivery_authorized"]
        is plan["comment_delivery_authorized"]
        is False
    )


@pytest.mark.parametrize(
    "change", ["wrong_policy", "missing_policy", "unit1_formative"]
)
def test_incompatible_pinned_application_policy_is_held(configured, change):
    c, value, path, kwargs, owners = configured
    value.update(source_lane="SDMGRASS_FORMATIVE", delivery_policy="SCORE_ONLY")
    if change == "wrong_policy":
        value["delivery_policy"] = "SCORE_AND_FEEDBACK"
    elif change == "missing_policy":
        value.pop("delivery_policy")
    else:
        value["contract"] = app.UNIT1_CONTRACT
        value.pop("source_root")
    path.write_bytes(cases.encoded(value))
    with pytest.raises(GradebookError, match="DELIVERY_POLICY"):
        app.build_owner_factory(*owners(), **kwargs())
    assert c.calls == {"canvas_reads": 0, "sheets_reads": 0, "posts": []}


async def test_score_only_real_native_transport_readback_and_no_replay(configured):
    c, value, path, kwargs, owners = configured
    value.update(source_lane="SDMGRASS_FORMATIVE", delivery_policy="SCORE_ONLY")
    path.write_bytes(cases.encoded(value))
    original = native._state(c.state["raw"])
    original["sheets"][2]["cells"]["5:2"]["note"] = (
        "Original teacher note.\nKeep exactly."
    )
    c.state["raw"] = raw_from_state(original)
    requests = []

    def transport(request):
        assert (
            request.method == "POST"
            and str(request.url) == c.google.url + ":batchUpdate"
        )
        with pytest.raises(RefreshJournalBusy):
            with c.journal.exclusive():
                pass
        receipt = json.loads(sorted(c.output.glob("*/receipt-*.json"))[-1].read_text(encoding="utf-8"))
        assert receipt["status"] == "SENDING"
        body = json.loads(request.content)
        assert body["requests"] == [
            {
                "updateCells": {
                    "start": {"sheetId": 2, "rowIndex": 5, "columnIndex": 2},
                    "rows": [{"values": [{"userEnteredValue": {"numberValue": 7}}]}],
                    "fields": "userEnteredValue",
                }
            }
        ]
        requests.append(body)
        after = copy.deepcopy(original)
        after["sheets"][2]["cells"]["5:2"]["userEnteredValue"] = {"numberValue": 7}
        c.state["raw"] = raw_from_state(after)
        return httpx.Response(200, json={"spreadsheetId": c.google.workbook_id})

    await c.google.http.aclose()
    c.google.http = httpx.AsyncClient(transport=httpx.MockTransport(transport))
    owner = app.build_owner_factory(*owners(), **kwargs())(
        c.domain.token, c.domain.csrf
    )
    prepared = await owner.prepare()
    result = await owner.execute(prepared["plan_id"], enabled=True)
    assert result["status"] == "PLANNED_OUTPUT_OBSERVED"
    assert len(requests) == 1
    assert (
        native._state(c.state["raw"])["sheets"][2]["cells"]["5:2"]["note"]
        == original["sheets"][2]["cells"]["5:2"]["note"]
    )
    c.state["canvas_unavailable"] = True
    again = await owner.execute(prepared["plan_id"], enabled=True)
    assert again["status"] == "PLANNED_OUTPUT_OBSERVED"
    assert again["sheets_write_requests"] == 0 and len(requests) == 1
    assert result["canvas_writes"] == again["canvas_writes"] == 0
    assert result["publication_allowed"] is again["publication_allowed"] is False
