"""Offline decisions over complete, independently pinned Canvas file captures.

This module neither admits teaching content nor executes a refresh. Old bytes
remain old observations, even when a later metadata object matches exactly.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import stat
from datetime import datetime
from pathlib import Path
from typing import Any

from .assets import MAX_FILE_BYTES, MAX_TOTAL_BYTES, verify_assets
from .core import (
    CAPTURE_COURSES,
    ORIGIN,
    SAFE_KEY,
    MirrorError,
    encoded,
    require_valid,
    sha,
)

MAX_JSON_BYTES = 16 * 1024 * 1024
MAX_TOTAL_JSON_BYTES = 64 * 1024 * 1024
MAX_SNAPSHOT_ENTRIES = 4096
MAX_FILES = 10_000
MAX_ENDPOINT_OBJECTS = 10_000
DECISIONS = (
    "BASELINE_BYTES_REUSE_CANDIDATE",
    "HOLD_METADATA_CHANGED",
    "HOLD_VERSION_UNVERIFIED",
    "NEW_IDENTITY_REVIEW_REQUIRED",
    "OBSERVED_ABSENCE_NO_DELETE",
)


def _need(condition: object, reason: str) -> None:
    if not condition:
        raise MirrorError(reason)


def _secure_open_available() -> bool:
    return (
        os.name == "posix"
        and all(
            type(getattr(os, name, None)) is int and getattr(os, name) > 0
            for name in ("O_NOFOLLOW", "O_NONBLOCK", "O_DIRECTORY")
        )
        and {"open", "mkdir", "stat"}.issubset(
            {function.__name__ for function in os.supports_dir_fd}
        )
        and "stat" in {function.__name__ for function in os.supports_follow_symlinks}
    )


def _no_symlinks(path: Path) -> Path:
    _need(".." not in path.parts, "ASSET_PLAN_PATH_HELD")
    absolute = path.absolute()
    for item in (absolute, *absolute.parents):
        _need(not item.is_symlink(), "ASSET_PLAN_SYMLINK_HELD")
    return absolute


def _signature(info: os.stat_result) -> tuple[int, int, int, int, int]:
    return info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_mode


def _read(
    path: Path, maximum: int, *, retain: bool
) -> tuple[bytes, str, tuple[int, int, int, int, int]]:
    """Bound reads before any existing verifier can use an unbounded read."""
    path = _no_symlinks(path)
    directory_flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    directory = os.open(path.anchor, directory_flags)
    try:
        for component in path.parts[1:-1]:
            child = os.open(component, directory_flags, dir_fd=directory)
            os.close(directory)
            directory = child
        before = os.stat(path.name, dir_fd=directory, follow_symlinks=False)
        _need(stat.S_ISREG(before.st_mode), "ASSET_PLAN_REGULAR_FILE_REQUIRED")
        _need(before.st_size <= maximum, "ASSET_PLAN_INPUT_SIZE_HELD")
        descriptor = os.open(
            path.name,
            os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
            dir_fd=directory,
        )
        chunks: list[bytes] = []
        digest = hashlib.sha256()
        total = 0
        with os.fdopen(descriptor, "rb") as stream:
            opened = os.fstat(stream.fileno())
            _need(_signature(opened) == _signature(before), "ASSET_PLAN_INPUT_CHANGED")
            while chunk := stream.read(min(65536, maximum - total + 1)):
                total += len(chunk)
                _need(total <= maximum, "ASSET_PLAN_INPUT_SIZE_HELD")
                digest.update(chunk)
                if retain:
                    chunks.append(chunk)
            _need(
                _signature(os.fstat(stream.fileno())) == _signature(before),
                "ASSET_PLAN_INPUT_CHANGED",
            )
        _need(total == before.st_size, "ASSET_PLAN_INPUT_CHANGED")
        _need(
            _signature(os.stat(path.name, dir_fd=directory, follow_symlinks=False))
            == _signature(before),
            "ASSET_PLAN_INPUT_CHANGED",
        )
        return b"".join(chunks), digest.hexdigest(), _signature(before)
    finally:
        os.close(directory)


class _Inputs:
    """One bounded read set, revalidated before returning a decision."""

    def __init__(self) -> None:
        self.facts: dict[Path, tuple[str, tuple[int, int, int, int, int]]] = {}
        self.json_bytes = 0

    def json(self, path: Path) -> Any:
        raw, digest, signature = _read(path, MAX_JSON_BYTES, retain=True)
        if path not in self.facts:
            self.json_bytes += len(raw)
        else:
            _need(self.facts[path] == (digest, signature), "ASSET_PLAN_INPUT_CHANGED")
        _need(self.json_bytes <= MAX_TOTAL_JSON_BYTES, "ASSET_PLAN_JSON_BUDGET_HELD")
        self.facts[path] = digest, signature
        return json.loads(
            raw,
            object_pairs_hook=_json_object,
            parse_constant=_json_constant,
            parse_float=_json_float,
        )

    def content(self, path: Path, size: int, digest: str) -> None:
        _, actual, signature = _read(path, size, retain=False)
        _need(
            signature[2] == size and actual == digest, "ASSET_PLAN_BASELINE_BYTES_HELD"
        )
        if path in self.facts:
            _need(self.facts[path] == (actual, signature), "ASSET_PLAN_INPUT_CHANGED")
        self.facts[path] = actual, signature

    def recheck(self) -> None:
        for path, (digest, signature) in self.facts.items():
            _, current_digest, current_signature = _read(
                path, signature[2], retain=False
            )
            _need(
                (current_digest, current_signature) == (digest, signature),
                "ASSET_PLAN_INPUT_CHANGED",
            )

    def read_bytes(self, path: Path) -> bytes:
        """Shared verifiers may reopen only an exact, preflighted bounded file."""
        _need(path in self.facts, "ASSET_PLAN_UNBOUND_VERIFIER_INPUT")
        digest, signature = self.facts[path]
        raw, current_digest, current_signature = _read(path, signature[2], retain=True)
        _need(
            (current_digest, current_signature) == (digest, signature),
            "ASSET_PLAN_INPUT_CHANGED",
        )
        return raw


def _json_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result = {}
    for key, value in pairs:
        _need(key not in result, "ASSET_PLAN_JSON_DUPLICATE_KEY")
        result[key] = value
    return result


def _json_constant(value: str) -> Any:
    raise MirrorError("ASSET_PLAN_JSON_NONFINITE_VALUE")


def _json_float(value: str) -> float:
    parsed = float(value)
    _need(math.isfinite(parsed), "ASSET_PLAN_JSON_NONFINITE_VALUE")
    return parsed


def _timestamp(value: Any) -> datetime | None:
    if type(value) is not str:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return (
            parsed
            if parsed.tzinfo is not None and parsed.utcoffset() is not None
            else None
        )
    except ValueError:
        return None


def _hash(value: Any) -> bool:
    return type(value) is str and re.fullmatch(r"[a-f0-9]{64}", value) is not None


def _identity(value: Any) -> str:
    _need(
        type(value) in (int, str) and re.fullmatch(r"[0-9]+", str(value)),
        "ASSET_PLAN_IDENTITY_HELD",
    )
    return str(value)


def _inventory(value: Any) -> dict[str, dict[str, Any]]:
    _need(type(value) is list and len(value) <= MAX_FILES, "ASSET_PLAN_INVENTORY_HELD")
    result: dict[str, dict[str, Any]] = {}
    total = 0
    for metadata in value:
        _need(type(metadata) is dict, "ASSET_PLAN_METADATA_HELD")
        identity = _identity(metadata.get("id"))
        _need(identity not in result, "ASSET_PLAN_DUPLICATE_IDENTITY")
        size = metadata.get("size")
        _need(
            type(size) is int and 0 <= size <= MAX_FILE_BYTES,
            "ASSET_PLAN_FILE_SIZE_HELD",
        )
        total += size
        _need(total <= MAX_TOTAL_BYTES, "ASSET_PLAN_BYTE_BUDGET_HELD")
        result[identity] = metadata
    return result


def _snapshot(
    root: Path, inputs: _Inputs
) -> tuple[dict[str, Any], dict[tuple[str, str], dict[str, Any]], dict[str, str]]:
    _no_symlinks(root)
    manifest = inputs.json(root / "manifest.json")
    _need(type(manifest) is dict, "ASSET_PLAN_SNAPSHOT_SCHEMA_HELD")
    _need(
        type(manifest.get("schema_version")) is int
        and manifest["schema_version"] == 1
        and manifest.get("kind") == "content_mirror"
        and manifest.get("status") == "COMPLETE"
        and manifest.get("origin") == ORIGIN
        and type(manifest.get("canvas_writes")) is int
        and manifest["canvas_writes"] == 0
        and "error" not in manifest
        and "endpoints" not in manifest,
        "ASSET_PLAN_COMPLETE_SNAPSHOT_REQUIRED",
    )
    courses = manifest.get("courses")
    _need(type(courses) is dict and courses, "ASSET_PLAN_COURSE_SCOPE_HELD")
    _need(
        all(
            label in CAPTURE_COURSES and identity == CAPTURE_COURSES[label]
            for label, identity in courses.items()
        ),
        "ASSET_PLAN_COURSE_SCOPE_HELD",
    )
    started, finished = (
        _timestamp(manifest.get("started_at")),
        _timestamp(manifest.get("finished_at")),
    )
    _need(
        started is not None and finished is not None and started <= finished,
        "ASSET_PLAN_CAPTURE_INTERVAL_HELD",
    )
    assert started is not None and finished is not None
    interval = {"started_at": started.isoformat(), "finished_at": finished.isoformat()}
    entries = manifest.get("entries")
    _need(
        type(entries) is list and 0 < len(entries) <= MAX_SNAPSHOT_ENTRIES,
        "ASSET_PLAN_ENDPOINT_COUNT_HELD",
    )
    files = {}
    seen = set()
    for entry in entries:
        _need(type(entry) is dict, "ASSET_PLAN_ENDPOINT_HELD")
        label, key = entry.get("course"), entry.get("key")
        _need(
            type(label) is str
            and label in courses
            and type(key) is str
            and SAFE_KEY.fullmatch(key),
            "ASSET_PLAN_ENDPOINT_HELD",
        )
        _need((label, key) not in seen, "ASSET_PLAN_DUPLICATE_ENDPOINT")
        seen.add((label, key))
        relative = f"{label}/objects/{key}.json"
        _need(
            entry.get("path") == relative and _hash(entry.get("sha256")),
            "ASSET_PLAN_ENDPOINT_HELD",
        )
        _need(
            type(entry.get("count")) is int
            and 0 <= entry["count"] <= MAX_ENDPOINT_OBJECTS,
            "ASSET_PLAN_ENDPOINT_HELD",
        )
        body = inputs.json(root / relative)
        _need(
            inputs.facts[root / relative][0] == entry["sha256"],
            "ASSET_PLAN_SOURCE_HASH_HELD",
        )
        _need(type(body) in (list, dict), "ASSET_PLAN_ENDPOINT_SHAPE_HELD")
        _need(
            (len(body) if isinstance(body, list) else 1) == entry["count"],
            "ASSET_PLAN_ENDPOINT_COUNT_HELD",
        )
        if key == "files":
            files.update(
                {
                    (label, identity): metadata
                    for identity, metadata in _inventory(body).items()
                }
            )
    _need(
        sum(item["size"] for item in files.values()) <= MAX_TOTAL_BYTES,
        "ASSET_PLAN_BYTE_BUDGET_HELD",
    )
    require_valid(root, read_bytes=inputs.read_bytes)
    return manifest, files, interval


def _baseline(
    root: Path,
    snapshot: Path,
    source: dict[str, Any],
    files: dict[tuple[str, str], dict[str, Any]],
    inputs: _Inputs,
) -> dict[tuple[str, str], dict[str, Any]]:
    _no_symlinks(root)
    manifest = inputs.json(root / "assets-manifest.json")
    _need(type(manifest) is dict, "ASSET_PLAN_BASELINE_SCHEMA_HELD")
    _need(
        type(manifest.get("schema_version")) is int
        and manifest["schema_version"] == 1
        and manifest.get("kind") == "canvas_file_assets"
        and manifest.get("status") == "COMPLETE"
        and type(manifest.get("canvas_writes")) is int
        and manifest["canvas_writes"] == 0
        and "error" not in manifest,
        "ASSET_PLAN_COMPLETE_BASELINE_REQUIRED",
    )
    _need(
        manifest.get("source_snapshot") == snapshot.name
        and manifest.get("source_manifest_sha256")
        == inputs.facts[snapshot / "manifest.json"][0]
        and manifest.get("courses") == source["courses"],
        "ASSET_PLAN_BASELINE_SOURCE_HELD",
    )
    records = manifest.get("files")
    _need(
        type(records) is list and len(records) <= MAX_FILES,
        "ASSET_PLAN_BASELINE_INVENTORY_HELD",
    )
    _need(
        type(manifest.get("expected_count")) is int
        and manifest["expected_count"] == len(files) == len(records),
        "ASSET_PLAN_BASELINE_INVENTORY_HELD",
    )
    _need(
        type(manifest.get("expected_bytes")) is int
        and manifest["expected_bytes"] == sum(row["size"] for row in files.values()),
        "ASSET_PLAN_BASELINE_INVENTORY_HELD",
    )
    result = {}
    for entry in records:
        _need(type(entry) is dict, "ASSET_PLAN_BASELINE_ENTRY_HELD")
        label, identity = entry.get("course"), entry.get("id")
        _need(
            type(label) is str and type(identity) is str,
            "ASSET_PLAN_BASELINE_ENTRY_HELD",
        )
        key = label, identity
        _need(key in files and key not in result, "ASSET_PLAN_BASELINE_IDENTITY_HELD")
        metadata = files[key]
        relative, metadata_relative = (
            f"{label}/files/{identity}/content.bin",
            f"{label}/files/{identity}/metadata.json",
        )
        _need(
            entry.get("status") == "COMPLETE"
            and entry.get("course_id") == source["courses"][label]
            and entry.get("path") == relative
            and entry.get("metadata_path") == metadata_relative
            and type(entry.get("size")) is int
            and entry["size"] == metadata["size"]
            and _hash(entry.get("sha256"))
            and entry.get("metadata_sha256") == sha(encoded(metadata)),
            "ASSET_PLAN_BASELINE_ENTRY_HELD",
        )
        downloaded = _timestamp(entry.get("downloaded_at"))
        _need(downloaded is not None, "ASSET_PLAN_BASELINE_DOWNLOAD_TIME_HELD")
        saved_metadata = inputs.json(root / metadata_relative)
        _need(
            saved_metadata == metadata
            and inputs.facts[root / metadata_relative][0] == entry["metadata_sha256"],
            "ASSET_PLAN_BASELINE_METADATA_HELD",
        )
        inputs.content(root / relative, entry["size"], entry["sha256"])
        result[key] = entry
    _need(set(result) == set(files), "ASSET_PLAN_BASELINE_INVENTORY_HELD")
    # The existing verifier remains the owner of the complete asset contract.
    # Every path, declared size and actual byte length was bounded above first.
    _need(
        verify_assets(root, snapshot, read_bytes=inputs.read_bytes)["ok"],
        "ASSET_PLAN_BASELINE_VERIFICATION_HELD",
    )
    return result


def _version_valid(metadata: dict[str, Any]) -> bool:
    fields = [key for key in ("updated_at", "modified_at") if key in metadata]
    return bool(fields) and all(_timestamp(metadata[key]) is not None for key in fields)


def plan_asset_refresh(
    *, baseline_snapshot: Path, baseline_assets: Path, current_snapshot: Path
) -> dict[str, Any]:
    """Return a deterministic private plan, without changing any local/remote data.

    Invalid provenance or any incomplete/corrupt baseline raises MirrorError.
    A successful plan still requires review and grants no fetch/reuse authority.
    """
    try:
        _need(_secure_open_available(), "ASSET_PLAN_SECURE_OPEN_UNAVAILABLE")
        inputs = _Inputs()
        baseline_snapshot = _no_symlinks(baseline_snapshot)
        baseline_assets = _no_symlinks(baseline_assets)
        current_snapshot = _no_symlinks(current_snapshot)
        old_source, old, old_interval = _snapshot(baseline_snapshot, inputs)
        new_source, current, current_interval = _snapshot(current_snapshot, inputs)
        _need(
            old_source["courses"] == new_source["courses"], "ASSET_PLAN_SCOPE_CHANGED"
        )
        assets = _baseline(baseline_assets, baseline_snapshot, old_source, old, inputs)
        entries = []
        counts = dict.fromkeys(DECISIONS, 0)
        for label, identity in sorted(old.keys() | current.keys()):
            key = label, identity
            before, after = old.get(key), current.get(key)
            entry: dict[str, Any] = {
                "course": label,
                "course_id": old_source["courses"][label],
                "id": identity,
            }
            if before is None:
                decision = "NEW_IDENTITY_REVIEW_REQUIRED"
            elif after is None:
                decision = "OBSERVED_ABSENCE_NO_DELETE"
            elif not _version_valid(before) or not _version_valid(after):
                decision = "HOLD_VERSION_UNVERIFIED"
            elif encoded(before) != encoded(after):
                decision = "HOLD_METADATA_CHANGED"
            else:
                decision = "BASELINE_BYTES_REUSE_CANDIDATE"
            if before is not None:
                asset = assets[key]
                downloaded = _timestamp(asset["downloaded_at"])
                assert downloaded is not None
                entry.update(
                    baseline_path=asset["path"],
                    baseline_size=asset["size"],
                    baseline_sha256=asset["sha256"],
                    baseline_downloaded_at=downloaded.isoformat(),
                    baseline_metadata_sha256=sha(encoded(before)),
                )
            if after is not None:
                entry["current_metadata_sha256"] = sha(encoded(after))
            entry["decision"] = decision
            entries.append(entry)
            counts[decision] += 1
        inputs.recheck()
        return {
            "schema_version": 1,
            "kind": "canvas_file_asset_refresh_plan",
            "ok": True,
            "status": "REVIEW_REQUIRED",
            "input_manifest_sha256": {
                "baseline_snapshot": inputs.facts[baseline_snapshot / "manifest.json"][
                    0
                ],
                "baseline_assets": inputs.facts[
                    baseline_assets / "assets-manifest.json"
                ][0],
                "current_snapshot": inputs.facts[current_snapshot / "manifest.json"][0],
            },
            "capture_intervals": {
                "baseline": old_interval,
                "current": current_interval,
            },
            "entries": entries,
            "counts": counts,
            "bytes": {
                "baseline_verified": sum(metadata["size"] for metadata in old.values()),
                "current_inventory": sum(
                    metadata["size"] for metadata in current.values()
                ),
                "reuse_candidate": sum(
                    entry["baseline_size"]
                    for entry in entries
                    if entry["decision"] == "BASELINE_BYTES_REUSE_CANDIDATE"
                ),
            },
            "source_admission": "NOT_ESTABLISHED",
            "download_authorized": False,
            "network_requests": 0,
            "canvas_writes": 0,
            "google_writes": 0,
        }
    except MirrorError:
        raise
    except (
        OSError,
        ValueError,
        TypeError,
        KeyError,
        OverflowError,
        RecursionError,
    ) as exc:
        raise MirrorError("ASSET_PLAN_INPUT_HELD") from exc
