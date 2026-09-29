"""Synthetic Google transport checks. No real credentials or external writes."""

import copy
import json
import os
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
        WORKBOOK, credentials, transport=httpx.MockTransport(fixture.handle)
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
    assert result == fixture.grid
    assert credentials.read_bytes() == original
    assert os.stat(credentials).st_mode & 0o777 == 0o600
    request = fixture.requests[-1]
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
    assert fixture.requests[-1].url.params.get_list("ranges") == [
        "'Teacher''s Reference'!A1:J10"
    ]


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
