"""Informational fingerprints of four loaded comment functions; no file I/O."""

from __future__ import annotations

import hashlib
import marshal
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from types import CodeType, FunctionType
from typing import Any

_SCHEMA = "LOADED_COMMENT_CODE_FINGERPRINT_V1"


def _normalized_code(code: CodeType) -> CodeType:
    """Remove only source locations, recursively; retain executable metadata."""
    return code.replace(
        co_filename="",
        co_firstlineno=1,
        co_linetable=b"",
        co_consts=tuple(
            _normalized_code(value) if type(value) is CodeType else value
            for value in code.co_consts
        ),
    )


def _function_sha256(function: Any) -> str:
    if type(function) is not FunctionType:
        raise TypeError("Expected a loaded Python function")
    return hashlib.sha256(marshal.dumps(_normalized_code(function.__code__))).hexdigest()


@dataclass(frozen=True)
class LoadedCommentRuntime:
    captured_at: str
    python_tag: str
    function_sha256: tuple[tuple[str, str], ...] = ()

    def as_dict(self) -> dict[str, Any]:
        """Return fresh containers; callers cannot mutate the captured tuple."""
        return {
            "schema": _SCHEMA,
            "status": "CAPTURED" if self.function_sha256 else "UNAVAILABLE",
            "captured_at": self.captured_at,
            "python_tag": self.python_tag,
            "scope": "listed_function_code_only",
            "coverage": {"expected_functions": 4, "captured_functions": len(self.function_sha256)},
            "function_sha256": dict(self.function_sha256),
        }


def capture_comment_runtime(publisher_type: type[Any]) -> LoadedCommentRuntime:
    """Capture once from actual bindings, never replacement modules or files.

    This covers only four listed code objects, not defaults, unlisted globals,
    dependencies, source files, runtime state, tool admission or authorization.
    Missing or uninspectable bindings yield informational UNAVAILABLE metadata.
    """
    captured_at = datetime.now(UTC).isoformat()
    python_tag = f"{sys.implementation.cache_tag}/marshal-{marshal.version}"
    try:
        prepare = publisher_type.prepare_comment
        parse_state = prepare.__globals__["parse_comment_state"]
        parser = parse_state.__globals__["parse_exact_observation"]
        functions = (
            ("publisher.prepare_comment", prepare),
            ("publisher.parse_comment_state", parse_state),
            ("protocol.parse_exact_observation", parser),
            ("protocol._observation_holds", parser.__globals__["_observation_holds"]),
        )
        fingerprints = tuple((name, _function_sha256(function)) for name, function in functions)
        return LoadedCommentRuntime(captured_at, python_tag, fingerprints)
    except Exception:
        # Diagnostic failure must never create an action gate or disclose values.
        return LoadedCommentRuntime(captured_at, python_tag)
