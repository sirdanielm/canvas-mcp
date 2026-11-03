"""Qualify repeated-field semantics from a genuine full direct metadata GET.

Raw omissions remain omissions. Derived empty collections are protocol
inferences, not observed arrays or protection/permission/write authority.
"""

from __future__ import annotations

import copy
import hashlib
import inspect
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote

import httpx

from . import google as google_module
from .client import GradebookError
from .google import GoogleSheets

MASK = (
    "spreadsheetId,developerMetadata,namedRanges,"
    "sheets(properties,merges,protectedRanges,conditionalFormats,basicFilter)"
)
SOURCES = (
    "https://developers.google.com/workspace/sheets/api/reference/rest/v4/spreadsheets/get",
    "https://developers.google.com/workspace/sheets/api/reference/rest/v4/spreadsheets",
    "https://developers.google.com/workspace/sheets/api/reference/rest/v4/spreadsheets/sheets",
    "https://developers.google.com/workspace/sheets/api/guides/field-masks",
    "https://protobuf.dev/programming-guides/json/",
)


def _need(value: object, code: str) -> None:
    if not value:
        raise GradebookError(code)


def _collection(container: dict[str, Any], key: str) -> dict[str, Any]:
    if key not in container:
        return {
            "raw_present": False,
            "raw_value": None,
            "derived_entries": (),
            "basis": "PROTOJSON_IMPLICIT_EMPTY_REPEATED_FROM_COMPLETE_UNRANGED_GET",
            "is_protocol_inference": True,
        }
    value = container[key]
    _need(
        type(value) is list and all(type(v) is dict for v in value),
        "DIRECT_METADATA_REPEATED_FIELD_WRONG_TYPE",
    )
    return {
        "raw_present": True,
        "raw_value": copy.deepcopy(value),
        "derived_entries": tuple(copy.deepcopy(value)),
        "basis": "ACTUALLY_RETURNED_ARRAY",
        "is_protocol_inference": False,
    }


async def observe_direct_metadata_collections(
    client: GoogleSheets,
    *,
    expected_workbook_id: str,
    sheet_id: int,
) -> dict[str, Any]:
    """Issue the covered request ourselves; never trust a request's flags/raw.

    The original application must separately qualify the configured client,
    runtime, target identity, actual protection and write permission. There is
    no arbitrary endpoint/mask/ranges/raw-response input or connector fallback.
    """
    _need(
        type(client) is GoogleSheets
        and type(sheet_id) is int
        and sheet_id >= 0
        and type(expected_workbook_id) is str
        and bool(expected_workbook_id)
        and client.workbook_id == expected_workbook_id,
        "DIRECT_METADATA_CONFIGURED_IDENTITY_REQUIRED",
    )
    _need(
        client.url
        == "https://sheets.googleapis.com/v4/spreadsheets/"
        + quote(expected_workbook_id, safe="")
        and google_module.METADATA_FIELDS == MASK
        and all(
            inspect.ismethod(getattr(client, name))
            and getattr(client, name).__func__ is getattr(GoogleSheets, name)
            for name in ("metadata", "_get", "_json_request")
        )
        and type(client.http) is httpx.AsyncClient
        and type(client.http._transport) is httpx.AsyncHTTPTransport
        and type(client.http._transport._pool).__name__ == "AsyncConnectionPool"
        and type(client.http._transport._pool).__module__ == "httpcore"
        and client.http.event_hooks == {"request": [], "response": []}
        and client.http._trust_env is False
        and not client.http._mounts
        and client.http.follow_redirects is False,
        "DIRECT_UNFILTERED_METADATA_ROUTE_REQUIRED",
    )
    started = datetime.now(UTC).isoformat()
    raw = await client.metadata()
    # metadata() invokes the original successful native GET with the exact mask,
    # no ranges/data filters and no local projection. Errors/truncation raise.
    _need(
        type(raw) is dict
        and raw.get("spreadsheetId") == expected_workbook_id
        and type(raw.get("sheets")) is list,
        "DIRECT_METADATA_SUCCESSFUL_RESPONSE_REQUIRED",
    )
    matches = [
        s
        for s in raw["sheets"]
        if type(s) is dict and s.get("properties", {}).get("sheetId") == sheet_id
    ]
    _need(len(matches) == 1, "DIRECT_METADATA_EXACT_SHEET_REQUIRED")
    observed = datetime.now(UTC).isoformat()
    return {
        "contract": "DIRECT_FULL_METADATA_REPEATED_COLLECTIONS_V1",
        "raw": copy.deepcopy(raw),
        "sheet_id": sheet_id,
        "collections": {
            "namedRanges": _collection(raw, "namedRanges"),
            "merges": _collection(matches[0], "merges"),
        },
        "coverage": {
            "method": "GET",
            "complete_unranged": True,
            "requested_fields": MASK,
            "ranges_or_data_filters": False,
            "local_projection_or_proxy": False,
            "original_metadata_source": str(Path(google_module.__file__)),
            "original_metadata_source_sha256": hashlib.sha256(
                Path(google_module.__file__).read_bytes()
            ).hexdigest(),
        },
        "request_started_at_utc": started,
        "observed_at_utc": observed,
        "protocol_primary_sources": SOURCES,
        "raw_omissions_preserved": True,
        "permission_or_write_authority_granted": False,
        "protection_defaults_inferred": False,
        "returned_entry_schema_or_target_membership_qualified": False,
    }
