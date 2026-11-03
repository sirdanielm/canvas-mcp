"""Original mirror owner's private-WHOLE bridge to its existing once history.

Reuses the original inode-bound mutexes and operations/intent/readback/terminal/
closure layout. No alternate journal, root, transport, login or publisher exists.
The host is composed from the original concrete Google/Canvas clients and real
owner callbacks. Tests may use controlled HTTP transports, never authority flags.
"""

from __future__ import annotations

import asyncio
import copy
import fcntl
import hashlib
import inspect
import json
import os
import stat
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any, cast

from . import native
from .client import GradebookClient, GradebookError
from .google import GoogleSheets
from .model import digest
from .unit2_private_proposed_edit import (
    _plan,
    classify_private_edit_readback,
    revalidate_private_edit,
)

ONCE = "ORIGINAL_PRIVATE_WHOLE_EDIT_ONCE_V1"


def _need(value: object, code: str) -> None:
    if not value:
        raise GradebookError(code)


def _sync(check: Callable[..., Any], *args: Any) -> Any:
    result = check(*args)
    if inspect.isawaitable(result):
        if inspect.iscoroutine(result):
            result.close()
        raise GradebookError("ORIGINAL_PRIVATE_EDIT_SYNC_CHECK_REQUIRED")
    return result


def _read(path: Path) -> dict[str, Any]:
    _need(not path.is_symlink(), "PRIVATE_ONCE_SYMLINK_HELD")
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(descriptor, "rb") as stream:
        before = os.fstat(stream.fileno())
        _need(
            stat.S_ISREG(before.st_mode)
            and before.st_uid == os.getuid()
            and before.st_mode & 0o077 == 0
            and before.st_size <= 128 * 1024 * 1024,
            "PRIVATE_ONCE_INPUT_HELD",
        )
        raw = stream.read(128 * 1024 * 1024 + 1)
        after = os.fstat(stream.fileno())
    _need(
        (before.st_ino, before.st_size, before.st_mtime_ns)
        == (after.st_ino, after.st_size, after.st_mtime_ns)
        == (path.stat().st_ino, path.stat().st_size, path.stat().st_mtime_ns),
        "PRIVATE_ONCE_INPUT_CHANGED",
    )
    value = json.loads(raw)
    _need(type(value) is dict, "PRIVATE_ONCE_OBJECT_REQUIRED")
    return cast(dict[str, Any], value)


def _save(path: Path, value: dict[str, Any]) -> None:
    """Original exclusive-create, fsync file and directory receipt primitive."""
    raw = (
        json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False) + "\n"
    ).encode()
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "wb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    directory = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)


