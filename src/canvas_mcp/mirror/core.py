"""Immutable captures, deterministic comparisons, and local-only proposals.

This module deliberately has no import from the server's authoring/write tools.
Only the fixed content endpoint allowlist can reach the authenticated transport.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import uuid
from collections import Counter
from datetime import UTC, datetime
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urljoin, urlsplit

import httpx

ORIGIN = "https://fcps.instructure.com"
COURSES = {
    "core": "363308",
    "advanced": "374070",
    "advisory": "375577",  # Retained for verification of earlier snapshots.
    "historical_311463": "311463",
    "historical_311462": "311462",
}
DEFAULT_CAPTURE_SCOPE = ["core", "advanced"]
HISTORICAL_COURSES = {"historical_311463", "historical_311462"}
CAPTURE_COURSES = {key: value for key, value in COURSES.items() if key != "advisory"}
SCHEMA = 1
# Object lists are fetched in full: Canvas does not offer a universal content
# delta feed. Deltas below are deterministic local comparisons of complete reads.
SPECS = (
    ("settings", "/settings", False),
    ("navigation", "/tabs", True),
    ("sections", "/sections", True),
    ("assignments", "/assignments", True),
    ("assignment_groups", "/assignment_groups", True),
    ("modules", "/modules", True),
    ("pages", "/pages", True),
    ("rubrics", "/rubrics", True),
    ("files", "/files", True),
    ("classic_quizzes", "/quizzes", True),
    ("announcements", "/discussion_topics", True),
)
FIXED_SUFFIXES = {"", *(suffix for _, suffix, _ in SPECS)}
DYNAMIC_SUFFIX = re.compile(
    r"/(?:modules/[0-9]+/items|pages/[0-9]+|rubrics/[0-9]+|quizzes/[0-9]+/questions)"
)
SAFE_KEY = re.compile(r"[a-z_]+(?:/[0-9]+)?\Z")
# These vary without an instructional edit. Full original JSON is still retained.
VOLATILE = {
    "updated_at",
    "needs_grading_count",
    "graded_submissions_exist",
    "has_submitted_submissions",
    "locked_for_user",
    "lock_info",
    "lock_explanation",
    "secure_params",
    "submissions_download_url",
    "url",
    "html_url",
}


class MirrorError(Exception):
    """Safe error code: never carries Canvas payloads, URLs, or credentials."""


def course_state_allowed(label: str, state: Any) -> bool:
    """The specifically authorized historical sources may be unpublished/concluded."""
    return state == "available" or (
        label in HISTORICAL_COURSES and state in {"unpublished", "completed"}
    )


def now() -> str:
    return datetime.now(UTC).isoformat()


def encoded(value: Any) -> bytes:
    return (
        json.dumps(value, sort_keys=True, ensure_ascii=False, indent=2) + "\n"
    ).encode()


def sha(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def private_write(path: Path, value: Any, *, replace: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    body = encoded(value)
    if replace:
        temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
        private_write_bytes(temporary, body)
        temporary.replace(path)
    else:
        private_write_bytes(path, body)


def private_write_bytes(path: Path, body: bytes) -> None:
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as stream:
        stream.write(body)
        stream.flush()
        os.fsync(stream.fileno())


def read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError) as exc:
        raise MirrorError("LOCAL_JSON_UNREADABLE") from exc


def course_id(value: Any) -> str:
    text = str(value)
    if not re.fullmatch(r"[0-9]+", text):
        raise MirrorError("INVALID_OBJECT_ID")
    return text


def object_key(item: dict[str, Any]) -> str:
    value = item.get("id", item.get("page_id"))
    if not isinstance(value, (int, str)) or isinstance(value, bool) or not str(value):
        raise MirrorError("OBJECT_ID_MISSING")
    return str(value)


class GetClient:
    """Fixed-origin GET transport, with same-endpoint pagination and bounded retry."""

    def __init__(self, token: str, *, transport: Any = None) -> None:
        self.requests = 0
        self.http = httpx.AsyncClient(
            headers={"Authorization": "Bearer " + token},
            timeout=30,
            follow_redirects=False,
            transport=transport,
        )

    async def close(self) -> None:
        await self.http.aclose()

    async def read(
        self, label: str, suffix: str, many: bool, params: Any = None
    ) -> Any:
        if label not in CAPTURE_COURSES or not (
            suffix in FIXED_SUFFIXES or DYNAMIC_SUFFIX.fullmatch(suffix)
        ):
            raise MirrorError("ENDPOINT_NOT_ALLOWED")
        path = f"/api/v1/courses/{COURSES[label]}{suffix}"
        url = ORIGIN + path
        visited: set[str] = set()
        records: list[dict[str, Any]] = []
        ids: set[str] = set()
        for _ in range(100):
            parsed = urlsplit(url)
            if (parsed.scheme, parsed.netloc, parsed.path) != (
                "https",
                "fcps.instructure.com",
                path,
            ) or parsed.fragment:
                raise MirrorError("PAGINATION_TARGET_CHANGED")
            if url in visited:
                raise MirrorError("PAGINATION_LOOP")
            visited.add(url)
            response = None
            for attempt in range(3):
                self.requests += 1
                try:
                    response = await self.http.get(url, params=params)
                except httpx.HTTPError as exc:
                    raise MirrorError("NETWORK_READ_FAILED") from exc
                if response.status_code not in (429, 502, 503, 504):
                    break
                if attempt < 2:
                    retry = response.headers.get("Retry-After", "")
                    # Long server backoffs become a checkpoint, never an early retry.
                    if retry and (not retry.isdecimal() or int(retry) > 15):
                        raise MirrorError("SERVER_BACKOFF_REQUIRED")
                    await asyncio.sleep(max(2**attempt, int(retry or 0)))
            assert response is not None
            if response.status_code != 200:
                raise MirrorError(f"HTTP_{response.status_code}")
            try:
                body = response.json()
            except ValueError as exc:
                raise MirrorError("INVALID_JSON") from exc
            next_url = response.links.get("next", {}).get("url")
            if not many:
                if not isinstance(body, dict) or next_url:
                    raise MirrorError("OBJECT_SHAPE_INVALID")
                return body
            if not isinstance(body, list) or any(not isinstance(x, dict) for x in body):
                raise MirrorError("COLLECTION_SHAPE_INVALID")
            for item in body:
                key = object_key(item)
                if key in ids:
                    raise MirrorError("DUPLICATE_OBJECT_ID")
                ids.add(key)
            records.extend(body)
            if not next_url:
                return records
            url = urljoin(url, next_url)
            params = None
        raise MirrorError("PAGINATION_LIMIT")


async def capture(root: Path, client: GetClient, labels: list[str]) -> Path:
    if (
        not labels
        or len(set(labels)) != len(labels)
        or any(x not in CAPTURE_COURSES for x in labels)
    ):
        raise MirrorError("INVALID_COURSE_SCOPE")
    snapshot_id = (
        datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:8]
    )
    target = root / snapshot_id
    target.mkdir(parents=True, mode=0o700)
    manifest: dict[str, Any] = {
        "schema_version": SCHEMA,
        "kind": "content_mirror",
        "id": snapshot_id,
        "origin": ORIGIN,
        "courses": {x: COURSES[x] for x in labels},
        "started_at": now(),
        "status": "INCOMPLETE",
        "canvas_writes": 0,
        "entries": [],
        "scope": "Authorized current/historical course content; actual publication states retained",
        "exclusions": [
            "student rosters",
            "grades",
            "submissions",
            "discussion replies",
            "file bytes",
            "Google refresh",
            "New Quizzes",
            "question banks",
        ],
    }

    def checkpoint() -> None:
        manifest["request_count"] = client.requests
        private_write(target / "manifest.json", manifest, replace=True)

    async def collect(
        label: str, key: str, suffix: str, many: bool, params: Any = None
    ) -> Any:
        if not SAFE_KEY.fullmatch(key):
            raise MirrorError("INVALID_CAPTURE_KEY")
        entry: dict[str, Any] = {
            "course": label,
            "key": key,
            "status": "INCOMPLETE",
            "method": "GET",
        }
        manifest["entries"].append(entry)
        checkpoint()
        body = await client.read(label, suffix, many, params)
        relative = f"{label}/objects/{key}.json"
        private_write(target / relative, body)
        entry.update(
            path=relative,
            sha256=sha(encoded(body)),
            count=len(body) if many else 1,
            status="COMPLETE",
            captured_at=now(),
        )
        checkpoint()
        return body

    try:
        checkpoint()
        for label in labels:
            course = await collect(
                label,
                "course",
                "",
                False,
                [("include[]", "syllabus_body"), ("include[]", "term")],
            )
            if str(course.get("id")) != COURSES[label]:
                raise MirrorError("COURSE_IDENTITY_MISMATCH")
            if not course_state_allowed(label, course.get("workflow_state")):
                raise MirrorError("COURSE_NOT_PUBLISHED")
            objects = {}
            for key, suffix, many in SPECS:
                params = [("per_page", "100")] if many else []
                if key == "assignments":
                    params.append(("include[]", "all_dates"))
                if key == "announcements":
                    params.append(("only_announcements", "true"))
                objects[key] = await collect(label, key, suffix, many, params)
            for module in objects["modules"]:
                mid = course_id(module["id"])
                items = await collect(
                    label,
                    f"module_items/{mid}",
                    f"/modules/{mid}/items",
                    True,
                    [("per_page", "100"), ("include[]", "content_details")],
                )
                if len(items) != module.get("items_count"):
                    raise MirrorError("MODULE_ITEM_COUNT_CHANGED")
            for kind, field in (("pages", "page_id"), ("rubrics", "id")):
                for item in objects[kind]:
                    iid = course_id(item[field])
                    detail = await collect(
                        label, f"{kind}_detail/{iid}", f"/{kind}/{iid}", False
                    )
                    if str(detail.get(field)) != iid:
                        raise MirrorError("DETAIL_IDENTITY_MISMATCH")
            for quiz in objects["classic_quizzes"]:
                qid = course_id(quiz["id"])
                await collect(
                    label,
                    f"quiz_questions/{qid}",
                    f"/quizzes/{qid}/questions",
                    True,
                    {"per_page": 100},
                )
        manifest.update(status="COMPLETE", finished_at=now())
        checkpoint()
        report = verify(target)
        if not report["ok"]:
            raise MirrorError("CAPTURE_VERIFICATION_FAILED")
    except BaseException as exc:
        manifest.update(
            status="INCOMPLETE",
            finished_at=now(),
            error=str(exc) if isinstance(exc, MirrorError) else type(exc).__name__,
        )
        checkpoint()
        raise
    return target


def checked_path(root: Path, relative: str) -> Path:
    if not isinstance(relative, str) or Path(relative).is_absolute():
        raise MirrorError("UNSAFE_LOCAL_PATH")
    target = (root / relative).resolve()
    if not target.is_relative_to(root.resolve()) or target == root.resolve():
        raise MirrorError("UNSAFE_LOCAL_PATH")
    return target


def verify(snapshot: Path) -> dict[str, Any]:
    manifest = read_json(snapshot / "manifest.json")
    errors: list[str] = []
    if not isinstance(manifest, dict):
        raise MirrorError("MANIFEST_SHAPE_INVALID")
    legacy = "endpoints" in manifest and "entries" not in manifest
    entries = manifest.get("endpoints" if legacy else "entries", [])
    if not isinstance(entries, list) or not entries:
        return {"ok": False, "errors": ["NO_ENDPOINTS"], "checked": 0}
    if not legacy and (
        manifest.get("schema_version") != SCHEMA
        or manifest.get("kind") != "content_mirror"
        or manifest.get("origin") != ORIGIN
        or manifest.get("status") != "COMPLETE"
        or manifest.get("canvas_writes") != 0
    ):
        errors.append("MANIFEST_NOT_COMPLETE_OR_INVALID")
    seen: set[tuple[str, str]] = set()
    course_labels: set[str] = set()
    for entry in entries:
        label, key = entry.get("course"), entry.get("key")
        if (
            label not in COURSES
            or not isinstance(key, str)
            or not SAFE_KEY.fullmatch(key)
        ):
            errors.append("INVALID_ENDPOINT_IDENTITY")
            continue
        course_labels.add(label)
        identity = (label, key)
        if identity in seen:
            errors.append("DUPLICATE_ENDPOINT")
        seen.add(identity)
        if entry.get("status") != "COMPLETE" or entry.get("method") != "GET":
            errors.append("INCOMPLETE_ENDPOINT")
            continue
        try:
            path = checked_path(snapshot, f"{label}/objects/{key}.json")
            if not legacy and entry.get("path") != f"{label}/objects/{key}.json":
                raise MirrorError("ENDPOINT_PATH_MISMATCH")
            body = path.read_bytes()
            if sha(body) != entry.get("sha256"):
                raise MirrorError("HASH_MISMATCH")
            value = json.loads(body)
            if not isinstance(value, (dict, list)):
                raise MirrorError("SHAPE_INVALID")
            if (len(value) if isinstance(value, list) else 1) != entry.get("count"):
                raise MirrorError("COUNT_MISMATCH")
            if isinstance(value, list):
                if any(not isinstance(x, dict) for x in value):
                    raise MirrorError("SHAPE_INVALID")
                keys = [object_key(x) for x in value]
                if len(set(keys)) != len(keys):
                    raise MirrorError("DUPLICATE_OBJECT_ID")
            if key == "course":
                if (
                    not isinstance(value, dict)
                    or str(value.get("id")) != COURSES[label]
                ):
                    raise MirrorError("COURSE_IDENTITY_MISMATCH")
                if not legacy and not course_state_allowed(
                    label, value.get("workflow_state")
                ):
                    raise MirrorError("COURSE_NOT_PUBLISHED")
        except (OSError, ValueError, MirrorError, AttributeError) as exc:
            errors.append(
                str(exc) if isinstance(exc, MirrorError) else "PAYLOAD_UNREADABLE"
            )
    if not legacy:
        if manifest.get("courses") != {x: COURSES[x] for x in course_labels}:
            errors.append("COURSE_SCOPE_MISMATCH")
        for label in course_labels:
            for key in ["course", *(x[0] for x in SPECS)]:
                if (label, key) not in seen:
                    errors.append("REQUIRED_ENDPOINT_MISSING")
            for base, field, prefix in (
                ("modules", "id", "module_items"),
                ("pages", "page_id", "pages_detail"),
                ("rubrics", "id", "rubrics_detail"),
                ("classic_quizzes", "id", "quiz_questions"),
            ):
                try:
                    for item in read_json(
                        snapshot / label / "objects" / f"{base}.json"
                    ):
                        if (label, f"{prefix}/{course_id(item[field])}") not in seen:
                            errors.append("DETAIL_ENDPOINT_MISSING")
                except (MirrorError, KeyError, TypeError):
                    errors.append("DETAIL_INDEX_INVALID")
    return {
        "ok": not errors,
        "errors": sorted(set(errors)),
        "checked": len(entries),
        "courses": sorted(course_labels),
        "legacy": legacy,
    }


def require_valid(snapshot: Path) -> dict[str, Any]:
    result = verify(snapshot)
    if not result["ok"]:
        raise MirrorError("SNAPSHOT_FAILED_QC")
    return result


def snapshot_objects(snapshot: Path) -> dict[tuple[str, str, str], dict[str, Any]]:
    require_valid(snapshot)
    manifest = read_json(snapshot / "manifest.json")
    result = {}
    for entry in manifest.get("entries", manifest.get("endpoints", [])):
        label, key = entry["course"], entry["key"]
        value = read_json(snapshot / label / "objects" / f"{key}.json")
        for item in value if isinstance(value, list) else [value]:
            identity = object_key(item) if isinstance(value, list) else "object"
            result[(label, key, identity)] = item
    return result


def normalized(value: dict[str, Any]) -> dict[str, Any]:
    # Do not recurse through content: URLs inside HTML/LTI definitions matter.
    return {key: item for key, item in value.items() if key not in VOLATILE}


def diff(before: Path, after: Path) -> dict[str, Any]:
    old, new = snapshot_objects(before), snapshot_objects(after)
    # Compare common endpoint scopes only. A new capture's missing endpoint is
    # never a mass deletion, and a newly added course is marked scope_added.
    old_scopes = {(x[0], x[1]) for x in old}
    new_scopes = {(x[0], x[1]) for x in new}
    for folder, scopes in ((before, old_scopes), (after, new_scopes)):
        manifest = read_json(folder / "manifest.json")
        scopes.update(
            (x["course"], x["key"])
            for x in manifest.get("entries", manifest.get("endpoints", []))
        )
    common = old_scopes & new_scopes
    changes = []
    for key in sorted(old.keys() | new.keys()):
        if key[:2] not in common:
            continue
        a, b = old.get(key), new.get(key)
        fields: list[str]
        if a is None:
            kind, fields = "added", []
        elif b is None:
            kind, fields = "removed_from_snapshot", []
        else:
            aa, bb = normalized(a), normalized(b)
            fields = sorted(k for k in aa.keys() | bb.keys() if aa.get(k) != bb.get(k))
            if not fields:
                continue
            kind = "changed"
        changes.append(
            {
                "course": key[0],
                "kind": key[1],
                "object_id": key[2],
                "change": kind,
                "fields": fields,
            }
        )
    return {
        "schema_version": SCHEMA,
        "before": before.name,
        "after": after.name,
        "changes": changes,
        "counts": dict(Counter(x["change"] for x in changes)),
        "scope_added": sorted([list(x) for x in new_scopes - old_scopes]),
        "scope_absent": sorted([list(x) for x in old_scopes - new_scopes]),
        "note": "Absence is an observation, not proof of deletion; no actions applied.",
    }


def audit(snapshot: Path) -> dict[str, Any]:
    qc = require_valid(snapshot)
    findings = []
    counts = {}
    for label in qc["courses"]:
        base = snapshot / label / "objects"
        assignments = read_json(base / "assignments.json")
        modules = read_json(base / "modules.json")
        by_id = {str(x["id"]): x for x in assignments}
        occurrences: Counter[str] = Counter()
        item_count = 0
        for module in modules:
            items = read_json(base / "module_items" / f"{course_id(module['id'])}.json")
            item_count += len(items)
            if len(items) != module.get("items_count"):
                findings.append(
                    {
                        "course": label,
                        "code": "MODULE_COUNT_MISMATCH",
                        "id": module["id"],
                    }
                )
            for item in items:
                if item.get("type") != "Assignment":
                    continue
                aid = str(item.get("content_id"))
                occurrences[aid] += 1
                if aid not in by_id:
                    findings.append(
                        {
                            "course": label,
                            "code": "ASSIGNMENT_REFERENCE_UNRESOLVED",
                            "id": aid,
                        }
                    )
                elif item.get("published") != by_id[aid].get("published"):
                    findings.append(
                        {"course": label, "code": "PUBLICATION_MISMATCH", "id": aid}
                    )
        for aid, assignment in by_id.items():
            if occurrences[aid] > 1:
                findings.append(
                    {
                        "course": label,
                        "code": "REPEATED_ASSIGNMENT_PLACEMENT",
                        "id": aid,
                    }
                )
            if assignment.get("published") and not occurrences[aid]:
                findings.append(
                    {
                        "course": label,
                        "code": "PUBLISHED_ASSIGNMENT_OUTSIDE_MODULES",
                        "id": aid,
                    }
                )
        counts[label] = {
            "assignments": len(assignments),
            "published_assignments": sum(
                x.get("published") is True for x in assignments
            ),
            "modules": len(modules),
            "module_items": item_count,
            "assignments_with_date_overrides": sum(
                x.get("has_overrides") is True for x in assignments
            ),
        }
    return {
        "schema_version": SCHEMA,
        "snapshot": snapshot.name,
        "qc": qc,
        "counts": counts,
        "findings": findings,
        "canvas_writes": 0,
    }


def assignment_from(snapshot: Path, label: str, assignment_id: str) -> dict[str, Any]:
    require_valid(snapshot)
    if label not in COURSES:
        raise MirrorError("INVALID_COURSE_SCOPE")
    for item in read_json(snapshot / label / "objects" / "assignments.json"):
        if str(item["id"]) == course_id(assignment_id):
            return dict(item)
    raise MirrorError("ASSIGNMENT_NOT_IN_SNAPSHOT")


def stage_description(
    snapshot: Path, label: str, assignment_id: str, html: str, output: Path
) -> dict[str, Any]:
    current = assignment_from(snapshot, label, assignment_id)
    before = current.get("description") or ""
    if not html.strip() or html == before:
        raise MirrorError("DRAFT_EMPTY_OR_UNCHANGED")
    draft = {
        "schema_version": SCHEMA,
        "kind": "assignment_description_proposal",
        "status": "DRAFT_NOT_AUTHORIZED",
        "origin": ORIGIN,
        "course": label,
        "course_id": COURSES[label],
        "assignment_id": course_id(assignment_id),
        "snapshot": snapshot.name,
        "created_at": now(),
        "canvas_writes": 0,
        "baseline_object_sha256": sha(encoded(current)),
        "before_description": before,
        "proposed_description": html,
        "before_sha256": sha(before.encode()),
        "proposed_sha256": sha(html.encode()),
        "preserve": {
            k: current.get(k)
            for k in (
                "points_possible",
                "published",
                "submission_types",
                "due_at",
                "all_dates",
                "external_tool_tag_attributes",
            )
        },
        "approval": "User must approve exact changes; this tool has no apply command.",
    }
    private_write(output, draft)
    return {"status": draft["status"], "proposal": str(output), "canvas_writes": 0}


def check_proposal(snapshot: Path, proposal: Path) -> dict[str, Any]:
    draft = read_json(proposal)
    if (
        draft.get("kind") != "assignment_description_proposal"
        or draft.get("status") != "DRAFT_NOT_AUTHORIZED"
        or draft.get("origin") != ORIGIN
        or draft.get("course_id") != COURSES.get(draft.get("course"))
    ):
        raise MirrorError("INVALID_PROPOSAL")
    for field, digest in (
        ("before_description", "before_sha256"),
        ("proposed_description", "proposed_sha256"),
    ):
        if not isinstance(draft.get(field), str) or sha(
            draft[field].encode()
        ) != draft.get(digest):
            raise MirrorError("PROPOSAL_HASH_MISMATCH")
    current = assignment_from(snapshot, draft["course"], draft["assignment_id"])
    matches = sha(encoded(current)) == draft.get("baseline_object_sha256")
    return {
        "status": (
            "BASELINE_MATCH_NOT_AUTHORIZATION"
            if matches
            else "CONFLICT_REVIEW_REQUIRED"
        ),
        "canvas_writes": 0,
        "live_read_required_before_write": True,
    }


def resources_check(archive: Path) -> dict[str, Any]:
    root = archive / "google-resources"
    errors: list[str] = []
    ids: set[str] = set()
    checked = 0
    for name in (
        "manifest.json",
        "nested-manifest.json",
        "recursive-manifest.json",
        "related-manifest.json",
    ):
        if not (root / name).exists():
            continue
        for resource in read_json(root / name)["resources"]:
            checked += 1
            if resource["id"] in ids:
                errors.append("DUPLICATE_RESOURCE")
            ids.add(resource["id"])
            export = resource["export"]
            try:
                path = checked_path(root, export["relative_path"])
                data = path.read_bytes()
                if sha(data) != export["sha256"] or len(data) != export["bytes"]:
                    errors.append("RESOURCE_HASH_OR_SIZE_MISMATCH")
            except (MirrorError, OSError):
                errors.append("RESOURCE_UNREADABLE")
    if not checked:
        errors.append("NO_RESOURCES")
    return {
        "ok": not errors,
        "checked": checked,
        "errors": sorted(set(errors)),
        "note": "Local byte integrity only; Google freshness and LTI attachment identity are not verified.",
    }


class LinkParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.links: set[str] = set()

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        for name, value in attrs:
            if name in {"href", "src"} and value:
                self.links.add(value)


def link_inventory(snapshot: Path) -> dict[str, Any]:
    """Private link map; does not launch LTI, follow links, or assert attachment IDs."""
    objects = snapshot_objects(snapshot)
    links = []
    for (label, kind, identity), item in sorted(objects.items()):
        found: set[str] = set()
        for field in ("description", "body", "message", "syllabus_body"):
            value = item.get(field)
            if isinstance(value, str):
                parser = LinkParser()
                parser.feed(value)
                found.update(parser.links)
        if isinstance(item.get("external_url"), str):
            found.add(item["external_url"])
        lti = item.get("external_tool_tag_attributes") or {}
        if isinstance(lti, dict) and isinstance(lti.get("url"), str):
            found.add(lti["url"])
        for url in sorted(found):
            try:
                parsed = urlsplit(url)
            except ValueError:
                continue
            if parsed.scheme not in ("https", "http"):
                continue
            google_id = None
            if parsed.hostname in {"docs.google.com", "drive.google.com"}:
                match = re.search(r"/(?:d|folders)/([A-Za-z0-9_-]+)", parsed.path)
                google_id = (
                    match.group(1)
                    if match
                    else parse_qs(parsed.query).get("id", [None])[0]
                )
            links.append(
                {
                    "course": label,
                    "kind": kind,
                    "object_id": identity,
                    "url": url,
                    "host": parsed.hostname,
                    "google_file_id": google_id,
                    "status": (
                        "OPAQUE_LTI"
                        if parsed.hostname == "assignments.google.com"
                        else "NOT_CHECKED_LIVE"
                    ),
                }
            )
    return {
        "schema_version": SCHEMA,
        "snapshot": snapshot.name,
        "links": links,
        "link_occurrences": len(links),
        "unique_urls": len({x["url"] for x in links}),
        "google_resource_ids": len(
            {x["google_file_id"] for x in links if x["google_file_id"]}
        ),
        "opaque_lti_links": sum(x["status"] == "OPAQUE_LTI" for x in links),
    }


def status(root: Path) -> dict[str, Any]:
    snapshots = []
    for path in sorted(root.glob("*/manifest.json")):
        try:
            manifest = read_json(path)
            if manifest.get("kind") != "content_mirror":
                continue
            snapshots.append(
                {
                    "snapshot": path.parent.name,
                    "status": manifest.get("status"),
                    "started_at": manifest.get("started_at"),
                    "finished_at": manifest.get("finished_at"),
                    "courses": sorted(manifest.get("courses", {})),
                    "completed_endpoints": sum(
                        x.get("status") == "COMPLETE"
                        for x in manifest.get("entries", [])
                    ),
                    "qc_ok": verify(path.parent)["ok"],
                }
            )
        except (MirrorError, AttributeError):
            snapshots.append(
                {"snapshot": path.parent.name, "status": "UNREADABLE", "qc_ok": False}
            )
    return {
        "snapshots": snapshots,
        "canvas_writes": 0,
        "note": "No automatic fallback: choose an explicit QC-passing snapshot for comparison or drafting.",
    }
