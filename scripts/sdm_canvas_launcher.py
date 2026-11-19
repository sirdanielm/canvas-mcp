"""Local macOS launcher: keep Canvas credentials in Keychain, outside Codex config."""

from __future__ import annotations

import argparse
import getpass
import json
import os
import re
import sys
from pathlib import Path
from urllib.parse import urlsplit

import httpx
from keyring.backend import KeyringBackend

ROOT = Path(__file__).resolve().parents[1]
CONFIG = Path.home() / ".config" / "canvas-authoring" / "connection.json"
SERVICE = "sdm.canvas-authoring"
MODULE_AUTHORING_WRITES = frozenset(
    {
        "add_draft_module_item",
        "edit_draft_module_item",
        "confirm_module_publication",
    }
)


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


class ConnectionCheckError(Exception):
    """A safe, user-facing connection failure with no response body or secret."""


def verify_credentials(origin: str, token: str) -> None:
    """Authenticate with exactly one GET; never follow redirects or modify Canvas."""
    origin = canvas_origin(origin)
    if not token or any(char.isspace() for char in token):
        raise ConnectionCheckError(
            "Paste the actual token value, without spaces or line breaks."
        )
    try:
        response = httpx.get(
            origin + "/api/v1/users/self/profile",
            headers={
                "Authorization": "Bearer " + token,
                "User-Agent": "sdm-canvas-authoring/1.0",
            },
            timeout=15,
            follow_redirects=False,
        )
    except httpx.HTTPError as exc:
        raise ConnectionCheckError(
            "Could not reach Canvas. Check the website and network connection."
        ) from exc
    if response.status_code == 401:
        raise ConnectionCheckError(
            "Canvas rejected the token (HTTP 401). Check that the token is active and belongs to this Canvas website. Paste its value, not its name."
        )
    if response.status_code != 200:
        raise ConnectionCheckError(
            f"Canvas authentication check returned HTTP {response.status_code}. No course content was changed."
        )
    try:
        profile = response.json()
    except ValueError as exc:
        raise ConnectionCheckError(
            "The website did not return a Canvas API profile."
        ) from exc
    if not isinstance(profile, dict) or not profile.get("id"):
        raise ConnectionCheckError("The website did not return a Canvas API profile.")


def setup_connection() -> int:
    if not sys.stdin.isatty():
        raise ValueError(
            "Setup needs an interactive terminal with hidden password input."
        )
    try:
        saved = read_connection()
    except (OSError, ValueError, KeyError, TypeError):
        saved = None
    print("Use the Canvas website you normally open in your browser.")
    if saved:
        print(f"Saved website: {saved}")
        print("Press Return to keep it, or type a different HTTPS Canvas website.")
    else:
        print(
            "Example only: https://your-school.instructure.com (this is not a preset)."
        )
    while True:
        value = input("Your Canvas website: ").strip()
        if not value and saved:
            origin = saved
            break
        try:
            origin = canvas_origin(value)
            break
        except ValueError:
            print(
                "Enter an HTTPS website address, without /courses/... or a query. An empty answer does not set the website."
            )
    token = getpass.getpass(
        "Paste the API token VALUE (hidden), then press Return: "
    ).strip()
    try:
        verify_credentials(origin, token)
    except ConnectionCheckError as exc:
        print(str(exc), file=sys.stderr)
        print(
            "The new token was not saved. Run setup again after correcting it.",
            file=sys.stderr,
        )
        return 1
    save_connection(origin, token)
    print(
        "Canvas accepted the token. It is saved in macOS Keychain. No course content was changed."
    )
    return 0


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


def module_authoring_write_policy(raw: str | None, publication_enabled: bool) -> str:
    """Keep this opt-in profile denied unless the operator names an exact subset."""
    if raw is None or not raw.strip():
        return "none"
    if raw.strip() == "none":
        return raw
    selected = set(filter(None, re.split(r"[,\s]+", raw.strip())))
    if not selected or not selected <= MODULE_AUTHORING_WRITES:
        return "none"
    if not publication_enabled:
        selected.discard("confirm_module_publication")
    return ",".join(sorted(selected)) if selected else "none"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--setup", action="store_true")
    mode.add_argument("--check", action="store_true")
    mode.add_argument("--draft-modules-only", action="store_true",
                      help="Start the guarded draft-only module profile; operator policy still applies")
    mode.add_argument(
        "--module-authoring-only",
        action="store_true",
        help="Start only the explicitly scoped module-authoring profile",
    )
    parser.add_argument("--module-authoring-courses")
    parser.add_argument("--module-authoring-journal")
    parser.add_argument("--enable-module-publication", action="store_true")
    mode.add_argument(
        "--verify",
        action="store_true",
        help="Check Canvas authentication using one GET",
    )
    args = parser.parse_args()
    if args.module_authoring_only:
        if not args.module_authoring_courses or not args.module_authoring_journal:
            parser.error("Module authoring requires explicit courses and an absolute journal")
        courses = args.module_authoring_courses.split(",")
        if (
            any(not re.fullmatch(r"[1-9][0-9]*", course) for course in courses)
            or len(courses) != len(set(courses))
            or not Path(args.module_authoring_journal).is_absolute()
        ):
            parser.error("Module authoring requires distinct numeric courses and an absolute journal")
    elif (
        args.module_authoring_courses is not None
        or args.module_authoring_journal is not None
        or args.enable_module_publication
    ):
        parser.error("Module authoring options require --module-authoring-only")
    try:
        if args.setup:
            return setup_connection()
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
        if args.verify:
            verify_credentials(origin, token)
            print(
                "Canvas authentication succeeded (HTTP 200). One GET request; no course content changed."
            )
            return 0
        executable = ROOT / ".venv" / "bin" / "canvas-mcp-server"
        os.chdir(ROOT)
        server_args = [str(executable), "--role", "educator"]
        environment = launch_environment(origin, token)
        if args.draft_modules_only:
            server_args.append("--draft-modules-only")
        if args.module_authoring_only:
            server_args.extend(
                [
                    "--module-authoring-only",
                    "--module-authoring-courses",
                    args.module_authoring_courses,
                    "--module-authoring-journal",
                    args.module_authoring_journal,
                ]
            )
            if args.enable_module_publication:
                server_args.append("--enable-module-publication")
            environment["ALLOWED_WRITE_TOOLS"] = module_authoring_write_policy(
                environment.get("ALLOWED_WRITE_TOOLS"), args.enable_module_publication
            )
        os.execve(
            str(executable),
            server_args,
            environment,
        )
    except ConnectionCheckError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\nCanvas setup cancelled.", file=sys.stderr)
        return 130
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
