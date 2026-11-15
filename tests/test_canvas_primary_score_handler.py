"""Fictional source-owned Publisher preparation; confirmation is disabled."""

import copy
import json
from contextlib import contextmanager
from pathlib import Path

import pytest
from test_canvas_primary_owner import connection as connection
from test_canvas_primary_review import case as case
from test_gradebook import snapshot as snapshot
from test_gradebook_native import binding as binding
from test_gradebook_native import raw_from_state

from canvas_mcp.gradebook import native
from canvas_mcp.gradebook.canvas_primary_score_handler import CanvasPrimaryScoreHandler
from canvas_mcp.gradebook.client import GradebookError
from canvas_mcp.gradebook.localgrass_edit_owner import LocalGrAssEditOwner


@pytest.fixture
async def handler_fixture(connection, case, tmp_path):
    await connection.refresh_source("fictional-canvas")
    stage = connection.prepare(
        **{k: case[k] for k in ("raw", "binding", "baseline", "current", "pin_binding")}
    )
    stage_id, _ = connection.store.save("review", stage)
    directory = tmp_path / "history" / stage_id
    directory.mkdir(parents=True)
    (directory / "plan.json").write_text(json.dumps(stage))
    receipt = {
        "contract": connection.contract,
        "plan_id": stage_id,
        "status": "PLANNED_OUTPUT_OBSERVED",
        "canvas_writes": 0,
        "publication_allowed": False,
    }
    (directory / "receipt-001.json").write_text(json.dumps(receipt))
    state = native._state(case["raw"])
    update = stage["transfer"]["requests"][0]["updateCells"]
    start = update["start"]
    state["sheets"][start["sheetId"]]["cells"][
        f"{start['rowIndex']}:{start['columnIndex']}"
    ].update(update["rows"][0]["values"][0])
    raw = raw_from_state(state)

    class Journal:
        @contextmanager
        def exclusive(self):
            yield

    owner = object.__new__(LocalGrAssEditOwner)
    owner.connection = connection
    owner.canvas = "fictional-canvas"
    owner.binding = case["binding"]
    owner.output_root = tmp_path / "history"
    owner.journal = Journal()
    owner._check_owner = lambda: None

    async def current_context():
        await connection.refresh_source(owner.canvas)
        return {
            "raw": copy.deepcopy(raw),
            "current": copy.deepcopy(case["current"]),
            "pin_binding": copy.deepcopy(case["pin_binding"]),
        }

    owner._context = current_context

    class Publisher:
        client = owner.canvas
        store = connection.store
        prepare_calls = 0

        async def prepare(self, course, review_id, *, owner_controls):
            self.prepare_calls += 1
            review = self.store.load("review", review_id)
            item = copy.deepcopy(review["changes"][0])
            await owner_controls.fresh_before_context(course, item)
            owner_controls.check_before_send(course, item)
            plan = {
                "course_id": course,
                "origin": case["current"]["origin"],
                "items": [item],
            }
            plan["owner_binding"] = owner_controls.bind_plan(plan)
            return {
                "ready_for_confirmation": True,
                "fake_plan": plan,
                "canvas_writes": 0,
            }

    pub = Publisher()

    def verify_stage(p, r):
        if p != stage or r != receipt:
            raise ValueError("unverified stage")

    def verify_scope(intent):
        if (
            intent["target"]["user_id"] != "101"
            or intent["approval_scope"] != "LOWER_OR_BLANK_ONLY"
        ):
            raise ValueError("unapproved")

    handler = CanvasPrimaryScoreHandler(
        publisher=pub,
        owner=owner,
        stage_plan_id=stage_id,
        verify_stage_receipt=verify_stage,
        verify_approval_scope=verify_scope,
    )
    return handler, pub, stage_id, case


@pytest.mark.asyncio
async def test_owned_prepare_routes_exact_intent_but_confirm_is_disabled(
    handler_fixture,
):
    handler, publisher, stage_id, case = handler_fixture
    assert handler.recognizes_review(stage_id)
    result = await handler.prepare(publisher, case["record"]["course_id"], stage_id)
    assert result["ready_for_confirmation"] is False and result["preview_ready"] is True
    assert result["publication_confirm_enabled"] is False
    assert "confirmation_token" not in result and publisher.prepare_calls == 0
    assert result["canvas_writes"] == 0
    preview = Path(result["review_file"]).read_text()
    assert (
        "Unapproved source-based advisory" in preview
        and "No Canvas grade or comment was sent" in preview
    )
    assert "teacher-entered" not in preview and "Canvas at review" in preview
    assert not list(publisher.store.root.glob("push-*.json"))
    with pytest.raises(
        GradebookError, match="PRIMARY_PUBLICATION_CONFIRM_NOT_INSTALLED"
    ):
        await handler.confirm(
            publisher, case["record"]["course_id"], "fake-operation", "fake-token"
        )


