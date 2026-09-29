"""Offline PKCE/OAuth setup checks; no browser or network is opened."""

import base64
import hashlib
import json
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest

from canvas_mcp.gradebook import google_authorize as auth
from canvas_mcp.gradebook.client import GradebookError


@pytest.fixture
def client_file(tmp_path):
    path = tmp_path / "desktop.json"
    path.write_text(
        json.dumps(
            {
                "installed": {
                    "client_id": "fictional-own-client",
                    "client_secret": "fictional-secret",
                    "auth_uri": auth.AUTH_URL,
                    "token_uri": auth.TOKEN_URL,
                }
            }
        )
    )
    path.chmod(0o600)
    return path


class Receiver:
    instances = []

    def __init__(self, state):
        self.state = state
        self.redirect_uri = "http://127.0.0.1:54321/oauth2/callback"
        self.closed = False
        self.instances.append(self)

    async def wait(self, timeout):
        return "fictional-code"

    def close(self):
        self.closed = True


@pytest.fixture
def receiver(monkeypatch):
    Receiver.instances = []
    monkeypatch.setattr(auth, "CallbackReceiver", Receiver)
    return Receiver


async def test_authorize_pkce_state_narrow_scope_and_private_exclusive_save(
    client_file, receiver
):
    captured = []
    destination = client_file.parent / "authorized.json"

    def browser(url):
        captured.append(parse_qs(urlsplit(url).query))
        return True

    def exchange(request):
        assert request.method == "POST" and str(request.url) == auth.TOKEN_URL
        fields = parse_qs(request.content.decode())
        verifier = fields["code_verifier"][0]
        expected = (
            base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
            .rstrip(b"=")
            .decode()
        )
        assert captured[0]["code_challenge"] == [expected]
        assert captured[0]["code_challenge_method"] == ["S256"]
        assert captured[0]["scope"] == [auth.SCOPE]
        assert captured[0]["include_granted_scopes"] == ["false"]
        assert captured[0]["state"] == [receiver.instances[0].state]
        assert fields["redirect_uri"] == [receiver.instances[0].redirect_uri]
        return httpx.Response(
            200,
            json={
                "scope": auth.SCOPE,
                "refresh_token": "fictional-refresh",
                "access_token": "not-persisted",
            },
        )

    result = await auth.authorize(
        client_file,
        destination,
        browser_open=browser,
        transport=httpx.MockTransport(exchange),
    )
    assert result["state"] == "AUTHORIZED"
    assert destination.stat().st_mode & 0o777 == 0o600
    saved = json.loads(destination.read_text())
    assert saved["tokens"]["gradebook"]["refresh_token"] == "fictional-refresh"
    assert "access_token" not in saved["tokens"]["gradebook"]
    assert "fictional-secret" not in json.dumps(result)
    assert receiver.instances[0].closed


@pytest.mark.parametrize("status", [400, 401, 429, 500, 503])
async def test_code_exchange_never_retries_or_saves_failure(
    client_file, receiver, status
):
    requests = []

    def exchange(request):
        requests.append(request)
        return httpx.Response(status, json={"error": "fictional-secret"})

    destination = client_file.parent / "authorized.json"
    with pytest.raises(GradebookError, match="exchange failed"):
        await auth.authorize(
            client_file,
            destination,
            browser_open=lambda _: True,
            transport=httpx.MockTransport(exchange),
        )
    assert len(requests) == 1 and not destination.exists()
    assert receiver.instances[0].closed


@pytest.mark.parametrize(
    "scope", ["", "https://www.googleapis.com/auth/drive", auth.SCOPE + " extra"]
)
async def test_unexpected_grant_is_not_saved(client_file, receiver, scope):
    destination = client_file.parent / "authorized.json"
    with pytest.raises(GradebookError, match="exactly"):
        await auth.authorize(
            client_file,
            destination,
            browser_open=lambda _: True,
            transport=httpx.MockTransport(
                lambda _: httpx.Response(
                    200, json={"scope": scope, "refresh_token": "fictional"}
                )
            ),
        )
    assert not destination.exists()


async def test_existing_credentials_are_preserved_before_browser_opens(
    client_file, receiver
):
    destination = client_file.parent / "authorized.json"
    destination.write_bytes(b"old credential")
    with pytest.raises(GradebookError, match="existing credentials"):
        await auth.authorize(
            client_file,
            destination,
            browser_open=lambda _: pytest.fail("browser must stay closed"),
        )
    assert destination.read_bytes() == b"old credential"
    assert not receiver.instances


