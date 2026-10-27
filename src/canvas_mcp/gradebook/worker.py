"""One local, GET-only Canvas worker for the central gradebook refresh queue.

The queue carries no grades or credentials. Canonical planning and immutable
baselines remain local. A durable SENDING record precedes the sole grade batch;
uncertain outcomes can only be read back, never retransmitted.
"""

from __future__ import annotations

import copy
import fcntl
import json
import os
import re
import sqlite3
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .client import GradebookError
from .diagnostics import Diagnostics, failure_code
from .model import digest
from .store import Store

PREFIX = "sdm.gradebook.refresh."
KEYS = {
    k: PREFIX + k + ".v1"
    for k in ("request", "claim", "applied", "status", "heartbeat")
}
IDS = {
    "claim": 2026092901,
    "applied": 2026092902,
    "status": 2026092903,
    "heartbeat": 2026092904,
}
UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
STATES = {
    "CLAIMING",
    "CLAIMED",
    "PREPARED",
    "SENDING",
    "VERIFYING",
    "VERIFIED",
    "HELD",
    "UNCERTAIN",
}
REFRESH_MODES = {"FULL_SYNC", "GET_ONLY"}
MODE_MISMATCH = "Refresh mode differs from the original operation; no data was replaced."
GET_ACTION = "REFRESH_GET_BOTH"
GET_MODE_REQUIRED = "GET-only request requires a GET-only worker; no data was replaced."
INTENT_INVALID = "Refresh request intent is invalid; no claim was sent."
CLAIM_UNCERTAIN = "Refresh claim outcome requires reconciliation; no claim was retried."


def stamp() -> str:
    return datetime.now(UTC).isoformat()


def age(value: Any) -> float:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            raise ValueError
        return (datetime.now(UTC) - parsed).total_seconds()
    except (AttributeError, TypeError, ValueError):
        raise GradebookError("Invalid refresh timestamp.") from None


def queue_metadata(raw: dict[str, Any]) -> dict[str, dict[str, Any]]:
    found: dict[str, dict[str, Any]] = {}
    for item in raw.get("developerMetadata", []):
        key = item.get("metadataKey")
        if key not in KEYS.values():
            if item.get("metadataId") in IDS.values():
                raise GradebookError("Reserved refresh metadata ID is occupied.")
            continue
        kind = next(k for k, v in KEYS.items() if v == key)
        mid = item.get("metadataId")
        if (
            kind in found
            or not isinstance(mid, int)
            or isinstance(mid, bool)
            or mid <= 0
        ):
            raise GradebookError("Duplicate or invalid refresh queue metadata.")
        location = item.get("location", {})
        if (
            item.get("visibility") != "DOCUMENT"
            or not isinstance(location, dict)
            or location.get("spreadsheet") is not True
            or set(location) - {"spreadsheet", "locationType"}
            or location.get("locationType", "SPREADSHEET") != "SPREADSHEET"
            or (kind in IDS and mid != IDS[kind])
        ):
            raise GradebookError("Refresh queue metadata ownership differs.")
        text = item.get("metadataValue", "")
        if not isinstance(text, str) or len(text) > 2048:
            raise GradebookError("Refresh queue metadata is oversized.")
        try:
            value = json.loads(text)
        except (ValueError, TypeError):
            raise GradebookError("Invalid refresh queue JSON.") from None
        if (
            not isinstance(value, dict)
            or type(value.get("v")) is not int
            or value.get("v") != 1
        ):
            raise GradebookError("Unsupported refresh queue schema.")
        found[kind] = {"metadata_id": mid, "value": value}
    return found


def validate_request(
    value: dict[str, Any], workbook_id: str, *, fresh: bool = True
) -> None:
    if (
        set(value) != {"v", "id", "action", "created_at", "workbook_id"}
        or type(value["v"]) is not int
        or value["v"] != 1
        or type(value["action"]) is not str
        or value["action"] not in {"REFRESH_BOTH", GET_ACTION}
        or value["workbook_id"] != workbook_id
        or not isinstance(value["id"], str)
        or not UUID.fullmatch(value["id"])
    ):
        raise GradebookError("Refresh request does not match the configured operation.")
    request_age = age(value["created_at"])
    if fresh and not -30 <= request_age <= 600:
        raise GradebookError("Refresh request expired; no grade data was replaced.")


def metadata_create(kind: str, value: dict[str, Any]) -> dict[str, Any]:
    item: dict[str, Any] = {
        "metadataKey": KEYS[kind],
        "metadataValue": json.dumps(value, separators=(",", ":")),
        "visibility": "DOCUMENT",
        "location": {"spreadsheet": True},
    }
    if kind in IDS:
        item["metadataId"] = IDS[kind]
    return {"createDeveloperMetadata": {"developerMetadata": item}}


