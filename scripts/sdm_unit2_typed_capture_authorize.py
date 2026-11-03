"""Explicit optional read-only profile setup, never invoked by capture or import."""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

from canvas_mcp.gradebook.client import GradebookError
from canvas_mcp.gradebook.google_authorize import authorize


async def run(args: argparse.Namespace) -> dict:
    if args.authorize_read_only_profile is not True:
        raise GradebookError("Explicit read-only setup invocation is required.")
    # Existing reviewed setup owns PKCE/state/loopback and exclusive600 output;
    # defaults and the existing mirror credential/profile are unchanged.
    return await authorize(
        Path(args.client_config),
        Path(args.new_credential),
        profile="unit2-typed-capture",
        read_only=True,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--authorize-read-only-profile", action="store_true")
    parser.add_argument("--client-config", required=True)
    parser.add_argument("--new-credential", required=True)
    try:
        print(json.dumps(asyncio.run(run(parser.parse_args()))))
    except (GradebookError, OSError, ValueError):
        print(
            json.dumps(
                {"state": "READ_ONLY_SETUP_HELD", "credential_or_token_returned": False}
            )
        )
        raise SystemExit(2) from None


if __name__ == "__main__":
    main()