async def test_browser_failure_closes_callback_without_credentials(
    client_file, receiver
):
    destination = client_file.parent / "authorized.json"
    with pytest.raises(GradebookError, match="open"):
        await auth.authorize(client_file, destination, browser_open=lambda _: False)
    assert receiver.instances[0].closed and not destination.exists()


@pytest.mark.parametrize(
    "target",
    [
        "/oauth2/callback?state=wrong&code=secret",
        "/oauth2/callback?state=expected&state=expected&code=secret",
        "/oauth2/callback?state=expected&code=a&code=b",
        "/other?state=expected&code=secret",
        "https://evil.example/oauth2/callback?state=expected&code=secret",
        "/oauth2/callback?state=expected&error=access_denied",
    ],
)
def test_callback_validation_never_echoes_code(target):
    with pytest.raises(GradebookError) as error:
        auth.callback_code(target, "expected")
    assert "secret" not in str(error.value)


def test_valid_callback_and_authenticated_denial():
    assert (
        auth.callback_code("/oauth2/callback?state=expected&code=valid", "expected")
        == "valid"
    )
    with pytest.raises(auth.AuthorizationDeclined):
        auth.callback_code(
            "/oauth2/callback?state=expected&error=access_denied", "expected"
        )
    with pytest.raises(GradebookError) as error:
        auth.callback_code(
            "/oauth2/callback?state=wrong&error=access_denied", "expected"
        )
    assert not isinstance(error.value, auth.AuthorizationDeclined)


@pytest.mark.parametrize(
    "change",
    [
        lambda d: d["installed"].update(client_id="1072944905499-default"),
        lambda d: d["installed"].update(token_uri="https://evil.example/token"),
        lambda d: d.update(web={}),
    ],
)
def test_only_owned_desktop_client_and_official_authority(client_file, change):
    raw = json.loads(client_file.read_text())
    change(raw)
    client_file.write_text(json.dumps(raw))
    with pytest.raises(GradebookError):
        auth.desktop_client(client_file)


def test_private_client_file_permissions_and_symlink(client_file):
    client_file.chmod(0o644)
    with pytest.raises(GradebookError, match="owner-only"):
        auth.desktop_client(client_file)
    client_file.chmod(0o600)
    alias = client_file.parent / "alias.json"
    alias.symlink_to(client_file)
    with pytest.raises(GradebookError, match="symlink"):
        auth.desktop_client(alias)


def test_private_write_never_overwrites(client_file):
    original = client_file.read_bytes()
    with pytest.raises(GradebookError, match="preserved"):
        auth.write_private_json(client_file, {"replacement": True})
    assert client_file.read_bytes() == original


def test_callback_handler_state_timeout_disconnect_and_quiet_errors(
    monkeypatch, capsys
):
    class Server:
        def __init__(self, address, handler):
            assert address == ("127.0.0.1", 0)
            self.server_port = 54321
            self.RequestHandlerClass = handler

        def server_close(self):
            pass

    monkeypatch.setattr(auth, "HTTPServer", Server)
    callback = auth.CallbackReceiver("expected")
    handler_class = callback.server.RequestHandlerClass
    handler = handler_class.__new__(handler_class)
    sent = []
    handler.send_response = sent.append
    handler.send_header = lambda *_: None
    handler.end_headers = lambda: None

    def disconnected(_):
        raise BrokenPipeError("fictional-private-callback-code")

    handler.wfile = SimpleNamespace(write=disconnected)
    handler.path = "/oauth2/callback?state=attacker&error=access_denied"
    handler.do_GET()
    assert callback.error is None and callback.code is None and sent[-1] == 400
    handler.path = "/oauth2/callback?state=expected&code=fictional-code"
    handler.do_GET()
    assert callback.code == "fictional-code" and sent[-1] == 200
    timeouts = []
    handler.connection = SimpleNamespace(settimeout=timeouts.append)
    monkeypatch.setattr(auth.BaseHTTPRequestHandler, "setup", lambda _: None)
    handler.setup()
    assert timeouts == [3]
    callback.server.handle_error(None, None)
    handler.log_message("secret callback %s", "fictional-code")
    output = capsys.readouterr()
    assert output.out == output.err == ""


def test_callback_rejects_excess_fields_without_echoing_values():
    target = "/oauth2/callback?state=expected&code=secret&" + "&".join(
        f"x{i}=private" for i in range(20)
    )
    with pytest.raises(GradebookError, match="field limit"):
        auth.callback_code(target, "expected")
