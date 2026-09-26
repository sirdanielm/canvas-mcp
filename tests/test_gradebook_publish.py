"""Exercise grade writes only against an in-memory synthetic Canvas transport."""

import copy
import json
from pathlib import Path
from unittest.mock import AsyncMock

import httpx
import pytest
from fastmcp import Client
from test_gradebook import edits
from test_gradebook import snapshot as snapshot

from canvas_mcp.gradebook.client import GradebookClient, GradebookError
from canvas_mcp.gradebook.ledger import Ledger
from canvas_mcp.gradebook.model import compare_edits, digest, submission_cell
from canvas_mcp.gradebook.publish import Publisher, context, require_simple_target
from canvas_mcp.gradebook.server import create_server
from canvas_mcp.gradebook.store import Store


@pytest.fixture
def system(tmp_path, snapshot):
    snapshot["course_workflow_state"] = "available"
    raw = {
        "user_id": 101,
        "assignment_id": 21,
        "score": 10,
        "grade": "10",
        "workflow_state": "graded",
        "assignment_visible": True,
    }
    state = {
        "submission": raw,
        "assignment": {
            "id": 21,
            "course_id": 12,
            "published": True,
            "points_possible": 20,
            "grading_type": "points",
            "moderated_grading": False,
            "anonymous_grading": False,
            "group_category_id": None,
        },
        "puts": [],
        "behavior": "success",
    }

    def handler(request):
        if request.method == "PUT":
            state["puts"].append(json.loads(request.content))
            body = state["puts"][-1]["submission"]
            if state["behavior"] in ("success", "timeout_applied"):
                if body.get("excuse"):
                    state["submission"]["excused"] = True
                else:
                    state["submission"]["score"] = float(body["posted_grade"])
                    state["submission"]["grade"] = body["posted_grade"]
                state["submission"]["graded_at"] = "2026-09-17T20:00:01Z"
            if state["behavior"].startswith("timeout"):
                raise httpx.ReadTimeout("synthetic timeout")
            if state["behavior"] == "reject":
                return httpx.Response(422, json={"sensitive": "must never surface"})
            if state["behavior"] == "server_error":
                return httpx.Response(500, json={"sensitive": "must never surface"})
            return httpx.Response(200, json=state["submission"])
        if "/submissions/" in request.url.path:
            return httpx.Response(200, json=state["submission"])
        return httpx.Response(200, json=state["assignment"])

    client = GradebookClient(snapshot["origin"], "test", httpx.MockTransport(handler))

    async def get_snapshot(course_id):
        current = copy.deepcopy(snapshot)
        current["cells"]["101:21"] = submission_cell(state["submission"])
        return current

    client.snapshot = AsyncMock(side_effect=get_snapshot)
    store = Store(tmp_path)
    store.save("snapshot", snapshot)
    review = compare_edits(snapshot, snapshot, edits(snapshot, 20))
    review_id, _ = store.save("review", review)
    ledger = Ledger(tmp_path)
    publisher = Publisher(client, store, ledger)
    return publisher, state, review_id, snapshot


async def prepared(system):
    publisher, state, review_id, baseline = system
    proposal = await publisher.prepare("12", review_id)
    assert proposal["ready_for_confirmation"]
    assert "Synthetic Student" not in json.dumps(proposal)
    assert state["puts"] == []
    return proposal


async def test_confirmed_push_readback_and_token_single_use(system):
    publisher, state, _, _ = system
    proposal = await prepared(system)
    result = await publisher.confirm(
        "12", proposal["operation_id"], proposal["confirmation_token"]
    )
    assert result["status"] == "verified"
    assert result["counts"] == {"verified": 1}
    assert state["puts"] == [{"submission": {"posted_grade": "20"}}]
    with pytest.raises(GradebookError, match="already consumed"):
        await publisher.confirm(
            "12", proposal["operation_id"], proposal["confirmation_token"]
        )
    assert len(state["puts"]) == 1


async def test_wrong_token_and_course_never_write(system):
    publisher, state, _, _ = system
    proposal = await prepared(system)
    with pytest.raises(GradebookError, match="does not match"):
        await publisher.confirm("12", proposal["operation_id"], "wrong")
    with pytest.raises(GradebookError, match="different course"):
        await publisher.confirm(
            "13", proposal["operation_id"], proposal["confirmation_token"]
        )
    assert state["puts"] == []
    assert publisher.ledger.summary(proposal["operation_id"])["status"] == "prepared"


async def test_expired_confirmation_never_writes(system):
    publisher, state, _, _ = system
    proposal = await prepared(system)
    with publisher.ledger.connect() as db:
        db.execute("UPDATE operations SET expires=0")
    with pytest.raises(GradebookError, match="expired"):
        await publisher.confirm(
            "12", proposal["operation_id"], proposal["confirmation_token"]
        )
    assert state["puts"] == []


