"""Render an offline, disabled comment-only proposal for canvas-gradebook.

This is a review companion to install_gradebook_connection.py, not an installer.
It consumes a caller-supplied TOML snapshot and explicit binding metadata. It
never reads a configuration path, environment, owner adapter, or credential;
never writes a file; and never starts a launcher, MCP client, or server. Source
and runtime hashes are validated metadata, not a claim of live verification.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import posixpath
import re
import sys
import tomllib
from typing import Any

CONNECTION_NAME = "canvas-gradebook"
READ_TOOLS = (
    "get_canvas_gradebook",
    "preview_gradebook_changes",
    "get_gradebook_push_status",
)
COMMENT_REVIEW_TOOLS = (
    "prepare_gradebook_comment_push",
    "reconcile_gradebook_comment_push",
)
COMMENT_CONFIRM_TOOL = "confirm_gradebook_comment_push"
_BINDING_FIELDS = {
    "source_root",
    "source_revision",
    "launcher_path",
    "launcher_sha256",
    "runtime_executable",
    "runtime_sha256",
    "runtime_python_version",
    "state_dir",
    "owner_policy_id",
    "owner_adapter",
    "owner_adapter_sha256",
}
_ENTRY_FIELDS = {
    "command",
    "args",
    "cwd",
    "enabled",
    "required",
    "startup_timeout_sec",
    "tool_timeout_sec",
    "enabled_tools",
}


def _path(value: Any, label: str) -> str:
    if (
        not isinstance(value, str)
        or not value.startswith("/")
        or value == "/"
        or value.startswith("//")
        or posixpath.normpath(value) != value
        or any(character in value for character in ("\x00", "\n", "\r", "\\"))
    ):
        raise ValueError(f"{label} must be an explicit normalized absolute path.")
    return value


def _hash(value: Any, label: str, length: int = 64) -> str:
    if (
        not isinstance(value, str)
        or re.fullmatch(rf"[0-9a-f]{{{length}}}", value) is None
    ):
        raise ValueError(f"{label} must be an explicit lowercase hexadecimal pin.")
    return value


def _binding(value: Any, *, proposed: bool) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != _BINDING_FIELDS:
        raise ValueError(
            "Each binding must supply exactly the documented metadata fields."
        )
    result = dict(value)
    for field in ("source_root", "launcher_path", "runtime_executable", "state_dir"):
        _path(result[field], field)
    _hash(result["source_revision"], "source_revision", 40)
    _hash(result["launcher_sha256"], "launcher_sha256")
    _hash(result["runtime_sha256"], "runtime_sha256")
    version = result["runtime_python_version"]
    if not isinstance(version, str) or re.fullmatch(r"3\.\d+\.\d+", version) is None:
        raise ValueError("runtime_python_version must be an explicit Python 3 version.")
    if int(version.split(".")[1]) < 11:
        raise ValueError("The proposed tooling requires Python >=3.11.")
    root = result["source_root"]
    if root == "/" or result["runtime_executable"] != root + "/.venv/bin/python":
        raise ValueError(
            "Runtime must retain the explicitly pinned source-root .venv binding."
        )
    if not result["launcher_path"].startswith(root + "/"):
        raise ValueError("Launcher belongs to a different source root.")
    if proposed:
        if result["launcher_path"] != root + "/scripts/sdm_gradebook_launcher.py":
            raise ValueError(
                "Proposal must reuse the existing gradebook publisher launcher."
            )
        _path(result["owner_adapter"], "owner_adapter")
        _hash(result["owner_adapter_sha256"], "owner_adapter_sha256")
        owner_id = result["owner_policy_id"]
        if (
            not isinstance(owner_id, str)
            or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}", owner_id) is None
        ):
            raise ValueError("An explicit opaque owner_policy_id is required.")
    elif any(
        result[field] is not None
        for field in ("owner_policy_id", "owner_adapter", "owner_adapter_sha256")
    ):
        raise ValueError(
            "The recognized read-only entry must explicitly have no owner adapter."
        )
    return result


def _current_entry(config_bytes: bytes, observed: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(config_bytes, bytes):
        raise ValueError("Supply the offline configuration snapshot as bytes.")
    try:
        parsed = tomllib.loads(config_bytes.decode("utf-8"))
    except (UnicodeDecodeError, tomllib.TOMLDecodeError):
        raise ValueError(
            "The offline configuration snapshot is not valid UTF-8 TOML."
        ) from None
    servers = parsed.get("mcp_servers")
    if not isinstance(servers, dict):
        raise ValueError("The offline snapshot has no recognized MCP server table.")
    entry = servers.get(CONNECTION_NAME)
    if not isinstance(entry, dict) or set(entry) - _ENTRY_FIELDS:
        raise ValueError(
            "The existing connection has an unrecognized configuration shape."
        )
    if (
        entry.get("command") != observed["runtime_executable"]
        or entry.get("cwd") != observed["source_root"]
    ):
        raise ValueError(
            "Current connection differs from the explicit source/runtime metadata."
        )
    tools = entry.get("enabled_tools")
    if (
        not isinstance(tools, list)
        or any(not isinstance(tool, str) for tool in tools)
        or len(tools) != len(READ_TOOLS)
        or set(tools) != set(READ_TOOLS)
    ):
        raise ValueError(
            "Only the exact existing three-tool read-only connection is recognized."
        )
    args = entry.get("args")
    if not isinstance(args, list) or not args or args[0] != observed["launcher_path"]:
        raise ValueError("Current launcher differs from the explicit source pin.")
    basename = posixpath.basename(observed["launcher_path"])
    if basename not in ("mcp_main_read_only.py", "sdm_gradebook_launcher.py"):
        raise ValueError("The current read-only launcher is not recognized.")
    # Like the existing installer, refuse unrecognized launcher arguments.
    # This helper deliberately cannot upgrade the read-only wrapper itself.
    remaining = args[1:]
    if remaining[:1] == ["--read-only"]:
        remaining = remaining[1:]
    elif basename == "sdm_gradebook_launcher.py":
        raise ValueError("The current publisher launcher must retain --read-only.")
    if remaining == ["--state-dir", observed["state_dir"]]:
        remaining = []
    elif not remaining:
        # Agreement between two metadata objects does not establish the
        # current store. Only the maintained publisher's source-owned default
        # is known; an unrelated wrapper must bind its state explicitly.
        if basename != "sdm_gradebook_launcher.py":
            raise ValueError(
                "Unknown wrapper state default is held; require explicit --state-dir."
            )
        if observed["state_dir"] != observed["source_root"] + "/local_gradebooks":
            raise ValueError(
                "Current launcher default state directory differs from the metadata."
            )
    if remaining:
        raise ValueError(
            "Unknown or writer-enabling current launcher arguments are refused."
        )
    for field in ("enabled", "required"):
        if field in entry and not isinstance(entry[field], bool):
            raise ValueError("Current connection boolean metadata is invalid.")
    for field in ("startup_timeout_sec", "tool_timeout_sec"):
        if field in entry and (
            type(entry[field]) is not int or not 1 <= entry[field] <= 3600
        ):
            raise ValueError("Current connection timeout metadata is invalid.")
    return entry


def stage_comment_connection(
    config_bytes: bytes,
    metadata: dict[str, Any],
    *,
    include_confirm_for_review: bool = False,
) -> dict[str, Any]:
    """Return a disabled proposal; leave the supplied snapshot byte-for-byte intact.

    Required metadata: schema_version=1, connection_name="canvas-gradebook",
    observed and proposed dictionaries with _BINDING_FIELDS. The observed owner
    fields must be explicit nulls. Proposed owner fields are required. Adoption
    must preserve the source root, revision, runtime, and durable state path.
    Current args must bind that state path explicitly, except for the maintained
    publisher's exact source_root/local_gradebooks default. Unknown wrapper
    defaults are held even when observed/proposed metadata agree.
    """
    if (
        not isinstance(metadata, dict)
        or set(metadata)
        != {"schema_version", "connection_name", "observed", "proposed"}
        or type(metadata["schema_version"]) is not int
        or metadata["schema_version"] != 1
        or metadata["connection_name"] != CONNECTION_NAME
    ):
        raise ValueError(
            "Explicit versioned canvas-gradebook binding metadata is required."
        )
    if type(include_confirm_for_review) is not bool:
        raise ValueError("include_confirm_for_review must be a boolean review choice.")
    observed = _binding(metadata["observed"], proposed=False)
    proposed = _binding(metadata["proposed"], proposed=True)
    entry = _current_entry(config_bytes, observed)
    for field in (
        "source_root",
        "source_revision",
        "runtime_executable",
        "runtime_sha256",
        "runtime_python_version",
        "state_dir",
    ):
        if observed[field] != proposed[field]:
            raise ValueError(
                "Source, runtime, or durable state repointing requires a separate owner review."
            )
    enabled_tools = [*READ_TOOLS, *COMMENT_REVIEW_TOOLS]
    if include_confirm_for_review:
        enabled_tools.append(COMMENT_CONFIRM_TOOL)
    desired = {
        "command": proposed["runtime_executable"],
        "args": [
            proposed["launcher_path"],
            "--state-dir",
            proposed["state_dir"],
            "--enable-comments",
            "--owner-adapter",
            proposed["owner_adapter"],
            "--owner-adapter-sha256",
            proposed["owner_adapter_sha256"],
        ],
        "cwd": proposed["source_root"],
        "enabled": False,
        "required": entry.get("required", False),
        "startup_timeout_sec": entry.get("startup_timeout_sec", 20),
        "tool_timeout_sec": entry.get("tool_timeout_sec", 300),
        "enabled_tools": enabled_tools,
    }
    snippet = (
        "\n".join(
            [f"[mcp_servers.{CONNECTION_NAME}]"]
            + [f"{key} = {json.dumps(value)}" for key, value in desired.items()]
        )
        + "\n"
    )
    if tomllib.loads(snippet)["mcp_servers"][CONNECTION_NAME] != desired:
        raise ValueError("The disabled proposal did not round-trip.")
    return {
        "schema_version": 1,
        "status": "OFFLINE_OWNER_ADOPTION_REQUIRED",
        "connection_name": CONNECTION_NAME,
        "current_snapshot_sha256": hashlib.sha256(config_bytes).hexdigest(),
        "binding_metadata_only": True,
        "observed": observed,
        "proposed": proposed,
        "proposed_entry": desired,
        "toml_snippet": snippet,
        "confirm_exposed_for_review": include_confirm_for_review,
        "live_enabled": False,
        "score_enablement": False,
        "config_writes": 0,
        "runtime_starts": 0,
        "existing_installer_adoption_supported": False,
        "adoption_requirements": [
            "Reuse canvas-gradebook; do not create a parallel runtime or client.",
            "Owner-controlled supported adoption must review the existing read-only binding; no blind overwrite.",
            "Revalidate all metadata against the intended current source, runtime, private owner policy and durable state before adoption.",
            "Review --enable-comments separately from client tool exposure; the snippet stays disabled.",
            "Expose confirm_gradebook_comment_push only through explicit supported owner adoption and retain platform approval gates.",
            "Reconcile prior operation history and independently verify every current target and comment before any future send.",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--include-confirm-for-review",
        action="store_true",
        help="Include confirm in the disabled snippet; grants no adoption or send authority.",
    )
    args = parser.parse_args()
    try:
        request = json.load(sys.stdin)
        if not isinstance(request, dict) or set(request) != {
            "config_snapshot_toml",
            "metadata",
        }:
            raise ValueError(
                "Supply only config_snapshot_toml and metadata through stdin."
            )
        snapshot = request["config_snapshot_toml"]
        if not isinstance(snapshot, str):
            raise ValueError("config_snapshot_toml must be a caller-supplied string.")
        result = stage_comment_connection(
            snapshot.encode("utf-8"),
            request["metadata"],
            include_confirm_for_review=args.include_confirm_for_review,
        )
    except (ValueError, TypeError, KeyError):
        # Avoid echoing supplied configuration values, paths, or private data.
        print(
            "Offline staging refused; review the supplied snapshot and binding metadata.",
            file=sys.stderr,
        )
        return 2
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
