"""Fictional, offline connection proposals: no live config or runtime access."""

from __future__ import annotations

import copy
import importlib.util
import io
import json
import sys
import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "comment_connection_staging", ROOT / "scripts/stage_comment_connection.py"
)
assert SPEC and SPEC.loader
staging = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(staging)

SOURCE = "/fictional/canvas-owner"
STATE = "/fictional/private/durable-gradebook-state"
READ_TOOLS = [
    "get_canvas_gradebook",
    "preview_gradebook_changes",
    "get_gradebook_push_status",
]


@pytest.fixture
def metadata() -> dict:
    observed = {
        "source_root": SOURCE,
        "source_revision": "a" * 40,
        "launcher_path": SOURCE + "/scripts/mcp_main_read_only.py",
        "launcher_sha256": "b" * 64,
        "runtime_executable": SOURCE + "/.venv/bin/python",
        "runtime_sha256": "c" * 64,
        "runtime_python_version": "3.12.14",
        "state_dir": STATE,
        "owner_policy_id": None,
        "owner_adapter": None,
        "owner_adapter_sha256": None,
    }
    proposed = {
        **observed,
        "launcher_path": SOURCE + "/scripts/sdm_gradebook_launcher.py",
        "launcher_sha256": "d" * 64,
        "owner_policy_id": "fictional-policy-v1",
        "owner_adapter": "/fictional/private/owner-policy.py",
        "owner_adapter_sha256": "e" * 64,
    }
    return {
        "schema_version": 1,
        "connection_name": "canvas-gradebook",
        "observed": observed,
        "proposed": proposed,
    }


def snapshot(metadata: dict, *, extra_args: list[str] | None = None) -> bytes:
    observed = metadata["observed"]
    if extra_args is None:
        extra_args = ["--state-dir", observed["state_dir"]]
    entry = {
        "command": observed["runtime_executable"],
        "args": [observed["launcher_path"], *extra_args],
        "cwd": observed["source_root"],
        "enabled": True,
        "required": False,
        "startup_timeout_sec": 20,
        "tool_timeout_sec": 300,
        "enabled_tools": READ_TOOLS,
    }
    # Comments, CRLF and an unrelated table must survive because there is no
    # replacement/config serializer or mutation path in this staging helper.
    return (
        '# keep this exact comment\r\nmodel = "fictional-model"\r\n'
        "[mcp_servers.canvas-gradebook]\r\n"
        + "\r\n".join(f"{key} = {json.dumps(value)}" for key, value in entry.items())
        + '\r\n[mcp_servers.unrelated]\r\ncommand = "/fictional/unrelated"\r\n'
    ).encode()


def test_default_is_disabled_comment_review_and_preserves_inputs(
    metadata: dict,
) -> None:
    original = snapshot(metadata)
    before = copy.deepcopy(metadata)
    result = staging.stage_comment_connection(original, metadata)
    assert original == snapshot(metadata)
    assert metadata == before
    proposed = result["proposed_entry"]
    assert proposed["enabled"] is False
    assert proposed["command"] == SOURCE + "/.venv/bin/python"
    assert proposed["cwd"] == SOURCE
    assert proposed["args"] == [
        SOURCE + "/scripts/sdm_gradebook_launcher.py",
        "--state-dir",
        STATE,
        "--enable-comments",
        "--owner-adapter",
        "/fictional/private/owner-policy.py",
        "--owner-adapter-sha256",
        "e" * 64,
    ]
    assert proposed["enabled_tools"] == [
        *READ_TOOLS,
        "prepare_gradebook_comment_push",
        "reconcile_gradebook_comment_push",
    ]
    assert "confirm_gradebook_comment_push" not in proposed["enabled_tools"]
    assert "--enable-push" not in proposed["args"]
    assert result["live_enabled"] is False
    assert result["score_enablement"] is False
    assert result["config_writes"] == result["runtime_starts"] == 0
    assert result["binding_metadata_only"] is True
    assert result["existing_installer_adoption_supported"] is False
    assert tomllib.loads(result["toml_snippet"])["mcp_servers"] == {
        "canvas-gradebook": proposed
    }
    assert "unrelated" not in result["toml_snippet"]


