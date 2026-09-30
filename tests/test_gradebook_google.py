"""Synthetic Google transport checks. No real credentials or external writes."""

import copy
import json
import os
import re
import time

import httpx
import pytest

from canvas_mcp.gradebook.client import GradebookError
from canvas_mcp.gradebook.google import GoogleSheets

WORKBOOK = "fictional_workbook"
SCOPE = "https://www.googleapis.com/auth/spreadsheets"


def sheet(sid=1, name="Core GET", rows=10, columns=10):
    return {
        "properties": {
            "sheetId": sid,
            "title": name,
            "sheetType": "GRID",
            "gridProperties": {"rowCount": rows, "columnCount": columns},
        },
        "protectedRanges": [{"protectedRangeId": 9, "range": {"sheetId": sid}}],
    }


class GoogleFixture:
    def __init__(self):
        self.requests = []
        self.token = {
            "access_token": "fictional_access",
            "token_type": "Bearer",
            "expires_in": 3600,
            "scope": SCOPE,
        }
        self.info = {"scope": SCOPE, "aud": "fictional_client"}
        self.metadata = {
            "spreadsheetId": WORKBOOK,
            "sheets": [sheet()],
            "developerMetadata": [{"metadataKey": "fixture", "metadataValue": "1"}],
        }
        self.metadata["sheets"][0]["conditionalFormats"] = [{"ranges": []}]
        self.metadata["sheets"][0]["basicFilter"] = {"range": {"sheetId": 1}}
        self.grid = copy.deepcopy(self.metadata)
        self.grid["sheets"][0]["data"] = [
            {
                "rowData": [
                    {
                        "values": [
                            {
                                "userEnteredValue": {
                                    "stringValue": "Fictional literal"
                                },
                                "userEnteredFormat": {"backgroundColor": {"red": 1}},
                                "note": "Fictional note",
                                "dataValidation": {"strict": True},
                            }
                        ]
                    }
                ],
                "rowMetadata": [{"hiddenByUser": True}],
                "columnMetadata": [{}],
            }
        ]
        self.grid["sheets"][0]["conditionalFormats"] = [{"ranges": []}]
        self.grid["sheets"][0]["basicFilter"] = {"range": {"sheetId": 1}}
        self.failures = {}

    def handle(self, request):
        self.requests.append(request)
        kind = (
            "token"
            if request.url.path == "/token"
            else (
                "info"
                if request.url.path == "/tokeninfo"
                else (
                    "batch"
                    if request.url.path.endswith(":batchUpdate")
                    else (
                        "grid"
                        if request.url.params.get("includeGridData")
                        else "metadata"
                    )
                )
            )
        )
        failure = self.failures.get(kind)
        if failure:
            return failure(request)
        if kind == "token":
            assert request.method == "POST"
            assert request.url.host == "oauth2.googleapis.com"
            return httpx.Response(200, json=self.token)
        if kind == "info":
            assert request.url.host == "oauth2.googleapis.com"
            return httpx.Response(200, json=self.info)
        assert request.headers["Authorization"] == "Bearer fictional_access"
        assert request.url.host == "sheets.googleapis.com"
        assert request.url.path == f"/v4/spreadsheets/{WORKBOOK}" + (
            ":batchUpdate" if kind == "batch" else ""
        )
        if kind == "batch":
            assert request.method == "POST"
            return httpx.Response(
                200, json={"spreadsheetId": WORKBOOK, "replies": [{}]}
            )
        assert request.method == "GET"
        return httpx.Response(200, json=self.grid if kind == "grid" else self.metadata)


@pytest.fixture
def credentials(tmp_path):
    path = tmp_path / "google.json"
    path.write_text(
        json.dumps(
            {
                "tokens": {
                    "gradebook": {
                        "type": "authorized_user",
                        "client_id": "fictional_client",
                        "client_secret": "fictional_secret",
                        "refresh_token": "fictional_refresh",
                        "access_token": "ignored_saved_access",
                        "expiry_date": 1,
                    }
                }
            }
        )
    )
    path.chmod(0o600)
    return path


@pytest.fixture
async def google(credentials):
    fixture = GoogleFixture()
    client = GoogleSheets(
        WORKBOOK,
        credentials,
        transport=httpx.MockTransport(fixture.handle),
        read_interval_seconds=0,
    )
    try:
        yield client, fixture
    finally:
        await client.close()


