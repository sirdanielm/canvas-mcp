"""GET control allowlist changes preserve every existing action gate."""

import importlib.util
import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]
spec = importlib.util.spec_from_file_location(
    "get_controls_installer", ROOT / "scripts/install_gradebook_connection.py"
)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def config(tmp_path, push=False):
    text = (ROOT / "config/sdm-gradebook.toml.example").read_text(encoding="utf-8")
    import json
    import re

    text = re.sub(
        r"(?m)^enabled_tools = .*",
        "enabled_tools = " + json.dumps(module.LEGACY_DEFAULT_TOOLS),
        text,
    )
    if push:
        text = text.replace(
            'sdm_gradebook_launcher.py"]',
            'sdm_gradebook_launcher.py", "--enable-push"]',
        )
    text += '\n[mcp_servers.other]\ncommand = "other"\nenabled_tools = ["do_other"]\n'
    p = tmp_path / "config.toml"
    p.write_text(text, encoding="utf-8")
    return p


@pytest.mark.parametrize("push", [True, False])
def test_add_only_control_names_preserves_every_other_setting(tmp_path, push):
    p = config(tmp_path, push)
    before = tomllib.loads(p.read_text(encoding="utf-8"))
    module.add_get_controls(p)
    after = tomllib.loads(p.read_text(encoding="utf-8"))
    old = before["mcp_servers"]["canvas-gradebook"]["enabled_tools"]
    assert (
        after["mcp_servers"]["canvas-gradebook"]["enabled_tools"]
        == old + module.GET_CONTROLS
    )
    after["mcp_servers"]["canvas-gradebook"]["enabled_tools"] = old
    assert after == before
    original = p.read_bytes()
    module.add_get_controls(p)
    assert p.read_bytes() == original
    backups = list(tmp_path.glob("config.before-get-controls-*.toml"))
    assert len(backups) == 1 and backups[0].stat().st_mode & 0o777 == 0o600


@pytest.mark.parametrize(
    "flags",
    [
        ["--enable-comments"],
        ["--enable-push", "--enable-comments"],
        ["--enable-comments", "--enable-push"],
    ],
)
def test_add_get_controls_preserves_existing_independent_comment_gate(tmp_path, flags):
    import json

    p = config(tmp_path)
    text = p.read_text(encoding="utf-8").replace(
        'sdm_gradebook_launcher.py"]',
        'sdm_gradebook_launcher.py", ' + ", ".join(map(json.dumps, flags)) + "]",
    )
    p.write_text(text, encoding="utf-8")
    before = tomllib.loads(p.read_text(encoding="utf-8"))
    module.add_get_controls(p)
    after = tomllib.loads(p.read_text(encoding="utf-8"))
    enabled = before["mcp_servers"]["canvas-gradebook"]["enabled_tools"]
    assert after["mcp_servers"]["canvas-gradebook"]["enabled_tools"] == (
        enabled + module.GET_CONTROLS
    )
    after["mcp_servers"]["canvas-gradebook"]["enabled_tools"] = enabled
    assert after == before


def test_repeated_action_flags_are_held_without_config_changes(tmp_path):
    p = config(tmp_path, push=True)
    p.write_text(
        p.read_text(encoding="utf-8").replace(
            '"--enable-push"]', '"--enable-push", "--enable-push"]'
        ), encoding="utf-8",
    )
    original = p.read_bytes()
    with pytest.raises(ValueError):
        module.add_get_controls(p)
    assert p.read_bytes() == original
    assert not list(tmp_path.glob("config.before-get-controls-*.toml"))


