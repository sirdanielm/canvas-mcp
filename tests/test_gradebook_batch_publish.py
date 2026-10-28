"""Exact reviewed grants, independent holds and resumable synthetic dispatches."""

import copy
import json
from unittest.mock import AsyncMock

import httpx
import pytest
from fastmcp import Client

from canvas_mcp.gradebook.batch_publish import BatchPublisher
from canvas_mcp.gradebook.client import GradebookClient, GradebookError
from canvas_mcp.gradebook.ledger import Ledger
from canvas_mcp.gradebook.model import compare_edits, digest, submission_cell
from canvas_mcp.gradebook.publish import Publisher
from canvas_mcp.gradebook.server import create_server
from canvas_mcp.gradebook.store import Store

pytest_plugins = ("test_gradebook", "test_gradebook_publish")


def make_system(tmp_path, snapshot, size=2, proposals=None):
    snapshot = copy.deepcopy(snapshot)
    snapshot["course_workflow_state"] = "available"
    snapshot["students"] = [
        {**copy.deepcopy(snapshot["students"][0]), "id": str(uid)}
        for uid in range(101, 101 + size)
    ]
    raws = {
        str(uid): {
            "user_id": uid,
            "assignment_id": 21,
            "score": 10,
            "grade": "10",
            "workflow_state": "graded",
            "assignment_visible": True,
        }
        for uid in range(101, 101 + size)
    }
    snapshot["cells"] = {uid + ":21": submission_cell(raw) for uid, raw in raws.items()}
    state = {"puts": [], "behaviors": {}, "after_put": None}
    assignment = {
        "id": 21,
        "course_id": 12,
        "published": True,
        "points_possible": 20,
        "grading_type": "points",
        "moderated_grading": False,
        "anonymous_grading": False,
        "group_category_id": None,
    }

    def handler(request):
        if "/submissions/" in request.url.path:
            uid = request.url.path.rsplit("/", 1)[1]
            if request.method == "PUT":
                state["puts"].append(uid)
                if state["behaviors"].get(uid) == "reject":
                    return httpx.Response(422)
                if state["behaviors"].get(uid) == "uncertain":
                    raise httpx.ReadTimeout("fictional response lost")
                value = json.loads(request.content)["submission"]["posted_grade"]
                raws[uid].update(score=float(value), grade=value)
                if state["after_put"]:
                    state["after_put"]()
            return httpx.Response(200, json=raws[uid])
        return httpx.Response(200, json=assignment)

    client = GradebookClient(
        snapshot["origin"], "fictional", httpx.MockTransport(handler)
    )

    async def current(course):
        fresh = copy.deepcopy(snapshot)
        fresh["cells"] = {
            uid + ":21": submission_cell(raw) for uid, raw in raws.items()
        }
        return fresh

    client.snapshot = AsyncMock(side_effect=current)
    store = Store(tmp_path)
    store.save("snapshot", snapshot)
    envelope = {
        "course_id": "12",
        "snapshot_id": digest(snapshot),
        "edits": [
            {
                "user_id": uid,
                "assignment_id": "21",
                "value": (proposals or {}).get(uid, 20),
            }
            for uid in raws
        ],
    }
    review = compare_edits(snapshot, snapshot, envelope)
    review_id, _ = store.save("review", review)
    publisher = Publisher(client, store, Ledger(tmp_path))
    return BatchPublisher(publisher), state, raws, review_id


async def approved(batches, review_id):
    preview = await batches.prepare_scores("12", review_id)
    assert preview["canvas_writes"] == 0
    batches.authorize("12", preview["batch_id"], preview["confirmation_token"])
    return preview


async def test_held_row_is_excluded_without_blocking_eligible_rows(tmp_path, snapshot):
    batches, state, _, review_id = make_system(tmp_path, snapshot, 3, {"101": 5})
    preview = await approved(batches, review_id)
    assert preview["held"] == 1
    result = await batches.execute_chunk("12", preview["batch_id"], 0)
    assert result["counts"] == {"verified": 2}
    assert state["puts"] == ["102", "103"]


