"""Bounded file-byte GETs with private, exact-identity integrity receipts."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlsplit

import httpx

from .core import (
    CAPTURE_COURSES,
    GetClient,
    MirrorError,
    checked_path,
    course_id,
    encoded,
    now,
    private_write,
    read_json,
    require_valid,
    sha,
)

MAX_FILE_BYTES = 100 * 1024 * 1024
MAX_TOTAL_BYTES = 250 * 1024 * 1024


def _redirect_allowed(
    url: str,
    file_id: str,
    *,
    first_storage_seen: bool = False,
    gateway_seen: bool = False,
) -> bool:
    parsed = urlsplit(url)
    if (
        parsed.scheme != "https"
        or parsed.username
        or parsed.password
        or parsed.fragment
    ):
        return False
    if parsed.port not in (None, 443):
        return False
    host = parsed.hostname or ""
    if host == "fcps.instructure.com":
        return parsed.path == f"/files/{file_id}/download"
    # Exact FCPS storage account/cluster observed in its authenticated response.
    # Bind the hostname to the selected file; never admit a domain wildcard.
    return (
        host == f"a5990-{file_id}.cluster33.canvas-user-content.com"
        or (first_storage_seen and host == "inst-fs-iad-prod.inscloudgate.net")
        or (
            first_storage_seen
            and gateway_seen
            and host == "cdn.inst-fs-iad-prod.inscloudgate.net"
        )
    )


async def _download(
    client: GetClient,
    external: httpx.AsyncClient,
    metadata: dict[str, Any],
    target: Path,
) -> dict[str, Any]:
    identity = course_id(metadata["id"])
    expected = metadata.get("size")
    if (
        not isinstance(expected, int)
        or isinstance(expected, bool)
        or not 0 <= expected <= MAX_FILE_BYTES
    ):
        raise MirrorError("FILE_SIZE_BOUND_REQUIRED")
    url = metadata.get("url", "")
    parsed = urlsplit(url)
    if (
        parsed.scheme != "https"
        or parsed.netloc != "fcps.instructure.com"
        or parsed.path != f"/files/{identity}/download"
        or parsed.fragment
    ):
        raise MirrorError("FILE_SOURCE_URL_NOT_ALLOWED")
    visited: set[str] = set()
    partial = target.with_suffix(".part")
    try:
        for _ in range(6):
            first_storage_seen = any(
                urlsplit(previous).hostname
                == f"a5990-{identity}.cluster33.canvas-user-content.com"
                for previous in visited
            )
            if (
                not _redirect_allowed(
                    url,
                    identity,
                    first_storage_seen=first_storage_seen,
                    gateway_seen=any(
                        urlsplit(previous).hostname
                        == "inst-fs-iad-prod.inscloudgate.net"
                        for previous in visited
                    ),
                )
                or url in visited
            ):
                raise MirrorError("FILE_REDIRECT_NOT_ALLOWED")
            visited.add(url)
            requester = (
                client.http
                if urlsplit(url).hostname == "fcps.instructure.com"
                else external
            )
            client.requests += 1
            async with requester.stream("GET", url, follow_redirects=False) as response:
                if response.status_code in (301, 302, 303, 307, 308):
                    location = response.headers.get("Location")
                    if not location:
                        raise MirrorError("FILE_REDIRECT_MISSING")
                    url = urljoin(url, location)
                    continue
                if response.status_code != 200:
                    raise MirrorError(f"FILE_HTTP_{response.status_code}")
                count = 0
                digest = hashlib.sha256()
                fd = os.open(partial, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                with os.fdopen(fd, "wb") as stream:
                    async for chunk in response.aiter_bytes(8192):
                        count += len(chunk)
                        if count > expected or count > MAX_FILE_BYTES:
                            raise MirrorError("FILE_SIZE_MISMATCH")
                        digest.update(chunk)
                        stream.write(chunk)
                    stream.flush()
                    os.fsync(stream.fileno())
                if count != expected:
                    raise MirrorError("FILE_SIZE_MISMATCH")
                partial.replace(target)
                return {
                    "size": count,
                    "sha256": digest.hexdigest(),
                    "etag": response.headers.get("ETag"),
                    "downloaded_at": now(),
                    "redirects": len(visited) - 1,
                }
        raise MirrorError("FILE_REDIRECT_LIMIT")
    except httpx.HTTPError as exc:
        raise MirrorError("FILE_NETWORK_READ_FAILED") from exc
    finally:
        partial.unlink(missing_ok=True)


async def download_files(
    snapshot: Path,
    destination: Path,
    client: GetClient,
    *,
    transport: Any = None,
) -> dict[str, Any]:
    """Capture exactly the files in a verified course inventory; never follow HTML."""
    require_valid(snapshot)
    source = read_json(snapshot / "manifest.json")
    if any(label not in CAPTURE_COURSES for label in source["courses"]):
        raise MirrorError("INVALID_COURSE_SCOPE")
    inventory = [
        (label, file)
        for label in sorted(source["courses"])
        for file in read_json(snapshot / label / "objects/files.json")
    ]
    if any(
        not isinstance(file.get("size"), int)
        or isinstance(file.get("size"), bool)
        or not 0 <= file["size"] <= MAX_FILE_BYTES
        for _, file in inventory
    ):
        raise MirrorError("FILE_SIZE_BOUND_REQUIRED")
    expected_bytes = sum(file["size"] for _, file in inventory)
    if expected_bytes > MAX_TOTAL_BYTES:
        raise MirrorError("LARGE_FILE_BATCH_REVIEW_REQUIRED")
    if destination.exists() or destination.is_symlink():
        raise MirrorError("DESTINATION_EXISTS")
    destination.mkdir(parents=True, mode=0o700)
    manifest: dict[str, Any] = {
        "schema_version": 1,
        "kind": "canvas_file_assets",
        "status": "INCOMPLETE",
        "started_at": now(),
        "source_snapshot": snapshot.name,
        "source_manifest_sha256": sha((snapshot / "manifest.json").read_bytes()),
        "courses": source["courses"],
        "expected_count": len(inventory),
        "expected_bytes": expected_bytes,
        "canvas_writes": 0,
        "files": [],
        "scope": "Canvas course Files only; external/LTI/media resources remain separate",
    }

    def checkpoint() -> None:
        manifest["request_count"] = client.requests
        private_write(destination / "assets-manifest.json", manifest, replace=True)

    checkpoint()
    try:
        async with httpx.AsyncClient(
            timeout=30, follow_redirects=False, transport=transport
        ) as external:
            for label, metadata in inventory:
                identity = course_id(metadata["id"])
                relative = f"{label}/files/{identity}/content.bin"
                target = checked_path(destination, relative)
                target.parent.mkdir(parents=True, mode=0o700)
                entry = {
                    "course": label,
                    "course_id": CAPTURE_COURSES[label],
                    "id": identity,
                    "status": "INCOMPLETE",
                    "path": relative,
                    "metadata_path": f"{label}/files/{identity}/metadata.json",
                    "metadata_sha256": sha(encoded(metadata)),
                }
                manifest["files"].append(entry)
                checkpoint()
                private_write(destination / entry["metadata_path"], metadata)
                entry.update(await _download(client, external, metadata, target))
                entry["status"] = "COMPLETE"
                checkpoint()
        manifest.update(status="COMPLETE", finished_at=now())
        checkpoint()
    except BaseException as exc:
        manifest.update(
            status="INCOMPLETE",
            finished_at=now(),
            error=str(exc) if isinstance(exc, MirrorError) else type(exc).__name__,
        )
        checkpoint()
        raise
    result = verify_assets(destination, snapshot)
    if not result["ok"]:
        raise MirrorError("ASSET_VERIFICATION_FAILED")
    return {
        "status": manifest["status"],
        "destination": str(destination),
        "files": len(inventory),
        "bytes": expected_bytes,
        "requests": client.requests,
        "canvas_writes": 0,
        "verification": result,
    }


def verify_assets(destination: Path, snapshot: Path) -> dict[str, Any]:
    """Check bytes against a separately pinned verified source inventory, offline."""
    require_valid(snapshot)
    source = read_json(snapshot / "manifest.json")
    expected = {
        (label, str(file["id"])): file
        for label in source["courses"]
        for file in read_json(snapshot / label / "objects/files.json")
    }
    manifest = read_json(destination / "assets-manifest.json")
    errors = set()
    if (
        manifest.get("source_manifest_sha256")
        != sha((snapshot / "manifest.json").read_bytes())
        or manifest.get("source_snapshot") != snapshot.name
        or manifest.get("courses") != source["courses"]
        or manifest.get("expected_count") != len(expected)
        or manifest.get("expected_bytes")
        != sum(file["size"] for file in expected.values())
    ):
        errors.add("ASSET_SOURCE_INVENTORY_MISMATCH")
    if (
        manifest.get("schema_version") != 1
        or manifest.get("kind") != "canvas_file_assets"
        or manifest.get("status") != "COMPLETE"
        or manifest.get("canvas_writes") != 0
    ):
        errors.add("ASSET_MANIFEST_INCOMPLETE")
    if len(manifest.get("files", [])) != manifest.get("expected_count"):
        errors.add("ASSET_COUNT_MISMATCH")
    identities = set()
    total = 0
    for entry in manifest.get("files", []):
        identity = (entry.get("course"), entry.get("id"))
        if identity in identities:
            errors.add("DUPLICATE_ASSET_IDENTITY")
        identities.add(identity)
        baseline = expected.get(identity)
        if baseline is None or entry.get("metadata_sha256") != sha(encoded(baseline)):
            errors.add("ASSET_SOURCE_METADATA_MISMATCH")
        if (
            entry.get("path") != f"{identity[0]}/files/{identity[1]}/content.bin"
            or entry.get("metadata_path")
            != f"{identity[0]}/files/{identity[1]}/metadata.json"
        ):
            errors.add("ASSET_SOURCE_PATH_MISMATCH")
        try:
            data = checked_path(destination, entry["path"]).read_bytes()
            metadata = checked_path(destination, entry["metadata_path"]).read_bytes()
            value = read_json(checked_path(destination, entry["metadata_path"]))
            if (
                entry.get("status") != "COMPLETE"
                or sha(data) != entry.get("sha256")
                or len(data) != entry.get("size")
            ):
                errors.add("ASSET_HASH_OR_SIZE_MISMATCH")
            if (
                sha(metadata) != entry.get("metadata_sha256")
                or str(value.get("id")) != entry.get("id")
                or value.get("size") != len(data)
            ):
                errors.add("ASSET_METADATA_MISMATCH")
            if CAPTURE_COURSES.get(entry.get("course")) != entry.get(
                "course_id"
            ) or manifest.get("courses", {}).get(entry.get("course")) != entry.get(
                "course_id"
            ):
                errors.add("ASSET_COURSE_MISMATCH")
            total += len(data)
        except (MirrorError, OSError, KeyError):
            errors.add("ASSET_UNREADABLE")
    if total != manifest.get("expected_bytes"):
        errors.add("ASSET_TOTAL_BYTES_MISMATCH")
    if identities != set(expected):
        errors.add("ASSET_SOURCE_IDENTITY_SET_MISMATCH")
    return {
        "ok": not errors,
        "errors": sorted(errors),
        "checked": len(identities),
        "bytes": total,
        "canvas_writes": 0,
    }
