"""Exercise the real HTTP entrypoint before parsing or credential-side effects."""

import asyncio
import json
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import pytest
from starlette.testclient import TestClient

from canvas_mcp import server
from canvas_mcp.core.credentials import get_request_credentials, is_http_request_active

BODY_LIMIT = 1024 * 1024


def build_http_app(monkeypatch: pytest.MonkeyPatch, inner: Any) -> Any:
    """Capture the same outer app that the HTTP launcher gives to uvicorn."""
    import anyio
    import uvicorn

    captured = {}
    monkeypatch.setattr(uvicorn, "Config", lambda app, **kwargs: captured.setdefault("app", app))
    monkeypatch.setattr(uvicorn, "Server", MagicMock())
    monkeypatch.setattr(anyio, "run", lambda fn: None)
    monkeypatch.setattr(server, "get_config", lambda: SimpleNamespace(
        entra_auth_enabled=False, mcp_access_keys=frozenset({"fixture-key"}),
        canvas_api_url="https://canvas.example.invalid/api/v1",
    ))
    server._run_http_server(SimpleNamespace(http_app=lambda **kwargs: inner), "127.0.0.1", 0)
    return captured["app"]


async def request(app: Any, frames: list[dict[str, Any]], *, headers: list | None = None,
                  path: str = "/mcp") -> tuple[list, list, int]:
    sent: list = []
    reads = 0

    async def receive() -> dict[str, Any]:
        nonlocal reads
        reads += 1
        assert frames, "request read past its complete body"
        return frames.pop(0)

    async def send(message: dict[str, Any]) -> None:
        sent.append(message)

    scope = {"type": "http", "method": "POST", "path": path, "headers": [
        (b"x-mcp-access-key", b"fixture-key"), (b"x-canvas-token", b"fixture-token"),
        *(headers or []),
    ]}
    await app(scope, receive, send)
    return sent, frames, reads


def body_frame(data: bytes, more: bool = False) -> dict[str, Any]:
    return {"type": "http.request", "body": data, "more_body": more}


def accepting_app(calls: list) -> Any:
    async def inner(scope: dict, receive: Any, send: Any) -> None:
        calls.append(scope["type"])
        assert is_http_request_active()
        assert get_request_credentials() is not None
        data = bytearray()
        while True:
            msg = await receive()
            data.extend(msg.get("body", b""))
            if not msg.get("more_body", False):
                break
        result = json.dumps({"bytes": len(data)}).encode()
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": result})
    return inner


@pytest.mark.asyncio
async def test_oversized_declared_body_is_refused_before_receive_or_application(monkeypatch):
    calls = []
    app = build_http_app(monkeypatch, accepting_app(calls))
    sent, _, reads = await request(app, [body_frame(b"unused")],
                                   headers=[(b"content-length", str(BODY_LIMIT + 1).encode())])
    assert sent[0]["status"] == 413
    assert reads == 0
    assert not calls
    assert get_request_credentials() is None and not is_http_request_active()


@pytest.mark.asyncio
@pytest.mark.parametrize("headers", [[], [(b"content-length", b"1")]])
async def test_stream_cap_rejects_missing_or_understated_length_before_app(monkeypatch, headers):
    calls = []
    app = build_http_app(monkeypatch, accepting_app(calls))
    sent, remaining, reads = await request(app, [body_frame(b"x" * BODY_LIMIT, True),
        body_frame(b"x", True), body_frame(b"unread")], headers=headers)
    assert sent[0]["status"] == 413
    assert reads == 2 and len(remaining) == 1
    assert not calls
    assert get_request_credentials() is None and not is_http_request_active()


@pytest.mark.asyncio
@pytest.mark.parametrize("size", [0, BODY_LIMIT - 1, BODY_LIMIT])
async def test_limit_is_inclusive_and_replayed_exactly_once(monkeypatch, size):
    calls = []
    app = build_http_app(monkeypatch, accepting_app(calls))
    sent, _, _ = await request(app, [body_frame(b"a" * size)],
                              headers=[(b"content-length", str(size).encode())])
    assert sent[0]["status"] == 200
    assert json.loads(sent[1]["body"]) == {"bytes": size}
    assert calls == ["http"]
    assert get_request_credentials() is None and not is_http_request_active()


@pytest.mark.asyncio
@pytest.mark.parametrize("headers", [
    [(b"content-length", b"-1")], [(b"content-length", b"abc")],
    [(b"content-length", b"1"), (b"content-length", b"1")],
    [(b"content-length", b"1"), (b"Content-Length", b"2")],
    [(b"content-length", b"1"), (b"transfer-encoding", b"chunked")],
])
async def test_ambiguous_or_invalid_length_is_rejected_before_body(monkeypatch, headers):
    calls = []
    app = build_http_app(monkeypatch, accepting_app(calls))
    sent, _, reads = await request(app, [body_frame(b"x")], headers=headers)
    assert sent[0]["status"] == 400
    assert reads == 0 and not calls


