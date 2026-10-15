"""Offline security contracts for bounded provider export materialization.

Only synthetic references and in-memory Office ZIPs are used. Every HTTP request
must go through an injected MockTransport; no credentials or live service reads.
"""

from __future__ import annotations

import base64
import hashlib
import io
import json
import re
import stat
import zipfile
from collections.abc import Iterator
from contextvars import Context
from pathlib import Path
from typing import Any

import httpx
import pytest

from canvas_mcp.mirror.export_materializer import main, materialize_export

SECRET = "SYNTHETIC_REFERENCE_SECRET_42"
URL = "https://fixture.oaiusercontent.com/export?signature=" + SECRET
DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
PPTX = "application/vnd.openxmlformats-officedocument.presentationml.presentation"


def office_bytes(member: str = "word/document.xml") -> bytes:
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(
            "[Content_Types].xml",
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"/>',
        )
        archive.writestr(member, "<synthetic>Teaching fixture</synthetic>")
    return stream.getvalue()


def reference(body: bytes, **changes: Any) -> dict[str, Any]:
    return {
        "download_url": URL,
        "mime_type": DOCX,
        "expected_bytes": len(body),
        **changes,
    }


def fixture_transport(
    body: bytes,
    requests: list[httpx.Request],
    *,
    status: int = 200,
    headers: dict[str, str] | None = None,
) -> httpx.MockTransport:
    def handle(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(status, content=body, headers=headers)

    return httpx.MockTransport(handle)


def assert_no_secret(run_dir: Path, result: dict[str, Any], captured: str = "") -> None:
    encoded = base64.b64encode(URL.encode()).decode()
    material = json.dumps(result) + captured
    assert SECRET not in material and URL not in material and encoded not in material
    if run_dir.exists():
        for path in run_dir.rglob("*"):
            if path.is_file():
                value = path.read_bytes()
                assert SECRET.encode() not in value
                assert URL.encode() not in value
                assert encoded.encode() not in value


def assert_held(result: dict[str, Any]) -> None:
    assert result["status"] == "HELD"
    assert re.fullmatch(r"[A-Z][A-Z0-9_]{0,95}", result["reason"])


def result_file(result: dict[str, Any], key: str, run_dir: Path) -> Path:
    path = Path(result[key])
    return path if path.is_absolute() else run_dir / path


@pytest.mark.parametrize(
    "mime,member",
    [
        (DOCX, "word/document.xml"),
        (XLSX, "xl/workbook.xml"),
        (PPTX, "ppt/presentation.xml"),
    ],
)
def test_success_has_exact_get_private_equal_copies_and_no_reference_persistence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mime: str, member: str
) -> None:
    body = office_bytes(member)
    requests: list[httpx.Request] = []
    monkeypatch.setenv("HTTP_PROXY", "http://invalid-proxy.invalid:9")
    monkeypatch.setenv("HTTPS_PROXY", "http://invalid-proxy.invalid:9")
    monkeypatch.setenv("CANVAS_API_TOKEN", "SYNTHETIC_UNUSED_CANVAS_TOKEN")
    run = tmp_path / "new-export"
    result = materialize_export(
        reference(body, mime_type=mime),
        run,
        transport=fixture_transport(body, requests),
    )
    assert result["status"] == "VERIFIED_NEEDS_METADATA"
    assert len(requests) == 1
    assert requests[0].method == "GET"
    assert str(requests[0].url) == URL
    assert not any(
        header in requests[0].headers
        for header in (
            "authorization",
            "proxy-authorization",
            "cookie",
            "x-canvas-token",
        )
    )
    assert result["bytes"] == len(body)
    assert result["sha256"] == hashlib.sha256(body).hexdigest()
    source = result_file(result, "source_path", run)
    working = result_file(result, "working_path", run)
    assert source != working
    assert source.resolve().is_relative_to(run.resolve())
    assert working.resolve().is_relative_to(run.resolve())
    assert source.read_bytes() == working.read_bytes() == body
    assert stat.S_IMODE(run.stat().st_mode) == 0o700
    for path in run.rglob("*"):
        assert stat.S_IMODE(path.stat().st_mode) == (0o700 if path.is_dir() else 0o600)
    assert_no_secret(run, result)


