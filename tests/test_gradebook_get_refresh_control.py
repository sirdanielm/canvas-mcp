"""Synthetic controller/MCP tests: never contact Canvas or Sheets."""

import copy

import pytest
from fastmcp import Client
from test_gradebook_get_refresh_request import Google
from test_gradebook_worker_integration import BINDINGS, BOOK, INSTANCE

from canvas_mcp.gradebook.client import GradebookError
from canvas_mcp.gradebook.get_refresh_control import GetRefreshControl
from canvas_mcp.gradebook.model import digest
from canvas_mcp.gradebook.server import create_server
from canvas_mcp.gradebook.store import Store
from canvas_mcp.gradebook.worker import GET_ACTION, RefreshJournal

RID = "3becc390-aad4-4f4c-986e-6b494801a174"


class ClosableGoogle(Google):
    closed = False

    async def close(self):
        self.closed = True


def setup(tmp_path):
    store = Store(tmp_path)
    google = ClosableGoogle(store)
    controller = GetRefreshControl(lambda: google, store, BINDINGS, INSTANCE)
    return store, google, controller


async def test_request_uses_existing_single_send_admission_and_closes(tmp_path):
    store, google, controller = setup(tmp_path)
    result = await controller.request()
    assert result["state"] == "QUEUED"
    assert result["canvas_writes"] == result["grade_writes"] == 0
    assert len(google.posts) == 1 and google.closed
    again = await controller.request()
    assert again["request_id"] == result["request_id"]
    assert len(google.posts) == 1


async def test_unknown_status_is_local_only(tmp_path):
    store, google, controller = setup(tmp_path)
    result = await controller.status(RID)
    assert result["state"] == "NOT_FOUND"
    assert google.reads == 0 and not google.posts


@pytest.mark.parametrize("rid", ["", "bad", RID.upper(), None])
async def test_status_rejects_invalid_id_without_transport(tmp_path, rid):
    store, google, controller = setup(tmp_path)
    with pytest.raises(GradebookError):
        await controller.status(rid)
    assert google.reads == 0


def verified(store):
    request = {
        "v": 1,
        "id": RID,
        "action": GET_ACTION,
        "workbook_id": BOOK,
        "requested_at": "2026-10-14T10:00:00+00:00",
    }
    journal = RefreshJournal(store.root, BOOK)
    op = journal.create(request, 1234, refresh_mode="GET_ONLY")
    plans = {}
    for course, binding in BINDINGS.items():
        snap_id, _ = store.save(
            "snapshot",
            {
                "course_id": binding["course_id"],
                "fetched_at": "2026-10-14T10:00:00+00:00",
            },
        )
        plans[course] = {
            "canvas_snapshot_id": snap_id,
            "mode": "GET_ONLY",
            "edit_preserved": True,
            "baseline_id": "a" * 64,
            "previous_baseline_id": "a" * 64,
        }
    manifest_id, _ = store.save(
        "refresh",
        {
            "request": request,
            "refresh_mode": "GET_ONLY",
            "binding_digest": digest(BINDINGS),
            "plans": plans,
        },
    )
    receipt_id, _ = store.save(
        "receipt",
        {
            "worker_schema": 1,
            "request_id": RID,
            "manifest_id": manifest_id,
            "verified_at": "2026-10-14T10:01:00+00:00",
            "canvas_writes": 0,
            "summary": {
                c: {
                    "students": 2,
                    "assignments": 3,
                    "edit_preserved": True,
                    "pending_edits": None,
                }
                for c in BINDINGS
            },
        },
    )
    # Durable states are exercised in worker tests; create a verified fixture.
    payload = {
        **op["payload"],
        "manifest_id": manifest_id,
        "receipt_id": receipt_id,
        "finalized": True,
    }
    import json

    with journal.connect() as db:
        db.execute(
            "UPDATE operations SET status='VERIFIED', payload=? WHERE id=?",
            (json.dumps(payload), RID),
        )
    return journal, manifest_id, receipt_id


async def test_verified_status_requires_exact_get_receipt_and_returns_aggregates(
    tmp_path,
):
    store, google, controller = setup(tmp_path)
    verified(store)
    result = await controller.status(RID)
    assert result["state"] == "VERIFIED" and result["finalized"]
    assert result["summary"] == {
        c: {"students": 2, "assignments": 3, "edit_preserved": True} for c in BINDINGS
    }
    assert google.reads == 0 and not google.posts
    assert "before" not in result and "plans" not in result


