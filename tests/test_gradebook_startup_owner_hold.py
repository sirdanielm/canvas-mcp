"""Optional source-owner holds preserve read startup and fail closed on actions."""

from types import SimpleNamespace

import httpx
import pytest
from fastmcp import Client

import canvas_mcp.gradebook.server as server_module
from canvas_mcp.gradebook.client import GradebookClient, GradebookError
from canvas_mcp.gradebook.store import Store


@pytest.fixture
async def harness(tmp_path, monkeypatch):
    events = []
    requests = []

    def transport(request):
        requests.append(request)
        raise AssertionError("No HTTP is needed by these routing regressions")

    client = GradebookClient(
        "https://canvas.invalid", "synthetic-token", httpx.MockTransport(transport)
    )
    store = Store(tmp_path / "state")
    review_id, _ = store.save("review", {"changes": []})
    plan_id, _ = store.save(
        "push", {"course_id": "12", "origin": client.origin, "items": []}
    )
    state = SimpleNamespace(
        events=events, requests=requests, client=client, store=store,
        review_id=review_id, plan_id=plan_id, consumed_tokens=0,
    )
    original_load = store.load

    def load(kind, artifact_id):
        events.append(("load", kind))
        return original_load(kind, artifact_id)

    monkeypatch.setattr(store, "load", load)

    class RoutingPublisher:
        def __init__(self, client, store, ledger):
            self.client, self.store, self.ledger = client, store, ledger
            state.publisher = self
            monkeypatch.setattr(ledger, "operation", self.operation)
            monkeypatch.setattr(ledger, "summary", self.summary)

        def operation(self, operation_id):
            events.append(("operation", operation_id))
            return {"plan_id": state.plan_id, "status": "prepared"}

        def summary(self, operation_id):
            events.append(("summary", operation_id))
            return {"status": "prepared", "counts": {"not_sent": 1}}

        async def prepare(self, course_id, review_id):
            events.append(("generic_prepare", review_id))
            return {"operation_id": "synthetic-operation", "canvas_writes": 0}

        async def confirm(self, course_id, operation_id, token):
            events.append(("generic_confirm", operation_id))
            state.consumed_tokens += 1
            return {"status": "synthetic-generic-confirm"}

        async def reconcile(self, course_id, operation_id):
            events.append(("generic_reconcile", operation_id))
            return {"status": "synthetic-readback", "canvas_writes": 0}

    monkeypatch.setattr(server_module, "Publisher", RoutingPublisher)
    yield state
    await client.close()


def make_server(harness, **kwargs):
    return server_module.create_server(
        harness.client, harness.store, {"core": "12"}, **kwargs
    )


def raising_factory(events, name="legacy"):
    def factory(publisher):
        events.append(("factory", name))
        raise GradebookError("Synthetic configuration pin mismatch")

    return factory


async def test_config_pin_hold_does_not_prevent_read_tool_registration(harness):
    server = make_server(
        harness, enable_push=True,
        unit1_score_handler_factory=raising_factory(harness.events),
    )
    async with Client(server) as mcp:
        tools = {tool.name for tool in await mcp.list_tools()}
    assert {"get_canvas_gradebook", "get_gradebook_push_status",
            "reconcile_gradebook_push", "confirm_gradebook_push"} <= tools
    assert harness.events == []
    assert harness.requests == []


@pytest.mark.parametrize("tool", ["prepare_gradebook_push", "confirm_gradebook_push"])
@pytest.mark.parametrize("failed_owner", ["legacy", "pair"])
async def test_owner_hold_precedes_artifact_lookup_fallback_and_token_use(
    harness, tool, failed_owner,
):
    def other_factory(publisher):
        harness.events.append(("factory", "legacy"))
        return None

    options = {"unit1_score_handler_factory": raising_factory(harness.events)}
    if failed_owner == "pair":
        options = {
            "unit1_score_handler_factory": other_factory,
            "unit1_pair_score_handler_factory": raising_factory(harness.events, "pair"),
        }
    server = make_server(harness, enable_push=True, **options)
    arguments = {"course": "core", "review_id": harness.review_id}
    if tool == "confirm_gradebook_push":
        arguments = {"course": "core", "operation_id": "synthetic-operation",
                     "confirmation_token": "unconsumed-synthetic-token"}
    async with Client(server) as mcp:
        result = await mcp.call_tool(tool, arguments)
    assert "configuration pin mismatch" in result.data["error"]
    assert all(event[0] == "factory" for event in harness.events)
    assert harness.consumed_tokens == 0
    assert harness.requests == []


async def test_generic_status_and_reconcile_do_not_initialize_source_owners(harness):
    server = make_server(
        harness, enable_push=True,
        unit1_score_handler_factory=raising_factory(harness.events),
        unit1_pair_score_handler_factory=raising_factory(harness.events, "pair"),
    )
    async with Client(server) as mcp:
        status = await mcp.call_tool(
            "get_gradebook_push_status",
            {"course": "core", "operation_id": "synthetic-operation"},
        )
        reconciled = await mcp.call_tool(
            "reconcile_gradebook_push",
            {"course": "core", "operation_id": "synthetic-operation"},
        )
    assert status.data["status"] == "prepared"
    assert reconciled.data["status"] == "synthetic-readback"
    assert not any(event[0] == "factory" for event in harness.events)
    assert harness.consumed_tokens == 0
    assert harness.requests == []