async def test_native_read_preserves_required_fields_and_private_credential(
    google, credentials
):
    client, fixture = google
    original = credentials.read_bytes()
    result = await client.read_workbook()
    assert assembled_grid(result) == assembled_grid(fixture.grid)
    for key in ("properties", "protectedRanges", "conditionalFormats", "basicFilter"):
        assert result["sheets"][0][key] == fixture.grid["sheets"][0][key]
    assert result["developerMetadata"] == fixture.grid["developerMetadata"]
    assert credentials.read_bytes() == original
    assert os.stat(credentials).st_mode & 0o777 == 0o600
    request = next(r for r in fixture.requests if r.url.params.get("includeGridData"))
    assert request.url.params.get_list("ranges") == ["'Core GET'!A1:J10"]
    fields = request.url.params["fields"]
    assert all(
        name in fields
        for name in (
            "developerMetadata",
            "userEnteredValue",
            "userEnteredFormat",
            "note",
            "dataValidation",
            "rowMetadata",
            "columnMetadata",
            "protectedRanges",
            "conditionalFormats",
            "basicFilter",
        )
    )
    assert not any("export" in str(r.url) for r in fixture.requests)


async def test_sheet_names_are_metadata_grounded_and_a1_escaped(google):
    client, fixture = google
    fixture.metadata["sheets"] = [sheet(name="Teacher's Reference")]
    fixture.grid = copy.deepcopy(fixture.metadata)
    await client.read_workbook()
    request = next(r for r in fixture.requests if r.url.params.get("includeGridData"))
    assert request.url.params.get_list("ranges") == ["'Teacher''s Reference'!A1:J10"]


@pytest.mark.parametrize(
    "change",
    [
        lambda m: m.update(spreadsheetId="wrong_workbook"),
        lambda m: m["sheets"].append(copy.deepcopy(m["sheets"][0])),
        lambda m: m["sheets"][0]["properties"].update(sheetId=True),
        lambda m: m["sheets"][0]["properties"].update(sheetType="OBJECT"),
        lambda m: m["sheets"][0]["properties"]["gridProperties"].update(rowCount=0),
        lambda m: m["sheets"][0]["properties"]["gridProperties"].update(rowCount=1001),
        lambda m: m["sheets"][0]["properties"]["gridProperties"].update(
            columnCount=259
        ),
        lambda m: m.update(sheets=[sheet(name="Reference", rows=1000, columns=51)]),
    ],
)
async def test_metadata_failures_prevent_grid_read(google, change):
    client, fixture = google
    change(fixture.metadata)
    with pytest.raises(GradebookError):
        await client.read_workbook()
    assert not any(r.url.params.get("includeGridData") for r in fixture.requests)


async def test_total_limit_applies_before_grid_request(credentials):
    fixture = GoogleFixture()
    fixture.metadata["sheets"].append(sheet(2, "Reference"))
    client = GoogleSheets(
        WORKBOOK,
        credentials,
        transport=httpx.MockTransport(fixture.handle),
        read_interval_seconds=0,
        max_total_cells=150,
    )
    try:
        with pytest.raises(GradebookError, match="total cell limit"):
            await client.read_workbook()
    finally:
        await client.close()


async def test_configured_sheet_limit_applies(credentials):
    fixture = GoogleFixture()
    client = GoogleSheets(
        WORKBOOK,
        credentials,
        transport=httpx.MockTransport(fixture.handle),
        read_interval_seconds=0,
        sheet_cell_limits={"Core GET": 50},
    )
    try:
        with pytest.raises(GradebookError, match="configured cell limit"):
            await client.metadata()
    finally:
        await client.close()


@pytest.mark.parametrize(
    "mutation",
    [
        lambda w: w["sheets"][0]["properties"].update(title="Renamed"),
        lambda w: w["sheets"][0]["data"].append({}),
        lambda w: w["sheets"][0]["data"][0].update(startRow=1),
        lambda w: w["sheets"][0]["data"][0].update(rowData=[{}] * 11),
        lambda w: w["sheets"][0]["data"][0].update(columnMetadata=[{}] * 11),
        lambda w: w["sheets"][0]["data"][0].update(rowData=[{"values": [{}] * 11}]),
        lambda w: w["sheets"][0]["data"][0].update(rowData=[{"values": ["bad"]}]),
    ],
)
async def test_grid_mismatch_or_overflow_never_truncates(google, mutation):
    client, fixture = google
    mutation(fixture.grid)
    with pytest.raises(GradebookError):
        await client.read_workbook()


async def test_scope_handshake_uses_tokeninfo_only_when_needed(google):
    client, fixture = google
    del fixture.token["scope"]
    fixture.info["scope"] = "https://www.googleapis.com/auth/drive.file"
    await client.metadata()
    await client.metadata()
    assert sum(r.url.path == "/tokeninfo" for r in fixture.requests) == 1


@pytest.mark.parametrize(
    "scope", ["", "https://www.googleapis.com/auth/spreadsheets.readonly", "unexpected"]
)
async def test_insufficient_scope_stops_before_workbook_read(google, scope):
    client, fixture = google
    fixture.token["scope"] = scope
    with pytest.raises(GradebookError, match="write scope"):
        await client.metadata()
    assert len(fixture.requests) == 1


