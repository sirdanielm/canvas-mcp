"""Owner source controls at the final grade transmission boundary."""

import asyncio
from typing import Any

import httpx
import pytest
from test_gradebook import snapshot as snapshot
from test_gradebook_publish import system as system

from canvas_mcp.gradebook.client import GradebookError
from canvas_mcp.gradebook.publish import (
    OwnerControls,
    WriteHeldBeforeSend,
    WriteUncertain,
    put_once,
)


def controls(system: Any, *, check=None, refresh=None, bind=None) -> OwnerControls:
    publisher, state, _, _ = system

    async def fresh(course_id, item):
        state["owner_events"].append("fresh")
        assert state["puts"] == []

    def current(course_id, item):
        state["owner_events"].append("current")

    def binding(plan):
        return {"kind": "SYNTHETIC_OWNER_BINDING", "source": "exact-fixture"}

    state["owner_events"] = []
    return OwnerControls(refresh or fresh, check or current, bind or binding)


async def test_owner_binding_required_without_consuming_token(system):
    publisher, state, review, _ = system
    c = controls(system)
    prepared = await publisher.prepare("12", review, owner_controls=c)
    op = prepared["operation_id"]
    plan = publisher.store.load("push", publisher.ledger.operation(op)["plan_id"])
    assert plan["owner_binding"]["kind"] == "SYNTHETIC_OWNER_BINDING"
    with pytest.raises(GradebookError, match="source owner controls"):
        await publisher.confirm("12", op, prepared["confirmation_token"])
    assert publisher.ledger.operation(op)["status"] == "prepared"
    assert state["puts"] == []
    result = await publisher.confirm("12", op, prepared["confirmation_token"], owner_controls=c)
    assert result["status"] == "verified"
    assert state["owner_events"] == ["fresh", "current", "fresh", "current", "current", "current"]


async def test_owner_check_failure_before_sending_is_known_not_sent(system):
    publisher, state, review, _ = system
    active = True

    def check(course_id, item):
        if not active:
            raise GradebookError("Synthetic source changed")

    c = controls(system, check=check)
    prepared = await publisher.prepare("12", review, owner_controls=c)
    active = False
    with pytest.raises(GradebookError, match="Synthetic source changed"):
        await publisher.confirm("12", prepared["operation_id"], prepared["confirmation_token"], owner_controls=c)
    result = publisher.ledger.summary(prepared["operation_id"])
    assert result["counts"] == {"not_sent": 1}
    assert state["puts"] == []


async def test_last_control_after_sending_checkpoint_prevents_http(system):
    publisher, state, review, _ = system
    operation_id = None

    def check(course_id, item):
        if operation_id is not None:
            operation = publisher.ledger.operation(operation_id)
            if operation["items"][0]["status"] == "sending":
                raise GradebookError("Synthetic source expired at boundary")

    c = controls(system, check=check)
    prepared = await publisher.prepare("12", review, owner_controls=c)
    operation_id = prepared["operation_id"]
    result = await publisher.confirm("12", operation_id, prepared["confirmation_token"], owner_controls=c)
    assert result["status"] == "stopped"
    assert result["counts"] == {"not_sent": 1}
    assert state["puts"] == []
    with publisher.ledger.connect() as db:
        assert db.execute("SELECT count(*) FROM target_locks").fetchone()[0] == 0


async def test_owner_refresh_is_before_final_context_get(system):
    publisher, state, review, _ = system
    checkpoints = []

    async def fresh(course_id, item):
        checkpoints.append(len(state["requests"]))

    def check(course_id, item):
        assert len(state["requests"]) == checkpoints[-1] + 2

    c = controls(system, refresh=fresh, check=check)
    prepared = await publisher.prepare("12", review, owner_controls=c)
    result = await publisher.confirm("12", prepared["operation_id"], prepared["confirmation_token"], owner_controls=c)
    assert result["status"] == "verified"


async def test_binding_cannot_mutate_canonical_plan(system):
    publisher, _, review, _ = system

    def bind(plan):
        plan["items"][0]["proposed"] = 0
        return {"kind": "SYNTHETIC_OWNER_BINDING"}

    c = controls(system, bind=bind)
    prepared = await publisher.prepare("12", review, owner_controls=c)
    plan = publisher.store.load("push", publisher.ledger.operation(prepared["operation_id"])["plan_id"])
    assert plan["items"][0]["proposed"] == 20


async def test_async_current_check_held_before_preparing_operation(system):
    publisher, state, review, _ = system

    async def invalid(course_id, item):
        return None

    c = controls(system, check=invalid)
    with pytest.raises(GradebookError, match="synchronously"):
        await publisher.prepare("12", review, owner_controls=c)
    with publisher.ledger.connect() as db:
        assert db.execute("SELECT count(*) FROM operations").fetchone()[0] == 0
    assert state["puts"] == []


