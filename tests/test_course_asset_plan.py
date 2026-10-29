"""Fictional complete captures for the offline asset decision layer."""

from __future__ import annotations

import builtins
import copy
import importlib.util
import json
import os
import sys
from pathlib import Path
from typing import Any

import httpx
import pytest

from canvas_mcp.mirror.core import CAPTURE_COURSES, ORIGIN, SPECS, encoded, sha


def file_metadata(identity: int = 17) -> dict[str, Any]:
    return {
        "id": identity,
        "size": 5,
        "content-type": "application/pdf",
        "updated_at": "2026-10-25T12:00:00+00:00",
        "modified_at": "2026-10-25T11:00:00+00:00",
        "url": f"https://fcps.instructure.com/files/{identity}/download?fictional=1",
        "display_name": "Fictional teaching file",
    }


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    path.write_bytes(encoded(value))
    os.chmod(path, 0o600)


def rewrite_snapshot_files(snapshot: Path, files: list[dict[str, Any]]) -> None:
    path = snapshot / "core/objects/files.json"
    write_json(path, files)
    manifest_path = snapshot / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    entry = next(item for item in manifest["entries"] if item["key"] == "files")
    entry.update(count=len(files), sha256=sha(path.read_bytes()))
    write_json(manifest_path, manifest)


def make_plan_inputs(
    tmp_path: Path,
    old_files: list[dict[str, Any]] | None = None,
    new_files: list[dict[str, Any]] | None = None,
) -> tuple[Path, Path, Path]:
    old_files = copy.deepcopy([file_metadata()] if old_files is None else old_files)
    new_files = copy.deepcopy(old_files if new_files is None else new_files)

    def snapshot(name: str, files: list[dict[str, Any]], day: int) -> Path:
        root = tmp_path / name
        root.mkdir(mode=0o700)
        entries = []
        for key, _, many in (("course", "", False), *SPECS):
            body: Any = [] if many else {}
            if key == "course":
                body = {
                    "id": int(CAPTURE_COURSES["core"]),
                    "workflow_state": "available",
                }
            elif key == "files":
                body = files
            relative = f"core/objects/{key}.json"
            write_json(root / relative, body)
            entries.append(
                {
                    "course": "core",
                    "key": key,
                    "path": relative,
                    "method": "GET",
                    "status": "COMPLETE",
                    "sha256": sha(encoded(body)),
                    "count": len(body) if many else 1,
                }
            )
        write_json(
            root / "manifest.json",
            {
                "schema_version": 1,
                "kind": "content_mirror",
                "id": name,
                "origin": ORIGIN,
                "courses": {"core": CAPTURE_COURSES["core"]},
                "status": "COMPLETE",
                "canvas_writes": 0,
                "entries": entries,
                "started_at": f"2026-10-{day:02}T12:00:00+00:00",
                "finished_at": f"2026-10-{day:02}T12:01:00+00:00",
            },
        )
        return root

    old = snapshot("old-snapshot", old_files, 25)
    current = snapshot("current-snapshot", new_files, 26)
    assets = tmp_path / "baseline-assets"
    assets.mkdir(mode=0o700)
    records = []
    for metadata in old_files:
        identity = str(metadata["id"])
        relative = f"core/files/{identity}/content.bin"
        content = assets / relative
        content.parent.mkdir(parents=True, mode=0o700)
        content.write_bytes(b"hello")
        os.chmod(content, 0o600)
        metadata_path = f"core/files/{identity}/metadata.json"
        write_json(assets / metadata_path, metadata)
        records.append(
            {
                "course": "core",
                "course_id": CAPTURE_COURSES["core"],
                "id": identity,
                "status": "COMPLETE",
                "path": relative,
                "metadata_path": metadata_path,
                "metadata_sha256": sha(encoded(metadata)),
                "size": 5,
                "sha256": sha(b"hello"),
                "downloaded_at": "2026-10-25T12:02:00+00:00",
            }
        )
    write_json(
        assets / "assets-manifest.json",
        {
            "schema_version": 1,
            "kind": "canvas_file_assets",
            "status": "COMPLETE",
            "source_snapshot": old.name,
            "source_manifest_sha256": sha((old / "manifest.json").read_bytes()),
            "courses": {"core": CAPTURE_COURSES["core"]},
            "expected_count": len(records),
            "expected_bytes": 5 * len(records),
            "canvas_writes": 0,
            "files": records,
        },
    )
    return old, assets, current


def plan(inputs: tuple[Path, Path, Path]) -> dict[str, Any]:
    from canvas_mcp.mirror.asset_plan import plan_asset_refresh

    old, assets, current = inputs
    return plan_asset_refresh(
        baseline_snapshot=old, baseline_assets=assets, current_snapshot=current
    )


