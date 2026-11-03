"""Fictional owner routing on the real POSIX Store/Ledger, with no network."""

from typing import Any

import pytest
from fastmcp import Client
from test_gradebook_startup_owner_hold import harness as harness
from test_gradebook_startup_owner_hold import make_server

from canvas_mcp.gradebook.client import GradebookError
from canvas_mcp.gradebook.owner_config import load_owner_policy


async def test_missing_private_policy_does_not_block_read_registration(harness: Any) -> None:
    app = make_server(harness, enable_push=True, **load_owner_policy().server_options())
    async with Client(app) as mcp:
        assert "get_canvas_gradebook" in {tool.name for tool in await mcp.list_tools()}
        result = await mcp.call_tool("prepare_gradebook_push", {"course": "core", "review_id": harness.review_id})
    assert "policy is required" in result.data["error"]
    assert harness.consumed_tokens == 0 and harness.requests == []



@pytest.mark.parametrize("answer", [None, 0, 1, "False", [], {}])
async def test_malformed_protected_scope_never_falls_back(harness: Any, answer: Any) -> None:
    app = make_server(harness, enable_push=True,
        protected_score_scope=lambda course, items: answer)
    async with Client(app) as mcp:
        result = await mcp.call_tool("prepare_gradebook_push", {"course": "core", "review_id": harness.review_id})
    assert "error" in result.data
    assert not any(event[0] == "generic_prepare" for event in harness.events)
    assert harness.consumed_tokens == 0 and harness.requests == []



async def test_private_protected_scope_refuses_unowned_operation_before_token(harness: Any) -> None:
    app = make_server(harness, enable_push=True,
        protected_score_scope=lambda course, items: course == "12")
    async with Client(app) as mcp:
        result = await mcp.call_tool("confirm_gradebook_push", {
            "course": "core", "operation_id": "synthetic-operation",
            "confirmation_token": "synthetic-token",
        })
    assert "error" in result.data
    assert harness.consumed_tokens == 0 and harness.requests == []



async def test_lazy_owned_prepare_and_expired_readback_keep_exact_owner(harness: Any) -> None:
    """Exercise the lifecycle independently of any private Unit1 owner source."""
    review, _ = harness.store.save("review", {"changes": [], "unit1_pair_score_intent": {}})
    owned_plan, _ = harness.store.save("push", {
        "course_id": "12", "origin": harness.client.origin, "items": [],
        "owner_binding": {"kind": "FICTIONAL_OWNER_BINDING"},
    })
    calls: list[str] = []
    current = True

    class Owner:
        def recognizes_review(self, review_id: str) -> bool:
            return review_id == review

        def matches_plan(self, course: str, plan: dict[str, Any]) -> bool:
            return course == "12" and plan.get("owner_binding") == {"kind": "FICTIONAL_OWNER_BINDING"}

        async def prepare(self, publisher: Any, course: str, review_id: str) -> dict[str, Any]:
            calls.append("prepare")
            harness.plan_id = owned_plan
            return {"operation_id": "synthetic-operation", "ready_for_confirmation": True}

        async def confirm(self, publisher: Any, course: str, operation: str, token: str) -> dict[str, Any]:
            calls.append("confirm")
            if not current:
                raise GradebookError("Fictional source approval expired")
            return {"status": "uncertain"}

        def status(self, course: str, operation: str) -> dict[str, Any]:
            calls.append("status")
            return {"status": "uncertain"}

        async def reconcile(self, publisher: Any, course: str, operation: str) -> dict[str, Any]:
            calls.append("reconcile")
            return {"status": "observed_applied", "retry_writes": False}

    def factory(publisher: Any) -> Owner:
        calls.append("factory")
        return Owner()

    app = make_server(harness, enable_push=True, unit1_pair_score_handler_factory=factory)
    assert calls == []
    async with Client(app) as mcp:
        prepared = await mcp.call_tool("prepare_gradebook_push", {"course": "core", "review_id": review})
        assert prepared.data["ready_for_confirmation"] is True
        assert calls == ["factory", "prepare"]
        arguments = {"course": "core", "operation_id": "synthetic-operation"}
        sent = await mcp.call_tool("confirm_gradebook_push", {**arguments, "confirmation_token": "synthetic-token"})
        assert sent.data["status"] == "uncertain"
        current = False
        status = await mcp.call_tool("get_gradebook_push_status", arguments)
        readback = await mcp.call_tool("reconcile_gradebook_push", arguments)
        denied = await mcp.call_tool("confirm_gradebook_push", {**arguments, "confirmation_token": "synthetic-token"})
    assert status.data["status"] == "uncertain"
    assert readback.data["status"] == "observed_applied"
    assert "expired" in denied.data["error"]
    assert calls == ["factory", "prepare", "confirm", "status", "reconcile", "confirm"]
    assert harness.consumed_tokens == 0 and harness.requests == []



async def test_missing_owner_policy_cannot_be_bypassed_by_score_batch_prepare(harness: Any) -> None:
    app = make_server(harness, enable_push=True, **load_owner_policy().server_options())
    async with Client(app) as mcp:
        result = await mcp.call_tool("prepare_gradebook_score_batch", {
            "course": "core", "review_id": harness.review_id,
        })
    assert "policy is required" in result.data["error"]
    assert harness.consumed_tokens == 0 and harness.requests == []
    assert not any(event[0] == "load" for event in harness.events)



@pytest.mark.parametrize("tool", ["authorize_gradebook_batch", "execute_gradebook_batch_chunk"])
async def test_private_scope_is_rechecked_before_batch_authorization_or_dispatch(harness: Any, monkeypatch: pytest.MonkeyPatch, tool: str) -> None:
    import canvas_mcp.gradebook.server as server_module

    class Batch:
        def __init__(self, publisher: Any) -> None:
            pass

        def _manifest(self, course: str, batch: str) -> tuple[str, dict[str, Any]]:
            return "synthetic-manifest", {"channel": "SCORE", "plan_ids": [harness.plan_id]}

        def authorize(self, *args: Any) -> None:
            pytest.fail("Source-owned batch must not consume an approval")

        async def execute_chunk(self, *args: Any) -> None:
            pytest.fail("Source-owned batch must not dispatch")

    monkeypatch.setattr(server_module, "BatchPublisher", Batch)
    app = make_server(harness, enable_push=True, **load_owner_policy().server_options())
    args = {"course": "core", "batch_id": "synthetic-batch"}
    args.update({"confirmation_token": "synthetic-token"} if tool.startswith("authorize") else {"chunk_index": 0})
    async with Client(app) as mcp:
        result = await mcp.call_tool(tool, args)
    assert "policy is required" in result.data["error"]
    assert harness.consumed_tokens == 0 and harness.requests == []
