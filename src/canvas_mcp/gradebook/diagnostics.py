"""Allowlisted local telemetry. No provider text, identities or cell contents."""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import sqlite3
import stat
import subprocess
import sys
import time
from collections import Counter
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

UUID = re.compile(r"[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}")
STAGES = frozenset(
    {
        "startup",
        "poll",
        "claim",
        "initial_workbook",
        "prepare_core",
        "prepare_advanced",
        "fresh_workbook",
        "grade_batch",
        "readback",
        "verify",
        "finalize",
        "reconcile",
        "release",
    }
)
STATES = frozenset(
    {
        "IDLE",
        "READY",
        "BUSY",
        "CLAIMING",
        "CLAIMED",
        "PREPARED",
        "SENDING",
        "VERIFYING",
        "VERIFIED",
        "UNCERTAIN",
        "HELD",
        "RELEASED",
        "UNKNOWN",
    }
)
DIFFERENCES = frozenset(
    {
        "workbook_identity",
        "sheet_inventory",
        "sheet_properties",
        "cell_value",
        "cell_format",
        "cell_note",
        "cell_validation",
        "protections",
        "conditional_formats",
        "basic_filter",
        "row_metadata",
        "column_metadata",
    }
)
REASONS = {
    "Workbook changed while preparing; refresh held.": "workbook_changed",
    "Refresh request expired; no grade data was replaced.": "request_expired",
    "Refresh plan expired.": "plan_expired",
    "Native refresh readback differs; preserve evidence and do not retry writes.": "readback_differs",
    "Native output verification failed.": "readback_failed",
    "Google transport failed; no automatic write retry.": "transport_failed",
    "Canvas read failed; previous snapshot retained.": "transport_failed",
    "Canvas snapshot exceeded the time limit; previous snapshot retained.": "snapshot_timeout",
    "Google returned invalid JSON.": "invalid_json",
    "Canvas returned invalid JSON.": "invalid_json",
    "Trusted baseline course or origin differs.": "baseline_differs",
}
FAILURES = frozenset(REASONS.values()) | {
    "unknown",
    "transport_timeout",
    "transport_failed",
    "cancelled",
    "none",
}
_context: ContextVar[dict[str, str] | None] = ContextVar(
    "gradebook_diagnostic_context", default=None
)


def failure_code(error: BaseException | str) -> str:
    if isinstance(error, (httpx.TimeoutException, TimeoutError)):
        return "transport_timeout"
    if isinstance(error, httpx.HTTPError):
        return "transport_failed"
    # Exact matching only; arbitrary exception text is never returned.
    return REASONS.get(str(error), "unknown")


def http_class(status: int | None) -> str:
    if status is None:
        return "no_response"
    if status in {401, 403, 404, 429}:
        return {
            401: "unauthorized",
            403: "forbidden",
            404: "not_found",
            429: "throttled",
        }[status]
    return {2: "success", 3: "redirect", 4: "client_error", 5: "server_error"}.get(
        status // 100, "other"
    )


def safe_record(event: str, fields: dict[str, Any]) -> dict[str, Any]:
    if event not in {
        "startup",
        "stage_start",
        "stage_end",
        "http",
        "loop",
        "difference",
    }:
        return {}
    result: dict[str, Any] = {
        "v": 1,
        "event": event,
        "at": datetime.now(UTC).isoformat(),
    }
    choices = {
        "component": {"canvas", "google", "worker"},
        "operation": {
            "get",
            "oauth_refresh",
            "oauth_inspect",
            "metadata_read",
            "workbook_read",
            "sheets_batch",
        },
        "stage": STAGES,
        "state": STATES,
        "failure_code": FAILURES,
        "outcome": {"success", "failure", "cancelled"},
        "http_class": {
            http_class(i) for i in (None, 0, 200, 300, 400, 401, 403, 404, 429, 500)
        },
    }
    for key, allowed in choices.items():
        if isinstance(fields.get(key), str) and fields[key] in allowed:
            result[key] = fields[key]
    rid = fields.get("request_id")
    if isinstance(rid, str) and UUID.fullmatch(rid):
        result["request_id"] = rid
    for key in ("duration_ms", "attempt", "dropped"):
        value = fields.get(key)
        if (
            isinstance(value, (int, float))
            and not isinstance(value, bool)
            and math.isfinite(value)
            and 0 <= value <= 1e12
        ):
            result[key] = round(value, 3)
    for key, size in (
        ("source_revision", 40),
        ("source_digest", 64),
        ("python_digest", 64),
    ):
        value = fields.get(key)
        if isinstance(value, str) and re.fullmatch(
            r"[a-f0-9]{" + str(size) + "}", value
        ):
            result[key] = value
    version = fields.get("python_version")
    if isinstance(version, str) and re.fullmatch(r"\d{1,2}\.\d{1,2}\.\d{1,2}", version):
        result["python_version"] = version
    categories = fields.get("difference_categories")
    if isinstance(categories, list):
        result["difference_categories"] = sorted(
            {v for v in categories if isinstance(v, str) and v in DIFFERENCES}
        )
    return result


