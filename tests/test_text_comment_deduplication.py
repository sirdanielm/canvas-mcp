"""Exact comment history must prove its attempt and visibility before deduping."""

import copy
from typing import Any

import httpx
import pytest
from test_text_comment_fresh_completion import configured as configured

from canvas_mcp.gradebook import text_comment_delivery_v4 as base
from canvas_mcp.gradebook.client import GradebookError
from canvas_mcp.gradebook.ledger import Ledger
from canvas_mcp.gradebook.store import Store


def delivery_for(configured: Any, kind: str) -> Any:
    make, client, store, _, manifest, _, _ = configured
    fresh = make()
    if kind == "fresh":
        return fresh
    root = store.root / "standalone-base"
    return base.TextCommentDelivery(
        client, Store(root), Ledger(root), manifest, canonical_root=root
    )


def observe_history(delivery: Any, patch: dict[str, Any], *, inject: bool) -> None:
    """Return controlled native GET facts; never alter backend data or receipts."""
    previous = delivery.client.http._transport.handler
    manifest = delivery._manifest()
    bodies = {
        r["user_id"]: base.pinned(r["body_ref"]).decode("utf-8")
        for r in manifest["records"]
    }

    def exchange(request: httpx.Request) -> httpx.Response:
        response = previous(request)
        if request.method == "GET" and "/submissions/" in request.url.path:
            value = response.json()
            if inject:
                uid = int(request.url.path.rsplit("/", 1)[1])
                value["submission_comments"] = [{
                    "id": 300 + uid, "author_id": manifest["actor_id"],
                    "comment": bodies[uid], "created_at": "2026-10-14T00:00:00Z",
                }]
            for comment in value["submission_comments"]:
                comment.update(copy.deepcopy(patch))
            return httpx.Response(200, json=value)
        return response

    delivery.client.http._transport.handler = exchange


@pytest.mark.parametrize("kind", ["base", "fresh"])
@pytest.mark.parametrize("stage", ["prepare", "final_get"])
@pytest.mark.parametrize("patch", [
    {"attempt": 1}, {"attempt": True}, {"attempt": "1"},
    {"created_at": None}, {"attachments": [{"id": 7}]},
    {"hidden": 0}, {"draft": None}, {"attachments": None},
], ids=["wrong_attempt", "boolean_attempt", "text_attempt", "missing_timestamp",
        "attachment_history", "untyped_hidden", "unknown_draft", "unknown_attachments"])
async def test_unverified_exact_history_holds_without_dedupe_or_append(
    configured: Any, kind: str, stage: str, patch: dict[str, Any]
) -> None:
    _, client, _, _, _, _, puts = configured
    delivery = delivery_for(configured, kind)
    try:
        with delivery.ledger.connect() as db:
            original = db.execute("SELECT COUNT(*) FROM operations").fetchone()[0]
        if stage == "prepare":
            observe_history(delivery, patch, inject=True)
            with pytest.raises(GradebookError):
                await delivery.prepare()
            with delivery.ledger.connect() as db:
                assert db.execute("SELECT COUNT(*) FROM operations").fetchone()[0] == original
                assert db.execute("SELECT COUNT(*) FROM target_locks").fetchone()[0] == 0
        else:
            plan = await delivery.prepare()
            observe_history(delivery, patch, inject=True)
            result = await delivery.confirm(
                plan["plan_id"], plan["operation_id"], plan["confirmation_token"],
                enabled=True, reviewed_plan_sha256=plan["plan_id"],
            )
            assert result["counts"].get("observed_applied", 0) == 0
            assert result["counts"].get("verified", 0) == 0
            assert result["counts"].get("not_sent", 0) >= 1
            assert result["held_receipts"]
            with pytest.raises(GradebookError, match="already consumed"):
                await delivery.confirm(
                    plan["plan_id"], plan["operation_id"], plan["confirmation_token"],
                    enabled=True, reviewed_plan_sha256=plan["plan_id"],
                )
        assert puts == []
        assert client.http.event_hooks["request"] == []
    finally:
        await client.close()


@pytest.mark.parametrize("kind", ["base", "fresh"])
@pytest.mark.parametrize("patch", [{}, {"attempt": None},
    {"attempt": None, "hidden": False, "draft": False, "attachments": []}],
    ids=["omitted_attempt", "exact_null_attempt", "explicit_visible_metadata"])
async def test_verified_exact_history_still_deduplicates_without_writing(
    configured: Any, kind: str, patch: dict[str, Any]
) -> None:
    _, client, _, _, _, _, puts = configured
    delivery = delivery_for(configured, kind)
    observe_history(delivery, patch, inject=True)
    try:
        result = await delivery.prepare()
        assert result["status"] == "NO_OP" and puts == []
    finally:
        await client.close()


@pytest.mark.parametrize("kind", ["base", "fresh"])
async def test_wrong_attempt_after_one_send_stays_uncertain_and_get_only(
    configured: Any, kind: str
) -> None:
    _, client, _, _, _, _, puts = configured
    delivery = delivery_for(configured, kind)
    try:
        plan = await delivery.prepare()
        observe_history(delivery, {"attempt": 1}, inject=False)
        result = await delivery.confirm(
            plan["plan_id"], plan["operation_id"], plan["confirmation_token"],
            enabled=True, reviewed_plan_sha256=plan["plan_id"],
        )
        assert result["counts"]["uncertain"] == 1 and len(puts) == 1
        result = await delivery.reconcile(plan["plan_id"], plan["operation_id"])
        assert result["counts"]["uncertain"] == 1 and len(puts) == 1
        with pytest.raises(GradebookError):
            await delivery.confirm(
                plan["plan_id"], plan["operation_id"], plan["confirmation_token"],
                enabled=True, reviewed_plan_sha256=plan["plan_id"],
            )
        assert len(puts) == 1
    finally:
        await client.close()


@pytest.mark.parametrize("comment_attempt", [True, 1.0, "1", 1], ids=["boolean", "float", "text", "exact_integer"])
async def test_observed_integer_attempt_requires_exact_native_type(configured: Any, comment_attempt: Any) -> None:
    _, client, _, _, _, _, puts = configured
    delivery = delivery_for(configured, "fresh")
    manifest = delivery._manifest()
    record = copy.deepcopy(manifest["records"][0])
    record["attempt"] = 1
    expected = base._json(base.pinned(record["submission_ref"]))
    expected["attempt"] = 1
    body = base.pinned(record["body_ref"]).decode("utf-8")
    previous = client.http._transport.handler

    def exchange(request: httpx.Request) -> httpx.Response:
        response = previous(request)
        value = response.json()
        value["attempt"] = 1
        value["submission_comments"] = [{"id": 401, "author_id": manifest["actor_id"],
            "comment": body, "created_at": "2026-10-14T00:00:00Z", "attempt": comment_attempt}]
        return httpx.Response(200, json=value)

    client.http._transport.handler = exchange
    item = {"record": record, "expected": expected, "body": body}
    try:
        if type(comment_attempt) is int:
            observed = await delivery._observe(manifest, item, authority=False)
            assert observed["matching"] == observed["verified_comment_ids"] == ["401"]
        else:
            with pytest.raises(GradebookError, match="ATTEMPT_UNVERIFIED"):
                await delivery._observe(manifest, item, authority=False)
        assert puts == []
    finally:
        await client.close()
