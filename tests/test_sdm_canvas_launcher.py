"""Credential handling tests; no Keychain or network access."""

import importlib.util
import json
import os
from pathlib import Path
from unittest.mock import Mock

import pytest

spec = importlib.util.spec_from_file_location(
    "sdm_launcher", Path(__file__).parents[1] / "scripts" / "sdm_canvas_launcher.py"
)
launcher = importlib.util.module_from_spec(spec)
spec.loader.exec_module(launcher)


@pytest.mark.parametrize(
    "url",
    [
        "https://school.example",
        "https://school.example/",
        "https://school.example/api/v1/",
    ],
)
def test_origin_normalization(url):
    assert launcher.canvas_origin(url) == "https://school.example"


@pytest.mark.parametrize(
    "url",
    [
        "http://school.example",
        "https://user:token@school.example",
        "https://school.example/courses/1",
        "https://school.example?token=x",
        "https://school.example/#fragment",
        "https://school.example:bad",
    ],
)
def test_invalid_origin_rejected(url):
    with pytest.raises(ValueError):
        launcher.canvas_origin(url)


def test_secret_only_saved_in_keychain(tmp_path, monkeypatch):
    backend = Mock()
    config = tmp_path / "settings" / "connection.json"
    monkeypatch.setattr(launcher, "CONFIG", config)
    monkeypatch.setattr(launcher, "keychain", lambda: backend)
    launcher.save_connection("https://school.example", "dummy-secret")
    backend.set_password.assert_called_once_with(
        launcher.SERVICE, "https://school.example", "dummy-secret"
    )
    assert json.loads(config.read_text()) == {"canvas_origin": "https://school.example"}
    assert "dummy-secret" not in config.read_text()
    assert config.stat().st_mode & 0o777 == 0o600


def test_keychain_failure_does_not_save_config(tmp_path, monkeypatch):
    backend = Mock()
    backend.set_password.side_effect = RuntimeError("denied")
    config = tmp_path / "connection.json"
    monkeypatch.setattr(launcher, "CONFIG", config)
    monkeypatch.setattr(launcher, "keychain", lambda: backend)
    with pytest.raises(RuntimeError):
        launcher.save_connection("https://school.example", "dummy-secret")
    assert not config.exists()


def test_environment_overrides_ambient_privileged_settings(monkeypatch):
    monkeypatch.setenv("EXECUTE_TYPESCRIPT_ENABLED", "true")
    monkeypatch.setenv("CANVAS_API_TOKEN", "wrong-token")
    monkeypatch.setenv("CANVAS_API_URL", "https://wrong.example")
    environment = launcher.launch_environment("https://school.example", "dummy-secret")
    assert environment["CANVAS_API_TOKEN"] == "dummy-secret"
    assert environment["CANVAS_API_URL"] == "https://school.example/api/v1"
    assert environment["EXECUTE_TYPESCRIPT_ENABLED"] == "false"
    assert environment["STUDENT_WRITE_TOOLS"] == ""
    assert environment["PYTHON_DOTENV_DISABLED"] == "1"
    assert os.environ["CANVAS_API_TOKEN"] == "wrong-token"


def test_keychain_error_is_redacted(monkeypatch, capsys):
    backend = Mock()
    backend.get_password.side_effect = RuntimeError("dummy-sensitive-error")
    monkeypatch.setattr(launcher, "read_connection", lambda: "https://school.example")
    monkeypatch.setattr(launcher, "keychain", lambda: backend)
    monkeypatch.setattr("sys.argv", ["launcher", "--check"])
    assert launcher.main() == 1
    captured = capsys.readouterr()
    assert "dummy-sensitive-error" not in captured.err
    assert not captured.out