class Diagnostics:
    """Best-effort bounded private JSONL; telemetry cannot alter write outcomes."""

    def __init__(self, path: Path | None = None) -> None:
        self.path, self.dropped = path, 0
        self.last_failure_stage: str | None = None

    def emit(self, event: str, **fields: Any) -> None:
        if self.path is None:
            return
        descriptor: int | None = None
        try:
            record = safe_record(event, {**(_context.get() or {}), **fields})
            if not record:
                return
            parent = self.path.parent
            if any(p.is_symlink() for p in (parent, *parent.parents)):
                raise OSError
            parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            info = parent.stat()
            if info.st_uid != os.getuid() or info.st_mode & 0o077:
                raise OSError
            descriptor = os.open(
                self.path, os.O_APPEND | os.O_CREAT | os.O_WRONLY | os.O_NOFOLLOW, 0o600
            )
            info = os.fstat(descriptor)
            if (
                not stat.S_ISREG(info.st_mode)
                or info.st_uid != os.getuid()
                or info.st_mode & 0o077
                or info.st_size > 5_000_000
            ):
                raise OSError
            os.write(
                descriptor,
                (json.dumps(record, sort_keys=True, allow_nan=False) + "\n").encode(),
            )
        except Exception:
            self.dropped += 1
        finally:
            if descriptor is not None:
                try:
                    os.close(descriptor)
                except OSError:
                    self.dropped += 1

    @contextmanager
    def stage(self, stage: str, request_id: str | None = None) -> Iterator[None]:
        fields = dict(_context.get() or {})
        if stage in STAGES:
            fields["stage"] = stage
        if isinstance(request_id, str) and UUID.fullmatch(request_id):
            fields["request_id"] = request_id
        token = _context.set(fields)
        start, outcome, code = time.monotonic(), "success", "none"
        self.emit("stage_start")
        try:
            yield
        except BaseException as error:
            outcome = "failure" if isinstance(error, Exception) else "cancelled"
            code = failure_code(error) if outcome == "failure" else "cancelled"
            if self.last_failure_stage is None:
                self.last_failure_stage = fields.get("stage")
            raise
        finally:
            self.emit(
                "stage_end",
                outcome=outcome,
                failure_code=code,
                duration_ms=(time.monotonic() - start) * 1000,
            )
            _context.reset(token)


def runtime_pin(root: Path) -> dict[str, str]:
    """Capture startup source/interpreter bytes, without emitting filesystem paths."""
    result = {"python_version": ".".join(map(str, sys.version_info[:3]))}
    try:
        files = [
            root / "scripts/sdm_gradebook_worker.py",
            *sorted((root / "src/canvas_mcp/gradebook").glob("*.py")),
        ]
        digest = hashlib.sha256()
        for path in files:
            digest.update(
                path.relative_to(root).as_posix().encode() + b"\0" + path.read_bytes()
            )
        result["source_digest"] = digest.hexdigest()
        result["python_digest"] = hashlib.sha256(
            Path(sys.executable).read_bytes()
        ).hexdigest()
        process = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            timeout=5,
            env={**os.environ, "GIT_OPTIONAL_LOCKS": "0"},
        )
        revision = process.stdout.strip()
        if process.returncode == 0 and re.fullmatch(r"[a-f0-9]{40}", revision):
            result["source_revision"] = revision
    except (OSError, subprocess.SubprocessError):
        pass
    return result


def _age(value: Any) -> float | None:
    try:
        when = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if when.tzinfo is None:
            return None
        return round((datetime.now(UTC) - when).total_seconds(), 3)
    except (AttributeError, TypeError, ValueError):
        return None


