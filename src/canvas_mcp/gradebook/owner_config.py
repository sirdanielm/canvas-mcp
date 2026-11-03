"""Explicit private owner-policy composition; no identities or default writer.

The operator may supply a reviewed local Python adapter and its exact SHA-256.
This is trusted startup configuration, never an MCP argument or new authority.
Without it score sends stay held while ordinary read tools remain available.
"""

from __future__ import annotations

import hashlib
import importlib.util
import os
import re
import stat
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .client import GradebookError


@dataclass(frozen=True)
class OwnerPolicy:
    """Trusted callables; private target bindings belong outside public source."""

    source_score_scope: Callable[[str, str | None, Any], bool]
    protected_score_scope: Callable[[str, Any], bool]
    score_handler_factory: Callable[[Any], Any] | None = None
    pair_score_handler_factory: Callable[[Any], Any] | None = None
    comment_release_factory: Callable[[Any], Any] | None = None

    def server_options(
        self, *, enable_qualified_comments: bool = False
    ) -> dict[str, Any]:
        return {
            "unit1_score_handler_factory": self.score_handler_factory,
            "unit1_pair_score_handler_factory": self.pair_score_handler_factory,
            "source_score_scope": self.source_score_scope,
            "protected_score_scope": self.protected_score_scope,
            "comment_release_factory": self.comment_release_factory,
            "enable_qualified_comments": (
                enable_qualified_comments is True
                and self.comment_release_factory is not None
            ),
        }


def _held_owner(_publisher: Any) -> Any:
    raise GradebookError("Private source-owner policy is required for score writes.")


def _all_scores(_course: str, _review: str | None, _items: Any) -> bool:
    return True


def _no_extra_targets(_course: str, _items: Any) -> bool:
    return False


def private_owner_adapter_supported() -> bool:
    """The absent-adapter policy stays portable; private file loading does not."""
    return os.name == "posix" and all(
        hasattr(os, name) for name in ("O_NOFOLLOW", "getuid")
    )


def load_owner_policy(
    path: Path | None = None, expected_sha256: str | None = None
) -> OwnerPolicy:
    """Load only explicitly pinned, private, operator-owned startup source.

    No configuration means a held score owner, not a generic fallback. Adapter
    functions must still enforce current source, approval and durable history;
    this source pin establishes integrity only. No credentials are supplied.
    """
    if path is None and expected_sha256 is None:
        return OwnerPolicy(_all_scores, _no_extra_targets, _held_owner)
    if (
        not isinstance(path, Path)
        or not path.is_absolute()
        or ".." in path.parts
        or not isinstance(expected_sha256, str)
        or re.fullmatch(r"[a-f0-9]{64}", expected_sha256) is None
    ):
        raise GradebookError(
            "Exact private owner adapter path and SHA-256 are required."
        )
    if not private_owner_adapter_supported():
        raise GradebookError(
            "Private owner adapters require POSIX O_NOFOLLOW/getuid protection."
        )
    if any(part.is_symlink() for part in (path, *path.parents)):
        raise GradebookError("Private owner adapter must not use symlinks.")
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
        with os.fdopen(fd, "rb") as stream:
            before = os.fstat(stream.fileno())
            if (
                not stat.S_ISREG(before.st_mode)
                or before.st_uid != os.getuid()
                or stat.S_IMODE(before.st_mode) != 0o600
                or before.st_nlink != 1
                or not 0 < before.st_size <= 1_000_000
            ):
                raise GradebookError(
                    "Private owner adapter ownership or permissions are invalid."
                )
            raw = stream.read(1_000_001)
            after = os.fstat(stream.fileno())
            named = path.stat(follow_symlinks=False)

        def facts(value: os.stat_result) -> tuple[int, ...]:
            return (
                value.st_dev,
                value.st_ino,
                value.st_mode,
                value.st_uid,
                value.st_nlink,
                value.st_size,
                value.st_mtime_ns,
                value.st_ctime_ns,
            )

        if (
            facts(before) != facts(after)
            or facts(after) != facts(named)
            or len(raw) != before.st_size
            or hashlib.sha256(raw).hexdigest() != expected_sha256
        ):
            raise GradebookError("Private owner adapter source changed.")
        name = "_canvas_private_owner_" + expected_sha256
        spec = importlib.util.spec_from_file_location(name, path)
        if spec is None:
            raise GradebookError("Private owner adapter cannot be loaded.")
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        try:
            exec(compile(raw, str(path), "exec"), module.__dict__)
            factory = getattr(module, "create_owner_policy", None)
            if not callable(factory):
                raise GradebookError("Private owner adapter factory is unavailable.")
            policy = factory()
        except Exception:
            # Adapter exceptions may include private evidence or source values.
            raise GradebookError(
                "Private owner adapter initialization failed."
            ) from None
        finally:
            sys.modules.pop(name, None)
    except GradebookError:
        raise
    except Exception:
        raise GradebookError("Private owner adapter is unavailable.") from None
    if (
        type(policy) is not OwnerPolicy
        or not callable(policy.source_score_scope)
        or not callable(policy.protected_score_scope)
        or any(
            value is not None and not callable(value)
            for value in (
                policy.score_handler_factory,
                policy.pair_score_handler_factory,
                policy.comment_release_factory,
            )
        )
    ):
        raise GradebookError("Private owner adapter policy is invalid.")
    return policy