@pytest.mark.parametrize("change", ["command", "cwd", "args", "duplicates"])
def test_unrecognized_binding_holds_without_replacement(tmp_path, change):
    p = config(tmp_path)
    text = p.read_text(encoding="utf-8")
    if change == "command":
        text = text.replace(".venv/bin/python", "other/python")
    elif change == "cwd":
        text = text.replace('cwd = "', 'cwd = "/wrong')
    elif change == "args":
        text = text.replace(
            'sdm_gradebook_launcher.py"]', 'sdm_gradebook_launcher.py", "--arbitrary"]'
        )
    else:
        text = text.replace(
            'enabled_tools = ["get_canvas_gradebook",',
            'enabled_tools = ["get_canvas_gradebook", "get_canvas_gradebook",',
            1,
        )
    p.write_text(text, encoding="utf-8")
    old = p.read_bytes()
    with pytest.raises(ValueError):
        module.add_get_controls(p)
    assert p.read_bytes() == old


def test_symlink_is_refused(tmp_path):
    p = config(tmp_path)
    link = tmp_path / "link"
    link.symlink_to(p)
    with pytest.raises(ValueError):
        module.add_get_controls(link)


def test_old_read_only_default_upgrades_to_protected_get_without_push(tmp_path):
    p = config(tmp_path)
    with pytest.raises(ValueError):
        module.install(p)
    module.install(p, upgrade=True)
    entry = tomllib.loads(p.read_text(encoding="utf-8"))["mcp_servers"]["canvas-gradebook"]
    assert set(module.GET_CONTROLS) <= set(entry["enabled_tools"])
    assert "prepare_gradebook_refresh" not in entry["enabled_tools"]
    assert "confirm_gradebook_push" not in entry["enabled_tools"]
    assert "--enable-push" not in entry["args"]


def test_default_upgrade_refuses_customized_push_profile(tmp_path):
    p = config(tmp_path, push=True)
    before = p.read_bytes()
    with pytest.raises(ValueError):
        module.install(p, upgrade=True)
    assert p.read_bytes() == before


def test_known_previous_timeout_upgrades_without_changing_action_gates(tmp_path):
    p = config(tmp_path)
    module.install(p, upgrade=True)
    old = p.read_text(encoding="utf-8").replace("tool_timeout_sec = 300", "tool_timeout_sec = 180")
    p.write_text(old, encoding="utf-8")
    before = tomllib.loads(p.read_text(encoding="utf-8"))
    module.install(p, upgrade=True)
    after = tomllib.loads(p.read_text(encoding="utf-8"))
    assert after["mcp_servers"]["canvas-gradebook"]["tool_timeout_sec"] == 300
    after["mcp_servers"]["canvas-gradebook"]["tool_timeout_sec"] = 180
    assert after == before


@pytest.mark.parametrize(
    "flags",
    [
        [],
        ["--enable-push"],
        ["--enable-comments"],
        ["--enable-push", "--enable-comments"],
        ["--enable-comments", "--comment-approval-seconds", "1800"],
    ],
)
def test_batch_controls_preserve_channels_and_unrelated_configuration(tmp_path, flags):
    import json

    p = config(tmp_path)
    text = p.read_text(encoding="utf-8")
    if flags:
        text = text.replace(
            'sdm_gradebook_launcher.py"]',
            'sdm_gradebook_launcher.py", ' + ", ".join(map(json.dumps, flags)) + "]",
        )
    p.write_text(text, encoding="utf-8")
    before = tomllib.loads(p.read_text(encoding="utf-8"))
    module.add_batch_controls(p)
    after = tomllib.loads(p.read_text(encoding="utf-8"))
    tools = after["mcp_servers"]["canvas-gradebook"]["enabled_tools"]
    assert set(module.BATCH_REVIEW_TOOLS) <= set(tools)
    enabled = "--enable-push" in flags or "--enable-comments" in flags
    assert all((t in tools) is enabled for t in module.BATCH_WRITE_TOOLS)
    after["mcp_servers"]["canvas-gradebook"]["enabled_tools"] = before["mcp_servers"][
        "canvas-gradebook"
    ]["enabled_tools"]
    assert after == before
    once = p.read_bytes()
    module.add_batch_controls(p)
    assert p.read_bytes() == once
