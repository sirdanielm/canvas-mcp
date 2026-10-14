"""Queue one explicit GET-only refresh; no Canvas or grade-cell transport."""

from __future__ import annotations

import asyncio
import secrets
import uuid
from collections.abc import AsyncIterator
from contextlib import ExitStack, asynccontextmanager
from time import monotonic
from typing import Any

from .client import GradebookError
from .model import digest, identifier
from .store import Store
from .worker import (
    GET_ACTION,
    IDS,
    UUID,
    RefreshJournal,
    RefreshJournalBusy,
    age,
    metadata_create,
    queue_metadata,
    stamp,
    validate_request,
)

REQUEST_UNCERTAIN = (
    "GET refresh request readback is uncertain; do not enqueue another request."
)
MAX_METADATA_ID = 2_147_483_647
LOCK_WAIT_SECONDS = 30.0
LOCK_POLL_SECONDS = 0.25
LOCK_BUSY = "Workbook lock stayed busy; no request was created or sent. Check local status."
_admission_pause = asyncio.sleep


@asynccontextmanager
async def _request_admission(journal: RefreshJournal) -> AsyncIterator[None]:
    """Wait only for typed flock contention, entirely before the request body."""
    deadline = monotonic() + LOCK_WAIT_SECONDS
    with ExitStack() as held:
        while True:
            try:
                held.enter_context(journal.exclusive())
            except RefreshJournalBusy:
                remaining = deadline - monotonic()
                if remaining <= 0:
                    raise GradebookError(LOCK_BUSY) from None
                await _admission_pause(min(LOCK_POLL_SECONDS, remaining))
                if monotonic() >= deadline:
                    raise GradebookError(LOCK_BUSY) from None
            else:
                break
        yield


def _identity(google: Any, bindings: dict[str, Any], instance_id: str) -> str:
    if (
        not isinstance(bindings, dict)
        or set(bindings) != {"core", "advanced"}
        or not isinstance(instance_id, str)
        or not UUID.fullmatch(instance_id)
    ):
        raise GradebookError("GET refresh request configuration differs.")
    books, courses, sheets = set(), set(), set()
    for binding in bindings.values():
        if (
            not isinstance(binding, dict)
            or not isinstance(binding.get("spreadsheet_id"), str)
            or not binding["spreadsheet_id"]
            or set(binding.get("sheets", {})) != {"Canvas", "Working", "_Sync"}
            or set(binding.get("tab_names", {})) != {"Canvas", "Working", "_Sync"}
        ):
            raise GradebookError("GET refresh request configuration differs.")
        books.add(binding["spreadsheet_id"])
        courses.add(identifier(binding.get("course_id")))
        for sid in binding["sheets"].values():
            if type(sid) is not int or sid < 0 or sid in sheets:
                raise GradebookError("GET refresh request sheet identities differ.")
            sheets.add(sid)
    if len(books) != 1 or len(courses) != 2:
        raise GradebookError(
            "GET refresh request course or workbook identities differ."
        )
    workbook_id = next(iter(books))
    if google.workbook_id != workbook_id:
        raise GradebookError("GET refresh request workbook identity differs.")
    return str(workbook_id)


def _metadata(
    raw: dict[str, Any], workbook_id: str, bindings: dict[str, Any]
) -> dict[str, Any]:
    if raw.get("spreadsheetId") != workbook_id:
        raise GradebookError("GET refresh request workbook identity differs.")
    properties = {
        sheet.get("properties", {}).get("sheetId"): sheet.get("properties", {})
        for sheet in raw.get("sheets", [])
    }
    for binding in bindings.values():
        for role, sid in binding["sheets"].items():
            if properties.get(sid, {}).get("title") != binding["tab_names"][role]:
                raise GradebookError("GET refresh request sheet identities differ.")
    return queue_metadata(raw)


def _metadata_id(raw: dict[str, Any]) -> int:
    occupied = set(IDS.values()) | {
        item.get("metadataId") for item in raw.get("developerMetadata", [])
    }
    for _ in range(16):
        candidate = 1 + secrets.randbelow(MAX_METADATA_ID)
        if candidate not in occupied:
            return candidate
    raise GradebookError("GET refresh request metadata identity is unavailable.")