async def test_failed_source_refresh_creates_no_lease(system):
    publisher, state, review, _ = system

    async def invalid(course_id, item):
        raise GradebookError("Synthetic unavailable source")

    c = controls(system, refresh=invalid)
    with pytest.raises(GradebookError, match="unavailable source"):
        await publisher.prepare("12", review, owner_controls=c)
    with publisher.ledger.connect() as db:
        assert db.execute("SELECT count(*) FROM operations").fetchone()[0] == 0
    assert state["requests"] == []
    assert state["puts"] == []


async def test_prior_awaited_request_hook_is_refused_before_transport(system):
    publisher, state, review, _ = system
    c = controls(system)
    prepared = await publisher.prepare("12", review, owner_controls=c)
    hook_ran = False

    async def revoking_hook(request):
        nonlocal hook_ran
        hook_ran = True

    publisher.client.http.event_hooks["request"] = [revoking_hook]
    result = await publisher.confirm("12", prepared["operation_id"], prepared["confirmation_token"], owner_controls=c)
    # The hook can run during GET preflight, but no PUT reaches transport.
    assert hook_ran
    assert result["counts"] == {"not_sent": 1}
    assert state["puts"] == []
    assert publisher.client.http.event_hooks["request"] == [revoking_hook]


async def test_final_http_hook_checks_and_restores_owner_controls(system):
    publisher, state, review, _ = system
    hook_checks = []

    def check(course_id, item):
        if publisher.client.http.event_hooks["request"]:
            hook_checks.append(True)
            raise GradebookError("Synthetic final hook source revocation")

    c = controls(system, check=check)
    prepared = await publisher.prepare("12", review, owner_controls=c)
    result = await publisher.confirm("12", prepared["operation_id"], prepared["confirmation_token"], owner_controls=c)
    assert hook_checks == [True]
    assert result["counts"] == {"not_sent": 1}
    assert state["puts"] == []
    assert publisher.client.http.event_hooks["request"] == []


@pytest.mark.parametrize("phase", ["preliminary", "final"])
@pytest.mark.parametrize("mutation", ["header", "auth", "request_hook", "response_hook",
                                      "client", "origin", "redirects"])
async def test_owned_envelope_frozen_before_callbacks_and_full_state_restored(system, phase, mutation):
    publisher, state, _, _ = system
    client, original = publisher.client, publisher.client.http
    headers, origin = list(original.headers.raw), client.origin
    replacement = httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(200)))

    async def hook(value):
        return None

    def check():
        final = bool(original.event_hooks["request"])
        if final != (phase == "final"):
            return None
        if mutation == "header":
            original.headers["Authorization"] = "Bearer changed-synthetic"
        elif mutation == "auth":
            original.auth = httpx.BasicAuth("synthetic", "synthetic")
        elif mutation == "request_hook":
            original.event_hooks["request"].append(hook)
        elif mutation == "response_hook":
            original.event_hooks["response"].append(hook)
        elif mutation == "client":
            client.http = replacement
        elif mutation == "origin":
            client.origin = "https://other.example"
        else:
            original.follow_redirects = True

    try:
        with pytest.raises(WriteHeldBeforeSend):
            await put_once(client, "12", {"user_id": "101", "assignment_id": "21", "proposed": 20},
                           current_control_check=check)
        assert state["puts"] == []
        assert client.http is original and client.origin == origin
        assert original.headers.raw == headers
        assert original.auth is None and original.follow_redirects is False
        assert original.event_hooks == {"request": [], "response": []}
    finally:
        await replacement.aclose()


async def test_cancelled_preliminary_callback_restores_state_without_http(system):
    publisher, state, _, _ = system
    http = publisher.client.http
    headers = list(http.headers.raw)

    def check():
        http.headers["Authorization"] = "Bearer changed-synthetic"
        http.auth = httpx.BasicAuth("synthetic", "synthetic")
        raise asyncio.CancelledError()

    with pytest.raises(asyncio.CancelledError):
        await put_once(publisher.client, "12", {"user_id": "101", "assignment_id": "21", "proposed": 20},
                       current_control_check=check)
    assert state["puts"] == []
    assert http.headers.raw == headers and http.auth is None
    assert http.event_hooks == {"request": [], "response": []}


async def test_post_send_sink_mutation_is_uncertain_and_restores_client(system):
    publisher, state, _, _ = system
    http = publisher.client.http
    headers = list(http.headers.raw)

    def sink(response):
        http.headers["Authorization"] = "Bearer changed-synthetic"
        http.auth = httpx.BasicAuth("synthetic", "synthetic")

    with pytest.raises(WriteUncertain):
        await put_once(publisher.client, "12", {"user_id": "101", "assignment_id": "21", "proposed": 20},
                       current_control_check=lambda: None, response_sink=sink)
    assert len(state["puts"]) == 1
    assert http.headers.raw == headers and http.auth is None
    assert http.event_hooks == {"request": [], "response": []}
