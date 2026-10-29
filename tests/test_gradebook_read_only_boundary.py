"""Read-only launcher requirements with fictional, immutable push histories."""

import builtins
import hashlib
import importlib.util
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any

import pytest
from fastmcp import Client, FastMCP
from fastmcp.exceptions import ToolError
from mcp.types import ToolAnnotations

from canvas_mcp.gradebook import client as client_module
from canvas_mcp.gradebook import server as server_module
from canvas_mcp.gradebook.ledger import Ledger
from canvas_mcp.gradebook.store import Store

READ_TOOLS = {
    "get_canvas_gradebook",
    "preview_gradebook_changes",
    "get_gradebook_push_status",
}
GENERIC_OPERATION = "a" * 32
OWNED_OPERATIONS = ("b" * 32, "d" * 32, "e" * 32)
UNKNOWN_OPERATION = "c" * 32


def history_fingerprint(root: Path) -> dict[str, str]:
    """Include the ledger, artifacts and any newly created sidecar or lock."""
    return {
        str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in root.rglob("*")
        if path.is_file()
    }


@pytest.fixture
def read_only_service(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Any:
    events: list[str] = []
    home = tmp_path / "fictional-home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("PYTHON_DOTENV_DISABLED", "1")

    credential_module = ModuleType("sdm_canvas_launcher")
    credential_module.SERVICE = "fictional-service"
    credential_module.read_connection = lambda: "https://fcps.instructure.com"
    credential_module.keychain = lambda: SimpleNamespace(
        get_password=lambda *_: "fictional-token"
    )
    monkeypatch.setitem(sys.modules, credential_module.__name__, credential_module)

    class NoNetworkCanvas:
        def __init__(self, origin: str, token: str) -> None:
            assert token == "fictional-token"
            self.origin = origin

        async def snapshot(self, course: str) -> dict[str, Any]:
            events.append("canvas-request")
            raise AssertionError("Local status must not request Canvas")

        async def close(self) -> None:
            events.append("client-close")

        def __getattr__(self, name: str) -> Any:
            events.append("unexpected-client-access:" + name)
            raise AttributeError("Unexpected Canvas client access")

    monkeypatch.setattr(client_module, "GradebookClient", NoNetworkCanvas)
    launcher_path = Path(__file__).resolve().parents[1] / "scripts/sdm_gradebook_launcher.py"
    spec = importlib.util.spec_from_file_location("fictional_boundary_launcher", launcher_path)
    assert spec is not None and spec.loader is not None
    launcher = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(launcher)
    launcher_root = tmp_path / "fictional-launcher-root"
    launcher_root.mkdir()
    monkeypatch.setattr(launcher, "ROOT", launcher_root)
    monkeypatch.setattr(launcher, "COURSES", {"core": "12"})

    state = tmp_path / "fictional-history"
    store = Store(state)
    ledger = Ledger(state)
    operations = [(GENERIC_OPERATION, {})]
    operations.extend(
        (operation, {"owner_binding": marker})
        for operation, marker in zip(
            OWNED_OPERATIONS, ({"kind": "fictional-private-owner"}, None, []), strict=True
        )
    )
    for operation, extra in operations:
        plan, _ = store.save(
            "push",
            {"course_id": "12", "origin": "https://fcps.instructure.com", "items": [], **extra},
        )
        with ledger.connect() as db:
            db.execute(
                "INSERT INTO operations VALUES(?,?,?,?,?,?)",
                (operation, plan, "d" * 64, 2, "uncertain", 1),
            )
            db.execute("INSERT INTO items VALUES(?,?,?,?)", (operation, 0, operation, "uncertain"))
            db.execute("INSERT INTO target_locks VALUES(?,?)", (operation, operation))
    before = history_fingerprint(state)

    captured: list[FastMCP] = []
    actual_create_server = server_module.create_server

    def compose(*args: Any, **kwargs: Any) -> FastMCP:
        assert kwargs.get("enable_push") is False
        assert kwargs.get("enable_comments") is False
        assert kwargs.get("get_refresh_control") is None
        server = actual_create_server(*args, **kwargs)

        @server.tool(annotations=ToolAnnotations(read_only_hint=True))
        async def future_tool() -> str:
            """A future tool must require deliberate profile admission."""
            events.append("future-tool")
            raise AssertionError("Unknown tools must not survive the read-only profile")

        captured.append(server)
        return server

    monkeypatch.setattr(server_module, "create_server", compose)
    monkeypatch.setattr(FastMCP, "run", lambda self: None)
    original_import = builtins.__import__

    def guarded_import(
        name: str,
        global_namespace: dict[str, Any] | None = None,
        local_namespace: dict[str, Any] | None = None,
        fromlist: tuple[str, ...] = (),
        level: int = 0,
    ) -> Any:
        imported = [name, *(name + "." + item for item in fromlist or ())]
        if any(
            item == "sdm_gradebook_worker" or (
                item.startswith("canvas_mcp.gradebook.")
                and any(part in item for part in ("owner", "get_refresh_control", "text_comments_mcp"))
            )
            for item in imported
        ):
            events.append("forbidden-import:" + name)
            raise AssertionError("Read-only startup/status must not import owners or controllers")
        return original_import(name, global_namespace, local_namespace, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", guarded_import)
    monkeypatch.setattr(
        sys, "argv", [str(launcher_path), "--read-only", "--state-dir", str(state)]
    )
    assert launcher.main() == 0
    assert len(captured) == 1
    assert history_fingerprint(state) == before
    assert events == []
    return SimpleNamespace(server=captured[0], state=state, before=before, events=events)


async def test_read_only_exposes_exact_tools_and_rejects_future_tools(read_only_service: Any) -> None:
    fixture = read_only_service
    async with Client(fixture.server) as session:
        tools = await session.list_tools()
        assert {tool.name for tool in tools} == READ_TOOLS
        assert all(tool.annotations is not None and tool.annotations.read_only_hint is True for tool in tools)
        for excluded in ("future_tool", "reconcile_gradebook_push", "request_gradebook_get_refresh"):
            with pytest.raises(ToolError):
                await session.call_tool(excluded, {})
    assert fixture.events == []
    assert history_fingerprint(fixture.state) == fixture.before


async def test_read_only_generic_status_preserves_expired_uncertain_history(read_only_service: Any) -> None:
    fixture = read_only_service
    async with Client(fixture.server) as session:
        response = await session.call_tool(
            "get_gradebook_push_status", {"course": "core", "operation_id": GENERIC_OPERATION}
        )
    assert response.data["status"] == "uncertain"
    assert response.data["counts"] == {"uncertain": 1}
    assert "token" not in response.data and "token_hash" not in response.data
    assert fixture.events == []
    assert history_fingerprint(fixture.state) == fixture.before


@pytest.mark.parametrize("operation", [UNKNOWN_OPERATION, *OWNED_OPERATIONS])
async def test_read_only_unknown_or_owned_status_stays_held_without_side_effects(
    read_only_service: Any, operation: str
) -> None:
    fixture = read_only_service
    async with Client(fixture.server) as session:
        response = await session.call_tool(
            "get_gradebook_push_status", {"course": "core", "operation_id": operation}
        )
    assert "error" in response.data
    assert "status" not in response.data
    assert fixture.events == []
    assert history_fingerprint(fixture.state) == fixture.before
