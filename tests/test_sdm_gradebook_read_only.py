"""Fictional launcher inputs; no saved credentials, clients or worker state."""

from __future__ import annotations

import builtins
import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any
from unittest.mock import Mock

import pytest

SCRIPT = Path(__file__).parents[1] / "scripts" / "sdm_gradebook_launcher.py"
READ_TOOLS = {
    "get_canvas_gradebook",
    "preview_gradebook_changes",
    "get_gradebook_push_status",
}


def load_launcher() -> ModuleType:
    spec = importlib.util.spec_from_file_location("fictional_gradebook_launcher", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize(
    ("arguments", "message"),
    [
        (["--read-only", "--enable-push"], "cannot be combined"),
        (["--read-only", "--enable-comments"], "cannot be combined"),
        (["--read-only", "--call", "prepare_gradebook_refresh"], "excludes this tool"),
        (["--read-only", "--call", "request_gradebook_get_refresh"], "excludes this tool"),
        (["--read-only", "--call", "authorize_gradebook_batch"], "excludes this tool"),
        (["--read-only", "--call", "execute_gradebook_batch_chunk"], "excludes this tool"),
        (["--read-only", "--call", "future_tool"], "invalid choice"),
        (["--comment-approval-seconds", "599"], "between 600 and 1800"),
        (["--comment-approval-seconds", "1801"], "between 600 and 1800"),
    ],
)
def test_invalid_arguments_precede_credential_and_data_imports(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    arguments: list[str],
    message: str,
) -> None:
    original_import = builtins.__import__

    def guarded_import(name: str, *args: Any, **kwargs: Any) -> Any:
        if name == "sdm_canvas_launcher" or name == "sdm_gradebook_worker" or name.startswith("canvas_mcp"):
            raise AssertionError("Credential or data module imported before argument rejection")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", guarded_import)
    monkeypatch.setattr(sys, "argv", [str(SCRIPT), *arguments])
    with pytest.raises(SystemExit) as exc:
        load_launcher().main()
    assert exc.value.code == 2
    assert message in capsys.readouterr().err


@pytest.fixture
def fictional_runtime(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> SimpleNamespace:
    calls = SimpleNamespace(servers=[], snapshots=[], closed=0, saved=[], tool_calls=[])
    helpers = ModuleType("sdm_canvas_launcher")
    helpers.SERVICE = "fictional-gradebook"  # type: ignore[attr-defined]
    helpers.read_connection = Mock(return_value="https://fcps.instructure.com")  # type: ignore[attr-defined]
    helpers.keychain = Mock(return_value=SimpleNamespace(get_password=Mock(return_value="fictional-token")))  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "sdm_canvas_launcher", helpers)

    class FakeClient:
        def __init__(self, origin: str, token: str) -> None:
            assert origin == "https://fcps.instructure.com" and token == "fictional-token"

        async def snapshot(self, course: str) -> dict[str, Any]:
            calls.snapshots.append(course)
            return {"fictional_snapshot": True}

        async def close(self) -> None:
            calls.closed += 1

    class FakeStore:
        def __init__(self, root: Path) -> None:
            self.root = root

        def save(self, kind: str, value: dict[str, Any]) -> tuple[str, Path]:
            calls.saved.append((kind, value))
            return "fictional-snapshot", self.root / "fictional.json"

    class FakeServer:
        def __init__(self, kwargs: dict[str, Any], bindings: dict[str, Any]) -> None:
            self.kwargs = kwargs
            self.bindings = bindings
            self.names = READ_TOOLS | {"prepare_gradebook_refresh", "future_tool"}
            self.local_provider = SimpleNamespace(remove_tool=self.names.remove)
            self.ran = False

        async def list_tools(self, **kwargs: Any) -> list[SimpleNamespace]:
            return [SimpleNamespace(name=name) for name in self.names]

        def run(self) -> None:
            self.ran = True

    def create_server(
        client: FakeClient,
        store: FakeStore,
        courses: dict[str, str],
        bindings: dict[str, Any],
        **kwargs: Any,
    ) -> FakeServer:
        server = FakeServer(kwargs, bindings)
        calls.servers.append(server)
        return server

    stubs = {
        "canvas_mcp.gradebook.client": {"GradebookClient": FakeClient, "GradebookError": ValueError},
        "canvas_mcp.gradebook.model": {"summary": lambda snapshot: {"fictional_summary": True}},
        "canvas_mcp.gradebook.store": {"Store": FakeStore},
        "canvas_mcp.gradebook.server": {"create_server": create_server},
    }
    for name, attributes in stubs.items():
        module = ModuleType(name)
        module.__dict__.update(attributes)
        monkeypatch.setitem(sys.modules, name, module)
    launcher = load_launcher()
    monkeypatch.setattr(launcher, "ROOT", tmp_path)
    calls.launcher = launcher
    calls.root = tmp_path
    return calls


def test_read_only_skips_workbook_and_worker_inputs(
    fictional_runtime: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    runtime = fictional_runtime
    original_import = builtins.__import__
    original_read_text = Path.read_text

    def guarded_import(name: str, *args: Any, **kwargs: Any) -> Any:
        if name in {"sdm_gradebook_worker", "canvas_mcp.gradebook.get_refresh_control"}:
            raise AssertionError("Read-only startup imported worker/controller")
        return original_import(name, *args, **kwargs)

    def guarded_read_text(path: Path, *args: Any, **kwargs: Any) -> str:
        if path.name == "sdm-gradebook-workbooks.json":
            raise AssertionError("Read-only startup read workbook bindings")
        return original_read_text(path, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", guarded_import)
    monkeypatch.setattr(Path, "read_text", guarded_read_text)
    monkeypatch.setattr(sys, "argv", [str(SCRIPT), "--read-only", "--state-dir", str(runtime.root / "isolated")])
    assert runtime.launcher.main() == 0
    server, = runtime.servers
    assert server.bindings == {}
    assert server.kwargs["get_refresh_control"] is None
    assert server.kwargs["enable_push"] is False
    assert server.kwargs["enable_comments"] is False
    assert server.names == READ_TOOLS
    assert server.ran
    assert not runtime.snapshots and not runtime.saved


def test_default_startup_preserves_bindings_and_public_comment_window(
    fictional_runtime: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    runtime = fictional_runtime
    config = runtime.root / "config" / "sdm-gradebook-workbooks.json"
    config.parent.mkdir()
    bindings = {"core": {"get_tab": "Fictional GET"}}
    config.write_text(json.dumps(bindings), encoding="utf-8")
    worker = ModuleType("sdm_gradebook_worker")
    worker.DEFAULT_CONFIG = runtime.root / "missing-worker.json"  # type: ignore[attr-defined]
    worker.google_client = Mock(side_effect=AssertionError("Unexpected Google client"))  # type: ignore[attr-defined]
    worker.load_config = Mock(side_effect=AssertionError("Unexpected worker configuration"))  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "sdm_gradebook_worker", worker)
    monkeypatch.setattr(sys, "argv", [str(SCRIPT), "--enable-comments", "--comment-approval-seconds", "1800"])
    assert runtime.launcher.main() == 0
    server, = runtime.servers
    assert server.bindings == bindings
    assert server.kwargs["enable_comments"] is True
    assert server.kwargs["comment_approval_seconds"] == 1800
    assert "future_tool" in server.names and server.ran
    worker.load_config.assert_not_called()  # type: ignore[attr-defined]
    worker.google_client.assert_not_called()  # type: ignore[attr-defined]


def test_read_only_does_not_start_when_an_expected_tool_is_missing(
    fictional_runtime: SimpleNamespace,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    runtime = fictional_runtime
    server_module = sys.modules["canvas_mcp.gradebook.server"]
    original_factory = server_module.create_server

    def incomplete_factory(*args: Any, **kwargs: Any) -> Any:
        server = original_factory(*args, **kwargs)
        server.names.remove("get_gradebook_push_status")
        return server

    monkeypatch.setattr(server_module, "create_server", incomplete_factory)
    monkeypatch.setattr(sys, "argv", [str(SCRIPT), "--read-only"])
    assert runtime.launcher.main() == 1
    server, = runtime.servers
    assert not server.ran
    assert "startup failed" in capsys.readouterr().err


@pytest.mark.parametrize("read_only", [False, True])
def test_snapshot_behavior_does_not_load_workbook_or_worker(
    fictional_runtime: SimpleNamespace,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    read_only: bool,
) -> None:
    runtime = fictional_runtime
    arguments = [str(SCRIPT), "--snapshot", "core"]
    if read_only:
        arguments.append("--read-only")
    monkeypatch.setattr(sys, "argv", arguments)
    assert runtime.launcher.main() == 0
    assert len(runtime.snapshots) == 1 and runtime.closed == 1
    assert len(runtime.saved) == 1 and not runtime.servers
    assert json.loads(capsys.readouterr().out)["canvas_writes"] == 0
