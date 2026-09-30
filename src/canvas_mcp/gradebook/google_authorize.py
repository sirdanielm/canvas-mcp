"""Explicit desktop OAuth setup for the local gradebook worker.

Only an explicitly invoked setup flow opens a browser. PKCE and state bind a
short-lived loopback callback; codes, tokens and HTTP request targets are never
logged. Existing credentials are never overwritten.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import os
import secrets
import stat
import tempfile
import time
import webbrowser
from collections.abc import Callable
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlencode, urlsplit

import httpx

from .client import GradebookError

SCOPE = "https://www.googleapis.com/auth/spreadsheets"
AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
DEFAULT_CLASP_PROJECT = "1072944905499-"


class AuthorizationDeclined(GradebookError):
    """A denial callback whose state has already been authenticated."""


def read_private_json(path: Path) -> dict[str, Any]:
    descriptor: int | None = None
    try:
        if path.is_symlink():
            raise GradebookError("Private configuration must not be a symlink.")
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
        info = os.fstat(descriptor)
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_mode & 0o077
            or info.st_uid != os.getuid()
            or not 0 < info.st_size <= 65_536
        ):
            raise GradebookError(
                "Configuration requires an owner-only file (mode 600)."
            )
        with os.fdopen(descriptor, "rb") as stream:
            descriptor = None
            raw = stream.read(65_537)
        if len(raw) > 65_536:
            raise GradebookError("Private configuration exceeds its size limit.")
        value = json.loads(raw)
        if not isinstance(value, dict):
            raise GradebookError("Private configuration must be a JSON object.")
        return value
    except GradebookError:
        raise
    except (OSError, ValueError, TypeError):
        raise GradebookError(
            "Private configuration is unavailable or invalid."
        ) from None
    finally:
        if descriptor is not None:
            os.close(descriptor)


def write_private_json(path: Path, value: dict[str, Any]) -> None:
    write_private_bytes(path, (json.dumps(value, indent=2) + "\n").encode())


def write_private_bytes(path: Path, value: bytes) -> None:
    """Exclusive publication; a race or existing file never destroys prior data."""
    if not path.is_absolute() or path.is_symlink() or path.exists():
        raise GradebookError(
            "Choose a new absolute private output path; existing files are preserved."
        )
    if any(parent.is_symlink() for parent in path.parents):
        raise GradebookError("Private output directories must not be symlinks.")
    temporary: str | None = None
    try:
        path.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
        info = path.parent.stat()
        if info.st_uid != os.getuid() or info.st_mode & 0o077:
            raise GradebookError(
                "Private output directory must be owned by you with mode 700."
            )
        descriptor, temporary = tempfile.mkstemp(prefix=".pending-", dir=path.parent)
        with os.fdopen(descriptor, "wb") as stream:
            os.fchmod(stream.fileno(), 0o600)
            stream.write(value)
            stream.flush()
            os.fsync(stream.fileno())
        os.link(temporary, path)
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    except GradebookError:
        raise
    except OSError:
        raise GradebookError(
            "Private output was not saved; existing files are preserved."
        ) from None
    finally:
        if temporary is not None:
            Path(temporary).unlink(missing_ok=True)


def desktop_client(path: Path) -> dict[str, str]:
    raw = read_private_json(path)
    installed = raw.get("installed")
    if not isinstance(installed, dict) or "web" in raw:
        raise GradebookError(
            "Google setup requires your own Desktop OAuth client JSON."
        )
    result = {}
    for key in ("client_id", "client_secret"):
        value = installed.get(key)
        if not isinstance(value, str) or not value or len(value) > 16_384:
            raise GradebookError("Desktop OAuth client configuration is incomplete.")
        result[key] = value
    if result["client_id"].startswith(DEFAULT_CLASP_PROJECT):
        raise GradebookError(
            "Google's default clasp project cannot be used; supply your own Desktop OAuth client."
        )
    if installed.get("token_uri", TOKEN_URL) != TOKEN_URL or installed.get(
        "auth_uri", AUTH_URL
    ) not in {
        AUTH_URL,
        "https://accounts.google.com/o/oauth2/auth",
    }:
        raise GradebookError("Desktop OAuth configuration has an unexpected authority.")
    return result


def callback_code(target: str, expected_state: str) -> str:
    """Pure callback validation; exceptions never contain query values."""
    parsed = urlsplit(target)
    if (
        parsed.path != "/oauth2/callback"
        or parsed.scheme
        or parsed.netloc
        or parsed.fragment
    ):
        raise GradebookError("OAuth callback path was invalid.")
    try:
        query = parse_qs(parsed.query, keep_blank_values=True, max_num_fields=10)
    except ValueError:
        raise GradebookError("OAuth callback query exceeded its field limit.") from None
    states = query.get("state", [])
    if len(states) != 1 or not secrets.compare_digest(states[0], expected_state):
        raise GradebookError("OAuth callback state did not match.")
    if "error" in query:
        raise AuthorizationDeclined("Google authorization was declined or failed.")
    codes = query.get("code", [])
    if len(codes) != 1 or not codes[0] or len(codes[0]) > 16_384:
        raise GradebookError("OAuth callback code was unavailable.")
    return codes[0]


class CallbackReceiver:
    def __init__(self, state: str) -> None:
        self.code: str | None = None
        self.error: GradebookError | None = None
        receiver = self

        class Handler(BaseHTTPRequestHandler):
            def setup(self) -> None:
                super().setup()
                self.connection.settimeout(3)

            def log_message(self, format: str, *args: Any) -> None:
                pass

            def do_GET(self) -> None:
                try:
                    code = callback_code(self.path, state)
                    if receiver.code is not None:
                        raise GradebookError("OAuth callback was already consumed.")
                    receiver.code = code
                    status, body = (
                        200,
                        b"Authorization received. Return to the setup terminal.",
                    )
                except (GradebookError, ValueError) as exc:
                    # Invalid cross-site callbacks cannot terminate the real flow.
                    status, body = (
                        400,
                        b"Authorization callback rejected. Return to the setup terminal.",
                    )
                    if isinstance(exc, AuthorizationDeclined):
                        receiver.error = GradebookError(
                            "Google authorization was declined or failed."
                        )
                try:
                    self.send_response(status)
                    self.send_header("Content-Type", "text/plain; charset=utf-8")
                    self.send_header("Cache-Control", "no-store")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                except OSError:
                    # Browser disconnects do not invalidate the accepted code or
                    # print a request traceback containing its callback URL.
                    pass

            def do_POST(self) -> None:
                try:
                    self.send_response(405)
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                except OSError:
                    pass

        class QuietServer(HTTPServer):
            def handle_error(self, request: Any, client_address: Any) -> None:
                # Never let callback URLs or codes reach traceback logging.
                pass

        self.server = QuietServer(("127.0.0.1", 0), Handler)
        self.server.timeout = 1
        self.redirect_uri = (
            f"http://127.0.0.1:{self.server.server_port}/oauth2/callback"
        )

    async def wait(self, timeout: float) -> str:
        deadline = time.monotonic() + timeout
        while self.code is None and self.error is None and time.monotonic() < deadline:
            await asyncio.to_thread(self.server.handle_request)
        if self.error is not None:
            raise self.error
        if self.code is None:
            raise GradebookError(
                "Google authorization timed out; no credential was saved."
            )
        return self.code

    def close(self) -> None:
        self.server.server_close()


async def authorize(
    client_config: Path,
    credential_path: Path,
    profile: str = "gradebook",
    *,
    timeout: float = 180,
    browser_open: Callable[[str], bool] = webbrowser.open,
    transport: httpx.AsyncBaseTransport | None = None,
) -> dict[str, Any]:
    if (
        not profile
        or not all(c.isascii() and (c.isalnum() or c in "_-") for c in profile)
        or len(profile) > 80
    ):
        raise GradebookError("Invalid Google authorization profile.")
    if not 1 <= timeout <= 300:
        raise GradebookError(
            "OAuth callback timeout must be between 1 and 300 seconds."
        )
    if (
        not credential_path.is_absolute()
        or credential_path.exists()
        or credential_path.is_symlink()
    ):
        raise GradebookError(
            "Choose a new absolute credential path; existing credentials are preserved."
        )
    client = desktop_client(client_config)
    state, verifier = secrets.token_urlsafe(32), secrets.token_urlsafe(64)
    challenge = (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
        .rstrip(b"=")
        .decode()
    )
    receiver = CallbackReceiver(state)
    try:
        url = (
            AUTH_URL
            + "?"
            + urlencode(
                {
                    "client_id": client["client_id"],
                    "redirect_uri": receiver.redirect_uri,
                    "response_type": "code",
                    "scope": SCOPE,
                    "access_type": "offline",
                    "prompt": "consent",
                    "include_granted_scopes": "false",
                    "state": state,
                    "code_challenge": challenge,
                    "code_challenge_method": "S256",
                }
            )
        )
        if not browser_open(url):
            raise GradebookError("Could not open the Google authorization browser.")
        code = await receiver.wait(timeout)
        async with httpx.AsyncClient(
            transport=transport, timeout=30, follow_redirects=False, trust_env=False
        ) as http:
            try:
                async with http.stream(
                    "POST",
                    TOKEN_URL,
                    data={
                        **client,
                        "grant_type": "authorization_code",
                        "code": code,
                        "redirect_uri": receiver.redirect_uri,
                        "code_verifier": verifier,
                    },
                ) as response:
                    raw = bytearray()
                    async for part in response.aiter_bytes(chunk_size=8192):
                        raw.extend(part)
                        if len(raw) > 65_536:
                            raise GradebookError(
                                "Google OAuth response exceeded its size limit."
                            )
                    if response.status_code != 200:
                        raise GradebookError(
                            "Google OAuth exchange failed; restart authorization without reusing the code."
                        )
            except httpx.HTTPError:
                raise GradebookError(
                    "Google OAuth transport failed; restart authorization without reusing the code."
                ) from None
        try:
            token = json.loads(raw)
        except (ValueError, UnicodeDecodeError):
            raise GradebookError("Google OAuth returned an invalid response.") from None
        if (
            not isinstance(token, dict)
            or not isinstance(token.get("scope"), str)
            or set(token["scope"].split()) != {SCOPE}
        ):
            raise GradebookError(
                "Google OAuth did not grant exactly the requested Sheets scope."
            )
        refresh = token.get("refresh_token")
        if not isinstance(refresh, str) or not refresh or len(refresh) > 16_384:
            raise GradebookError(
                "Google did not issue a refresh credential; no credential was saved."
            )
        write_private_json(
            credential_path,
            {
                "tokens": {
                    profile: {
                        "type": "authorized_user",
                        **client,
                        "refresh_token": refresh,
                    }
                }
            },
        )
        return {
            "state": "AUTHORIZED",
            "profile": profile,
            "scope": SCOPE,
            "canvas_writes": 0,
            "sheets_writes": 0,
        }
    finally:
        receiver.close()
