"""Bounded Google Sheets transport for the private, local refresh worker.

Credentials remain local. Reads may retry; a Sheets batch is transmitted once
only. The caller must durably record SENDING before calling ``batch`` and must
reconcile uncertain outcomes instead of repeating that call.
"""

from __future__ import annotations

import asyncio
import copy
import json
import math
import os
import re
import stat
import time
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
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
METADATA_FIELDS = (
    "spreadsheetId,developerMetadata,"
    "sheets(properties,protectedRanges,conditionalFormats,basicFilter)"
)
WORKBOOK_FIELDS = (
    "spreadsheetId,developerMetadata,"
    "sheets(properties,protectedRanges,conditionalFormats,basicFilter,"
    "data(startRow,startColumn,rowMetadata,columnMetadata,"
    "rowData(values(userEnteredValue,userEnteredFormat,note,dataValidation))))"
)
MAX_RETURNED_CELLS = 500_000  # Matches native.MAX_NATIVE_CELLS.


@dataclass
class _ReadBudget:
    returned_bytes: int = 0
    returned_cells: int = 0


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
        max_chunk_cells: int = 10_000,
        max_total_response_bytes: int = 80_000_000,
        max_chunk_requests: int = 200,
        read_timeout_seconds: float = 180,
        read_interval_seconds: float = 1.1,
        read_clock: Callable[[], float] | None = None,
        read_sleep: Callable[[float], Awaitable[None]] | None = None,
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
            max_chunk_cells,
            max_total_response_bytes,
            max_chunk_requests,
        )
        if not all(_positive_int(limit) for limit in limits):
            raise GradebookError("Google read limits must be positive integers.")
        if (
            isinstance(read_timeout_seconds, bool)
            or not isinstance(read_timeout_seconds, (int, float))
            or not math.isfinite(read_timeout_seconds)
            or read_timeout_seconds <= 0
        ):
            raise GradebookError("Google read timeout must be positive and finite.")
        if (
            isinstance(read_interval_seconds, bool)
            or not isinstance(read_interval_seconds, (int, float))
            or not math.isfinite(read_interval_seconds)
            or read_interval_seconds < 0
        ):
            raise GradebookError("Google read interval must be nonnegative and finite.")
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
        self.max_chunk_cells = max_chunk_cells
        self.max_total_response_bytes = max_total_response_bytes
        self.max_chunk_requests = max_chunk_requests
        self.read_timeout_seconds = read_timeout_seconds
        self.read_interval_seconds = read_interval_seconds
        self._read_clock = read_clock or time.monotonic
        self._read_sleep = read_sleep or asyncio.sleep
        self._last_read_started: float | None = None
        self._read_lock = asyncio.Lock()
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

    async def _pace_read(self) -> None:
        # All Sheets GETs, including retries and control polling, share one
        # start-time limiter. 1.1 seconds stays below 60 reads/minute per user.
        async with self._read_lock:
            if self._last_read_started is not None:
                delay = (
                    self._last_read_started
                    + self.read_interval_seconds
                    - self._read_clock()
                )
                if delay > 0:
                    await self._read_sleep(delay)
            self._last_read_started = self._read_clock()

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
        read_budget: _ReadBudget | None = None,
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
                if method == "GET" and url == self.url:
                    await self._pace_read()
                async with self.http.stream(
                    method, url, headers=headers, params=params, data=data, json=payload
                ) as response:
                    length = response.headers.get("content-length")
                    if length and (not length.isdecimal() or int(length) > limit):
                        raise GradebookError("Google response exceeded its size limit.")
                    body = bytearray()
                    async for chunk in response.aiter_bytes(chunk_size=65_536):
                        if read_budget is not None:
                            read_budget.returned_bytes += len(chunk)
                            if (
                                read_budget.returned_bytes
                                > self.max_total_response_bytes
                            ):
                                raise GradebookError(
                                    "Google workbook read exceeded its cumulative byte limit."
                                )
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

    async def _get(
        self, params: Any, *, read_budget: _ReadBudget | None = None
    ) -> dict[str, Any]:
        await self._authorize()
        if isinstance(params, dict):
            params = {**params, "prettyPrint": "false"}
        else:
            params = [*(params or []), ("prettyPrint", "false")]
        for attempt in range(2):
            status, body = await self._json_request(
                "GET",
                self.url,
                retry=True,
                params=params,
                headers={"Authorization": "Bearer " + str(self._access_token)},
                read_budget=read_budget,
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

    async def metadata(
        self, *, _read_budget: _ReadBudget | None = None
    ) -> dict[str, Any]:
        result = await self._get({"fields": METADATA_FIELDS}, read_budget=_read_budget)
        self._sheets(result)
        self._validated_token = self._access_token
        return result

    async def read_workbook(self) -> dict[str, Any]:
        """Capture all allocated cells in bounded, sequential rectangles.

        A range response may omit empty trailing cells, but no allocated range
        is skipped. Metadata brackets the complete capture. This is an interval
        observation, not a server-side transaction; the worker still requires
        an idle workbook and its separate fresh-input check before any write.
        """
        self._validated_token = None
        try:
            async with asyncio.timeout(self.read_timeout_seconds):
                return await self._read_workbook()
        except TimeoutError:
            self._validated_token = None
            raise GradebookError(
                "Google workbook read exceeded its time limit; no partial read accepted."
            ) from None
        except BaseException:
            self._validated_token = None
            raise

    @staticmethod
    def _header(sheet: dict[str, Any]) -> dict[str, Any]:
        result = {"properties": sheet["properties"]}
        for key in ("protectedRanges", "conditionalFormats", "basicFilter"):
            value = sheet.get(key, {} if key == "basicFilter" else [])
            if (key == "basicFilter" and not isinstance(value, dict)) or (
                key != "basicFilter"
                and (
                    not isinstance(value, list)
                    or any(not isinstance(item, dict) for item in value)
                )
            ):
                raise GradebookError("Google returned invalid sheet-level metadata.")
            result[key] = value
        return result

    @classmethod
    def _chunk_header_matches(
        cls, sheet: dict[str, Any], expected: dict[str, Any]
    ) -> bool:
        actual = cls._header(sheet)
        if actual["properties"] != expected["properties"]:
            return False
        # Sheets filters range-related metadata in a range-limited response.
        # Retain complete headers from the bracketing, unrestricted reads;
        # any metadata returned here must still be an exact, ordered subset.
        for key in ("protectedRanges", "conditionalFormats"):
            remaining = iter(expected[key])
            for item in actual[key]:
                if not any(item == known for known in remaining):
                    return False
        return (
            not actual["basicFilter"]
            or actual["basicFilter"] == expected["basicFilter"]
        )

    def _rectangles(
        self, inventory: dict[int, dict[str, Any]]
    ) -> list[tuple[int, int, int, int, int]]:
        result = []
        for sid, properties in inventory.items():
            grid = properties["gridProperties"]
            # Ordinarily only rows are chunked. Very wide reference sheets are
            # tiled by column too, so even one requested row obeys the bound.
            width = min(grid["columnCount"], self.max_chunk_cells)
            for c0 in range(0, grid["columnCount"], width):
                c1 = min(c0 + width, grid["columnCount"])
                height = max(1, self.max_chunk_cells // (c1 - c0))
                for r0 in range(0, grid["rowCount"], height):
                    r1 = min(r0 + height, grid["rowCount"])
                    result.append((sid, r0, r1, c0, c1))
                    if len(result) > self.max_chunk_requests:
                        raise GradebookError(
                            "Google workbook exceeds the bounded chunk request count."
                        )
        return result

    @staticmethod
    def _dimensions(
        raw: list[dict[str, Any]],
        start: int,
        stop: int,
        seen: dict[int, dict[str, Any]],
    ) -> list[dict[str, Any]]:
        output: list[dict[str, Any]] = []
        for offset, position in enumerate(range(start, stop)):
            value = raw[offset] if offset < len(raw) else {}
            if not isinstance(value, dict):
                raise GradebookError("Google returned invalid dimension metadata.")
            if position in seen:
                if seen[position] != value:
                    raise GradebookError(
                        "Google dimension metadata changed between chunks."
                    )
                output.append({})
            else:
                seen[position] = copy.deepcopy(value)
                output.append(copy.deepcopy(value))
        # Remove only empty suffixes, never interior placeholders or offsets.
        while output and not output[-1]:
            output.pop()
        return output

    def _chunk(
        self,
        sheet: dict[str, Any],
        bounds: tuple[int, int, int, int],
        seen_rows: dict[int, dict[str, Any]],
        seen_columns: dict[int, dict[str, Any]],
        budget: _ReadBudget,
    ) -> dict[str, Any]:
        r0, r1, c0, c1 = bounds
        blocks = sheet.get("data", [])
        if not isinstance(blocks, list) or len(blocks) > 1:
            raise GradebookError("Google returned unexpected grid blocks.")
        block = blocks[0] if blocks else {}
        if not isinstance(block, dict) or (
            blocks
            and (
                type(block.get("startRow", 0)) is not int
                or type(block.get("startColumn", 0)) is not int
                or block.get("startRow", 0) != r0
                or block.get("startColumn", 0) != c0
            )
        ):
            raise GradebookError(
                "Google grid coordinates did not match the requested range."
            )
        for key, limit in (
            ("rowData", r1 - r0),
            ("rowMetadata", r1 - r0),
            ("columnMetadata", c1 - c0),
        ):
            items = block.get(key, [])
            if not isinstance(items, list) or len(items) > limit:
                raise GradebookError(
                    "Google returned grid data outside the requested rectangle."
                )
        rows = block.get("rowData", [])
        for row in rows:
            if (
                not isinstance(row, dict)
                or not isinstance(row.get("values", []), list)
                or len(row.get("values", [])) > c1 - c0
            ):
                raise GradebookError("Google returned invalid grid row data.")
            values = row.get("values", [])
            if any(not isinstance(cell, dict) for cell in values):
                raise GradebookError("Google returned invalid grid cell data.")
            budget.returned_cells += len(values)
            if budget.returned_cells > MAX_RETURNED_CELLS:
                raise GradebookError(
                    "Google workbook exceeds the native returned-cell limit."
                )
        return {
            "startRow": r0,
            "startColumn": c0,
            "rowData": rows,
            "rowMetadata": self._dimensions(
                block.get("rowMetadata", []), r0, r1, seen_rows
            ),
            "columnMetadata": self._dimensions(
                block.get("columnMetadata", []), c0, c1, seen_columns
            ),
        }

    async def _read_workbook(self) -> dict[str, Any]:
        budget = _ReadBudget()
        initial = await self.metadata(_read_budget=budget)
        before = self._sheets(initial)
        headers = {
            s["properties"]["sheetId"]: self._header(s) for s in initial["sheets"]
        }
        rectangles = self._rectangles(before)
        captured: dict[int, list[dict[str, Any]]] = {sid: [] for sid in before}
        rows: dict[int, dict[int, dict[str, Any]]] = {sid: {} for sid in before}
        columns: dict[int, dict[int, dict[str, Any]]] = {sid: {} for sid in before}
        for sid, r0, r1, c0, c1 in rectangles:
            name = before[sid]["title"].replace("'", "''")
            requested = f"'{name}'!{column_name(c0 + 1)}{r0 + 1}:{column_name(c1)}{r1}"
            part = await self._get(
                [
                    ("includeGridData", "true"),
                    ("fields", WORKBOOK_FIELDS),
                    ("ranges", requested),
                ],
                read_budget=budget,
            )
            inventory = self._sheets(part)
            if sid not in inventory or any(
                key not in before or value != before[key]
                for key, value in inventory.items()
            ):
                raise GradebookError(
                    "Google chunk sheet inventory changed during read."
                )
            for sheet in part["sheets"]:
                returned_id = sheet["properties"]["sheetId"]
                if not self._chunk_header_matches(sheet, headers[returned_id]):
                    raise GradebookError(
                        "Google sheet metadata changed between chunks."
                    )
                if returned_id != sid:
                    if sheet.get("data", []):
                        raise GradebookError(
                            "Google returned data for an unrequested sheet."
                        )
                    continue
                captured[sid].append(
                    self._chunk(
                        sheet, (r0, r1, c0, c1), rows[sid], columns[sid], budget
                    )
                )
        final = await self.metadata(_read_budget=budget)
        if (
            self._sheets(final) != before
            or {s["properties"]["sheetId"]: self._header(s) for s in final["sheets"]}
            != headers
        ):
            raise GradebookError(
                "Google sheet metadata changed during read; workbook retained."
            )
        # Use final coordination metadata while preserving every captured native
        # cell field. Native validation understands these nonoverlapping blocks.
        result = copy.deepcopy(final)
        for sheet in result["sheets"]:
            sheet["data"] = captured[sheet["properties"]["sheetId"]]
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
