"""Bounded Google Sheets transport for the private, local refresh worker.

Credentials remain local. Reads may retry; a Sheets batch is transmitted once
only. The caller must durably record SENDING before calling ``batch`` and must
reconcile uncertain outcomes instead of repeating that call.
"""

from __future__ import annotations

import asyncio
import json
import math
import os
import re
import stat
import time
from collections.abc import Mapping
from pathlib import Path
from typing import Any, TypeGuard

import httpx

from .client import GradebookError
from .workbook import column_name

TOKEN_URL = "https://oauth2.googleapis.com/token"
TOKEN_INFO_URL = "https://oauth2.googleapis.com/tokeninfo"
WRITE_SCOPES = {
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
    "https://www.googleapis.com/auth/drive.file",
}
GRADE_SHEETS = frozenset({"Core GET", "Adv GET", "Core Edit", "Adv Edit"})
METADATA_FIELDS = "spreadsheetId,developerMetadata,sheets(properties,protectedRanges)"
WORKBOOK_FIELDS = (
    "spreadsheetId,developerMetadata,"
    "sheets(properties,protectedRanges,conditionalFormats,basicFilter,"
    "data(startRow,startColumn,rowMetadata,columnMetadata,"
    "rowData(values(userEnteredValue,userEnteredFormat,note,dataValidation))))"
)


def _positive_int(value: Any) -> TypeGuard[int]:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def _credential(path: Path, profile: str) -> dict[str, str]:
    """Read one owner-only credential without following file symlinks."""
    descriptor: int | None = None
    try:
        if path.is_symlink():
            raise GradebookError("Google credential must not be a symlink.")
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
        info = os.fstat(descriptor)
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_mode & 0o077
            or info.st_uid != os.getuid()
            or not 0 < info.st_size <= 1_000_000
        ):
            raise GradebookError(
                "Google credential requires a private owner-only file."
            )
        with os.fdopen(descriptor, "rb") as stream:
            descriptor = None
            raw = stream.read(1_000_001)
        if len(raw) > 1_000_000:
            raise GradebookError("Google credential file exceeds its size limit.")
        envelope = json.loads(raw)
        entry = envelope["tokens"][profile]
        if not isinstance(entry, dict) or entry.get("type") != "authorized_user":
            raise GradebookError("Google credential profile must be authorized_user.")
        result = {}
        for name in ("client_id", "client_secret", "refresh_token"):
            value = entry.get(name)
            if not isinstance(value, str) or not value or len(value) > 16_384:
                raise GradebookError("Google credential profile is incomplete.")
            result[name] = value
        return result
    except GradebookError:
        raise
    except (OSError, ValueError, KeyError, TypeError):
        raise GradebookError(
            "Google credential profile is unavailable or invalid."
        ) from None
    finally:
        if descriptor is not None:
            os.close(descriptor)


