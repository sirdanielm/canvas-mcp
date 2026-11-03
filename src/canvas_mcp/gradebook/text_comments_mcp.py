"""Opt-in MCP surface for server-owned, already reviewed text-only releases.

No raw body, target, grade, rubric, filesystem path or transport is tool input.
The owner injects the existing guarded protocol and its synchronous current
source/authority check. Nothing is registered or patched while disabled.
"""

from __future__ import annotations

import asyncio
import inspect
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any, Protocol

from fastmcp import FastMCP
from mcp.types import ToolAnnotations


class TextDelivery(Protocol):
    manifest_ref: dict[str, Any]

    def _authority(self, manifest: dict[str, Any]) -> list[dict[str, Any]]: ...

    async def prepare(self) -> dict[str, Any]: ...

    async def confirm(
        self,
        plan_id: str,
        op: str,
        token: str,
        *,
        enabled: bool = False,
        reviewed_plan_sha256: str = "",
    ) -> dict[str, Any]: ...

    async def reconcile(self, plan_id: str, op: str) -> dict[str, Any]: ...


@dataclass(frozen=True)
class QualifiedTextRelease:
    """Trusted server configuration, never deserialized from MCP arguments.

    current_control_check must authenticate the sealed Root release and check
    its actual source/physical/journal controls. It is synchronous so it can
    run after the protocol's last awaited GET and immediately before PUT.
    Reconciliation intentionally does not renew an expired write authority.
    """

    delivery: TextDelivery
    current_control_check: Callable[[], Any]


def _check_current(check: Callable[[], Any]) -> None:
    result = check()
    if result is not None:
        if inspect.iscoroutine(result):
            result.close()
        raise ValueError("SYNCHRONOUS_CURRENT_CONTROL_CHECK_REQUIRED")


def register_submission_comment_tools(
    server: FastMCP,
    releases: Mapping[str, QualifiedTextRelease] | None = None,
    *,
    enabled: bool = False,
) -> None:
    """Register three comment-only tools only after owner opt-in.

    The same lock serializes all calls on this registered comment surface,
    preserving the existing protocol's temporary HTTP request hooks. No
    concurrency, retry, token renewal, grade or rubric path is introduced.
    """
    if enabled is not True:
        return
    if not releases:
        raise ValueError("REVIEWED_TEXT_RELEASE_CONFIGURATION_REQUIRED")

    configured = dict(releases)
    seen: set[int] = set()
    snapshots: dict[str, dict[str, Any]] = {}
    for release_id, release in configured.items():
        if (
            type(release_id) is not str
            or re.fullmatch(r"[a-f0-9]{64}", release_id) is None
            or not isinstance(release, QualifiedTextRelease)
            or not callable(release.current_control_check)
            or inspect.iscoroutinefunction(release.current_control_check)
            or inspect.iscoroutinefunction(
                type(release.current_control_check).__call__
            )  # noqa: B004 - inspect the already-callable object's async implementation
        ):
            raise ValueError("EXACT_REVIEWED_TEXT_RELEASE_REQUIRED")
        ref = release.delivery.manifest_ref
        if (
            type(ref) is not dict
            or set(ref) != {"path", "sha256", "bytes"}
            or ref["sha256"] != release_id
            or type(ref["path"]) is not str
            or type(ref["bytes"]) is not int
            or ref["bytes"] <= 0
            or id(release.delivery) in seen
        ):
            raise ValueError("EXACT_REVIEWED_TEXT_RELEASE_REQUIRED")
        seen.add(id(release.delivery))
        snapshots[release_id] = dict(ref)

    # Wrap only configured instances, never the library class or module seal.
    # The reviewed protocol calls _authority after its final awaited GET.
    for release in configured.values():
        original = release.delivery._authority
        current = release.current_control_check

        def checked_authority(
            manifest: dict[str, Any],
            _original: Callable[[dict[str, Any]], list[dict[str, Any]]] = original,
            _current: Callable[[], Any] = current,
        ) -> list[dict[str, Any]]:
            loaded = _original(manifest)
            _check_current(_current)
            return loaded

        release.delivery._authority = checked_authority  # type: ignore[method-assign]

    lock = asyncio.Lock()

    def resolve(release_id: str) -> QualifiedTextRelease:
        release = configured.get(release_id)
        if release is None or release.delivery.manifest_ref != snapshots[release_id]:
            raise ValueError("UNKNOWN_OR_CHANGED_REVIEWED_TEXT_RELEASE")
        return release

    @server.tool(annotations=ToolAnnotations(read_only_hint=False))
    async def prepare_submission_comments(release_id: str) -> dict[str, Any]:
        """Prepare a configured audited release; no Canvas write; private state is written.

        Existing exact matching comments return NO_OP. A prepared private
        plan, durable claim and finite one-use token are not authorization
        to confirm an unreviewed plan. Never provide student rows in chat.
        """
        async with lock:
            try:
                release = resolve(release_id)
                _check_current(release.current_control_check)
                return await release.delivery.prepare()
            except Exception:
                return {
                    "error": "Comment preparation held; no Canvas write.",
                    "canvas_writes": 0,
                    "retry_writes": False,
                }

    @server.tool(
        annotations=ToolAnnotations(
            read_only_hint=False,
            destructive_hint=True,
            idempotent_hint=False,
        )
    )
    async def confirm_submission_comments(
        release_id: str,
        plan_id: str,
        operation_id: str,
        confirmation_token: str,
        enabled: bool = False,
        reviewed_plan_sha256: str = "",
    ) -> dict[str, Any]:
        """Confirm the exact independently reviewed, authorized text-only plan.

        Requires owner opt-in plus an actual reviewed plan and one-use token.
        Sends no grade/rubric/PDF fields. An uncertain result must be inspected
        and reconciled by GET only; this tool never automatically retries.
        """
        async with lock:
            try:
                release = resolve(release_id)
                _check_current(release.current_control_check)
                return await release.delivery.confirm(
                    plan_id,
                    operation_id,
                    confirmation_token,
                    enabled=enabled,
                    reviewed_plan_sha256=reviewed_plan_sha256,
                )
            except Exception:
                return {
                    "error": "Comment confirmation held; inspect durable state before any action.",
                    "operation_id": operation_id,
                    "retry_writes": False,
                    "reconcile_only": True,
                }

    @server.tool(annotations=ToolAnnotations(read_only_hint=False))
    async def reconcile_submission_comments(
        release_id: str,
        plan_id: str,
        operation_id: str,
    ) -> dict[str, Any]:
        """Reconcile by Canvas GET only, even after expiry; private state is written.

        No new token, source activation, reservation deletion or replay.
        """
        async with lock:
            try:
                release = resolve(release_id)
                return await release.delivery.reconcile(plan_id, operation_id)
            except Exception:
                return {
                    "error": "Comment reconciliation held; retain original operation.",
                    "operation_id": operation_id,
                    "retry_writes": False,
                }