async def test_tokeninfo_audience_mismatch_is_held(google):
    client, fixture = google
    del fixture.token["scope"]
    fixture.info["aud"] = "different_client"
    with pytest.raises(GradebookError, match="audience"):
        await client.metadata()


async def test_read_401_refreshes_once(google):
    client, fixture = google
    calls = 0

    def expired(_):
        nonlocal calls
        calls += 1
        return httpx.Response(401 if calls == 1 else 200, json=fixture.metadata)

    fixture.failures["metadata"] = expired
    await client.metadata()
    assert calls == 2
    assert sum(r.url.path == "/token" for r in fixture.requests) == 2


async def test_service_disabled_error_is_actionable_and_sanitized(google):
    client, fixture = google
    fixture.failures["metadata"] = lambda _: httpx.Response(
        403,
        json={
            "error": {
                "message": "fictional private record and secret",
                "details": [
                    {
                        "reason": "SERVICE_DISABLED",
                        "metadata": {"credential": "fictional_secret"},
                    }
                ],
            }
        },
    )
    with pytest.raises(GradebookError) as error:
        await client.metadata()
    assert str(error.value) == "Google read stopped: HTTP 403 (SERVICE_DISABLED)."


async def test_malformed_provider_reason_never_leaks_response(google):
    client, fixture = google
    fixture.failures["metadata"] = lambda _: httpx.Response(
        403, json={"error": {"details": [{"reason": ["fictional_secret"]}]}}
    )
    with pytest.raises(GradebookError) as error:
        await client.metadata()
    assert str(error.value) == "Google read stopped: HTTP 403."


async def test_auth_refresh_retry_is_bounded(google, monkeypatch):
    client, fixture = google

    async def no_sleep(_):
        return None

    monkeypatch.setattr("canvas_mcp.gradebook.google.asyncio.sleep", no_sleep)
    fixture.failures["token"] = lambda _: httpx.Response(
        503, json={"error": "fictional_secret"}
    )
    with pytest.raises(GradebookError, match="OAuth refresh failed"):
        await client.metadata()
    assert len(fixture.requests) == 3
    assert all(r.url.path == "/token" for r in fixture.requests)


async def test_batch_payload_and_endpoint_are_fixed(google):
    client, fixture = google
    request = {"updateCells": {"start": {"sheetId": 1}, "fields": "userEnteredValue"}}
    assert (await client.batch([request]))["spreadsheetId"] == WORKBOOK
    assert json.loads(fixture.requests[-1].content) == {
        "requests": [request],
        "includeSpreadsheetInResponse": False,
    }


async def test_preflighted_batch_has_exactly_one_outbound_post(google):
    client, fixture = google
    await client.read_workbook()
    fixture.requests.clear()
    await client.send_preflighted_batch([{"updateCells": {}}])
    assert [(r.method, r.url.path) for r in fixture.requests] == [
        ("POST", f"/v4/spreadsheets/{WORKBOOK}:batchUpdate")
    ]


@pytest.mark.parametrize(
    "invalidate", ["expired", "not_verified", "token_replaced", "not_authorized"]
)
async def test_preflighted_batch_refuses_without_fresh_token_before_http(
    google, invalidate
):
    client, fixture = google
    await client.metadata()
    fixture.requests.clear()
    if invalidate == "expired":
        client._expires_at = time.monotonic() - 1
    elif invalidate == "not_verified":
        client._validated_token = None
    elif invalidate == "token_replaced":
        client._access_token = "different_fictional_token"
    else:
        client._authorized = False
    with pytest.raises(GradebookError, match="verified workbook read and unexpired"):
        await client.send_preflighted_batch([{"updateCells": {}}])
    assert fixture.requests == []


async def test_preflighted_expiry_uses_existing_sixty_second_cushion(google):
    client, fixture = google
    await client.metadata()
    fixture.requests.clear()
    client._expires_at = time.monotonic() + 30
    await client.send_preflighted_batch([{"updateCells": {}}])
    assert len(fixture.requests) == 1


@pytest.mark.parametrize("status", [401, 429, 500, 503])
async def test_preflighted_http_failure_never_retries_any_request(google, status):
    client, fixture = google
    await client.metadata()
    fixture.requests.clear()
    fixture.failures["batch"] = lambda _: httpx.Response(
        status, json={"error": "fictional_secret"}
    )
    with pytest.raises(GradebookError, match="reconcile"):
        await client.send_preflighted_batch([{"updateCells": {}}])
    assert len(fixture.requests) == 1
    assert fixture.requests[0].url.path.endswith(":batchUpdate")


