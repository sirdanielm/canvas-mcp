"""Fictional end-to-end gate tests. No real records or transport."""

from typing import Any

import pytest
from test_gradebook import snapshot as snapshot
from test_gradebook_publish import comment_system as comment_system
from test_gradebook_publish import prepared_comment
from test_gradebook_publish import system as system

from canvas_mcp.gradebook import publish
from canvas_mcp.gradebook.client import GradebookError

COMPACT = "0123 | A2 | Core_A\nMC8: read-A | key-D | -2.5"


def narrative(envelope: Any) -> dict[str, Any]:
    return {
        **envelope,
        "category": "UNIT2_FEEDBACK",
        "comment": "0123 | A2 | Core_A\nMC8: Your response omits charge conservation. Explain the proton and neutron changes in detail.",
    }


def test_original_defect_long_unit2_narrative_must_be_rejected(
    comment_system: Any,
) -> None:
    _, _, envelope = comment_system
    envelope = narrative(envelope)
    with pytest.raises(GradebookError, match="compact feedback policy"):
        publish.comment_envelope(envelope, envelope["origin"], "12")


async def test_bad_format_creates_no_preview_token_or_send(comment_system: Any) -> None:
    publisher, state, envelope = comment_system
    envelope.update(narrative(envelope))
    with pytest.raises(GradebookError, match="compact feedback policy"):
        await prepared_comment(comment_system)
    assert state["forms"] == []
    assert not list(publisher.store.root.glob("push-*.json"))
    with publisher.ledger.connect() as db:
        assert db.execute("SELECT count(*) FROM operations").fetchone()[0] == 0


async def test_valid_compact_unit2_uses_existing_exact_preview_and_comment_route(
    comment_system: Any,
) -> None:
    publisher, state, envelope = comment_system
    envelope.update(category="UNIT2_FEEDBACK", comment=COMPACT)
    preview = await prepared_comment(comment_system)
    assert state["forms"] == []
    result = await publisher.confirm_comment(
        "12", preview["operation_id"], preview["confirmation_token"]
    )
    assert result["counts"] == {"verified": 1}
    # This existing fixture is on-paper. An upload attempt is not invented.
    assert state["forms"] == [
        {"comment[text_comment]": [COMPACT], "comment[group_comment]": ["false"]}
    ]


async def test_preexisting_noncompact_preview_cannot_bypass_new_guard(
    comment_system: Any, monkeypatch: Any
) -> None:
    publisher, state, envelope = comment_system
    envelope.update(narrative(envelope))
    validator = publish.inspect_unit2_body
    # A fictional old preview saved before adoption, not a live bypass.
    with monkeypatch.context() as old_version:
        old_version.setattr(publish, "inspect_unit2_body", lambda body: [])
        preview = await prepared_comment(comment_system)
    assert publish.inspect_unit2_body is validator
    with pytest.raises(GradebookError, match="compact feedback policy"):
        await publisher.confirm_comment(
            "12", preview["operation_id"], preview["confirmation_token"]
        )
    assert state["forms"] == []
    assert publisher.ledger.summary(preview["operation_id"])["counts"] == {"planned": 1}


def test_existing_unit1_full_feedback_is_not_silently_reinterpreted(
    comment_system: Any,
) -> None:
    _, _, envelope = comment_system
    assert envelope["category"] == "UNIT1_FEEDBACK"
    publish.comment_envelope(envelope, envelope["origin"], "12")
