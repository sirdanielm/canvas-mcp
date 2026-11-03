"""Pure synthetic diagnostics; no real package, server, client or credentials."""

from __future__ import annotations

import ast
import asyncio
import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
HELPER = ROOT / "src/canvas_mcp/gradebook/runtime_diagnostics.py"
SERVER = ROOT / "src/canvas_mcp/gradebook/server.py"


class SyntheticGradebookError(Exception):
    pass


SYNTHETIC_SOURCE = '''
def _observation_holds(value, *, comment_only=False):
    return ["old-excusal-policy"] if value else []

def _parse_source(value, *, submission=False, comment_only=False):
    return value

def _raw_fields(value, names):
    return tuple((name, value.get(name)) for name in names)

def parse_exact_observation(value, *, comment_only=False):
    return _observation_holds(value, comment_only=comment_only)

def parse_comment_state(value):
    return parse_exact_observation(value, comment_only=True)

async def comment_state(value):
    return value

def comment_spec(value):
    return parse_comment_state(value)

class Publisher:
    def __init__(self, client, store, ledger):
        self.client, self.store, self.ledger = client, store, ledger

    async def prepare_comment(self, course, filename, digest):
        EVENTS.append((course, filename, digest))
        if PREVIEW_MODE == "hold":
            raise GradebookError("Synthetic protection hold")
        if PREVIEW_MODE == "unexpected":
            raise RuntimeError("synthetic-private-payload")
        return {"ready_for_confirmation": True, "changes": 1, "canvas_writes": 0}
'''


def synthetic_namespace(source=SYNTHETIC_SOURCE, filename="synthetic-original.py"):
    namespace = {
        "EVENTS": [], "PREVIEW_MODE": "success",
        "GradebookError": SyntheticGradebookError,
    }
    exec(compile(source, filename, "exec"), namespace)
    return namespace


def load_helper():
    spec = importlib.util.spec_from_file_location("isolated_runtime_diagnostics", HELPER)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class RegistryOnlyMCP:
    """Record decorators; performs no MCP initialization or transport action."""

    def __init__(self, name):
        self.name, self.tools = name, {}

    def tool(self, **kwargs):
        def decorate(function):
            self.tools[function.__name__] = function
            return function
        return decorate


def isolated_server(namespace):
    tree = ast.parse(SERVER.read_text(encoding="utf-8"))
    function = next(node for node in tree.body if isinstance(node, ast.FunctionDef)
                    and node.name == "create_server")
    isolated = ast.Module(body=[
        ast.ImportFrom(module="__future__", names=[ast.alias(name="annotations")], level=0),
        function,
    ], type_ignores=[])
    ast.fix_missing_locations(isolated)
    globals_ = {
        "FastMCP": RegistryOnlyMCP,
        "Publisher": namespace["Publisher"],
        "Ledger": lambda root: object(),
        "BatchPublisher": lambda publisher: object(),
        "ToolAnnotations": lambda **kwargs: None,
        "GradebookError": SyntheticGradebookError,
    }
    if HELPER.exists():
        globals_["capture_comment_runtime"] = load_helper().capture_comment_runtime
    exec(compile(isolated, str(SERVER), "exec"), globals_)
    return globals_["create_server"](
        object(), SimpleNamespace(root=Path("/unused-synthetic-state")),
        {"core": "fictional-course"},
    )


def preview(server):
    return asyncio.run(server.tools["prepare_gradebook_comment_push"](
        "core", "synthetic.json", "synthetic-digest",
    ))


def test_existing_comment_preview_result_reports_loaded_fingerprint():
    namespace = synthetic_namespace()
    result = preview(isolated_server(namespace))
    assert result["ready_for_confirmation"] is True
    assert result["canvas_writes"] == 0
    assert result["loaded_comment_runtime"]["status"] == "CAPTURED"
    assert len(result["loaded_comment_runtime"]["function_sha256"]) == 4
    assert namespace["EVENTS"] == [
        ("fictional-course", "synthetic.json", "synthetic-digest")
    ]


