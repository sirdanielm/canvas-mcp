"""Independent offline asset-planning boundaries; synthetic archives only."""

import builtins
import hashlib
import importlib
import io
import json
import os
import socket
import stat
import subprocess
import sys
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
from test_course_mirror import make_snapshot

from canvas_mcp.mirror import core
from canvas_mcp.mirror.assets import MAX_FILE_BYTES, download_files, verify_assets
from canvas_mcp.mirror.core import GetClient, MirrorError, encoded, read_json, sha

REUSE = "BASELINE_BYTES_REUSE_CANDIDATE"
SECURE_OPEN_AVAILABLE = (
    os.name == "posix"
    and all(hasattr(os, name) for name in ("O_NOFOLLOW", "O_DIRECTORY", "O_NONBLOCK"))
    and os.open in os.supports_dir_fd
    and os.stat in os.supports_dir_fd
    and os.stat in os.supports_follow_symlinks
)
pytestmark = pytest.mark.skipif(
    not SECURE_OPEN_AVAILABLE,
    reason="Asset planner input validation requires POSIX secure-open capabilities",
)


def fingerprint(root: Path) -> dict[str, tuple[Any, ...]]:
    """Hash fixture inputs without following symlinks or loading large files."""
    result = {}
    for path in root.rglob("*"):
        mode = path.lstat().st_mode
        if stat.S_ISLNK(mode):
            value = ("link", os.readlink(path))
        elif stat.S_ISDIR(mode):
            value = ("directory",)
        else:
            digest = hashlib.sha256()
            with path.open("rb") as stream:
                while block := stream.read(65536):
                    digest.update(block)
            value = ("file", digest.hexdigest(), path.stat().st_size)
        result[str(path.relative_to(root))] = value
    return result


@pytest.fixture
async def archive(tmp_path: Path) -> Any:
    files = [
        {
            "id": 17,
            "size": 5,
            "url": "https://fcps.instructure.com/files/17/download?token=fictional-signed-url",
            "filename": "fictional-first.txt",
            "updated_at": "2026-10-28T12:00:00Z",
        },
        {
            "id": 18,
            "size": 0,
            "url": "https://fcps.instructure.com/files/18/download",
            "filename": "fictional-empty.txt",
            "modified_at": "2026-10-28T12:00:00+00:00",
        },
    ]

    def inventory(path: str, body: Any) -> Any:
        return files if path.endswith("/files") else body

    old = await make_snapshot(tmp_path / "baseline-captures", inventory)
    current = await make_snapshot(tmp_path / "current-captures", inventory)
    assets = tmp_path / "baseline-assets"
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            200, content=b"hello" if request.url.path == "/files/17/download" else b""
        )
    )
    client = GetClient("fictional-token", transport=transport)
    try:
        await download_files(old, assets, client, transport=transport)
    finally:
        await client.close()
    assert verify_assets(assets, old)["ok"]
    return SimpleNamespace(root=tmp_path, old=old, assets=assets, current=current)