def metadata_update(kind: str, value: dict[str, Any]) -> dict[str, Any]:
    return {
        "updateDeveloperMetadata": {
            "dataFilters": [{"developerMetadataLookup": {"metadataId": IDS[kind]}}],
            "developerMetadata": {
                "metadataValue": json.dumps(value, separators=(",", ":"))
            },
            "fields": "metadataValue",
        }
    }


def metadata_delete(mid: int) -> dict[str, Any]:
    return {
        "deleteDeveloperMetadata": {
            "dataFilter": {"developerMetadataLookup": {"metadataId": mid}}
        }
    }


class RefreshJournalBusy(GradebookError):
    """Typed pre-admission contention; no journal lock was acquired."""


class RefreshJournal:
    """Private FULL-sync operation journal, separate from Canvas publication."""

    def __init__(self, root: Path, workbook_id: str) -> None:
        self.root = root / "refresh-worker"
        if self.root.is_symlink():
            raise GradebookError("Refresh journal directory must not be a symlink.")
        self.root.mkdir(mode=0o700, parents=True, exist_ok=True)
        os.chmod(self.root, 0o700)
        self.path = self.root / "operations.sqlite3"
        self.lock = self.root / "workbook.lock"
        self.workbook_id = workbook_id
        if self.path.is_symlink():
            raise GradebookError("Refresh journal must not be a symlink.")
        if not self.path.exists():
            fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            os.close(fd)
        os.chmod(self.path, 0o600)
        with self.connect() as db:
            db.execute(
                "CREATE TABLE IF NOT EXISTS operations (id TEXT PRIMARY KEY, workbook TEXT NOT NULL, status TEXT NOT NULL, payload TEXT NOT NULL, updated TEXT NOT NULL)"
            )

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

    @contextmanager
    def exclusive(self) -> Iterator[None]:
        if self.lock.is_symlink():
            raise GradebookError("Refresh lock must not be a symlink.")
        fd = os.open(self.lock, os.O_CREAT | os.O_RDWR, 0o600)
        try:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise RefreshJournalBusy(
                    "Another local refresh worker owns this workbook."
                ) from None
            yield
        finally:
            os.close(fd)

    def get(self, request_id: str) -> dict[str, Any] | None:
        with self.connect() as db:
            row = db.execute(
                "SELECT * FROM operations WHERE id=?", (request_id,)
            ).fetchone()
        if row is None:
            return None
        if row["workbook"] != self.workbook_id:
            raise GradebookError("Refresh journal belongs to another workbook.")
        return {
            "id": row["id"],
            "status": row["status"],
            "payload": json.loads(row["payload"]),
        }

    def unresolved(self) -> list[str]:
        with self.connect() as db:
            return [
                r[0]
                for r in db.execute(
                    "SELECT id FROM operations WHERE workbook=? AND status NOT IN ('VERIFIED','RELEASED')",
                    (self.workbook_id,),
                )
            ]

    def create(
        self, request: dict[str, Any], metadata_id: int, *,
        refresh_mode: str | None = None,
    ) -> dict[str, Any]:
        if refresh_mode is not None and (
            type(refresh_mode) is not str or refresh_mode not in REFRESH_MODES
        ):
            raise GradebookError("Refresh mode is unsupported.")
        payload = {
            "request": request,
            "metadata_id": metadata_id,
            "claim_nonce": str(uuid.uuid4()),
        }
        if refresh_mode is not None:
            payload.update(refresh_mode_schema=1, refresh_mode=refresh_mode)
        with self.connect() as db:
            db.execute(
                "INSERT OR IGNORE INTO operations VALUES(?,?,?,?,?)",
                (
                    request["id"],
                    self.workbook_id,
                    "CLAIMING",
                    json.dumps(payload),
                    stamp(),
                ),
            )
        operation = self.get(request["id"])
        assert operation is not None
        if (
            operation["payload"]["request"] != request
            or operation["payload"]["metadata_id"] != metadata_id
        ):
            raise GradebookError("Request ID was reused with different content.")
        if refresh_mode is not None and (
            type(operation["payload"].get("refresh_mode_schema")) is not int
            or operation["payload"].get("refresh_mode_schema") != 1
            or operation["payload"].get("refresh_mode") != refresh_mode
        ):
            raise GradebookError(MODE_MISMATCH)
        return operation

    def update(self, request_id: str, status: str, **patch: Any) -> dict[str, Any]:
        allowed = {
            "CLAIMING": {"CLAIMING", "CLAIMED", "HELD"},
            "CLAIMED": {"PREPARED", "HELD"},
            "PREPARED": {"PREPARED", "SENDING", "HELD"},
            "SENDING": {"VERIFYING", "UNCERTAIN"},
            "VERIFYING": {"VERIFIED", "UNCERTAIN"},
            "UNCERTAIN": {"VERIFYING", "UNCERTAIN"},
            "HELD": {"HELD", "RELEASED"},
            "VERIFIED": {"VERIFIED"},
            "RELEASED": set(),
        }
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT * FROM operations WHERE id=? AND workbook=?",
                (request_id, self.workbook_id),
            ).fetchone()
            if row is None or status not in allowed[row["status"]]:
                raise GradebookError("Invalid refresh state transition.")
            payload = json.loads(row["payload"])
            payload.update(patch)
            db.execute(
                "UPDATE operations SET status=?,payload=?,updated=? WHERE id=?",
                (status, json.dumps(payload), stamp(), request_id),
            )
        result = self.get(request_id)
        assert result is not None
        return result