async def test_preflighted_timeout_never_refreshes_or_retries(google):
    client, fixture = google
    await client.metadata()
    fixture.requests.clear()

    def timeout(request):
        raise httpx.ReadTimeout("fictional_secret", request=request)

    fixture.failures["batch"] = timeout
    with pytest.raises(GradebookError, match="no automatic write retry"):
        await client.send_preflighted_batch([{"updateCells": {}}])
    assert len(fixture.requests) == 1


@pytest.mark.parametrize("status", [401, 403, 429, 500, 502, 503, 504])
async def test_batch_http_failure_never_retries_or_refreshes_token(google, status):
    client, fixture = google
    fixture.failures["batch"] = lambda _: httpx.Response(
        status, json={"error": "fictional_secret"}
    )
    with pytest.raises(GradebookError, match="reconcile"):
        await client.batch([{"updateCells": {}}])
    assert sum(r.url.path.endswith(":batchUpdate") for r in fixture.requests) == 1
    assert sum(r.url.path == "/token" for r in fixture.requests) == 1


async def test_batch_transport_failure_is_not_retried(google):
    client, fixture = google

    def timeout(request):
        raise httpx.ReadTimeout("fictional_secret", request=request)

    fixture.failures["batch"] = timeout
    with pytest.raises(GradebookError, match="no automatic write retry"):
        await client.batch([{"updateCells": {}}])
    assert sum(r.url.path.endswith(":batchUpdate") for r in fixture.requests) == 1


async def test_read_retry_is_bounded(google, monkeypatch):
    client, fixture = google

    async def no_sleep(_):
        return None

    monkeypatch.setattr("canvas_mcp.gradebook.google.asyncio.sleep", no_sleep)
    fixture.failures["metadata"] = lambda _: httpx.Response(
        503, json={"error": "fictional_secret"}
    )
    with pytest.raises(GradebookError, match="HTTP 503"):
        await client.metadata()
    assert sum(r.url.path.endswith(WORKBOOK) for r in fixture.requests) == 3


class Chunks(httpx.AsyncByteStream):
    async def __aiter__(self):
        yield b"x" * 60
        yield b"x" * 60


async def test_streaming_response_limit_applies_without_content_length(credentials):
    fixture = GoogleFixture()
    fixture.failures["metadata"] = lambda _: httpx.Response(200, stream=Chunks())
    client = GoogleSheets(
        WORKBOOK,
        credentials,
        transport=httpx.MockTransport(fixture.handle),
        read_interval_seconds=0,
        max_response_bytes=100,
    )
    try:
        with pytest.raises(GradebookError, match="size limit"):
            await client.metadata()
    finally:
        await client.close()


async def test_redirect_does_not_send_credentials_to_new_host(google):
    client, fixture = google
    fixture.failures["metadata"] = lambda _: httpx.Response(
        302, json={}, headers={"Location": "https://evil.example"}
    )
    with pytest.raises(GradebookError, match="HTTP 302"):
        await client.metadata()
    assert all(r.url.host != "evil.example" for r in fixture.requests)


@pytest.mark.parametrize("mode", [0o644, 0o640, 0o606])
def test_insecure_credentials_are_rejected(credentials, mode):
    credentials.chmod(mode)
    with pytest.raises(GradebookError, match="owner-only"):
        GoogleSheets(WORKBOOK, credentials)


def test_credential_symlink_is_rejected(credentials):
    link = credentials.parent / "linked.json"
    link.symlink_to(credentials)
    with pytest.raises(GradebookError, match="symlink"):
        GoogleSheets(WORKBOOK, link)


def test_profile_is_explicit_and_never_falls_back(credentials):
    with pytest.raises(GradebookError, match="unavailable or invalid"):
        GoogleSheets(WORKBOOK, credentials, profile="other")


@pytest.mark.parametrize(
    "value", ["../other", "https://evil.example", "id?access_token=x"]
)
def test_invalid_workbook_id_is_rejected_before_credentials(credentials, value):
    with pytest.raises(GradebookError, match="identity"):
        GoogleSheets(value, credentials)


