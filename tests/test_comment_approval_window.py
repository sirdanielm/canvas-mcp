"""Synthetic transport checks for the teacher's bounded mobile approval window."""

import json
from typing import Any

import pytest
from fastmcp import Client
from test_gradebook_publish import prepared_comment

from canvas_mcp.gradebook.client import GradebookError
from canvas_mcp.gradebook.model import digest
from canvas_mcp.gradebook.publish import Publisher
from canvas_mcp.gradebook.server import create_server

pytest_plugins = ("test_gradebook", "test_gradebook_publish")


def with_window(comment_system: tuple[Any, ...], seconds: Any) -> tuple[Any, ...]:
    old, state, envelope = comment_system
    publisher = Publisher(
        old.client, old.store, old.ledger, comment_approval_seconds=seconds
    )
    return publisher, state, envelope


async def test_extended_comment_window_sends_once_after_ten_minutes(
    comment_system: tuple[Any, ...],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    publisher, state, envelope = with_window(comment_system, 1800)
    clock = [1000.0]
    monkeypatch.setattr("canvas_mcp.gradebook.ledger.time.time", lambda: clock[0])
    preview = await prepared_comment((publisher, state, envelope))
    operation = publisher.ledger.operation(preview["operation_id"])
    assert operation["expires"] == 2800.0
    assert preview["expires_in_seconds"] == 1800
    assert preview["expires_at"] == operation["expires"]
    clock[0] = 1900.0
    result = await publisher.confirm_comment(
        "12", preview["operation_id"], preview["confirmation_token"]
    )
    assert result["counts"] == {"verified": 1}
    assert len(state["forms"]) == 1
    assert state["forms"] == [
        {
            "comment[text_comment]": [envelope["comment"]],
            "comment[group_comment]": ["false"],
        }
    ]
    assert state["submission"]["score"] == 10 and state["submission"]["grade"] == "10"
    with pytest.raises(GradebookError, match="already consumed"):
        await publisher.confirm_comment(
            "12", preview["operation_id"], preview["confirmation_token"]
        )
    assert len(state["forms"]) == 1


async def test_extended_window_still_expires_without_send(
    comment_system: tuple[Any, ...],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    publisher, state, envelope = with_window(comment_system, 1800)
    clock = [1000.0]
    monkeypatch.setattr("canvas_mcp.gradebook.ledger.time.time", lambda: clock[0])
    preview = await prepared_comment((publisher, state, envelope))
    clock[0] = 2800.01
    with pytest.raises(GradebookError, match="expired"):
        await publisher.confirm_comment(
            "12", preview["operation_id"], preview["confirmation_token"]
        )
    assert state["forms"] == []


async def test_old_preview_and_score_window_are_not_extended(
    comment_system: tuple[Any, ...],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    old, state, envelope = comment_system
    clock = [1000.0]
    monkeypatch.setattr("canvas_mcp.gradebook.ledger.time.time", lambda: clock[0])
    preview = await prepared_comment(comment_system)
    configured, _, _ = with_window(comment_system, 1800)
    assert old.ledger.operation(preview["operation_id"])["expires"] == 1600.0
    numeric, _ = old.ledger.prepare("fictional-numeric", ["fictional-target"])
    assert old.ledger.operation(numeric)["expires"] == 1600.0
    with pytest.raises(GradebookError, match="score windows remain"):
        old.ledger.prepare(
            "fictional-numeric", ["other-target"], comment_approval_seconds=1800
        )
    with old.ledger.connect() as db:
        assert db.execute("SELECT COUNT(*) FROM operations").fetchone()[0] == 2
    clock[0] = 1600.01
    with pytest.raises(GradebookError, match="expired"):
        await configured.confirm_comment(
            "12", preview["operation_id"], preview["confirmation_token"]
        )
    assert state["forms"] == []


@pytest.mark.parametrize("seconds", [True, 0, 599, 1801, 1800.0, "1800"])
def test_comment_window_invalid_values_fail_before_network(
    comment_system: tuple[Any, ...],
    seconds: Any,
) -> None:
    _, state, _ = comment_system
    before = list(state["requests"])
    with pytest.raises(GradebookError, match="approval window"):
        with_window(comment_system, seconds)
    assert state["requests"] == before and state["forms"] == []


async def test_extended_window_keeps_final_target_check(
    comment_system: tuple[Any, ...],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    publisher, state, envelope = with_window(comment_system, 1800)
    clock = [1000.0]
    monkeypatch.setattr("canvas_mcp.gradebook.ledger.time.time", lambda: clock[0])
    preview = await prepared_comment((publisher, state, envelope))
    clock[0] = 1900.0
    state["submission"]["score"] = 11
    state["submission"]["grade"] = "11"
    with pytest.raises(GradebookError, match="target changed after preview"):
        await publisher.confirm_comment(
            "12", preview["operation_id"], preview["confirmation_token"]
        )
    assert publisher.ledger.summary(preview["operation_id"])["counts"] == {
        "not_sent": 1
    }
    assert state["forms"] == []


async def test_extended_window_keeps_exact_source_binding(
    comment_system: tuple[Any, ...],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    publisher, state, envelope = with_window(comment_system, 1800)
    clock = [1000.0]
    monkeypatch.setattr("canvas_mcp.gradebook.ledger.time.time", lambda: clock[0])
    preview = await prepared_comment((publisher, state, envelope))
    clock[0] = 1900.0
    envelope["comment"] += " Changed after preview."
    (publisher.store.root / "inbox/comment.json").write_text(json.dumps(envelope))
    with pytest.raises(GradebookError, match="Source comment proposal changed"):
        await publisher.confirm_comment(
            "12", preview["operation_id"], preview["confirmation_token"]
        )
    assert state["forms"] == []


async def test_registered_mcp_reports_exact_durable_extended_expiry(
    comment_system: tuple[Any, ...],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    publisher, state, envelope = comment_system
    monkeypatch.setattr("canvas_mcp.gradebook.ledger.time.time", lambda: 1000.0)
    (publisher.store.root / "inbox/comment.json").write_text(json.dumps(envelope))
    server = create_server(
        publisher.client,
        publisher.store,
        {"core": "12"},
        enable_comments=True,
        comment_approval_seconds=1800,
    )
    async with Client(server) as mcp:
        result = await mcp.call_tool(
            "prepare_gradebook_comment_push",
            {
                "course": "core",
                "comments_filename": "comment.json",
                "expected_envelope_sha256": digest(envelope),
            },
        )
    operation = publisher.ledger.operation(result.data["operation_id"])
    assert result.data["expires_in_seconds"] == 1800
    assert result.data["expires_at"] == operation["expires"] == 2800.0
    assert state["forms"] == []
