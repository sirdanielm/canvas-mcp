"""Add only the reviewed canvas-gradebook entry; preserve all existing settings."""

from __future__ import annotations

import argparse
import hashlib
import os
import re
import tempfile
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def install(config_path: Path, upgrade: bool = False) -> str:
    if config_path.is_symlink():
        raise ValueError("Refusing to replace a symlinked configuration.")
    original = config_path.read_bytes()
    parsed = tomllib.loads(original.decode())
    addition = (ROOT / "config" / "sdm-gradebook.toml.example").read_text()
    desired = tomllib.loads(addition)["mcp_servers"]["canvas-gradebook"]
    existing = parsed.get("mcp_servers", {}).get("canvas-gradebook")
    if existing is not None:
        if existing == desired:
            return "Connection already matches; no settings changed."
        expected_previous = {
            **desired,
            "enabled_tools": ["get_canvas_gradebook", "preview_gradebook_changes"],
        }
        if not upgrade or existing != expected_previous:
            raise ValueError(
                "An existing canvas-gradebook connection differs; no settings changed."
            )
        updated, replacements = re.subn(
            r"(?ms)^\[mcp_servers\.canvas-gradebook\]\n.*?(?=^\[|\Z)",
            lambda _: addition + "\n",
            original.decode(),
            count=1,
        )
        if replacements != 1:
            raise ValueError("Cannot safely locate the existing gradebook table.")
        replacement = updated.encode()
        parsed["mcp_servers"].pop("canvas-gradebook")
    else:
        replacement = original + b"\n" + addition.encode()
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
        tomllib.loads(config_path.read_text())["mcp_servers"]["canvas-gradebook"]
        != desired
    ):
        raise ValueError("Configuration readback did not match.")
    return "Installed canvas-gradebook with seven read-only Canvas tools; existing connections preserved."


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--config", type=Path, default=Path.home() / ".codex" / "config.toml"
    )
    parser.add_argument(
        "--upgrade",
        action="store_true",
        help="Upgrade the recognized initial two-tool entry only",
    )
    args = parser.parse_args()
    print(install(args.config, args.upgrade))