class ChunkedGoogleFixture(GoogleFixture):
    """Slice a fixed synthetic grid independently of the adapter's assembler."""

    def __init__(self, rows=7, columns=4):
        super().__init__()
        self.metadata["sheets"] = [sheet(rows=rows, columns=columns)]
        self.metadata["sheets"][0]["conditionalFormats"] = [{"ranges": []}]
        self.metadata["sheets"][0]["basicFilter"] = {"range": {"sheetId": 1}}
        self.values = {
            (r, c): {
                "userEnteredValue": {"numberValue": 100 * r + c},
                "userEnteredFormat": {"backgroundColor": {"red": 0.25}},
                "note": f"Fictional cell {r}:{c}",
                "dataValidation": {"strict": True},
            }
            for r in range(rows)
            for c in range(columns)
            if (r + c) % 3
        }
        self.row_dimensions = [{"pixelSize": 20 + r} for r in range(rows)]
        self.column_dimensions = [{"pixelSize": 80 + c} for c in range(columns)]
        self.grid_calls = []
        self.mutate_chunk = lambda body, bounds, index: None
        self.failures["grid"] = self.grid_response

    @staticmethod
    def column_number(name):
        result = 0
        for char in name:
            result = 26 * result + ord(char) - ord("A") + 1
        return result - 1

    def grid_response(self, request):
        ranges = request.url.params.get_list("ranges")
        assert len(ranges) == 1
        match = re.fullmatch(r"'Core GET'!([A-Z]+)(\d+):([A-Z]+)(\d+)", ranges[0])
        assert match, ranges
        c0, r0, c1, r1 = match.groups()
        bounds = (
            int(r0) - 1,
            int(r1),
            self.column_number(c0),
            self.column_number(c1) + 1,
        )
        self.grid_calls.append(bounds)
        rs, re_, cs, ce = bounds
        body = copy.deepcopy(self.metadata)
        body["sheets"][0]["data"] = [
            {
                "startRow": rs,
                "startColumn": cs,
                "rowData": [
                    {
                        "values": [
                            copy.deepcopy(self.values.get((r, c), {}))
                            for c in range(cs, ce)
                        ]
                    }
                    for r in range(rs, re_)
                ],
                "rowMetadata": copy.deepcopy(self.row_dimensions[rs:re_]),
                "columnMetadata": copy.deepcopy(self.column_dimensions[cs:ce]),
            }
        ]
        self.mutate_chunk(body, bounds, len(self.grid_calls))
        return httpx.Response(200, json=body)


def assembled_grid(raw):
    cells, rows, columns = {}, {}, {}
    for block in raw["sheets"][0].get("data", []):
        rs, cs = block.get("startRow", 0), block.get("startColumn", 0)
        for ri, row in enumerate(block.get("rowData", []), rs):
            for ci, value in enumerate(row.get("values", []), cs):
                if value:
                    assert (ri, ci) not in cells
                    cells[ri, ci] = value
        for key, start, target in (
            ("rowMetadata", rs, rows),
            ("columnMetadata", cs, columns),
        ):
            for index, value in enumerate(block.get(key, []), start):
                if value:
                    assert index not in target
                    target[index] = value
    return cells, rows, columns


def assert_no_sheet_writes(fixture):
    assert all(
        request.method == "GET" or request.url.path == "/token"
        for request in fixture.requests
    )


@pytest.mark.parametrize("chunk_cells", [12, 3])
async def test_chunks_assemble_sparse_cells_and_native_fields(credentials, chunk_cells):
    fixture = ChunkedGoogleFixture()
    client = GoogleSheets(
        WORKBOOK,
        credentials,
        transport=httpx.MockTransport(fixture.handle),
        read_interval_seconds=0,
        max_chunk_cells=chunk_cells,
    )
    try:
        result = await client.read_workbook()
    finally:
        await client.close()
    cells, rows, columns = assembled_grid(result)
    assert cells == fixture.values
    assert rows == dict(enumerate(fixture.row_dimensions))
    assert columns == dict(enumerate(fixture.column_dimensions))
    assert (
        result["sheets"][0]["protectedRanges"]
        == fixture.metadata["sheets"][0]["protectedRanges"]
    )
    assert result["sheets"][0]["basicFilter"] == {"range": {"sheetId": 1}}
    assert result["sheets"][0]["conditionalFormats"] == [{"ranges": []}]
    coverage = []
    for rs, re_, cs, ce in fixture.grid_calls:
        assert (re_ - rs) * (ce - cs) <= chunk_cells
        coverage.extend((r, c) for r in range(rs, re_) for c in range(cs, ce))
    assert len(coverage) == 28
    assert set(coverage) == {(r, c) for r in range(7) for c in range(4)}
    if chunk_cells == 12:
        assert fixture.grid_calls == [(0, 3, 0, 4), (3, 6, 0, 4), (6, 7, 0, 4)]
    assert not fixture.requests[-1].url.params.get("includeGridData")
    assert_no_sheet_writes(fixture)


async def test_empty_middle_chunk_preserves_later_cell_offsets(credentials):
    fixture = ChunkedGoogleFixture()
    fixture.values = {
        (0, 0): {"userEnteredValue": {"stringValue": "first"}},
        (6, 3): {"userEnteredValue": {"stringValue": "last"}},
    }
    fixture.row_dimensions = [{}] * 7
    fixture.column_dimensions = [{}] * 4

    def omit_empty(body, bounds, index):
        if index == 2:
            body["sheets"][0].pop("data")

    fixture.mutate_chunk = omit_empty
    client = GoogleSheets(
        WORKBOOK,
        credentials,
        transport=httpx.MockTransport(fixture.handle),
        read_interval_seconds=0,
        max_chunk_cells=12,
    )
    try:
        result = await client.read_workbook()
    finally:
        await client.close()
    assert assembled_grid(result)[0] == fixture.values
    assert_no_sheet_writes(fixture)