@contextmanager
def forbid_side_effects(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """A planner may read inputs; it must not start transport or create output."""
    attempts = []

    def forbidden(*args: Any, **kwargs: Any) -> Any:
        attempts.append("forbidden-side-effect")
        raise AssertionError("Offline plan attempted a forbidden side effect")

    original_open = builtins.open
    original_io_open = io.open
    original_os_open = os.open
    original_import = builtins.__import__
    original_import_module = importlib.import_module

    def read_only_open(original: Callable[..., Any], file: Any, mode: Any = "r", *args: Any, **kwargs: Any) -> Any:
        if isinstance(mode, str) and any(flag in mode for flag in "wax+"):
            forbidden()
        return original(file, mode, *args, **kwargs)

    def read_only_fd(path: Any, flags: int, *args: Any, **kwargs: Any) -> int:
        if flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND):
            forbidden()
        return original_os_open(path, flags, *args, **kwargs)

    def no_credentials(name: str, *args: Any, **kwargs: Any) -> Any:
        if name == "sdm_canvas_launcher" or name == "keyring" or name.startswith("keyring."):
            forbidden()
        return original_import(name, *args, **kwargs)

    def no_credential_module(name: str, package: str | None = None) -> Any:
        if name == "sdm_canvas_launcher" or name == "keyring" or name.startswith("keyring."):
            forbidden()
        return original_import_module(name, package)

    with monkeypatch.context() as guard:
        guard.setattr(sys, "dont_write_bytecode", True)
        guard.setattr(builtins, "open", lambda *a, **kw: read_only_open(original_open, *a, **kw))
        guard.setattr(io, "open", lambda *a, **kw: read_only_open(original_io_open, *a, **kw))
        guard.setattr(os, "open", read_only_fd)
        if original_os_open in os.supports_dir_fd:
            guard.setattr(os, "supports_dir_fd", {*os.supports_dir_fd, read_only_fd})
        guard.setattr(builtins, "__import__", no_credentials)
        guard.setattr(importlib, "import_module", no_credential_module)
        guard.setattr(core, "GetClient", forbidden)
        guard.setattr(httpx, "AsyncClient", forbidden)
        guard.setattr(httpx, "Client", forbidden)
        guard.setattr(socket, "create_connection", forbidden)
        guard.setattr(socket.socket, "connect", forbidden)
        guard.setattr(socket.socket, "connect_ex", forbidden)
        guard.setattr(socket, "getaddrinfo", forbidden)
        guard.setattr(subprocess, "Popen", forbidden)
        guard.setattr(os, "system", forbidden)
        for name in ("mkdir", "unlink", "remove", "rename", "replace", "rmdir", "chmod", "utime"):
            guard.setattr(os, name, forbidden)
        for name in ("mkdir", "unlink", "rename", "replace", "write_text", "write_bytes", "touch"):
            guard.setattr(Path, name, forbidden)
        try:
            yield
        finally:
            assert attempts == []


