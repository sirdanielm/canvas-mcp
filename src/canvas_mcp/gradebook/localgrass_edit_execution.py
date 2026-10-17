"""Dormant one-shot native execution using existing LocalGrAss receipt storage.

No transport is constructed or registered. The existing application supplies its
native reader/writer, explicit enablement and shared staging output root. The
existing participation-stage lock and plan/receipt layout preserve mutual owner
exclusion and unresolved target history. No new queue, ledger or service exists.
"""

from __future__ import annotations

import asyncio
import copy
import inspect
import math
import re
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .client import GradebookError
from .localgrass_teacher_edit import CONTRACT, LocalGrAssEditConnection
from .model import digest


def _need(value: Any, code: str) -> None:
    if not value:
        raise GradebookError(code)


async def _invoke(callback: Callable[..., Any], *args: Any) -> Any:
    result = callback(*args)
    return await result if inspect.isawaitable(result) else result


def _targets(plan: dict[str, Any]) -> tuple[str, str, set[str]]:
    binding = plan.get("binding", {})
    _need(
        type(binding) is dict
        and type(binding.get("spreadsheet_id")) is str
        and len(binding["spreadsheet_id"]) > 5
        and type(binding.get("course_id")) in (str, int)
        and re.fullmatch(r"[0-9]+", str(binding["course_id"])) is not None
        and int(binding["course_id"]) > 0
        and type(plan.get("items")) is list
        and len(plan["items"]) <= 10_000
        and all(
            type(item) is dict
            and type(item.get("key")) is str
            and re.fullmatch(r"[0-9]+:[0-9]+", item["key"]) is not None
            and all(int(v) > 0 for v in item["key"].split(":"))
            for item in plan["items"]
        ),
        "PRIOR_OPERATION_SCOPE_UNKNOWN",
    )
    return (
        str(binding.get("spreadsheet_id")),
        str(binding.get("course_id")),
        {item["key"] for item in plan["items"]},
    )