@pytest.mark.asyncio
async def test_declared_length_must_match_actual_completed_body(monkeypatch):
    calls = []
    app = build_http_app(monkeypatch, accepting_app(calls))
    sent, _, _ = await request(app, [body_frame(b"short")], headers=[(b"content-length", b"10")])
    assert sent[0]["status"] == 400 and not calls


@pytest.mark.asyncio
async def test_public_form_keeps_its_smaller_eight_kib_limit(monkeypatch):
    calls = []
    app = build_http_app(monkeypatch, accepting_app(calls))
    sent, _, _ = await request(app, [body_frame(b"x" * 8193)], path="/admin/access/confirm")
    assert sent[0]["status"] == 413 and not calls


@pytest.mark.asyncio
async def test_disconnect_never_passes_partial_json_to_application(monkeypatch):
    calls = []
    app = build_http_app(monkeypatch, accepting_app(calls))
    sent, _, _ = await request(app, [body_frame(b'{"jsonrpc":', True), {"type": "http.disconnect"}])
    assert not sent and not calls
    assert get_request_credentials() is None and not is_http_request_active()


@pytest.mark.asyncio
async def test_replay_preserves_following_disconnect_for_streamed_responses(monkeypatch):
    observed = []

    async def inner(scope, receive, send):
        observed.extend([await receive(), await receive()])

    app = build_http_app(monkeypatch, inner)
    await request(app, [body_frame(b"a", True), body_frame(b"b"), {"type": "http.disconnect"}])
    assert observed == [body_frame(b"ab"), {"type": "http.disconnect"}]


@pytest.mark.asyncio
async def test_empty_frames_do_not_accumulate_retained_chunk_objects():
    import tracemalloc

    remaining = 50_000

    async def receive():
        nonlocal remaining
        remaining -= 1
        return body_frame(b"", remaining > 0)

    tracemalloc.start()
    try:
        assert await server._read_body(receive, max_bytes=8192) == b""
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    # A zero-byte body must not retain an attacker-selected list of 50k frames.
    assert peak < 256 * 1024


@pytest.mark.asyncio
async def test_invalid_utf8_is_not_removed_to_turn_a_bad_key_into_a_valid_key(monkeypatch):
    calls = []
    app = build_http_app(monkeypatch, accepting_app(calls))
    sent, _, _ = await request(app, [body_frame(b"")],
                              headers=[(b"x-mcp-access-key", b"fixture-\xffkey")])
    assert sent[0]["status"] == 401 and not calls


@pytest.mark.asyncio
async def test_cancellation_during_body_read_never_enters_application(monkeypatch):
    calls = []
    app = build_http_app(monkeypatch, accepting_app(calls))
    entered = asyncio.Event()

    async def receive():
        entered.set()
        await asyncio.Event().wait()

    task = asyncio.create_task(app({"type": "http", "path": "/mcp", "headers": [],
                                    "method": "POST"}, receive, None))
    await asyncio.wait_for(entered.wait(), 1)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert not calls
    assert get_request_credentials() is None and not is_http_request_active()


def test_real_mcp_initialization_remains_available_below_limit(monkeypatch):
    from fastmcp import FastMCP

    mcp = FastMCP("bounded-test")
    app = build_http_app(monkeypatch, mcp.http_app(stateless_http=True))
    with TestClient(app) as client:
        response = client.post("/mcp", headers={
            "X-MCP-Access-Key": "fixture-key", "X-Canvas-Token": "fixture-token",
            "Accept": "application/json, text/event-stream",
        }, json={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
            "protocolVersion": "2024-11-05", "capabilities": {},
            "clientInfo": {"name": "fixture", "version": "1"},
        }})
    assert response.status_code == 200
    assert "serverInfo" in response.text and '"error"' not in response.text


@pytest.mark.parametrize("position", [0, 1, 2, None])
def test_every_access_key_is_compared_even_after_a_match(monkeypatch, position):
    allowed = frozenset({"fixture-first", "fixture-second", "fixture-third"})
    order = list(allowed)
    presented = "fixture-missing" if position is None else order[position]
    original = server.hmac.compare_digest
    compared = []

    def compare(left, right):
        compared.append(right)
        return original(left, right)

    monkeypatch.setattr(server.hmac, "compare_digest", compare)
    assert server._access_key_ok(presented, allowed) is (position is not None)
    assert len(compared) == len(allowed)


def test_non_ascii_access_keys_fail_closed_or_match_exact_utf8_bytes():
    assert not server._access_key_ok("not-ascii-\u00e9", frozenset({"fixture-key"}))
    assert server._access_key_ok("fixture-\u00e9", frozenset({"fixture-\u00e9", "other"}))
    assert not server._access_key_ok("", frozenset())
