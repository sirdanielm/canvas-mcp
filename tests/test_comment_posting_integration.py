"""Automatic posting may leave submission.updated_at unchanged; never resend."""

import json
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from test_gradebook_publish import comment_system as comment_system
from test_gradebook_publish import prepared_comment
from test_gradebook_publish import snapshot as snapshot
from test_gradebook_publish import system as system

from canvas_mcp.gradebook import publish
from canvas_mcp.gradebook.client import GradebookError


def automatic_post(state):
    state["after_put"] = {
        "updated_at": state["submission"]["updated_at"],
        "posted_at": datetime.now(UTC).isoformat(),
    }


async def test_posting_with_unchanged_update_verifies_exactly_once(comment_system):
    publisher, state, _ = comment_system
    automatic_post(state)
    proposal = await prepared_comment(comment_system)
    result = await publisher.confirm_comment(
        "12", proposal["operation_id"], proposal["confirmation_token"]
    )
    assert result["counts"] == {"verified": 1} and len(state["forms"]) == 1
    receipt = publisher.store.load("receipt", result["readback_receipt_id"])
    assert receipt["comparison"]["stored_verified"] is True
    assert receipt["posting_observation_window"][0] == receipt["send_preflight_at"]
    assert state["submission"]["score"] == 10


async def test_actual_serializer_omits_update_at_every_stage(comment_system):
    publisher, state, _ = comment_system
    automatic_post(state)
    original = publisher.client.http._transport.handler

    def serializer(request):
        response = original(request)
        if "/submissions/" in request.url.path and response.status_code == 200:
            body = response.json()
            body.pop("updated_at", None)
            return httpx.Response(200, json=body)
        return response

    publisher.client.http._transport = httpx.MockTransport(serializer)
    proposal = await prepared_comment(comment_system)
    result = await publisher.confirm_comment(
        "12", proposal["operation_id"], proposal["confirmation_token"]
    )
    assert result["counts"] == {"verified": 1} and len(state["forms"]) == 1
    receipt = publisher.store.load("receipt", result["readback_receipt_id"])
    assert all(
        "updated_at" not in json.loads(receipt[key]["submission"]["body"])
        for key in ("before", "send_preflight", "after")
    )
    assert receipt["comparison"]["stored_verified"] is True


async def test_lost_response_posting_remains_observed_only(comment_system):
    publisher, state, _ = comment_system
    automatic_post(state)
    proposal = await prepared_comment(comment_system)
    state["behavior"] = "timeout_applied"
    result = await publisher.confirm_comment(
        "12", proposal["operation_id"], proposal["confirmation_token"]
    )
    assert result["counts"] == {"uncertain": 1}
    result = await publisher.reconcile_comment("12", proposal["operation_id"])
    assert result["counts"] == {"observed_applied": 1} and len(state["forms"]) == 1


@pytest.mark.parametrize(
    "posted_offset,expected", [(0, "verified"), (1000, "uncertain")]
)
async def test_later_reconciliation_respects_original_posting_window(
    comment_system, monkeypatch, posted_offset, expected
):
    publisher, state, _ = comment_system
    start = datetime.now(UTC)
    automatic_post(state)
    proposal = await prepared_comment(comment_system)
    state["fail_readback"] = True
    with pytest.raises(GradebookError):
        await publisher.confirm_comment(
            "12", proposal["operation_id"], proposal["confirmation_token"]
        )
    assert (
        publisher.ledger.operation(proposal["operation_id"])["items"][0][
            "response_comment_id"
        ]
        == "502"
    )
    state["fail_readback"] = False
    state["submission"]["posted_at"] = (
        start + timedelta(seconds=posted_offset)
    ).isoformat()

    class Later(datetime):
        @classmethod
        def now(cls, tz=None):
            return start + timedelta(seconds=2000)

    monkeypatch.setattr(publish, "datetime", Later)
    result = await publisher.reconcile_comment("12", proposal["operation_id"])
    assert result["counts"] == {expected: 1} and len(state["forms"]) == 1
    receipt = publisher.store.load("receipt", result["readback_receipt_id"])
    operation = publisher.ledger.operation(proposal["operation_id"])
    assert datetime.fromisoformat(
        receipt["posting_observation_window"][1]
    ).timestamp() == pytest.approx(operation["expires"] + 300, abs=0.000001)
    assert state["submission"]["score"] == 10
