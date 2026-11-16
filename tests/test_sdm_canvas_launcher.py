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
    assert json.loads(config.read_text(encoding="utf-8")) == {"canvas_origin": "https://school.example"}
    assert "dummy-secret" not in config.read_text(encoding="utf-8")
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


class _CapturedExec(BaseException):
    pass


@pytest.mark.parametrize('raw,expected', [
    (None, set()), ('', set()), ('none', set()), ('all', set()),
    ('create_module', set()), ('create_module,add_module_item', {'create_module', 'add_module_item'}),
    ('none,create_module', 'invalid'), ('create_modul', 'invalid'),
    ('create_module,add_module_item,update_module', set()),
])
def test_draft_launcher_to_actual_startup_preserves_operator_policy(monkeypatch, raw, expected):
    import asyncio
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    from fastmcp import FastMCP

    import canvas_mcp.core.audit as audit
    import canvas_mcp.server as server
    from canvas_mcp.core.tool_policy import TOOL_EFFECTS, Effect

    if raw is None:
        monkeypatch.delenv('ALLOWED_WRITE_TOOLS', raising=False)
    else:
        monkeypatch.setenv('ALLOWED_WRITE_TOOLS', raw)
    monkeypatch.setattr('sys.argv', ['launcher', '--draft-modules-only'])
    monkeypatch.setattr(launcher, 'read_connection', lambda: 'https://school.example')
    monkeypatch.setattr(launcher, 'keychain', lambda: SimpleNamespace(get_password=lambda *_: 'synthetic-token'))
    monkeypatch.setattr(launcher.os, 'chdir', lambda *_: None)
    captured = {}

    def fake_exec(executable, argv, environment):
        captured.update(argv=argv, env=environment)
        raise _CapturedExec()

    monkeypatch.setattr(launcher.os, 'execve', fake_exec)
    with pytest.raises(_CapturedExec):
        launcher.main()
    assert captured['argv'][-1] == '--draft-modules-only'
    assert captured['env'].get('ALLOWED_WRITE_TOOLS') == raw
    config = SimpleNamespace(canvas_api_url='https://school.example/api/v1', institution_name='',
                             canvas_role='educator', allowed_write_tools=captured['env'].get('ALLOWED_WRITE_TOOLS'), mcp_server_name='mock')
    monkeypatch.setattr('sys.argv', captured['argv'])
    monkeypatch.setattr(server, 'get_config', lambda: config)
    monkeypatch.setattr(server, 'validate_config', lambda: True)
    fake_verify = AsyncMock(return_value=(True, 'synthetic'))
    monkeypatch.setattr(server, '_validate_token', fake_verify)
    monkeypatch.setattr(audit, 'init_audit_logging', lambda: None)
    observed = set()

    def capture_run(mcp):
        async def names():
            return {t.name for t in await mcp.list_tools(run_middleware=False)}
        observed.update(asyncio.run(names()))

    monkeypatch.setattr(FastMCP, 'run', capture_run)
    if expected == 'invalid':
        with pytest.raises(SystemExit):
            server.main()
        fake_verify.assert_not_awaited()
    else:
        server.main()
        assert {n for n in observed if TOOL_EFFECTS[n] != Effect.READ} == expected
        assert {'list_modules', 'list_module_items'} <= observed


@pytest.mark.parametrize('flag', ['--setup', '--check', '--verify'])
def test_draft_launcher_does_not_combine_with_setup(monkeypatch, flag):
    monkeypatch.setattr('sys.argv', ['launcher', flag, '--draft-modules-only'])
    with pytest.raises(SystemExit):
        launcher.main()


def test_normal_launcher_keeps_normal_arguments_and_operator_policy(monkeypatch):
    from types import SimpleNamespace

    monkeypatch.setattr('sys.argv', ['launcher'])
    monkeypatch.setenv('ALLOWED_WRITE_TOOLS', 'none')
    monkeypatch.setattr(launcher, 'read_connection', lambda: 'https://school.example')
    monkeypatch.setattr(launcher, 'keychain', lambda: SimpleNamespace(get_password=lambda *_: 'synthetic-token'))
    monkeypatch.setattr(launcher.os, 'chdir', lambda *_: None)
    captured = {}

    def fake_exec(executable, argv, environment):
        captured.update(argv=argv, env=environment)
        raise _CapturedExec()

    monkeypatch.setattr(launcher.os, 'execve', fake_exec)
    with pytest.raises(_CapturedExec):
        launcher.main()
    assert captured['argv'][1:] == ['--role', 'educator']
    assert captured['env']['ALLOWED_WRITE_TOOLS'] == 'none'