async def _execute_local_edit_once(
    connection: LocalGrAssEditConnection,
    plan: dict[str, Any],
    *,
    expected_plan_sha256: str,
    output_root: Path,
    read_context: Callable[[], Any],
    write_requests: Callable[..., Any],
    enabled: bool = False,
    reconcile_only: bool = False,
) -> dict[str, Any]:
    """Use one existing native batch or historical readback, never auto-retry.

    read_context supplies raw/current/pin_binding from existing owners. Callbacks
    are trusted application configuration, never MCP arguments. enabled is an
    additional mechanical gate; it cannot create user authorization. Every write
    needs an idle workbook and current separately authorized local staging scope.
    """
    _need(
        isinstance(connection, LocalGrAssEditConnection),
        "AUTHENTICATED_CONNECTION_REQUIRED",
    )
    connection.validate_plan(plan, expected_plan_sha256=expected_plan_sha256)
    _need(
        type(enabled) is bool and type(reconcile_only) is bool,
        "EXPLICIT_LOCAL_EXECUTION_MODE",
    )
    _need(
        all(callable(c) for c in (read_context, write_requests)),
        "EXISTING_NATIVE_CALLBACKS_REQUIRED",
    )
    if not enabled and not reconcile_only:
        return {
            "status": "LOCAL_EDIT_WRITE_DISABLED",
            "canvas_writes": 0,
            "sheets_write_requests": 0,
            "retry_writes": False,
            "score_delivery_authorized": False,
            "comment_delivery_authorized": False,
        }
    files = connection.files
    root = files.private_directory(output_root)
    # Exactly the lock already used by participation_staging. The caller must
    # supply that same existing owner root, not create a parallel staging area.
    with files.locked(root / ".participation-stage.lock"):
        session = files.private_directory(root / expected_plan_sha256)
        plan_path = session / "plan.json"
        if plan_path.exists():
            _need(
                digest(files.load(plan_path)) == expected_plan_sha256,
                "SAVED_NATIVE_PLAN_CHANGED",
            )
        else:
            _need(not reconcile_only, "RETAINED_NATIVE_PLAN_REQUIRED")
            files.write(plan_path, plan)
        receipts = sorted(session.glob("receipt-*.json"))
        previous = files.load(receipts[-1]) if receipts else None
        if previous is not None:
            _need(
                type(previous) is dict
                and previous.get("contract") == CONTRACT
                and previous.get("plan_id") == expected_plan_sha256
                and previous.get("canvas_writes") == 0
                and previous.get("retry_writes") is False
                and previous.get("publication_allowed") is False,
                "RETAINED_NATIVE_RECEIPT_UNVERIFIED",
            )
        _need(
            not reconcile_only or previous is not None, "RETAINED_SEND_HISTORY_REQUIRED"
        )
        target = _targets(plan)
        priors = list(root.glob("*/plan.json"))
        _need(len(priors) <= 10_000, "NATIVE_HISTORY_INSPECTION_LIMIT")
        known_terminal = {
            "STAGED_UNAPPROVED",
            "PLANNED_OUTPUT_OBSERVED",
            "NO_ELIGIBLE_EDIT_CHANGES",
        }
        for prior_path in priors:
            if prior_path.parent == session:
                continue
            prior = files.load(prior_path)
            folder_id = prior_path.parent.name
            _need(
                digest(prior) == folder_id
                or prior.get("plan_id")
                == folder_id
                == digest({k: v for k, v in prior.items() if k != "plan_id"}),
                "PRIOR_NATIVE_PLAN_UNVERIFIED",
            )
            prior_target = _targets(prior)
            if target[:2] != prior_target[:2]:
                continue
            prior_receipts = sorted(prior_path.parent.glob("receipt-*.json"))
            if not prior_target[2] and prior_receipts:
                # An empty target list is only a safe no-op when its retained
                # phase is known. Unknown/sending histories cannot hide scope.
                phase = files.load(prior_receipts[-1]).get("status")
                _need(phase in known_terminal, "UNRESOLVED_NATIVE_TARGET_HISTORY")
            if not target[2].intersection(prior_target[2]):
                continue
            if prior_receipts:
                phase = files.load(prior_receipts[-1]).get("status")
                _need(phase in known_terminal, "UNRESOLVED_NATIVE_TARGET_HISTORY")
        context = await _invoke(read_context)
        observed = connection.classify(
            plan, context["raw"], expected_plan_sha256=expected_plan_sha256
        )

        def record(status: str, writes: int = 0) -> dict[str, Any]:
            receipt = {
                "contract": CONTRACT,
                "plan_id": expected_plan_sha256,
                "status": status,
                "observed_status": observed["status"],
                "native_fingerprint": observed["actual_fingerprint"],
                "sheets_write_requests": writes,
                "canvas_writes": 0,
                "retry_writes": False,
                "publication_allowed": False,
                "score_delivery_authorized": False,
                "comment_delivery_authorized": False,
            }
            stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S.%fZ")
            files.write(
                session / ("receipt-" + stamp + "-" + uuid.uuid4().hex[:8] + ".json"),
                receipt,
            )
            return receipt

        if (
            previous is not None
            and previous.get("status") == "PLANNED_OUTPUT_OBSERVED"
            and observed["status"] != "PLANNED_OUTPUT_OBSERVED"
        ):
            # Later legitimate workbook edits do not revoke a completed send.
            # Return current drift separately without appending uncertainty or
            # replacing the retained terminal proof used by future operations.
            return {
                **copy.deepcopy(previous),
                "status": "VERIFIED_HISTORY_RETAINED",
                "historical_status": previous["status"],
                "historical_receipt_sha256": digest(previous),
                "current_observed_status": observed["status"],
                "current_native_fingerprint": observed["actual_fingerprint"],
                "sheets_write_requests": 0,
            }
        if observed["status"] == "PLANNED_OUTPUT_OBSERVED":
            return record("PLANNED_OUTPUT_OBSERVED")
        # A prior attempt/unknown receipt never permits another native batch,
        # including when eventual readback still resembles the old preimage.
        if previous is not None or reconcile_only:
            return record("UNCERTAIN_RECONCILIATION_REQUIRED")
        _need(
            observed["status"] == "BEFORE_STILL_PRESENT", "NATIVE_DESTINATION_DIVERGED"
        )
        connection.revalidate(
            plan,
            expected_plan_sha256=expected_plan_sha256,
            raw=context["raw"],
            current=context["current"],
            pin_binding=context["pin_binding"],
        )
        requests = plan["transfer"]["requests"]
        if not requests:
            return record("NO_ELIGIBLE_EDIT_CHANGES")
        _need(enabled is True and not reconcile_only, "LOCAL_NATIVE_WRITE_NOT_ENABLED")
        try:
            # Complete all Canvas/PIN/native reads before durable send intent.
            # A token refresh or metadata probe must not intervene between
            # SENDING and the fixed one-shot native transport.
            context = await _invoke(read_context)
            observed = connection.classify(
                plan, context["raw"], expected_plan_sha256=expected_plan_sha256
            )
            connection.revalidate(
                plan,
                expected_plan_sha256=expected_plan_sha256,
                raw=context["raw"],
                current=context["current"],
                pin_binding=context["pin_binding"],
            )
        except Exception:
            return record("HELD_BEFORE_SEND")
        record("SENDING")  # Existing atomic write/fsync primitive; before any request.
        try:
            # Recheck the authenticated teacher/source immediately after the
            # durable checkpoint, without another network context read.
            connection.revalidate(
                plan,
                expected_plan_sha256=expected_plan_sha256,
                raw=context["raw"],
                current=context["current"],
                pin_binding=context["pin_binding"],
            )
        except Exception:
            return record("HELD_BEFORE_SEND")
        try:
            await _invoke(
                write_requests,
                plan["binding"]["spreadsheet_id"],
                copy.deepcopy(requests),
            )
            fresh = await _invoke(read_context)
            observed = connection.classify(
                plan, fresh["raw"], expected_plan_sha256=expected_plan_sha256
            )
            if observed["status"] != "PLANNED_OUTPUT_OBSERVED":
                return record("UNCERTAIN_RECONCILIATION_REQUIRED", len(requests))
            return record("PLANNED_OUTPUT_OBSERVED", len(requests))
        except asyncio.CancelledError:
            record("UNCERTAIN_RECONCILIATION_REQUIRED", len(requests))
            raise
        except Exception:
            return record("UNCERTAIN_RECONCILIATION_REQUIRED", len(requests))


async def execute_local_edit_once(
    connection: LocalGrAssEditConnection,
    plan: dict[str, Any],
    *,
    expected_plan_sha256: str,
    output_root: Path,
    read_context: Callable[[], Any],
    write_requests: Callable[..., Any],
    enabled: bool = False,
    reconcile_only: bool = False,
    max_seconds: float = 120,
) -> dict[str, Any]:
    """Bound the existing owner operation; cancellation retains send uncertainty."""
    _need(
        type(max_seconds) in (int, float)
        and math.isfinite(max_seconds)
        and 0 < max_seconds <= 600,
        "NATIVE_EXECUTION_TIMEOUT_INVALID",
    )
    try:
        async with asyncio.timeout(max_seconds):
            return await _execute_local_edit_once(
                connection,
                plan,
                expected_plan_sha256=expected_plan_sha256,
                output_root=output_root,
                read_context=read_context,
                write_requests=write_requests,
                enabled=enabled,
                reconcile_only=reconcile_only,
            )
    except TimeoutError:
        raise GradebookError("NATIVE_EXECUTION_TIMED_OUT") from None
