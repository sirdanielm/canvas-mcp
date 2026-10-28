"""Portable TOML edits in synthetic files; no launcher, service or real config."""

import importlib.util
import json
import re
import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("line_ending_installer", ROOT / "scripts/install_gradebook_connection.py")
assert SPEC and SPEC.loader
installer = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(installer)


def config(tmp_path: Path, newline: str, tools: list[str]) -> tuple[Path, bytes, bytes, bytes]:
    template = (ROOT / "config/sdm-gradebook.toml.example").read_text(encoding="utf-8")
    entry = re.sub(r"(?m)^enabled_tools = .*", "enabled_tools = " + json.dumps(tools), template)
    prefix = 'model = "unchanged"\n[mcp_servers.existing]\ncommand = "retain"\n'
    suffix = '\n[features]\nunchanged = true\n'
    original = (prefix + entry + suffix).replace("\n", newline).encode("utf-8")
    path = tmp_path / "synthetic-config.toml"
    path.write_bytes(original)
    return path, original, prefix.replace("\n", newline).encode("utf-8"), suffix.replace("\n", newline).encode("utf-8")


@pytest.mark.parametrize("newline", ["\n", "\r\n"], ids=["LF", "CRLF"])
@pytest.mark.parametrize("operation", ["upgrade", "add_get_controls"])
def test_recognized_config_with_either_line_ending_preserves_unrelated_bytes(tmp_path: Path, newline: str, operation: str) -> None:
    tools = ["get_canvas_gradebook", "preview_gradebook_changes"] if operation == "upgrade" else installer.LEGACY_DEFAULT_TOOLS
    path, original, prefix, suffix = config(tmp_path, newline, tools)
    before = tomllib.loads(original.decode("utf-8"))
    if operation == "upgrade":
        installer.install(path, upgrade=True)
    else:
        installer.add_get_controls(path)
    result = path.read_bytes()
    assert result.startswith(prefix) and result.endswith(suffix)
    if newline == "\r\n":
        assert b"\n" not in result.replace(b"\r\n", b"")
    after = tomllib.loads(result.decode("utf-8"))
    old_entry = before["mcp_servers"].pop("canvas-gradebook")
    new_entry = after["mcp_servers"].pop("canvas-gradebook")
    assert after == before
    if operation == "upgrade":
        desired = tomllib.loads((ROOT / "config/sdm-gradebook.toml.example").read_text(encoding="utf-8"))
        assert new_entry == desired["mcp_servers"]["canvas-gradebook"]
    else:
        assert new_entry["enabled_tools"] == old_entry["enabled_tools"] + installer.GET_CONTROLS
        new_entry["enabled_tools"] = old_entry["enabled_tools"]
        assert new_entry == old_entry
    backups = list(tmp_path.glob("config.before-*.toml"))
    assert len(backups) == 1 and backups[0].read_bytes() == original
    assert "confirm_gradebook_push" not in tomllib.loads(result.decode("utf-8"))["mcp_servers"]["canvas-gradebook"]["enabled_tools"]
