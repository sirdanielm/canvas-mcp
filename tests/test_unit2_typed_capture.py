"""Fictional native typed GET only; no credentials or network."""

from __future__ import annotations

import copy
import hashlib
import json
import os
from pathlib import Path
from typing import Any

import pytest

from canvas_mcp.gradebook.client import GradebookError
from canvas_mcp.gradebook.google import GoogleSheets
from canvas_mcp.gradebook.unit2_typed_capture import (
    CELL_FIELDS,
    TABS,
    capture_to_local_sink,
    file_ref,
    qualify_registration,
    validate_native_response,
    validate_request,
)


@pytest.fixture
def fixture(
    tmp_path: Path,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
    config = {
        "spreadsheet_id": "FICTIONAL_UNIT2_PROOF",
        "header_row": 6,
        "headers": {t: ["key", "value"] for t in TABS},
        "sheet_ids": {t: i for i, t in enumerate(TABS)},
        "table_capacities": dict.fromkeys(TABS, 5),
        "canvas_writes": False,
        "paid_calls": False,
    }
    p = tmp_path / "native.json"
    p.write_text(json.dumps(config), encoding="utf-8")
    review = tmp_path / "operator-review.json"
    review.write_text(json.dumps({"fictional": True}), encoding="utf-8")
    code = tmp_path / "fictional_code.py"
    code.write_text("# fictional source, not authority\n", encoding="utf-8")
    registration = {
        "schema": "UNIT2_LOCAL_TYPED_CAPTURE_REGISTRATION_V1",
        "transport_code_refs": {
            n: file_ref(code) for n in ["google", "endpoint", "cli"]
        },
        "state": "ACTIVE_REVIEWED_READ_ONLY",
        "allowed_operation": "READ_UNIT2_TYPED_PROOF_ONLY",
        "spreadsheet_id": config["spreadsheet_id"],
        "native_config_ref": file_ref(p),
        "credential_path": str(tmp_path / "NO_REAL_CREDENTIAL"),
        "credential_profile": "unit2-typed-capture",
        "operator_review_ref": file_ref(review),
    }
    request = {
        "spreadsheet_id": config["spreadsheet_id"],
        "ranges": [f"'{t}'!A6:B8" for t in TABS],
        "cell_fields": CELL_FIELDS,
    }
    response = {
        "spreadsheetId": config["spreadsheet_id"],
        "sheets": [
            {
                "properties": {
                    "sheetId": i,
                    "title": t,
                    "gridProperties": {"rowCount": 11, "columnCount": 2},
                },
                "data": [
                    {
                        "startRow": 5,
                        "startColumn": 0,
                        "rowData": [
                            {
                                "values": [
                                    {"userEnteredValue": {"stringValue": "key"}},
                                    {"userEnteredValue": {"stringValue": "value"}},
                                ]
                            },
                            {
                                "values": [
                                    {
                                        "userEnteredValue": {
                                            "stringValue": "=FICTIONAL_LITERAL"
                                        },
                                        "userEnteredFormat": {
                                            "textFormat": {"bold": True}
                                        },
                                        "dataValidation": {"strict": True},
                                        "note": "FICTIONAL_NOTE",
                                        "chipRuns": [],
                                    }
                                ]
                            },
                        ],
                    }
                ],
            }
            for i, t in enumerate(TABS)
        ],
    }
    return config, registration, request, response


def test_exact_mask_headers_chip_and_formula_looking_text_unchanged(
    fixture: Any,
) -> None:
    c, _, q, r = fixture
    before = copy.deepcopy(r)
    validate_native_response(c, q, r)
    assert r == before


@pytest.mark.parametrize(
    "bad",
    [
        "missing",
        "extra",
        "wrongbook",
        "wrongwidth",
        "unquoted",
        "overlap",
        "capacity",
        "noheader",
    ],
)
def test_request_rejection(fixture: Any, bad: str) -> None:
    c, _, q, _ = fixture
    if bad == "missing":
        q["ranges"].pop()
    if bad == "extra":
        q["cell_fields"] += ",effectiveValue"
    if bad == "wrongbook":
        q["spreadsheet_id"] = "WRONG"
    if bad == "wrongwidth":
        q["ranges"][0] = "'Grades'!A6:A8"
    if bad == "unquoted":
        q["ranges"][0] = "Grades!A6:B8"
    if bad == "overlap":
        q["ranges"][0] = q["ranges"][1]
    if bad == "capacity":
        q["ranges"][0] = "'Grades'!A6:B99"
    if bad == "noheader":
        q["ranges"][0] = "'Grades'!A7:B8"
    with pytest.raises(GradebookError):
        validate_request(c, q)


@pytest.mark.parametrize(
    "bad",
    [
        "wrongbook",
        "tabid",
        "header",
        "missingtab",
        "overlap",
        "outside",
        "extra_field",
        "unrequestedgrid",
    ],
)
def test_native_response_rejection(fixture: Any, bad: str) -> None:
    c, _, q, r = fixture
    s = r["sheets"][0]
    if bad == "wrongbook":
        r["spreadsheetId"] = "WRONG"
    if bad == "tabid":
        s["properties"]["sheetId"] = 90
    if bad == "header":
        s["data"][0]["rowData"][0]["values"][0]["userEnteredValue"] = {
            "formulaValue": "=BAD"
        }
    if bad == "missingtab":
        r["sheets"].pop()
    if bad == "overlap":
        s["data"].append(copy.deepcopy(s["data"][0]))
    if bad == "outside":
        s["data"][0]["startRow"] = 99
    if bad == "extra_field":
        s["data"][0]["rowData"][1]["values"][0]["effectiveValue"] = {
            "stringValue": "BAD"
        }
    if bad == "unrequestedgrid":
        r["sheets"].append(
            {"properties": {"title": "Other", "sheetId": 99}, "data": [{}]}
        )
    with pytest.raises(GradebookError):
        validate_native_response(c, q, r)


def test_inactive_registration_stops_before_any_credential(fixture: Any) -> None:
    _, r, _, _ = fixture
    r["state"] = "REVIEW_ONLY_NOT_ACTIVATED"
    with pytest.raises(GradebookError, match="NOT_ACTIVATED"):
        qualify_registration(r)


def test_native_configuration_pin_drift_rejected(fixture: Any) -> None:
    _, r, _, _ = fixture
    Path(r["native_config_ref"]["path"]).write_text("{}", encoding="utf-8")
    with pytest.raises(GradebookError, match="LOCAL_REF_CHANGED"):
        qualify_registration(r)


async def test_canonical_google_public_method_has_only_bounded_gets(
    fixture: Any,
) -> None:
    c, _, q, r = fixture
    google = object.__new__(GoogleSheets)
    google.read_only = True
    google.workbook_id = c["spreadsheet_id"]
    google.read_timeout_seconds = 10
    google._validated_token = "must_clear"
    calls = []

    async def get(params: Any, **kwargs: Any) -> dict[str, Any]:
        calls.append(params)
        return copy.deepcopy(
            r
            if isinstance(params, list)
            else {
                "spreadsheetId": r["spreadsheetId"],
                "sheets": [{"properties": x["properties"]} for x in r["sheets"]],
            }
        )

    google._get = get
    observed = await google.read_registered_unit2_typed_ranges(c, q)
    assert observed == r and len(calls) == 3 and google._validated_token is None
    assert [v for k, v in calls[1] if k == "ranges"] == q["ranges"]
    assert "chipRuns" in dict(calls[1])["fields"]


async def test_metadata_drift_refuses_capture(fixture: Any) -> None:
    c, _, q, r = fixture
    google = object.__new__(GoogleSheets)
    google.read_only = True
    google.workbook_id = c["spreadsheet_id"]
    google.read_timeout_seconds = 10
    google._validated_token = None
    count = 0

    async def get(params: Any, **kwargs: Any) -> dict[str, Any]:
        nonlocal count
        count += 1
        value = copy.deepcopy(r)
        if count == 3:
            value["sheets"][0]["properties"]["gridProperties"]["rowCount"] += 1
        if not isinstance(params, list):
            for x in value["sheets"]:
                x.pop("data")
        return value

    google._get = get
    with pytest.raises(GradebookError, match="metadata changed"):
        await google.read_registered_unit2_typed_ranges(c, q)
    assert google._validated_token is None


async def test_same_process_sink_metadata_only(fixture: Any) -> None:
    c, registration, request, response = fixture

    class Google:
        read_only = True
        workbook_id = c["spreadsheet_id"]

        async def read_registered_unit2_typed_ranges(
            self, config: Any, query: Any
        ) -> Any:
            assert config == c and query == request
            return response

    class Sink:
        root = Path(registration["native_config_ref"]["path"]).parent
        config = c

        def persist(self, **kwargs: Any) -> dict[str, Any]:
            assert kwargs["response"] is response
            return _fictional_sink_result(self.root, **kwargs)

    rp = Path(registration["native_config_ref"]["path"]).parent / "registration.json"
    rp.write_text(json.dumps(registration), encoding="utf-8")
    result = await capture_to_local_sink(
        Google(),
        Sink(),
        registration=registration,
        request=request,
        registration_ref=file_ref(rp),
        transport_code_ref=file_ref(Path(__file__).resolve()),
    )
    assert result["status"] == "LOCAL_FILE_SAVED_NOT_TRANSPORT_AUTHORITY"
    assert result["raw_payload_returned"] is False
    assert Path(result["metadata_manifest_ref"]["path"]).stat().st_mode & 0o777 == 0o600


async def test_real_canonical_http_serializer_uses_gets_only(
    fixture: Any, tmp_path: Path
) -> None:
    import httpx

    config, _, query, response = fixture
    credential = tmp_path / "fictional-oauth.json"
    credential.write_text(
        json.dumps(
            {
                "tokens": {
                    "unit2-typed-capture": {
                        "type": "authorized_user",
                        "client_id": "FICTIONAL",
                        "client_secret": "FICTIONAL",
                        "refresh_token": "FICTIONAL",
                    }
                }
            }
        )
    , encoding="utf-8")
    credential.chmod(0o600)
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if request.url.host == "oauth2.googleapis.com":
            assert request.method == "POST" and request.url.path == "/token"
            return httpx.Response(
                200,
                json={
                    "access_token": "FICTIONAL",
                    "token_type": "Bearer",
                    "expires_in": 3600,
                    "scope": "https://www.googleapis.com/auth/spreadsheets.readonly",
                },
            )
        assert request.method == "GET" and request.url.host == "sheets.googleapis.com"
        assert request.url.path == "/v4/spreadsheets/FICTIONAL_UNIT2_PROOF"
        if request.url.params.get("includeGridData"):
            assert request.url.params.get_list("ranges") == query["ranges"]
            assert request.url.params["fields"].endswith("chipRuns)))))")
            return httpx.Response(200, json=response)
        return httpx.Response(
            200,
            json={
                "spreadsheetId": response["spreadsheetId"],
                "sheets": [{"properties": x["properties"]} for x in response["sheets"]],
            },
        )

    google = GoogleSheets(
        config["spreadsheet_id"],
        credential,
        "unit2-typed-capture",
        transport=httpx.MockTransport(handler),
        read_only=True,
        read_interval_seconds=0,
    )
    try:
        assert (
            await google.read_registered_unit2_typed_ranges(config, query) == response
        )
    finally:
        await google.close()
    assert len(calls) == 4 and sum(x.method == "GET" for x in calls) == 3


async def _verify_sink_contract(sink_type: Any, fixture: Any, tmp_path: Path) -> None:
    config, registration, request, response = fixture
    output = tmp_path / "output"
    output.mkdir(mode=0o700)

    class Google:
        read_only = True
        workbook_id = config["spreadsheet_id"]

        async def read_registered_unit2_typed_ranges(self, c: Any, q: Any) -> Any:
            return response

    registration_path = tmp_path / "registration.json"
    registration_path.write_text(json.dumps(registration), encoding="utf-8")
    result = await capture_to_local_sink(
        Google(),
        sink_type(config, output),
        registration=registration,
        request=request,
        registration_ref=file_ref(registration_path),
        transport_code_ref=file_ref(Path(__file__).resolve()),
    )
    saved = json.loads(Path(result["capture_ref"]["path"]).read_text(encoding="utf-8"))
    assert saved["response"] == response
    assert "FICTIONAL_NOTE" not in json.dumps(result)
    assert result["raw_payload_returned"] is False
    assert Path(result["capture_ref"]["path"]).stat().st_mode & 0o777 == 0o600


async def test_fictional_sink_preserves_complete_native_response_privately(
    fixture: Any, tmp_path: Path
) -> None:
    """Self-contained consumer contract; no private implementation dependency."""

    class FictionalSink:
        def __init__(self, config: Any, root: Path) -> None:
            self.config, self.root = config, root

        def persist(self, **kwargs: Any) -> dict[str, Any]:
            return _fictional_sink_result(self.root, **kwargs)

    await _verify_sink_contract(FictionalSink, fixture, tmp_path)


async def test_explicit_owner_sink_in_process_frozen_interface(
    fixture: Any, tmp_path: Path
) -> None:
    """Optional owner integration retains exact explicit source/hash validation."""
    import importlib.util

    source = os.environ.get("CANVAS_UNIT2_CAPTURE_SINK_SOURCE")
    expected = os.environ.get("CANVAS_UNIT2_CAPTURE_SINK_SHA256")
    if source is None and expected is None:
        pytest.skip("Optional owner-sink integration requires explicit source and hash")
    if source is None or expected is None:
        pytest.fail("Owner-sink integration requires both source and hash")
    path = Path(source)
    assert path.is_absolute()
    assert not any(item.is_symlink() for item in (path, *path.parents))
    assert file_ref(path)["sha256"] == expected, (
        "Explicit owner-sink source hash changed"
    )
    spec = importlib.util.spec_from_file_location("configured_writer_sink", path)
    assert spec is not None and spec.loader is not None
    sink_module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(sink_module)
    await _verify_sink_contract(sink_module.LocalTypedProofSink, fixture, tmp_path)


async def test_inactive_cli_has_zero_client_construction(
    fixture: Any, tmp_path: Path, monkeypatch: Any
) -> None:
    import argparse
    import importlib.util

    path = Path(__file__).parents[1] / "scripts/sdm_unit2_typed_capture.py"
    spec = importlib.util.spec_from_file_location("fictional_unit2_cli", path)
    assert spec is not None and spec.loader is not None
    cli = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cli)
    _, registration, _, _ = fixture
    registration["state"] = "REVIEW_ONLY_NOT_ACTIVATED"
    rp = tmp_path / "registration.json"
    rp.write_text(json.dumps(registration), encoding="utf-8")

    def forbidden(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("MUST_NOT_CONSTRUCT_CLIENT_OR_READ_CREDENTIALS")

    monkeypatch.setattr(cli, "GoogleSheets", forbidden)
    with pytest.raises(GradebookError, match="NOT_ACTIVATED"):
        await cli.run(
            argparse.Namespace(
                registration=str(rp),
                ranges_file=str(tmp_path / "absent.json"),
                output_root=str(tmp_path),
                read_registered_proof=True,
            )
        )


async def test_registration_ref_object_drift_stops_before_get(
    fixture: Any, tmp_path: Path
) -> None:
    _, registration, request, _ = fixture
    rp = tmp_path / "different.json"
    rp.write_text(json.dumps({"different": True}), encoding="utf-8")
    with pytest.raises(GradebookError, match="REGISTRATION_OBJECT_REF_CHANGED"):
        await capture_to_local_sink(
            object(),
            object(),
            registration=registration,
            request=request,
            registration_ref=file_ref(rp),
            transport_code_ref=file_ref(Path(__file__).resolve()),
        )


@pytest.mark.parametrize(
    "method", ["batch", "send_preflighted_batch", "_send_batch", "_json_request"]
)
async def test_read_only_mode_refuses_all_batch_routes_before_http(
    fixture: Any, tmp_path: Path, method: str
) -> None:
    import httpx

    c, _, _, _ = fixture
    p = tmp_path / "dummy-credential.json"
    p.write_text(
        json.dumps(
            {
                "tokens": {
                    "unit2-typed-capture": {
                        "type": "authorized_user",
                        "client_id": "FICTIONAL",
                        "client_secret": "FICTIONAL",
                        "refresh_token": "FICTIONAL",
                    }
                }
            }
        )
    , encoding="utf-8")
    p.chmod(0o600)

    def forbidden(request: httpx.Request) -> httpx.Response:
        raise AssertionError("NO_AUTH_OR_SHEETS_HTTP_ALLOWED_FOR_WRITE_REFUSAL")

    client = GoogleSheets(
        c["spreadsheet_id"],
        p,
        "unit2-typed-capture",
        read_only=True,
        transport=httpx.MockTransport(forbidden),
    )
    try:
        with pytest.raises(GradebookError, match="Read-only"):
            if method == "_json_request":
                await client._json_request(
                    "POST",
                    client.url + ":batchUpdate",
                    retry=False,
                    payload={"requests": []},
                )
            elif method == "_send_batch":
                await client._send_batch({"requests": []})
            else:
                await getattr(client, method)([{"updateCells": {}}])
    finally:
        await client.close()


@pytest.mark.parametrize("changed", ["registration", "native", "operator", "source"])
async def test_changed_during_await_stops_before_sink(
    fixture: Any, tmp_path: Path, changed: str
) -> None:
    c, registration, request, response = fixture
    rp = tmp_path / "registration.json"
    rp.write_text(json.dumps(registration), encoding="utf-8")
    regref = file_ref(rp)
    code = tmp_path / "transport.py"
    code.write_text("# fixture", encoding="utf-8")
    coderef = file_ref(code)

    class Google:
        read_only = True
        workbook_id = c["spreadsheet_id"]

        async def read_registered_unit2_typed_ranges(
            self, config: Any, query: Any
        ) -> Any:
            p = {
                "registration": rp,
                "native": Path(registration["native_config_ref"]["path"]),
                "operator": Path(registration["operator_review_ref"]["path"]),
                "source": code,
            }[changed]
            p.write_text("{}", encoding="utf-8")
            return response

    class Sink:
        config = c

        def persist(self, **kwargs: Any) -> None:
            raise AssertionError("MUST_NOT_SAVE_PROOF_AFTER_MUTABLE_INPUT_CHANGED")

    with pytest.raises(GradebookError):
        await capture_to_local_sink(
            Google(),
            Sink(),
            registration=registration,
            request=request,
            registration_ref=regref,
            transport_code_ref=coderef,
        )


@pytest.mark.parametrize("which", ["registration", "ranges"])
def test_cli_original_symlink_paths_rejected(tmp_path: Path, which: str) -> None:
    import importlib.util

    path = Path(__file__).parents[1] / "scripts/sdm_unit2_typed_capture.py"
    spec = importlib.util.spec_from_file_location("symlink_cli", path)
    assert spec is not None and spec.loader is not None
    cli = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cli)
    original = tmp_path / (which + ".json")
    original.write_text("{}", encoding="utf-8")
    link = tmp_path / (which + "-link.json")
    link.symlink_to(original)
    with pytest.raises(GradebookError, match="DIRECT_ARGUMENT_PATH_REQUIRED"):
        cli.direct_ref(link)