def inspect_journal(
    state_dir: Path, workbook_id: str, request_id: str | None = None
) -> dict[str, Any]:
    """Read-only SQLite URI; never instantiate Store/RefreshJournal or clients."""
    root = state_dir / "refresh-worker"
    path = root / "operations.sqlite3"
    result: dict[str, Any] = {
        "source": "local_journal",
        "worker_running": "unverified",
        "journal_present": path.exists(),
        "ready": False,
        "recent_local_activity": False,
        "requests": [],
    }
    if any(p.is_symlink() for p in (path, root, state_dir)):
        raise ValueError("Diagnostic journal must not be a symlink.")
    if path.exists():
        if path.with_name(path.name + "-wal").exists():
            raise ValueError("A WAL journal requires a reviewed consistent snapshot.")
        db = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=5)
        try:
            db.execute("PRAGMA query_only=ON")
            rows = db.execute(
                "SELECT id,status,payload,updated FROM operations WHERE workbook=? ORDER BY updated DESC LIMIT 1000",
                (workbook_id,),
            )
            for rid, status, payload, updated in rows:
                if not UUID.fullmatch(rid) or (request_id and request_id != rid):
                    continue
                if not request_id and status in {"VERIFIED", "RELEASED"}:
                    continue
                value = json.loads(payload)
                code = value.get("failure_code")
                if not isinstance(code, str) or code not in FAILURES:
                    code = failure_code(value.get("failure_reason", ""))
                item = {
                    "request_id": rid,
                    "state": status if status in STATES else "UNKNOWN",
                    "age_seconds": _age(value.get("request", {}).get("created_at")),
                    "updated_age_seconds": _age(updated),
                }
                if status in {"HELD", "UNCERTAIN"}:
                    item["failure_code"] = code
                    reason = value.get("failure_reason")
                    if isinstance(reason, str) and reason in REASONS:
                        item["failure_reason"] = reason
                    if (
                        isinstance(value.get("failure_stage"), str)
                        and value["failure_stage"] in STAGES
                    ):
                        item["failure_stage"] = value["failure_stage"]
                    categories = value.get("difference_categories")
                    if isinstance(categories, list):
                        item["difference_categories"] = sorted(
                            {
                                v
                                for v in categories
                                if isinstance(v, str) and v in DIFFERENCES
                            }
                        )
                result["requests"].append(item)
        finally:
            db.close()
    states = Counter(item["state"] for item in result["requests"])
    result.update(
        unresolved=sum(
            n for s, n in states.items() if s not in {"VERIFIED", "RELEASED"}
        ),
        states=dict(states),
    )
    result["state"] = (
        "UNCERTAIN"
        if "UNCERTAIN" in states
        else (
            "HELD"
            if set(states)
            - {
                "CLAIMING",
                "CLAIMED",
                "PREPARED",
                "SENDING",
                "VERIFYING",
                "VERIFIED",
                "RELEASED",
            }
            else "IN_PROGRESS" if result["unresolved"] else "NO_LOCAL_HOLDS"
        )
    )
    log = root / "diagnostics.jsonl"
    if log.exists() and not log.is_symlink():
        with log.open("rb") as stream:
            stream.seek(max(0, log.stat().st_size - 65_536))
            lines = stream.read(65_536).splitlines()
        found_activity = False
        for line in reversed(lines):
            try:
                value = json.loads(line)
            except (ValueError, UnicodeDecodeError):
                continue
            if (
                isinstance(value, dict)
                and value.get("event") == "startup"
                and "startup_pin" not in result
            ):
                allowed = safe_record("startup", value)
                result["startup_pin"] = {
                    key: item
                    for key, item in allowed.items()
                    if key
                    in {
                        "source_revision",
                        "source_digest",
                        "python_digest",
                        "python_version",
                    }
                }
                result["startup_age_seconds"] = _age(value.get("at"))
            if (
                isinstance(value, dict)
                and value.get("event") == "loop"
                and not found_activity
            ):
                elapsed = _age(value.get("at"))
                result["local_activity_age_seconds"] = elapsed
                result["recent_local_activity"] = (
                    elapsed is not None and 0 <= elapsed <= 180
                )
                found_activity = True
    return result
