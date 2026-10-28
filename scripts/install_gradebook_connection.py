"""Add only the reviewed canvas-gradebook entry; preserve all existing settings."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import tempfile
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GET_CONTROLS = [
    "request_gradebook_get_refresh",
    "get_gradebook_get_refresh_status",
    "review_gradebook_edits",
    "select_gradebook_review_batch",
]
LEGACY_DEFAULT_TOOLS = [
    "get_canvas_gradebook",
    "preview_gradebook_changes",
    "prepare_gradebook_refresh",
    "verify_gradebook_refresh",
    "prepare_gradebook_push",
    "get_gradebook_push_status",
    "reconcile_gradebook_push",
]


BATCH_REVIEW_TOOLS = [
    "prepare_gradebook_score_batch",
    "prepare_gradebook_comment_batch",
    "get_gradebook_batch_status",
    "revoke_gradebook_batch",
]
BATCH_WRITE_TOOLS = ["authorize_gradebook_batch", "execute_gradebook_batch_chunk"]
PRE_BATCH_DEFAULT_TOOLS = [
    "get_canvas_gradebook",
    "preview_gradebook_changes",
    "prepare_gradebook_push",
    "get_gradebook_push_status",
    "reconcile_gradebook_push",
    *GET_CONTROLS,
]


def _recognized_arguments(args: object, template: list[str]) -> bool:
    if not isinstance(args, list) or args[: len(template)] != template:
        return False
    extras = args[len(template) :]
    seen = set()
    index = 0
    while index < len(extras):
        flag = extras[index]
        if not isinstance(flag, str) or flag in seen:
            return False
        seen.add(flag)
        if flag in ("--enable-push", "--enable-comments"):
            index += 1
            continue
        if flag == "--comment-approval-seconds" and index + 1 < len(extras):
            value = extras[index + 1]
            if (
                not isinstance(value, str)
                or not value.isdecimal()
                or not 600 <= int(value) <= 1800
            ):
                return False
            index += 2
            continue
        return False
    return True


def _add_controls(config_path: Path, controls: list[str], label: str) -> str:
    """Add only protected GET control names; preserve custom push/comment gates."""
    if config_path.is_symlink():
        raise ValueError("Refusing to replace a symlinked configuration.")
    original = config_path.read_bytes()
    before = tomllib.loads(original.decode())
    entry = before.get("mcp_servers", {}).get("canvas-gradebook")
    if not isinstance(entry, dict):
        raise ValueError("Existing gradebook connection is required.")
    template = tomllib.loads((ROOT / "config/sdm-gradebook.toml.example").read_text(encoding="utf-8"))[
        "mcp_servers"
    ]["canvas-gradebook"]
    if (
        entry.get("command") != template["command"]
        or entry.get("cwd") != template["cwd"]
    ):
        raise ValueError("Gradebook launcher binding differs; no settings changed.")
    args = entry.get("args")
    if not _recognized_arguments(args, template["args"]):
        raise ValueError("Gradebook launcher arguments differ; no settings changed.")
    enabled = entry.get("enabled_tools")
    if (
        not isinstance(enabled, list)
        or any(not isinstance(x, str) for x in enabled)
        or len(set(enabled)) != len(enabled)
    ):
        raise ValueError("Gradebook tool allowlist is invalid.")
    added = [x for x in controls if x not in enabled]
    if not added:
        return f"{label} controls already enabled; no settings changed."
    new_tools = [*enabled, *added]
    table = re.search(
        r"(?ms)^\[mcp_servers\.canvas-gradebook\]\r?\n.*?(?=^\[|\Z)", original.decode()
    )
    if table is None:
        raise ValueError("Cannot locate exact gradebook table.")
    changed, count = re.subn(
        r"(?ms)^enabled_tools\s*=\s*\[[^\]]*\]",
        lambda _: "enabled_tools = " + json.dumps(new_tools),
        table.group(),
        count=1,
    )
    if count != 1:
        raise ValueError("Cannot locate gradebook tool allowlist.")
    replacement = (
        original.decode()[: table.start()] + changed + original.decode()[table.end() :]
    ).encode()
    after = tomllib.loads(replacement.decode())
    after["mcp_servers"]["canvas-gradebook"]["enabled_tools"] = enabled
    if after != before:
        raise ValueError("Unrelated settings changed; installation refused.")
    backup = config_path.with_name(
        "config.before-"
        + label.lower()
        + "-controls-"
        + hashlib.sha256(original).hexdigest()[:12]
        + ".toml"
    )
    if not backup.exists():
        with open(
            backup, "xb", opener=lambda p, flags: os.open(p, flags, 0o600)
        ) as stream:
            stream.write(original)
    fd, name = tempfile.mkstemp(
        dir=config_path.parent, prefix=".gradebook-get-controls-"
    )
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(replacement)
            stream.flush()
            os.fsync(stream.fileno())
        if config_path.read_bytes() != original:
            raise ValueError(
                "Configuration changed during installation; no replacement."
            )
        os.replace(name, config_path)
    finally:
        Path(name).unlink(missing_ok=True)
    check = tomllib.loads(config_path.read_text(encoding="utf-8"))
    assert check["mcp_servers"]["canvas-gradebook"]["enabled_tools"] == new_tools
    check["mcp_servers"]["canvas-gradebook"]["enabled_tools"] = enabled
    if check != before:
        raise ValueError("Configuration readback differs.")
    return f"Added {label} controls; all existing push, comment and connection settings preserved."


def add_get_controls(config_path: Path) -> str:
    return _add_controls(config_path, GET_CONTROLS, "get")


def add_batch_controls(config_path: Path) -> str:
    """Expose reviewed batches only within already enabled publication channels."""
    if config_path.is_symlink():
        raise ValueError("Refusing to replace a symlinked configuration.")
    entry = (
        tomllib.loads(config_path.read_text(encoding="utf-8"))
        .get("mcp_servers", {})
        .get("canvas-gradebook", {})
    )
    args = entry.get("args", [])
    controls = list(BATCH_REVIEW_TOOLS)
    if "--enable-push" in args or "--enable-comments" in args:
        controls += BATCH_WRITE_TOOLS
    return _add_controls(config_path, controls, "batch")


def install(config_path: Path, upgrade: bool = False) -> str:
    if config_path.is_symlink():
        raise ValueError("Refusing to replace a symlinked configuration.")
    original = config_path.read_bytes()
    parsed = tomllib.loads(original.decode())
    addition = (ROOT / "config" / "sdm-gradebook.toml.example").read_text(encoding="utf-8")
    desired = tomllib.loads(addition)["mcp_servers"]["canvas-gradebook"]
    newline = "\r\n" if b"\r\n" in original else "\n"
    formatted_addition = addition.replace("\n", newline)
    existing = parsed.get("mcp_servers", {}).get("canvas-gradebook")
    if existing is not None:
        if existing == desired:
            return "Connection already matches; no settings changed."
        recognized_previous = [
            {**desired, "enabled_tools": tools, "tool_timeout_sec": timeout}
            for tools in (
                ["get_canvas_gradebook", "preview_gradebook_changes"],
                LEGACY_DEFAULT_TOOLS,
                PRE_BATCH_DEFAULT_TOOLS,
                desired["enabled_tools"],
            )
            for timeout in (180, desired["tool_timeout_sec"])
        ]
        if not upgrade or existing not in recognized_previous:
            raise ValueError(
                "An existing canvas-gradebook connection differs; no settings changed."
            )
        updated, replacements = re.subn(
            r"(?ms)^\[mcp_servers\.canvas-gradebook\]\r?\n.*?(?=^\[|\Z)",
            lambda _: formatted_addition + newline,
            original.decode(),
            count=1,
        )
        if replacements != 1:
            raise ValueError("Cannot safely locate the existing gradebook table.")
        replacement = updated.encode()
        parsed["mcp_servers"].pop("canvas-gradebook")
    else:
        replacement = original + newline.encode() + formatted_addition.encode()
    check = tomllib.loads(replacement.decode())
    check["mcp_servers"].pop("canvas-gradebook")
    if check != parsed:
        raise ValueError("Unrelated settings changed; installation refused.")
    stamp = hashlib.sha256(original).hexdigest()[:12]
    backup = config_path.with_name(f"config.before-gradebook-{stamp}.toml")
    if not backup.exists():
        with open(
            backup, "xb", opener=lambda p, flags: os.open(p, flags, 0o600)
        ) as stream:
            stream.write(original)
    fd, temporary = tempfile.mkstemp(
        dir=config_path.parent, prefix=".gradebook-config-"
    )
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(replacement)
            stream.flush()
            os.fsync(stream.fileno())
        if config_path.read_bytes() != original:
            raise ValueError(
                "Configuration changed during installation; retry after review."
            )
        os.replace(temporary, config_path)
    finally:
        Path(temporary).unlink(missing_ok=True)
    if (
        tomllib.loads(config_path.read_text(encoding="utf-8"))["mcp_servers"]["canvas-gradebook"]
        != desired
    ):
        raise ValueError("Configuration readback did not match.")
    return "Installed protected GET and private EDIT review controls; Canvas publication remains disabled and existing connections preserved."


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--config", type=Path, default=Path.home() / ".codex" / "config.toml"
    )
    parser.add_argument(
        "--upgrade",
        action="store_true",
        help="Upgrade a recognized earlier read-only entry; customized write gates are preserved by refusal",
    )
    parser.add_argument(
        "--add-get-controls",
        action="store_true",
        help="Add only GET-only queue/status tools to the existing connection",
    )
    parser.add_argument(
        "--add-batch-controls",
        action="store_true",
        help="Add reviewed batch tools while retaining existing score/comment enablement",
    )
    args = parser.parse_args()
    if args.add_get_controls and args.add_batch_controls:
        parser.error("Choose one control update per invocation")
    print(
        add_batch_controls(args.config)
        if args.add_batch_controls
        else (
            add_get_controls(args.config)
            if args.add_get_controls
            else install(args.config, args.upgrade)
        )
    )