class RefreshWorker:
    def __init__(
        self,
        google: Any,
        canvas: Any,
        store: Store,
        bindings: dict[str, Any],
        instance_id: str,
        diagnostics: Diagnostics | None = None,
        *,
        get_only: bool = False,
    ) -> None:
        if (
            set(bindings) != {"core", "advanced"}
            or not UUID.fullmatch(instance_id)
            or type(get_only) is not bool
        ):
            raise GradebookError(
                "Worker requires both configured courses and a stable instance ID."
            )
        workbook_ids = {b["spreadsheet_id"] for b in bindings.values()}
        if len(workbook_ids) != 1:
            raise GradebookError("Both courses must share one workbook.")
        self.workbook_id = workbook_ids.pop()
        self.google, self.canvas, self.store = google, canvas, store
        self.bindings, self.instance_id = copy.deepcopy(bindings), instance_id
        self.diagnostics = diagnostics or Diagnostics()
        self.get_only = get_only
        self.journal = RefreshJournal(store.root, self.workbook_id)

    async def _metadata(self) -> dict[str, dict[str, Any]]:
        raw = await self.google.metadata()
        if raw.get("spreadsheetId") != self.workbook_id:
            raise GradebookError("Google workbook identity differs.")
        return queue_metadata(raw)

    async def _status(
        self, request_id: str, state: str, summary: dict[str, Any] | None = None
    ) -> None:
        if state not in STATES:
            raise GradebookError("Unknown refresh status.")
        entries = await self._metadata()
        value = {
            "v": 1,
            "id": request_id,
            "workbook_id": self.workbook_id,
            "state": state,
            "updated_at": stamp(),
        }
        if summary is not None:
            value["summary"] = summary
        await self.google.batch(
            [
                (metadata_update if "status" in entries else metadata_create)(
                    "status", value
                )
            ]
        )

    async def heartbeat(self) -> dict[str, Any]:
        with self.journal.exclusive():
            entries = await self._metadata()
            blocked = bool(
                self.journal.unresolved()
                or "claim" in entries
                or "applied" in entries
                or "request" in entries
            )
            value = {
                "v": 1,
                "workbook_id": self.workbook_id,
                "state": "BUSY" if blocked else "READY",
                "refresh_mode": "GET_ONLY" if self.get_only else "FULL_SYNC",
                "updated_at": stamp(),
            }
            await self.google.batch(
                [
                    (metadata_update if "heartbeat" in entries else metadata_create)(
                        "heartbeat", value
                    )
                ]
            )
            return {"state": value["state"], "canvas_writes": 0}

    def _own_markers(self, entries: dict[str, Any], op: dict[str, Any]) -> None:
        rid = op["id"]
        request = entries.get("request")
        if request is None or request != {
            "metadata_id": op["payload"]["metadata_id"],
            "value": op["payload"]["request"],
        }:
            raise GradebookError("Queued request changed; reconciliation required.")
        claim = entries.get("claim", {}).get("value")
        if (
            claim is None
            or claim.get("id") != rid
            or claim.get("owner") != self.instance_id
            or claim.get("workbook_id") != self.workbook_id
            or claim.get("nonce") != op["payload"].get("claim_nonce")
        ):
            raise GradebookError("Refresh claim belongs to another worker or request.")
        applied = entries.get("applied", {}).get("value")
        if applied is not None and (
            applied.get("id") != rid or applied.get("workbook_id") != self.workbook_id
        ):
            raise GradebookError("Refresh applied marker differs.")

    def _operation_mode(self, op: dict[str, Any]) -> str:
        """Resolve retained intent; a restart cannot widen a pre-send scope.

        Versioned journal pins precede the first outbound claim. An older
        operation's existing immutable manifest owns its mode; a truly legacy
        operation without either pin or manifest retains FULL_SYNC semantics.
        """
        payload = op["payload"]
        pinned = None
        if "refresh_mode_schema" in payload:
            mode_value = payload.get("refresh_mode")
            if (
                type(payload["refresh_mode_schema"]) is not int
                or payload["refresh_mode_schema"] != 1
                or type(mode_value) is not str or mode_value not in REFRESH_MODES
            ):
                raise GradebookError("Refresh journal has an unsupported mode pin.")
            pinned = payload["refresh_mode"]
        if "manifest_id" in payload:
            manifest = self.store.load("refresh", payload["manifest_id"])
            mode = manifest.get("refresh_mode", "FULL_SYNC")
            if type(mode) is not str or mode not in REFRESH_MODES:
                raise GradebookError("Refresh manifest has an unsupported mode.")
            if pinned is not None and pinned != mode:
                raise GradebookError(MODE_MISMATCH)
            return str(mode)
        return str(pinned) if pinned is not None else "FULL_SYNC"

    def _trusted_request_intent(self, op: dict[str, Any]) -> None:
        """Admit only the helper's immutable, exact GET request intent."""
        payload = op["payload"]
        if (
            type(payload.get("request_intent_schema")) is not int
            or payload["request_intent_schema"] != 1
            or type(payload.get("refresh_mode_schema")) is not int
            or payload["refresh_mode_schema"] != 1
            or payload.get("refresh_mode") != "GET_ONLY"
            or payload.get("request_send_state") not in ("SENDING", "CONFIRMED")
            or type(payload.get("request_intent_receipt_id")) is not str
        ):
            raise GradebookError(INTENT_INVALID)
        receipt = self.store.load("receipt", payload["request_intent_receipt_id"])
        if (
            set(receipt) != {
                "request_intent_schema", "request", "metadata_id", "refresh_mode",
                "binding_digest", "workbook_id", "created_at", "canvas_writes",
            }
            or type(receipt.get("request_intent_schema")) is not int
            or receipt["request_intent_schema"] != 1
            or receipt.get("request") != payload["request"]
            or type(receipt.get("metadata_id")) is not int
            or receipt["metadata_id"] != payload["metadata_id"]
            or receipt.get("refresh_mode") != "GET_ONLY"
            or receipt.get("binding_digest") != digest(self.bindings)
            or receipt.get("workbook_id") != self.workbook_id
            or type(receipt.get("canvas_writes")) is not int
            or receipt["canvas_writes"] != 0
            or type(receipt.get("created_at")) is not str
        ):
            raise GradebookError(INTENT_INVALID)
        validate_request(receipt["request"], self.workbook_id, fresh=False)
        if receipt["request"]["action"] != GET_ACTION:
            raise GradebookError(INTENT_INVALID)
        if age(receipt["created_at"]) < -30:
            raise GradebookError(INTENT_INVALID)

    async def _claim_once(self, op: dict[str, Any]) -> dict[str, Any]:
        """Save the sole claim attempt before POST; lost claims never retry."""
        validate_request(op["payload"]["request"], self.workbook_id)
        if op["payload"].get("claim_send_attempted") is True:
            self.journal.update(
                op["id"], "HELD", failure_reason=CLAIM_UNCERTAIN,
                failure_code=failure_code(CLAIM_UNCERTAIN), failure_stage="claim",
            )
            raise GradebookError(CLAIM_UNCERTAIN)
        if "claim_send_attempted" in op["payload"] and op["payload"]["claim_send_attempted"] is not False:
            raise GradebookError(INTENT_INVALID)
        op = self.journal.update(op["id"], "CLAIMING", claim_send_attempted=True)
        claim = {
            "v": 1, "id": op["id"], "owner": self.instance_id,
            "nonce": op["payload"]["claim_nonce"],
            "workbook_id": self.workbook_id, "created_at": stamp(),
        }
        try:
            with self.diagnostics.stage("claim", op["id"]):
                await self.google.batch([metadata_create("claim", claim)])
        except Exception:
            entries = await self._metadata()
        else:
            entries = await self._metadata()
        if "claim" not in entries:
            self.journal.update(
                op["id"], "HELD", failure_reason=CLAIM_UNCERTAIN,
                failure_code=failure_code(CLAIM_UNCERTAIN), failure_stage="claim",
            )
            raise GradebookError(CLAIM_UNCERTAIN)
        self._own_markers(entries, op)
        self.diagnostics.last_failure_stage = None
        return self.journal.update(op["id"], "CLAIMED")

    async def step(self) -> dict[str, Any]:
        self.diagnostics.last_failure_stage = None
        with self.journal.exclusive():
            entries = await self._metadata()
            request_entry = entries.get("request")
            if request_entry is None:
                if (
                    self.journal.unresolved()
                    or "claim" in entries
                    or "applied" in entries
                ):
                    raise GradebookError("Unresolved refresh requires reconciliation.")
                return {"state": "IDLE", "canvas_writes": 0}
            request = request_entry["value"]
            validate_request(request, self.workbook_id, fresh=False)
            op = self.journal.get(request["id"])
            if op is not None and op["status"] == "RELEASED":
                raise GradebookError("Released refresh request arrived late; reconciliation is required.")
            if (
                request["action"] == GET_ACTION and not self.get_only
                and (op is None or op["status"] == "CLAIMING")
            ):
                # Leave a fresh GET-only request available for the correctly
                # composed worker. Post-send recovery still follows its manifest.
                raise GradebookError(GET_MODE_REQUIRED)
            if op is None:
                if (
                    self.journal.unresolved()
                    or "claim" in entries
                    or "applied" in entries
                ):
                    raise GradebookError("An earlier refresh must be reconciled first.")
                op = self.journal.create(
                    request, request_entry["metadata_id"],
                    refresh_mode="GET_ONLY" if self.get_only else "FULL_SYNC",
                )
                try:
                    validate_request(request, self.workbook_id)
                except GradebookError as exc:
                    self.journal.update(
                        op["id"],
                        "HELD",
                        failure_reason=str(exc),
                        failure_code=failure_code(exc),
                        failure_stage="claim",
                    )
                    await self._status(op["id"], "HELD")
                    return {"state": "HELD", "request_id": op["id"], "canvas_writes": 0}
                op = await self._claim_once(op)
                # Exact claim readback resolves any prior lost response.
                self.diagnostics.last_failure_stage = None
            else:
                self.journal.create(request, request_entry["metadata_id"])
                if op["status"] == "HELD":
                    return {"state": "HELD", "request_id": op["id"], "canvas_writes": 0}
                if op["status"] == "CLAIMING" and "claim" not in entries:
                    if op["payload"].get("claim_send_attempted") is True:
                        self.journal.update(
                            op["id"], "HELD", failure_reason=CLAIM_UNCERTAIN,
                            failure_code=failure_code(CLAIM_UNCERTAIN), failure_stage="claim",
                        )
                        raise GradebookError(CLAIM_UNCERTAIN)
                    if (
                        entries.get("request") != {
                            "metadata_id": op["payload"]["metadata_id"],
                            "value": op["payload"]["request"],
                        }
                        or "applied" in entries
                        or not self.get_only or self._operation_mode(op) != "GET_ONLY"
                    ):
                        raise GradebookError(INTENT_INVALID)
                    self._trusted_request_intent(op)
                    op = await self._claim_once(op)
                else:
                    self._own_markers(entries, op)
                    if op["status"] == "CLAIMING":
                        op = self.journal.update(op["id"], "CLAIMED")
            if op["status"] in {"SENDING", "VERIFYING", "UNCERTAIN", "VERIFIED"}:
                return await self._reconcile(op)
            if op["status"] == "HELD":
                return {"state": "HELD", "request_id": op["id"], "canvas_writes": 0}
            try:
                with self.diagnostics.stage("poll", op["id"]):
                    return await self._prepare_apply(op)
            except Exception as exc:
                latest = self.journal.get(op["id"])
                assert latest is not None
                state = (
                    "UNCERTAIN"
                    if latest["status"] in {"SENDING", "VERIFYING", "UNCERTAIN"}
                    else "HELD"
                )
                if latest["status"] != "VERIFIED":
                    self.journal.update(
                        op["id"],
                        state,
                        failure_reason=(
                            str(exc)
                            if isinstance(exc, GradebookError)
                            else "Unexpected local or transport failure; reconcile the durable operation."
                        ),
                        failure_code=failure_code(exc),
                        failure_stage=self.diagnostics.last_failure_stage,
                    )
                    try:
                        await self._status(op["id"], state)
                    except Exception:
                        pass
                raise GradebookError(
                    "Refresh stopped safely; inspect its durable status before continuing."
                ) from None

    async def _prepare_apply(self, op: dict[str, Any]) -> dict[str, Any]:
        from .native import fingerprint, validate_workbook
        from .service import prepare_refresh

        requested_mode = "GET_ONLY" if self.get_only else "FULL_SYNC"
        if op["payload"]["request"]["action"] == GET_ACTION and not self.get_only:
            raise GradebookError(GET_MODE_REQUIRED)
        if self._operation_mode(op) != requested_mode:
            raise GradebookError(MODE_MISMATCH)
        if self.get_only:
            from .get_only_refresh import (
                prepare_get_only_refresh,
                validate_get_workbook,
            )

            validate = validate_get_workbook
        else:
            validate = validate_workbook

        validate_request(op["payload"]["request"], self.workbook_id)
        await self._status(op["id"], "CLAIMED")
        with self.diagnostics.stage("initial_workbook", op["id"]):
            before = await self.google.read_workbook()
            views = validate(before, self.bindings)
        plans = {}
        for course in ("core", "advanced"):
            with self.diagnostics.stage("prepare_" + course, op["id"]):
                if self.get_only:
                    plans[course] = await prepare_get_only_refresh(
                        self.canvas, self.store, course, self.bindings[course], before
                    )
                else:
                    plans[course] = await prepare_refresh(
                        self.canvas,
                        self.store,
                        course,
                        self.bindings[course],
                        views[course],
                    )
        batch = []
        # Never shrink a sheet merely because the canonical layout is narrower.
        column_counts = {
            s["properties"]["sheetId"]: s["properties"]["gridProperties"]["columnCount"]
            for s in before["sheets"]
        }
        for plan in plans.values():
            requests = copy.deepcopy(plan["batch_update"]["requests"])
            for request in requests:
                update = request.get("updateSheetProperties")
                if update and "columnCount" in update["properties"].get(
                    "gridProperties", {}
                ):
                    props = update["properties"]
                    props["gridProperties"]["columnCount"] = max(
                        column_counts[props["sheetId"]],
                        props["gridProperties"]["columnCount"],
                    )
            plan["batch_update"]["requests"] = requests
            batch.extend(requests)
        marker = {
            "v": 1,
            "id": op["id"],
            "workbook_id": self.workbook_id,
            "binding_digest": digest(self.bindings),
        }
        batch.append(metadata_create("applied", marker))
        manifest = {
            "worker_schema": 1,
            "refresh_mode": "GET_ONLY" if self.get_only else "FULL_SYNC",
            "request": op["payload"]["request"],
            "binding_digest": digest(self.bindings),
            "before": before,
            "input_fingerprint": fingerprint(before),
            "plans": plans,
            "batch_update": batch,
        }
        manifest_id, _ = self.store.save("refresh", manifest)
        op = self.journal.update(
            op["id"], "PREPARED", manifest_id=manifest_id, batch_digest=digest(batch)
        )
        await self._status(op["id"], "PREPARED")
        with self.diagnostics.stage("fresh_workbook", op["id"]):
            fresh = await self.google.read_workbook()
            validate(fresh, self.bindings)
        self._own_markers(queue_metadata(fresh), op)
        if "applied" in queue_metadata(fresh):
            raise GradebookError(
                "An applied marker already exists; no second batch is permitted."
            )
        if fingerprint(fresh) != manifest["input_fingerprint"]:
            from .native import difference_categories

            # Diagnostics must not replace the original hold if projection fails.
            try:
                categories = difference_categories(before, fresh)
            except Exception:
                categories = []
            self.journal.update(op["id"], "PREPARED", difference_categories=categories)
            self.diagnostics.last_failure_stage = "fresh_workbook"
            self.diagnostics.emit(
                "difference", stage="fresh_workbook", difference_categories=categories
            )
            raise GradebookError("Workbook changed while preparing; refresh held.")
        if any(not 0 <= age(plan["created_at"]) <= 300 for plan in plans.values()):
            raise GradebookError("Refresh plan expired.")
        validate_request(op["payload"]["request"], self.workbook_id)
        self.journal.update(op["id"], "SENDING")
        # No await or outbound call between durable SENDING and this one batch.
        try:
            with self.diagnostics.stage("grade_batch", op["id"]):
                await self.google.send_preflighted_batch(batch)
        except Exception as exc:
            uncertain = self.journal.update(
                op["id"],
                "UNCERTAIN",
                failure_code=failure_code(exc),
                failure_stage="grade_batch",
            )
            return await self._reconcile(uncertain)
        verifying = self.journal.update(op["id"], "VERIFYING")
        return await self._reconcile(verifying)

    async def _reconcile(self, op: dict[str, Any]) -> dict[str, Any]:
        from .native import verify_native_output

        if not op or "manifest_id" not in op["payload"]:
            raise GradebookError("Refresh reconciliation artifact is unavailable.")
        manifest = self.store.load("refresh", op["payload"]["manifest_id"])
        mode = self._operation_mode(op)
        if mode == "GET_ONLY":
            from .get_only_refresh import verify_get_only_output
        elif mode != "FULL_SYNC":
            raise GradebookError("Refresh manifest has an unsupported mode.")
        if (
            manifest["binding_digest"] != digest(self.bindings)
            or digest(manifest["batch_update"]) != op["payload"]["batch_digest"]
        ):
            raise GradebookError(
                "Refresh binding or batch differs from its durable record."
            )
        if op["status"] == "VERIFIED":
            receipt = self.store.load("receipt", op["payload"]["receipt_id"])
            return await self._finalize(
                op, receipt["summary"], op["payload"]["receipt_id"]
            )
        with self.diagnostics.stage("readback", op["id"]):
            after = await self.google.read_workbook()
        entries = queue_metadata(after)
        self._own_markers(entries, op)
        expected_marker = json.loads(
            manifest["batch_update"][-1]["createDeveloperMetadata"][
                "developerMetadata"
            ]["metadataValue"]
        )
        if entries.get("applied", {}).get("value") != expected_marker:
            if op["status"] != "UNCERTAIN":
                self.journal.update(op["id"], "UNCERTAIN")
            await self._status(op["id"], "UNCERTAIN")
            return {
                "state": "UNCERTAIN",
                "request_id": op["id"],
                "canvas_writes": 0,
                "retry_writes": False,
            }
        if op["status"] not in {"VERIFYING", "VERIFIED"}:
            op = self.journal.update(op["id"], "VERIFYING")
        native_postcondition: dict[str, Any] = {}
        try:
            with self.diagnostics.stage("verify", op["id"]):
                if mode == "GET_ONLY":
                    verify_get_only_output(
                        manifest["before"], after, manifest["plans"],
                        self.store, self.bindings, postcondition_report=native_postcondition,
                    )
                else:
                    verify_native_output(
                        manifest["before"], after, manifest["plans"], self.store, self.bindings,
                    )
        except Exception as exc:
            if op["status"] != "VERIFIED":
                self.journal.update(
                    op["id"],
                    "UNCERTAIN",
                    failure_reason=(
                        str(exc)
                        if isinstance(exc, GradebookError)
                        else "Native output verification failed."
                    ),
                    failure_code=failure_code(exc),
                    failure_stage="verify",
                )
            await self._status(op["id"], "UNCERTAIN")
            return {
                "state": "UNCERTAIN",
                "request_id": op["id"],
                "canvas_writes": 0,
                "retry_writes": False,
            }
        summary = {}
        for course, plan in manifest["plans"].items():
            current = self.store.load("snapshot", plan["canvas_snapshot_id"])
            summary[course] = {
                "students": len(current["students"]),
                "assignments": len(current["assignments"]),
                "pending_edits": (
                    None if mode == "GET_ONLY" else len(plan["pending_edits"])
                ),
                **({"edit_preserved": True} if mode == "GET_ONLY" else {}),
            }
        receipt_id, _ = self.store.save(
            "receipt",
            {
                "worker_schema": 1,
                "request_id": op["id"],
                "manifest_id": op["payload"]["manifest_id"],
                "verified_at": stamp(),
                "summary": summary,
                "canvas_writes": 0,
                **({"native_postcondition": native_postcondition} if mode == "GET_ONLY" else {}),
            },
        )
        if op["status"] != "VERIFIED":
            op = self.journal.update(op["id"], "VERIFIED", receipt_id=receipt_id)
        return await self._finalize(op, summary, receipt_id)

    async def _finalize(
        self, op: dict[str, Any], summary: dict[str, Any], receipt_id: str
    ) -> dict[str, Any]:
        # Grade readback already succeeded durably. Cleanup never rewrites grades
        # and does not invalidate that earlier receipt if a teacher edits later.
        result = {
            "state": "VERIFIED",
            "request_id": op["id"],
            "receipt_id": receipt_id,
            "summary": summary,
            "canvas_writes": 0,
        }
        if op["payload"].get("finalized"):
            return result
        entries = await self._metadata()
        prior_status = entries.get("status", {}).get("value", {})
        # A crash or lost response may follow successful metadata-only cleanup.
        # Recover that outcome without issuing another write or touching edits.
        if not any(k in entries for k in ("request", "claim", "applied")):
            if (
                prior_status.get("id") == op["id"]
                and prior_status.get("workbook_id") == self.workbook_id
                and prior_status.get("state") == "VERIFIED"
                and prior_status.get("summary") == summary
            ):
                self.journal.update(op["id"], "VERIFIED", finalized=True)
                return result
            raise GradebookError(
                "Refresh receipt exists but finalization markers differ."
            )
        self._own_markers(entries, op)
        status = {
            "v": 1,
            "id": op["id"],
            "workbook_id": self.workbook_id,
            "state": "VERIFIED",
            "updated_at": stamp(),
            "summary": summary,
        }
        cleanup = [
            (metadata_update if "status" in entries else metadata_create)(
                "status", status
            )
        ]
        cleanup += [
            metadata_delete(entries[k]["metadata_id"])
            for k in ("request", "claim", "applied")
        ]
        try:
            await self.google.batch(cleanup)
        except Exception:
            # Read once to resolve a lost cleanup response. Never repeat the
            # grade batch; an unconfirmed cleanup retains its durable receipt.
            done = await self._metadata()
        else:
            done = await self._metadata()
        if (
            any(k in done for k in ("request", "claim", "applied"))
            or done.get("status", {}).get("value") != status
        ):
            raise GradebookError(
                "Refresh completed but queue finalization needs reconciliation."
            )
        self.journal.update(op["id"], "VERIFIED", finalized=True)
        return result

    async def release_held(self, request_id: str) -> dict[str, Any]:
        """Explicit operator recovery only before any possible grade batch.

        The journal retains the request and all private artifacts. No grade data
        is changed. SENDING/UNCERTAIN can never be released through this path.
        """
        with self.journal.exclusive():
            op = self.journal.get(request_id)
            if op is None or op["status"] not in {
                "CLAIMING",
                "CLAIMED",
                "PREPARED",
                "HELD",
            }:
                raise GradebookError(
                    "Only a held operation before SENDING can be released."
                )
            entries = await self._metadata()
            req = entries.get("request")
            if (
                op["status"] in {"CLAIMING", "HELD"}
                and not any(k in entries for k in ("request", "claim", "applied"))
                and op["payload"].get("request_intent_schema") == 1
            ):
                self._trusted_request_intent(op)
                if (
                    "manifest_id" in op["payload"]
                    or ("claim_send_attempted" in op["payload"]
                        and op["payload"]["claim_send_attempted"] is not False)
                ):
                    raise GradebookError("Request claim may have been attempted; release refused.")
                self.journal.update(
                    request_id, "HELD", release_requested=True,
                    release_reason="UNCLAIMED_REQUEST_INTENT_ABSENT_REMOTE",
                )
                self.journal.update(request_id, "RELEASED")
                return {"state": "RELEASED", "request_id": request_id,
                        "canvas_writes": 0, "grade_writes": 0}
            if op["payload"].get("release_requested") and not any(
                k in entries for k in ("request", "claim", "applied")
            ):
                self.journal.update(request_id, "RELEASED")
                return {
                    "state": "RELEASED",
                    "request_id": request_id,
                    "canvas_writes": 0,
                    "grade_writes": 0,
                }
            if (
                req
                != {
                    "metadata_id": op["payload"]["metadata_id"],
                    "value": op["payload"]["request"],
                }
                or "applied" in entries
            ):
                raise GradebookError(
                    "Request changed or may have been applied; release refused."
                )
            if "claim" in entries:
                self._own_markers(entries, op)
            op = self.journal.update(request_id, "HELD", release_requested=True)
            held = {
                "v": 1,
                "id": request_id,
                "workbook_id": self.workbook_id,
                "state": "HELD",
                "updated_at": stamp(),
            }
            deletes = [
                (metadata_update if "status" in entries else metadata_create)(
                    "status", held
                ),
                metadata_delete(req["metadata_id"]),
            ]
            if "claim" in entries:
                deletes.append(metadata_delete(IDS["claim"]))
            try:
                await self.google.batch(deletes)
            except Exception:
                after = await self._metadata()
            else:
                after = await self._metadata()
            if "request" in after or "claim" in after or "applied" in after:
                raise GradebookError("Release readback differs; retain the hold.")
            self.journal.update(request_id, "RELEASED")
            return {
                "state": "RELEASED",
                "request_id": request_id,
                "canvas_writes": 0,
                "grade_writes": 0,
            }

    async def reconcile(self, request_id: str) -> dict[str, Any]:
        """Reconcile one existing operation; never prepare or send grade data."""
        with self.journal.exclusive():
            op = self.journal.get(request_id)
            if op is None or op["status"] not in {
                "SENDING",
                "VERIFYING",
                "UNCERTAIN",
                "VERIFIED",
            }:
                raise GradebookError(
                    "Only a previously attempted refresh can be reconciled."
                )
            return await self._reconcile(op)
