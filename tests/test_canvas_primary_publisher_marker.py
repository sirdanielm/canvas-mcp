"""Fictional Publisher verifies derived review remains source owned."""

import pytest
from test_gradebook import snapshot as snapshot
from test_gradebook_publish import system as system

from canvas_mcp.gradebook.client import GradebookError
from canvas_mcp.gradebook.publish import OwnerControls
from canvas_mcp.gradebook.scoped_review import validated_review


@pytest.mark.asyncio
async def test_publisher_retains_source_marker_and_rejects_generic_reuse(system):
    publisher, state, review_id, _ = system
    review = publisher.store.load("review", review_id)
    review["canvas_primary_publication_intent"] = {
        "contract": "FICTIONAL_SOURCE_INTENT"
    }
    source_id, _ = publisher.store.save("review", review)
    with pytest.raises(GradebookError, match="source owner controls"):
        await publisher.prepare("12", source_id)

    async def fresh(course, item):
        return None

    def check(course, item):
        return None

    def bind(plan):
        return {"kind": "FICTIONAL_OWNER"}

    prepared = await publisher.prepare(
        "12", source_id, owner_controls=OwnerControls(fresh, check, bind)
    )
    assert prepared["ready_for_confirmation"] is True
    derived = publisher.store.load("review", prepared["review_id"])
    assert derived["canvas_primary_source_review"]["source_review_id"] == source_id
    with pytest.raises(GradebookError):
        validated_review(
            publisher.store, "12", publisher.client.origin, prepared["review_id"]
        )
    with pytest.raises(GradebookError, match="cannot be prepared again"):
        await publisher.prepare("12", prepared["review_id"])
    with pytest.raises(GradebookError, match="cannot be prepared again"):
        await publisher.prepare(
            "12",
            prepared["review_id"],
            owner_controls=OwnerControls(fresh, check, bind),
        )
    assert state["puts"] == []
