"""Pure predecessor native-readback comparator for fictional regression tests."""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime, timedelta
from typing import Any


def need(value: Any, code: str) -> None:
    if not value:
        raise ValueError(code)


def full_raw_matches(
    expected: dict[str, Any], actual: dict[str, Any], *, workbook_id: str
) -> bool:
    """Permit bound heartbeat advance and stable metadata-ID array order only.

    Original observations remain untouched. The exact timestamp JSON token is
    separated and unique positive exact-int metadata IDs ordered only in
    comparison copies; all other metadata string bytes and all other raw JSON
    values, presence and types remain protected.
    """

    def pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in items:
            if key in result:
                raise ValueError("DUPLICATE_HEARTBEAT_KEY")
            result[key] = value
        return result

    def invalid_constant(_: str) -> Any:
        raise ValueError("NONFINITE_HEARTBEAT_VALUE")

    def heartbeat(raw: dict[str, Any]) -> tuple[dict[str, Any], datetime]:
        need(
            type(raw) is dict
            and type(workbook_id) is str
            and bool(workbook_id)
            and raw.get("spreadsheetId") == workbook_id,
            "BOUND_WORKBOOK_REQUIRED",
        )
        metadata = raw.get("developerMetadata")
        need(type(metadata) is list, "HEARTBEAT_METADATA_REQUIRED")
        need(
            all(
                type(entry) is dict
                and "metadataId" in entry
                and type(entry["metadataId"]) is int
                and entry["metadataId"] > 0
                for entry in metadata
            ),
            "STABLE_TYPED_METADATA_IDS_REQUIRED",
        )
        need(
            len({entry["metadataId"] for entry in metadata}) == len(metadata),
            "UNIQUE_METADATA_IDS_REQUIRED",
        )
        matches = [
            (i, entry)
            for i, entry in enumerate(metadata)
            if type(entry) is dict
            and (
                entry.get("metadataKey") == "sdm.gradebook.refresh.heartbeat.v1"
                or entry.get("metadataId") == 2026092904
            )
        ]
        need(len(matches) == 1, "UNIQUE_BOUND_HEARTBEAT_REQUIRED")
        index, entry = matches[0]
        need(
            set(entry)
            == {"location", "metadataId", "metadataKey", "metadataValue", "visibility"}
            and type(entry["metadataId"]) is int
            and entry["metadataId"] == 2026092904
            and type(entry["metadataKey"]) is str
            and entry["metadataKey"] == "sdm.gradebook.refresh.heartbeat.v1"
            and type(entry["visibility"]) is str
            and entry["visibility"] == "DOCUMENT"
            and type(entry["location"]) is dict
            and set(entry["location"]) == {"locationType", "spreadsheet"}
            and type(entry["location"]["locationType"]) is str
            and entry["location"]["locationType"] == "SPREADSHEET"
            and entry["location"]["spreadsheet"] is True
            and type(entry["metadataValue"]) is str,
            "EXACT_HEARTBEAT_METADATA_REQUIRED",
        )
        value = entry["metadataValue"]
        payload = json.loads(
            value, object_pairs_hook=pairs, parse_constant=invalid_constant
        )
        need(
            type(payload) is dict
            and set(payload)
            == {"v", "workbook_id", "state", "refresh_mode", "updated_at"}
            and type(payload["v"]) is int
            and payload["v"] == 1
            and type(payload["workbook_id"]) is str
            and payload["workbook_id"] == workbook_id
            and type(payload["state"]) is str
            and payload["state"] == "READY"
            and type(payload["refresh_mode"]) is str
            and payload["refresh_mode"] == "GET_ONLY"
            and type(payload["updated_at"]) is str,
            "EXACT_READY_GET_ONLY_HEARTBEAT_REQUIRED",
        )
        timestamp = payload["updated_at"]
        need(
            re.fullmatch(
                r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|[+-]\d{2}:\d{2})",
                timestamp,
                flags=re.ASCII,
            )
            is not None,
            "AWARE_HEARTBEAT_TIMESTAMP_REQUIRED",
        )
        observed = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
        need(observed.tzinfo is not None, "AWARE_HEARTBEAT_TIMESTAMP_REQUIRED")
        tokens = list(re.finditer(r'"updated_at"\s*:\s*("[^"\\]*")', value))
        need(
            len(tokens) == 1 and tokens[0].group(1) == json.dumps(timestamp),
            "ONE_LITERAL_HEARTBEAT_TIMESTAMP_REQUIRED",
        )
        token = tokens[0]
        compared_entry = dict(entry)
        compared_entry["metadataValue"] = (
            value[: token.start(1)]
            + '"__BOUND_HEARTBEAT_TIME__"'
            + value[token.end(1) :]
        )
        compared_metadata = list(metadata)
        compared_metadata[index] = compared_entry
        compared_metadata.sort(key=lambda item: item["metadataId"])
        compared_raw = dict(raw)
        compared_raw["developerMetadata"] = compared_metadata
        return compared_raw, observed

    try:
        before, before_time = heartbeat(expected)
        after, after_time = heartbeat(actual)
        if not before_time <= after_time <= datetime.now(UTC) + timedelta(seconds=5):
            return False
        return json.dumps(
            before, sort_keys=True, separators=(",", ":"), allow_nan=False
        ) == json.dumps(after, sort_keys=True, separators=(",", ":"), allow_nan=False)
    except (ValueError, TypeError, KeyError, OverflowError):
        return False
