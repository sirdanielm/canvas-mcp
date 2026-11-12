"""Source-only composition into the existing local EDIT owner; off by default.

Application composition must supply a trusted authority which freshly captures
Canvas source on every owner context read and synchronously revalidates its
retained evidence. This module creates no clients, permission, or writer.
"""

from __future__ import annotations

import copy
import inspect
from pathlib import Path
from types import ModuleType
from typing import Any

from .canvas_primary_review import (
    CONTRACT,
    _verified,
    prepare_primary_review_transfer,
    revalidate_primary_review_transfer,
)
from .client import GradebookError
from .localgrass_draft_edit import LocalGrAssDraftEditConnection
from .model import digest
from .proposal_edit_transfer import classify_proposal_readback
from .store import Store


def _need(value: Any, code: str) -> None:
    if not value:
        raise GradebookError(code)


class CanvasPrimaryEditConnection(LocalGrAssDraftEditConnection):
    """Advisory adapter for the existing owner and one-shot execution protocol."""

    contract = CONTRACT

    def __init__(
        self,
        *,
        store: Store,
        files: ModuleType,
        authority: Any,
        evidence: dict[str, Any],
        record: dict[str, Any],
        proposal: dict[str, Any],
        assignment_bindings_path: Path,
        expected_assignment_bindings_sha256: str,
        registry_path: Path,
        preservation: dict[str, Any] | None = None,
    ) -> None:
        _need(
            isinstance(store, Store)
            and isinstance(files, ModuleType)
            and all(
                callable(getattr(files, name, None))
                for name in (
                    "file_sha",
                    "load",
                    "local_path",
                    "private_directory",
                    "locked",
                    "write",
                )
            )
            and callable(getattr(authority, "refresh", None))
            and callable(getattr(authority, "assert_current", None)),
            "PRIMARY_INSTALLED_OWNERS_REQUIRED",
        )
        _need(
            all(
                isinstance(p, Path) and p.is_absolute()
                for p in (assignment_bindings_path, registry_path)
            ),
            "PRIMARY_EXPLICIT_BINDINGS_REQUIRED",
        )
        self.store, self.files, self.authority = store, files, authority
        self._source_fresh = False
        self.assignment_path, self.assignment_sha256 = (
            assignment_bindings_path,
            expected_assignment_bindings_sha256,
        )
        self.registry_path, self.preservation = (
            registry_path,
            copy.deepcopy(preservation),
        )
        self.current_attempt_review_binding = None
        self.evidence, self.record, self.proposal = (
            copy.deepcopy(evidence),
            copy.deepcopy(record),
            copy.deepcopy(proposal),
        )
        self._registered()

    async def refresh_source(self, canvas: Any) -> None:
        """Installed authority must perform its fresh authenticated Canvas GET."""
        self._source_fresh = False
        outcome = self.authority.refresh(canvas, copy.deepcopy(self.evidence))
        _need(inspect.isawaitable(outcome), "PRIMARY_FRESH_SOURCE_REQUIRED")
        result = await outcome
        _need(result is None, "PRIMARY_FRESH_SOURCE_REQUIRED")
        self._source_fresh = True
        try:
            _verified(self.evidence, self._assert_current)
        except Exception:
            self._source_fresh = False
            raise

    def _assert_current(self, evidence: dict[str, Any]) -> None:
        _need(self._source_fresh, "PRIMARY_FRESH_SOURCE_REQUIRED")
        result = self.authority.assert_current(evidence)
        if inspect.iscoroutine(result):
            result.close()
        _need(result is None, "PRIMARY_FRESH_SOURCE_REQUIRED")

    def _registered(self) -> dict[str, Any]:
        _need(
            self.files.file_sha(self.assignment_path) == self.assignment_sha256,
            "ASSIGNMENT_BINDINGS_CHANGED",
        )
        bindings = self.files.load(self.assignment_path)
        _need(
            self.files.file_sha(self.assignment_path) == self.assignment_sha256
            and type(bindings) is list,
            "ASSIGNMENT_BINDINGS_CHANGED",
        )
        found = [
            x
            for x in bindings
            if type(x) is dict
            and str(x.get("course_id")) == self.record.get("course_id")
            and str(x.get("assignment_id")) == self.record.get("assignment_id")
        ]
        _need(len(found) == 1, "EXACT_CENTRAL_ASSIGNMENT_REQUIRED")
        return copy.deepcopy(found[0])

    def assignment_targets(
        self, *, course_id: str, pin_binding: dict[str, Any]
    ) -> list[str]:
        _verified(self.evidence, self._assert_current)
        self._registered()
        _need(
            course_id == self.record.get("course_id")
            and pin_binding.get("by_pin", {}).get(self.record.get("pin"))
            == self.record.get("user_id"),
            "PRIMARY_TARGET_CHANGED",
        )
        return [self.record["assignment_id"]]

    def prepare(
        self,
        *,
        raw: dict[str, Any],
        binding: dict[str, Any],
        baseline: dict[str, Any],
        current: dict[str, Any],
        pin_binding: dict[str, Any],
    ) -> dict[str, Any]:
        target = self._registered()
        matches = [
            x
            for x in current["assignments"]
            if x.get("id") == self.record["assignment_id"]
        ]
        _need(len(matches) == 1, "ASSIGNMENT_METADATA_REQUIRED")
        target.update(
            assignment_metadata=matches[0].get("assignment_metadata"),
            assignment_metadata_sha256=matches[0].get("assignment_metadata_sha256"),
        )
        primary = prepare_primary_review_transfer(
            evidence=self.evidence,
            record=self.record,
            proposal=self.proposal,
            assignment_binding=target,
            authority=self._assert_current,
            raw=raw,
            binding=binding,
            baseline=baseline,
            current=current,
            pin_binding=pin_binding,
            preservation=self.preservation,
        )
        return {
            "contract": CONTRACT,
            "binding": copy.deepcopy(binding),
            "items": [
                {"key": self.record["user_id"] + ":" + self.record["assignment_id"]}
            ],
            "assignment_bindings_sha256": self.assignment_sha256,
            "primary_plan": primary,
            "transfer": copy.deepcopy(primary["transfer"]),
            "canvas_writes": 0,
            "sheets_writes": 0,
            "publication_allowed": False,
        }

    @staticmethod
    def validate_plan(plan: dict[str, Any], *, expected_plan_sha256: str) -> None:
        _need(
            type(plan) is dict
            and digest(plan) == expected_plan_sha256
            and plan.get("contract") == CONTRACT
            and plan.get("publication_allowed") is False
            and plan.get("canvas_writes") == plan.get("sheets_writes") == 0,
            "PRIMARY_OWNER_PLAN_CHANGED",
        )
        primary = plan.get("primary_plan", {})
        record = primary.get("transfer", {}).get("record", {})
        _need(
            plan.get("binding") == primary.get("transfer", {}).get("binding")
            and plan.get("transfer") == primary.get("transfer")
            and plan.get("items")
            == [
                {
                    "key": str(record.get("user_id"))
                    + ":"
                    + str(record.get("assignment_id"))
                }
            ],
            "PRIMARY_OWNER_PLAN_CHANGED",
        )

    def revalidate(
        self,
        plan: dict[str, Any],
        *,
        expected_plan_sha256: str,
        raw: dict[str, Any],
        current: dict[str, Any],
        pin_binding: dict[str, Any],
    ) -> None:
        self.validate_plan(plan, expected_plan_sha256=expected_plan_sha256)
        target = self._registered()
        _need(
            plan["assignment_bindings_sha256"] == self.assignment_sha256
            and all(
                plan["primary_plan"]["assignment_binding"].get(k) == v
                for k, v in target.items()
            )
            and plan["primary_plan"]["evidence"] == self.evidence,
            "PRIMARY_OWNER_SOURCE_CHANGED",
        )
        revalidate_primary_review_transfer(
            plan["primary_plan"],
            expected_plan_sha256=digest(plan["primary_plan"]),
            authority=self._assert_current,
            raw=raw,
            current=current,
            pin_binding=pin_binding,
        )

    @staticmethod
    def classify(
        plan: dict[str, Any], raw: dict[str, Any], *, expected_plan_sha256: str
    ) -> dict[str, Any]:
        CanvasPrimaryEditConnection.validate_plan(
            plan, expected_plan_sha256=expected_plan_sha256
        )
        return classify_proposal_readback(
            plan["transfer"], raw, expected_plan_sha256=digest(plan["transfer"])
        )
