"""Local macOS launcher: keep Canvas credentials in Keychain, outside Codex config."""

from __future__ import annotations

import argparse
import getpass
import json
import os
import sys
from pathlib import Path
from urllib.parse import urlsplit

from keyring.backend import KeyringBackend

ROOT = Path(__file__).resolve().parents[1]
CONFIG = Path.home() / ".config" / "canvas-authoring" / "connection.json"
SERVICE = "sdm.canvas-authoring"


def canvas_origin(value: str) -> str:
    parsed = urlsplit(value.strip())
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
        or parsed.path.rstrip("/") not in ("", "/api/v1")
    ):
        raise ValueError(
            "Enter your HTTPS Canvas home URL, without a course path or query."
        )
    _ = parsed.port  # Reject malformed ports before saving or using the URL.
    return f"https://{parsed.netloc.lower()}"


def keychain() -> KeyringBackend:
    from keyring.backends.macOS import Keyring

    return Keyring()  # Deliberately never use a plaintext fallback backend.


def read_connection() -> str:
    value = json.loads(CONFIG.read_text())
    if set(value) != {"canvas_origin"}:
        raise ValueError(
            "Unexpected connection settings; rerun Setup Canvas Connection."
        )
    return canvas_origin(value["canvas_origin"])


def save_connection(origin: str, token: str) -> None:
    origin = canvas_origin(origin)
    if not token or any(char.isspace() for char in token):
        raise ValueError("The token must be nonempty and contain no whitespace.")
    keychain().set_password(SERVICE, origin, token)
    CONFIG.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = CONFIG.with_suffix(".tmp")
    with open(
        temporary, "w", opener=lambda path, flags: os.open(path, flags, 0o600)
    ) as stream:
        json.dump({"canvas_origin": origin}, stream)
        stream.write("\n")
    os.chmod(temporary, 0o600)
    temporary.replace(CONFIG)


def launch_environment(origin: str, token: str) -> dict[str, str]:
    result = dict(os.environ)
    result.update(
        {
            "CANVAS_API_URL": canvas_origin(origin) + "/api/v1",
            "CANVAS_API_TOKEN": token,
            "CANVAS_ROLE": "educator",
            "EXECUTE_TYPESCRIPT_ENABLED": "false",
            "STUDENT_WRITE_TOOLS": "",
            "PYTHON_DOTENV_DISABLED": "1",
            "ENABLE_DATA_ANONYMIZATION": "true",
        }
    )
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--setup", action="store_true")
    mode.add_argument("--check", action="store_true")
    args = parser.parse_args()
    try:
        if args.setup:
            if not sys.stdin.isatty():
                raise ValueError(
                    "Setup needs an interactive terminal with hidden password input."
                )
            origin = canvas_origin(
                input("Canvas home URL (https://your-school.instructure.com): ")
            )
            token = getpass.getpass(
                "Canvas API token (hidden; stored in macOS Keychain): "
            ).strip()
            save_connection(origin, token)
            print(
                "Canvas connection saved. The token is in macOS Keychain, not in this repository."
            )
            return 0
        origin = read_connection()
        token = keychain().get_password(SERVICE, origin)
        if not token:
            raise ValueError(
                "No Canvas token found. Run Setup Canvas Connection.command first."
            )
        if args.check:
            print(
                "Canvas connection configured; Keychain credential is available. No API call made."
            )
            return 0
        executable = ROOT / ".venv" / "bin" / "canvas-mcp-server"
        os.chdir(ROOT)
        os.execve(
            str(executable),
            [str(executable), "--role", "educator"],
            launch_environment(origin, token),
        )
    except FileNotFoundError:
        print(
            "Canvas setup is incomplete. Run scripts/Setup Canvas Connection.command.",
            file=sys.stderr,
        )
        return 1
    except (ValueError, KeyError, TypeError):
        print(
            "Canvas settings are missing or invalid. Rerun Setup Canvas Connection.command.",
            file=sys.stderr,
        )
        return 1
    except Exception:
        # Keychain errors may contain platform details. Never echo credential-bearing values.
        print(
            "Canvas startup failed. Check Keychain access and the local installation.",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