@pytest.mark.parametrize(
    "mutation",
    [
        lambda body, block: block.update(startRow=block["startRow"] + 1),
        lambda body, block: block.update(startColumn=1),
        lambda body, block: block.pop("startRow"),
        lambda body, block: block["rowData"].append({}),
        lambda body, block: block["rowData"][0]["values"].append({}),
        lambda body, block: block["rowMetadata"].append({}),
        lambda body, block: block["columnMetadata"].append({}),
        lambda body, block: body["sheets"][0]["data"].append({}),
        lambda body, block: body["sheets"][0]["properties"].update(title="changed"),
        lambda body, block: body["sheets"][0]["protectedRanges"][0].update(
            protectedRangeId=888
        ),
        lambda body, block: body["sheets"][0].update(
            conditionalFormats=[{"ranges": [{"sheetId": 1}]}]
        ),
        lambda body, block: body["sheets"][0].update(
            basicFilter={"range": {"sheetId": 1, "startRowIndex": 1}}
        ),
        lambda body, block: body.update(sheets=[]),
    ],
)
async def test_bad_second_chunk_holds_without_partial_result(credentials, mutation):
    fixture = ChunkedGoogleFixture()

    def mutate(body, bounds, index):
        if index == 2:
            mutation(body, body["sheets"][0]["data"][0])

    fixture.mutate_chunk = mutate
    client = GoogleSheets(
        WORKBOOK,
        credentials,
        transport=httpx.MockTransport(fixture.handle),
        read_interval_seconds=0,
        max_chunk_cells=12,
    )
    try:
        with pytest.raises(GradebookError):
            await client.read_workbook()
        assert client._validated_token is None
    finally:
        await client.close()
    assert len(fixture.grid_calls) == 2
    assert_no_sheet_writes(fixture)


@pytest.mark.parametrize("dimension", ["rowMetadata", "columnMetadata"])
async def test_repeated_dimension_metadata_must_match(credentials, dimension):
    fixture = ChunkedGoogleFixture()

    def mutate(body, bounds, index):
        if index > 1:
            body["sheets"][0]["data"][0][dimension][0]["pixelSize"] = 999

    fixture.mutate_chunk = mutate
    client = GoogleSheets(
        WORKBOOK,
        credentials,
        transport=httpx.MockTransport(fixture.handle),
        read_interval_seconds=0,
        max_chunk_cells=3 if dimension == "rowMetadata" else 12,
    )
    try:
        with pytest.raises(GradebookError):
            await client.read_workbook()
    finally:
        await client.close()
    assert_no_sheet_writes(fixture)


@pytest.mark.parametrize("limit", ["max_total_response_bytes", "max_chunk_requests"])
async def test_chunk_read_has_finite_aggregate_budget(credentials, limit):
    fixture = ChunkedGoogleFixture()
    client = GoogleSheets(
        WORKBOOK,
        credentials,
        transport=httpx.MockTransport(fixture.handle),
        read_interval_seconds=0,
        max_chunk_cells=4,
        **{limit: 2000 if limit == "max_total_response_bytes" else 2},
    )
    try:
        with pytest.raises(GradebookError):
            await client.read_workbook()
    finally:
        await client.close()
    assert len(fixture.grid_calls) < 7
    assert_no_sheet_writes(fixture)


async def test_oversized_individual_chunk_is_not_silently_retried_or_truncated(
    credentials,
):
    fixture = ChunkedGoogleFixture()
    fixture.values[0, 0] = {"note": "fictional" * 1000}
    client = GoogleSheets(
        WORKBOOK,
        credentials,
        transport=httpx.MockTransport(fixture.handle),
        read_interval_seconds=0,
        max_chunk_cells=4,
        max_response_bytes=2000,
    )
    try:
        with pytest.raises(GradebookError, match="size limit"):
            await client.read_workbook()
    finally:
        await client.close()
    assert len(fixture.grid_calls) == 1
    assert_no_sheet_writes(fixture)


