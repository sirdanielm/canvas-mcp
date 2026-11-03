"""Bounded saved complete-proposal intake around the ORIGINAL EDIT once owner.

This is file intake/orchestration, never a source verifier or a replacement
journal/controller. Trusted original-owner callbacks authenticate current scope,
source, independent QC, staged Sheet, target and rounding. File hashes, this
manifest and green source tests confer none of those authorities.
"""

from __future__ import annotations

import copy
import hashlib
import inspect
import json
import os
import re
import stat
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

from canvas_mcp.gradebook.model import digest
from canvas_mcp.gradebook.unit2_native_whole_source import AUTHOR as NATIVE_AUTHOR
from canvas_mcp.gradebook.unit2_note_draft import EditOnlyAuthorization
from canvas_mcp.gradebook.unit2_private_proposed_edit import (
    AUTHOR,
    FINAL_NEAREST,
    REVIEWED_AUTHOR,
    classify_private_edit_readback,
    prepare_private_edit,
)
from canvas_mcp.gradebook.unit2_private_proposed_owner import (
    ONCE,
    OriginalPrivateWholeHost,
    OriginalPrivateWholeOwner,
    _read,
)
from canvas_mcp.gradebook.unit2_reviewed_whole_source import source_digest

CONTRACT = "UNIT2_SAVED_COMPLETE_EDIT_BATCH_V1"
MAX_CASES = 3
HASH = re.compile(r"[a-f0-9]{64}")
NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,79}")
Json = dict[str, Any]


class BatchHold(ValueError):
    """A bounded intake/once predicate failed; never permission to retry."""


def _need(value: object, code: str) -> None:
    if not value:
        raise BatchHold(code)


def _sync(check: Callable[..., Any], *args: Any) -> Any:
    result = check(*copy.deepcopy(args))
    if inspect.isawaitable(result):
        if inspect.iscoroutine(result):
            result.close()
        raise BatchHold("BATCH_SYNCHRONOUS_AUTHENTIC_CHECK_REQUIRED")
    return result


def _ref(ref: Any) -> None:
    _need(
        type(ref) is dict
        and set(ref) == {"path", "bytes", "sha256"}
        and type(ref["path"]) is str
        and Path(ref["path"]).is_absolute()
        and ".." not in Path(ref["path"]).parts
        and type(ref["bytes"]) is int
        and 0 <= ref["bytes"] <= 20_000_000
        and type(ref["sha256"]) is str
        and HASH.fullmatch(ref["sha256"]),
        "BATCH_EXACT_BOUNDED_REFERENCE_REQUIRED",
    )


