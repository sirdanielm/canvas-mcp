"""Bounded GET of a connector export reference, without argv or durable secrets.

This byte verifier does not prove teaching-content admission or source revision.
The caller must admit the export before calling and re-read metadata afterwards.
No service registration, credential access, retries, or archive promotion occurs.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import sys
import time
import zipfile
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path
from typing import Any, TextIO
from urllib.parse import urlsplit

import httpx

MAX_BYTES = 12 * 1024 * 1024
MAX_INPUT_BYTES = 64 * 1024
MAX_UNCOMPRESSED = 128 * 1024 * 1024
FORMATS = {
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": (
        ".docx",
        "word/document.xml",
    ),
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": (
        ".xlsx",
        "xl/workbook.xml",
    ),
    "application/vnd.openxmlformats-officedocument.presentationml.presentation": (
        ".pptx",
        "ppt/presentation.xml",
    ),
}
HOST = re.compile(r"(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+oaiusercontent\.com\Z")
_QUIET_REFERENCE: ContextVar[bool] = ContextVar("quiet_export_reference", default=False)


class _ReferenceLogFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        return not _QUIET_REFERENCE.get()


@contextmanager
def _quiet_dependency_logs() -> Iterator[None]:
    # Ancestor logger filters do not filter propagated child records. Include
    # actual emitters, including HTTPcore's DEBUG response-header traces.
    names = {
        "httpx",
        "httpcore",
        "httpcore.connection",
        "httpcore.http11",
        "httpcore.http2",
    }
    names.update(
        name
        for name in list(logging.Logger.manager.loggerDict)
        if name.startswith(("httpx.", "httpcore."))
    )
    loggers = [logging.getLogger(name) for name in names]
    guard = _ReferenceLogFilter()
    token = _QUIET_REFERENCE.set(True)
    try:
        for logger in loggers:
            logger.addFilter(guard)
        yield
    finally:
        for logger in loggers:
            logger.removeFilter(guard)
        _QUIET_REFERENCE.reset(token)


class MaterializationError(Exception):
    """Only a fixed error code; never attach provider exceptions or references."""


def _validate(reference: dict[str, Any]) -> tuple[str, str, int]:
    if not isinstance(reference, dict) or set(reference) != {
        "download_url",
        "mime_type",
        "expected_bytes",
    }:
        raise MaterializationError("REFERENCE_SCHEMA_HELD")
    url, mime, expected = (
        reference["download_url"],
        reference["mime_type"],
        reference["expected_bytes"],
    )
    if not isinstance(url, str) or len(url) > MAX_INPUT_BYTES:
        raise MaterializationError("REFERENCE_ORIGIN_HELD")
    try:
        parsed = urlsplit(url)
        valid = (
            url.startswith("https://")
            and not any(ord(c) <= 32 or ord(c) == 127 for c in url)
            and parsed.scheme == "https"
            and HOST.fullmatch(parsed.hostname or "") is not None
            and parsed.username is None
            and parsed.password is None
            and parsed.netloc == parsed.hostname
            and parsed.port is None
            and "#" not in url
        )
    except ValueError:
        valid = False
    if not valid:
        raise MaterializationError("REFERENCE_ORIGIN_HELD")
    if not isinstance(mime, str) or mime not in FORMATS:
        raise MaterializationError("FORMAT_HELD")
    if type(expected) is not int or not 0 < expected <= MAX_BYTES:
        raise MaterializationError("SIZE_BOUND_HELD")
    return url, mime, expected


def _write(path: Path, body: bytes) -> None:
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as stream:
        stream.write(body)
        stream.flush()
        os.fsync(stream.fileno())


def _receipt(run: Path, value: dict[str, Any]) -> None:
    temporary = run / ".receipt.partial"
    _write(temporary, (json.dumps(value, indent=2) + "\n").encode())
    os.replace(temporary, run / "receipt.json")
    fd = os.open(run, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _check_office(path: Path, required: str, started: float) -> None:
    with zipfile.ZipFile(path) as archive:
        entries = archive.infolist()
        names = [entry.filename for entry in entries]
        if (
            len(entries) > 10000
            or len(names) != len(set(names))
            or not {"[Content_Types].xml", required} <= set(names)
            or sum(entry.file_size for entry in entries) > MAX_UNCOMPRESSED
            or any(entry.flag_bits & 1 for entry in entries)
        ):
            raise MaterializationError("OFFICE_STRUCTURE_HELD")
        # Read every member for CRC verification without extracting paths.
        for entry in entries:
            with archive.open(entry) as member:
                while member.read(65536):
                    if time.monotonic() - started > 30:
                        raise MaterializationError("TRANSFER_TIME_HELD")


def materialize_export(
    reference: dict[str, Any],
    run_dir: Path,
    *,
    transport: httpx.BaseTransport | None = None,
) -> dict[str, Any]:
    """Create one exclusive private receipt-bound source/working pair.

    The reference stays in this process. Existing directories always refuse
    replay before network access, including interrupted or held attempts.
    Transport injection is for controlled offline tests, never credentials.
    """
    try:
        url, mime, expected = _validate(reference)
    except MaterializationError as exc:
        return {"status": "HELD", "reason": str(exc), "metadata_recheck_required": True}
    try:
        if ".." in run_dir.parts or run_dir.absolute() != run_dir.resolve():
            return {
                "status": "HELD",
                "reason": "DESTINATION_HELD",
                "metadata_recheck_required": True,
            }
        run_dir.mkdir(mode=0o700, parents=False, exist_ok=False)
    except FileExistsError:
        return {
            "status": "HELD",
            "reason": "DESTINATION_EXISTS_HELD",
            "metadata_recheck_required": True,
        }
    except (OSError, RuntimeError):
        return {
            "status": "HELD",
            "reason": "DESTINATION_HELD",
            "metadata_recheck_required": True,
        }
    suffix, required = FORMATS[mime]
    result: dict[str, Any] = {
        "schema_version": 1,
        "status": "RECEIVING_REVIEW_REQUIRED",
        "export_mime_type": mime,
        "expected_bytes": expected,
        "metadata_recheck_required": True,
        "content_admission": "CALLER_RESPONSIBILITY_NOT_PROVED",
        "automatic_retries": 0,
    }
    partial = run_dir / ".source.partial"
    working = run_dir / ".working.partial"
    started = time.monotonic()
    try:
        _receipt(run_dir, result)
        digest = hashlib.sha256()
        total = 0
        # Disable proxy/netrc environment inheritance and isolate cookies/auth.
        client = httpx.Client(
            transport=transport,
            trust_env=False,
            follow_redirects=False,
            timeout=httpx.Timeout(5.0, connect=10.0),
            auth=None,
        )
        with (
            _quiet_dependency_logs(),
            client,
            client.stream(
                "GET",
                url,
                headers={"Accept": mime, "Accept-Encoding": "identity"},
            ) as response,
        ):
            if response.status_code != 200:
                raise MaterializationError("HTTP_STATUS_HELD")
            if response.headers.get("content-encoding", "identity") != "identity":
                raise MaterializationError("CONTENT_ENCODING_HELD")
            length = response.headers.get("content-length")
            if length is not None and length != str(expected):
                raise MaterializationError("CONTENT_LENGTH_HELD")
            fd = os.open(partial, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "wb") as stream:
                # Do not buffer until a 64 KiB chunk fills: a slow trickle
                # must reach the elapsed-time check on every received chunk.
                for chunk in response.iter_bytes():
                    if time.monotonic() - started > 30:
                        raise MaterializationError("TRANSFER_TIME_HELD")
                    total += len(chunk)
                    if total > expected:
                        raise MaterializationError("SIZE_BOUND_HELD")
                    digest.update(chunk)
                    stream.write(chunk)
                stream.flush()
                os.fsync(stream.fileno())
            if total != expected:
                raise MaterializationError("EXPECTED_SIZE_HELD")
        _check_office(partial, required, started)
        _write(working, partial.read_bytes())
        if hashlib.sha256(working.read_bytes()).hexdigest() != digest.hexdigest():
            raise MaterializationError("WORKING_COPY_HASH_HELD")
        source_name, working_name = "source" + suffix, "working" + suffix
        result.update(
            status="VERIFIED_BYTES_PENDING_COMMIT",
            bytes=total,
            sha256=digest.hexdigest(),
            source_path=source_name,
            working_path=working_name,
            office_crc_verified=True,
            source_committed=False,
            working_committed=False,
        )
        _receipt(run_dir, result)
        # Hard links refuse overwrite even if another process creates a target.
        os.link(partial, run_dir / source_name)
        result["source_committed"] = True
        _receipt(run_dir, result)
        partial.unlink()
        os.link(working, run_dir / working_name)
        result["working_committed"] = True
        working.unlink()
        result.update(
            status="VERIFIED_NEEDS_METADATA",
            bytes=total,
            sha256=digest.hexdigest(),
            source_path=source_name,
            working_path=working_name,
            office_crc_verified=True,
        )
    except Exception as exc:
        reason = str(exc) if isinstance(exc, MaterializationError) else "TRANSFER_HELD"
        result.update(status="HELD", reason=reason)
        for path in (partial, working):
            try:
                if path.exists():
                    path.unlink()
            except OSError:
                result["partial_cleanup_requires_review"] = True
    try:
        _receipt(run_dir, result)
    except OSError:
        result.update(
            status="HELD", reason="RECEIPT_IO_HELD", durable_receipt_confirmed=False
        )
    return result


def main(
    argv: list[str] | None = None,
    *,
    stdin: TextIO | None = None,
    transport: httpx.BaseTransport | None = None,
) -> int:
    """Read a bounded JSON reference only from stdin; never echo bad arguments."""
    args = sys.argv[1:] if argv is None else argv
    if args == ["--help"]:
        print("Usage: materialize_course_export.py --output NEW_PRIVATE_RUN_DIR")
        print("Read one admitted export reference JSON from non-echoing stdin.")
        return 0
    try:
        if (
            len(args) != 2
            or args[0] != "--output"
            or not args[1]
            or "://" in args[1]
            or any(ord(c) < 32 for c in args[1])
        ):
            raise MaterializationError("CLI_ARGUMENTS_HELD")
        channel = sys.stdin if stdin is None else stdin
        if channel.isatty():
            raise MaterializationError("NONINTERACTIVE_STDIN_REQUIRED")
        raw = channel.read(MAX_INPUT_BYTES + 1)
        if len(raw.encode("utf-8")) > MAX_INPUT_BYTES:
            raise MaterializationError("INPUT_BOUND_HELD")
        reference = json.loads(raw)
        result = materialize_export(reference, Path(args[1]), transport=transport)
        print(
            json.dumps(
                {
                    "status": result["status"],
                    "bytes_verified": result.get("bytes", 0),
                    "reason": result.get("reason"),
                    "metadata_recheck_required": True,
                }
            )
        )
        return 0 if result["status"] == "VERIFIED_NEEDS_METADATA" else 2
    except Exception as exc:
        reason = (
            str(exc) if isinstance(exc, MaterializationError) else "INPUT_OR_IO_HELD"
        )
        print(json.dumps({"status": "HELD", "reason": reason}))
        return 2