class GoogleSheets:
    """A fixed-workbook adapter; no generic URL or Drive-write capability."""

    def __init__(
        self,
        workbook_id: str,
        credential_path: Path | str,
        profile: str = "gradebook",
        transport: httpx.AsyncBaseTransport | None = None,
        *,
        max_grade_rows: int = 1000,
        max_grade_columns: int = 258,
        max_reference_cells: int = 50_000,
        max_total_cells: int = 1_000_000,
        max_response_bytes: int = 20_000_000,
        sheet_cell_limits: Mapping[str, int] | None = None,
    ) -> None:
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,200}", workbook_id):
            raise GradebookError("Invalid Google workbook identity.")
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", profile):
            raise GradebookError("Invalid Google credential profile.")
        limits = (
            max_grade_rows,
            max_grade_columns,
            max_reference_cells,
            max_total_cells,
            max_response_bytes,
        )
        if not all(_positive_int(limit) for limit in limits):
            raise GradebookError("Google read limits must be positive integers.")
        if any(
            not isinstance(name, str) or not name or not _positive_int(limit)
            for name, limit in (sheet_cell_limits or {}).items()
        ):
            raise GradebookError("Google sheet limits are invalid.")
        self.workbook_id = workbook_id
        self.url = f"https://sheets.googleapis.com/v4/spreadsheets/{workbook_id}"
        self._credential = _credential(Path(credential_path), profile)
        self.max_grade_rows = max_grade_rows
        self.max_grade_columns = max_grade_columns
        self.max_reference_cells = max_reference_cells
        self.max_total_cells = max_total_cells
        self.max_response_bytes = max_response_bytes
        self.sheet_cell_limits = dict(sheet_cell_limits or {})
        self._access_token: str | None = None
        self._expires_at = 0.0
        self._authorized = False
        self._validated_token: str | None = None
        self._auth_lock = asyncio.Lock()
        self.http = httpx.AsyncClient(
            timeout=30, follow_redirects=False, trust_env=False, transport=transport
        )

    async def close(self) -> None:
        await self.http.aclose()

    async def _json_request(
        self,
        method: str,
        url: str,
        *,
        retry: bool,
        headers: dict[str, str] | None = None,
        params: Any = None,
        data: dict[str, str] | None = None,
        payload: dict[str, Any] | None = None,
        byte_limit: int | None = None,
    ) -> tuple[int, dict[str, Any]]:
        allowed = {
            ("POST", TOKEN_URL),
            ("GET", TOKEN_INFO_URL),
            ("GET", self.url),
            ("POST", self.url + ":batchUpdate"),
        }
        if (method, url) not in allowed:
            raise GradebookError("Google request target is not allowed.")
        limit = byte_limit if byte_limit is not None else self.max_response_bytes
        for attempt in range(3 if retry else 1):
            try:
                async with self.http.stream(
                    method, url, headers=headers, params=params, data=data, json=payload
                ) as response:
                    length = response.headers.get("content-length")
                    if length and (not length.isdecimal() or int(length) > limit):
                        raise GradebookError("Google response exceeded its size limit.")
                    body = bytearray()
                    async for chunk in response.aiter_bytes(chunk_size=65_536):
                        body.extend(chunk)
                        if len(body) > limit:
                            raise GradebookError(
                                "Google response exceeded its size limit."
                            )
                    status = response.status_code
                    if retry and status in {429, 502, 503, 504} and attempt < 2:
                        delay = response.headers.get("retry-after", str(2**attempt))
                        if not delay.isdecimal() or int(delay) > 5:
                            raise GradebookError(
                                "Google retry delay requires a later attempt."
                            )
                        await asyncio.sleep(int(delay))
                        continue
                    try:
                        result = json.loads(body)
                    except (ValueError, UnicodeDecodeError):
                        raise GradebookError("Google returned invalid JSON.") from None
                    if not isinstance(result, dict):
                        raise GradebookError(
                            "Google returned an unexpected response shape."
                        )
                    return status, result
            except httpx.HTTPError:
                if retry and attempt < 2:
                    await asyncio.sleep(2**attempt)
                    continue
                raise GradebookError(
                    "Google transport failed; no automatic write retry."
                ) from None
        raise GradebookError("Google read retry limit was reached.")

    @staticmethod
    def _error(
        status: int, body: dict[str, Any], *, write: bool = False
    ) -> GradebookError:
        # Return only recognized reason codes, never provider messages or URLs.
        details = body.get("error", {})
        reason = ""
        if isinstance(details, dict):
            entries = details.get("details", [])
            if isinstance(entries, list):
                known = {
                    "SERVICE_DISABLED",
                    "ACCESS_TOKEN_SCOPE_INSUFFICIENT",
                    "SCOPE_INSUFFICIENT",
                }
                reason = next(
                    (
                        d["reason"]
                        for d in entries
                        if isinstance(d, dict)
                        and isinstance(d.get("reason"), str)
                        and d["reason"] in known
                    ),
                    "",
                )
        suffix = f" ({reason})" if reason else ""
        action = (
            "write stopped; reconcile before another write" if write else "read stopped"
        )
        return GradebookError(f"Google {action}: HTTP {status}{suffix}.")

    async def _authorize(self, *, force: bool = False) -> None:
        async with self._auth_lock:
            if not force and self._authorized and time.monotonic() < self._expires_at:
                return
            self._authorized = False
            self._validated_token = None
            status, token = await self._json_request(
                "POST",
                TOKEN_URL,
                retry=True,
                data={**self._credential, "grant_type": "refresh_token"},
                byte_limit=65_536,
            )
            if status != 200:
                raise GradebookError(
                    "Google OAuth refresh failed; reconnect the configured profile."
                )
            access = token.get("access_token")
            expires = token.get("expires_in")
            if (
                not isinstance(access, str)
                or not access
                or len(access) > 16_384
                or not isinstance(token.get("token_type"), str)
                or token["token_type"].lower() != "bearer"
                or isinstance(expires, bool)
                or not isinstance(expires, (int, float))
                or not math.isfinite(expires)
                or expires <= 60
            ):
                raise GradebookError("Google OAuth returned an invalid token response.")
            scope = token.get("scope")
            if not isinstance(scope, str):
                status, info = await self._json_request(
                    "GET",
                    TOKEN_INFO_URL,
                    retry=True,
                    params={"access_token": access},
                    byte_limit=65_536,
                )
                if status != 200:
                    raise GradebookError("Google OAuth scope verification failed.")
                scope = info.get("scope")
                audience = info.get("aud", info.get("issued_to"))
                if audience is not None and audience != self._credential["client_id"]:
                    raise GradebookError("Google OAuth token audience did not match.")
            if not isinstance(scope, str) or not WRITE_SCOPES.intersection(
                scope.split()
            ):
                raise GradebookError(
                    "Google OAuth lacks a supported Sheets write scope (SCOPE_INSUFFICIENT)."
                )
            self._access_token = access
            self._expires_at = time.monotonic() + expires - 60
            self._authorized = True

    async def _get(self, params: Any) -> dict[str, Any]:
        await self._authorize()
        for attempt in range(2):
            status, body = await self._json_request(
                "GET",
                self.url,
                retry=True,
                params=params,
                headers={"Authorization": "Bearer " + str(self._access_token)},
            )
            if status == 401 and attempt == 0:
                await self._authorize(force=True)
                continue
            if status != 200:
                raise self._error(status, body)
            return body
        raise GradebookError("Google authentication failed.")

    def _sheets(self, workbook: dict[str, Any]) -> dict[int, dict[str, Any]]:
        if workbook.get("spreadsheetId") != self.workbook_id:
            raise GradebookError("Google workbook identity did not match.")
        sheets = workbook.get("sheets")
        if not isinstance(sheets, list) or not sheets or len(sheets) > 100:
            raise GradebookError("Google workbook has an unsupported sheet inventory.")
        result: dict[int, dict[str, Any]] = {}
        names: set[str] = set()
        total = 0
        for sheet in sheets:
            if not isinstance(sheet, dict) or not isinstance(
                sheet.get("properties"), dict
            ):
                raise GradebookError("Google sheet metadata is incomplete.")
            properties = sheet["properties"]
            sid, name = properties.get("sheetId"), properties.get("title")
            grid = properties.get("gridProperties")
            if (
                not isinstance(sid, int)
                or isinstance(sid, bool)
                or sid < 0
                or sid in result
                or not isinstance(name, str)
                or not name
                or len(name) > 100
                or name in names
                or properties.get("sheetType", "GRID") != "GRID"
                or not isinstance(grid, dict)
            ):
                raise GradebookError("Google sheet identity or type is invalid.")
            rows, columns = grid.get("rowCount"), grid.get("columnCount")
            if not _positive_int(rows) or not _positive_int(columns):
                raise GradebookError("Google sheet dimensions are invalid.")
            cells = rows * columns
            if name in GRADE_SHEETS:
                if rows > self.max_grade_rows or columns > self.max_grade_columns:
                    raise GradebookError(
                        "Google grade sheet exceeds configured dimensions."
                    )
            elif cells > self.max_reference_cells:
                raise GradebookError("Google reference sheet exceeds its cell limit.")
            if cells > self.sheet_cell_limits.get(name, self.max_total_cells):
                raise GradebookError("Google sheet exceeds its configured cell limit.")
            total += cells
            if total > self.max_total_cells:
                raise GradebookError("Google workbook exceeds its total cell limit.")
            names.add(name)
            result[sid] = properties
        return result

    async def metadata(self) -> dict[str, Any]:
        result = await self._get({"fields": METADATA_FIELDS})
        self._sheets(result)
        self._validated_token = self._access_token
        return result

    async def read_workbook(self) -> dict[str, Any]:
        before = self._sheets(await self.metadata())
        params = [("includeGridData", "true"), ("fields", WORKBOOK_FIELDS)]
        for properties in before.values():
            grid = properties["gridProperties"]
            name = properties["title"].replace("'", "''")
            end = column_name(grid["columnCount"]) + str(grid["rowCount"])
            params.append(("ranges", f"'{name}'!A1:{end}"))
        result = await self._get(params)
        after = self._sheets(result)
        if before != after:
            raise GradebookError(
                "Google sheet metadata changed during read; workbook retained."
            )
        for sheet in result["sheets"]:
            grid = sheet["properties"]["gridProperties"]
            blocks = sheet.get("data", [])
            if not isinstance(blocks, list) or len(blocks) > 1:
                raise GradebookError("Google returned unexpected grid blocks.")
            for block in blocks:
                if (
                    not isinstance(block, dict)
                    or block.get("startRow", 0) != 0
                    or block.get("startColumn", 0) != 0
                ):
                    raise GradebookError(
                        "Google grid coordinates did not match the requested range."
                    )
                for key, limit in (
                    ("rowData", grid["rowCount"]),
                    ("rowMetadata", grid["rowCount"]),
                    ("columnMetadata", grid["columnCount"]),
                ):
                    rows = block.get(key, [])
                    if not isinstance(rows, list) or len(rows) > limit:
                        raise GradebookError(
                            "Google returned grid data outside its metadata bounds."
                        )
                for row in block.get("rowData", []):
                    if (
                        not isinstance(row, dict)
                        or not isinstance(row.get("values", []), list)
                        or len(row.get("values", [])) > grid["columnCount"]
                    ):
                        raise GradebookError("Google returned invalid grid row data.")
                    if any(
                        not isinstance(cell, dict) for cell in row.get("values", [])
                    ):
                        raise GradebookError("Google returned invalid grid cell data.")
        self._validated_token = self._access_token
        return result

    def _batch_payload(self, requests: list[dict[str, Any]]) -> dict[str, Any]:
        if (
            not isinstance(requests, list)
            or not requests
            or any(not isinstance(r, dict) or len(r) != 1 for r in requests)
        ):
            raise GradebookError("Google batch requires a nonempty request list.")
        payload = {"requests": requests, "includeSpreadsheetInResponse": False}
        try:
            size = len(json.dumps(payload, allow_nan=False).encode())
        except (ValueError, TypeError):
            raise GradebookError("Google batch is not valid literal JSON.") from None
        if size > self.max_response_bytes:
            raise GradebookError("Google batch exceeds its size limit.")
        return payload

    async def batch(self, requests: list[dict[str, Any]]) -> dict[str, Any]:
        """Metadata/control write with an access probe before its sole POST."""
        payload = self._batch_payload(requests)
        # This read verifies actual fixed-workbook access, including after token
        # refresh. It cannot prove write permission or eliminate the edit race.
        await self.metadata()
        return await self._send_batch(payload)

    async def send_preflighted_batch(
        self, requests: list[dict[str, Any]]
    ) -> dict[str, Any]:
        """Send the grade batch once with no refresh, metadata read, or retry.

        The caller must first read/verify the workbook and durably record
        SENDING. Expired or unverified credentials stop before any HTTP call.
        ``_expires_at`` already reserves 60 seconds of actual token lifetime.
        """
        return await self._send_batch(self._batch_payload(requests))

    async def _send_batch(self, payload: dict[str, Any]) -> dict[str, Any]:
        if (
            not self._authorized
            or not self._access_token
            or self._validated_token != self._access_token
            or time.monotonic() >= self._expires_at
        ):
            raise GradebookError(
                "Google batch requires a fresh verified workbook read and unexpired token."
            )
        status, body = await self._json_request(
            "POST",
            self.url + ":batchUpdate",
            retry=False,
            payload=payload,
            headers={"Authorization": "Bearer " + str(self._access_token)},
        )
        if status != 200:
            raise self._error(status, body, write=True)
        if body.get("spreadsheetId") != self.workbook_id:
            raise GradebookError(
                "Google write readback identity is uncertain; reconcile before another write."
            )
        return body