@pytest.mark.asyncio
async def test_missing_actual_scope_or_wrong_review_holds(handler_fixture):
    handler, publisher, stage_id, case = handler_fixture
    with pytest.raises(GradebookError):
        await handler.prepare(publisher, case["record"]["course_id"], "0" * 64)
    handler.verify_approval_scope = lambda _: True
    with pytest.raises(GradebookError, match="PRIMARY_PUBLICATION_APPROVAL_HELD"):
        await handler.prepare(publisher, case["record"]["course_id"], stage_id)


def test_opt_in_policy_never_bypasses_generic_owner_gate():
    from canvas_mcp.gradebook.canvas_primary_score_handler import (
        make_exclusive_primary_owner_policy,
    )

    def factory(publisher):
        return None

    def protected(course, items):
        return False

    policy = make_exclusive_primary_owner_policy(
        handler_factory=factory, protected_scope=protected
    )
    assert policy.source_score_scope("12", None, None) is True
    assert policy.pair_score_handler_factory is not None
    with pytest.raises(GradebookError):
        policy.pair_score_handler_factory(object())
    assert policy.protected_score_scope is protected


@pytest.mark.asyncio
async def test_exclusive_handler_holds_unrelated_generic_scores(handler_fixture):
    handler, _, _, _ = handler_fixture
    assert (
        handler.protects_items("12", [{"user_id": "999", "assignment_id": "999"}])
        is True
    )
    assert handler.protects_items("other", []) is True
    assert handler.protects_items("12", None) is True


def test_handoff_preview_escapes_untrusted_names_and_shows_attempt(tmp_path):
    from canvas_mcp.gradebook.canvas_primary_score_handler import _write_handoff_preview
    from canvas_mcp.gradebook.store import Store

    store = Store(tmp_path / "handoff")
    snapshot = {
        "course_name": "<script>course</script>",
        "fetched_at": "2026-11-12T12:00:00Z",
        "students": [{"id": "101", "name": "<img src=x>", "sections": ["A1"]}],
        "assignments": [{"id": "21", "name": "<b>activity</b>"}],
        "cells": {"101:21": {"attempt": 1, "submitted_at": "2026-11-12T11:00:00Z"}},
    }
    baseline_id, _ = store.save("snapshot", snapshot)
    review = {
        "baseline_id": baseline_id,
        "changes": [
            {"user_id": "101", "assignment_id": "21", "current": None, "proposed": 20}
        ],
    }
    page = Path(_write_handoff_preview(store, review)).read_text()
    assert (
        "<script>" not in page
        and "<img src=x>" not in page
        and "<b>activity</b>" not in page
    )
    assert (
        "&lt;script&gt;course&lt;/script&gt;" in page and "2026-11-12T11:00:00Z" in page
    )
    assert "Unapproved source-based advisory" in page and "teacher-entered" not in page
    assert "Canvas ID" in page and ">101<" in page


@pytest.mark.parametrize(
    "url,expected",
    [
        ("https://canvas.example/courses/12/assignments/21", True),
        ("https://canvas.example.evil.test/courses/12/assignments/21", False),
        ("https://canvas.example/courses/12/assignments/22", False),
        ("javascript:alert(1)", False),
    ],
)
def test_handoff_link_requires_exact_canvas_origin_and_assignment(
    tmp_path, url, expected
):
    from canvas_mcp.gradebook.canvas_primary_score_handler import _write_handoff_preview
    from canvas_mcp.gradebook.store import Store

    store = Store(tmp_path / "preview")
    baseline = {
        "origin": "https://canvas.example",
        "course_id": "12",
        "course_name": "Example",
        "fetched_at": "now",
        "students": [{"id": "101", "name": "Student", "sections": ["A1"]}],
        "assignments": [
            {"id": "21", "name": "Activity", "assignment_metadata": {"html_url": url}}
        ],
        "cells": {"101:21": {"attempt": 1, "submitted_at": "2026-11-12T11:00:00Z"}},
    }
    baseline_id, _ = store.save("snapshot", baseline)
    review = {
        "baseline_id": baseline_id,
        "changes": [
            {"user_id": "101", "assignment_id": "21", "current": None, "proposed": 20}
        ],
    }
    page = Path(_write_handoff_preview(store, review)).read_text()
    assert ("Open the Canvas assignment" in page) is expected