async def test_changed_canvas_after_preview_stops_whole_operation(system):
    publisher, state, _, _ = system
    proposal = await prepared(system)
    state["submission"]["score"] = 11
    with pytest.raises(GradebookError, match="changed after"):
        await publisher.confirm(
            "12", proposal["operation_id"], proposal["confirmation_token"]
        )
    assert state["puts"] == []
    assert publisher.ledger.summary(proposal["operation_id"])["counts"] == {
        "not_sent": 1
    }


async def test_changed_assignment_after_preview_conflicts_without_write(system):
    publisher, state, _, _ = system
    proposal = await prepared(system)
    state["assignment"]["points_possible"] = 25
    result = await publisher.confirm(
        "12", proposal["operation_id"], proposal["confirmation_token"]
    )
    assert result["counts"] == {"conflict": 1}
    assert state["puts"] == []


@pytest.mark.parametrize(
    "behavior", ["timeout_applied", "timeout_unapplied", "server_error", "mismatch"]
)
async def test_uncertain_write_never_retried(system, behavior):
    publisher, state, _, _ = system
    proposal = await prepared(system)
    state["behavior"] = behavior
    result = await publisher.confirm(
        "12", proposal["operation_id"], proposal["confirmation_token"]
    )
    assert result["status"] == "uncertain"
    assert len(state["puts"]) == 1
    restarted = Publisher(
        publisher.client, publisher.store, Ledger(publisher.store.root)
    )
    readback = await restarted.reconcile("12", proposal["operation_id"])
    if behavior == "timeout_applied":
        assert readback["counts"] == {"observed_applied": 1}
    else:
        assert readback["counts"] == {"uncertain": 1}
        op, token = restarted.ledger.prepare(
            "a" * 64,
            [
                restarted.ledger.operation(proposal["operation_id"])["items"][0][
                    "target"
                ]
            ],
        )
        with pytest.raises(GradebookError, match="unresolved push"):
            restarted.ledger.claim(op, token)
    assert len(state["puts"]) == 1


async def test_explicit_rejection_stops_without_retry(system):
    publisher, state, _, _ = system
    proposal = await prepared(system)
    state["behavior"] = "reject"
    result = await publisher.confirm(
        "12", proposal["operation_id"], proposal["confirmation_token"]
    )
    assert result["counts"] == {"rejected": 1}
    assert len(state["puts"]) == 1
    assert "sensitive" not in json.dumps(result)


async def test_crash_checkpoint_readback_does_not_send(system):
    publisher, state, _, _ = system
    proposal = await prepared(system)
    publisher.ledger.claim(proposal["operation_id"], proposal["confirmation_token"])
    publisher.ledger.mark(proposal["operation_id"], 0, "sending")
    result = await publisher.reconcile("12", proposal["operation_id"])
    assert result["counts"] == {"uncertain": 1}
    assert state["puts"] == []


async def test_single_operation_lock_excludes_reconcile(system):
    publisher, state, _, _ = system
    proposal = await prepared(system)
    with publisher.ledger.exclusive(proposal["operation_id"]):
        with pytest.raises(GradebookError, match="already running"):
            await publisher.reconcile("12", proposal["operation_id"])
    assert state["puts"] == []


@pytest.mark.parametrize(
    "field,value",
    [
        ("moderated_grading", True),
        ("anonymous_grading", True),
        ("group_category_id", 5),
        ("use_rubric_for_grading", True),
        ("has_sub_assignments", True),
    ],
)
async def test_special_grading_workflows_block_push(system, field, value):
    publisher, state, review_id, _ = system
    state["assignment"][field] = value
    with pytest.raises(GradebookError):
        await publisher.prepare("12", review_id)
    assert state["puts"] == []


async def test_closed_period_and_missing_visibility_block(system):
    publisher, state, _, _ = system
    ctx = await context(publisher.client, "12", "101", "21")
    ctx["closed_period"] = True
    with pytest.raises(GradebookError):
        require_simple_target(ctx, 20)
    ctx["closed_period"] = None
    ctx["submission"]["visible"] = None
    with pytest.raises(GradebookError):
        require_simple_target(ctx, 20)
    assert state["puts"] == []


async def test_excusal_has_exact_payload_no_grade_comment(system):
    publisher, state, _, baseline = system
    review = compare_edits(baseline, baseline, edits(baseline, "EX"))
    review_id, _ = publisher.store.save("review", review)
    proposal = await publisher.prepare("12", review_id)
    result = await publisher.confirm(
        "12", proposal["operation_id"], proposal["confirmation_token"]
    )
    assert result["counts"] == {"verified": 1}
    assert state["puts"] == [{"submission": {"excuse": True}}]