def test_fingerprint_normalizes_paths_and_lines_in_nested_code():
    helper = load_helper()
    nested = SYNTHETIC_SOURCE.replace(
        '["old-excusal-policy"] if value else []',
        '[item for item in ("old-excusal-policy",) if value]',
    )
    first = synthetic_namespace(nested, "/private/old/location.py")
    moved = synthetic_namespace("\n" * 17 + nested, "/different/location.py")
    a = helper.capture_comment_runtime(first["Publisher"]).as_dict()
    b = helper.capture_comment_runtime(moved["Publisher"]).as_dict()
    assert a["function_sha256"] == b["function_sha256"]
    assert a["coverage"] == {"expected_functions": 4, "captured_functions": 4}
    assert "/private" not in json.dumps(a)
    assert "/different" not in json.dumps(b)


def test_final_policy_helper_change_changes_identity_with_unchanged_parser():
    helper = load_helper()
    old = synthetic_namespace()
    new = synthetic_namespace(SYNTHETIC_SOURCE.replace(
        '["old-excusal-policy"] if value else []', '[]',
    ))
    a = helper.capture_comment_runtime(old["Publisher"]).as_dict()
    b = helper.capture_comment_runtime(new["Publisher"]).as_dict()
    assert a["function_sha256"]["protocol.parse_exact_observation"] == (
        b["function_sha256"]["protocol.parse_exact_observation"]
    )
    assert a["function_sha256"]["protocol._observation_holds"] != (
        b["function_sha256"]["protocol._observation_holds"]
    )
    assert a["function_sha256"] != b["function_sha256"]
    assert old["EVENTS"] == new["EVENTS"] == []


def test_changed_source_file_does_not_relabel_already_loaded_functions(tmp_path, monkeypatch):
    helper = load_helper()
    source = tmp_path / "synthetic_policy.py"
    source.write_text(SYNTHETIC_SOURCE, encoding="utf-8")
    old = synthetic_namespace(source.read_text(encoding="utf-8"), str(source))
    snapshot = helper.capture_comment_runtime(old["Publisher"])
    source.write_text(SYNTHETIC_SOURCE.replace("old-excusal-policy", "new-policy"), encoding="utf-8")
    new = synthetic_namespace(source.read_text(encoding="utf-8"), str(source))

    def forbidden_read(*args, **kwargs):
        raise AssertionError("Fingerprinting must not read source from disk")

    monkeypatch.setattr(Path, "read_text", forbidden_read)
    monkeypatch.setattr(Path, "read_bytes", forbidden_read)
    monkeypatch.setattr("builtins.open", forbidden_read)
    assert helper.capture_comment_runtime(old["Publisher"]).function_sha256 == (
        snapshot.function_sha256
    )
    assert helper.capture_comment_runtime(new["Publisher"]).function_sha256 != (
        snapshot.function_sha256
    )


def test_server_snapshot_survives_rebinding_and_result_mutation():
    namespace = synthetic_namespace()
    server = isolated_server(namespace)
    initial = preview(server)["loaded_comment_runtime"]
    fingerprints = initial["function_sha256"].copy()
    captured_at = initial["captured_at"]
    changed = synthetic_namespace(SYNTHETIC_SOURCE.replace("old-excusal-policy", "new-policy"))
    namespace["_observation_holds"] = changed["_observation_holds"]
    initial["function_sha256"].clear()
    initial["coverage"]["captured_functions"] = -1
    next_result = preview(server)["loaded_comment_runtime"]
    assert next_result["function_sha256"] == fingerprints
    assert next_result["captured_at"] == captured_at
    assert len(next_result["function_sha256"]) == 4
    assert next_result["coverage"]["captured_functions"] == 4
    assert preview(isolated_server(namespace))["loaded_comment_runtime"]["function_sha256"] != fingerprints


