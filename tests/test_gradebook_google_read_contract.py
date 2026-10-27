"""Independent read-only transport and native annotation contracts; synthetic data."""

import copy
from typing import Any

import httpx
import pytest
from test_gradebook_google import WORKBOOK, ChunkedGoogleFixture, GoogleFixture
from test_gradebook_google import credentials as credentials

from canvas_mcp.gradebook.client import GradebookError
from canvas_mcp.gradebook.google import GoogleSheets


@pytest.mark.parametrize("method", ["batch", "send_preflighted_batch", "_send_batch", "_json_request"])
async def test_read_only_refuses_every_batch_route_before_any_http(credentials: Any, method: str) -> None:
    def forbidden(request: httpx.Request) -> httpx.Response:
        raise AssertionError("Read-only write refusal must precede OAuth and Sheets HTTP")

    client = GoogleSheets(WORKBOOK, credentials, read_only=True, transport=httpx.MockTransport(forbidden))
    try:
        with pytest.raises(GradebookError, match="Read-only"):
            if method == "_json_request":
                await client._json_request("POST", client.url + ":batchUpdate", retry=False, payload={"requests": []})
            elif method == "_send_batch":
                await client._send_batch({"requests": []})
            else:
                await getattr(client, method)([{"updateCells": {}}])
    finally:
        await client.close()


async def test_read_only_scope_can_read_but_never_enable_batch(credentials: Any) -> None:
    fixture = GoogleFixture()
    fixture.token["scope"] = "https://www.googleapis.com/auth/spreadsheets.readonly"
    client = GoogleSheets(WORKBOOK, credentials, read_only=True, read_interval_seconds=0,
                          transport=httpx.MockTransport(fixture.handle))
    try:
        raw = await client.read_workbook()
        assert raw["spreadsheetId"] == WORKBOOK
        with pytest.raises(GradebookError, match="Read-only"):
            await client.send_preflighted_batch([{"updateCells": {}}])
    finally:
        await client.close()
    assert all(request.method == "GET" or request.url.path == "/token" for request in fixture.requests)


@pytest.mark.parametrize("read_only", [0, 1, "true", None])
def test_read_only_mode_requires_explicit_boolean(credentials: Any, read_only: Any) -> None:
    with pytest.raises(GradebookError, match="boolean"):
        GoogleSheets(WORKBOOK, credentials, read_only=read_only)


@pytest.mark.parametrize("key", ["protectedRanges", "merges", "conditionalFormats", "basicFilter"])
def test_header_preserves_unknown_omission(key: str) -> None:
    header = {"properties": {"sheetId": 1}}
    assert key not in GoogleSheets._header(header)
    header[key] = {} if key == "basicFilter" else []
    assert GoogleSheets._header(header)[key] == header[key]


async def test_filtered_annotation_omission_keeps_full_bracketing_facts(credentials: Any) -> None:
    fixture = ChunkedGoogleFixture()
    fixture.metadata["namedRanges"] = [{"namedRangeId": "fixture-range", "name": "Fictional", "range": {"sheetId": 1}}]
    fixture.metadata["sheets"][0]["merges"] = [{"sheetId": 1, "startRowIndex": 1, "endRowIndex": 2}]

    def omit(body: Any, bounds: Any, index: int) -> None:
        body.pop("namedRanges")
        for key in ("protectedRanges", "merges", "conditionalFormats", "basicFilter"):
            body["sheets"][0].pop(key)

    fixture.mutate_chunk = omit
    client = GoogleSheets(WORKBOOK, credentials, read_interval_seconds=0, max_chunk_cells=12,
                          transport=httpx.MockTransport(fixture.handle))
    try:
        result = await client.read_workbook()
    finally:
        await client.close()
    assert result["namedRanges"] == fixture.metadata["namedRanges"]
    for key in ("protectedRanges", "merges", "conditionalFormats", "basicFilter"):
        assert result["sheets"][0][key] == fixture.metadata["sheets"][0][key]
    grid_requests = [request for request in fixture.requests if request.url.params.get("includeGridData")]
    assert grid_requests and all("namedRanges" in r.url.params["fields"] and "merges" in r.url.params["fields"] for r in grid_requests)
    assert all(request.method == "GET" or request.url.path == "/token" for request in fixture.requests)


@pytest.mark.parametrize("change", ["invented_name", "typed_range_change", "order_change"])
async def test_chunk_annotations_cannot_change_or_reorder_full_authority(credentials: Any, change: str) -> None:
    fixture = ChunkedGoogleFixture()
    fixture.metadata["namedRanges"] = [
        {"namedRangeId": "one", "name": "FictionalOne", "range": {"sheetId": 1}},
        {"namedRangeId": "two", "name": "FictionalTwo", "range": {"sheetId": 1}},
    ]
    fixture.metadata["sheets"][0]["merges"] = [{"sheetId": 1, "startRowIndex": 1, "endRowIndex": 2}]

    def mutate(body: Any, bounds: Any, index: int) -> None:
        if change == "invented_name":
            body["namedRanges"][0]["name"] = "Changed"
        elif change == "order_change":
            body["namedRanges"].reverse()
        else:
            body["sheets"][0]["merges"][0]["startRowIndex"] = True

    fixture.mutate_chunk = mutate
    client = GoogleSheets(WORKBOOK, credentials, read_interval_seconds=0, max_chunk_cells=12,
                          transport=httpx.MockTransport(fixture.handle))
    try:
        with pytest.raises(GradebookError, match="changed between chunks"):
            await client.read_workbook()
    finally:
        await client.close()


async def test_omitted_to_explicit_empty_annotation_change_is_not_equivalent(credentials: Any) -> None:
    fixture = GoogleFixture()
    metadata_reads = 0
    original = fixture.handle

    def handle(request: httpx.Request) -> httpx.Response:
        nonlocal metadata_reads
        if request.url.host == "sheets.googleapis.com" and not request.url.params.get("includeGridData"):
            metadata_reads += 1
            if metadata_reads == 2:
                body = copy.deepcopy(fixture.metadata)
                body["namedRanges"] = []
                return httpx.Response(200, json=body)
        return original(request)

    client = GoogleSheets(WORKBOOK, credentials, read_interval_seconds=0, transport=httpx.MockTransport(handle))
    try:
        with pytest.raises(GradebookError, match="metadata changed during read"):
            await client.read_workbook()
    finally:
        await client.close()
