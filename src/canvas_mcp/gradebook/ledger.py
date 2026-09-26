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

    def prepare(self, plan_id: str, targets: list[str]) -> tuple[str, str]:
        if not targets or len(targets) > 25 or len(set(targets)) != len(targets):
            raise GradebookError("Push requires 1–25 distinct reviewed targets.")
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
                    now + 600,
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
        return {**dict(row), "items": [dict(item) for item in items]}

    def claim(self, operation_id: str, token: str) -> str:
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
            targets = db.execute(
                "SELECT target FROM items WHERE operation_id=?", (operation_id,)
            ).fetchall()
            for target in targets:
                if db.execute(
                    "SELECT 1 FROM target_locks WHERE target=?", (target[0],)
                ).fetchone():
                    raise GradebookError(
                        "A target has an unresolved push; reconcile it before another attempt."
                    )
                db.execute(
                    "INSERT INTO target_locks VALUES(?,?)", (target[0], operation_id)
                )
            db.execute(
                "UPDATE operations SET status='running' WHERE id=?", (operation_id,)
            )
        return str(row["plan_id"])

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