def _fictional_sink_result(root: Path, **kwargs: Any) -> dict[str, Any]:
    """Independent minimal consumer of the exact metadata-only receipt schema."""
    raw = json.dumps({"response": kwargs["response"]}, ensure_ascii=False).encode()
    digest = hashlib.sha256(raw).hexdigest()
    path = root / f"TYPED-CAPTURE-{digest}.receipt.private.json"
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(raw)
    return {
        "contract": "UNIT2_LOCAL_TYPED_FILE_RECEIPT_V1",
        "status": "LOCAL_FILE_SAVED_NOT_TRANSPORT_AUTHORITY",
        "capture_ref": file_ref(path),
        "started_at": kwargs["started_at"],
        "completed_at": kwargs["completed_at"],
        "request": kwargs["request"],
        "transport_code_ref": kwargs["transport_code_ref"],
        "registration_ref": kwargs["registration_ref"],
        "counts": {"requested_cells": 30, "tables": list(TABS), "range_count": 5},
        "raw_payload_returned": False,
        "external_mutations": 0,
    }


@pytest.mark.parametrize(
    "leak", ["extra", "status", "counts", "request", "capture_ref"]
)
async def test_sink_cannot_return_or_embed_native_payload_in_metadata(
    fixture: Any, tmp_path: Path, leak: str
) -> None:
    config, registration, request, response = fixture
    sentinel = "FICTIONAL_PRIVATE_SINK_SENTINEL"
    response["sheets"][0]["data"][0]["rowData"][1]["values"][0]["note"] = sentinel

    class Google:
        read_only = True
        workbook_id = config["spreadsheet_id"]

        async def read_registered_unit2_typed_ranges(self, c: Any, q: Any) -> Any:
            return response

    class Sink:
        def __init__(self) -> None:
            self.config, self.root = config, tmp_path

        def persist(self, **kwargs: Any) -> dict[str, Any]:
            result = _fictional_sink_result(self.root, **kwargs)
            if leak == "extra":
                result["unexpected_native_response"] = response
            elif leak == "status":
                result["status"] = sentinel
            elif leak == "counts":
                result["counts"]["unexpected_native_response"] = response
            elif leak == "request":
                result["request"] = {**request, "unexpected_native_response": response}
            else:
                result["capture_ref"]["unexpected_native_response"] = response
            return result

    reg = tmp_path / "registration.json"
    reg.write_text(json.dumps(registration), encoding="utf-8")
    with pytest.raises(GradebookError, match="SINK_METADATA") as held:
        await capture_to_local_sink(
            Google(),
            Sink(),
            registration=registration,
            request=request,
            registration_ref=file_ref(reg),
            transport_code_ref=file_ref(Path(__file__).resolve()),
        )
    assert sentinel not in str(held.value)
    assert not list(tmp_path.glob("TYPED-CAPTURE-METADATA-*"))


def test_cli_private_sink_initialization_error_has_no_traceback_or_payload(
    monkeypatch: Any, capsys: Any
) -> None:
    import importlib.util
    import sys

    path = Path(__file__).parents[1] / "scripts/sdm_unit2_typed_capture.py"
    spec = importlib.util.spec_from_file_location("private_sink_error_cli", path)
    assert spec is not None and spec.loader is not None
    cli = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cli)

    async def private_failure(args: Any) -> Any:
        raise RuntimeError("FICTIONAL_PRIVATE_SINK_SENTINEL")

    monkeypatch.setattr(cli, "run", private_failure)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            str(path),
            "--registration",
            "fictional",
            "--ranges-file",
            "fictional",
            "--output-root",
            "fictional",
        ],
    )
    with pytest.raises(SystemExit) as held:
        cli.main()
    assert held.value.code == 2
    captured = capsys.readouterr()
    assert captured.err == ""
    assert json.loads(captured.out) == {
        "status": "CAPTURE_HELD",
        "raw_payload_returned": False,
        "external_mutations": 0,
    }
    assert "FICTIONAL_PRIVATE_SINK_SENTINEL" not in captured.out