def verify_original_note_manifest(
    directory: Path,
    intent: dict[str, Any],
    terminal: dict[str, Any],
    readback: dict[str, Any],
    *,
    root: Path,
    read_ref: Callable[[dict[str, Any]], bytes],
    compile_copy: Callable[..., dict[str, Any]],
    full_raw_matches: Callable[..., bool],
    bindings: dict[str, Any],
    workbook_id: str,
    origin: str,
) -> dict[str, Any]:
    """Replay ONLY the original pure note compiler against its saved evidence.

    read_ref is the original hash-bound reader; compile_copy/full_raw_matches
    are the original configured software functions, never request callbacks.
    This checks historical closed DELIVERY only. Historical source/QC cache
    availability is reported separately; current new-write source/QC checks are
    never disabled. Creates no clients and grants no new write.
    """

    def load(ref: dict[str, Any]) -> dict[str, Any]:
        data = read_ref(copy.deepcopy(ref))
        _need(
            type(data) is bytes
            and hashlib.sha256(data).hexdigest() == ref.get("sha256")
            and len(data) == ref.get("bytes", len(data)),
            "ORIGINAL_MANIFEST_REF_CHANGED",
        )
        value = json.loads(data)
        _need(type(value) is dict, "ORIGINAL_MANIFEST_OBJECT_REQUIRED")
        return cast(dict[str, Any], value)

    _need(
        directory.parent == root
        and not directory.is_symlink()
        and digest(_read(directory / "intent.json")) == digest(intent)
        and digest(_read(directory / "terminal.json")) == digest(terminal)
        and digest(_read(directory / "readback.json")) == digest(readback)
        and _read(directory / "closure.json").get("status") == "CLOSED",
        "ORIGINAL_MANIFEST_DURABLE_CLOSED_EFFECT_REQUIRED",
    )
    _need(
        intent.get("status") == "SENDING"
        and terminal.get("status")
        == readback.get("status")
        == "PLANNED_OUTPUT_OBSERVED"
        and type(intent.get("send_attempts")) is int
        and intent["send_attempts"] == 0
        and type(terminal.get("send_attempts")) is int
        and terminal["send_attempts"] == 1
        and all(
            record.get("retry_writes") is False
            and type(record.get("canvas_writes")) is int
            and record["canvas_writes"] == 0
            and type(record.get("numeric_writes")) is int
            and record["numeric_writes"] == 0
            for record in (intent, terminal)
        ),
        "ORIGINAL_MANIFEST_RESOLVED_EFFECT_REQUIRED",
    )
    _need(
        type(intent.get("requests")) is list
        and bool(intent["requests"])
        and all(
            type(r) is dict
            and set(r) == {"updateCells"}
            and r["updateCells"].get("fields") == "note"
            for r in intent["requests"]
        ),
        "ORIGINAL_MANIFEST_NOTE_FOOTPRINT_REQUIRED",
    )
    config = load(intent["config_ref"])
    _need(
        config.get("contract") == "ROOT_EXISTING_TRANSPORT_NOTE_COPY_V1"
        and config.get("execution_admitted") is True
        and Path(config["output_root"]) == root == directory.parent
        and config["operation_id"]
        == intent["operation_id"]
        == terminal["operation_id"]
        == directory.name
        and config["manifest"] == intent["manifest"] == terminal["manifest"]
        and intent["manifest_sha256"] == intent["manifest"]["sha256"]
        and config["native_preimage"] == intent["native_preimage"],
        "ORIGINAL_MANIFEST_CONFIG_COUPLING_CHANGED",
    )
    manifest, before = load(intent["manifest"]), load(intent["native_preimage"])
    plan = compile_copy(
        manifest,
        before,
        copy.deepcopy(bindings),
        workbook_id=workbook_id,
        origin=origin,
        # Only after authenticated durable CLOSED success. The original pure
        # compiler still enforces literal body/hash, target joins, all intended
        # note requests and preservation. It is not re-running old academicQC.
        verify_pins=False,
    )
    _need(
        digest(plan["requests"]) == digest(intent["requests"])
        and plan["canvas_writes"] == plan["numeric_writes"] == 0
        and all(
            type(record.get("send_attempts")) is int for record in (intent, terminal)
        )
        and intent["send_attempts"] == 0
        and terminal["send_attempts"] == 1
        and intent["status"] == "SENDING"
        and terminal["status"] == readback["status"] == "PLANNED_OUTPUT_OBSERVED",
        "ORIGINAL_MANIFEST_REQUESTS_OR_OUTCOME_CHANGED",
    )
    for key, expected in (
        ("candidate_count", plan["candidate_count"]),
        ("prepared_count", plan["note_change_count"]),
        ("already_present_count", plan["already_present_count"]),
    ):
        _need(
            all(
                type(record.get(key)) is int and record[key] == expected
                for record in (intent, terminal)
            ),
            "ORIGINAL_MANIFEST_COUNTS_CHANGED",
        )
    _need(
        type(terminal.get("staged_count")) is int
        and terminal["staged_count"] == plan["note_change_count"]
        and full_raw_matches(
            plan["after_raw"], readback["raw"], workbook_id=workbook_id
        )
        is True
        and digest(native._state(plan["after_raw"]))
        == digest(native._state(readback["raw"]))
        == digest(readback["native_state"]),
        "ORIGINAL_MANIFEST_NATIVE_READBACK_CHANGED",
    )

    missing: list[dict[str, Any]] = []
    for item in manifest["candidates"]:
        for ref in (
            item["body_ref"],
            item["source_record_ref"],
            item["capture_ref"],
            *item["pins"],
        ):
            if not Path(ref["path"]).exists() and ref not in missing:
                missing.append(copy.deepcopy(ref))
    return {
        "contract": "ORIGINAL_CLOSED_NOTE_EFFECT_EVIDENCE_V1",
        "closed_effect_resolved": True,
        "old_source_QC_requalified": False,
        "historical_source_provenance": "GAP" if missing else "NOT_REOPENED",
        "missing_historical_source_refs": missing,
        "known_note_footprint": [
            copy.deepcopy(r["updateCells"]["range"]) for r in intent["requests"]
        ],
        "current_write_or_source_authority_granted": False,
    }