def test_cli_plan_is_private_aggregate_and_offline(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    inputs = make_plan_inputs(tmp_path)
    output = tmp_path / "reports" / "new-plan.json"
    script = Path(__file__).parents[1] / "scripts/course_mirror.py"
    spec = importlib.util.spec_from_file_location("fictional_course_plan_cli", script)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    original_import = builtins.__import__

    def guarded_import(name: str, *args: Any, **kwargs: Any) -> Any:
        if name == "sdm_canvas_launcher" or name.startswith("keyring"):
            pytest.fail("Offline planning must not import a credential helper")
        return original_import(name, *args, **kwargs)

    def forbidden(*args: Any, **kwargs: Any) -> Any:
        pytest.fail("Offline planning must not construct a transport")

    monkeypatch.setattr(builtins, "__import__", guarded_import)
    monkeypatch.setattr(httpx, "AsyncClient", forbidden)
    monkeypatch.setattr(httpx, "Client", forbidden)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            str(script),
            "assets-plan",
            *(str(p) for p in inputs),
            "--output",
            str(output),
        ],
    )
    assert module.main() == 0
    stdout = capsys.readouterr().out
    summary = json.loads(stdout)
    saved = json.loads(output.read_text(encoding="utf-8"))
    assert "entries" not in summary and "input_manifest_sha256" not in summary
    assert summary["counts"]["BASELINE_BYTES_REUSE_CANDIDATE"] == 1
    assert summary["bytes"] == {
        "baseline_verified": 5,
        "current_inventory": 5,
        "reuse_candidate": 5,
    }
    assert saved["entries"][0]["baseline_sha256"] == sha(b"hello")
    assert "Fictional teaching file" not in output.read_text(encoding="utf-8")
    assert "https://" not in output.read_text(encoding="utf-8")
    assert output.stat().st_mode & 0o077 == 0
    assert summary["network_requests"] == 0 and summary["download_authorized"] is False


def test_exact_metadata_and_verified_bytes_are_only_a_reuse_candidate(
    tmp_path: Path,
) -> None:
    inputs = make_plan_inputs(tmp_path)
    before = {
        str(p): p.read_bytes()
        for root in inputs
        for p in root.rglob("*")
        if p.is_file()
    }
    result = plan(inputs)
    assert result["ok"] is True and result["status"] == "REVIEW_REQUIRED"
    assert result["bytes"] == {
        "baseline_verified": 5,
        "current_inventory": 5,
        "reuse_candidate": 5,
    }
    assert result["entries"][0]["decision"] == "BASELINE_BYTES_REUSE_CANDIDATE"
    assert result["entries"][0]["baseline_downloaded_at"] == "2026-10-25T12:02:00+00:00"
    assert (
        result["capture_intervals"]["current"]["finished_at"]
        == "2026-10-26T12:01:00+00:00"
    )
    assert result == plan(inputs)
    assert before == {
        str(p): p.read_bytes()
        for root in inputs
        for p in root.rglob("*")
        if p.is_file()
    }
    assert result["source_admission"] == "NOT_ESTABLISHED"
    assert result["download_authorized"] is False


@pytest.mark.parametrize(
    "field,value",
    [
        ("updated_at", "2026-10-26T12:00:00+00:00"),
        ("url", "https://fcps.instructure.com/files/17/download?fictional=2"),
        ("display_name", "Renamed fictional material"),
    ],
)
def test_any_metadata_drift_requires_review(
    tmp_path: Path, field: str, value: str
) -> None:
    changed = dict(file_metadata(), **{field: value})
    result = plan(make_plan_inputs(tmp_path, new_files=[changed]))
    assert result["entries"][0]["decision"] == "HOLD_METADATA_CHANGED"
    assert result["counts"]["BASELINE_BYTES_REUSE_CANDIDATE"] == 0


@pytest.mark.parametrize(
    "revision",
    [
        {},
        {"updated_at": "naive"},
        {"updated_at": "2026-10-25T12:00:00"},
        {"modified_at": None},
    ],
)
def test_revision_evidence_must_be_present_and_aware(
    tmp_path: Path, revision: dict[str, Any]
) -> None:
    metadata = {
        k: v
        for k, v in file_metadata().items()
        if k not in {"updated_at", "modified_at"}
    }
    metadata.update(revision)
    result = plan(make_plan_inputs(tmp_path, old_files=[metadata]))
    assert result["entries"][0]["decision"] == "HOLD_VERSION_UNVERIFIED"


def test_new_and_absent_identities_create_no_download_or_deletion_authority(
    tmp_path: Path,
) -> None:
    result = plan(make_plan_inputs(tmp_path, new_files=[file_metadata(18)]))
    assert [row["decision"] for row in result["entries"]] == [
        "OBSERVED_ABSENCE_NO_DELETE",
        "NEW_IDENTITY_REVIEW_REQUIRED",
    ]
    assert result["download_authorized"] is False


@pytest.mark.parametrize("placement", ["existing", "input", "symlink-parent"])
def test_cli_refuses_unsafe_output_without_overwrite(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    placement: str,
) -> None:
    inputs = make_plan_inputs(tmp_path)
    output = tmp_path / "output.json"
    if placement == "existing":
        output.write_text("preserve", encoding="utf-8")
    elif placement == "input":
        output = inputs[2] / "new-plan.json"
    else:
        parent = tmp_path / "target"
        parent.mkdir()
        (tmp_path / "link").symlink_to(parent, target_is_directory=True)
        output = tmp_path / "link" / "new-plan.json"
    script = Path(__file__).parents[1] / "scripts/course_mirror.py"
    spec = importlib.util.spec_from_file_location("fictional_output_cli", script)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            str(script),
            "assets-plan",
            *(str(p) for p in inputs),
            "--output",
            str(output),
        ],
    )
    assert module.main() != 0
    capsys.readouterr()
    if placement == "existing":
        assert output.read_text(encoding="utf-8") == "preserve"
    else:
        assert not output.exists()
