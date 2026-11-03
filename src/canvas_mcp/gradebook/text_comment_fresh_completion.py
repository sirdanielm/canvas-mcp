"""Inactive owner-sealed fresh text completion; historical uncertainty is retained.

This is the existing TextV4 transport with a separate permanent descendant claim.
It cannot qualify a human instruction: the configuring owner must authenticate
the exact event and supply a synchronous current authority/source check.
"""

from __future__ import annotations

import hashlib
import inspect
import json
import math
import re
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any, cast

from . import text_comment_delivery_v4 as base

REVIEWED_CERTIFICATE_SHA256: str | None = None
CLAIMS = "text_comment_fresh_completions_v1"
DISPOSITIONS = "text_comment_completion_dispositions_v1"
ANCESTOR_TABLES = frozenset({"text_comment_deliveries_v1", "text_comment_recovery_vector_claims_v1"})
FIELDS = frozenset({
    "kind", "human_event_id", "original_human_evidence_ref", "origin", "actor_id",
    "manifest_sha256", "not_before", "expires", "text_only", "grade_write",
    "pdf_upload", "producer_history", "records", "ancestors",
})


def _json_pin(reference: dict[str, Any]) -> Any:
    def invalid(_: str) -> Any:
        raise base.GradebookError("COMPLETION_NONFINITE_JSON")
    return json.loads(base.pinned(reference), parse_constant=invalid)


def _finite(value: Any) -> bool:
    return type(value) in (int, float) and math.isfinite(value)


