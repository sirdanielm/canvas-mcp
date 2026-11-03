"""Inactive exact-manifest private Canvas text delivery; never a generic sender.

The operator supplies the existing authenticated GradebookClient, Store and Ledger.
No factory, credentials, registration, PDF upload or grade mutation lives here.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import secrets
import stat
import time
from decimal import Decimal
from pathlib import Path
from typing import Any, cast
from urllib.parse import urlencode, urlsplit

import httpx

from canvas_mcp.gradebook.client import GradebookError
from canvas_mcp.gradebook.ledger import Ledger
from canvas_mcp.gradebook.store import Store

REVIEWED_MANIFEST_SHA256: str | None = None
MAX_BATCH = 3
MAX_SOURCE_BYTES = 20_000_000
MAX_GET_BYTES = 5_000_000
CLAIM_TABLES = frozenset({"text_comment_deliveries_v1", "text_comment_fresh_completions_v1"})
_VOLATILE = {"submission_comments", "updated_at", "read_status", "html_url", "preview_url", "seconds_late"}


def need(condition: bool, code: str) -> None:
    if not condition:
        raise GradebookError(code)


class _DecimalToken(str):
    """Preserve the exact JSON number token; never round a live grade through float."""


def _json(raw: bytes) -> Any:
    def invalid(_: str) -> Any:
        raise GradebookError("NONFINITE_JSON")

    try:
        return json.loads(raw, parse_float=_DecimalToken, parse_constant=invalid)
    except (UnicodeError, ValueError) as exc:
        raise GradebookError("INVALID_JSON") from exc


def encoded(value: Any) -> Any:
    if isinstance(value, _DecimalToken):
        return ["decimal", str(value)]
    if value is None:
        return ["null"]
    if type(value) is bool:
        return ["bool", value]
    if type(value) is int:
        return ["int", value]
    if type(value) is str:
        return ["str", value]
    if type(value) is list:
        return ["list", [encoded(x) for x in value]]
    need(type(value) is dict, "UNSUPPORTED_JSON_TYPE")
    return ["dict", [[k, encoded(value[k])] for k in sorted(value)]]


def file_pin(path: Path) -> dict[str, Any]:
    """Offline operator convenience; never called automatically on source/media."""
    raw = path.read_bytes()
    return {"path": str(path), "sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw)}


def pinned(ref: Any) -> bytes:
    need(type(ref) is dict and set(ref) == {"path", "sha256", "bytes"}, "INVALID_FILE_PIN")
    need(type(ref["path"]) is str and type(ref["sha256"]) is str, "INVALID_FILE_PIN")
    need(re.fullmatch("[a-f0-9]{64}", ref["sha256"]) is not None, "INVALID_FILE_PIN")
    need(type(ref["bytes"]) is int and 0 < ref["bytes"] <= MAX_SOURCE_BYTES, "INVALID_FILE_PIN")
    path = Path(ref["path"])
    need(path.is_absolute() and ".." not in path.parts, "INVALID_PRIVATE_PATH")
    need(all(not p.is_symlink() for p in (path, *path.parents)), "SYMLINK_PIN")
    parent = path.parent.stat()
    need(parent.st_uid == os.getuid() and stat.S_IMODE(parent.st_mode) == 0o700, "PRIVATE_PARENT_REQUIRED")
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        before = os.fstat(fd)
        need(stat.S_ISREG(before.st_mode) and before.st_uid == os.getuid(), "PRIVATE_FILE_REQUIRED")
        need(stat.S_IMODE(before.st_mode) == 0o600 and before.st_nlink == 1, "PRIVATE_FILE_REQUIRED")
        need(before.st_size == ref["bytes"], "PIN_SIZE_MISMATCH")
        with os.fdopen(fd, "rb", closefd=False) as stream:
            raw = stream.read(MAX_SOURCE_BYTES + 1)
        after, named = os.fstat(fd), path.stat(follow_symlinks=False)
        def facts(s: os.stat_result) -> tuple[int, ...]:
            return (s.st_dev, s.st_ino, s.st_mode, s.st_uid, s.st_nlink, s.st_size, s.st_mtime_ns, s.st_ctime_ns)
        need(facts(before) == facts(after) == facts(named), "PIN_CHANGED_DURING_READ")
        need(len(raw) == ref["bytes"] and hashlib.sha256(raw).hexdigest() == ref["sha256"], "PIN_HASH_MISMATCH")
        return raw
    finally:
        os.close(fd)


def _id(value: Any) -> int:
    if type(value) is not int or value <= 0:
        raise GradebookError("TYPED_POSITIVE_ID_REQUIRED")
    return value


def target(record: dict[str, Any]) -> dict[str, Any]:
    keys = ("course_id", "assignment_id", "user_id", "submission_id", "section_id")
    result = {k: _id(record.get(k)) for k in keys}
    need("attempt" in record and (record["attempt"] is None or type(record["attempt"]) is int and record["attempt"] > 0), "TYPED_ATTEMPT_REQUIRED")
    result["attempt"] = record["attempt"]
    return result


def key(origin: str, record: dict[str, Any]) -> str:
    return ":".join((origin, str(record["course_id"]), str(record["user_id"]), str(record["assignment_id"])))


def stable(submission: dict[str, Any]) -> Any:
    return encoded({k: v for k, v in submission.items() if k not in _VOLATILE})


def no_transport_retries(http: httpx.AsyncClient) -> None:
    # Exact pinned HTTPX transport types only; MockTransport is the offline test
    # seam. Custom/retrying adapters are not an enabled operator destination.
    for transport in [http._transport, *http._mounts.values()]:
        if transport is None or type(transport) is httpx.MockTransport:
            continue
        need(type(transport) is httpx.AsyncHTTPTransport and getattr(transport._pool, "_retries", None) == 0, "RETRYING_OR_CUSTOM_WRITE_TRANSPORT_FORBIDDEN")


def comments(submission: dict[str, Any]) -> dict[str, Any]:
    need("submission_comments" in submission and type(submission["submission_comments"]) is list, "COMMENTS_COVERAGE_MISSING")
    result = {}
    for c in submission["submission_comments"]:
        need(type(c) is dict and type(c.get("comment")) is str, "COMMENT_SHAPE_INVALID")
        cid = str(_id(c.get("id")))
        _id(c.get("author_id"))
        need(cid not in result, "DUPLICATE_COMMENT_ID")
        result[cid] = c
    return result


def matching(current: dict[str, Any], actor_id: int, body: str) -> list[str]:
    found = []
    for cid, c in current.items():
        # Only the observed Canvas omission of ONE terminal LF is equivalent.
        same_body = c["comment"] == body or body.endswith("\n") and c["comment"] == body[:-1]
        need(not same_body or c["author_id"] == actor_id, "EXACT_BODY_BY_DIFFERENT_AUTHOR_REVIEW_ONLY")
        if c["author_id"] == actor_id and same_body:
            need(c.get("hidden") is not True and c.get("draft") is not True, "EXACT_COMMENT_NOT_VISIBLE")
            found.append(cid)
    need(len(found) <= 1, "DUPLICATE_EXACT_AUTHORED_BODY")
    return found


class TextCommentDelivery:
    """Explicit private entrypoint. Construction performs no I/O or table creation."""

    def __init__(self, client: Any, store: Store, ledger: Ledger, manifest_ref: dict[str, Any], *, canonical_root: Path) -> None:
        need(isinstance(canonical_root, Path) and canonical_root.is_absolute()
             and ".." not in canonical_root.parts, "EXPLICIT_CANONICAL_STATE_ROOT_REQUIRED")
        self.canonical_root = canonical_root
        self.client, self.store, self.ledger, self.manifest_ref = client, store, ledger, manifest_ref
        self._held_receipts: list[str] = []
        self._last_get_receipt: str | None = None

    def _manifest(self, *, lease: bool = True) -> dict[str, Any]:
        reviewed = self._reviewed_manifest_sha256()
        need(reviewed is not None and self.manifest_ref.get("sha256") == reviewed, "TEXT_ROUTE_DISABLED_OR_UNREVIEWED")
        need(self.store.root == self.canonical_root and self.ledger.path == self.canonical_root / "push-ledger.sqlite3", "SHARED_CANONICAL_STATE_REQUIRED")
        m = _json(pinned(self.manifest_ref))
        need(type(m) is dict and m.get("kind") == "EXACT_AUDITED_SHEET_TEXT_COMMENT_RELEASE_V1", "MANIFEST_KIND_MISMATCH")
        origin = m.get("origin")
        need(type(origin) is str and origin == self.client.origin and origin == origin.rstrip("/"), "ORIGIN_MISMATCH")
        url = urlsplit(origin)
        need(url.scheme == "https" and bool(url.hostname) and not (url.username or url.password or url.query or url.fragment or url.path), "ORIGIN_INVALID")
        _id(m.get("actor_id"))
        need(m.get("submission_include") in (["visibility", "submission_comments"], ["visibility", "submission_comments", "user"]), "EXACT_SUBMISSION_GET_QUERY_REQUIRED")
        need(m.get("assignment_include") in ([], ["all_dates", "overrides"]), "EXACT_ASSIGNMENT_GET_QUERY_REQUIRED")
        records = m.get("records")
        need(type(records) is list and 1 <= len(records) <= MAX_BATCH, "BATCH_LIMIT")
        keys, pins = [], []
        for r in records:
            need(type(r) is dict and type(r.get("pin")) is str and re.fullmatch("[0-9]{4}", r["pin"]) is not None, "PIN_INVALID")
            t = target(r)
            keys.append(key(origin, t))
            pins.append(r["pin"])
        need(len(set(keys)) == len(keys) and len(set(pins)) == len(pins), "DUPLICATE_TARGET")
        need(type(m.get("not_before")) is int and type(m.get("expires")) is int and 0 < m["expires"] - m["not_before"] <= 600, "FINITE_LEASE_REQUIRED")
        if lease:
            need(m["not_before"] <= time.time() < m["expires"], "MANIFEST_EXPIRED_OR_NOT_STARTED")
        return cast(dict[str, Any], m)

    def _authority(self, m: dict[str, Any]) -> list[dict[str, Any]]:
        # A source seal checks integrity, not human identity. Root must independently
        # authenticate the referenced original human instruction before sealing.
        a = _json(pinned(m["authority_ref"]))
        bindings = [{**target(r), "pin": r["pin"], "body_ref": r["body_ref"]} for r in m["records"]]
        need(type(a) is dict and a.get("kind") == "DIRECT_HUMAN_TEXT_COMMENT_RELEASE_BINDING", "AUTHORITY_KIND_MISMATCH")
        need(a.get("origin") == m["origin"] and a.get("records") == bindings, "AUTHORITY_VECTOR_MISMATCH")
        need(a.get("direct_human_approval") is True and a.get("text_only") is True and a.get("grade_write") is False and a.get("pdf_upload") is False, "DIRECT_TEXT_ONLY_AUTHORITY_REQUIRED")
        pinned(a["original_human_evidence_ref"])
        coverage = _json(pinned(m["coverage_ref"]))
        need(type(coverage) is dict and coverage.get("kind") == "REVIEWED_COMPLETE_SUBMISSION_COMMENTS_GET_CONTRACT" and coverage.get("origin") == m["origin"] and coverage.get("include") == m["submission_include"] and coverage.get("complete") is True, "COMMENT_COVERAGE_CONTRACT_REQUIRED")
        pinned(coverage["evidence_ref"])
        loaded = []
        for r in m["records"]:
            raw = pinned(r["body_ref"])
            need(len(raw) <= 100_000, "BODY_TOO_LARGE")
            try:
                body = raw.decode("utf-8")
            except UnicodeError as exc:
                raise GradebookError("BODY_UTF8_REQUIRED") from exc
            need(bool(body) and not body.isspace() and "\x00" not in body, "BODY_EMPTY_OR_NUL")
            source = _json(pinned(r["source_ref"]))
            need(type(source) is dict and source.get("kind") == "AUDITED_SHEET_TEXT_COMMENT_SOURCE_BINDING" and source.get("target") == target(r) and source.get("body_ref") == r["body_ref"], "SOURCE_BODY_TARGET_MISMATCH")
            need(source.get("audited_resolved") is True and source.get("canvas_text_release") is True, "SOURCE_RELEASE_NOT_QUALIFIED")
            pinned(source["central_mirror_receipt_ref"])
            owner_refs = source.get("owner_evidence_refs")
            need(type(owner_refs) is list and bool(owner_refs), "OWNER_EVIDENCE_REQUIRED")
            for ref in owner_refs:
                pinned(ref)
            expected = _json(pinned(r["submission_ref"]))
            assignment = _json(pinned(r["assignment_ref"]))
            self._submission_identity(expected, r)
            self._assignment(assignment, r)
            loaded.append({"record": r, "body": body, "expected": expected, "assignment": assignment})
        return loaded

    def _save(self, value: dict[str, Any]) -> str:
        return self.store.save("receipt", value)[0]

    def _raw(self, response: httpx.Response, phase: str) -> str:
        return self._save({"kind": "TEXT_COMMENT_RAW_HTTP", "phase": phase, "captured_at": time.time(), "method": response.request.method, "url": str(response.request.url), "status": response.status_code, "raw_base64": base64.b64encode(response.content).decode(), "sha256": hashlib.sha256(response.content).hexdigest(), "headers": {k: v for k, v in response.headers.items() if k.lower() in {"link", "content-type"}}})

    async def _get(self, path: str, params: Any = None) -> tuple[Any, str]:
        # Direct HTTPX: no GradebookClient._get/pages 429 retry machinery.
        response = await self.client.http.get(self.client.origin + "/api/v1" + path, params=params)
        need(len(response.content) <= MAX_GET_BYTES, "GET_RESPONSE_TOO_LARGE")
        receipt = self._raw(response, "get")
        self._last_get_receipt = receipt
        need(response.status_code == 200 and not response.is_redirect, "CURRENT_GET_FAILED")
        need(not response.links.get("next") and not response.links.get("prev"), "INCOMPLETE_OR_PAGINATED_GET")
        return _json(response.content), receipt

    @staticmethod
    def _path(r: dict[str, Any]) -> str:
        return f"/courses/{r['course_id']}/assignments/{r['assignment_id']}/submissions/{r['user_id']}"

    @staticmethod
    def _submission_identity(s: Any, r: dict[str, Any]) -> None:
        need(type(s) is dict, "SUBMISSION_SHAPE")
        for k in ("id", "user_id", "assignment_id"):
            expected = r["submission_id"] if k == "id" else r[k]
            need(type(s.get(k)) is int and s[k] == expected, "RAW_SUBMISSION_IDENTITY_MISMATCH")
        need("attempt" in s and type(s["attempt"]) is type(r["attempt"]) and s["attempt"] == r["attempt"], "RAW_ATTEMPT_MISMATCH")
        need("excused" in s and (s["excused"] is None or type(s["excused"]) is bool and s["excused"] is False), "EXCUSED_OR_UNTYPED_SUBMISSION_HOLD")
        need(s.get("assignment_visible") is True and s.get("grade_matches_current_submission") is True and s.get("in_closed_grading_period") is not True, "SUBMISSION_PUBLICATION_HOLD")
        need("score" in s and "grade" in s, "RAW_GRADE_FIELDS_REQUIRED")

    @staticmethod
    def _assignment(a: Any, r: dict[str, Any]) -> None:
        need(type(a) is dict and type(a.get("id")) is int and a["id"] == r["assignment_id"] and type(a.get("course_id")) is int and a["course_id"] == r["course_id"], "ASSIGNMENT_IDENTITY_MISMATCH")
        need(a.get("published") is True and a.get("grading_type") == "points" and a.get("in_closed_grading_period") is False and a.get("post_manually") is False, "ASSIGNMENT_PUBLICATION_HOLD")
        need(a.get("submission_types") == ["on_paper"] and a.get("moderated_grading") is False and a.get("anonymous_grading") is False and a.get("has_sub_assignments") is not True and a.get("group_category_id") is None and a.get("use_rubric_for_grading") is not True, "COMPLEX_ASSIGNMENT_HOLD")
        points = a.get("points_possible")
        need(type(points) is int or isinstance(points, _DecimalToken), "UNIT1_POINTS_MISMATCH")
        need(Decimal(str(points)) == 100, "UNIT1_POINTS_MISMATCH")

    async def _observe(self, m: dict[str, Any], item: dict[str, Any], *, authority: bool = True) -> dict[str, Any]:
        r, receipts = item["record"], []
        if authority:
            actor, receipt = await self._get("/users/self")
            receipts.append(receipt)
            need(type(actor) is dict and type(actor.get("id")) is int and actor["id"] == m["actor_id"] and actor["id"] != r["user_id"], "ACTOR_MISMATCH")
            course, receipt = await self._get(f"/courses/{r['course_id']}")
            receipts.append(receipt)
            need(type(course) is dict and type(course.get("id")) is int and course["id"] == r["course_id"] and course.get("workflow_state") == "available", "COURSE_NOT_AVAILABLE")
            permission, receipt = await self._get(f"/courses/{r['course_id']}/permissions", [("permissions[]", "manage_grades")])
            receipts.append(receipt)
            need(type(permission) is dict and permission.get("manage_grades") is True, "GRADE_PERMISSION_REVOKED")
            enrollment, receipt = await self._get(f"/courses/{r['course_id']}/enrollments", [("user_id", str(r["user_id"])), ("type[]", "StudentEnrollment"), ("state[]", "active"), ("per_page", "100")])
            receipts.append(receipt)
            need(type(enrollment) is list and bool(enrollment), "ACTIVE_SECTION_MISSING")
            need(all(type(e) is dict and type(e.get("user_id")) is int and e["user_id"] == r["user_id"] and type(e.get("course_id")) is int and e["course_id"] == r["course_id"] and e.get("type") == "StudentEnrollment" and e.get("enrollment_state") == "active" for e in enrollment), "ENROLLMENT_IDENTITY_MISMATCH")
            need(any(type(e.get("course_section_id")) is int and e["course_section_id"] == r["section_id"] for e in enrollment), "ACTIVE_SECTION_MISSING")
            assignment, receipt = await self._get(f"/courses/{r['course_id']}/assignments/{r['assignment_id']}", [("include[]", x) for x in m["assignment_include"]])
            receipts.append(receipt)
            self._assignment(assignment, r)
            need(encoded({k: v for k, v in assignment.items() if k != "updated_at"}) == encoded({k: v for k, v in item["assignment"].items() if k != "updated_at"}), "ASSIGNMENT_CHANGED")
        started = time.time()
        submission, receipt = await self._get(self._path(r), [("include[]", x) for x in m["submission_include"]])
        receipts.append(receipt)
        self._submission_identity(submission, r)
        need(stable(submission) == stable(item["expected"]), "RAW_SUBMISSION_OR_GRADE_CHANGED")
        cs = comments(submission)
        visible = [cid for cid, c in cs.items() if type(c.get("created_at")) is str and bool(c["created_at"]) and c.get("hidden") is not True and c.get("draft") is not True and not c.get("attachments") and ("attempt" not in c or type(c["attempt"]) is type(r["attempt"]) and c["attempt"] == r["attempt"])]
        links = {cid: {"id": c["id"], "author_id": c["author_id"], "comment": c["comment"]} for cid, c in cs.items()}
        return {"stable": stable(submission), "comments": {cid: encoded(c) for cid, c in cs.items()}, "comment_links": links, "matching": matching(cs, m["actor_id"], item["body"]), "verified_comment_ids": visible, "started": started, "receipts": receipts}

    def _reviewed_manifest_sha256(self) -> str | None:
        return REVIEWED_MANIFEST_SHA256

    def _claim_table(self) -> str:
        return "text_comment_deliveries_v1"

    def _checked_claim_table(self) -> str:
        name = self._claim_table()
        need(type(name) is str and name in CLAIM_TABLES, "UNREVIEWED_CLAIM_TABLE")
        return name

    def _prepare_admission(self, db: Any, manifest: dict[str, Any]) -> None:
        """Owner extension point; the default preserves legacy admission."""

    def _append_disposition(self, db: Any, manifest: dict[str, Any], operation_id: str, plan_id: str) -> None:
        """Owner extension point, inside the sole preparation transaction."""

    def _no_op_disposition(self, manifest: dict[str, Any], receipt_id: str) -> None:
        """Owner extension point; default no-op behavior remains unchanged."""

    def _tables(self, db: Any) -> None:
        db.execute(f"CREATE TABLE IF NOT EXISTS {self._checked_claim_table()} (target TEXT PRIMARY KEY, operation_id TEXT NOT NULL, position INTEGER NOT NULL, plan_id TEXT NOT NULL, phase TEXT NOT NULL, state_id TEXT, UNIQUE(operation_id,position))")

    async def prepare(self) -> dict[str, Any]:
        m = self._manifest()
        loaded = self._authority(m)
        observed = [await self._observe(m, item) for item in loaded]
        self._authority(self._manifest())
        active = [i for i, before in enumerate(observed) if not before["matching"]]
        preview = {"kind": "EXACT_TEXT_COMMENT_REVIEW_V1", "manifest_ref": self.manifest_ref, "actor_id": m["actor_id"], "origin": m["origin"], "items": [{"record": loaded[i]["record"], "body": loaded[i]["body"], "before": observed[i]} for i in active], "no_ops": [loaded[i]["record"]["pin"] for i, before in enumerate(observed) if before["matching"]], "retry_writes": False, "grade_write": False, "pdf_upload": False}
        if not active:
            receipt_id = self._save(preview)
            self._no_op_disposition(m, receipt_id)
            return {"status": "NO_OP", "receipt_id": receipt_id, "retry_writes": False}
        plan_id = self.store.save("review", preview)[0]
        op, token, now = secrets.token_hex(16), secrets.token_urlsafe(32), time.time()
        targets = [key(m["origin"], loaded[i]["record"]) for i in active]
        with self.ledger.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            self._tables(db)
            need(m["not_before"] <= time.time() < m["expires"], "MANIFEST_EXPIRED_OR_NOT_STARTED")
            self._prepare_admission(db, m)
            for k in targets:
                need(db.execute("SELECT 1 FROM target_locks WHERE target=?", (k,)).fetchone() is None, "UNRESOLVED_SCORE_OR_DELIVERY_LOCK")
                need(db.execute(f"SELECT 1 FROM {self._checked_claim_table()} WHERE target=?", (k,)).fetchone() is None, "TEXT_TARGET_PERMANENTLY_CLAIMED_RECONCILE_ONLY")
                if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='comment_pdf_deliveries'").fetchone():
                    need(db.execute("SELECT 1 FROM comment_pdf_deliveries WHERE target=?", (k,)).fetchone() is None, "PDF_DELIVERY_ALREADY_CLAIMED")
            # Same schema and token protocol as Ledger.prepare, atomically with
            # permanent claims before tokens leave this method. No old row changes.
            db.execute("INSERT INTO operations VALUES(?,?,?,?,?,?)", (op, plan_id, hashlib.sha256(token.encode()).hexdigest(), min(now + 600, m["expires"]), "prepared", now))
            for position, k in enumerate(targets):
                db.execute("INSERT INTO items VALUES(?,?,?,?)", (op, position, k, "planned"))
                db.execute(f"INSERT INTO {self._checked_claim_table()} VALUES(?,?,?,?,?,NULL)", (k, op, position, plan_id, "prepared"))
            self._append_disposition(db, m, op, plan_id)
        return {"plan_id": plan_id, "operation_id": op, "confirmation_token": token, "enabled": False, "retry_writes": False, "count": len(active)}

    def _plan(self, plan_id: str, op: str) -> dict[str, Any]:
        p, operation = self.store.load("review", plan_id), self.ledger.operation(op)
        need(p.get("kind") == "EXACT_TEXT_COMMENT_REVIEW_V1" and p.get("manifest_ref") == self.manifest_ref and operation["plan_id"] == plan_id, "PLAN_OPERATION_MISMATCH")
        need(len(p["items"]) == len(operation["items"]) and 1 <= len(p["items"]) <= MAX_BATCH, "PLAN_VECTOR_MISMATCH")
        for i, item in enumerate(p["items"]):
            need(operation["items"][i]["position"] == i and operation["items"][i]["target"] == key(p["origin"], item["record"]), "PLAN_TARGET_MISMATCH")
        return p

    def _bound(self, op: str, position: int, plan_id: str, expected_status: str) -> None:
        with self.ledger.connect() as db:
            operation = db.execute("SELECT * FROM operations WHERE id=?", (op,)).fetchone()
            item = db.execute("SELECT * FROM items WHERE operation_id=? AND position=?", (op, position)).fetchone()
            claim = db.execute(f"SELECT * FROM {self._checked_claim_table()} WHERE operation_id=? AND position=?", (op, position)).fetchone()
            need(operation is not None and item is not None and claim is not None, "PERMANENT_CLAIM_MISSING")
            need(operation["status"] == "running" and operation["plan_id"] == plan_id and time.time() < operation["expires"] and item["status"] == expected_status and claim["plan_id"] == plan_id and claim["target"] == item["target"], "CONSUMED_STALE_OR_CHANGED_OPERATION")
            need(claim["phase"] == ("prepared" if expected_status == "planned" else "sending") and (expected_status != "sending" or claim["state_id"] is not None), "PERMANENT_CLAIM_PHASE_CHANGED")
            need(db.execute("SELECT 1 FROM target_locks WHERE target=? AND operation_id=?", (item["target"], op)).fetchone() is not None, "SHARED_TARGET_LOCK_LOST")

    def _state(self, op: str, position: int) -> dict[str, Any]:
        with self.ledger.connect() as db:
            row = db.execute(f"SELECT state_id FROM {self._checked_claim_table()} WHERE operation_id=? AND position=?", (op, position)).fetchone()
        need(row is not None and row["state_id"] is not None, "DURABLE_INTENT_UNAVAILABLE")
        return self.store.load("receipt", row["state_id"])

    def _checkpoint(self, op: str, position: int, phase: str, value: dict[str, Any]) -> str:
        state_id = self._save({**value, "phase": phase})
        with self.ledger.connect() as db:
            need(db.execute(f"UPDATE {self._checked_claim_table()} SET phase=?,state_id=? WHERE operation_id=? AND position=?", (phase, state_id, op, position)).rowcount == 1, "PERMANENT_CLAIM_MISSING")
        return state_id

    @staticmethod
    def _outcome(before: dict[str, Any], after: dict[str, Any], response_comments: dict[str, Any] | None) -> str:
        need(before["stable"] == after["stable"], "READBACK_GRADE_OR_SUBMISSION_CHANGED")
        need(all(after["comments"].get(cid) == c for cid, c in before["comments"].items()), "EXISTING_COMMENTS_CHANGED")
        added = set(after["comments"]) - set(before["comments"])
        need(len(after["matching"]) == 1 and added == set(after["matching"]), "NEW_EXACT_COMMENT_NOT_UNIQUE")
        need(after["matching"][0] in after["verified_comment_ids"], "NEW_COMMENT_VISIBILITY_TIMESTAMP_OR_ATTEMPT_UNVERIFIED")
        if response_comments is not None:
            cid = after["matching"][0]
            need(response_comments.get(cid) == after["comment_links"][cid], "PUT_RESPONSE_COMMENT_NOT_LINKED")
        return "verified" if response_comments is not None else "observed_applied"

    async def confirm(self, plan_id: str, op: str, token: str, *, enabled: bool = False, reviewed_plan_sha256: str = "") -> dict[str, Any]:
        need(enabled is True and reviewed_plan_sha256 == plan_id, "EXPLICIT_EXACT_PLAN_ENABLE_REQUIRED")
        with self.ledger.exclusive(op):
            p = self._plan(plan_id, op)
            m = self._manifest()
            loaded = self._authority(m)
            by_key = {key(m["origin"], x["record"]): x for x in loaded}
            for item in p["items"]:
                x = by_key.get(key(m["origin"], item["record"]))
                need(x is not None and x["record"] == item["record"] and x["body"] == item["body"], "PLAN_SOURCE_BODY_MISMATCH")
            need(self.ledger.claim(op, token) == plan_id, "CLAIM_PLAN_MISMATCH")
            self._held_receipts = []
            for position, reviewed in enumerate(p["items"]):
                item = by_key[key(m["origin"], reviewed["record"])]
                await self._send(m, item, plan_id, op, position)
                if self.ledger.operation(op)["items"][position]["status"] not in {"verified", "observed_applied"}:
                    break
            return {**self.ledger.finish(op), "held_receipts": self._held_receipts}

    async def _send(self, m: dict[str, Any], item: dict[str, Any], plan_id: str, op: str, position: int) -> None:
        body = urlencode([("comment[text_comment]", item["body"]), ("comment[group_comment]", "false")]).encode("ascii")
        url = self.client.origin + "/api/v1" + self._path(item["record"])
        http = self.client.http
        need(isinstance(http, httpx.AsyncClient) and http.follow_redirects is False, "NONREVIEWED_HTTP_TRANSPORT")
        no_transport_retries(http)
        previous_hooks = list(http.event_hooks["request"])
        hook_calls, sent, no_op = 0, False, False
        before: dict[str, Any] | None = None

        async def final_hook(request: httpx.Request) -> None:
            nonlocal hook_calls, sent, no_op, before
            if request.method != "PUT":
                return
            hook_calls += 1
            need(hook_calls == 1 and str(request.url) == url and request.content == body, "ONE_EXACT_COMMENT_PUT_ONLY")
            need(request.headers.get("content-type") == "application/x-www-form-urlencoded" and not request.headers.get("content-encoding"), "EXACT_COMMENT_FORM_HEADERS_REQUIRED")
            need(http.event_hooks["request"] == [*previous_hooks, final_hook], "UNREVIEWED_LATE_REQUEST_HOOK")
            self._bound(op, position, plan_id, "planned")
            self._authority(self._manifest())
            # HTTPX awaits request hooks before sending; this final submission GET
            # is the last await. Every later guard and intent checkpoint is sync.
            before = await self._observe(m, item)
            self._authority(self._manifest())
            self._bound(op, position, plan_id, "planned")
            need(time.time() - before["started"] <= 60, "IMMEDIATE_SUBMISSION_GET_EXPIRED")
            need(http.event_hooks["request"] == [*previous_hooks, final_hook], "UNREVIEWED_LATE_REQUEST_HOOK")
            if before["matching"]:
                no_op = True
                self._checkpoint(op, position, "deduplicated", {"kind": "TEXT_COMMENT_NO_OP", "before": before, "retry_writes": False})
                self.ledger.mark(op, position, "observed_applied")
                raise GradebookError("EXACT_AUTHORED_BODY_ALREADY_PRESENT_NO_SEND")
            intent = {"kind": "TEXT_COMMENT_DURABLE_INTENT", "operation_id": op, "position": position, "plan_id": plan_id, "manifest_ref": self.manifest_ref, "before": before, "body_sha256": item["record"]["body_ref"]["sha256"], "request_sha256": hashlib.sha256(body).hexdigest(), "url": url, "retry_writes": False, "grade_write": False, "pdf_upload": False}
            state_id = self._save(intent)
            with self.ledger.connect() as db:
                db.execute("BEGIN IMMEDIATE")
                need(db.execute("SELECT 1 FROM operations WHERE id=? AND status='running' AND plan_id=? AND expires>?", (op, plan_id, time.time())).fetchone() is not None, "LATE_OPERATION_CHANGED")
                need(db.execute("SELECT 1 FROM target_locks WHERE target=? AND operation_id=?", (key(m["origin"], item["record"]), op)).fetchone() is not None, "SHARED_TARGET_LOCK_LOST")
                need(db.execute("UPDATE items SET status='sending' WHERE operation_id=? AND position=? AND status='planned'", (op, position)).rowcount == 1, "LATE_ITEM_CHANGED")
                need(db.execute(f"UPDATE {self._checked_claim_table()} SET phase='sending',state_id=? WHERE operation_id=? AND position=? AND plan_id=? AND phase='prepared' AND target=?", (state_id, op, position, plan_id, key(m["origin"], item["record"]))).rowcount == 1, "LATE_PERMANENT_CLAIM_CHANGED")
            self._bound(op, position, plan_id, "sending")
            self._authority(self._manifest())
            need(time.time() - before["started"] <= 60, "IMMEDIATE_SUBMISSION_GET_EXPIRED")
            sent = True

        http.event_hooks["request"] = [*previous_hooks, final_hook]
        try:
            response = await http.put(url, content=body, headers={"Content-Type": "application/x-www-form-urlencoded"}, follow_redirects=False)
            response_ref = self._raw(response, "put")
            need(sent and hook_calls == 1 and before is not None, "FINAL_HTTP_GUARD_NOT_EXECUTED")
            self._checkpoint(op, position, "response", {**self._state(op, position), "response_ref": response_ref})
            need(response.status_code == 200, "COMMENT_PUT_NOT_200_RECONCILE_ONLY")
            response_value = _json(response.content)
            need(type(response_value) is dict, "PUT_RESPONSE_SHAPE_INVALID")
            # The PUT may omit GET-only expansions. Validate present identities,
            # link its actual comment, and prove all grade fields with the GET.
            for field in ("id", "assignment_id", "user_id", "attempt"):
                if field in response_value:
                    expected = item["record"]["submission_id"] if field == "id" else item["record"][field]
                    need(type(response_value[field]) is type(expected) and response_value[field] == expected, "PUT_RESPONSE_IDENTITY_MISMATCH")
            response_comments = {cid: {"id": c["id"], "author_id": c["author_id"], "comment": c["comment"]} for cid, c in comments(response_value).items()}
            after = await self._observe(m, item, authority=False)
            if before is None:
                raise GradebookError("FINAL_HTTP_GUARD_NOT_EXECUTED")
            outcome = self._outcome(before, after, response_comments)
            self._checkpoint(op, position, outcome, {**self._state(op, position), "readback": after, "retry_writes": False})
            self.ledger.mark(op, position, outcome)
        except (httpx.HTTPError, GradebookError, OSError) as exc:
            if not no_op:
                with self.ledger.connect() as db:
                    old = db.execute(f"SELECT phase,state_id FROM {self._checked_claim_table()} WHERE operation_id=? AND position=?", (op, position)).fetchone()
                need(old is not None, "PERMANENT_CLAIM_MISSING")
                prior = self.store.load("receipt", old["state_id"]) if old["state_id"] is not None else {}
                failure = {"exception_type": type(exc).__name__, "code": str(exc) if isinstance(exc, GradebookError) else "HTTP_TRANSPORT_ERROR" if isinstance(exc, httpx.HTTPError) else "PRIVATE_PIN_IO_ERROR", "phase_before": old["phase"], "transport_guard_completed": sent, "last_get_receipt": self._last_get_receipt, "retry_writes": False}
                receipt = self._checkpoint(op, position, "held", {**prior, "kind": prior.get("kind", "TEXT_COMMENT_PRETRANSPORT_HOLD"), "operation_id": op, "position": position, "failure": failure, "retry_writes": False})
                self._held_receipts.append(receipt)
                operation = self.ledger.operation(op)
                status = operation["items"][position]["status"]
                if status == "sending":
                    self.ledger.mark(op, position, "uncertain")
                elif status == "planned":
                    self.ledger.mark(op, position, "not_sent" if operation["status"] == "running" else "uncertain")
        finally:
            http.event_hooks["request"] = previous_hooks

    async def reconcile(self, plan_id: str, op: str) -> dict[str, Any]:
        """GET only. Neither expired authority nor uncertainty creates a new token."""
        with self.ledger.exclusive(op):
            p = self._plan(plan_id, op)
            m = self._manifest(lease=False)
            for position, reviewed in enumerate(p["items"]):
                status = self.ledger.operation(op)["items"][position]["status"]
                if status not in {"sending", "uncertain"}:
                    continue
                state = self._state(op, position)
                r = reviewed["record"]
                item = {"record": r, "body": reviewed["body"], "expected": _json(pinned(r["submission_ref"]))}
                try:
                    after = await self._observe(m, item, authority=False)
                    need("before" in state, "NO_DURABLE_SEND_CONTEXT_GET_ONLY")
                    outcome = self._outcome(state["before"], after, None)
                    self._checkpoint(op, position, outcome, {**state, "reconciliation": after, "retry_writes": False})
                    self.ledger.mark(op, position, outcome)
                except (httpx.HTTPError, GradebookError):
                    self._checkpoint(op, position, "uncertain", {**state, "retry_writes": False})
                    self.ledger.mark(op, position, "uncertain")
            return self.ledger.finish(op)
