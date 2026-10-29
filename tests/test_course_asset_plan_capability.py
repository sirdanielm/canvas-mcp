"""Unavailable secure-open capabilities fail before any input or service access."""

import builtins
import importlib
import io
import os
import socket
import subprocess
from pathlib import Path
from typing import Any

import httpx
import pytest

from canvas_mcp.mirror import core
from canvas_mcp.mirror.core import MirrorError


@pytest.mark.parametrize("missing_flag", ["O_NOFOLLOW", "O_DIRECTORY", "O_NONBLOCK"])
def test_unavailable_secure_open_stops_before_any_read_or_side_effect(
    monkeypatch: pytest.MonkeyPatch, missing_flag: str
) -> None:
    module = importlib.import_module("canvas_mcp.mirror.asset_plan")
    inputs = {
        "baseline_snapshot": Path("fictional-not-present/baseline-snapshot"),
        "baseline_assets": Path("fictional-not-present/baseline-assets"),
        "current_snapshot": Path("fictional-not-present/current-snapshot"),
    }
    attempts = []

    def forbidden(*args: Any, **kwargs: Any) -> Any:
        attempts.append("forbidden-access")
        raise AssertionError("Capability failure must precede all I/O")

    with monkeypatch.context() as guard:
        guard.delattr(os, missing_flag, raising=False)
        original_open = os.open
        original_stat = os.stat
        guard.setattr(os, "open", forbidden)
        if original_open in os.supports_dir_fd:
            guard.setattr(os, "supports_dir_fd", {*os.supports_dir_fd, forbidden})
        for name in ("stat", "lstat", "listdir", "scandir", "mkdir", "unlink", "replace"):
            guard.setattr(os, name, forbidden)
        if original_stat in os.supports_dir_fd:
            guard.setattr(os, "supports_dir_fd", {*os.supports_dir_fd, forbidden})
        if original_stat in os.supports_follow_symlinks:
            guard.setattr(os, "supports_follow_symlinks", {*os.supports_follow_symlinks, forbidden})
        for name in ("open", "read_bytes", "read_text", "stat", "lstat", "resolve", "exists"):
            guard.setattr(Path, name, forbidden)
        guard.setattr(builtins, "open", forbidden)
        guard.setattr(io, "open", forbidden)
        guard.setattr(core, "GetClient", forbidden)
        guard.setattr(httpx, "AsyncClient", forbidden)
        guard.setattr(httpx, "Client", forbidden)
        guard.setattr(socket, "create_connection", forbidden)
        guard.setattr(socket.socket, "connect", forbidden)
        guard.setattr(subprocess, "Popen", forbidden)
        guard.setattr(os, "system", forbidden)
        with pytest.raises(MirrorError, match="^ASSET_PLAN_SECURE_OPEN_UNAVAILABLE$"):
            module.plan_asset_refresh(**inputs)
    assert attempts == []
