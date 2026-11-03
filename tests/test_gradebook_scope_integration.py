"""Independent synthetic routing findings and actual-Publisher integration."""

import pytest
from fastmcp import Client
from test_gradebook import snapshot as snapshot
from test_gradebook_publish import system as system
from test_gradebook_startup_owner_hold import harness as harness
from test_gradebook_startup_owner_hold import make_server

from canvas_mcp.gradebook.client import GradebookError
from canvas_mcp.gradebook.server import create_server


@pytest.mark.parametrize("marker", ["manual_four_authority", "owner_binding"])
async def test_unknown_owner_marker_in_review_cannot_fall_back(harness, marker):
    review_id, _ = harness.store.save(
        "review", {"changes": [], marker: {"kind": "synthetic"}}
    )
    server = make_server(
        harness,
        enable_push=True,
        unit1_score_handler_factory=lambda publisher: None,
        source_score_scope=lambda course_id, review_id, items: False,
    )
    async with Client(server) as mcp:
        result = await mcp.call_tool(
            "prepare_gradebook_push", {"course": "core", "review_id": review_id}
        )
    assert "error" in result.data
    assert not any(event[0] == "generic_prepare" for event in harness.events)
    assert harness.consumed_tokens == 0 and harness.requests == []


async def test_unknown_pair_marker_in_plan_cannot_fall_back(harness):
    harness.plan_id, _ = harness.store.save(
        "push",
        {
            "course_id": "12",
            "origin": harness.client.origin,
            "items": [],
            "unit1_pair_score_intent": {"kind": "synthetic"},
        },
    )
    server = make_server(
        harness,
        enable_push=True,
        unit1_score_handler_factory=lambda publisher: None,
        source_score_scope=lambda course_id, review_id, items: False,
    )
    async with Client(server) as mcp:
        result = await mcp.call_tool(
            "confirm_gradebook_push",
            {
                "course": "core",
                "operation_id": "synthetic-operation",
                "confirmation_token": "unconsumed-synthetic-token",
            },
        )
    assert "error" in result.data
    assert not any(event[0] == "generic_confirm" for event in harness.events)
    assert harness.consumed_tokens == 0 and harness.requests == []


async def test_actual_publisher_fresh_compare_mock_put_and_readback_skip_unrelated_owner(
    system,
):
    publisher, state, review_id, _ = system
    factory_calls = []

    def held_factory(publisher):
        factory_calls.append(True)
        raise GradebookError("Synthetic legacy owner configuration pin hold")

    server = create_server(
        publisher.client,
        publisher.store,
        {"core": "12"},
        enable_push=True,
        unit1_score_handler_factory=held_factory,
        source_score_scope=lambda course_id, review_id, items: False,
    )
    try:
        async with Client(server) as mcp:
            prepared = await mcp.call_tool(
                "prepare_gradebook_push", {"course": "core", "review_id": review_id}
            )
            assert prepared.data["ready_for_confirmation"] is True
            assert publisher.client.snapshot.await_count == 1
            assert state["puts"] == [] and factory_calls == []
            before_confirm = len(state["requests"])
            result = await mcp.call_tool(
                "confirm_gradebook_push",
                {
                    "course": "core",
                    "operation_id": prepared.data["operation_id"],
                    "confirmation_token": prepared.data["confirmation_token"],
                },
            )
        assert result.data["counts"] == {"verified": 1}
        assert len(state["puts"]) == 1 and factory_calls == []
        assert len(state["requests"]) > before_confirm
        assert state["requests"][-1][0] == "GET"
    finally:
        await publisher.client.close()