def test_confirm_review_never_activates_connection(metadata: dict) -> None:
    result = staging.stage_comment_connection(
        snapshot(metadata), metadata, include_confirm_for_review=True
    )
    assert result["proposed_entry"]["enabled"] is False
    assert (
        result["proposed_entry"]["enabled_tools"][-1]
        == "confirm_gradebook_comment_push"
    )
    assert result["live_enabled"] is False
    assert "--enable-push" not in result["toml_snippet"]


@pytest.mark.parametrize(
    "flags",
    [
        ["--enable-push"],
        ["--enable-comments"],
        ["--call", "confirm_gradebook_comment_push"],
        ["--owner-adapter", "/fictional/unknown.py"],
        ["--state-dir", "/fictional/other-state"],
        ["--unknown"],
        ["--read-only", "--read-only"],
    ],
)
def test_refuses_writer_or_unknown_current_arguments(
    metadata: dict, flags: list[str]
) -> None:
    with pytest.raises(ValueError, match="arguments"):
        staging.stage_comment_connection(snapshot(metadata, extra_args=flags), metadata)


@pytest.mark.parametrize(
    "flags", [["--state-dir", STATE], ["--read-only", "--state-dir", STATE]]
)
def test_accepts_explicit_current_state_binding(
    metadata: dict, flags: list[str]
) -> None:
    assert (
        staging.stage_comment_connection(
            snapshot(metadata, extra_args=flags), metadata
        )["live_enabled"]
        is False
    )


@pytest.mark.parametrize(
    ("launcher", "flags"),
    [
        ("mcp_main_read_only.py", []),
        ("mcp_main_read_only.py", ["--read-only"]),
        ("sdm_gradebook_launcher.py", ["--read-only"]),
    ],
)
def test_agreeing_metadata_cannot_invent_an_unbound_state_directory(
    metadata: dict, launcher: str, flags: list[str]
) -> None:
    metadata["observed"]["launcher_path"] = SOURCE + "/scripts/" + launcher
    # Both metadata objects agree, but the saved args do not establish STATE.
    assert metadata["observed"]["state_dir"] == metadata["proposed"]["state_dir"]
    with pytest.raises(ValueError, match="state"):
        staging.stage_comment_connection(snapshot(metadata, extra_args=flags), metadata)


def test_only_maintained_launcher_exact_state_default_is_recognized(
    metadata: dict,
) -> None:
    metadata["observed"]["launcher_path"] = (
        SOURCE + "/scripts/sdm_gradebook_launcher.py"
    )
    metadata["observed"]["state_dir"] = SOURCE + "/local_gradebooks"
    metadata["proposed"]["state_dir"] = SOURCE + "/local_gradebooks"
    result = staging.stage_comment_connection(
        snapshot(metadata, extra_args=["--read-only"]), metadata
    )
    assert result["proposed_entry"]["args"][1:3] == [
        "--state-dir",
        SOURCE + "/local_gradebooks",
    ]
    assert result["live_enabled"] is False


def test_unknown_wrapper_default_is_held_even_at_maintained_default_path(
    metadata: dict,
) -> None:
    metadata["observed"]["state_dir"] = SOURCE + "/local_gradebooks"
    metadata["proposed"]["state_dir"] = SOURCE + "/local_gradebooks"
    with pytest.raises(ValueError, match="state"):
        staging.stage_comment_connection(snapshot(metadata, extra_args=[]), metadata)


@pytest.mark.parametrize(
    ("field", "replacement"),
    [
        ("source_root", "/fictional/different-root"),
        ("source_revision", "f" * 40),
        ("runtime_executable", "/fictional/other-runtime/python"),
        ("runtime_sha256", "f" * 64),
        ("runtime_python_version", "3.13.1"),
        ("state_dir", "/fictional/other-state"),
        (
            "launcher_path",
            "/fictional/different-root/scripts/sdm_gradebook_launcher.py",
        ),
    ],
)
def test_refuses_different_roots_runtime_or_durable_state(
    metadata: dict, field: str, replacement: str
) -> None:
    original = snapshot(metadata)
    metadata["proposed"][field] = replacement
    with pytest.raises(ValueError):
        staging.stage_comment_connection(original, metadata)


