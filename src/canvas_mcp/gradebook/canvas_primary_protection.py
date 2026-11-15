"""Fail-closed private target protection for Canvas-primary advisory staging.

A registry is protective only; it grants no academic, staging or publication
permission. Trusted application authority must independently verify its source,
monitored population and coverage on every preflight.
"""

from __future__ import annotations

import copy
import hashlib
import inspect
import json
import os
import re
import stat
from collections.abc import Callable
from pathlib import Path
from typing import Any, cast

from .client import GradebookError
from .model import grade_value

CONTRACT = "CANVAS_PRIMARY_TARGET_PROTECTION_V1"
HASH = re.compile(r"[a-f0-9]{64}\Z")
ID = re.compile(r"[1-9][0-9]*\Z")


def _need(value: Any, code: str) -> None:
    if not value:
        raise GradebookError(code)


def read_protection_registry(path: Path, expected_sha256: str) -> dict[str, Any]:
    """Load one owner-private pinned registry; malformed or changed bytes hold."""
    _need(
        isinstance(path, Path)
        and path.is_absolute()
        and type(expected_sha256) is str
        and HASH.fullmatch(expected_sha256)
        and not any(p.is_symlink() for p in (path, *path.parents)),
        "PROTECTION_REGISTRY_HELD",
    )
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(fd, "rb") as stream:
            before = os.fstat(stream.fileno())
            _need(
                stat.S_ISREG(before.st_mode)
                and before.st_uid == os.getuid()
                and before.st_mode & 0o077 == 0
                and 0 < before.st_size <= 4 * 1024 * 1024,
                "PROTECTION_REGISTRY_HELD",
            )
            data = stream.read(4 * 1024 * 1024 + 1)
            after = os.fstat(stream.fileno())

        def identity(st: os.stat_result) -> tuple[int, int, int, int, int]:
            return st.st_dev, st.st_ino, st.st_size, st.st_mtime_ns, st.st_ctime_ns

        _need(
            len(data) <= 4 * 1024 * 1024
            and identity(before) == identity(after) == identity(path.stat())
            and hashlib.sha256(data).hexdigest() == expected_sha256,
            "PROTECTION_REGISTRY_HELD",
        )

        def unique_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
            result: dict[str, Any] = {}
            for key, value in pairs:
                if key in result:
                    raise ValueError("duplicate key")
                result[key] = value
            return result

        registry = json.loads(
            data,
            object_pairs_hook=unique_pairs,
            parse_constant=lambda _: (_ for _ in ()).throw(ValueError()),
        )
    except (OSError, ValueError, TypeError):
        raise GradebookError("PROTECTION_REGISTRY_HELD") from None
    _validate_registry(registry)
    return cast(dict[str, Any], registry)


def _validate_registry(registry: Any) -> None:
    _need(
        type(registry) is dict
        and set(registry)
        == {
            "contract",
            "population_state",
            "population_evidence_sha256",
            "protected_students",
            "coverage",
            "protected_targets",
        }
        and registry["contract"] == CONTRACT
        and registry["population_state"] == "COMPLETE"
        and type(registry["population_evidence_sha256"]) is str
        and HASH.fullmatch(registry["population_evidence_sha256"]),
        "PROTECTION_REGISTRY_HELD",
    )
    students, coverage, targets = (
        registry[k] for k in ("protected_students", "coverage", "protected_targets")
    )
    _need(
        type(students) is list
        and bool(students)
        and type(coverage) is list
        and type(targets) is list,
        "PROTECTION_REGISTRY_HELD",
    )

    def fields(item: Any, keys: set[str], ids: tuple[str, ...]) -> bool:
        return (
            type(item) is dict
            and set(item) == keys
            and all(type(item[k]) is str and ID.fullmatch(item[k]) for k in ids)
            and type(item.get("evidence_sha256")) is str
            and bool(HASH.fullmatch(item["evidence_sha256"]))
        )

    _need(
        all(fields(x, {"user_id", "evidence_sha256"}, ("user_id",)) for x in students),
        "PROTECTION_REGISTRY_HELD",
    )
    _need(
        all(
            fields(
                x,
                {"course_id", "user_id", "state", "evidence_sha256"},
                ("course_id", "user_id"),
            )
            and x["state"] in {"COMPLETE", "INCOMPLETE"}
            for x in coverage
        ),
        "PROTECTION_REGISTRY_HELD",
    )
    _need(
        all(
            fields(
                x,
                {"course_id", "user_id", "assignment_id", "evidence_sha256"},
                ("course_id", "user_id", "assignment_id"),
            )
            for x in targets
        ),
        "PROTECTION_REGISTRY_HELD",
    )
    subjects = [x["user_id"] for x in students]
    scopes = [(x["course_id"], x["user_id"]) for x in coverage]
    cells = [(x["course_id"], x["user_id"], x["assignment_id"]) for x in targets]
    _need(
        len(subjects) == len(set(subjects))
        and len(scopes) == len(set(scopes))
        and len(cells) == len(set(cells))
        and all(x["user_id"] in subjects for x in coverage + targets),
        "PROTECTION_REGISTRY_HELD",
    )
    # Complete coverage cannot be inferred from an empty protected-target list.
    _need(
        all(
            x["state"] != "COMPLETE"
            or any(
                (t["course_id"], t["user_id"]) == (x["course_id"], x["user_id"])
                for t in targets
            )
            for x in coverage
        ),
        "PROTECTION_REGISTRY_HELD",
    )


def assert_target_unprotected(
    registry: dict[str, Any],
    target: dict[str, str],
    current_cell: dict[str, Any],
    authority: Callable[..., Any],
) -> None:
    """Reject exact protected targets and unresolved zeros of monitored students."""
    _validate_registry(registry)
    _need(
        type(target) is dict
        and set(target) == {"course_id", "user_id", "assignment_id"}
        and all(type(v) is str and ID.fullmatch(v) for v in target.values())
        and callable(authority),
        "PROTECTION_AUTHORITY_HELD",
    )
    try:
        result = authority(copy.deepcopy(registry), copy.deepcopy(target))
    except Exception:
        raise GradebookError("PROTECTION_AUTHORITY_HELD") from None
    if inspect.iscoroutine(result):
        result.close()
    _need(result is None, "PROTECTION_AUTHORITY_HELD")
    exact = [
        x
        for x in registry["protected_targets"]
        if all(x[k] == target[k] for k in target)
    ]
    _need(not exact, "PROTECTED_TARGET_HELD")
    monitored = any(
        x["user_id"] == target["user_id"] for x in registry["protected_students"]
    )
    if monitored:
        _need(
            type(current_cell) is dict and {"value", "grade"} <= set(current_cell),
            "PROTECTED_ZERO_PROVENANCE_HELD",
        )
        values = (
            grade_value(current_cell["value"]),
            grade_value(current_cell["grade"]),
        )
        zero_observed = any(
            type(value) in (int, float) and value == 0 for value in values
        )
    else:
        zero_observed = False
    if monitored and zero_observed:
        match = [
            x
            for x in registry["coverage"]
            if x["course_id"] == target["course_id"]
            and x["user_id"] == target["user_id"]
        ]
        _need(
            len(match) == 1 and match[0]["state"] == "COMPLETE",
            "PROTECTED_ZERO_PROVENANCE_HELD",
        )