def read_reference(ref: Json) -> bytes:
    """Bounded original-byte file reader; no executable imports or credentials."""
    _ref(ref)
    path = Path(ref["path"])
    _need(
        not any(p.is_symlink() for p in (path, *path.parents)),
        "BATCH_DIRECT_REFERENCE_REQUIRED",
    )
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, "rb") as stream:
        before = os.fstat(stream.fileno())
        _need(
            stat.S_ISREG(before.st_mode) and before.st_size == ref["bytes"],
            "BATCH_REGULAR_REFERENCE_REQUIRED",
        )
        raw = stream.read(20_000_001)
        after = os.fstat(stream.fileno())
    current = path.stat()
    _need(
        (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
        == (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)
        == (current.st_dev, current.st_ino, current.st_size, current.st_mtime_ns)
        and hashlib.sha256(raw).hexdigest() == ref["sha256"],
        "BATCH_REFERENCE_CHANGED",
    )
    return raw


def _json(raw: bytes) -> Json:
    def unique(pairs: list[tuple[str, Any]]) -> Json:
        result: Json = {}
        for key, value in pairs:
            _need(key not in result, "BATCH_DUPLICATE_JSON_KEY")
            result[key] = value
        return result

    def constant(_: str) -> None:
        raise BatchHold("BATCH_NONFINITE_JSON")

    value = json.loads(raw, object_pairs_hook=unique, parse_constant=constant)
    _need(type(value) is dict, "BATCH_JSON_OBJECT_REQUIRED")
    return cast(Json, value)


def _instant(value: Any) -> datetime:
    _need(type(value) is str, "BATCH_AWARE_CLOCK_REQUIRED")
    try:
        instant = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise BatchHold("BATCH_AWARE_CLOCK_REQUIRED") from error
    _need(
        instant.tzinfo is not None and instant.utcoffset() is not None,
        "BATCH_AWARE_CLOCK_REQUIRED",
    )
    return instant


def _now(clock: Callable[[], datetime]) -> datetime:
    value = clock()
    _need(
        type(value) is datetime
        and value.tzinfo is not None
        and value.utcoffset() is not None,
        "BATCH_REAL_AWARE_CLOCK_REQUIRED",
    )
    return value


def load_manifest(ref: Json, *, clock: Callable[[], datetime]) -> tuple[Json, bytes]:
    raw = read_reference(ref)
    manifest = _json(raw)
    _need(
        set(manifest) == {"contract", "batch_id", "job_slot", "created_at", "cases"}
        and manifest["contract"] == CONTRACT
        and type(manifest["batch_id"]) is str
        and NAME.fullmatch(manifest["batch_id"]),
        "BATCH_EXACT_MANIFEST_REQUIRED",
    )
    slot = manifest["job_slot"]
    _need(
        type(slot) is dict
        and set(slot) == {"task_id", "owner", "input_sha256"}
        and all(type(slot[k]) is str and bool(slot[k]) for k in slot)
        and HASH.fullmatch(slot["input_sha256"]),
        "BATCH_CURRENT_JOB_SLOT_REQUIRED",
    )
    _need(_instant(manifest["created_at"]) <= _now(clock), "BATCH_FUTURE_MANIFEST_HELD")
    cases = manifest["cases"]
    _need(
        type(cases) is list and 0 < len(cases) <= MAX_CASES,
        "BATCH_AT_MOST_THREE_CASES_REQUIRED",
    )
    keys = {
        "case_id",
        "source_request_ref",
        "source_author",
        "expected_source_profile_sha256",
        "qc_ref",
        "body_ref",
        "readable_ref",
        "sheet_readback_ref",
        "rounding_proof_ref",
        "target",
        "expected_identity_binding_sha256",
    }
    ids, targets = set(), set()
    for case in cases:
        _need(
            type(case) is dict
            and set(case) == keys
            and type(case["case_id"]) is str
            and NAME.fullmatch(case["case_id"])
            and case["case_id"] not in ids,
            "BATCH_EXACT_UNIQUE_CASE_REQUIRED",
        )
        ids.add(case["case_id"])
        _need(
            type(case["source_author"]) is str
            and case["source_author"] in {AUTHOR, REVIEWED_AUTHOR, NATIVE_AUTHOR},
            "BATCH_UNSUPPORTED_SOURCE_AUTHOR",
        )
        for key in (
            "expected_source_profile_sha256",
            "expected_identity_binding_sha256",
        ):
            _need(
                type(case[key]) is str and HASH.fullmatch(case[key]),
                "BATCH_EXACT_SOURCE_IDENTITY_REQUIRED",
            )
        for key in (
            "source_request_ref",
            "qc_ref",
            "body_ref",
            "readable_ref",
            "sheet_readback_ref",
            "rounding_proof_ref",
        ):
            _ref(case[key])
        target = case["target"]
        base = {"origin", "course_id", "user_id", "assignment_id"}
        _need(
            type(target) is dict
            and base
            <= set(target)
            <= base | {"attempt", "submitted_at", "submission_types"}
            and all(type(target[k]) is str and bool(target[k]) for k in base),
            "BATCH_EXACT_TARGET_REQUIRED",
        )
        if "attempt" in target:
            _need(
                target["attempt"] is None
                or type(target["attempt"]) is int
                and target["attempt"] >= 0,
                "BATCH_TARGET_ATTEMPT_TYPE_REQUIRED",
            )
        if target.get("submitted_at") is not None:
            _need(
                _instant(target["submitted_at"]) <= _now(clock),
                "BATCH_FUTURE_TARGET_HELD",
            )
        if "submission_types" in target:
            _need(
                type(target["submission_types"]) is list
                and all(type(v) is str for v in target["submission_types"]),
                "BATCH_TARGET_SUBMISSION_TYPES_REQUIRED",
            )
        target_key = source_digest(target)
        _need(target_key not in targets, "BATCH_DUPLICATE_TARGET_HELD")
        targets.add(target_key)
    return manifest, raw


@dataclass(frozen=True)
class CaseRuntime:
    """Actual original host + separate genuine current independent-QC checker."""

    host: OriginalPrivateWholeHost
    authorization: EditOnlyAuthorization
    binding: Json
    qc_check: Callable[[Json, Json, Json, Json], None]


def _error_code(error: BaseException) -> str:
    text = str(error)
    return text if re.fullmatch(r"[A-Z0-9_:]{1,140}", text) else "BATCH_CASE_GUARD_HELD"


def _prior(
    owner: OriginalPrivateWholeOwner, case: Json, request: Json
) -> tuple[Path, Json] | None:
    matches = []
    for directory in owner.root.iterdir():
        if not directory.is_dir() or not directory.name.startswith("private-whole-"):
            continue  # Genuine original owner still validates all legacy schemas.
        _need(not directory.is_symlink(), "BATCH_ORIGINAL_HISTORY_SYMLINK")
        intent_path = directory / "intent.json"
        if not intent_path.exists():
            continue  # A pre-send hold is not a delivered/uncertain operation.
        intent = _read(intent_path)
        _need(
            intent.get("contract") == ONCE and type(intent.get("plan")) is dict,
            "BATCH_ORIGINAL_PRIVATE_INTENT_REQUIRED",
        )
        plan = intent["plan"]
        _need(
            digest(plan) == intent.get("plan_sha256")
            and directory.name == "private-whole-" + digest(plan),
            "BATCH_ORIGINAL_INTENT_CHANGED",
        )
        if (
            source_digest(plan["source_request"]) == source_digest(request)
            and plan["target"] == case["target"]
        ):
            matches.append((directory, plan))
    _need(len(matches) <= 1, "BATCH_MULTIPLE_PRIOR_IDENTITIES_HELD")
    return matches[0] if matches else None


def _closed_observed(directory: Path, plan: Json) -> bool:
    if not all(
        (directory / name).exists()
        for name in ("terminal.json", "readback.json", "closure.json")
    ):
        return False
    terminal, readback, closure = (
        _read(directory / name)
        for name in ("terminal.json", "readback.json", "closure.json")
    )
    if (
        terminal.get("status") != "PLANNED_OUTPUT_OBSERVED"
        or closure.get("status") != "CLOSED"
    ):
        return False
    _need(
        type(terminal.get("send_attempts")) is int
        and terminal["send_attempts"] == 1
        and terminal.get("retry_writes") is False
        and type(terminal.get("canvas_writes")) is int
        and terminal["canvas_writes"] == 0
        and type(terminal.get("staged_count")) is int
        and terminal["staged_count"] == 1
        and closure.get("clients_awaited") is True
        and terminal.get("plan_sha256") == digest(plan)
        and readback.get("status") == "PLANNED_OUTPUT_OBSERVED"
        and classify_private_edit_readback(
            plan, readback["raw"], expected_plan_sha256=digest(plan)
        )["status"]
        == "PLANNED_OUTPUT_OBSERVED",
        "BATCH_CLOSED_DELIVERY_PROOF_CHANGED",
    )
    return True


def _save(path: Path, value: Json | bytes) -> None:
    raw = (
        value
        if type(value) is bytes
        else (
            json.dumps(
                value, sort_keys=True, ensure_ascii=False, allow_nan=False, indent=2
            )
            + "\n"
        ).encode()
    )
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "wb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    fd = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _compose_runtime(
    runtime: CaseRuntime,
    case: Json,
    request: Json,
    body: bytes,
    scope: Callable[[str], None],
    execute: bool,
) -> OriginalPrivateWholeHost:
    def owner_check() -> None:
        scope("EDIT_ONCE" if execute else "READ_ONLY")
        _need(
            _sync(runtime.host.owner_check) is None,
            "BATCH_ORIGINAL_CURRENT_OWNER_REQUIRED",
        )

    def checked_source(given: Json) -> Json:
        owner_check()
        _need(given == request, "BATCH_REQUEST_REBINDING_HELD")
        source = _sync(runtime.host.source_check, given)
        _need(
            type(source) is dict
            and source.get("author_contract") == case["source_author"]
            and source_digest(source) == case["expected_source_profile_sha256"]
            and source.get("scope") == "WHOLE_TEST"
            and source.get("identity_binding_sha256")
            == case["expected_identity_binding_sha256"]
            and type(source.get("feedback")) is str
            and source["feedback"].encode("utf-8") == body,
            "BATCH_EXACT_COMPLETE_SOURCE_BODY_REQUIRED",
        )
        for key in (
            "qc_ref",
            "body_ref",
            "readable_ref",
            "sheet_readback_ref",
            "rounding_proof_ref",
        ):
            read_reference(case[key])
        _need(
            _sync(
                runtime.qc_check,
                source,
                case["qc_ref"],
                case["target"],
                case["body_ref"],
            )
            is None,
            "BATCH_CURRENT_INDEPENDENT_QC_REQUIRED",
        )
        return cast(Json, source)

    return OriginalPrivateWholeHost(
        runtime.host.google,
        runtime.host.canvas,
        read_context=runtime.host.reader,
        owner_check=owner_check,
        source_check=checked_source,
        staged_source_check=runtime.host.staged_source_check,
        target_check=runtime.host.target_check,
        rounding_check=runtime.host.rounding_check,
    )