async def test_preexisting_hold_is_not_cleared_when_later_state_looks_ready(
    tmp_path, snapshot
):
    batches, state, _, review_id = make_system(tmp_path, snapshot)
    old_review = batches.store.load("review", review_id)
    baseline = batches.store.load("snapshot", old_review["baseline_id"])
    captured = copy.deepcopy(baseline)
    captured["cells"]["101:21"].update(value=11, grade="11")
    batches.store.save("snapshot", captured)
    parent = compare_edits(
        baseline,
        captured,
        {
            "course_id": "12",
            "snapshot_id": digest(baseline),
            "edits": [
                {"user_id": uid, "assignment_id": "21", "value": 20}
                for uid in ("101", "102")
            ],
        },
    )
    parent_id, _ = batches.store.save("review", parent)
    preview = await approved(batches, parent_id)
    assert preview["held"] == 1
    result = await batches.execute_chunk("12", preview["batch_id"], 0)
    assert result["counts"] == {"verified": 1} and state["puts"] == ["102"]


@pytest.mark.parametrize("bad", ["classification", "writes", "course"])
async def test_untrusted_review_metadata_cannot_gain_batch_authority(
    tmp_path, snapshot, bad
):
    batches, state, _, review_id = make_system(tmp_path, snapshot)
    review = batches.store.load("review", review_id)
    if bad == "classification":
        review["changes"][0].update(status="review_required", reasons=["owner_hold"])
        review["counts"] = {"review_required": 1, "ready_for_review": 1}
    elif bad == "writes":
        review["canvas_writes"] = 1
    else:
        review["course_id"] = "13"
    changed_id, _ = batches.store.save("review", review)
    with pytest.raises(GradebookError):
        await batches.prepare_scores("12", changed_id)
    assert batches.publisher.client.snapshot.await_count == 0
    assert state["puts"] == []


async def test_changed_target_does_not_freeze_other_reviewed_targets(
    tmp_path, snapshot
):
    batches, state, raws, review_id = make_system(tmp_path, snapshot)
    preview = await approved(batches, review_id)
    raws["101"].update(score=11, grade="11")
    result = await batches.execute_chunk("12", preview["batch_id"], 0)
    assert result["counts"] == {"conflict": 1, "verified": 1}
    assert state["puts"] == ["102"]


@pytest.mark.parametrize(
    "behavior,held_state", [("reject", "rejected"), ("uncertain", "uncertain")]
)
async def test_independent_targets_continue_after_a_failed_send(
    tmp_path, snapshot, behavior, held_state
):
    batches, state, _, review_id = make_system(tmp_path, snapshot)
    preview = await approved(batches, review_id)
    state["behaviors"]["101"] = behavior
    result = await batches.execute_chunk("12", preview["batch_id"], 0)
    assert result["counts"] == {held_state: 1, "verified": 1}
    assert state["puts"] == ["101", "102"]
    assert await batches.execute_chunk("12", preview["batch_id"], 0) == result
    assert state["puts"] == ["101", "102"]
    if behavior == "uncertain":
        operation_id, token = batches.ledger.prepare(
            "a" * 64, ["https://school.example:12:101:21"]
        )
        with pytest.raises(GradebookError, match="unresolved push"):
            batches.ledger.claim(operation_id, token)


async def test_one_approval_survives_between_chunks_without_extending_legacy_tokens(
    tmp_path, snapshot, monkeypatch
):
    clock = [1000.0]
    monkeypatch.setattr("canvas_mcp.gradebook.ledger.time.time", lambda: clock[0])
    batches, state, _, review_id = make_system(tmp_path, snapshot, 26)
    preview = await approved(batches, review_id)
    assert preview["chunks"] == 2 and preview["expires_at"] == 8200.0
    first = await batches.execute_chunk("12", preview["batch_id"], 0)
    assert first["counts"] == {"verified": 25}
    clock[0] = 1800.0
    second = await batches.execute_chunk("12", preview["batch_id"], 1)
    assert second["counts"] == {"verified": 1} and len(state["puts"]) == 26
    with pytest.raises(GradebookError, match="already consumed"):
        batches.authorize("12", preview["batch_id"], preview["confirmation_token"])
    legacy, _ = batches.ledger.prepare("b" * 64, ["fictional-independent"])
    assert batches.ledger.operation(legacy)["expires"] == 2400.0


