"""Durable, single-use confirmations and per-target write exclusion.

A crash after recording 'sending' is uncertain. No worker resumes a PUT from
that state. Reconciliation reads Canvas and never retransmits the request.
"""

from __future__ import annotations

import fcntl
import hashlib
import os
import re
import secrets
import sqlite3
import time
from collections import Counter
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from .client import GradebookError


class Ledger:
    def __init__(self, root: Path) -> None:
        self.path = root / "push-ledger.sqlite3"
        if self.path.is_symlink():
            raise GradebookError("Push ledger must not be a symlink.")
        if not self.path.exists():
            fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            os.close(fd)
        os.chmod(self.path, 0o600)
        with self.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS operations (
                    id TEXT PRIMARY KEY, plan_id TEXT NOT NULL,
                    token_hash TEXT NOT NULL, expires REAL NOT NULL,
                    status TEXT NOT NULL, created REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS items (
                    operation_id TEXT NOT NULL, position INTEGER NOT NULL,
                    target TEXT NOT NULL, status TEXT NOT NULL,
                    PRIMARY KEY(operation_id, position)
                );
                CREATE TABLE IF NOT EXISTS target_locks (
                    target TEXT PRIMARY KEY, operation_id TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS comment_items (
                    operation_id TEXT NOT NULL, position INTEGER NOT NULL,
                    delivery_id TEXT NOT NULL, response_comment_id TEXT,
                    PRIMARY KEY(operation_id, position)
                );
                CREATE INDEX IF NOT EXISTS comment_delivery_lookup
                    ON comment_items(delivery_id);
                CREATE TABLE IF NOT EXISTS batch_authorizations (
                    id TEXT PRIMARY KEY, manifest_id TEXT NOT NULL,
                    token_hash TEXT NOT NULL, expires REAL NOT NULL,
                    status TEXT NOT NULL, created REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS batch_chunks (
                    batch_id TEXT NOT NULL, position INTEGER NOT NULL,
                    plan_id TEXT NOT NULL, operation_id TEXT,
                    PRIMARY KEY(batch_id, position)
                );
            """)

    @contextmanager
    def exclusive(self, operation_id: str) -> Iterator[None]:
        if not re.fullmatch("[a-f0-9]{32}", operation_id):
            raise GradebookError("Invalid operation reference.")
        path = self.path.parent / (".push-" + operation_id + ".lock")
        if path.is_symlink():
            raise GradebookError("Operation lock must not be a symlink.")
        fd = os.open(path, os.O_CREAT | os.O_RDWR, 0o600)
        try:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise GradebookError("This push operation is already running.") from exc
            yield
        finally:
            os.close(fd)

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        db = sqlite3.connect(self.path, timeout=5)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA synchronous=FULL")
        try:
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def prepare(
        self,
        plan_id: str,
        targets: list[str],
        *,
        comment_delivery_ids: list[str] | None = None,
        comment_approval_seconds: int = 600,
    ) -> tuple[str, str]:
        if (
            type(comment_approval_seconds) is not int
            or not 600 <= comment_approval_seconds <= 1800
            or (comment_delivery_ids is None and comment_approval_seconds != 600)
        ):
            raise GradebookError(
                "Comment approval window must be 600–1800 seconds; "
                "score windows remain 600 seconds."
            )
        if not targets or len(targets) > 25 or len(set(targets)) != len(targets):
            raise GradebookError("Push requires 1–25 distinct reviewed targets.")
        if comment_delivery_ids is not None and (
            len(comment_delivery_ids) != len(targets)
            or len(set(comment_delivery_ids)) != len(targets)
            or any(
                type(v) is not str or re.fullmatch(r"[a-f0-9]{64}", v) is None
                for v in comment_delivery_ids
            )
        ):
            raise GradebookError("Invalid reviewed comment delivery identities.")
        operation_id = secrets.token_hex(16)
        token = secrets.token_urlsafe(32)
        now = time.time()
        with self.connect() as db:
            db.execute(
                "INSERT INTO operations VALUES(?,?,?,?,?,?)",
                (
                    operation_id,
                    plan_id,
                    hashlib.sha256(token.encode()).hexdigest(),
                    now + comment_approval_seconds,
                    "prepared",
                    now,
                ),
            )
            db.executemany(
                "INSERT INTO items VALUES(?,?,?,?)",
                [
                    (operation_id, i, target, "planned")
                    for i, target in enumerate(targets)
                ],
            )
            if comment_delivery_ids is not None:
                db.executemany(
                    "INSERT INTO comment_items VALUES(?,?,?,NULL)",
                    [(operation_id, i, v) for i, v in enumerate(comment_delivery_ids)],
                )
        return operation_id, token

    def operation(self, operation_id: str) -> dict[str, Any]:
        if not re.fullmatch("[a-f0-9]{32}", operation_id):
            raise GradebookError("Invalid push operation reference.")
        with self.connect() as db:
            row = db.execute(
                "SELECT * FROM operations WHERE id=?", (operation_id,)
            ).fetchone()
            if row is None:
                raise GradebookError("Push operation is unavailable.")
            items = db.execute(
                "SELECT position,target,status FROM items WHERE operation_id=? ORDER BY position",
                (operation_id,),
            ).fetchall()
            comments = {
                item["position"]: dict(item)
                for item in db.execute(
                    "SELECT position,delivery_id,response_comment_id FROM comment_items WHERE operation_id=?",
                    (operation_id,),
                )
            }
        return {
            **dict(row),
            "items": [
                {**dict(item), **comments.get(item["position"], {})} for item in items
            ],
        }

    def claim(
        self, operation_id: str, token: str, *, independent_targets: bool = False
    ) -> str:
        # BEGIN IMMEDIATE serializes token consumption across server processes.
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT * FROM operations WHERE id=?", (operation_id,)
            ).fetchone()
            if row is None or not secrets.compare_digest(
                row["token_hash"], hashlib.sha256(token.encode()).hexdigest()
            ):
                raise GradebookError("Push confirmation does not match this operation.")
            if row["status"] != "prepared":
                raise GradebookError(
                    "Confirmation already consumed; inspect operation status. Do not retry."
                )
            if time.time() > row["expires"]:
                raise GradebookError(
                    "Push confirmation expired; prepare a fresh review."
                )
            if db.execute(
                """SELECT 1 FROM comment_items pending
                JOIN comment_items prior ON prior.delivery_id=pending.delivery_id
                JOIN items sent ON sent.operation_id=prior.operation_id AND sent.position=prior.position
                WHERE pending.operation_id=?
                AND sent.status IN ('sending','uncertain','verified','observed_applied')""",
                (operation_id,),
            ).fetchone():
                raise GradebookError(
                    "This exact comment was sent or may have been sent; readback only."
                )
            targets = db.execute(
                "SELECT position,target FROM items WHERE operation_id=?",
                (operation_id,),
            ).fetchall()
            for target in targets:
                if db.execute(
                    "SELECT 1 FROM target_locks WHERE target=?", (target["target"],)
                ).fetchone():
                    if independent_targets:
                        db.execute(
                            "UPDATE items SET status='conflict' WHERE operation_id=? AND position=?",
                            (operation_id, target["position"]),
                        )
                        continue
                    raise GradebookError(
                        "A target has an unresolved push; reconcile it before another attempt."
                    )
                db.execute(
                    "INSERT INTO target_locks VALUES(?,?)",
                    (target["target"], operation_id),
                )
            db.execute(
                "UPDATE operations SET status='running' WHERE id=?", (operation_id,)
            )
        return str(row["plan_id"])

    def prepare_batch(
        self, manifest_id: str, plan_ids: list[str], approval_seconds: int
    ) -> tuple[str, str]:
        """Bind one review to immutable child plans, without authorizing a write."""
        if (
            type(approval_seconds) is not int
            or not 600 <= approval_seconds <= 28800
            or not re.fullmatch(r"[a-f0-9]{64}", manifest_id)
            or not 1 <= len(plan_ids) <= 1000
            or len(set(plan_ids)) != len(plan_ids)
            or any(not re.fullmatch(r"[a-f0-9]{64}", p) for p in plan_ids)
        ):
            raise GradebookError(
                "Invalid immutable batch or approval window (600–28800 seconds)."
            )
        batch_id, token = secrets.token_hex(16), secrets.token_urlsafe(32)
        now = time.time()
        with self.connect() as db:
            db.execute(
                "INSERT INTO batch_authorizations VALUES(?,?,?,?,?,?)",
                (
                    batch_id,
                    manifest_id,
                    hashlib.sha256(token.encode()).hexdigest(),
                    now + approval_seconds,
                    "prepared",
                    now,
                ),
            )
            db.executemany(
                "INSERT INTO batch_chunks VALUES(?,?,?,NULL)",
                [(batch_id, i, plan) for i, plan in enumerate(plan_ids)],
            )
        return batch_id, token

    def batch(self, batch_id: str) -> dict[str, Any]:
        if not re.fullmatch(r"[a-f0-9]{32}", batch_id):
            raise GradebookError("Invalid batch reference.")
        with self.connect() as db:
            row = db.execute(
                "SELECT * FROM batch_authorizations WHERE id=?", (batch_id,)
            ).fetchone()
            if row is None:
                raise GradebookError("Batch authorization is unavailable.")
            chunks = db.execute(
                "SELECT position,plan_id,operation_id FROM batch_chunks WHERE batch_id=? ORDER BY position",
                (batch_id,),
            ).fetchall()
        return {**dict(row), "chunks": [dict(c) for c in chunks]}

    def authorize_batch(self, batch_id: str, token: str) -> None:
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT * FROM batch_authorizations WHERE id=?", (batch_id,)
            ).fetchone()
            if row is None or not secrets.compare_digest(
                row["token_hash"], hashlib.sha256(token.encode()).hexdigest()
            ):
                raise GradebookError(
                    "Batch confirmation does not match the reviewed manifest."
                )
            if row["status"] != "prepared":
                raise GradebookError(
                    "Batch confirmation already consumed or revoked; inspect status."
                )
            if time.time() > row["expires"]:
                raise GradebookError(
                    "Batch authorization expired; no write authorized."
                )
            db.execute(
                "UPDATE batch_authorizations SET status='authorized' WHERE id=?",
                (batch_id,),
            )

    def require_batch(self, batch_id: str, manifest_id: str) -> dict[str, Any]:
        batch = self.batch(batch_id)
        if batch["manifest_id"] != manifest_id or batch["status"] != "authorized":
            raise GradebookError(
                "Batch is not authorized for this exact manifest or was revoked."
            )
        if time.time() > batch["expires"]:
            raise GradebookError(
                "Batch authorization expired; remaining targets are held."
            )
        return batch

    def revoke_batch(self, batch_id: str) -> None:
        self.batch(batch_id)
        with self.connect() as db:
            db.execute(
                "UPDATE batch_authorizations SET status='revoked' WHERE id=?",
                (batch_id,),
            )

    def attach_batch_chunk(
        self, batch_id: str, manifest_id: str, position: int, operation_id: str
    ) -> None:
        """Attach only an unused operation for the pre-reviewed child plan."""
        self.require_batch(batch_id, manifest_id)
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            batch = db.execute(
                "SELECT * FROM batch_authorizations WHERE id=?", (batch_id,)
            ).fetchone()
            chunk = db.execute(
                "SELECT * FROM batch_chunks WHERE batch_id=? AND position=?",
                (batch_id, position),
            ).fetchone()
            op = db.execute(
                "SELECT * FROM operations WHERE id=?", (operation_id,)
            ).fetchone()
            if (
                batch is None
                or batch["status"] != "authorized"
                or time.time() > batch["expires"]
                or chunk is None
                or chunk["operation_id"] is not None
                or op is None
                or op["status"] != "prepared"
                or op["plan_id"] != chunk["plan_id"]
            ):
                raise GradebookError(
                    "Batch chunk changed or is already dispatched; inspect status."
                )
            db.execute(
                "UPDATE batch_chunks SET operation_id=? WHERE batch_id=? AND position=?",
                (operation_id, batch_id, position),
            )

    def unstarted_chunk_token(
        self, batch_id: str, manifest_id: str, operation_id: str
    ) -> str:
        """Recover only a never-claimed dispatch after restart; never a possible send."""
        self.require_batch(batch_id, manifest_id)
        token = secrets.token_urlsafe(32)
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT o.status,b.status AS grant_status,b.expires FROM operations o "
                "JOIN batch_chunks c ON c.operation_id=o.id "
                "JOIN batch_authorizations b ON b.id=c.batch_id "
                "WHERE o.id=? AND b.id=? AND b.manifest_id=?",
                (operation_id, batch_id, manifest_id),
            ).fetchone()
            if (
                row is None
                or row["status"] != "prepared"
                or row["grant_status"] != "authorized"
                or time.time() > row["expires"]
            ):
                raise GradebookError(
                    "Only an unstarted authorized chunk may obtain a dispatch token."
                )
            db.execute(
                "UPDATE operations SET token_hash=?,expires=? WHERE id=?",
                (
                    hashlib.sha256(token.encode()).hexdigest(),
                    min(row["expires"], time.time() + 600),
                    operation_id,
                ),
            )
        return token

    def save_comment_response(
        self, operation_id: str, position: int, comment_id: str
    ) -> None:
        """Retain the response-linked ID before GET readback; never replace it."""
        if (
            type(comment_id) is not str
            or re.fullmatch(r"[1-9][0-9]*", comment_id) is None
        ):
            raise GradebookError("Invalid response comment identity.")
        with self.connect() as db:
            row = db.execute(
                """SELECT c.response_comment_id,i.status FROM comment_items c
                JOIN items i ON i.operation_id=c.operation_id AND i.position=c.position
                WHERE c.operation_id=? AND c.position=?""",
                (operation_id, position),
            ).fetchone()
            if (
                row is None
                or row["status"] != "sending"
                or row["response_comment_id"] is not None
            ):
                raise GradebookError("Comment response checkpoint is unavailable.")
            db.execute(
                "UPDATE comment_items SET response_comment_id=? WHERE operation_id=? AND position=?",
                (comment_id, operation_id, position),
            )

    def mark(self, operation_id: str, position: int, status: str) -> None:
        allowed = {
            "sending",
            "verified",
            "observed_applied",
            "uncertain",
            "conflict",
            "rejected",
            "not_sent",
        }
        if status not in allowed:
            raise GradebookError("Invalid push checkpoint.")
        with self.connect() as db:
            row = db.execute(
                "SELECT target,status FROM items WHERE operation_id=? AND position=?",
                (operation_id, position),
            ).fetchone()
            if row is None:
                raise GradebookError("Push item is unavailable.")
            if status == "sending" and row["status"] != "planned":
                raise GradebookError("A submission request cannot be sent twice.")
            if row["status"] in {
                "verified",
                "observed_applied",
                "not_sent",
                "rejected",
                "conflict",
            }:
                if row["status"] == status:
                    return
                raise GradebookError("A completed push checkpoint cannot be rewritten.")
            db.execute(
                "UPDATE items SET status=? WHERE operation_id=? AND position=?",
                (status, operation_id, position),
            )
            if status in {
                "verified",
                "observed_applied",
                "conflict",
                "rejected",
                "not_sent",
            }:
                db.execute(
                    "DELETE FROM target_locks WHERE target=? AND operation_id=?",
                    (row["target"], operation_id),
                )

    def finish(self, operation_id: str) -> dict[str, Any]:
        operation = self.operation(operation_id)
        if operation["status"] == "prepared":
            return self.summary(operation_id)
        for item in operation["items"]:
            if item["status"] == "planned":
                self.mark(operation_id, item["position"], "not_sent")
        counts = Counter(i["status"] for i in self.operation(operation_id)["items"])
        state = (
            "uncertain"
            if counts["sending"] or counts["uncertain"]
            else (
                "verified"
                if sum(counts.values())
                == counts["verified"] + counts["observed_applied"]
                else "stopped"
            )
        )
        with self.connect() as db:
            db.execute(
                "UPDATE operations SET status=? WHERE id=?", (state, operation_id)
            )
        return self.summary(operation_id)

    def summary(self, operation_id: str) -> dict[str, Any]:
        operation = self.operation(operation_id)
        return {
            "operation_id": operation_id,
            "status": operation["status"],
            "counts": dict(Counter(item["status"] for item in operation["items"])),
            "retry_writes": False,
        }