@pytest.mark.parametrize("field", sorted(staging._BINDING_FIELDS))
def test_every_source_owner_runtime_state_pin_is_explicit(
    metadata: dict, field: str
) -> None:
    original = snapshot(metadata)
    del metadata["proposed"][field]
    with pytest.raises(ValueError, match="metadata fields"):
        staging.stage_comment_connection(original, metadata)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("runtime_python_version", "3.10.9"),
        ("runtime_python_version", "3.12"),
        ("owner_adapter_sha256", "unverified"),
        ("owner_adapter", "~/owner.py"),
        ("state_dir", "/fictional/private/../other"),
        ("source_revision", "main"),
        ("owner_policy_id", None),
    ],
)
def test_refuses_incomplete_or_noncanonical_binding(
    metadata: dict, field: str, value: object
) -> None:
    original = snapshot(metadata)
    metadata["proposed"][field] = value
    with pytest.raises(ValueError):
        staging.stage_comment_connection(original, metadata)


def test_refuses_score_tool_exposure_and_custom_environment(metadata: dict) -> None:
    original = snapshot(metadata)
    score_tools = original.replace(
        b'"get_gradebook_push_status"', b'"confirm_gradebook_push"'
    )
    with pytest.raises(ValueError, match="read-only"):
        staging.stage_comment_connection(score_tools, metadata)
    custom = original.replace(
        b"enabled = true", b'enabled = true\r\nenv = { SECRET = "do-not-output" }'
    )
    with pytest.raises(ValueError, match="shape"):
        staging.stage_comment_connection(custom, metadata)


@pytest.mark.parametrize(
    "contents",
    [
        b'mcp_servers = "wrong-shape"',
        b"[mcp_servers.canvas-gradebook]\nenabled_tools = [{ malformed = true }]",
        b"invalid = ",
        b"\xff",
    ],
)
def test_malformed_snapshots_are_refused_without_echoing_values(
    metadata: dict, contents: bytes
) -> None:
    with pytest.raises(ValueError):
        staging.stage_comment_connection(contents, metadata)


def test_publisher_current_profile_requires_explicit_read_only(metadata: dict) -> None:
    metadata["observed"]["launcher_path"] = (
        SOURCE + "/scripts/sdm_gradebook_launcher.py"
    )
    with pytest.raises(ValueError, match="retain --read-only"):
        staging.stage_comment_connection(snapshot(metadata), metadata)
    result = staging.stage_comment_connection(
        snapshot(metadata, extra_args=["--read-only", "--state-dir", STATE]), metadata
    )
    assert result["live_enabled"] is False


def test_staging_does_not_touch_environment_files_or_processes(
    metadata: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    import builtins
    import os
    import subprocess

    original = snapshot(metadata)

    def forbidden(*args: object, **kwargs: object) -> None:
        raise AssertionError("offline staging must not use ambient I/O")

    class NoEnvironment(dict):
        def __getitem__(self, key: object) -> object:
            forbidden()

        def get(self, *args: object) -> object:
            forbidden()

    monkeypatch.setattr(builtins, "open", forbidden)
    monkeypatch.setattr(Path, "read_bytes", forbidden)
    monkeypatch.setattr(Path, "write_bytes", forbidden)
    monkeypatch.setattr(os, "replace", forbidden)
    monkeypatch.setattr(os, "environ", NoEnvironment())
    monkeypatch.setattr(subprocess, "Popen", forbidden)
    result = staging.stage_comment_connection(original, metadata)
    assert result["status"] == "OFFLINE_OWNER_ADOPTION_REQUIRED"


def test_cli_accepts_stdin_only_and_redacts_bad_input(
    metadata: dict, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(sys, "argv", ["stage_comment_connection.py"])
    monkeypatch.setattr(
        sys,
        "stdin",
        io.StringIO(
            json.dumps(
                {
                    "config_snapshot_toml": snapshot(metadata).decode(),
                    "metadata": metadata,
                }
            )
        ),
    )
    assert staging.main() == 0
    assert json.loads(capsys.readouterr().out)["live_enabled"] is False
    monkeypatch.setattr(sys, "stdin", io.StringIO('{"SECRET": "never-echo-this"}'))
    assert staging.main() == 2
    captured = capsys.readouterr()
    assert "never-echo-this" not in captured.out + captured.err


def test_cli_has_no_install_config_path_or_enable_flag(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for flag in (
        "--config",
        "--install",
        "--enable-push",
        "--enable-comments",
        "--adopt",
    ):
        monkeypatch.setattr(sys, "argv", ["stage_comment_connection.py", flag])
        with pytest.raises(SystemExit) as exc:
            staging.main()
        assert exc.value.code == 2
