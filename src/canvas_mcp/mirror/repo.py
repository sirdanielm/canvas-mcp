"""Offline editable derivatives and exact draft diffs; never an LMS writer."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from .core import (
    COURSES,
    ORIGIN,
    MirrorError,
    checked_path,
    encoded,
    now,
    private_write,
    private_write_bytes,
    read_json,
    require_valid,
    sha,
    snapshot_objects,
)

SCHEMA = 1
HTML_FIELDS = {
    "course": ("syllabus_body",),
    "assignments": ("description",),
    "pages_detail": ("body",),
    "announcements": ("message",),
}
# These are draftable editorial fields, not permission or a supported publisher.
DRAFT_FIELDS = {
    "course": {"syllabus_body"},
    "assignments": {"description", "name"},
    "pages_detail": {"body", "title"},
    "announcements": {"message", "title"},
}
IDENTITY_FIELDS = {"id", "page_id", "course_id", "assignment_id"}


def _folder(identity: str) -> str:
    if re.fullmatch(r"[A-Za-z0-9_-]+", identity):
        return identity
    return "identity-" + sha(identity.encode())


def _index(snapshot: Path) -> list[dict[str, Any]]:
    result = []
    for (label, endpoint, identity), value in sorted(
        snapshot_objects(snapshot).items()
    ):
        base = f"working/{label}/{endpoint}/{_folder(identity)}"
        html = {
            field: f"{base}/{field}.html"
            for field in HTML_FIELDS.get(endpoint.split("/")[0], ())
            if isinstance(value.get(field), str)
        }
        result.append(
            {
                "origin": ORIGIN,
                "course": label,
                "course_id": COURSES[label],
                "endpoint": endpoint,
                "object_id": identity,
                "baseline_object_sha256": sha(encoded(value)),
                "working_json": f"{base}/object.json",
                "html": html,
            }
        )
    return result


def materialize(snapshot: Path, destination: Path) -> dict[str, Any]:
    """Create a private partial workspace, preserving all captured bytes exactly."""
    require_valid(snapshot)
    manifest = read_json(snapshot / "manifest.json")
    if manifest.get("kind") != "content_mirror" or "entries" not in manifest:
        raise MirrorError("UNSUPPORTED_SNAPSHOT_SCHEMA")
    if destination.exists() or destination.is_symlink():
        raise MirrorError("DESTINATION_EXISTS")
    destination.mkdir(parents=True, mode=0o700)
    index = _index(snapshot)
    receipt: dict[str, Any] = {
        "schema_version": SCHEMA,
        "kind": "editable_course_repo",
        "status": "INCOMPLETE",
        "created_at": now(),
        "origin": ORIGIN,
        "source_snapshot": snapshot.name,
        "source_manifest_sha256": sha((snapshot / "manifest.json").read_bytes()),
        "courses": manifest["courses"],
        "completeness": "PARTIAL_CONTENT_ONLY",
        "exclusions": manifest.get("exclusions", []),
        "canvas_writes": 0,
        "objects": index,
    }
    private_write(destination / "repo-manifest.json", receipt)
    try:
        paths = ["manifest.json", *(entry["path"] for entry in manifest["entries"])]
        for relative in paths:
            source = checked_path(snapshot, relative)
            target = checked_path(destination, "source/" + relative)
            target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            private_write_bytes(target, source.read_bytes())
        copied = destination / "source"
        require_valid(copied)
        if (
            sha((copied / "manifest.json").read_bytes())
            != receipt["source_manifest_sha256"]
        ):
            raise MirrorError("SOURCE_MANIFEST_CHANGED")
        objects = snapshot_objects(copied)
        if _index(copied) != index:
            raise MirrorError("SOURCE_CHANGED_DURING_COPY")
        for entry in index:
            value = objects[(entry["course"], entry["endpoint"], entry["object_id"])]
            private_write(destination / entry["working_json"], value)
            for field, relative in entry["html"].items():
                private_write_bytes(destination / relative, value[field].encode())
        private_write_bytes(destination / ".gitignore", b"*\n")
        private_write_bytes(
            destination / "README.txt",
            (
                b"Private editable course workspace, PARTIAL_CONTENT_ONLY.\n"
                b"source/ preserves the captured JSON; working/ contains editable derivatives.\n"
                b"No file bytes, New Quizzes, banks, rosters, grades, submissions, or histories are included.\n"
                b"HTML is untrusted source data: do not execute it or open it in an unrestricted browser.\n"
                b"repo-diff produces drafts only. No apply/push command exists.\n"
                b"Teacher review, exact authorization, fresh GET and readback are required for any future publisher.\n"
                b"Do not commit private data to Git. This command does not initialize Git.\n"
            ),
        )
        receipt["status"] = "LOCAL_ONLY_NOT_AUTHORIZED"
        receipt["finished_at"] = now()
        private_write(destination / "repo-manifest.json", receipt, replace=True)
    except BaseException:
        # The durable INCOMPLETE receipt prevents a failed copy being used as a baseline.
        raise
    return {
        "status": receipt["status"],
        "destination": str(destination),
        "objects": len(index),
        "html_files": sum(len(entry["html"]) for entry in index),
        "completeness": receipt["completeness"],
        "source_manifest_sha256": receipt["source_manifest_sha256"],
        "canvas_writes": 0,
    }


def repo_diff(repository: Path) -> dict[str, Any]:
    """Draft object-specific changes, retaining missing/unknown/identity conflicts."""
    receipt = read_json(checked_path(repository, "repo-manifest.json"))
    if (
        receipt.get("schema_version") != SCHEMA
        or receipt.get("kind") != "editable_course_repo"
        or receipt.get("status") != "LOCAL_ONLY_NOT_AUTHORIZED"
        or receipt.get("origin") != ORIGIN
        or receipt.get("canvas_writes") != 0
    ):
        raise MirrorError("REPO_NOT_COMPLETE_OR_INVALID")
    source = checked_path(repository, "source")
    require_valid(source)
    if sha((source / "manifest.json").read_bytes()) != receipt.get(
        "source_manifest_sha256"
    ):
        raise MirrorError("SOURCE_MANIFEST_CHANGED")
    expected = _index(source)
    if (
        expected != receipt.get("objects")
        or receipt.get("courses") != read_json(source / "manifest.json")["courses"]
    ):
        raise MirrorError("REPO_INDEX_MISMATCH")
    objects = snapshot_objects(source)
    holds: set[str] = set()
    changes = []
    allowed_paths: set[str] = set()
    for entry in expected:
        before = objects[(entry["course"], entry["endpoint"], entry["object_id"])]
        paths = [entry["working_json"], *entry["html"].values()]
        allowed_paths.update(paths)
        resolved = {relative: checked_path(repository, relative) for relative in paths}
        if any(not path.is_file() for path in resolved.values()):
            holds.add("WORKING_FILE_MISSING")
            continue
        proposed = read_json(resolved[entry["working_json"]])
        if not isinstance(proposed, dict):
            holds.add("WORKING_OBJECT_SHAPE_INVALID")
            continue
        proposed = dict(proposed)
        for field in IDENTITY_FIELDS:
            if (field in before) != (field in proposed) or before.get(
                field
            ) != proposed.get(field):
                holds.add("SOURCE_IDENTITY_CHANGED")
        for field, relative in entry["html"].items():
            try:
                html = resolved[relative].read_bytes().decode("utf-8")
            except (OSError, UnicodeError):
                holds.add("WORKING_HTML_UNREADABLE")
                continue
            if html != before[field]:
                if field not in proposed or (
                    proposed[field] != before[field] and proposed[field] != html
                ):
                    holds.add("EDIT_REPRESENTATIONS_CONFLICT")
                else:
                    proposed[field] = html
        fields = sorted(
            key
            for key in before.keys() | proposed.keys()
            if (key in before) != (key in proposed)
            or before.get(key) != proposed.get(key)
        )
        if not fields:
            continue
        draftable = DRAFT_FIELDS.get(entry["endpoint"].split("/")[0], set())
        if not set(fields) <= draftable:
            holds.add("UNSUPPORTED_EDIT_FIELD")
        changes.append(
            {
                **{
                    key: entry[key]
                    for key in (
                        "origin",
                        "course",
                        "course_id",
                        "endpoint",
                        "object_id",
                        "baseline_object_sha256",
                    )
                },
                "fields": fields,
                "before": before,
                "proposed": proposed,
                "proposed_object_sha256": sha(encoded(proposed)),
            }
        )
    for path in (repository / "working").rglob("*"):
        if path.is_symlink():
            checked_path(repository, str(path.relative_to(repository)))
            holds.add("WORKING_SYMLINK_REVIEW_REQUIRED")
        if path.is_file() and str(path.relative_to(repository)) not in allowed_paths:
            holds.add("UNINDEXED_WORKING_FILE")
    return {
        "schema_version": SCHEMA,
        "kind": "course_repo_draft_diff",
        "status": "CONFLICT_REVIEW_REQUIRED" if holds else "DRAFT_NOT_AUTHORIZED",
        "created_at": now(),
        "source_snapshot": receipt["source_snapshot"],
        "source_manifest_sha256": receipt["source_manifest_sha256"],
        "completeness": "PARTIAL_CONTENT_ONLY",
        "changes": changes,
        "holds": sorted(holds),
        "canvas_writes": 0,
        "fresh_get_required": True,
        "teacher_exact_diff_approval_required": True,
        "note": "Offline draft only. No LMS writer is implemented or authorized.",
    }