async def test_held_decrease_gets_no_confirmation(system):
    publisher, state, _, baseline = system
    review = compare_edits(baseline, baseline, edits(baseline, 5))
    review_id, _ = publisher.store.save("review", review)
    proposal = await publisher.prepare("12", review_id)
    assert not proposal["ready_for_confirmation"]
    assert "confirmation_token" not in proposal
    assert state["puts"] == []


async def test_review_escapes_canvas_content_and_is_private(system):
    publisher, state, _, baseline = system
    baseline["students"][0]["name"] = "<script>bad()</script>"
    publisher.store.save("snapshot", baseline)
    review = compare_edits(baseline, baseline, edits(baseline, 20))
    review_id, _ = publisher.store.save("review", review)
    proposal = await publisher.prepare("12", review_id)
    path = Path(proposal["review_file"])
    assert "<script>bad()" not in path.read_text()
    assert "&lt;script&gt;" in path.read_text()
    assert path.stat().st_mode & 0o777 == 0o600
    assert publisher.ledger.path.stat().st_mode & 0o777 == 0o600


async def test_write_tool_absent_by_default_and_present_only_when_enabled(system):
    publisher, state, _, _ = system
    for enabled in [False, True]:
        async with Client(
            create_server(
                publisher.client, publisher.store, {"core": "12"}, enable_push=enabled
            )
        ) as mcp:
            names = {tool.name for tool in await mcp.list_tools()}
        assert ("confirm_gradebook_push" in names) == enabled
    assert state["puts"] == []


async def test_partial_batch_stops_after_uncertain_item(system, monkeypatch):
    import canvas_mcp.gradebook.publish as publish_module
    from canvas_mcp.gradebook.publish import WriteUncertain

    publisher, state, _, baseline = system
    original_ctx = await context(publisher.client, "12", "101", "21")
    expanded = copy.deepcopy(baseline)
    for uid in ["102", "103"]:
        expanded["students"].append(
            {"id": uid, "name": "Synthetic Additional", "sections": ["A1"]}
        )
        expanded["cells"][uid + ":21"] = copy.deepcopy(expanded["cells"]["101:21"])
    publisher.store.save("snapshot", expanded)
    contexts = {uid: copy.deepcopy(original_ctx) for uid in ["101", "102", "103"]}
    publisher.client.snapshot = AsyncMock(return_value=expanded)

    async def read_context(client, course_id, uid, aid):
        return copy.deepcopy(contexts[uid])

    sent = []

    async def write_once(client, course_id, item):
        sent.append(item["user_id"])
        if len(sent) == 2:
            raise WriteUncertain("Synthetic uncertain result")
        contexts[item["user_id"]]["submission"]["value"] = item["proposed"]

    monkeypatch.setattr(publish_module, "context", read_context)
    monkeypatch.setattr(publish_module, "put_once", write_once)
    review = compare_edits(
        expanded,
        expanded,
        {
            "course_id": "12",
            "snapshot_id": digest(expanded),
            "edits": [
                {"user_id": uid, "assignment_id": "21", "value": 20} for uid in contexts
            ],
        },
    )
    review_id, _ = publisher.store.save("review", review)
    proposal = await publisher.prepare("12", review_id)
    result = await publisher.confirm(
        "12", proposal["operation_id"], proposal["confirmation_token"]
    )
    assert sent == ["101", "102"]
    assert result["counts"] == {"verified": 1, "uncertain": 1, "not_sent": 1}
    assert result["status"] == "uncertain"
    await publisher.reconcile("12", proposal["operation_id"])
    assert sent == ["101", "102"]


async def test_readback_failure_leaves_durable_sending_checkpoint(system, monkeypatch):
    import canvas_mcp.gradebook.publish as publish_module

    publisher, state, _, _ = system
    proposal = await prepared(system)
    real_context = publish_module.context

    async def get_context(*args):
        if state["puts"]:
            raise GradebookError("Synthetic readback failure")
        return await real_context(*args)

    monkeypatch.setattr(publish_module, "context", get_context)
    with pytest.raises(GradebookError, match="readback failure"):
        await publisher.confirm(
            "12", proposal["operation_id"], proposal["confirmation_token"]
        )
    assert len(state["puts"]) == 1
    assert publisher.ledger.summary(proposal["operation_id"])["status"] == "uncertain"
    monkeypatch.setattr(publish_module, "context", real_context)
    result = await publisher.reconcile("12", proposal["operation_id"])
    assert result["counts"] == {"observed_applied": 1}
    assert len(state["puts"]) == 1