@pytest.mark.parametrize("stop", ["expiry", "revocation"])
async def test_expiry_and_revocation_stop_remaining_chunks(
    tmp_path, snapshot, monkeypatch, stop
):
    clock = [1000.0]
    monkeypatch.setattr("canvas_mcp.gradebook.ledger.time.time", lambda: clock[0])
    batches, state, _, review_id = make_system(tmp_path, snapshot, 26)
    preview = await approved(batches, review_id)
    await batches.execute_chunk("12", preview["batch_id"], 0)
    if stop == "expiry":
        clock[0] = 8200.01
    else:
        batches.revoke("12", preview["batch_id"])
    with pytest.raises(GradebookError, match="expired|revoked"):
        await batches.execute_chunk("12", preview["batch_id"], 1)
    assert len(state["puts"]) == 25


async def test_revocation_is_rechecked_before_each_send(tmp_path, snapshot):
    batches, state, _, review_id = make_system(tmp_path, snapshot)
    preview = await approved(batches, review_id)
    state["after_put"] = lambda: batches.revoke("12", preview["batch_id"])
    with pytest.raises(GradebookError, match="revoked"):
        await batches.execute_chunk("12", preview["batch_id"], 0)
    assert state["puts"] == ["101"]
    status = batches.status("12", preview["batch_id"])
    assert status["chunks"][0]["counts"] == {"verified": 1, "not_sent": 1}


async def test_revocation_during_target_get_preflight_prevents_first_put(
    tmp_path, snapshot, monkeypatch
):
    from canvas_mcp.gradebook import publish

    batches, state, _, review_id = make_system(tmp_path, snapshot)
    preview = await approved(batches, review_id)
    original = publish.context

    async def revoke_after_read(*args):
        result = await original(*args)
        batches.revoke("12", preview["batch_id"])
        return result

    monkeypatch.setattr(publish, "context", revoke_after_read)
    with pytest.raises(GradebookError, match="revoked"):
        await batches.execute_chunk("12", preview["batch_id"], 0)
    assert state["puts"] == []
    assert batches.status("12", preview["batch_id"])["chunks"][0]["counts"] == {
        "not_sent": 2
    }


async def test_wrong_course_token_or_mutated_payload_cannot_authorize_or_send(
    tmp_path, snapshot
):
    batches, state, _, review_id = make_system(tmp_path, snapshot)
    preview = await batches.prepare_scores("12", review_id)
    with pytest.raises(GradebookError, match="course"):
        batches.authorize("13", preview["batch_id"], preview["confirmation_token"])
    with pytest.raises(GradebookError, match="does not match"):
        batches.authorize("12", preview["batch_id"], "wrong")
    batches.authorize("12", preview["batch_id"], preview["confirmation_token"])
    batch = batches.ledger.batch(preview["batch_id"])
    path = batches.store.root / ("push-" + batch["chunks"][0]["plan_id"] + ".json")
    plan = json.loads(path.read_text(encoding="utf-8"))
    plan["items"][0]["proposed"] = 19
    path.write_text(json.dumps(plan), encoding="utf-8")
    with pytest.raises(GradebookError, match="integrity"):
        await batches.execute_chunk("12", preview["batch_id"], 0)
    assert state["puts"] == []


