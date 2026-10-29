"""GET-only course mirror and file retrieval; local drafts have no apply command."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


def _write_asset_plan(
    output: Path, roots: tuple[Path, ...], report: dict[str, Any]
) -> None:
    """Write one new private report through no-follow directory descriptors."""
    from canvas_mcp.mirror.asset_plan import _secure_open_available
    from canvas_mcp.mirror.core import MirrorError, encoded

    if not _secure_open_available():
        raise MirrorError("ASSET_PLAN_SECURE_OPEN_UNAVAILABLE")
    absolute = output.absolute()
    if ".." in output.parts or any(
        path.is_symlink() for path in (absolute, *absolute.parents)
    ):
        raise MirrorError("ASSET_PLAN_OUTPUT_HELD")
    if absolute.exists() or any(
        absolute.is_relative_to(root.absolute())
        or absolute.resolve().is_relative_to(root.resolve())
        for root in roots
    ):
        raise MirrorError("ASSET_PLAN_OUTPUT_HELD")
    directory = os.open(absolute.anchor, os.O_RDONLY | os.O_DIRECTORY)
    try:
        for component in absolute.parts[1:-1]:
            try:
                os.mkdir(component, mode=0o700, dir_fd=directory)
            except FileExistsError:
                # The no-follow directory open below validates existing entries.
                pass
            child = os.open(
                component,
                os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                dir_fd=directory,
            )
            os.close(directory)
            directory = child
        descriptor = os.open(
            absolute.name,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
            0o600,
            dir_fd=directory,
        )
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(encoded(report))
            stream.flush()
            os.fsync(stream.fileno())
        os.fsync(directory)
    except OSError as exc:
        raise MirrorError("ASSET_PLAN_OUTPUT_HELD") from exc
    finally:
        os.close(directory)


def main() -> int:
    from canvas_mcp.mirror.core import (
        CAPTURE_COURSES,
        COURSES,
        DEFAULT_CAPTURE_SCOPE,
        ORIGIN,
        GetClient,
        MirrorError,
        audit,
        capture,
        check_proposal,
        diff,
        link_inventory,
        private_write,
        resources_check,
        stage_description,
        status,
        verify,
    )

    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    get = sub.add_parser(
        "get", help="GET content of explicitly selected approved course identities"
    )
    get.add_argument(
        "--courses",
        nargs="+",
        choices=list(CAPTURE_COURSES),
        default=DEFAULT_CAPTURE_SCOPE,
    )
    get.add_argument(
        "--root", type=Path, default=ROOT / "local_gradebooks/course_mirror"
    )
    for name in ("verify", "audit"):
        item = sub.add_parser(name)
        item.add_argument("snapshot", type=Path)
        item.add_argument("--output", type=Path)
    delta = sub.add_parser("diff")
    delta.add_argument("before", type=Path)
    delta.add_argument("after", type=Path)
    delta.add_argument("--output", type=Path)
    resources = sub.add_parser("resources-check")
    resources.add_argument("archive", type=Path)
    listing = sub.add_parser("status")
    listing.add_argument(
        "--root", type=Path, default=ROOT / "local_gradebooks/course_mirror"
    )
    links = sub.add_parser(
        "links", help="Save a private offline link map; print only counts"
    )
    links.add_argument("snapshot", type=Path)
    links.add_argument("--output", type=Path, required=True)
    stage = sub.add_parser("stage-description")
    stage.add_argument("snapshot", type=Path)
    stage.add_argument("course", choices=list(COURSES))
    stage.add_argument("assignment_id")
    stage.add_argument("html", type=Path)
    stage.add_argument("output", type=Path)
    check = sub.add_parser("check-proposal")
    check.add_argument("snapshot", type=Path)
    check.add_argument("proposal", type=Path)
    repo_create = sub.add_parser(
        "repo-create", help="Create a private editable derivative of a valid snapshot"
    )
    repo_create.add_argument("snapshot", type=Path)
    repo_create.add_argument("destination", type=Path)
    repo_delta = sub.add_parser(
        "repo-diff", help="Save an exact offline draft diff; never applies edits"
    )
    repo_delta.add_argument("repository", type=Path)
    repo_delta.add_argument("--output", type=Path, required=True)
    files_get = sub.add_parser(
        "files-get", help="Download the exact captured Canvas file inventory"
    )
    files_get.add_argument("snapshot", type=Path)
    files_get.add_argument("destination", type=Path)
    assets_verify = sub.add_parser(
        "assets-verify", help="Verify file-byte receipts offline"
    )
    assets_verify.add_argument("destination", type=Path)
    assets_verify.add_argument("snapshot", type=Path)
    assets_plan = sub.add_parser(
        "assets-plan",
        help="Plan offline from complete pinned captures; never downloads",
    )
    assets_plan.add_argument("baseline_snapshot", type=Path)
    assets_plan.add_argument("baseline_assets", type=Path)
    assets_plan.add_argument("current_snapshot", type=Path)
    assets_plan.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    os.umask(0o077)
    try:
        if args.command in {"get", "files-get"}:
            from sdm_canvas_launcher import SERVICE, keychain, read_connection

            if read_connection() != ORIGIN:
                raise MirrorError("CANVAS_ORIGIN_MISMATCH")
            token = keychain().get_password(SERVICE, ORIGIN)
            if not token:
                raise MirrorError("CANVAS_CREDENTIAL_UNAVAILABLE")

            async def run() -> dict:
                client = GetClient(token)
                try:
                    if args.command == "get":
                        path = await capture(args.root, client, args.courses)
                        return {
                            "snapshot_path": str(path),
                            "requests": client.requests,
                            **audit(path),
                        }
                    from canvas_mcp.mirror.assets import download_files

                    return await download_files(args.snapshot, args.destination, client)
                finally:
                    await client.close()

            result = asyncio.run(run())
        elif args.command == "verify":
            result = verify(args.snapshot)
        elif args.command == "audit":
            result = audit(args.snapshot)
        elif args.command == "diff":
            result = diff(args.before, args.after)
        elif args.command == "resources-check":
            result = resources_check(args.archive)
        elif args.command == "status":
            result = status(args.root)
        elif args.command == "links":
            result = link_inventory(args.snapshot)
        elif args.command == "stage-description":
            result = stage_description(
                args.snapshot,
                args.course,
                args.assignment_id,
                args.html.read_text(),
                args.output,
            )
        elif args.command == "repo-create":
            from canvas_mcp.mirror.repo import materialize

            result = materialize(args.snapshot, args.destination)
        elif args.command == "repo-diff":
            from canvas_mcp.mirror.repo import repo_diff

            result = repo_diff(args.repository)
        elif args.command == "assets-verify":
            from canvas_mcp.mirror.assets import verify_assets

            result = verify_assets(args.destination, args.snapshot)
        elif args.command == "assets-plan":
            from canvas_mcp.mirror.asset_plan import plan_asset_refresh

            result = plan_asset_refresh(
                baseline_snapshot=args.baseline_snapshot,
                baseline_assets=args.baseline_assets,
                current_snapshot=args.current_snapshot,
            )
            _write_asset_plan(
                args.output,
                (args.baseline_snapshot, args.baseline_assets, args.current_snapshot),
                result,
            )
        else:
            result = check_proposal(args.snapshot, args.proposal)
        if getattr(args, "output", None) and args.command not in {
            "stage-description",
            "assets-plan",
        }:
            private_write(args.output, result)
        if args.command == "assets-plan":
            result = {
                key: result[key]
                for key in (
                    "ok",
                    "status",
                    "counts",
                    "bytes",
                    "source_admission",
                    "download_authorized",
                    "network_requests",
                    "canvas_writes",
                    "google_writes",
                )
            }
        if args.command == "links":
            result = {k: v for k, v in result.items() if k != "links"}
        if args.command == "repo-diff":
            result = {
                "status": result["status"],
                "changes": len(result["changes"]),
                "holds": result["holds"],
                "canvas_writes": 0,
                "output": str(args.output),
            }
        print(json.dumps(result, indent=2))
        return (
            0
            if result.get("ok", True)
            and result.get("status") != "CONFLICT_REVIEW_REQUIRED"
            else 2
        )
    except MirrorError as exc:
        print(
            json.dumps({"status": "STOPPED", "reason": str(exc), "canvas_writes": 0}),
            file=sys.stderr,
        )
    except Exception:
        print(
            json.dumps(
                {
                    "status": "STOPPED",
                    "reason": "LOCAL_OR_CONNECTION_FAILURE",
                    "canvas_writes": 0,
                }
            ),
            file=sys.stderr,
        )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
