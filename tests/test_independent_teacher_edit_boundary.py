"""Independent review probes: fictional authenticated stores, blocked sockets.

These tests live only in the review snapshot, not an owner's checkout.
"""

import copy
import json
import socket

import httpx
import pytest
from test_localgrass_teacher_edit import binding as binding
from test_localgrass_teacher_edit import integrated as integrated
from test_localgrass_teacher_edit import snapshot as snapshot

from canvas_mcp.gradebook.client import GradebookError
from canvas_mcp.gradebook.google import GoogleSheets
from canvas_mcp.gradebook.localgrass_edit_execution import execute_local_edit_once
from canvas_mcp.gradebook.model import digest


@pytest.fixture(autouse=True)
def forbid_real_network(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("Independent qualification attempted real networking")

    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(socket.socket, "connect_ex", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)


@pytest.mark.asyncio
async def test_new_authenticated_decision_cannot_bypass_uncertain_same_target(
    integrated, tmp_path
):
    connection, context, domain, *_ = integrated
    original = connection.prepare(**context)
    root = tmp_path / "shared-existing-stage"
    sends = []

    def loses_reply(book, requests):
        sends.append(book)
        raise TimeoutError("Fictional unresolved send")

    result = await execute_local_edit_once(
        connection,
        original,
        expected_plan_sha256=digest(original),
        output_root=root,
        read_context=lambda: context,
        write_requests=loses_reply,
        enabled=True,
    )
    assert result["status"] == "UNCERTAIN_RECONCILIATION_REQUIRED"
    domain.review.save_draft(
        domain.token,
        domain.csrf,
        domain.case_key,
        domain.proposal_id,
        domain.acceptance["decision_id"],
        1,
        "8.0",
        "A separately accepted fictional teacher correction.",
    )
    latest = domain.review.accept_draft(domain.token, domain.csrf, domain.case_key, 2)
    domain.source.decision_id = latest["decision_id"]
    newer = connection.prepare(**context)
    assert digest(newer) != digest(original)
    assert newer["items"] == original["items"]

    def forbidden_read():
        raise AssertionError("Overlapping uncertain history reached native read")

    with pytest.raises(GradebookError, match="UNRESOLVED_NATIVE_TARGET_HISTORY"):
        await execute_local_edit_once(
            connection,
            newer,
            expected_plan_sha256=digest(newer),
            output_root=root,
            read_context=forbidden_read,
            write_requests=loses_reply,
            enabled=True,
        )
    assert len(sends) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("outcome", ["success", "http401", "http503", "timeout"])
async def test_actual_google_transport_has_one_post_after_durable_intent(
    integrated, tmp_path, monkeypatch, outcome
):
    connection, context, *_ = integrated
    plan = connection.prepare(**context)
    root = tmp_path / "shared-existing-stage"
    credential = tmp_path / "fictional-google.json"
    credential.write_text(
        json.dumps(
            {
                "tokens": {
                    "gradebook": {
                        "type": "authorized_user",
                        "client_id": "fictional_client",
                        "client_secret": "fictional_secret",
                        "refresh_token": "fictional_refresh",
                    }
                }
            }
        )
    )
    credential.chmod(0o600)
    raw = copy.deepcopy(context["raw"])
    calls = []
    intent_seen = False
    batch_seen = False
    old_write = connection.files.write

    def durable_write(path, value):
        nonlocal intent_seen
        old_write(path, value)
        if type(value) is dict and value.get("status") == "SENDING":
            assert json.loads(path.read_text())["status"] == "SENDING"
            intent_seen = True

    monkeypatch.setattr(connection.files, "write", durable_write)

    def metadata():
        result = copy.deepcopy(raw)
        for sheet in result["sheets"]:
            sheet.pop("data", None)
        return result

    def handle(request):
        nonlocal batch_seen
        calls.append((request.method, request.url.host, request.url.path))
        if intent_seen and not batch_seen:
            assert request.method == "POST"
            assert request.url.path.endswith(":batchUpdate")
        if request.url.host == "oauth2.googleapis.com":
            assert not intent_seen
            assert request.method == "POST" and request.url.path == "/token"
            return httpx.Response(
                200,
                json={
                    "access_token": "fictional_access",
                    "token_type": "Bearer",
                    "expires_in": 3600,
                    "scope": "https://www.googleapis.com/auth/spreadsheets",
                },
            )
        assert request.url.host == "sheets.googleapis.com"
        assert request.headers["Authorization"] == "Bearer fictional_access"
        expected = "/v4/spreadsheets/fictional-book"
        if request.method == "POST":
            assert intent_seen and not batch_seen
            assert request.url.path == expected + ":batchUpdate"
            batch_seen = True
            assert json.loads(request.content) == {
                "requests": plan["transfer"]["requests"],
                "includeSpreadsheetInResponse": False,
            }
            if outcome == "timeout":
                raise httpx.ReadTimeout("Fictional reply lost", request=request)
            if outcome.startswith("http"):
                return httpx.Response(int(outcome[4:]), json={"error": {}})
            update = json.loads(request.content)["requests"][0]["updateCells"]
            target = next(
                s
                for s in raw["sheets"]
                if s["properties"]["sheetId"] == update["start"]["sheetId"]
            )
            row, col = update["start"]["rowIndex"], update["start"]["columnIndex"]
            target["data"][0]["rowData"][row]["values"][col].update(
                update["rows"][0]["values"][0]
            )
            return httpx.Response(
                200, json={"spreadsheetId": "fictional-book", "replies": [{}]}
            )
        assert request.method == "GET" and request.url.path == expected
        if not request.url.params.get("includeGridData"):
            return httpx.Response(200, json=metadata())
        requested = request.url.params.get("ranges")
        result = metadata()
        for sheet in result["sheets"]:
            title = sheet["properties"]["title"].replace("'", "''")
            if requested.startswith("'" + title + "'!"):
                original = next(
                    s
                    for s in raw["sheets"]
                    if s["properties"]["sheetId"] == sheet["properties"]["sheetId"]
                )
                sheet["data"] = copy.deepcopy(original["data"])
        return httpx.Response(200, json=result)

    google = GoogleSheets(
        "fictional-book",
        credential,
        transport=httpx.MockTransport(handle),
        read_interval_seconds=0,
    )

    async def read_context():
        return {
            "raw": await google.read_workbook(),
            "current": context["current"],
            "pin_binding": context["pin_binding"],
        }

    async def write_requests(book, requests):
        assert book == google.workbook_id
        return await google.send_preflighted_batch(requests)

    try:
        result = await execute_local_edit_once(
            connection,
            plan,
            expected_plan_sha256=digest(plan),
            output_root=root,
            read_context=read_context,
            write_requests=write_requests,
            enabled=True,
        )
        expected = (
            "PLANNED_OUTPUT_OBSERVED"
            if outcome == "success"
            else "UNCERTAIN_RECONCILIATION_REQUIRED"
        )
        assert result["status"] == expected
        result = await execute_local_edit_once(
            connection,
            plan,
            expected_plan_sha256=digest(plan),
            output_root=root,
            read_context=read_context,
            write_requests=write_requests,
            enabled=True,
        )
        assert result["status"] == expected
    finally:
        await google.close()
    assert sum(path.endswith(":batchUpdate") for _, _, path in calls) == 1
    assert sum(host == "oauth2.googleapis.com" for _, host, _ in calls) == 1
    assert result["canvas_writes"] == 0
    assert result["retry_writes"] is False