@pytest.mark.parametrize("when", ["before_approval", "after_approval"])
async def test_changed_teacher_review_display_cannot_keep_dispatch_authority(
    tmp_path, snapshot, when
):
    from pathlib import Path

    batches, state, _, review_id = make_system(tmp_path, snapshot)
    preview = await batches.prepare_scores("12", review_id)
    if when == "after_approval":
        batches.authorize("12", preview["batch_id"], preview["confirmation_token"])
    Path(preview["review_files"][0]).write_text("Changed reviewed values", encoding="utf-8")
    with pytest.raises(GradebookError, match="display changed"):
        if when == "before_approval":
            batches.authorize("12", preview["batch_id"], preview["confirmation_token"])
        else:
            await batches.execute_chunk("12", preview["batch_id"], 0)
    assert state["puts"] == []


async def test_invalid_manifest_channel_cannot_borrow_comment_enablement(
    tmp_path, snapshot
):
    batches, state, _, review_id = make_system(tmp_path, snapshot)
    preview = await batches.prepare_scores("12", review_id)
    manifest = batches.store.load("push", preview["manifest_id"])
    manifest["channel"] = "INVALID"
    changed_id, _ = batches.store.save("push", manifest)
    batch_id, token = batches.ledger.prepare_batch(
        changed_id, manifest["plan_ids"], 7200
    )
    publisher = batches.publisher
    server = create_server(
        publisher.client, publisher.store, {"core": "12"}, enable_comments=True
    )
    async with Client(server) as mcp:
        result = (
            await mcp.call_tool(
                "authorize_gradebook_batch",
                {
                    "course": "core",
                    "batch_id": batch_id,
                    "confirmation_token": token,
                },
            )
        ).data
    assert "error" in result and state["puts"] == []
    assert batches.ledger.batch(batch_id)["status"] == "prepared"


async def test_locked_target_is_quarantined_without_releasing_its_original_lock(
    tmp_path, snapshot
):
    batches, state, _, review_id = make_system(tmp_path, snapshot)
    preview = await approved(batches, review_id)
    target = "https://school.example:12:101:21"
    prior, token = batches.ledger.prepare("a" * 64, [target])
    batches.ledger.claim(prior, token)
    batches.ledger.mark(prior, 0, "sending")
    result = await batches.execute_chunk("12", preview["batch_id"], 0)
    assert result["counts"] == {"conflict": 1, "verified": 1}
    assert state["puts"] == ["102"]
    with batches.ledger.connect() as db:
        assert (
            db.execute(
                "SELECT operation_id FROM target_locks WHERE target=?", (target,)
            ).fetchone()[0]
            == prior
        )


async def test_unstarted_dispatch_can_resume_but_claimed_dispatch_cannot(
    tmp_path, snapshot
):
    batches, state, _, review_id = make_system(tmp_path, snapshot)
    preview = await approved(batches, review_id)
    batch = batches.ledger.batch(preview["batch_id"])
    plan_id = batch["chunks"][0]["plan_id"]
    targets = ["https://school.example:12:101:21", "https://school.example:12:102:21"]
    operation_id, _ = batches.ledger.prepare(plan_id, targets)
    batches.ledger.attach_batch_chunk(
        preview["batch_id"], preview["manifest_id"], 0, operation_id
    )
    result = await BatchPublisher(batches.publisher).execute_chunk(
        "12", preview["batch_id"], 0
    )
    assert result["counts"] == {"verified": 2}
    assert len(state["puts"]) == 2
    with pytest.raises(GradebookError, match="unstarted"):
        batches.ledger.unstarted_chunk_token(
            preview["batch_id"], preview["manifest_id"], operation_id
        )


async def test_comment_grant_still_binds_exact_source_and_never_replays(comment_system):
    publisher, state, envelope = comment_system
    batches = BatchPublisher(publisher)
    filename = publisher.store.root / "inbox/comment.json"
    filename.write_text(json.dumps(envelope), encoding="utf-8")
    preview = await batches.prepare_comments(
        "12", [{"filename": "comment.json", "envelope_sha256": digest(envelope)}]
    )
    batches.authorize("12", preview["batch_id"], preview["confirmation_token"])
    result = await batches.execute_chunk("12", preview["batch_id"], 0)
    assert result["counts"] == {"verified": 1} and len(state["forms"]) == 1
    repeated = await batches.execute_chunk("12", preview["batch_id"], 0)
    assert repeated["counts"] == {"verified": 1} and len(state["forms"]) == 1


