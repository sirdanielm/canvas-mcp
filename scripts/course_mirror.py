"""GET-only course mirror. All other subcommands are offline; no apply command."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


def main() -> int:
    from canvas_mcp.mirror.core import (
        COURSES,
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
        "get", help="GET content of the three approved published courses"
    )
    get.add_argument(
        "--courses", nargs="+", choices=list(COURSES), default=list(COURSES)
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
    args = parser.parse_args()
    os.umask(0o077)
    try:
        if args.command == "get":
            from sdm_canvas_launcher import SERVICE, keychain, read_connection

            if read_connection() != ORIGIN:
                raise MirrorError("CANVAS_ORIGIN_MISMATCH")
            token = keychain().get_password(SERVICE, ORIGIN)
            if not token:
                raise MirrorError("CANVAS_CREDENTIAL_UNAVAILABLE")

            async def run() -> dict:
                client = GetClient(token)
                try:
                    path = await capture(args.root, client, args.courses)
                    return {
                        "snapshot_path": str(path),
                        "requests": client.requests,
                        **audit(path),
                    }
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
        else:
            result = check_proposal(args.snapshot, args.proposal)
        if getattr(args, "output", None) and args.command != "stage-description":
            private_write(args.output, result)
        if args.command == "links":
            result = {k: v for k, v in result.items() if k != "links"}
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