def test_authentication_uses_one_get_without_redirects(monkeypatch):
    response = Mock(status_code=200)
    response.json.return_value = {"id": 42, "name": "not printed"}
    request = Mock(return_value=response)
    monkeypatch.setattr(launcher.httpx, "get", request)
    launcher.verify_credentials("https://school.example", "dummy-secret")
    request.assert_called_once_with(
        "https://school.example/api/v1/users/self/profile",
        headers={
            "Authorization": "Bearer dummy-secret",
            "User-Agent": "sdm-canvas-authoring/1.0",
        },
        timeout=15,
        follow_redirects=False,
    )


@pytest.mark.parametrize("status", [401, 403, 302, 500])
def test_authentication_failure_does_not_expose_response(monkeypatch, status):
    response = Mock(status_code=status, text="dummy-sensitive-response")
    request = Mock(return_value=response)
    monkeypatch.setattr(launcher.httpx, "get", request)
    with pytest.raises(launcher.ConnectionCheckError) as error:
        launcher.verify_credentials("https://school.example", "dummy-secret")
    assert str(status) in str(error.value)
    assert "dummy-sensitive-response" not in str(error.value)
    assert "dummy-secret" not in str(error.value)
    request.assert_called_once()


@pytest.mark.parametrize("profile", [{}, [], {"unexpected": True}])
def test_non_canvas_response_is_rejected(monkeypatch, profile):
    response = Mock(status_code=200)
    response.json.return_value = profile
    monkeypatch.setattr(launcher.httpx, "get", Mock(return_value=response))
    with pytest.raises(launcher.ConnectionCheckError):
        launcher.verify_credentials("https://school.example", "dummy-secret")


def test_setup_retries_blank_website_and_verifies_before_saving(monkeypatch, capsys):
    monkeypatch.setattr(launcher.sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(
        launcher, "read_connection", Mock(side_effect=FileNotFoundError)
    )
    answers = iter(["", "https://school.example"])
    monkeypatch.setattr("builtins.input", lambda _: next(answers))
    monkeypatch.setattr(launcher.getpass, "getpass", lambda _: "dummy-secret")
    operations = Mock()
    monkeypatch.setattr(launcher, "verify_credentials", operations.verify)
    monkeypatch.setattr(launcher, "save_connection", operations.save)
    assert launcher.setup_connection() == 0
    assert [call[0] for call in operations.mock_calls] == ["verify", "save"]
    assert "dummy-secret" not in capsys.readouterr().out


def test_rejected_replacement_preserves_existing_credential(monkeypatch, capsys):
    monkeypatch.setattr(launcher.sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(launcher, "read_connection", lambda: "https://school.example")
    monkeypatch.setattr("builtins.input", lambda _: "")
    monkeypatch.setattr(launcher.getpass, "getpass", lambda _: "dummy-secret")
    verify = Mock(
        side_effect=launcher.ConnectionCheckError(
            "Canvas rejected the token (HTTP 401)."
        )
    )
    save = Mock()
    monkeypatch.setattr(launcher, "verify_credentials", verify)
    monkeypatch.setattr(launcher, "save_connection", save)
    assert launcher.setup_connection() == 1
    verify.assert_called_once_with("https://school.example", "dummy-secret")
    save.assert_not_called()
    result = capsys.readouterr()
    assert "not saved" in result.err
    assert "dummy-secret" not in result.err + result.out


def test_network_failure_is_redacted(monkeypatch):
    request = Mock(side_effect=launcher.httpx.ConnectError("dummy-sensitive-error"))
    monkeypatch.setattr(launcher.httpx, "get", request)
    with pytest.raises(launcher.ConnectionCheckError) as error:
        launcher.verify_credentials("https://school.example", "dummy-secret")
    assert "dummy-sensitive-error" not in str(error.value)


def test_invalid_token_does_not_make_a_request(monkeypatch):
    request = Mock()
    monkeypatch.setattr(launcher.httpx, "get", request)
    with pytest.raises(launcher.ConnectionCheckError):
        launcher.verify_credentials("https://school.example", "")
    request.assert_not_called()