async def test_comment_source_drift_after_batch_review_sends_nothing(comment_system):
    publisher, state, envelope = comment_system
    batches = BatchPublisher(publisher)
    filename = publisher.store.root / "inbox/comment.json"
    filename.write_text(json.dumps(envelope), encoding="utf-8")
    preview = await batches.prepare_comments(
        "12", [{"filename": "comment.json", "envelope_sha256": digest(envelope)}]
    )
    batches.authorize("12", preview["batch_id"], preview["confirmation_token"])
    envelope["comment"] += " changed"
    filename.write_text(json.dumps(envelope), encoding="utf-8")
    with pytest.raises(GradebookError, match="changed after preview"):
        await batches.execute_chunk("12", preview["batch_id"], 0)
    assert state["forms"] == []


@pytest.mark.parametrize("claimed", [False, True])
async def test_comment_chunk_restart_resumes_only_unclaimed_dispatch(
    comment_system, claimed
):
    publisher, state, envelope = comment_system
    batches = BatchPublisher(publisher)
    (publisher.store.root / "inbox/comment.json").write_text(json.dumps(envelope), encoding="utf-8")
    preview = await batches.prepare_comments(
        "12", [{"filename": "comment.json", "envelope_sha256": digest(envelope)}]
    )
    batches.authorize("12", preview["batch_id"], preview["confirmation_token"])
    plan_id = batches.ledger.batch(preview["batch_id"])["chunks"][0]["plan_id"]
    plan = publisher.store.load("push", plan_id)
    operation, token = publisher.ledger.prepare(
        plan_id,
        ["https://school.example:12:101:21"],
        comment_delivery_ids=[plan["delivery_id"]],
    )
    publisher.ledger.attach_batch_chunk(
        preview["batch_id"], preview["manifest_id"], 0, operation
    )
    if claimed:
        publisher.ledger.claim(operation, token)
    restarted = Publisher(
        publisher.client, Store(publisher.store.root), Ledger(publisher.store.root)
    )
    result = await BatchPublisher(restarted).execute_chunk("12", preview["batch_id"], 0)
    if claimed:
        assert result["counts"] == {"planned": 1} and state["forms"] == []
        assert (await restarted.reconcile_comment("12", operation))["counts"] == {
            "not_sent": 1
        }
    else:
        assert result["counts"] == {"verified": 1} and len(state["forms"]) == 1


@pytest.mark.parametrize(
    "enable_push,enable_comments", [(False, False), (True, False), (False, True)]
)
async def test_batch_write_tools_and_channels_follow_operator_enablement(
    tmp_path, snapshot, enable_push, enable_comments
):
    batches, state, _, review_id = make_system(tmp_path, snapshot)
    publisher = batches.publisher
    server = create_server(
        publisher.client,
        publisher.store,
        {"core": "12"},
        enable_push=enable_push,
        enable_comments=enable_comments,
    )
    async with Client(server) as mcp:
        names = {t.name for t in await mcp.list_tools()}
        assert ("execute_gradebook_batch_chunk" in names) is (
            enable_push or enable_comments
        )
        preview = (
            await mcp.call_tool(
                "prepare_gradebook_score_batch",
                {"course": "core", "review_id": review_id},
            )
        ).data
        if enable_push or enable_comments:
            result = (
                await mcp.call_tool(
                    "authorize_gradebook_batch",
                    {
                        "course": "core",
                        "batch_id": preview["batch_id"],
                        "confirmation_token": preview["confirmation_token"],
                    },
                )
            ).data
            assert ("error" not in result) is enable_push
    assert state["puts"] == []
