"""Launch the gradebook service; grade and comment writes have separate opt-ins."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

from sdm_canvas_launcher import SERVICE, keychain, read_connection

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
COURSES = {"core": "363308", "advanced": "374070"}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", choices=list(COURSES))
    parser.add_argument(
        "--call",
        choices=[
            "get_canvas_gradebook",
            "preview_gradebook_changes",
            "prepare_gradebook_refresh",
            "verify_gradebook_refresh",
            "prepare_gradebook_push",
            "get_gradebook_push_status",
            "reconcile_gradebook_push",
            "confirm_gradebook_push",
            "prepare_gradebook_comment_push",
            "reconcile_gradebook_comment_push",
            "confirm_gradebook_comment_push",
            "request_gradebook_get_refresh",
            "get_gradebook_get_refresh_status",
            "review_gradebook_edits",
            "select_gradebook_review_batch",
        ],
    )
    parser.add_argument(
        "--arguments", default="{}", help="JSON tool arguments; no student rows"
    )
    parser.add_argument("--state-dir", type=Path, default=ROOT / "local_gradebooks")
    parser.add_argument(
        "--enable-push",
        action="store_true",
        help="Register the separately confirmed Canvas write tool",
    )
    parser.add_argument(
        "--enable-comments",
        action="store_true",
        help="Register the separately confirmed comment-only tool; does not enable grades",
    )
    parser.add_argument(
        "--comment-approval-seconds", type=int, default=600,
        help="Future comment preview approval window (600–1800 seconds); score windows stay 600.",
    )
    args = parser.parse_args()
    if not 600 <= args.comment_approval_seconds <= 1800:
        parser.error("--comment-approval-seconds must be between 600 and 1800")
    # Prevent unrelated .env files from enabling features or logging identities.
    os.environ["PYTHON_DOTENV_DISABLED"] = "1"
    from canvas_mcp.gradebook.client import GradebookClient, GradebookError
    from canvas_mcp.gradebook.model import summary
    from canvas_mcp.gradebook.server import create_server
    from canvas_mcp.gradebook.store import Store

    try:
        origin = read_connection()
        if origin != "https://fcps.instructure.com":
            raise GradebookError(
                "Configured class IDs belong to fcps.instructure.com; Canvas origin differs."
            )
        token = keychain().get_password(SERVICE, origin)
        if not token:
            raise GradebookError("Canvas Keychain credential is unavailable.")
        client = GradebookClient(origin, token)
        store = Store(args.state_dir)
        if args.snapshot:

            async def fetch() -> None:
                try:
                    snapshot = await client.snapshot(COURSES[args.snapshot])
                    artifact_id, path = store.save("snapshot", snapshot)
                    print(
                        json.dumps(
                            {
                                **summary(snapshot),
                                "snapshot_id": artifact_id,
                                "local_file": str(path),
                                "canvas_writes": 0,
                            }
                        )
                    )
                finally:
                    await client.close()

            asyncio.run(fetch())
        else:
            bindings = json.loads(
                (ROOT / "config/sdm-gradebook-workbooks.json").read_text()
            )
            # Optional local controller; a missing worker configuration does not
            # disable the existing standalone Canvas snapshot/review tools.
            get_control = None
            from sdm_gradebook_worker import DEFAULT_CONFIG, google_client, load_config
            if DEFAULT_CONFIG.exists():
                config = load_config(DEFAULT_CONFIG)
                if Path(config["state_dir"]).resolve() != store.root.resolve():
                    raise GradebookError("Worker and MCP gradebook stores differ.")
                from canvas_mcp.gradebook.get_refresh_control import GetRefreshControl
                get_control = GetRefreshControl(
                    lambda: google_client(config, bindings), store, bindings,
                    config["instance_id"],
                )
            server = create_server(
                client,
                store,
                COURSES,
                bindings,
                enable_push=args.enable_push,
                enable_comments=args.enable_comments,
                get_refresh_control=get_control,
                comment_approval_seconds=args.comment_approval_seconds,
            )
            if args.call:
                from fastmcp import Client

                async def call() -> None:
                    try:
                        async with Client(server) as mcp:
                            result = await mcp.call_tool(
                                args.call, json.loads(args.arguments)
                            )
                            print(json.dumps(result.data))
                    finally:
                        await client.close()

                asyncio.run(call())
            else:
                server.run()
        return 0
    except GradebookError as exc:
        print(str(exc), file=sys.stderr)
    except Exception:
        print(
            "Gradebook startup failed. Check saved Canvas connection and Keychain access.",
            file=sys.stderr,
        )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