@pytest.mark.parametrize("change", ["inventory", "protection", "rule", "filter"])
async def test_final_metadata_changes_invalidate_all_chunks(credentials, change):
    fixture = ChunkedGoogleFixture()
    calls = 0

    def metadata_response(request):
        nonlocal calls
        calls += 1
        body = copy.deepcopy(fixture.metadata)
        if calls == 2:
            if change == "inventory":
                body["sheets"].append(sheet(2, "New reference"))
            elif change == "protection":
                body["sheets"][0]["protectedRanges"].clear()
            elif change == "rule":
                body["sheets"][0]["conditionalFormats"].clear()
            else:
                body["sheets"][0]["basicFilter"] = {}
        return httpx.Response(200, json=body)

    fixture.failures["metadata"] = metadata_response
    client = GoogleSheets(
        WORKBOOK,
        credentials,
        transport=httpx.MockTransport(fixture.handle),
        read_interval_seconds=0,
        max_chunk_cells=12,
    )
    try:
        with pytest.raises(GradebookError):
            await client.read_workbook()
    finally:
        await client.close()
    assert calls == 2
    assert len(fixture.grid_calls) == 3
    assert_no_sheet_writes(fixture)


class VirtualReadClock:
    def __init__(self):
        self.now = 100.0
        self.sleeps = []

    def __call__(self):
        return self.now

    async def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.now += seconds


async def test_default_read_pacing_spans_metadata_chunks_and_repeated_captures(
    credentials,
):
    fixture = ChunkedGoogleFixture()
    clock = VirtualReadClock()
    read_times = []

    def handle(request):
        if request.url.host == "sheets.googleapis.com":
            read_times.append(clock())
        return fixture.handle(request)

    client = GoogleSheets(
        WORKBOOK,
        credentials,
        transport=httpx.MockTransport(handle),
        max_chunk_cells=12,
        read_clock=clock,
        read_sleep=clock.sleep,
    )
    try:
        await client.read_workbook()
        await client.read_workbook()
    finally:
        await client.close()
    assert len(read_times) == 10
    assert [
        later - earlier
        for earlier, later in zip(read_times, read_times[1:], strict=False)
    ] == (pytest.approx([1.1] * 9))
    assert all(
        request.url.params.get("prettyPrint") == "false"
        for request in fixture.requests
        if request.url.host == "sheets.googleapis.com"
    )
    assert_no_sheet_writes(fixture)


async def test_transient_read_retry_also_obeys_default_pacing(credentials):
    fixture = GoogleFixture()
    clock = VirtualReadClock()
    attempts = []

    def transient(request):
        attempts.append(clock())
        if len(attempts) == 1:
            return httpx.Response(503, json={}, headers={"Retry-After": "0"})
        return httpx.Response(200, json=fixture.metadata)

    fixture.failures["metadata"] = transient
    client = GoogleSheets(
        WORKBOOK,
        credentials,
        transport=httpx.MockTransport(fixture.handle),
        read_clock=clock,
        read_sleep=clock.sleep,
    )
    try:
        await client.metadata()
    finally:
        await client.close()
    assert attempts == pytest.approx([100, 101.1])
    assert_no_sheet_writes(fixture)


async def test_retry_bytes_count_toward_aggregate_read_budget(credentials):
    fixture = GoogleFixture()
    metadata_size = len(httpx.Response(200, json=fixture.metadata).content)
    grid_size = len(httpx.Response(200, json=fixture.grid).content)
    attempts = 0

    def transient(request):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return httpx.Response(
                503,
                json={"error": {"message": "fictional" * 100}},
                headers={"Retry-After": "0"},
            )
        return httpx.Response(200, json=fixture.grid)

    fixture.failures["grid"] = transient
    client = GoogleSheets(
        WORKBOOK,
        credentials,
        transport=httpx.MockTransport(fixture.handle),
        read_interval_seconds=0,
        max_total_response_bytes=2 * metadata_size + grid_size + 50,
    )
    try:
        with pytest.raises(GradebookError, match="cumulative byte limit"):
            await client.read_workbook()
        assert client._validated_token is None
    finally:
        await client.close()
    assert attempts == 2
    assert_no_sheet_writes(fixture)


async def test_final_developer_metadata_is_retained_without_false_drift(credentials):
    fixture = ChunkedGoogleFixture()
    calls = 0

    def metadata(request):
        nonlocal calls
        calls += 1
        body = copy.deepcopy(fixture.metadata)
        if calls == 2:
            body["developerMetadata"] = [
                {"metadataKey": "latest_control", "metadataValue": "2"}
            ]
        return httpx.Response(200, json=body)

    fixture.failures["metadata"] = metadata
    client = GoogleSheets(
        WORKBOOK,
        credentials,
        transport=httpx.MockTransport(fixture.handle),
        read_interval_seconds=0,
        max_chunk_cells=12,
    )
    try:
        result = await client.read_workbook()
    finally:
        await client.close()
    assert result["developerMetadata"] == [
        {"metadataKey": "latest_control", "metadataValue": "2"}
    ]
    assert assembled_grid(result)[0] == fixture.values
    assert_no_sheet_writes(fixture)