class OriginalPrivateWholeHost:
    """Concrete original clients; callbacks are trusted owner composition only."""

    def __init__(
        self,
        google: GoogleSheets,
        canvas: GradebookClient,
        *,
        read_context: Callable[..., Any],
        owner_check: Callable[[], None],
        source_check: Callable[..., Any],
        staged_source_check: Callable[..., Any],
        target_check: Callable[..., Any],
        rounding_check: Callable[..., Any] | None,
    ) -> None:
        _need(
            type(google) is GoogleSheets
            and type(canvas) is GradebookClient
            and all(
                callable(x)
                for x in (
                    read_context,
                    owner_check,
                    source_check,
                    staged_source_check,
                    target_check,
                )
            ),
            "ORIGINAL_PRIVATE_EDIT_CLIENTS_AND_CHECKERS_REQUIRED",
        )
        self.google, self.canvas = google, canvas
        self.reader, self.owner_check = read_context, owner_check
        self.source_check, self.staged_source_check = source_check, staged_source_check
        self.target_check, self.rounding_check = target_check, rounding_check

    async def read(self) -> dict[str, Any]:
        self.check_owner()
        result = self.reader(self.google, self.canvas)
        value = await result if inspect.isawaitable(result) else result
        _need(
            type(value) is dict and {"raw", "canvas_observation"} <= set(value),
            "ORIGINAL_PRIVATE_EDIT_REAL_CONTEXT_REQUIRED",
        )
        return cast(dict[str, Any], value)

    def check_owner(self) -> None:
        _need(
            _sync(self.owner_check) is None,
            "ORIGINAL_PRIVATE_EDIT_CURRENT_OWNER_REQUIRED",
        )

    def revalidate(self, plan: dict[str, Any], context: dict[str, Any]) -> None:
        self.check_owner()
        revalidate_private_edit(
            plan,
            raw=context["raw"],
            canvas_observation=context["canvas_observation"],
            expected_plan_sha256=digest(plan),
            source_check=self.source_check,
            staged_source_check=self.staged_source_check,
            target_check=self.target_check,
            prior_outcome="KNOWN_NOT_SENT",
            rounding_check=self.rounding_check,
        )

    async def close(self) -> None:
        try:
            await self.google.close()
        finally:
            await self.canvas.close()