class FreshTextCommentCompletion(base.TextCommentDelivery):
    """Exactly three newly authorized appends, never an assertion of zero old sends."""

    def __init__(self, client: Any, store: Any, ledger: Any,
                 manifest_ref: dict[str, Any], *, canonical_root: Path, certificate_ref: dict[str, Any],
                 current_control_check: Callable[[], None]) -> None:
        base.need(callable(current_control_check)
                  and not inspect.iscoroutinefunction(current_control_check)
                  and not inspect.iscoroutinefunction(type(current_control_check).__call__),
                  "SYNCHRONOUS_CURRENT_COMPLETION_AUTHORITY_REQUIRED")
        super().__init__(client, store, ledger, dict(manifest_ref), canonical_root=canonical_root)
        self.certificate_ref = dict(certificate_ref)
        self._certificate_identity = dict(certificate_ref)
        self.current_control_check = current_control_check

    def _sealed_certificate(self) -> dict[str, Any]:
        base.need(self.certificate_ref == self._certificate_identity
                  and REVIEWED_CERTIFICATE_SHA256 is not None
                  and self.certificate_ref.get("sha256") == REVIEWED_CERTIFICATE_SHA256,
                  "COMPLETION_CERTIFICATE_UNREVIEWED")
        certificate = _json_pin(self.certificate_ref)
        base.need(type(certificate) is dict and set(certificate) == FIELDS
                  and certificate["kind"] == "FRESH_THREE_TEXT_COMMENT_COMPLETION_V1",
                  "COMPLETION_CERTIFICATE_INVALID")
        base.need(certificate["manifest_sha256"] == self.manifest_ref.get("sha256"),
                  "COMPLETION_MANIFEST_CHANGED")
        return cast(dict[str, Any], certificate)

    def _reviewed_manifest_sha256(self) -> str | None:
        return str(self._sealed_certificate()["manifest_sha256"])

    def _claim_table(self) -> str:
        return CLAIMS

    @staticmethod
    def _exists(db: Any, name: str) -> bool:
        return db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)).fetchone() is not None

    def _current(self) -> None:
        result = cast(Callable[[], Any], self.current_control_check)()
        if inspect.isawaitable(result):
            if inspect.iscoroutine(result):
                result.close()
            raise base.GradebookError("SYNCHRONOUS_CURRENT_COMPLETION_AUTHORITY_REQUIRED")
        base.need(result is None, "CURRENT_COMPLETION_AUTHORITY_HELD")

    def _validate(self, manifest: dict[str, Any], db: Any) -> dict[str, Any]:
        certificate = self._sealed_certificate()
        self._current()
        records = manifest["records"]
        expected = [{**base.target(r), "pin": r["pin"], "body_ref": r["body_ref"],
                     "source_ref": r["source_ref"]} for r in records]
        base.need(len(records) == 3 and certificate["records"] == expected
                  and certificate["origin"] == manifest["origin"]
                  and type(certificate["actor_id"]) is int
                  and certificate["actor_id"] == manifest["actor_id"],
                  "COMPLETION_TARGET_BODY_OR_SOURCE_CHANGED")
        base.need(type(certificate["human_event_id"]) is str
                  and re.fullmatch(r"[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}", certificate["human_event_id"]) is not None
                  and certificate["text_only"] is True and certificate["grade_write"] is False
                  and certificate["pdf_upload"] is False
                  and certificate["producer_history"] == "UNKNOWN_PRESERVED",
                  "FRESH_TEXT_ONLY_COMPLETION_AUTHORITY_REQUIRED")
        base.need(type(certificate["not_before"]) is int and type(certificate["expires"]) is int
                  and certificate["not_before"] == manifest["not_before"]
                  and certificate["expires"] == manifest["expires"]
                  and 0 < certificate["expires"] - certificate["not_before"] <= 600
                  and certificate["not_before"] <= time.time() < certificate["expires"],
                  "COMPLETION_AUTHORITY_EXPIRED")
        authority = _json_pin(manifest["authority_ref"])
        base.need(authority["original_human_evidence_ref"] == certificate["original_human_evidence_ref"],
                  "COMPLETION_HUMAN_EVENT_CHANGED")
        base.pinned(certificate["original_human_evidence_ref"])
        ancestors = certificate["ancestors"]
        base.need(type(ancestors) is list and len(ancestors) == 2
                  and {a.get("claim_table") for a in ancestors if type(a) is dict} == ANCESTOR_TABLES,
                  "COMPLETION_ANCESTORS_REQUIRED")
        wanted = {base.key(manifest["origin"], r) for r in records}
        by_target = {base.key(manifest["origin"], r): r for r in records}
        operations = set()
        for ancestor in ancestors:
            base.need(type(ancestor) is dict and set(ancestor) == {"claim_table", "snapshot_ref"},
                      "COMPLETION_ANCESTOR_INVALID")
            table = ancestor["claim_table"]
            base.need(table in ANCESTOR_TABLES and self._exists(db, table), "COMPLETION_ANCESTOR_INVALID")
            snapshot = _json_pin(ancestor["snapshot_ref"])
            base.need(type(snapshot) is dict and set(snapshot) == {"operation", "items", "claims"},
                      "COMPLETION_ANCESTOR_INVALID")
            old = snapshot["operation"]
            operation_id = old["id"]
            base.need(operation_id not in operations, "COMPLETION_ANCESTOR_INVALID")
            operations.add(operation_id)
            operation = db.execute("SELECT * FROM operations WHERE id=?", (operation_id,)).fetchone()
            items = [dict(x) for x in db.execute("SELECT * FROM items WHERE operation_id=? ORDER BY position", (operation_id,))]
            claims = [dict(x) for x in db.execute(f"SELECT * FROM {table} WHERE operation_id=? ORDER BY position", (operation_id,))]
            base.need(operation is not None and snapshot == {"operation": dict(operation), "items": items, "claims": claims}
                      and operation["status"] == "prepared" and _finite(operation["expires"])
                      and operation["expires"] <= certificate["not_before"]
                      and len(items) == len(claims) == 3
                      and {x["target"] for x in items} == wanted
                      and {x["target"] for x in claims} == wanted
                      and all(x["status"] == "planned" for x in items)
                      and all(x["phase"] == "prepared" and x["state_id"] is None for x in claims),
                      "COMPLETION_ANCESTOR_CHANGED_OR_NOT_QUIESCENT")
            plan = self.store.load("review", operation["plan_id"])
            base.need(plan["origin"] == manifest["origin"] and plan["actor_id"] == manifest["actor_id"]
                      and len(plan["items"]) == 3, "COMPLETION_ORIGINAL_PLAN_CHANGED")
            for item in plan["items"]:
                record = item["record"]
                current = by_target.get(base.key(manifest["origin"], record))
                base.need(current is not None and base.target(record) == base.target(current)
                          and record["pin"] == current["pin"]
                          and record["body_ref"]["sha256"] == current["body_ref"]["sha256"]
                          and hashlib.sha256(item["body"].encode()).hexdigest() == current["body_ref"]["sha256"],
                          "COMPLETION_ORIGINAL_BODY_CHANGED")
        for target in wanted:
            lock = db.execute("SELECT operation_id FROM target_locks WHERE target=?", (target,)).fetchone()
            if lock is None:
                continue
            base.need(self._exists(db, DISPOSITIONS) and self._exists(db, CLAIMS), "COMPLETION_FOREIGN_TARGET_LOCK")
            own = db.execute(f"SELECT operation_id FROM {DISPOSITIONS} WHERE human_event_id=? AND certificate_sha256=?",
                             (certificate["human_event_id"], self.certificate_ref["sha256"])).fetchone()
            claim = db.execute(f"SELECT operation_id FROM {CLAIMS} WHERE target=?", (target,)).fetchone()
            operation = db.execute("SELECT status FROM operations WHERE id=?", (lock["operation_id"],)).fetchone()
            base.need(own is not None and claim is not None and operation is not None
                      and own["operation_id"] == claim["operation_id"] == lock["operation_id"]
                      and operation["status"] == "running", "COMPLETION_FOREIGN_TARGET_LOCK")
        return certificate

    def _authority(self, manifest: dict[str, Any]) -> list[dict[str, Any]]:
        loaded = super()._authority(manifest)
        with self.ledger.connect() as db:
            self._validate(manifest, db)
        return loaded

    def _prepare_admission(self, db: Any, manifest: dict[str, Any]) -> None:
        certificate = self._validate(manifest, db)
        if self._exists(db, DISPOSITIONS):
            base.need(db.execute(f"SELECT 1 FROM {DISPOSITIONS} WHERE human_event_id=?",
                                 (certificate["human_event_id"],)).fetchone() is None,
                      "COMPLETION_EVENT_ALREADY_CLAIMED_RECONCILE_ONLY")

    def _append_disposition(self, db: Any, manifest: dict[str, Any], operation_id: str, plan_id: str) -> None:
        certificate = self._validate(manifest, db)
        self._record_disposition(db, certificate, operation_id, plan_id, "PREPARED")

    def _record_disposition(self, db: Any, certificate: dict[str, Any], operation_id: str | None,
                            plan_id: str, outcome: str) -> None:
        db.execute(f"CREATE TABLE IF NOT EXISTS {DISPOSITIONS} (human_event_id TEXT PRIMARY KEY, certificate_sha256 TEXT NOT NULL UNIQUE, operation_id TEXT UNIQUE, plan_id TEXT NOT NULL, manifest_sha256 TEXT NOT NULL, producer_history TEXT NOT NULL, outcome TEXT NOT NULL)")
        for action in ("UPDATE", "DELETE"):
            db.execute(f"CREATE TRIGGER IF NOT EXISTS completion_disposition_no_{action.lower()} BEFORE {action} ON {DISPOSITIONS} BEGIN SELECT RAISE(ABORT,'IMMUTABLE_COMPLETION_DISPOSITION'); END")
        db.execute(f"INSERT INTO {DISPOSITIONS} VALUES(?,?,?,?,?,?,?)", (certificate["human_event_id"], self.certificate_ref["sha256"], operation_id, plan_id, self.manifest_ref["sha256"], "UNKNOWN_PRESERVED", outcome))

    def _no_op_disposition(self, manifest: dict[str, Any], receipt_id: str) -> None:
        with self.ledger.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            self._prepare_admission(db, manifest)
            certificate = self._validate(manifest, db)
            self._record_disposition(db, certificate, None, receipt_id, "NO_OP")