def plan(archive: Any, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    before = fingerprint(archive.root)
    try:
        with forbid_side_effects(monkeypatch):
            module = importlib.import_module("canvas_mcp.mirror.asset_plan")
            return module.plan_asset_refresh(
                baseline_snapshot=archive.old,
                baseline_assets=archive.assets,
                current_snapshot=archive.current,
            )
    finally:
        assert fingerprint(archive.root) == before


def test_verified_reuse_plan_is_deterministic_offline_and_immutable(
    archive: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    result = plan(archive, monkeypatch)
    assert result == plan(archive, monkeypatch)
    assert result["ok"] is True and result["status"] == "REVIEW_REQUIRED"
    assert result["counts"].get(REUSE) == 2
    assert sum(result["counts"].values()) == 2
    assert [entry["decision"] for entry in result["entries"]] == [REUSE, REUSE]
    assert result["network_requests"] == result["canvas_writes"] == result["google_writes"] == 0
    assert result["download_authorized"] is False
    assert result["source_admission"] == "NOT_ESTABLISHED"
    assert "fictional-signed-url" not in json.dumps(result)


def write_fixture_json(path: Path, value: Any) -> None:
    path.write_bytes(encoded(value))


def repin_inventory(snapshot: Path, files: list[dict[str, Any]]) -> None:
    """Maintain fixture snapshot integrity while changing its declared inventory."""
    write_fixture_json(snapshot / "core/objects/files.json", files)
    manifest = read_json(snapshot / "manifest.json")
    entry = next(item for item in manifest["entries"] if item["key"] == "files")
    entry.update(sha256=sha(encoded(files)), count=len(files))
    write_fixture_json(snapshot / "manifest.json", manifest)


def link_to_equal_fixture(path: Path) -> None:
    target = path.with_name(path.name + ".fictional-copy")
    path.rename(target)
    try:
        path.symlink_to(target.name)
    except (OSError, NotImplementedError):
        pytest.skip("This test requires permission to create a fixture symlink")


@pytest.mark.parametrize(
    "fault",
    [
        "corrupt-content",
        "missing-content",
        "missing-metadata",
        "corrupt-metadata",
        "missing-asset-manifest",
        "corrupt-asset-manifest",
        "oversize-content",
        "content-link",
        "metadata-link",
        "asset-manifest-link",
        "baseline-snapshot-manifest-link",
        "current-inventory-link",
        "assets-root-link",
        "snapshot-root-link",
        "ancestor-link",
    ],
)
def test_one_bad_baseline_source_globally_holds_even_an_independent_good_asset(
    archive: Any, monkeypatch: pytest.MonkeyPatch, fault: str
) -> None:
    content = archive.assets / "core/files/17/content.bin"
    metadata = archive.assets / "core/files/17/metadata.json"
    if fault == "corrupt-content":
        content.write_bytes(b"other")
    elif fault == "missing-content":
        content.unlink()
    elif fault == "missing-metadata":
        metadata.unlink()
    elif fault == "corrupt-metadata":
        metadata.write_bytes(b"not-json")
    elif fault == "missing-asset-manifest":
        (archive.assets / "assets-manifest.json").unlink()
    elif fault == "corrupt-asset-manifest":
        (archive.assets / "assets-manifest.json").write_bytes(b"not-json")
    elif fault == "oversize-content":
        with content.open("r+b") as stream:
            stream.truncate(MAX_FILE_BYTES + 1)
        original_read = Path.read_bytes

        def forbid_whole_oversize_read(path: Path) -> bytes:
            if path == content:
                raise AssertionError("Oversize source must be held before an unbounded read")
            return original_read(path)

        monkeypatch.setattr(Path, "read_bytes", forbid_whole_oversize_read)
    elif fault in {
        "content-link", "metadata-link", "asset-manifest-link",
        "baseline-snapshot-manifest-link", "current-inventory-link",
    }:
        selected = {
            "content-link": content,
            "metadata-link": metadata,
            "asset-manifest-link": archive.assets / "assets-manifest.json",
            "baseline-snapshot-manifest-link": archive.old / "manifest.json",
            "current-inventory-link": archive.current / "core/objects/files.json",
        }[fault]
        link_to_equal_fixture(selected)
    else:
        target = archive.assets if fault == "assets-root-link" else archive.old
        alias_parent = archive.root / "fictional-aliases"
        alias_parent.mkdir()
        alias = alias_parent / target.name
        try:
            alias.symlink_to(
                archive.root if fault == "ancestor-link" else target,
                target_is_directory=True,
            )
        except (OSError, NotImplementedError):
            pytest.skip("This test requires permission to create a fixture symlink")
        if fault == "assets-root-link":
            archive.assets = alias
        elif fault == "snapshot-root-link":
            archive.old = alias
        else:
            archive.old = alias / archive.old.relative_to(archive.root)
    with pytest.raises(MirrorError):
        plan(archive, monkeypatch)


@pytest.mark.parametrize(
    "fault",
    [
        "unsupported-assets-schema",
        "incomplete-after-403",
        "wrong-source-manifest-pin",
        "wrong-source-snapshot",
        "wrong-course-id",
        "duplicate-asset",
        "self-consistent-asset-omission",
        "legacy-baseline-snapshot",
        "unsupported-current-schema",
        "wrong-current-origin",
        "wrong-current-course-map",
        "duplicate-current-identity",
    ],
)
def test_baseline_structure_or_source_binding_failure_never_returns_partial_reuse(
    archive: Any, monkeypatch: pytest.MonkeyPatch, fault: str
) -> None:
    receipt_path = archive.assets / "assets-manifest.json"
    receipt = read_json(receipt_path)
    if fault == "unsupported-assets-schema":
        receipt["schema_version"] = 999
    elif fault == "incomplete-after-403":
        receipt.update(status="INCOMPLETE", error="FILE_HTTP_403")
    elif fault == "wrong-source-manifest-pin":
        receipt["source_manifest_sha256"] = "f" * 64
    elif fault == "wrong-source-snapshot":
        receipt["source_snapshot"] = "different-fictional-capture"
    elif fault == "wrong-course-id":
        receipt["files"][0]["course_id"] = "999"
    elif fault == "duplicate-asset":
        receipt["files"] = [receipt["files"][0], receipt["files"][0]]
    elif fault == "self-consistent-asset-omission":
        receipt.update(files=[receipt["files"][1]], expected_count=1, expected_bytes=0)
    elif fault == "legacy-baseline-snapshot":
        manifest_path = archive.old / "manifest.json"
        manifest = read_json(manifest_path)
        manifest["endpoints"] = manifest.pop("entries")
        write_fixture_json(manifest_path, manifest)
        receipt["source_manifest_sha256"] = sha(manifest_path.read_bytes())
    elif fault == "duplicate-current-identity":
        files = read_json(archive.current / "core/objects/files.json")
        repin_inventory(archive.current, [files[0], files[0]])
    else:
        manifest_path = archive.current / "manifest.json"
        manifest = read_json(manifest_path)
        if fault == "unsupported-current-schema":
            manifest["schema_version"] = 999
        elif fault == "wrong-current-origin":
            manifest["origin"] = "https://wrong-fictional-origin.example"
        else:
            manifest["courses"] = {"core": "999"}
        write_fixture_json(manifest_path, manifest)
    write_fixture_json(receipt_path, receipt)
    with pytest.raises(MirrorError):
        plan(archive, monkeypatch)


def test_boolean_zero_size_cannot_pass_as_a_verified_empty_file(
    archive: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    for snapshot in (archive.old, archive.current):
        files = read_json(snapshot / "core/objects/files.json")
        files[1]["size"] = False
        repin_inventory(snapshot, files)
    metadata_path = archive.assets / "core/files/18/metadata.json"
    metadata = read_json(metadata_path)
    metadata["size"] = False
    write_fixture_json(metadata_path, metadata)
    receipt_path = archive.assets / "assets-manifest.json"
    receipt = read_json(receipt_path)
    receipt["source_manifest_sha256"] = sha((archive.old / "manifest.json").read_bytes())
    receipt["files"][1].update(size=False, metadata_sha256=sha(metadata_path.read_bytes()))
    write_fixture_json(receipt_path, receipt)
    # Re-pin every binding so only the strict scalar contract prevents treating
    # False as the size of this valid zero-byte file (False == 0 in Python).
    with pytest.raises(MirrorError):
        plan(archive, monkeypatch)


def test_valid_planner_does_not_reread_inputs_through_unbounded_path_helpers(
    archive: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A size preflight cannot bound a later whole-file read after replacement."""
    unbounded_reads = []
    original_bytes, original_text = Path.read_bytes, Path.read_text

    def checked_bytes(path: Path) -> bytes:
        if path.is_relative_to(archive.root):
            unbounded_reads.append("whole-input-bytes")
            raise AssertionError("Input bytes require a bounded descriptor read")
        return original_bytes(path)

    def checked_text(path: Path, *args: Any, **kwargs: Any) -> str:
        if path.is_relative_to(archive.root):
            unbounded_reads.append("whole-input-text")
            raise AssertionError("Input JSON requires a bounded descriptor read")
        return original_text(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_bytes", checked_bytes)
    monkeypatch.setattr(Path, "read_text", checked_text)
    result = plan(archive, monkeypatch)
    assert unbounded_reads == []
    assert result["counts"].get(REUSE) == 2


def test_nested_overflow_json_number_is_invalid_not_ordinary_metadata_drift(
    archive: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    inventory_path = archive.current / "core/objects/files.json"
    raw = inventory_path.read_bytes().replace(
        b'"filename":', b'"extra": [{"nested": 1e999}], "filename":', 1
    )
    inventory_path.write_bytes(raw)
    manifest_path = archive.current / "manifest.json"
    manifest = read_json(manifest_path)
    next(entry for entry in manifest["entries"] if entry["key"] == "files")["sha256"] = sha(raw)
    write_fixture_json(manifest_path, manifest)
    with pytest.raises(MirrorError):
        plan(archive, monkeypatch)


@pytest.mark.parametrize("header", ["baseline-assets", "baseline-snapshot", "current-snapshot"])
@pytest.mark.parametrize("error", ["FILE_HTTP_403", None])
def test_complete_marker_never_overrides_a_retained_error_header(
    archive: Any, monkeypatch: pytest.MonkeyPatch, header: str, error: str | None
) -> None:
    path = {
        "baseline-assets": archive.assets / "assets-manifest.json",
        "baseline-snapshot": archive.old / "manifest.json",
        "current-snapshot": archive.current / "manifest.json",
    }[header]
    manifest = read_json(path)
    assert manifest["status"] == "COMPLETE"
    manifest["error"] = error
    write_fixture_json(path, manifest)
    if header == "baseline-snapshot":
        receipt_path = archive.assets / "assets-manifest.json"
        receipt = read_json(receipt_path)
        receipt["source_manifest_sha256"] = sha(path.read_bytes())
        write_fixture_json(receipt_path, receipt)
    with pytest.raises(MirrorError):
        plan(archive, monkeypatch)


def test_ancestor_swap_after_symlink_check_never_opens_outside_content(
    archive: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An eventual hash hold cannot undo an unauthorized outside-file read."""
    module = importlib.import_module("canvas_mcp.mirror.asset_plan")
    content = archive.assets / "core/files/17/content.bin"
    approved_parent = content.parent
    retained_parent = approved_parent.with_name("retained-approved-parent")
    outside_parent = archive.root / "fictional-outside-directory"
    outside_parent.mkdir()
    outside_content = outside_parent / content.name
    outside_content.write_bytes(b"other")
    outside_identity = outside_content.stat()
    baseline = fingerprint(archive.root)
    original_check = module._no_symlinks
    original_open, original_rename = os.open, os.rename
    original_symlink, original_unlink = os.symlink, os.unlink
    swapped = False
    outside_opens = []

    def swap_after_approved_check(path: Path) -> Path:
        nonlocal swapped
        checked = original_check(path)
        if checked == content and not swapped:
            # Only this explicitly modeled fixture race bypasses the ordinary
            # no-write traps. Restore it before comparing the complete inputs.
            original_rename(approved_parent, retained_parent)
            original_symlink(outside_parent, approved_parent, target_is_directory=True)
            swapped = True
        return checked

    def observe_open(path: Any, flags: int, *args: Any, **kwargs: Any) -> int:
        descriptor = original_open(path, flags, *args, **kwargs)
        opened = os.fstat(descriptor)
        if (opened.st_dev, opened.st_ino) == (outside_identity.st_dev, outside_identity.st_ino):
            outside_opens.append("outside-content-opened")
        return descriptor

    monkeypatch.setattr(module, "_no_symlinks", swap_after_approved_check)
    monkeypatch.setattr(os, "open", observe_open)
    if original_open in os.supports_dir_fd:
        monkeypatch.setattr(os, "supports_dir_fd", {*os.supports_dir_fd, observe_open})
    try:
        with forbid_side_effects(monkeypatch):
            with pytest.raises(MirrorError):
                module.plan_asset_refresh(
                    baseline_snapshot=archive.old,
                    baseline_assets=archive.assets,
                    current_snapshot=archive.current,
                )
    finally:
        if swapped:
            original_unlink(approved_parent)
            original_rename(retained_parent, approved_parent)
        assert fingerprint(archive.root) == baseline
    assert swapped, "The test must reach the post-check/pre-open race boundary"
    assert outside_opens == [], "A later hold must not conceal an outside-content open"
