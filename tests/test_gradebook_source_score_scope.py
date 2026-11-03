"""Candidate routing regressions: synthetic artifacts and mock transport only.

Root reviews/adopts these tests. This audit file changes no repository source.
The legacy factory deliberately raises, reproducing the installed pin hold.
"""

import pytest
from fastmcp import Client
from test_gradebook_startup_owner_hold import (
    harness as harness,
)
from test_gradebook_startup_owner_hold import (
    make_server,
    raising_factory,
)

SYNTHETIC_LEGACY_REVIEW = "f" * 64


def no_factory_or_generic(events):
    return all(
        event[0] not in {"factory", "generic_prepare", "generic_confirm"}
        for event in events
    )


async def test_unrelated_review_prepares_despite_held_legacy_owner(harness):
    scope_calls = []

    def scope(course_id, review_id, items):
        scope_calls.append((course_id, review_id, items))
        return False

    server = make_server(
        harness,
        enable_push=True,
        unit1_score_handler_factory=raising_factory(harness.events),
        source_score_scope=scope,
    )
    async with Client(server) as mcp:
        result = await mcp.call_tool(
            "prepare_gradebook_push",
            {"course": "core", "review_id": harness.review_id},
        )
    assert result.data["operation_id"] == "synthetic-operation"
    assert scope_calls
    assert not any(event[0] == "factory" for event in harness.events)
    assert ("load", "review") in harness.events
    assert ("generic_prepare", harness.review_id) in harness.events
    assert harness.requests == []
    assert harness.consumed_tokens == 0


async def test_unrelated_operation_confirms_despite_held_legacy_owner(harness):
    server = make_server(
        harness,
        enable_push=True,
        unit1_score_handler_factory=raising_factory(harness.events),
        source_score_scope=lambda course_id, review_id, items: False,
    )
    async with Client(server) as mcp:
        result = await mcp.call_tool(
            "confirm_gradebook_push",
            {
                "course": "core",
                "operation_id": "synthetic-operation",
                "confirmation_token": "synthetic-exact-token",
            },
        )
    assert result.data["status"] == "synthetic-generic-confirm"
    assert not any(event[0] == "factory" for event in harness.events)
    assert ("load", "push") in harness.events
    assert ("generic_confirm", "synthetic-operation") in harness.events
    assert harness.consumed_tokens == 1
    assert harness.requests == []


@pytest.mark.parametrize("tool", ["prepare_gradebook_push", "confirm_gradebook_push"])
async def test_protected_scope_pin_hold_blocks_fallback_and_token(harness, tool):
    server = make_server(
        harness,
        enable_push=True,
        unit1_score_handler_factory=raising_factory(harness.events),
        source_score_scope=lambda course_id, review_id, items: True,
    )
    args = {"course": "core", "review_id": harness.review_id}
    if tool == "confirm_gradebook_push":
        args = {
            "course": "core",
            "operation_id": "synthetic-operation",
            "confirmation_token": "unconsumed-synthetic-token",
        }
    async with Client(server) as mcp:
        result = await mcp.call_tool(tool, args)
    assert "configuration pin mismatch" in result.data["error"]
    assert any(event[0] == "factory" for event in harness.events)
    assert not any(
        event[0] in {"generic_prepare", "generic_confirm"} for event in harness.events
    )
    assert harness.consumed_tokens == 0
    assert harness.requests == []


async def test_exact_legacy_reference_checks_owner_before_store_lookup(harness):
    def scope(course_id, review_id, items):
        return review_id == SYNTHETIC_LEGACY_REVIEW

    server = make_server(
        harness,
        enable_push=True,
        unit1_score_handler_factory=raising_factory(harness.events),
        source_score_scope=scope,
    )
    async with Client(server) as mcp:
        result = await mcp.call_tool(
            "prepare_gradebook_push",
            {"course": "core", "review_id": SYNTHETIC_LEGACY_REVIEW},
        )
    assert "configuration pin mismatch" in result.data["error"]
    assert harness.events == [("factory", "legacy")]
    assert harness.requests == []
    assert harness.consumed_tokens == 0


@pytest.mark.parametrize("value", [None, 0, 1, "False", [], {}])
@pytest.mark.parametrize("tool", ["prepare_gradebook_push", "confirm_gradebook_push"])
async def test_malformed_scope_result_is_held_before_fallback(harness, value, tool):
    server = make_server(
        harness,
        enable_push=True,
        unit1_score_handler_factory=raising_factory(harness.events),
        source_score_scope=lambda course_id, review_id, items: value,
    )
    args = {"course": "core", "review_id": harness.review_id}
    if tool == "confirm_gradebook_push":
        args = {
            "course": "core",
            "operation_id": "synthetic-operation",
            "confirmation_token": "unconsumed-synthetic-token",
        }
    async with Client(server) as mcp:
        result = await mcp.call_tool(tool, args)
    assert "error" in result.data
    assert no_factory_or_generic(harness.events)
    assert harness.consumed_tokens == 0
    assert harness.requests == []


async def test_raising_scope_callback_is_held_without_legacy_or_fallback(harness):
    def scope(course_id, review_id, items):
        raise RuntimeError("Synthetic unknown owner composition")

    server = make_server(
        harness,
        enable_push=True,
        unit1_score_handler_factory=raising_factory(harness.events),
        source_score_scope=scope,
    )
    async with Client(server) as mcp:
        result = await mcp.call_tool(
            "prepare_gradebook_push",
            {"course": "core", "review_id": harness.review_id},
        )
    assert "error" in result.data
    assert no_factory_or_generic(harness.events)
    assert harness.consumed_tokens == 0
    assert harness.requests == []
