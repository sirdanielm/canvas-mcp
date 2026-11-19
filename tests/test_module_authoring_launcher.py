"""Scoped launcher tests; all credentials, filesystem settings and exec are mocked."""

import importlib.util
from pathlib import Path
from unittest.mock import Mock

import pytest

spec = importlib.util.spec_from_file_location(
    "module_authoring_launcher",
    Path(__file__).parents[1] / "scripts" / "sdm_canvas_launcher.py",
)
launcher = importlib.util.module_from_spec(spec)
spec.loader.exec_module(launcher)


class CapturedExec(BaseException):
    """Stop before a child process can be started."""


@pytest.mark.parametrize(
    "raw,enabled,expected",
    [
        (None, False, "none"),
        ("", False, "none"),
        (" ", True, "none"),
        ("none", True, "none"),
        ("all", True, "none"),
        ("none,add_draft_module_item", True, "none"),
        ("create_assignment", True, "none"),
        ("add_draft_module_item,create_assignment", True, "none"),
        ("confirm_module_publication", False, "none"),
        ("add_draft_module_item", False, "add_draft_module_item"),
        ("edit_draft_module_item", False, "edit_draft_module_item"),
        (
            "edit_draft_module_item add_draft_module_item",
            False,
            "add_draft_module_item,edit_draft_module_item",
        ),
        (
            "add_draft_module_item,confirm_module_publication",
            False,
            "add_draft_module_item",
        ),
        ("confirm_module_publication", True, "confirm_module_publication"),
    ],
)
def test_explicit_subset_and_publication_opt_in(raw, enabled, expected):
    assert launcher.module_authoring_write_policy(raw, enabled) == expected


@pytest.mark.parametrize(
    "raw,publication_enabled,expected",
    [
        (None, False, "none"),
        ("none", True, "none"),
        ("all", True, "none"),
        ("add_draft_module_item", False, "add_draft_module_item"),
        (
            "edit_draft_module_item,confirm_module_publication",
            False,
            "edit_draft_module_item",
        ),
        ("confirm_module_publication", True, "confirm_module_publication"),
    ],
)
def test_new_mode_forwards_exact_scope_and_policy(
    monkeypatch, tmp_path, raw, publication_enabled, expected
):
    journal = str(tmp_path / "journal")
    options = [
        "launcher",
        "--module-authoring-only",
        "--module-authoring-courses",
        "123,456",
        "--module-authoring-journal",
        journal,
    ]
    if publication_enabled:
        options.append("--enable-module-publication")
    monkeypatch.setattr(
        launcher.sys,
        "argv",
        options,
    )
    if raw is None:
        monkeypatch.delenv("ALLOWED_WRITE_TOOLS", raising=False)
    else:
        monkeypatch.setenv("ALLOWED_WRITE_TOOLS", raw)
    monkeypatch.setattr(launcher, "read_connection", lambda: "https://school.example")
    backend = Mock()
    backend.get_password.return_value = "synthetic-not-a-credential"
    monkeypatch.setattr(launcher, "keychain", lambda: backend)
    monkeypatch.setattr(launcher.os, "chdir", Mock())
    monkeypatch.setattr(
        launcher.httpx, "get", Mock(side_effect=AssertionError("No network permitted"))
    )
    captured = {}

    def capture(executable, argv, environment):
        captured.update(executable=executable, argv=argv, environment=environment)
        raise CapturedExec()

    monkeypatch.setattr(launcher.os, "execve", capture)
    with pytest.raises(CapturedExec):
        launcher.main()
    assert captured["argv"][1:] == ["--role", "educator", *options[1:]]
    assert captured["environment"]["ALLOWED_WRITE_TOOLS"] == expected
    assert captured["environment"]["EXECUTE_TYPESCRIPT_ENABLED"] == "false"
    assert captured["environment"]["STUDENT_WRITE_TOOLS"] == ""
    assert captured["environment"]["PYTHON_DOTENV_DISABLED"] == "1"
    assert not Path(journal).exists()
    launcher.httpx.get.assert_not_called()


@pytest.mark.parametrize(
    "options",
    [
        ["--module-authoring-only"],
        ["--enable-module-publication"],
        ["--module-authoring-courses", "123"],
        ["--module-authoring-journal", "/private/journal"],
        ["--module-authoring-only", "--module-authoring-courses", "123"],
        ["--module-authoring-only", "--module-authoring-journal", "/private/journal"],
        [
            "--module-authoring-only",
            "--module-authoring-courses",
            "123,123",
            "--module-authoring-journal",
            "/private/journal",
        ],
        [
            "--module-authoring-only",
            "--module-authoring-courses",
            "all",
            "--module-authoring-journal",
            "/private/journal",
        ],
        [
            "--module-authoring-only",
            "--module-authoring-courses",
            "123",
            "--module-authoring-journal",
            "relative-journal",
        ],
        ["--enable-module-publication"],
        ["--module-authoring-courses", "123"],
        ["--module-authoring-journal", "/private/journal"],
        ["--check", "--module-authoring-only"],
        ["--setup", "--module-authoring-only"],
        ["--verify", "--module-authoring-only"],
        ["--draft-modules-only", "--module-authoring-only"],
    ],
)
def test_invalid_scope_stops_before_settings_or_keychain(monkeypatch, options):
    monkeypatch.setattr(launcher.sys, "argv", ["launcher", *options])
    read = Mock(side_effect=AssertionError("No settings access permitted"))
    keychain = Mock(side_effect=AssertionError("No Keychain access permitted"))
    execute = Mock(side_effect=AssertionError("No process launch permitted"))
    monkeypatch.setattr(launcher, "read_connection", read)
    monkeypatch.setattr(launcher, "keychain", keychain)
    monkeypatch.setattr(launcher.os, "execve", execute)
    with pytest.raises(SystemExit) as error:
        launcher.main()
    assert error.value.code == 2
    read.assert_not_called()
    keychain.assert_not_called()
    execute.assert_not_called()