class OriginalPrivateWholeOwner:
    """A real private-plan variant of the original mirror-owner once lifecycle."""

    def __init__(
        self,
        root: Path,
        locks: tuple[tuple[Path, int, int], ...],
        *,
        original_history_check: Callable[[], None],
        original_history_config_ref: dict[str, Any],
        manifest_history_check: Callable[..., None] | None = None,
    ) -> None:
        _need(
            root.is_absolute()
            and root.is_dir()
            and not root.is_symlink()
            and root.stat().st_uid == os.getuid()
            and root.stat().st_mode & 0o077 == 0
            and callable(original_history_check)
            and len(locks) >= 2,
            "ORIGINAL_PRIVATE_EDIT_EXISTING_HISTORY_REQUIRED",
        )
        _need(
            ".." not in root.parts
            and not any(p.is_symlink() for p in (root, *root.parents))
            and len({str(x[0]) for x in locks}) == len(locks),
            "ORIGINAL_PRIVATE_EDIT_EXISTING_LOCKS_REQUIRED",
        )
        config_path = Path(original_history_config_ref["path"])
        config = _read(config_path)
        _need(
            hashlib.sha256(config_path.read_bytes()).hexdigest()
            == original_history_config_ref["sha256"]
            and Path(config["output_root"]) == root
            and config["locks"] == [[str(p), dev, ino] for p, dev, ino in locks],
            "ORIGINAL_PRIVATE_EDIT_HISTORY_BINDING_CHANGED",
        )
        self.root, self.locks = root, locks
        self.original_history_check = original_history_check
        self.manifest_history_check = manifest_history_check

    def _history(self, selected: Path) -> None:
        # The genuine original history verifier authenticates the preserved
        # predecessor namespaces. This namespace validates both original note
        # receipts and this explicit private-plan version, never a blank root.
        _need(
            _sync(self.original_history_check) is None,
            "ORIGINAL_EDIT_HISTORY_CHECK_REQUIRED",
        )
        directories = list(self.root.iterdir())
        _need(len(directories) <= 10_000, "ORIGINAL_EDIT_HISTORY_LIMIT")
        for directory in directories:
            if not directory.is_dir() or directory == selected:
                continue
            _need(not directory.is_symlink(), "ORIGINAL_EDIT_HISTORY_SYMLINK")
            terminal_path = directory / "terminal.json"
            intent_path = directory / "intent.json"
            if not terminal_path.exists() and not intent_path.exists():
                raise GradebookError("ORIGINAL_EDIT_HISTORY_UNSETTLED")
            terminal = _read(terminal_path) if terminal_path.exists() else None
            closure_path = directory / "closure.json"
            _need(
                closure_path.exists() and _read(closure_path).get("status") == "CLOSED",
                "ORIGINAL_EDIT_HISTORY_CLIENTS_UNSETTLED",
            )
            if not intent_path.exists():
                _need(
                    terminal is not None
                    and terminal.get("status") == "HELD_BEFORE_SEND"
                    and type(terminal.get("send_attempts")) is int
                    and terminal["send_attempts"] == 0,
                    "ORIGINAL_EDIT_HISTORY_UNSETTLED",
                )
                continue
            intent = _read(intent_path)
            readback_path = directory / "readback.json"
            _need(
                terminal is not None
                and terminal.get("status") == "PLANNED_OUTPUT_OBSERVED"
                and type(terminal.get("send_attempts")) is int
                and terminal["send_attempts"] == 1
                and readback_path.exists(),
                "ORIGINAL_EDIT_HISTORY_UNSETTLED",
            )
            assert terminal is not None
            readback = _read(readback_path)
            _need(
                readback.get("status") == "PLANNED_OUTPUT_OBSERVED",
                "ORIGINAL_EDIT_HISTORY_UNSETTLED",
            )
            if "plan" not in intent:
                # Existing ROOT_EXISTING_TRANSPORT_NOTE_COPY_V1 operations
                # carry immutable manifest/config/preimage refs and requests.
                # The real original compiler/readback verifier must authenticate
                # them; this branch never invents a plan or blesses a status.
                _need(
                    type(intent.get("manifest")) is dict
                    and {"path", "sha256"} <= set(intent["manifest"])
                    and intent.get("manifest_sha256") == intent["manifest"]["sha256"]
                    and terminal.get("manifest") == intent["manifest"]
                    and intent.get("operation_id")
                    == terminal.get("operation_id")
                    == directory.name
                    and type(intent.get("config_ref")) is dict
                    and type(intent.get("native_preimage")) is dict
                    and type(intent.get("requests")) is list
                    and bool(intent["requests"])
                    and all(
                        type(record.get(key)) is int and record[key] == 0
                        for record in (intent, terminal)
                        for key in ("canvas_writes", "numeric_writes")
                    )
                    and callable(self.manifest_history_check),
                    "ORIGINAL_MANIFEST_HISTORY_VERIFIER_REQUIRED",
                )
                assert self.manifest_history_check is not None
                _need(
                    _sync(
                        self.manifest_history_check,
                        directory,
                        copy.deepcopy(intent),
                        copy.deepcopy(terminal),
                        copy.deepcopy(readback),
                    )
                    is None,
                    "ORIGINAL_MANIFEST_HISTORY_NOT_VERIFIED",
                )
                continue
            _need(
                digest(intent["plan"])
                == intent.get("plan_sha256")
                == terminal.get("plan_sha256"),
                "ORIGINAL_EDIT_HISTORY_UNSETTLED",
            )
            if intent.get("contract") == ONCE:
                _need(
                    classify_private_edit_readback(
                        intent["plan"],
                        readback["raw"],
                        expected_plan_sha256=intent["plan_sha256"],
                    )["status"]
                    == "PLANNED_OUTPUT_OBSERVED",
                    "ORIGINAL_EDIT_HISTORY_UNSETTLED",
                )
            else:
                # Exact original note-history native postcondition remains.
                _need(
                    readback.get("native_state") == intent["plan"].get("after_state")
                    and digest(readback["native_state"]) == readback.get("fingerprint")
                    and json.loads(
                        json.dumps(
                            native._state(readback["raw"]),
                            sort_keys=True,
                            allow_nan=False,
                        )
                    )
                    == readback["native_state"],
                    "ORIGINAL_EDIT_HISTORY_UNSETTLED",
                )

    async def execute(
        self,
        plan: dict[str, Any],
        host: OriginalPrivateWholeHost,
        *,
        expected_plan_sha256: str,
        review_check: Callable[[dict[str, Any]], None],
    ) -> dict[str, Any]:
        """Two real preflights, durable intent, one send, independent readback."""
        _need(
            type(host) is OriginalPrivateWholeHost and callable(review_check),
            "ORIGINAL_PRIVATE_EDIT_HOST_REQUIRED",
        )
        operation: Path | None = None
        held: list[int] = []
        result = {
            "contract": ONCE,
            "operation_id": None,
            "plan_sha256": expected_plan_sha256,
            "status": "HELD_BEFORE_SEND",
            "send_attempts": 0,
            "staged_count": 0,
            "retry_writes": False,
            "canvas_writes": 0,
        }
        try:
            _plan(plan, expected_plan_sha256)
            _need(
                _sync(review_check, copy.deepcopy(plan)) is None,
                "ORIGINAL_PRIVATE_EDIT_REVIEW_REQUIRED",
            )
            operation = self.root / ("private-whole-" + expected_plan_sha256)
            result["operation_id"] = operation.name
            deadline = time.monotonic() + 45
            for path, dev, ino in self.locks:
                fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
                held.append(fd)
                while True:
                    host.check_owner()
                    for info in (os.fstat(fd), path.stat(follow_symlinks=False)):
                        _need(
                            stat.S_ISREG(info.st_mode)
                            and (info.st_dev, info.st_ino) == (dev, ino),
                            "ORIGINAL_PRIVATE_EDIT_LOCK_CHANGED",
                        )
                    try:
                        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                        for info in (os.fstat(fd), path.stat(follow_symlinks=False)):
                            _need(
                                stat.S_ISREG(info.st_mode)
                                and (info.st_dev, info.st_ino) == (dev, ino),
                                "ORIGINAL_PRIVATE_EDIT_LOCK_CHANGED",
                            )
                        break
                    except BlockingIOError:
                        _need(
                            time.monotonic() < deadline,
                            "ORIGINAL_PRIVATE_EDIT_LOCK_BUSY",
                        )
                        await asyncio.sleep(0.2)
            self._history(operation)
            if operation.exists():
                # Any existing directory is readback-only, never a second send.
                intent = _read(operation / "intent.json")
                _need(
                    intent.get("contract") == ONCE and intent.get("plan") == plan,
                    "ORIGINAL_PRIVATE_EDIT_EXISTING_INTENT_REQUIRED",
                )
                context = await host.read()
                observed = classify_private_edit_readback(
                    plan, context["raw"], expected_plan_sha256=expected_plan_sha256
                )
                return {
                    **result,
                    **observed,
                    "historical_intent_retained": True,
                    "staged_count": int(
                        observed["status"] == "PLANNED_OUTPUT_OBSERVED"
                    ),
                }
            if not plan["requests"]:
                context = await host.read()
                observed = classify_private_edit_readback(
                    plan, context["raw"], expected_plan_sha256=expected_plan_sha256
                )
                _need(
                    observed["status"] == "PLANNED_OUTPUT_OBSERVED",
                    "ORIGINAL_PRIVATE_EDIT_NO_CHANGE_DIVERGED",
                )
                return {**result, **observed, "staged_count": 1, "send_attempts": 0}
            operation.mkdir(mode=0o700)
            try:
                for _ in range(2):
                    context = await host.read()
                    host.revalidate(plan, context)
                _save(
                    operation / "intent.json",
                    {
                        "contract": ONCE,
                        "plan": plan,
                        "plan_sha256": expected_plan_sha256,
                    },
                )
                # No network/authentication probe between intent and sole send.
                host.revalidate(plan, context)
                result["send_attempts"] = 1
                try:
                    await host.google.send_preflighted_batch(
                        copy.deepcopy(plan["requests"])
                    )
                except Exception:
                    result["send_outcome_uncertain"] = True
                context = await host.read()
                observed = classify_private_edit_readback(
                    plan, context["raw"], expected_plan_sha256=expected_plan_sha256
                )
                _save(operation / "readback.json", {**observed, "raw": context["raw"]})
                result.update(
                    status=observed["status"],
                    staged_count=int(observed["status"] == "PLANNED_OUTPUT_OBSERVED"),
                )
            except BaseException as error:
                result.update(
                    status="READBACK_UNCERTAIN"
                    if result["send_attempts"]
                    else "HELD_BEFORE_SEND",
                    error_type=type(error).__name__,
                )
                if not isinstance(error, Exception):
                    raise
            finally:
                _save(operation / "terminal.json", result)
            return result
        finally:
            try:
                closing = asyncio.create_task(host.close())
                try:
                    await asyncio.shield(closing)
                except asyncio.CancelledError:
                    await closing
                    raise
                if (
                    operation is not None
                    and operation.is_dir()
                    and not (operation / "closure.json").exists()
                ):
                    _save(
                        operation / "closure.json",
                        {"status": "CLOSED", "clients_awaited": True},
                    )
            finally:
                for fd in reversed(held):
                    os.close(fd)