@pytest.mark.parametrize(
    "url",
    [
        "http://fixture.oaiusercontent.com/export",
        "https://oaiusercontent.com/export",
        "https://eviloaiusercontent.com/export",
        "https://fixture.oaiusercontent.com.evil.invalid/export",
        "https://127.0.0.1/export",
        "https://fixture.oaiusercontent.com:443/export",
        "https://user:password@fixture.oaiusercontent.com/export",
        "https://fixture.oaiusercontent.com/export#fragment",
    ],
)
def test_unapproved_reference_is_rejected_before_http(tmp_path: Path, url: str) -> None:
    body = office_bytes()
    requests: list[httpx.Request] = []
    run = tmp_path / "held"
    result = materialize_export(
        reference(body, download_url=url),
        run,
        transport=fixture_transport(body, requests),
    )
    assert_held(result)
    assert requests == []
    assert_no_secret(run, result)


@pytest.mark.parametrize(
    "expected", [True, False, None, "100", 0, -1, 12 * 1024 * 1024 + 1]
)
def test_invalid_exact_size_is_rejected_before_http(
    tmp_path: Path, expected: Any
) -> None:
    requests: list[httpx.Request] = []
    body = office_bytes()
    result = materialize_export(
        reference(body, expected_bytes=expected),
        tmp_path / "held",
        transport=fixture_transport(body, requests),
    )
    assert_held(result)
    assert requests == []


def test_unsupported_mime_is_rejected_before_http(tmp_path: Path) -> None:
    body = office_bytes()
    requests: list[httpx.Request] = []
    result = materialize_export(
        reference(body, mime_type="application/octet-stream"),
        tmp_path / "held",
        transport=fixture_transport(body, requests),
    )
    assert_held(result)
    assert requests == []


@pytest.mark.parametrize("status", [301, 302, 307, 403, 404, 500])
def test_redirect_and_http_errors_are_terminal_static_holds(
    tmp_path: Path, status: int
) -> None:
    requests: list[httpx.Request] = []
    body = office_bytes()
    run = tmp_path / "held"
    result = materialize_export(
        reference(body),
        run,
        transport=fixture_transport(
            (SECRET + URL).encode(),
            requests,
            status=status,
            headers={"Location": "https://other.oaiusercontent.com/?secret=" + SECRET},
        ),
    )
    assert_held(result)
    assert len(requests) == 1
    assert_no_secret(run, result)


@pytest.mark.parametrize("delta", [-1, 1])
def test_short_or_long_body_never_becomes_verified_source(
    tmp_path: Path, delta: int
) -> None:
    body = office_bytes()
    requests: list[httpx.Request] = []
    run = tmp_path / "held"
    result = materialize_export(
        reference(body, expected_bytes=len(body) + delta),
        run,
        transport=fixture_transport(body, requests),
    )
    assert_held(result)
    assert len(requests) == 1
    assert_no_secret(run, result)


def test_declared_length_mismatch_is_held(tmp_path: Path) -> None:
    body = office_bytes()
    requests: list[httpx.Request] = []
    result = materialize_export(
        reference(body),
        tmp_path / "held",
        transport=fixture_transport(
            body, requests, headers={"Content-Length": str(len(body) + 1)}
        ),
    )
    assert_held(result)
    assert len(requests) == 1


@pytest.mark.parametrize("body", [b"not-a-zip", office_bytes("xl/workbook.xml")])
def test_corrupt_or_wrong_office_type_is_held(tmp_path: Path, body: bytes) -> None:
    requests: list[httpx.Request] = []
    run = tmp_path / "held"
    result = materialize_export(
        reference(body), run, transport=fixture_transport(body, requests)
    )
    assert_held(result)
    assert_no_secret(run, result)


