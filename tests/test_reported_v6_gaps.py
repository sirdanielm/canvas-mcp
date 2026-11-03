"""Negative probes of author-reported V6 constraints; fictional transport only."""

from typing import Any

import pytest
from test_gradebook import snapshot as snapshot
from test_gradebook_publish import comment_system as comment_system
from test_gradebook_publish import prepared_comment
from test_gradebook_publish import system as system

from canvas_mcp.gradebook import publish
from canvas_mcp.gradebook.client import GradebookError


@pytest.mark.parametrize("stage", ["prepare", "confirm"])
@pytest.mark.parametrize(
    "body",
    [
        "0123 | A2 | Core_A\nFRQ1a: read-blank | key-a|b | -1",
        "0123 | A2 | Core_A\nMC999: read-A | key-D | -1",
        "0123 | A2 | Core_A\nFRQ1a: read-blank | key-" + r"\u007c" * 4 + " | -1",
        "0123 | A2 | Core_A\nFRQ1a: read-observed private physical observation | key-charge | -1",
    ],
)
async def test_reported_v6_invalid_body_must_not_create_preview(
    comment_system: Any, body: str, stage: str, monkeypatch: Any
) -> None:
    publisher, state, envelope = comment_system
    envelope.update(category="UNIT2_FEEDBACK", comment=body)
    if stage == "prepare":
        with pytest.raises(GradebookError, match="compact feedback policy"):
            await prepared_comment(comment_system)
    else:
        # Simulate an immutable preview saved before the format guard existed.
        with monkeypatch.context() as legacy:
            legacy.setattr(publish, "inspect_unit2_body", lambda body: [])
            preview = await prepared_comment(comment_system)
        with pytest.raises(GradebookError, match="compact feedback policy"):
            await publisher.confirm_comment(
                "12", preview["operation_id"], preview["confirmation_token"]
            )
    assert state["forms"] == []
