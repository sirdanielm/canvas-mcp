"""Fictional direct transport coverage; no account, data or live network."""

import asyncio
import copy
import json
import socket
import time

import httpx
import pytest
from test_gradebook import snapshot as snapshot
from test_gradebook_native import binding as binding
from test_private_proposed_edit import scenario as scenario

from canvas_mcp.gradebook import google as google_module
from canvas_mcp.gradebook.client import GradebookError
from canvas_mcp.gradebook.google import GoogleSheets
from canvas_mcp.gradebook.unit2_metadata_collections import (
    MASK,
    observe_direct_metadata_collections,
)


@pytest.fixture(autouse=True)
def deny_network(monkeypatch):
    def deny(*args, **kwargs):
        raise AssertionError("REAL_NETWORK_FORBIDDEN")

    monkeypatch.setattr(socket.socket, "connect", deny)
    monkeypatch.setattr(socket.socket, "connect_ex", deny)
    monkeypatch.setattr(socket, "create_connection", deny)


@pytest.fixture
def direct(tmp_path, scenario, monkeypatch):
    raw = copy.deepcopy(scenario["raw"])
    for sheet in raw["sheets"]:
        sheet.pop("data", None)
    raw.pop("namedRanges", None)
    for s in raw["sheets"]:
        s.pop("merges", None)
    p = tmp_path / "fictional-credential.json"
    p.write_text(
        json.dumps(
            {
                "tokens": {
                    "gradebook": {
                        "type": "authorized_user",
                        "client_id": "fictional",
                        "client_secret": "fictional",
                        "refresh_token": "fictional",
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    p.chmod(0o600)
    client = GoogleSheets(raw["spreadsheetId"], p)
    client._authorized = True
    client._access_token = "FICTIONAL"
    client._expires_at = time.monotonic() + 1000
    requests = []

    async def handle(request):
        requests.append(request)
        return httpx.Response(200, json=copy.deepcopy(raw))

    monkeypatch.setattr(client.http._transport, "handle_async_request", handle)
    return client, raw, requests


def run(direct, **kw):
    c, raw, requests = direct

    async def execute():
        try:
            return await observe_direct_metadata_collections(
                c,
                expected_workbook_id=kw.get("book", raw["spreadsheetId"]),
                sheet_id=kw.get("sid", 2),
            )
        finally:
            await c.close()

    return asyncio.run(execute())


def test_omitted_repeated_is_separate_inference_not_raw_array(direct):
    c, raw, requests = direct
    before = copy.deepcopy(raw)
    result = run(direct)
    assert result["raw"] == before and raw == before
    assert "namedRanges" not in result["raw"]
    assert "merges" not in next(
        s for s in result["raw"]["sheets"] if s["properties"]["sheetId"] == 2
    )
    assert all(
        v["is_protocol_inference"] is True
        and v["derived_entries"] == ()
        and v["raw_value"] is None
        for v in result["collections"].values()
    )
    assert len(requests) == 1 and requests[0].method == "GET"
    assert list(requests[0].url.params.multi_items()) == [
        ("fields", MASK),
        ("prettyPrint", "false"),
    ]
    assert (
        result["permission_or_write_authority_granted"] is False
        and result["protection_defaults_inferred"] is False
    )


def test_present_arrays_keep_every_entry_and_are_not_inferences(direct):
    c, raw, requests = direct
    raw["namedRanges"] = [
        {"name": "Fictional", "namedRangeId": "n", "range": {"sheetId": 2}}
    ]
    next(s for s in raw["sheets"] if s["properties"]["sheetId"] == 2)["merges"] = [
        {
            "sheetId": 2,
            "startRowIndex": 1,
            "endRowIndex": 2,
            "startColumnIndex": 1,
            "endColumnIndex": 3,
        }
    ]
    r = run(direct)
    assert all(
        v["raw_present"] is True
        and v["is_protocol_inference"] is False
        and len(v["derived_entries"]) == 1
        for v in r["collections"].values()
    )


@pytest.mark.parametrize(
    "field,value",
    [("namedRanges", None), ("namedRanges", {}), ("merges", None), ("merges", [1])],
)
def test_wrong_present_types_never_default_to_empty(direct, field, value):
    c, raw, requests = direct
    obj = (
        raw
        if field == "namedRanges"
        else next(s for s in raw["sheets"] if s["properties"]["sheetId"] == 2)
    )
    obj[field] = value
    with pytest.raises(GradebookError):
        run(direct)


def test_wrong_book_holds_before_get(direct):
    with pytest.raises(GradebookError, match="IDENTITY_REQUIRED"):
        run(direct, book="different")
    assert not direct[2]


def test_missing_sheet_holds_after_get(direct):
    with pytest.raises(GradebookError, match="EXACT_SHEET_REQUIRED"):
        run(direct, sid=999)


def test_changed_fieldmask_cannot_claim_coverage(direct, monkeypatch):
    monkeypatch.setattr(
        google_module, "METADATA_FIELDS", "spreadsheetId,sheets(properties)"
    )
    with pytest.raises(GradebookError, match="UNFILTERED_METADATA_ROUTE"):
        run(direct)
    assert not direct[2]


def test_replaced_fetcher_cannot_claim_direct_unranged_proof(direct):
    async def partial():
        return direct[1]

    direct[0].metadata = partial
    with pytest.raises(GradebookError, match="UNFILTERED_METADATA_ROUTE"):
        run(direct)
    assert not direct[2]


def test_unsuccessful_response_cannot_create_semantic_proof(direct, monkeypatch):
    async def handle(request):
        return httpx.Response(403, json={"error": {"message": "fictional refusal"}})

    monkeypatch.setattr(direct[0].http._transport, "handle_async_request", handle)
    with pytest.raises(GradebookError):
        run(direct)


def test_replaced_endpoint_cannot_claim_google_coverage(direct):
    direct[0].url = "https://fictional.invalid/proxy"
    with pytest.raises(GradebookError, match="UNFILTERED_METADATA_ROUTE"):
        run(direct)
    assert not direct[2]


def test_response_hook_cannot_prune_metadata(direct):
    async def pruning(response):
        pass

    direct[0].http.event_hooks = {"request": [], "response": [pruning]}
    with pytest.raises(GradebookError, match="UNFILTERED_METADATA_ROUTE"):
        run(direct)
    assert not direct[2]


def test_proxy_pool_cannot_claim_direct_metadata(direct):
    client = direct[0]
    original = client.http._transport._pool

    class FictionalProxy:
        async def aclose(self):
            await original.aclose()

    client.http._transport._pool = FictionalProxy()
    with pytest.raises(GradebookError, match="UNFILTERED_METADATA_ROUTE"):
        run(direct)
    assert not direct[2]


@pytest.mark.parametrize("field", ["properties", "basicFilter"])
def test_chunk_metadata_preserves_number_and_boolean_native_types(field):
    expected = {
        "properties": {"sheetId": 7, "index": 0},
        "basicFilter": {"range": {"sheetId": 7, "startRowIndex": 0}},
    }
    observed = copy.deepcopy(expected)
    if field == "properties":
        observed[field]["index"] = False
    else:
        observed[field]["range"]["startRowIndex"] = False
    assert not GoogleSheets._chunk_header_matches(observed, expected)


def test_present_empty_filter_does_not_replace_known_nonempty_filter():
    expected = {
        "properties": {"sheetId": 7},
        "basicFilter": {"range": {"sheetId": 7}},
    }
    assert not GoogleSheets._chunk_header_matches(
        {"properties": {"sheetId": 7}, "basicFilter": {}}, expected
    )
    assert GoogleSheets._chunk_header_matches({"properties": {"sheetId": 7}}, expected)
    assert GoogleSheets._chunk_header_matches(
        {"properties": {"sheetId": 7}, "basicFilter": {}},
        {"properties": {"sheetId": 7}, "basicFilter": {}},
    )