def test_transport_exception_does_not_leak_reference(tmp_path: Path) -> None:
    body = office_bytes()

    def fail(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("secret-bearing message " + URL, request=request)

    run = tmp_path / "held"
    result = materialize_export(
        reference(body), run, transport=httpx.MockTransport(fail)
    )
    assert_held(result)
    assert_no_secret(run, result)


def test_existing_output_cannot_overwrite_or_make_http_request(tmp_path: Path) -> None:
    body = office_bytes()
    requests: list[httpx.Request] = []
    run = tmp_path / "existing"
    run.mkdir()
    preserved = run / "owner.txt"
    preserved.write_bytes(b"preserve owner bytes")
    result = materialize_export(
        reference(body), run, transport=fixture_transport(body, requests)
    )
    assert_held(result)
    assert requests == []
    assert preserved.read_bytes() == b"preserve owner bytes"


def test_output_symlink_cannot_write_outside(tmp_path: Path) -> None:
    body = office_bytes()
    requests: list[httpx.Request] = []
    outside = tmp_path / "outside"
    outside.mkdir()
    run = tmp_path / "symlink"
    run.symlink_to(outside, target_is_directory=True)
    result = materialize_export(
        reference(body), run, transport=fixture_transport(body, requests)
    )
    assert_held(result)
    assert requests == []
    assert list(outside.iterdir()) == []


def test_cli_consumes_reference_only_from_stdin_and_prints_aggregate(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    body = office_bytes()
    requests: list[httpx.Request] = []
    run = tmp_path / "cli"
    result = main(
        ["--output", str(run)],
        stdin=io.StringIO(json.dumps(reference(body))),
        transport=fixture_transport(body, requests),
    )
    captured = capsys.readouterr()
    assert result == 0
    output = json.loads(captured.out)
    assert output["status"] == "VERIFIED_NEEDS_METADATA"
    assert len(requests) == 1
    assert_no_secret(run, output, captured.out + captured.err)
    assert str(run) not in captured.out


@pytest.mark.parametrize(
    "payload",
    [
        "{bad-json" + SECRET,
        json.dumps({"download_url": URL}),
        " " * (64 * 1024 + 1),
        json.dumps(
            {
                "download_url": URL,
                "mime_type": DOCX,
                "expected_bytes": 1,
                "unknown": SECRET,
            }
        ),
    ],
)
def test_cli_invalid_stdin_is_bounded_static_and_never_fetches(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], payload: str
) -> None:
    requests: list[httpx.Request] = []
    run = tmp_path / "held"
    result = main(
        ["--output", str(run)],
        stdin=io.StringIO(payload),
        transport=fixture_transport(b"", requests),
    )
    captured = capsys.readouterr()
    assert result != 0
    assert_held(json.loads(captured.out))
    assert requests == []
    assert_no_secret(run, {}, captured.out + captured.err)


def test_cli_rejects_unknown_arguments_without_echoing_secrets(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    requests: list[httpx.Request] = []
    run = tmp_path / "held"
    result = main(
        ["--output", str(run), "--url", URL],
        stdin=io.StringIO("{}"),
        transport=fixture_transport(b"", requests),
    )
    captured = capsys.readouterr()
    assert result != 0
    assert_held(json.loads(captured.out))
    assert requests == []
    assert_no_secret(run, {}, captured.out + captured.err)


def test_symlink_parent_cannot_redirect_new_run_outside(tmp_path: Path) -> None:
    body = office_bytes()
    requests: list[httpx.Request] = []
    outside = tmp_path / "outside-parent"
    outside.mkdir()
    parent = tmp_path / "linked-parent"
    parent.symlink_to(outside, target_is_directory=True)
    result = materialize_export(
        reference(body), parent / "new-run", transport=fixture_transport(body, requests)
    )
    assert_held(result)
    assert requests == []
    assert list(outside.iterdir()) == []


@pytest.mark.parametrize("delta", [-1, 0, 1])
def test_streamed_response_without_length_obeys_exact_expected_bytes(
    tmp_path: Path, delta: int
) -> None:
    body = office_bytes()
    requests: list[httpx.Request] = []

    class Chunks(httpx.SyncByteStream):
        def __iter__(self) -> Iterator[bytes]:
            yield body[:10]
            yield body[10:]

    def handle(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, stream=Chunks())

    run = tmp_path / "streamed"
    result = materialize_export(
        reference(body, expected_bytes=len(body) + delta),
        run,
        transport=httpx.MockTransport(handle),
    )
    assert len(requests) == 1
    if delta:
        assert_held(result)
    else:
        assert result["status"] == "VERIFIED_NEEDS_METADATA"
        assert result["sha256"] == hashlib.sha256(body).hexdigest()
    assert_no_secret(run, result)


def test_stdin_read_is_bounded_before_json_parse(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    requests: list[httpx.Request] = []

    class BoundedInput(io.StringIO):
        def read(self, size: int = -1) -> str:
            assert 0 < size <= 64 * 1024 + 1
            return super().read(size)

    result = main(
        ["--output", str(tmp_path / "held")],
        stdin=BoundedInput(" " * (64 * 1024 + 1)),
        transport=fixture_transport(b"", requests),
    )
    captured = capsys.readouterr()
    assert result != 0
    assert_held(json.loads(captured.out))
    assert requests == []


def test_httpx_info_logging_never_emits_provider_canary(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    import logging

    body = office_bytes()
    caplog.set_level(logging.INFO)
    caplog.set_level(logging.INFO, logger="httpx")
    caplog.set_level(logging.DEBUG, logger="httpcore.http11")
    caplog.set_level(logging.DEBUG, logger="httpcore.http2")
    control = logging.getLogger("synthetic.unrelated.control")
    control.info("UNRELATED_CONTROL_BEFORE")

    def handle(request: httpx.Request) -> httpx.Response:
        control.info("UNRELATED_CONTROL_DURING")
        Context().run(logging.getLogger("httpx").info, "UNRELATED_HTTPX_CONTEXT")
        for logger_name in ("httpcore.http11", "httpcore.http2"):
            logging.getLogger(logger_name).debug(
                "receive_response_headers.complete return_value=%r",
                (
                    b"HTTP/1.1",
                    302,
                    b"Found",
                    [
                        (b"location", URL.encode()),
                        (b"set-cookie", b"SYNTHETIC_COOKIE_CANARY=private"),
                    ],
                ),
            )
        return httpx.Response(200, content=body)

    result = materialize_export(
        reference(body), tmp_path / "logged", transport=httpx.MockTransport(handle)
    )
    control.info("UNRELATED_CONTROL_AFTER")
    assert result["status"] == "VERIFIED_NEEDS_METADATA"
    assert SECRET not in caplog.text
    assert URL not in caplog.text
    assert "SYNTHETIC_COOKIE_CANARY" not in caplog.text
    for marker in (
        "UNRELATED_CONTROL_BEFORE",
        "UNRELATED_CONTROL_DURING",
        "UNRELATED_CONTROL_AFTER",
        "UNRELATED_HTTPX_CONTEXT",
    ):
        assert marker in caplog.text


def test_second_commit_failure_retains_verified_source_provenance(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from canvas_mcp.mirror import export_materializer as materializer

    body = office_bytes()
    requests: list[httpx.Request] = []
    run = tmp_path / "second-commit-held"
    real_link = materializer.os.link
    count = 0
    canary = "SYNTHETIC_SECOND_COMMIT_IO_CANARY"

    def fail_second_link(*args: Any, **kwargs: Any) -> None:
        nonlocal count
        count += 1
        if count == 2:
            raise OSError(canary)
        real_link(*args, **kwargs)

    monkeypatch.setattr(materializer.os, "link", fail_second_link)
    result = materialize_export(
        reference(body), run, transport=fixture_transport(body, requests)
    )
    assert_held(result)
    assert result["bytes"] == len(body)
    assert result["sha256"] == hashlib.sha256(body).hexdigest()
    source = result_file(result, "source_path", run)
    assert source.read_bytes() == body
    receipt = json.loads((run / "receipt.json").read_text())
    assert receipt["status"] == "HELD"
    assert receipt["bytes"] == len(body)
    assert receipt["sha256"] == hashlib.sha256(body).hexdigest()
    assert receipt["source_path"] == result["source_path"]
    assert canary not in json.dumps(result) + json.dumps(receipt)
    assert_no_secret(run, result)


def test_initial_receipt_io_failure_returns_static_held(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from canvas_mcp.mirror import export_materializer as materializer

    body = office_bytes()
    requests: list[httpx.Request] = []
    canary = "SYNTHETIC_INITIAL_RECEIPT_IO_CANARY"

    def fail_receipt(*args: Any, **kwargs: Any) -> None:
        raise OSError(canary)

    monkeypatch.setattr(materializer, "_receipt", fail_receipt)
    run = tmp_path / "receipt-io-held"
    result = materialize_export(
        reference(body), run, transport=fixture_transport(body, requests)
    )
    assert_held(result)
    assert requests == []
    assert canary not in json.dumps(result)
    assert_no_secret(run, result)


def test_elapsed_deadline_checked_after_each_small_transport_chunk(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from canvas_mcp.mirror import export_materializer as materializer

    body = office_bytes()
    elapsed = 0.0
    yielded = 0
    requests: list[httpx.Request] = []

    def fake_monotonic() -> float:
        return elapsed

    class SlowSmallChunks(httpx.SyncByteStream):
        def __iter__(self) -> Iterator[bytes]:
            nonlocal elapsed, yielded
            for value in body:
                elapsed += 20.0
                yielded += 1
                yield bytes([value])

    def handle(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, stream=SlowSmallChunks())

    monkeypatch.setattr(materializer.time, "monotonic", fake_monotonic)
    result = materialize_export(
        reference(body),
        tmp_path / "elapsed-held",
        transport=httpx.MockTransport(handle),
    )
    assert_held(result)
    assert result["reason"] == "TRANSFER_TIME_HELD"
    assert len(requests) == 1
    assert yielded <= 2


def test_symlink_loop_is_a_neutral_pre_network_hold(tmp_path: Path) -> None:
    loop = tmp_path / "loop"
    loop.symlink_to(loop)
    body = office_bytes()
    requests: list[httpx.Request] = []
    result = materialize_export(
        reference(body), loop / "new-run", transport=fixture_transport(body, requests)
    )
    assert_held(result)
    assert requests == []


def test_final_receipt_directory_fsync_failure_persists_held_not_verified(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import os

    from canvas_mcp.mirror import export_materializer as materializer

    body = office_bytes()
    requests: list[httpx.Request] = []
    run = tmp_path / "final-receipt-fsync-held"
    real_fsync = os.fsync
    failed = False
    canary = "SYNTHETIC_FINAL_DIRECTORY_FSYNC_CANARY"

    def fail_verified_directory_once(fd: int) -> None:
        nonlocal failed
        receipt = run / "receipt.json"
        if stat.S_ISDIR(os.fstat(fd).st_mode) and receipt.exists():
            saved = json.loads(receipt.read_text())
            if saved["status"] == "VERIFIED_NEEDS_METADATA" and not failed:
                failed = True
                raise OSError(canary)
        real_fsync(fd)

    monkeypatch.setattr(materializer.os, "fsync", fail_verified_directory_once)
    result = materialize_export(
        reference(body), run, transport=fixture_transport(body, requests)
    )
    assert failed
    assert_held(result)
    saved = json.loads((run / "receipt.json").read_text())
    assert saved["status"] == "HELD"
    assert saved["bytes"] == result["bytes"] == len(body)
    assert saved["sha256"] == result["sha256"] == hashlib.sha256(body).hexdigest()
    assert saved["source_committed"] and saved["working_committed"]
    assert result_file(saved, "source_path", run).read_bytes() == body
    assert result_file(saved, "working_path", run).read_bytes() == body
    assert canary not in json.dumps(result) + json.dumps(saved)
    assert_no_secret(run, result)


def test_persistent_final_receipt_failure_keeps_unfinalized_marker(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import os

    from canvas_mcp.mirror import export_materializer as materializer

    body = office_bytes()
    requests: list[httpx.Request] = []
    run = tmp_path / "persistent-finalization-held"
    real_fsync = os.fsync
    finalization_failed = False
    canary = "SYNTHETIC_PERSISTENT_FINAL_FSYNC_CANARY"

    def fail_after_verified_replace(fd: int) -> None:
        nonlocal finalization_failed
        receipt = run / "receipt.json"
        if stat.S_ISDIR(os.fstat(fd).st_mode) and receipt.exists():
            saved = json.loads(receipt.read_text())
            if saved["status"] == "VERIFIED_NEEDS_METADATA":
                finalization_failed = True
            if finalization_failed:
                raise OSError(canary)
        real_fsync(fd)

    monkeypatch.setattr(materializer.os, "fsync", fail_after_verified_replace)
    result = materialize_export(
        reference(body), run, transport=fixture_transport(body, requests)
    )
    assert finalization_failed
    assert_held(result)
    assert (run / "UNFINALIZED").is_file()
    saved = json.loads((run / "receipt.json").read_text())
    assert saved["status"] in {"HELD", "VERIFIED_NEEDS_METADATA"}
    assert result["bytes"] == len(body)
    assert result["sha256"] == hashlib.sha256(body).hexdigest()
    assert result["source_committed"] and result["working_committed"]
    assert result_file(result, "source_path", run).read_bytes() == body
    assert canary not in json.dumps(result) + json.dumps(saved)
    assert_no_secret(run, result)
