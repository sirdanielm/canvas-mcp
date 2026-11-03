"""Fictional trusted-owner binding checks, without inferring callback identity."""

import copy
from typing import Any

import pytest
from test_gradebook import snapshot as snapshot
from test_gradebook_publish import system as system

from canvas_mcp.gradebook.client import GradebookError
from canvas_mcp.gradebook.model import digest
from canvas_mcp.gradebook.publish import OwnerControls


def source_controls(system: Any) -> tuple[OwnerControls, dict[str, Any]]:
    publisher, _, _, _ = system
    authority: dict[str, Any] = {
        "current": {
            "contract": "FICTIONAL_SAVED_SOURCE_OWNER_V1",
            "source_revision": "fictional-source-r1",
            "approval_revision": "fictional-approved-selection-r1",
            "body_sha256": "a" * 64,
        },
        "plan_id": None,
        "binding_calls": 0,
        "checks": 0,
    }

    async def refresh(course_id: str, item: dict[str, Any]) -> None:
        return None

    def check(course_id: str, item: dict[str, Any]) -> None:
        authority["checks"] += 1
        if authority["plan_id"] is not None:
            retained = publisher.store.load("push", authority["plan_id"])
            if digest(authority["current"]) != digest(retained["owner_binding"]):
                raise GradebookError("Fictional retained source owner binding changed")

    def bind(plan: dict[str, Any]) -> dict[str, Any]:
        authority["binding_calls"] += 1
        return copy.deepcopy(authority["current"])

    return OwnerControls(refresh, check, bind), authority


@pytest.mark.parametrize(
    "changed", ["source_revision", "approval_revision", "body_sha256"]
)
async def test_current_owner_rejects_changed_frozen_binding_before_http(
    system: Any, changed: str
) -> None:
    publisher, state, review_id, _ = system
    controls, authority = source_controls(system)
    proposal = await publisher.prepare("12", review_id, owner_controls=controls)
    operation = publisher.ledger.operation(proposal["operation_id"])
    authority["plan_id"] = operation["plan_id"]
    original_plan = publisher.store.load("push", operation["plan_id"])
    authority["current"][changed] = "b" * 64
    with pytest.raises(GradebookError, match="retained source owner binding changed"):
        await publisher.confirm(
            "12",
            proposal["operation_id"],
            proposal["confirmation_token"],
            owner_controls=controls,
        )
    assert state["puts"] == []
    assert publisher.store.load("push", operation["plan_id"]) == original_plan
    assert publisher.ledger.summary(proposal["operation_id"])["counts"] == {
        "not_sent": 1
    }
    assert authority["binding_calls"] == 1


async def test_confirmation_keeps_prepare_only_binder_separate_from_current_authority(
    system: Any,
) -> None:
    publisher, state, review_id, _ = system
    preparation, authority = source_controls(system)
    proposal = await publisher.prepare("12", review_id, owner_controls=preparation)
    operation = publisher.ledger.operation(proposal["operation_id"])
    authority["plan_id"] = operation["plan_id"]
    original_plan = publisher.store.load("push", operation["plan_id"])

    def prepare_only(plan: dict[str, Any]) -> dict[str, Any]:
        raise AssertionError(
            "Preparing a new owner binding during confirm is forbidden"
        )

    confirmation = OwnerControls(
        preparation.fresh_before_context,
        preparation.check_before_send,
        prepare_only,
    )
    result = await publisher.confirm(
        "12",
        proposal["operation_id"],
        proposal["confirmation_token"],
        owner_controls=confirmation,
    )
    assert result["counts"] == {"verified": 1}
    assert state["puts"] == [{"submission": {"posted_grade": "20"}}]
    assert publisher.store.load("push", operation["plan_id"]) == original_plan
    assert authority["binding_calls"] == 1
    assert authority["checks"] >= 2