@pytest.mark.parametrize("mode,error", [
    ("hold", "Synthetic protection hold"),
    ("unexpected", "Comment preview failed; nothing sent."),
])
def test_existing_error_paths_keep_semantics_and_report_snapshot(mode, error):
    namespace = synthetic_namespace()
    server = isolated_server(namespace)
    expected = preview(server)["loaded_comment_runtime"]
    namespace["PREVIEW_MODE"] = mode
    result = preview(server)
    assert result["error"] == error
    assert result["canvas_writes"] == 0
    assert result["loaded_comment_runtime"] == expected
    assert "synthetic-private-payload" not in json.dumps(result)
    assert "operation_id" not in result
    assert "confirmation_token" not in result


@pytest.mark.parametrize("mode", ["success", "hold", "unexpected"])
def test_missing_diagnostic_binding_does_not_block_existing_tool(mode):
    namespace = synthetic_namespace()
    del namespace["_observation_holds"]
    namespace["PREVIEW_MODE"] = mode
    server = isolated_server(namespace)
    result = preview(server)
    assert result["canvas_writes"] == 0
    if mode == "success":
        assert result["ready_for_confirmation"] is True
    else:
        assert "error" in result
    metadata = result["loaded_comment_runtime"]
    assert metadata["status"] == "UNAVAILABLE"
    assert metadata["function_sha256"] == {}
    assert metadata["coverage"] == {"expected_functions": 4, "captured_functions": 0}


def test_callable_wrapper_is_nonfatal_and_does_not_claim_identity():
    namespace = synthetic_namespace()
    original = namespace["Publisher"].prepare_comment

    class CallableWrapper:
        async def __call__(self, *args, **kwargs):
            return await original(*args, **kwargs)

    namespace["Publisher"].prepare_comment = CallableWrapper()
    metadata = load_helper().capture_comment_runtime(namespace["Publisher"]).as_dict()
    assert metadata["status"] == "UNAVAILABLE"
    assert metadata["function_sha256"] == {}
    assert namespace["EVENTS"] == []


def test_fingerprint_follows_bound_parser_globals_not_same_name_module(monkeypatch):
    helper = load_helper()
    publish = synthetic_namespace()
    actual_protocol = synthetic_namespace(SYNTHETIC_SOURCE.replace("old-excusal-policy", "actual-bound-policy"))
    decoy_protocol = synthetic_namespace(SYNTHETIC_SOURCE.replace("old-excusal-policy", "decoy-module-policy"))
    publish["parse_exact_observation"] = actual_protocol["parse_exact_observation"]
    actual_protocol["parse_exact_observation"].__module__ = "synthetic_decoy_protocol"
    monkeypatch.setitem(sys.modules, "synthetic_decoy_protocol", SimpleNamespace(**decoy_protocol))
    metadata = helper.capture_comment_runtime(publish["Publisher"]).as_dict()
    expected = helper.capture_comment_runtime(actual_protocol["Publisher"]).as_dict()
    decoy = helper.capture_comment_runtime(decoy_protocol["Publisher"]).as_dict()
    assert metadata["function_sha256"]["protocol._observation_holds"] == (
        expected["function_sha256"]["protocol._observation_holds"]
    )
    assert metadata["function_sha256"]["protocol._observation_holds"] != (
        decoy["function_sha256"]["protocol._observation_holds"]
    )
    assert publish["EVENTS"] == actual_protocol["EVENTS"] == decoy_protocol["EVENTS"] == []


def test_existing_tool_registry_is_unchanged():
    server = isolated_server(synthetic_namespace())
    assert set(server.tools) == {
        "get_canvas_gradebook", "preview_gradebook_changes",
        "prepare_gradebook_push", "get_gradebook_push_status",
        "reconcile_gradebook_push", "prepare_gradebook_comment_push",
        "reconcile_gradebook_comment_push",
        "prepare_gradebook_score_batch", "prepare_gradebook_comment_batch",
        "get_gradebook_batch_status", "revoke_gradebook_batch",
    }
