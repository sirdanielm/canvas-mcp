"""Source-owned route tests use fictional artifacts, no Canvas writes."""

import pytest
from fastmcp import Client
from test_gradebook_startup_owner_hold import harness as harness
from test_gradebook_startup_owner_hold import make_server

from canvas_mcp.gradebook.client import GradebookError


@pytest.mark.asyncio
async def test_primary_review_requires_recognizing_owner_not_generic(harness):
    review_id, _ = harness.store.save(
        "review", {"contract": "CANVAS_PRIMARY_VISUAL_ADVISORY_V1", "changes": []}
    )
    server = make_server(
        harness, enable_push=True, source_score_scope=lambda *args: False
    )
    async with Client(server) as mcp:
        result = await mcp.call_tool(
            "prepare_gradebook_push", {"course": "core", "review_id": review_id}
        )
    assert "exact Canvas-primary source owner" in result.data["error"]
    assert not any(event[0] == "generic_prepare" for event in harness.events)
    assert harness.requests == []


@pytest.mark.asyncio
async def test_primary_review_routes_exact_owned_prepare(harness):
    review_id, _ = harness.store.save(
        "review", {"contract": "CANVAS_PRIMARY_VISUAL_ADVISORY_V1", "changes": []}
    )
    calls = []

    class Owner:
        def recognizes_review(self, value):
            return value == review_id

        async def prepare(self, publisher, course, value):
            calls.append((course, value))
            return {
                "ready_for_confirmation": True,
                "publication_confirm_enabled": False,
                "canvas_writes": 0,
            }

        def protects_items(self, *args):
            return True

        def matches_plan(self, *args):
            return False

    server = make_server(
        harness, enable_push=True, unit1_pair_score_handler_factory=lambda _: Owner()
    )
    async with Client(server) as mcp:
        result = await mcp.call_tool(
            "prepare_gradebook_push", {"course": "core", "review_id": review_id}
        )
    assert (
        calls == [("12", review_id)]
        and result.data["publication_confirm_enabled"] is False
    )
    assert not any(event[0] == "generic_prepare" for event in harness.events)
    assert harness.requests == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "marker", ["canvas_primary_publication_intent", "canvas_primary_source_review"]
)
async def test_source_derived_review_cannot_fall_back_to_generic_or_batch(
    harness, marker
):
    from canvas_mcp.gradebook.scoped_review import validated_review

    review_id, _ = harness.store.save("review", {"changes": [], marker: {}})
    with pytest.raises(GradebookError):
        validated_review(harness.store, "12", harness.client.origin, review_id)
    server = make_server(
        harness, enable_push=True, source_score_scope=lambda *args: False
    )
    async with Client(server) as mcp:
        result = await mcp.call_tool(
            "prepare_gradebook_push", {"course": "core", "review_id": review_id}
        )
    assert "source-approved review" in result.data["error"]
    assert not any(event[0] == "generic_prepare" for event in harness.events)


@pytest.mark.asyncio
@pytest.mark.parametrize("action", ["prepare", "confirm"])
async def test_exclusive_policy_holds_unrelated_generic_even_if_delegate_does_not(
    harness, action
):
    from canvas_mcp.gradebook.canvas_primary_score_handler import (
        make_exclusive_primary_owner_policy,
    )

    harness.review_id, _ = harness.store.save(
        "review",
        {"changes": [{"user_id": "999", "assignment_id": "888", "proposed": 20}]},
    )
    harness.plan_id, _ = harness.store.save(
        "push",
        {
            "course_id": "12",
            "origin": harness.client.origin,
            "items": [{"user_id": "999", "assignment_id": "888", "proposed": 20}],
        },
    )

    class Delegate:
        def recognizes_review(self, review):
            return False

        def protects_items(self, course, items):
            return False

        def matches_plan(self, course, plan):
            return False

    policy = make_exclusive_primary_owner_policy(
        handler_factory=lambda publisher: Delegate(),
        protected_scope=lambda course, items: False,
    )
    server = make_server(harness, enable_push=True, **policy.server_options())
    async with Client(server) as mcp:
        if action == "prepare":
            await mcp.call_tool(
                "prepare_gradebook_push",
                {"course": "core", "review_id": harness.review_id},
            )
        else:
            await mcp.call_tool(
                "confirm_gradebook_push",
                {
                    "course": "core",
                    "operation_id": "synthetic-operation",
                    "confirmation_token": "token",
                },
            )
    assert not any(e[0] == "generic_" + action for e in harness.events)
    assert harness.consumed_tokens == 0 and harness.requests == []