@pytest.mark.parametrize("extra_data", [[], [{}], [{"startRow": 0}]])
async def test_nonrequested_sheet_may_only_supply_metadata(credentials, extra_data):
    fixture = GoogleFixture()
    fixture.metadata["sheets"].append(sheet(2, "Reference", rows=2, columns=2))
    fixture.grid["sheets"].append(copy.deepcopy(fixture.metadata["sheets"][1]))
    fixture.grid["sheets"][1]["data"] = extra_data
    calls = 0

    def grid(request):
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(200, json=fixture.grid)
        body = copy.deepcopy(fixture.metadata)
        body["sheets"][1]["data"] = [{"startRow": 0, "startColumn": 0}]
        return httpx.Response(200, json=body)

    fixture.failures["grid"] = grid
    client = GoogleSheets(
        WORKBOOK,
        credentials,
        transport=httpx.MockTransport(fixture.handle),
        read_interval_seconds=0,
    )
    try:
        if extra_data:
            with pytest.raises(GradebookError, match="unrequested sheet"):
                await client.read_workbook()
            assert calls == 1
        else:
            result = await client.read_workbook()
            assert len(result["sheets"]) == 2
            assert calls == 2
    finally:
        await client.close()
    assert_no_sheet_writes(fixture)


def fictional_rules():
    return [
        {
            "ranges": [
                {"sheetId": 1, "startRowIndex": index, "endRowIndex": index + 1}
            ],
            "booleanRule": {
                "condition": {
                    "type": "CUSTOM_FORMULA",
                    "values": [{"userEnteredValue": f"=A1={index}"}],
                },
                "format": {"backgroundColor": {"red": 0.25 * index}},
            },
        }
        for index in range(3)
    ]


@pytest.mark.parametrize("selection", [[], [0], [1], [0, 2]])
async def test_range_filtered_rules_keep_full_workbook_authority(
    credentials, selection
):
    fixture = ChunkedGoogleFixture()
    rules = fictional_rules()
    fixture.metadata["sheets"][0]["conditionalFormats"] = rules

    def filtered_rules(body, bounds, index):
        body["sheets"][0]["conditionalFormats"] = [
            copy.deepcopy(rules[i]) for i in selection
        ]

    fixture.mutate_chunk = filtered_rules
    client = GoogleSheets(
        WORKBOOK,
        credentials,
        transport=httpx.MockTransport(fixture.handle),
        read_interval_seconds=0,
        max_chunk_cells=12,
    )
    try:
        result = await client.read_workbook()
    finally:
        await client.close()
    assert result["sheets"][0]["conditionalFormats"] == rules
    assert assembled_grid(result)[0] == fixture.values
    assert_no_sheet_writes(fixture)


@pytest.mark.parametrize("mutation", ["changed", "unexpected", "reversed", "duplicate"])
async def test_filtered_rules_cannot_invent_change_or_reorder_authority(
    credentials, mutation
):
    fixture = ChunkedGoogleFixture()
    rules = fictional_rules()
    fixture.metadata["sheets"][0]["conditionalFormats"] = rules

    def bad_rules(body, bounds, index):
        returned = copy.deepcopy(rules)
        if mutation == "changed":
            returned[0]["booleanRule"]["format"]["backgroundColor"]["red"] = 0.99
        elif mutation == "unexpected":
            returned.append({"ranges": []})
        elif mutation == "reversed":
            returned = [returned[2], returned[0]]
        else:
            returned = [returned[0], returned[0]]
        body["sheets"][0]["conditionalFormats"] = returned

    fixture.mutate_chunk = bad_rules
    client = GoogleSheets(
        WORKBOOK,
        credentials,
        transport=httpx.MockTransport(fixture.handle),
        read_interval_seconds=0,
        max_chunk_cells=12,
    )
    try:
        with pytest.raises(GradebookError):
            await client.read_workbook()
        assert client._validated_token is None
    finally:
        await client.close()
    assert len(fixture.grid_calls) == 1
    assert_no_sheet_writes(fixture)


@pytest.mark.parametrize("field", ["protectedRanges", "basicFilter"])
async def test_range_filtered_header_omission_restores_complete_final_header(
    credentials, field
):
    fixture = ChunkedGoogleFixture()

    def omit_header(body, bounds, index):
        body["sheets"][0].pop(field)

    fixture.mutate_chunk = omit_header
    client = GoogleSheets(
        WORKBOOK,
        credentials,
        transport=httpx.MockTransport(fixture.handle),
        read_interval_seconds=0,
        max_chunk_cells=12,
    )
    try:
        result = await client.read_workbook()
    finally:
        await client.close()
    assert result["sheets"][0][field] == fixture.metadata["sheets"][0][field]
    assert assembled_grid(result)[0] == fixture.values
    assert_no_sheet_writes(fixture)