def _review_checker(
    host: OriginalPrivateWholeHost, plan: Json
) -> Callable[[Json], None]:
    expected = copy.deepcopy(plan)

    def review(given: Json) -> None:
        host.check_owner()
        _need(
            digest(given) == digest(expected)
            and given["source"] == _sync(host.source_check, expected["source_request"]),
            "BATCH_REVIEWED_PLAN_CHANGED",
        )

    return review


def _bind_case_scope(
    check: Callable[[str, Json | None], None], case: Json
) -> Callable[[str], None]:
    bound = copy.deepcopy(case)

    def scope(action: str) -> None:
        check(action, bound)

    return scope


def _get_only_review(scope: Callable[[str], None]) -> Callable[[Json], None]:
    def review(_: Json) -> None:
        scope("UNKNOWN_GET_ONLY")

    return review


async def run_saved_batch(
    manifest_ref: Json,
    *,
    original_owner: OriginalPrivateWholeOwner,
    services_for: Callable[[Json], CaseRuntime],
    authority_check: Callable[[Json, str], None],
    output_root: Path,
    execute: bool = False,
    clock: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> Json:
    """At most three cases; effect state remains ONLY in the original once root.

    output_root contains private readable/structured run reports, not another
    execution ledger. An old UNKNOWN is GET-only and remains administratively
    unresolved even if that GET observes the plan; this code never finalizes it.
    No prior verified case (including QC141) is regraded, reopened or resent.
    """
    _need(
        type(original_owner) is OriginalPrivateWholeOwner
        and callable(services_for)
        and callable(authority_check)
        and type(execute) is bool,
        "BATCH_ORIGINAL_OWNER_AND_RUNTIME_REQUIRED",
    )
    manifest, raw_manifest = load_manifest(manifest_ref, clock=clock)
    slot = copy.deepcopy(manifest["job_slot"])

    def scope(action: str, case: Json | None = None) -> None:
        _need(
            _instant(manifest["created_at"]) <= _now(clock),
            "BATCH_CLOCK_BEFORE_MANIFEST",
        )
        _need(
            _sync(
                authority_check,
                {"job_slot": slot, "manifest_ref": manifest_ref, "case": case},
                action,
            )
            is None,
            "BATCH_CURRENT_OWNER_SCOPE_REQUIRED",
        )

    scope("READ_ONLY")
    _need(
        output_root.is_absolute()
        and output_root.is_dir()
        and not any(p.is_symlink() for p in (output_root, *output_root.parents))
        and output_root.stat().st_uid == os.getuid()
        and stat.S_IMODE(output_root.stat().st_mode) & 0o077 == 0,
        "BATCH_EXISTING_PRIVATE_OUTPUT_REQUIRED",
    )
    run = output_root / (manifest["batch_id"] + "-" + uuid.uuid4().hex)
    run.mkdir(mode=0o700)
    _save(run / "manifest.private.json", raw_manifest)
    results: list[Json] = []
    fenced = False
    for case in manifest["cases"]:
        case_dir = run / case["case_id"]
        case_dir.mkdir(mode=0o700)
        case_scope = _bind_case_scope(scope, case)
        host: OriginalPrivateWholeHost | None = None
        plan: Json | None = None
        result: Json = {
            "case_id": case["case_id"],
            "status": "HELD",
            "new_send_attempts": 0,
        }
        try:
            case_scope("READ_ONLY")
            _need(not fenced, "BATCH_PRIOR_UNKNOWN_EFFECT_FENCE")
            request = _json(read_reference(case["source_request_ref"]))
            prior = _prior(original_owner, case, request)
            if prior is not None:
                directory, plan = prior
                result["original_operation_id"] = directory.name
                if _closed_observed(directory, plan):
                    result.update(
                        status="NO_OP_DELIVERED",
                        reason="ACTUAL_ORIGINAL_CLOSED_READBACK_VERIFIED",
                    )
                    continue
                if not execute:
                    result.update(
                        status="HELD_UNKNOWN_GET_ONLY",
                        reason="ORIGINAL_OPERATION_UNRESOLVED",
                    )
                    fenced = True
                    continue
            runtime = services_for(copy.deepcopy(case))
            if (
                type(runtime) is CaseRuntime
                and type(runtime.host) is OriginalPrivateWholeHost
            ):
                host = runtime.host
            _need(
                type(runtime) is CaseRuntime
                and type(runtime.host) is OriginalPrivateWholeHost
                and type(runtime.authorization) is EditOnlyAuthorization
                and callable(runtime.qc_check),
                "BATCH_GENUINE_CASE_RUNTIME_REQUIRED",
            )
            base_host = runtime.host
            # Close a genuine acquired client even if a later local proof fails.
            host = base_host
            if prior is not None:
                case_scope("UNKNOWN_GET_ONLY")
                assert plan is not None
                observed = await original_owner.execute(
                    plan,
                    host,
                    expected_plan_sha256=digest(plan),
                    review_check=_get_only_review(case_scope),
                )
                host = None
                result.update(
                    status="HELD_UNKNOWN_GET_ONLY",
                    reason="ORIGINAL_FINALIZATION_STILL_REQUIRED",
                    observed_status=observed["status"],
                    new_send_attempts=0,
                )
                fenced = True
                continue
            for key in (
                "qc_ref",
                "body_ref",
                "readable_ref",
                "sheet_readback_ref",
                "rounding_proof_ref",
            ):
                read_reference(case[key])
            _need(
                bool(read_reference(case["readable_ref"]).decode("utf-8").strip()),
                "BATCH_READABLE_ARTIFACT_REQUIRED",
            )
            body = read_reference(case["body_ref"])
            proof = _json(read_reference(case["rounding_proof_ref"]))
            host = _compose_runtime(runtime, case, request, body, case_scope, execute)
            host.source_check(
                request
            )  # Preserve the first precise source/QC hold before planner wrapping.
            context = await host.read()
            plan = prepare_private_edit(
                request,
                raw=context["raw"],
                binding=copy.deepcopy(runtime.binding),
                target=case["target"],
                expected_identity_binding_sha256=case[
                    "expected_identity_binding_sha256"
                ],
                canvas_observation=context["canvas_observation"],
                unit_sheet_readback_ref=case["sheet_readback_ref"],
                authorization=runtime.authorization,
                prior_outcome="KNOWN_NOT_SENT",
                source_check=host.source_check,
                staged_source_check=host.staged_source_check,
                target_check=host.target_check,
                score_representation=FINAL_NEAREST,
                final_rounding_proof=proof,
                rounding_check=host.rounding_check,
            )
            _save(case_dir / "plan.private.json", plan)
            _save(
                case_dir / "qualification.private.json",
                {
                    "manifest_ref": manifest_ref,
                    "job_slot": slot,
                    "case": case,
                    "plan_sha256": digest(plan),
                },
            )
            result.update(plan_sha256=digest(plan), status="PREPARED_NOT_EXECUTED")
            if execute:
                case_scope("EDIT_ONCE")
                observed = await original_owner.execute(
                    plan,
                    host,
                    expected_plan_sha256=digest(plan),
                    review_check=_review_checker(host, plan),
                )
                host = None
                _save(case_dir / "original-owner-result.private.json", observed)
                result.update(
                    status=observed["status"],
                    original_operation_id=observed["operation_id"],
                    new_send_attempts=observed["send_attempts"],
                )
                fenced = observed["status"] not in {
                    "PLANNED_OUTPUT_OBSERVED",
                    "HELD_BEFORE_SEND",
                }
        except BaseException as error:
            result.update(
                status="HELD",
                reason=_error_code(error),
                error_type=type(error).__name__,
            )
            if plan is not None:
                directory = original_owner.root / ("private-whole-" + digest(plan))
                if (directory / "intent.json").exists():
                    try:
                        closed = _closed_observed(directory, plan)
                    except Exception:
                        closed = False
                    if prior is None:
                        result["new_send_attempts"] = None
                        terminal_path = directory / "terminal.json"
                        if terminal_path.exists():
                            record = _read(terminal_path)
                            if type(record.get("send_attempts")) is int and record[
                                "send_attempts"
                            ] in (0, 1):
                                result["new_send_attempts"] = record["send_attempts"]
                    if not closed:
                        result.update(
                            status="HELD_UNKNOWN_GET_ONLY",
                            original_operation_id=directory.name,
                        )
                    else:
                        result.update(
                            status="DELIVERED_REPORT_HELD",
                            original_operation_id=directory.name,
                            actual_closed_delivery_verified=True,
                        )
                    fenced = True
            if (
                "HISTORY_UNSETTLED" in result["reason"]
                or "HISTORY_CLIENTS_UNSETTLED" in result["reason"]
            ):
                fenced = True
            if not isinstance(error, Exception):
                result["interrupted"] = True
                raise
        finally:
            if host is not None:
                try:
                    await host.close()
                except Exception as error:
                    result.update(
                        status="HELD_CLIENTS_UNSETTLED",
                        reason=_error_code(error),
                        clients_closed=False,
                    )
                    fenced = True
            _save(case_dir / "result.private.json", result)
            results.append(result)
    unknown_counts = sum(x["new_send_attempts"] is None for x in results)
    known_sends = sum(
        x["new_send_attempts"] for x in results if type(x["new_send_attempts"]) is int
    )
    output = {
        "contract": "UNIT2_SAVED_EDIT_BATCH_RESULT_V1",
        "manifest_ref": copy.deepcopy(manifest_ref),
        "batch_id": manifest["batch_id"],
        "job_slot": slot,
        "completed_at": _now(clock).isoformat(),
        "execute_requested": execute,
        "results": results,
        "new_send_attempts": None if unknown_counts else known_sends,
        "known_new_send_attempts": known_sends,
        "unknown_send_attempt_case_count": unknown_counts,
        "new_delivered_pairs": sum(
            x["status"] == "PLANNED_OUTPUT_OBSERVED" and x["new_send_attempts"] == 1
            for x in results
        ),
        "verified_no_ops": sum(x["status"] == "NO_OP_DELIVERED" for x in results),
        "unresolved_original_effects_remain_fenced": fenced,
        "canvas_writes": 0,
        "retry_writes": False,
        "output_directory": str(run),
    }
    _save(run / "result.private.json", output)
    lines = [
        "# Saved whole-proposal EDIT batch",
        "",
        "This is unaccepted local staging; Canvas publication and teacher acceptance are separate.",
        "",
    ]
    lines += [
        f"- {x['case_id']}: {x['status']} ({x.get('reason', 'original once readback')})"
        for x in results
    ]
    lines += [
        "",
        f"New sends: {output['new_send_attempts']}; new verified pairs: {output['new_delivered_pairs']}; already-delivered no-ops: {output['verified_no_ops']}.",
        "",
    ]
    _save(run / "result.md", "\n".join(lines).encode())
    return output