@pytest.mark.parametrize(
    "mutation", ["mode", "receipt", "preservation", "counts", "course", "binding"]
)
async def test_status_holds_correlated_receipt_defects(tmp_path, mutation):
    store, google, controller = setup(tmp_path)
    journal, manifest_id, receipt_id = verified(store)
    op = journal.get(RID)
    payload = copy.deepcopy(op["payload"])
    if mutation in {"mode", "binding"}:
        manifest = store.load("refresh", manifest_id)
        manifest["refresh_mode" if mutation == "mode" else "binding_digest"] = "WRONG"
        payload["manifest_id"], _ = store.save("refresh", manifest)
    elif mutation == "course":
        manifest = store.load("refresh", manifest_id)
        snap, _ = store.save(
            "snapshot", {"course_id": "999", "fetched_at": "2026-10-14T10:00:00+00:00"}
        )
        manifest["plans"]["core"]["canvas_snapshot_id"] = snap
        payload["manifest_id"], _ = store.save("refresh", manifest)
    receipt = store.load("receipt", receipt_id)
    receipt["manifest_id"] = payload["manifest_id"]
    if mutation == "receipt":
        receipt["request_id"] = "wrong"
    if mutation == "preservation":
        receipt["summary"]["core"]["edit_preserved"] = False
    if mutation == "counts":
        receipt["summary"]["core"]["students"] = True
    payload["receipt_id"], _ = store.save("receipt", receipt)
    import json

    with journal.connect() as db:
        db.execute(
            "UPDATE operations SET payload=? WHERE id=?", (json.dumps(payload), RID)
        )
    with pytest.raises(GradebookError):
        await controller.status(RID)
    assert google.reads == 0


@pytest.mark.parametrize(
    "mutation",
    [
        "mode_schema_bool", "canvas_writes_bool", "worker_schema_bool",
        "plan_mode", "plan_preservation", "baseline_changed", "baseline_invalid",
        "plans_missing", "summary_not_object", "plan_not_object",
        "request_mismatch", "verification_time", "source_time", "empty_counts",
    ],
)
async def test_complete_status_requires_strict_preservation_proof(tmp_path, mutation):
    store, google, controller = setup(tmp_path)
    journal, manifest_id, receipt_id = verified(store)
    payload = copy.deepcopy(journal.get(RID)["payload"])
    manifest = store.load("refresh", manifest_id)
    receipt = store.load("receipt", receipt_id)
    if mutation == "mode_schema_bool":
        payload["refresh_mode_schema"] = True
    elif mutation == "canvas_writes_bool":
        receipt["canvas_writes"] = False
    elif mutation == "worker_schema_bool":
        receipt["worker_schema"] = True
    elif mutation == "plan_mode":
        manifest["plans"]["core"]["mode"] = "FULL_SYNC"
    elif mutation == "plan_preservation":
        manifest["plans"]["core"]["edit_preserved"] = False
    elif mutation == "baseline_changed":
        manifest["plans"]["core"]["baseline_id"] = "b" * 64
    elif mutation == "baseline_invalid":
        manifest["plans"]["core"]["baseline_id"] = "private sentinel"
        manifest["plans"]["core"]["previous_baseline_id"] = "private sentinel"
    elif mutation == "plans_missing":
        del manifest["plans"]["core"]
    elif mutation == "summary_not_object":
        receipt["summary"]["core"] = []
    elif mutation == "plan_not_object":
        manifest["plans"]["core"] = []
    elif mutation == "request_mismatch":
        manifest["request"]["workbook_id"] = "unbound-workbook"
    elif mutation == "verification_time":
        receipt["verified_at"] = "private sentinel"
    elif mutation == "empty_counts":
        receipt["summary"]["core"]["students"] = 0
    else:
        plan = manifest["plans"]["core"]
        snapshot = store.load("snapshot", plan["canvas_snapshot_id"])
        snapshot["fetched_at"] = "private sentinel"
        plan["canvas_snapshot_id"], _ = store.save("snapshot", snapshot)
    payload["manifest_id"], _ = store.save("refresh", manifest)
    receipt["manifest_id"] = payload["manifest_id"]
    payload["receipt_id"], _ = store.save("receipt", receipt)
    import json

    with journal.connect() as db:
        db.execute(
            "UPDATE operations SET payload=? WHERE id=?", (json.dumps(payload), RID)
        )
    with pytest.raises(GradebookError) as error:
        await controller.status(RID)
    assert "private sentinel" not in str(error.value)
    assert google.reads == 0 and not google.posts


async def test_mcp_tools_register_only_with_installed_controller(tmp_path):
    class NoCanvas:
        origin = "https://school.example"

    store, google, controller = setup(tmp_path)
    async with Client(
        create_server(NoCanvas(), store, {}, get_refresh_control=controller)
    ) as mcp:
        names = {t.name for t in await mcp.list_tools()}
        assert {
            "request_gradebook_get_refresh",
            "get_gradebook_get_refresh_status",
        } <= names
        result = await mcp.call_tool(
            "get_gradebook_get_refresh_status", {"request_id": RID}
        )
        assert result.data["state"] == "NOT_FOUND"
    async with Client(create_server(NoCanvas(), store, {})) as mcp:
        assert "request_gradebook_get_refresh" not in {
            t.name for t in await mcp.list_tools()
        }
