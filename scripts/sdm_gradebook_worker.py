"""Explicit local worker lifecycle. Canvas remains GET-only in every command."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import plistlib
import sys
import uuid
from collections import Counter
from pathlib import Path
from typing import Any

# canvas_mcp.__init__ imports the server, which can import dotenv-aware config.
# Disable dotenv before the first package import, including import-only use.
os.environ["PYTHON_DOTENV_DISABLED"] = "1"
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
DEFAULT_CONFIG = Path.home() / ".config/canvas-authoring/gradebook-worker.json"
COURSES = {"core": "363308", "advanced": "374070"}
ORIGIN = "https://fcps.instructure.com"

from canvas_mcp.gradebook.client import GradebookClient, GradebookError  # noqa: E402
from canvas_mcp.gradebook.google import GoogleSheets  # noqa: E402
from canvas_mcp.gradebook.google_authorize import (  # noqa: E402
    authorize,
    read_private_json,
    write_private_bytes,
    write_private_json,
)
from canvas_mcp.gradebook.native import validate_workbook  # noqa: E402
from canvas_mcp.gradebook.store import Store  # noqa: E402
from canvas_mcp.gradebook.workbook import edits_from_cells  # noqa: E402
from canvas_mcp.gradebook.worker import RefreshJournal, RefreshWorker  # noqa: E402


def bindings() -> dict[str, Any]:
    try:
        value = json.loads((ROOT / "config/sdm-gradebook-workbooks.json").read_text())
        if set(value) != set(COURSES) or any(
            value[k]["course_id"] != v for k, v in COURSES.items()
        ):
            raise ValueError
        if len({b["spreadsheet_id"] for b in value.values()}) != 1:
            raise ValueError
        return dict(value)
    except (OSError, ValueError, KeyError, TypeError):
        raise GradebookError(
            "Canonical gradebook bindings are unavailable or changed."
        ) from None


def _absolute_path(value: Any) -> Path:
    if (
        not isinstance(value, str)
        or not Path(value).is_absolute()
        or Path(value).is_symlink()
    ):
        raise GradebookError("Worker paths must be absolute and must not be symlinks.")
    return Path(value)


def load_config(path: Path) -> dict[str, Any]:
    value = read_private_json(path)
    if (
        set(value)
        != {
            "schema_version",
            "instance_id",
            "credential_path",
            "profile",
            "state_dir",
            "poll_seconds",
        }
        or type(value["schema_version"]) is not int
        or value["schema_version"] != 1
    ):
        raise GradebookError("Unsupported worker configuration schema.")
    try:
        if str(uuid.UUID(value["instance_id"])) != value["instance_id"]:
            raise ValueError
    except (ValueError, TypeError, AttributeError):
        raise GradebookError("Worker instance ID is invalid.") from None
    _absolute_path(value["credential_path"])
    _absolute_path(value["state_dir"])
    if value["profile"] != "gradebook":
        raise GradebookError("Worker requires the dedicated gradebook OAuth profile.")
    if (
        isinstance(value["poll_seconds"], bool)
        or not isinstance(value["poll_seconds"], int)
        or not 30 <= value["poll_seconds"] <= 300
    ):
        raise GradebookError("Worker polling must be between 30 and 300 seconds.")
    return value


def configure(
    path: Path, credential_path: Path | None = None, state_dir: Path | None = None
) -> dict[str, Any]:
    if path.exists():
        load_config(path)
        return {"state": "CONFIGURED", "existing": True, "started": False}
    credential = credential_path or path.parent / "gradebook-google.json"
    state = state_dir or ROOT / "local_gradebooks"
    _absolute_path(str(credential))
    _absolute_path(str(state))
    value = {
        "schema_version": 1,
        "instance_id": str(uuid.uuid4()),
        "credential_path": str(credential),
        "profile": "gradebook",
        "state_dir": str(state),
        "poll_seconds": 30,
    }
    write_private_json(path, value)
    return {"state": "CONFIGURED", "existing": False, "started": False}


def canvas_client() -> GradebookClient:
    # Imported only for active processing. Doctor/status never fetch Canvas.
    from sdm_canvas_launcher import SERVICE, keychain, read_connection

    try:
        origin = read_connection()
        if origin != ORIGIN:
            raise GradebookError(
                "Canvas connection does not match the fixed course origin."
            )
        token = keychain().get_password(SERVICE, origin)
        if not token:
            raise GradebookError("Canvas Keychain credential is unavailable.")
        return GradebookClient(origin, token)
    except GradebookError:
        raise
    except Exception:
        raise GradebookError(
            "Canvas connection or Keychain access is unavailable."
        ) from None


def google_client(config: dict[str, Any], bound: dict[str, Any]) -> GoogleSheets:
    return GoogleSheets(
        bound["core"]["spreadsheet_id"],
        Path(config["credential_path"]),
        profile=config["profile"],
    )


async def doctor(google: Any, store: Store, bound: dict[str, Any]) -> dict[str, Any]:
    raw = await google.read_workbook()
    views = validate_workbook(raw, bound)
    summary = {}
    for course in ("core", "advanced"):
        snapshot_id = views[course]["_Sync"].get("B2")
        if not isinstance(snapshot_id, str):
            raise GradebookError("Trusted workbook baseline reference is unavailable.")
        baseline = store.load("snapshot", snapshot_id)
        if (
            baseline.get("course_id") != COURSES[course]
            or baseline.get("origin") != ORIGIN
        ):
            raise GradebookError("Trusted baseline course or origin differs.")
        edits = edits_from_cells(views[course], baseline)
        summary[course] = {
            "students": len(baseline["students"]),
            "assignments": len(baseline["assignments"]),
            "pending_edits": len(edits["edits"]),
        }
    return {
        "state": "READY",
        "summary": summary,
        "canvas_writes": 0,
        "sheets_writes": 0,
        "worker_installed": False,
    }


def local_status(
    config: dict[str, Any], bound: dict[str, Any], request_id: str | None = None
) -> dict[str, Any]:
    journal = RefreshJournal(
        Store(Path(config["state_dir"])).root, bound["core"]["spreadsheet_id"]
    )
    if request_id:
        _request_id(request_id)
        operation = journal.get(request_id)
        result = {
            "state": operation["status"] if operation else "NOT_FOUND",
            "request_id": request_id,
            "source": "local_journal",
        }
        if operation and isinstance(
            operation.get("payload", {}).get("failure_reason"), str
        ):
            result["failure_reason"] = operation["payload"]["failure_reason"]
        return result
    states: Counter[str] = Counter()
    for rid in journal.unresolved():
        operation = journal.get(rid)
        if operation:
            states[operation["status"]] += 1
    in_progress = {"CLAIMING", "CLAIMED", "PREPARED", "SENDING", "VERIFYING"}
    # These are durable operation phases, not evidence that a process is alive.
    # Uncertainty or a hold takes precedence over another operation's progress.
    if "UNCERTAIN" in states:
        state = "UNCERTAIN"
    elif set(states) - in_progress:
        state = "HELD"
    else:
        state = "IN_PROGRESS" if states else "NO_LOCAL_HOLDS"
    return {
        "state": state,
        "unresolved": sum(states.values()),
        "states": dict(states),
        "source": "local_journal",
        "worker_running": "unverified",
    }


def _request_id(value: str) -> None:
    try:
        if str(uuid.UUID(value)) != value:
            raise ValueError
    except (ValueError, TypeError, AttributeError):
        raise GradebookError("Refresh request ID must be a canonical UUID.") from None


async def run_loop(worker: Any, poll_seconds: int) -> None:
    failures, previous = 0, None
    while True:
        try:
            result = await worker.step()
            if result.get("state") == "IDLE":
                await worker.heartbeat()
            message = json.dumps(result, sort_keys=True)
            if message != previous:
                print(message, flush=True)
                previous = message
            failures = 0
            delay = poll_seconds
        except GradebookError as exc:
            print(
                json.dumps({"state": "HELD", "error": str(exc), "canvas_writes": 0}),
                flush=True,
            )
            delay = min(300, poll_seconds * 2 ** min(failures, 4))
            failures += 1
        except Exception:
            print(
                json.dumps(
                    {
                        "state": "HELD",
                        "error": "Worker stopped this attempt safely; inspect durable status.",
                        "canvas_writes": 0,
                    }
                ),
                flush=True,
            )
            delay = min(300, poll_seconds * 2 ** min(failures, 4))
            failures += 1
        await asyncio.sleep(delay)


def launch_agent(
    path: Path, config_path: Path, config: dict[str, Any]
) -> dict[str, Any]:
    """Generate a reviewable template only; never invoke launchctl or install."""
    logs = Path(config["state_dir"]) / "refresh-worker"
    logs.mkdir(parents=True, mode=0o700, exist_ok=True)
    if logs.is_symlink() or logs.stat().st_mode & 0o077:
        raise GradebookError("Worker log directory must be private.")
    value = {
        "Label": "org.sdm.canvas-gradebook-refresh",
        "ProgramArguments": [
            str(ROOT / ".venv/bin/python"),
            str(ROOT / "scripts/sdm_gradebook_worker.py"),
            "--config",
            str(config_path),
            "run",
        ],
        "WorkingDirectory": str(ROOT),
        "RunAtLoad": True,
        "KeepAlive": {"SuccessfulExit": False},
        "ThrottleInterval": 30,
        "EnvironmentVariables": {"PYTHON_DOTENV_DISABLED": "1"},
        "StandardOutPath": str(logs / "worker.stdout.log"),
        "StandardErrorPath": str(logs / "worker.stderr.log"),
    }
    write_private_bytes(path, plistlib.dumps(value))
    return {
        "state": "TEMPLATE_READY",
        "template": str(path),
        "installed": False,
        "started": False,
        "next_step": "Review the plist before a separately authorized per-user launchd installation.",
    }


async def execute(args: argparse.Namespace) -> dict[str, Any]:
    path = args.config.expanduser().absolute()
    if args.command == "configure":
        return configure(path, args.credential_path, args.state_dir)
    config = load_config(path)
    if args.command == "authorize":
        return await authorize(
            args.client_config.expanduser().absolute(),
            Path(config["credential_path"]),
            config["profile"],
        )
    bound = bindings()
    if args.command == "status":
        return local_status(config, bound, args.request_id)
    if args.command in {"reconcile", "release-held"}:
        _request_id(args.request_id)
    if args.command == "release-held" and not args.confirm:
        raise GradebookError("Releasing a held queue request requires --confirm.")
    google = google_client(config, bound)
    canvas = None
    try:
        store = Store(Path(config["state_dir"]))
        if args.command in {"doctor", "launch-agent", "once", "run"}:
            ready = await doctor(google, store, bound)
            if args.command == "doctor":
                return ready
            if args.command == "launch-agent":
                return launch_agent(args.output.expanduser().absolute(), path, config)
        canvas = canvas_client() if args.command in {"once", "run"} else None
        worker = RefreshWorker(google, canvas, store, bound, config["instance_id"])
        if args.command == "once":
            result = await worker.step()
            if result.get("state") == "IDLE":
                await worker.heartbeat()
            return dict(result)
        if args.command == "run":
            await run_loop(worker, config["poll_seconds"])
            return {"state": "STOPPED"}
        if args.command == "reconcile":
            return dict(await worker.reconcile(args.request_id))
        if args.command == "release-held":
            return dict(await worker.release_held(args.request_id))
        raise GradebookError("Unsupported worker command.")
    finally:
        await google.close()
        if canvas is not None:
            await canvas.close()


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    commands = result.add_subparsers(dest="command", required=True)
    setup = commands.add_parser(
        "configure", help="Create private config; do not start the worker"
    )
    setup.add_argument("--credential-path", type=Path)
    setup.add_argument("--state-dir", type=Path)
    auth = commands.add_parser(
        "authorize", help="Explicitly open browser for your own Desktop OAuth client"
    )
    auth.add_argument("--client-config", type=Path, required=True)
    commands.add_parser(
        "doctor", help="Read Google workbook and validate local baselines"
    )
    commands.add_parser("once", help="Process at most one queued refresh")
    commands.add_parser(
        "run", help="Run locally while this process is active; no installation"
    )
    status = commands.add_parser("status", help="Read aggregate local journal state")
    status.add_argument("--request-id")
    reconcile = commands.add_parser(
        "reconcile",
        help="Read back an existing uncertain operation; never resend grade data",
    )
    reconcile.add_argument("request_id")
    release = commands.add_parser(
        "release-held",
        help="Explicitly release a pre-send hold; never uncertain writes",
    )
    release.add_argument("request_id")
    release.add_argument("--confirm", action="store_true")
    launch = commands.add_parser(
        "launch-agent",
        help="After a successful doctor check, generate a plist without installing",
    )
    launch.add_argument("--output", type=Path, required=True)
    return result


def main(argv: list[str] | None = None) -> int:
    os.environ["PYTHON_DOTENV_DISABLED"] = "1"
    try:
        result = asyncio.run(execute(parser().parse_args(argv)))
        print(json.dumps(result, sort_keys=True))
        return 0
    except GradebookError as exc:
        print(
            json.dumps({"state": "HELD", "error": str(exc), "canvas_writes": 0}),
            file=sys.stderr,
        )
        return 1
    except KeyboardInterrupt:
        print(json.dumps({"state": "STOPPED", "durable_operations_retained": True}))
        return 0
    except Exception:
        print(
            json.dumps(
                {
                    "state": "HELD",
                    "error": "Worker setup or execution failed safely; inspect configuration and durable status.",
                    "canvas_writes": 0,
                }
            ),
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