async def request_get_refresh(
    google: Any, store: Store, bindings: dict[str, Any], instance_id: str
) -> dict[str, Any]:
    """Persist intent, send one metadata batch, and verify its exact readback.

    Repeated calls deduplicate an existing unclaimed GET-only request. A possible
    unconfirmed send becomes a durable HELD operation; no automatic resend exists.
    """
    workbook_id = _identity(google, bindings, instance_id)
    journal = RefreshJournal(store.root, workbook_id)
    async with _request_admission(journal):
        unresolved = journal.unresolved()
        raw = await google.metadata()
        entries = _metadata(raw, workbook_id, bindings)
        if "request" in entries:
            existing = entries["request"]["value"]
            validate_request(existing, workbook_id, fresh=False)
            if existing["action"] != GET_ACTION:
                raise GradebookError("Existing refresh request has a different mode.")
            if unresolved:
                operation = journal.get(existing["id"])
                if (
                    unresolved != [existing["id"]]
                    or operation is None
                    or operation["status"] in {"HELD", "UNCERTAIN"}
                    or type(operation["payload"].get("refresh_mode_schema")) is not int
                    or operation["payload"].get("refresh_mode_schema") != 1
                    or operation["payload"].get("refresh_mode") != "GET_ONLY"
                    or operation["payload"].get("request") != existing
                    or operation["payload"].get("metadata_id")
                    != entries["request"]["metadata_id"]
                ):
                    raise GradebookError("Unresolved refresh requires reconciliation.")
                if "claim" in entries:
                    claim = entries["claim"]["value"]
                    if (
                        claim.get("id") != existing["id"]
                        or claim.get("workbook_id") != workbook_id
                        or claim.get("owner") != instance_id
                        or claim.get("nonce") != operation["payload"].get("claim_nonce")
                    ):
                        raise GradebookError(
                            "Existing refresh markers require reconciliation."
                        )
            elif "claim" in entries or "applied" in entries:
                raise GradebookError("Existing refresh markers require reconciliation.")
            return {
                "state": "ALREADY_QUEUED",
                "request_id": existing["id"],
                "canvas_writes": 0,
                "grade_writes": 0,
                "sheets_writes": 0,
                "retry_writes": False,
            }
        if unresolved:
            raise GradebookError("Unresolved refresh requires reconciliation.")
        if "claim" in entries or "applied" in entries:
            raise GradebookError("Existing refresh markers require reconciliation.")
        status = entries.get("status", {}).get("value")
        if status is not None and (
            status.get("workbook_id") != workbook_id
            or status.get("state") not in {"VERIFIED", "HELD"}
        ):
            raise GradebookError("Existing refresh status requires reconciliation.")
        heartbeat = entries.get("heartbeat", {}).get("value", {})
        if (
            heartbeat.get("workbook_id") != workbook_id
            or heartbeat.get("state") != "READY"
            or heartbeat.get("refresh_mode") != "GET_ONLY"
            or not -30 <= age(heartbeat.get("updated_at")) <= 90
        ):
            raise GradebookError(
                "A fresh READY GET-only worker is required before requesting refresh."
            )
        request: dict[str, Any] = {
            "v": 1,
            "id": str(uuid.uuid4()),
            "action": GET_ACTION,
            "created_at": stamp(),
            "workbook_id": workbook_id,
        }
        validate_request(request, workbook_id)
        mid = _metadata_id(raw)
        intent_id, _ = store.save(
            "receipt",
            {
                "request_intent_schema": 1,
                "refresh_mode": "GET_ONLY",
                "request": request,
                "metadata_id": mid,
                "binding_digest": digest(bindings),
                "workbook_id": workbook_id,
                "created_at": stamp(),
                "canvas_writes": 0,
            },
        )
        # Persist a blocking row before the sole outbound request POST. A hard
        # interruption retains this intent; only exact observed metadata can
        # permit the worker's first claim, never a queue resend.
        journal.create(request, mid, refresh_mode="GET_ONLY")
        journal.update(
            request["id"],
            "CLAIMING",
            request_intent_schema=1,
            request_intent_receipt_id=intent_id,
            request_send_state="SENDING",
        )
        batch = metadata_create("request", request)
        batch["createDeveloperMetadata"]["developerMetadata"]["metadataId"] = mid
        cancelled = False
        try:
            await google.batch([batch])
        except asyncio.CancelledError:
            cancelled = True
        except Exception:
            pass  # A lost POST response can only be resolved by metadata GET.
        confirmed = False
        try:
            after = _metadata(await google.metadata(), workbook_id, bindings)
            confirmed = after.get("request") == {"metadata_id": mid, "value": request}
        except asyncio.CancelledError:
            cancelled = True
        except Exception:
            pass
        if not confirmed:
            journal.update(
                request["id"],
                "HELD",
                failure_reason=REQUEST_UNCERTAIN,
                failure_code="request_uncertain",
                request_send_state="UNCERTAIN",
            )
        else:
            journal.update(request["id"], "CLAIMING", request_send_state="CONFIRMED")
        if cancelled:
            raise asyncio.CancelledError
        return {
            "state": "QUEUED" if confirmed else "REQUEST_UNCERTAIN",
            "request_id": request["id"],
            "intent_receipt_id": intent_id,
            "canvas_writes": 0,
            "grade_writes": 0,
            "sheets_write_attempts": 1,
            "queue_write_verified": confirmed,
            "retry_writes": False,
        }
