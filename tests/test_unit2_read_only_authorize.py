"""Only mocked browser/callback/OAuth and fictional private output."""

from __future__ import annotations

import json
from typing import Any
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
from test_gradebook_google_authorize import client_file as client_file
from test_gradebook_google_authorize import receiver as receiver

from canvas_mcp.gradebook import google_authorize as auth
from canvas_mcp.gradebook.client import GradebookError


async def test_dedicated_profile_requests_exact_read_only_scope(
    client_file: Any, receiver: Any
) -> None:
    urls = []
    destination = client_file.parent / "read-only-credential.json"
    result = await auth.authorize(
        client_file,
        destination,
        "unit2-typed-capture",
        read_only=True,
        browser_open=lambda url: urls.append(url) or True,
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200, json={"scope": auth.READ_ONLY_SCOPE, "refresh_token": "FICTIONAL"}
            )
        ),
    )
    query = parse_qs(urlsplit(urls[0]).query)
    assert query["scope"] == [auth.READ_ONLY_SCOPE]
    assert query["include_granted_scopes"] == ["false"]
    assert set(json.loads(destination.read_text(encoding="utf-8"))["tokens"]) == {"unit2-typed-capture"}
    assert result["scope"] == auth.READ_ONLY_SCOPE and "FICTIONAL" not in json.dumps(
        result
    )
    assert destination.stat().st_mode & 0o777 == 0o600


async def test_wrong_profile_stops_before_browser(
    client_file: Any, receiver: Any
) -> None:
    with pytest.raises(GradebookError, match="dedicated"):
        await auth.authorize(
            client_file,
            client_file.parent / "new.json",
            "gradebook",
            read_only=True,
            browser_open=lambda url: pytest.fail("MUST_NOT_OPEN_BROWSER"),
        )
    assert receiver.instances == []


async def test_broader_write_scope_is_not_saved_for_read_only_request(
    client_file: Any, receiver: Any
) -> None:
    destination = client_file.parent / "no-broader-scope.json"
    with pytest.raises(GradebookError, match="exactly"):
        await auth.authorize(
            client_file,
            destination,
            "unit2-typed-capture",
            read_only=True,
            browser_open=lambda url: True,
            transport=httpx.MockTransport(
                lambda request: httpx.Response(
                    200, json={"scope": auth.SCOPE, "refresh_token": "FICTIONAL"}
                )
            ),
        )
    assert not destination.exists()