async def test_pair_factory_failure_does_not_cache_partial_legacy_owner(harness):
    calls = {"legacy": 0, "pair": 0}
    available = False

    class LegacyHandler:
        def recognizes_review(self, review_id):
            return review_id == "synthetic-manifest-reference"

        async def prepare(self, publisher, course_id, review_id):
            harness.events.append(("legacy_prepare", review_id))
            return {"operation_id": "synthetic-owned-operation", "canvas_writes": 0}

    def legacy_factory(publisher):
        calls["legacy"] += 1
        return LegacyHandler()

    def pair_factory(publisher):
        calls["pair"] += 1
        if not available:
            raise GradebookError("Synthetic pair configuration pin mismatch")
        return None

    server = make_server(
        harness, enable_push=True, unit1_score_handler_factory=legacy_factory,
        unit1_pair_score_handler_factory=pair_factory,
    )
    async with Client(server) as mcp:
        arguments = {"course": "core", "review_id": "synthetic-manifest-reference"}
        for _ in range(2):
            held = await mcp.call_tool("prepare_gradebook_push", arguments)
            assert "configuration pin mismatch" in held.data["error"]
            assert not any(event[0] == "legacy_prepare" for event in harness.events)
        assert calls == {"legacy": 2, "pair": 2}
        available = True
        for _ in range(2):
            result = await mcp.call_tool("prepare_gradebook_push", arguments)
            assert result.data["operation_id"] == "synthetic-owned-operation"
    assert calls == {"legacy": 3, "pair": 3}
    assert len([event for event in harness.events if event[0] == "legacy_prepare"]) == 2
    assert not any(event[0] in {"load", "generic_prepare"} for event in harness.events)
    assert harness.requests == []


async def test_paired_owner_plan_status_confirm_and_reconcile_keep_owner_route(harness):
    calls = []
    plan_id, _ = harness.store.save(
        "push", {"course_id": "12", "origin": harness.client.origin,
                 "items": [], "owner_binding": {"kind": "synthetic-pair"}},
    )
    harness.plan_id = plan_id

    class PairHandler:
        def matches_plan(self, course_id, plan):
            return course_id == "12" and plan["owner_binding"]["kind"] == "synthetic-pair"

        def status(self, course_id, operation_id):
            calls.append("status")
            return {"status": "synthetic-owner-status"}

        async def confirm(self, publisher, course_id, operation_id, token):
            calls.append("confirm")
            assert token == "synthetic-owner-token"
            return {"status": "synthetic-owner-confirm"}

        async def reconcile(self, publisher, course_id, operation_id):
            calls.append("reconcile")
            return {"status": "synthetic-owner-reconcile"}

    def factory(publisher):
        calls.append("factory")
        return PairHandler()

    server = make_server(
        harness, enable_push=True, unit1_pair_score_handler_factory=factory,
    )
    async with Client(server) as mcp:
        for tool, expected in [
            ("get_gradebook_push_status", "synthetic-owner-status"),
            ("confirm_gradebook_push", "synthetic-owner-confirm"),
            ("reconcile_gradebook_push", "synthetic-owner-reconcile"),
        ]:
            arguments = {"course": "core", "operation_id": "synthetic-operation"}
            if tool == "confirm_gradebook_push":
                arguments["confirmation_token"] = "synthetic-owner-token"
            result = await mcp.call_tool(tool, arguments)
            assert result.data["status"] == expected
    assert calls == ["factory", "status", "confirm", "reconcile"]
    assert not any(event[0].startswith("generic_") for event in harness.events)
    assert harness.consumed_tokens == 0
    assert harness.requests == []


async def test_disabled_push_never_initializes_owner_factories(harness):
    server = make_server(
        harness, enable_push=False,
        unit1_score_handler_factory=raising_factory(harness.events),
        unit1_pair_score_handler_factory=raising_factory(harness.events, "pair"),
    )
    async with Client(server) as mcp:
        tools = {tool.name for tool in await mcp.list_tools()}
        result = await mcp.call_tool(
            "prepare_gradebook_push", {"course": "core", "review_id": harness.review_id}
        )
    assert "confirm_gradebook_push" not in tools
    assert result.data["publishing_available"] is False
    assert not any(event[0] == "factory" for event in harness.events)
    assert harness.requests == []


@pytest.mark.parametrize("tool", ["get_gradebook_push_status", "reconcile_gradebook_push"])
async def test_owned_readback_stays_held_when_its_owner_configuration_fails(harness, tool):
    harness.plan_id, _ = harness.store.save(
        "push", {"course_id": "12", "origin": harness.client.origin,
                 "items": [], "owner_binding": {"kind": "synthetic-pair"}},
    )
    server = make_server(
        harness, enable_push=True,
        unit1_pair_score_handler_factory=raising_factory(harness.events, "pair"),
    )
    async with Client(server) as mcp:
        result = await mcp.call_tool(
            tool, {"course": "core", "operation_id": "synthetic-operation"}
        )
    assert "configuration pin mismatch" in result.data["error"]
    assert ("factory", "pair") in harness.events
    assert not any(event[0] in {"summary", "generic_reconcile"}
                   for event in harness.events)
    assert harness.consumed_tokens == 0
    assert harness.requests == []
