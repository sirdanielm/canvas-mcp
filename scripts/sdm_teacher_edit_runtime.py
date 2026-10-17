"""Pinned, check-only admission for the private local EDIT application runtime.

The trusted host retains Admission and passes it as runtime_check when composing
the existing authenticated application. This file starts no server or client.
Check mode blocks conventional socket/DNS APIs; reviewed code hashes remain
the trust boundary. This is not a security sandbox for malicious pinned code.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import os
import re
import stat
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

CONTRACT = "LOCALGRASS_EDIT_IMMUTABLE_RUNTIME_V1"
HASH = re.compile(r"[a-f0-9]{64}\Z")


class RuntimeHold(ValueError):
    pass


def need(value: Any) -> None:
    if not value:
        raise RuntimeHold("IMMUTABLE_BRIDGE_RUNTIME_CHANGED")


def identity(value: os.stat_result) -> tuple[int, ...]:
    return (
        value.st_dev,
        value.st_ino,
        value.st_uid,
        value.st_gid,
        value.st_mode,
        value.st_nlink,
        value.st_size,
        value.st_mtime_ns,
        value.st_ctime_ns,
    )


def read_checked(path: Path, expected: str, maximum: int = 32 * 1024 * 1024) -> bytes:
    path = Path(path)
    need(
        path.is_absolute()
        and ".." not in path.parts
        and type(expected) is str
        and HASH.fullmatch(expected)
        and not any(p.is_symlink() for p in (path, *path.parents))
    )
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(descriptor, "rb") as stream:
        before = os.fstat(stream.fileno())
        need(
            stat.S_ISREG(before.st_mode)
            and before.st_uid == os.getuid()
            and before.st_nlink == 1
            and 0 <= before.st_size <= maximum
        )
        raw = stream.read(maximum + 1)
        after = os.fstat(stream.fileno())
    need(
        len(raw) == before.st_size
        and identity(before) == identity(after) == identity(path.lstat())
        and hashlib.sha256(raw).hexdigest() == expected
    )
    return raw


def unique_pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
    result = {}
    for key, value in items:
        need(key not in result)
        result[key] = value
    return result


class Admission:
    """Synchronous full code/Python/external-reader check, including reentry."""

    def __init__(self, manifest_path: Path, expected_sha256: str) -> None:
        self.path = Path(manifest_path)
        self.expected = expected_sha256
        self.root = self.path.parent
        self.__call__()

    def __call__(self) -> None:
        raw = read_checked(self.path, self.expected, 2 * 1024 * 1024)
        manifest = json.loads(raw, object_pairs_hook=unique_pairs)
        need(
            type(manifest) is dict
            and set(manifest)
            == {
                "contract",
                "python",
                "packages",
                "external",
                "support_files",
                "source_basis",
                "created_at_utc",
            }
        )
        need(manifest["contract"] == CONTRACT)
        python = manifest["python"]
        need(
            set(python) == {"path", "sha256"}
            and Path(sys.executable).resolve() == Path(python["path"])
        )
        read_checked(Path(python["path"]), python["sha256"], 256 * 1024 * 1024)
        packages = manifest["packages"]
        need(type(packages) is dict and set(packages) == {"canvas", "domain"})
        for name, prefix in (("canvas", "canvas_mcp"), ("domain", "localgrass")):
            files = packages[name]
            need(type(files) is dict and 1 <= len(files) <= 300)
            base = self.root / name
            for relative, expected in files.items():
                need(
                    type(relative) is str
                    and re.fullmatch(prefix + r"(?:/[a-zA-Z0-9_]+)+\.py", relative)
                )
                read_checked(base / relative, expected)
            observed = set()
            for number, item in enumerate(base.rglob("*")):
                need(number < 1000 and not item.is_symlink())
                if item.is_file():
                    observed.add(str(item.relative_to(base)))
            need(observed == set(files))
        external = manifest["external"]
        need(
            type(external) is dict
            and set(external)
            == {
                "domain_reader",
                "domain_rules",
                "shared_pin_package",
                "shared_pin_module",
            }
        )
        for item in external.values():
            need(type(item) is dict and set(item) == {"path", "sha256"})
            read_checked(Path(item["path"]), item["sha256"])
        support = manifest["support_files"]
        need(type(support) is dict and set(support) == {"bootstrap.py"})
        read_checked(self.root / "bootstrap.py", support["bootstrap.py"])
        allowed = {"manifest.json", "bootstrap.py"}
        for name in ("canvas", "domain"):
            allowed.update(name + "/" + relative for relative in packages[name])
        directories: set[str] = set()
        for relative in allowed:
            directories.update(
                str(parent) for parent in Path(relative).parents if str(parent) != "."
            )
        observed_files: set[str] = set()
        observed_directories: set[str] = set()
        for number, item in enumerate(self.root.rglob("*")):
            need(number < 2000 and not item.is_symlink())
            mode = item.lstat().st_mode
            relative = str(item.relative_to(self.root))
            if stat.S_ISREG(mode):
                observed_files.add(relative)
            elif stat.S_ISDIR(mode):
                observed_directories.add(relative)
            else:
                need(False)
        need(observed_files == allowed and observed_directories == directories)
        unused = self.root / "unused-bytecode"
        need(not unused.exists() and not unused.is_symlink())
        sys.pycache_prefix = str(unused)
        sys.dont_write_bytecode = True
        return None


def load_application(
    manifest_path: Path, expected_sha256: str
) -> tuple[ModuleType, ModuleType, ModuleType, Admission]:
    """Verify before imports; return the existing factory and retained guard."""
    admission = Admission(manifest_path, expected_sha256)
    root = admission.root
    need(
        not any(
            name == "canvas_mcp"
            or name.startswith("canvas_mcp.")
            or name == "localgrass"
            or name.startswith("localgrass.")
            for name in sys.modules
        )
    )
    sys.path[:0] = [str(root / "canvas"), str(root / "domain")]
    factory = importlib.import_module("canvas_mcp.gradebook.localgrass_application")
    controller = importlib.import_module("localgrass.teacher_edit_application")
    review = importlib.import_module("localgrass.teacher_review")
    for name, module in tuple(sys.modules.items()):
        if name == "canvas_mcp" or name.startswith("canvas_mcp."):
            base = root / "canvas"
        elif name == "localgrass" or name.startswith("localgrass."):
            base = root / "domain"
        else:
            continue
        location = Path(getattr(module, "__file__", "")).resolve()
        need(location.is_relative_to(base))
    admission()
    return factory, controller, review, admission


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest-sha256", required=True)
    parser.add_argument("--check", action="store_true", required=True)
    args = parser.parse_args(argv)
    try:
        # Check mode imports concrete code with all outgoing socket connections
        # refused. It creates no clients, database, account or teacher session.
        import socket

        attempts = []

        def blocked(*args: Any, **kwargs: Any) -> None:
            attempts.append(True)
            raise RuntimeHold("CHECK_MODE_NETWORK_DISABLED")

        for name in (
            "connect",
            "connect_ex",
            "send",
            "sendall",
            "sendto",
            "sendmsg",
            "sendfile",
            "bind",
            "listen",
        ):
            if hasattr(socket.socket, name):
                setattr(socket.socket, name, blocked)
        for name in (
            "getaddrinfo",
            "gethostbyname",
            "gethostbyname_ex",
            "gethostbyaddr",
        ):
            setattr(socket, name, blocked)
        load_application(Path(__file__).parent / "manifest.json", args.manifest_sha256)
        need(not attempts)
        print(
            json.dumps(
                {
                    "status": "INSTALLED_CODE_BINDINGS_VERIFIED",
                    "staging_enabled": False,
                    "real_case_checked": False,
                    "services_started": 0,
                    "network_attempts": 0,
                    "Canvas_writes": 0,
                    "paid_calls": 0,
                }
            )
        )
        return 0
    except Exception:
        print(
            json.dumps(
                {
                    "status": "HELD",
                    "reason": "IMMUTABLE_BRIDGE_RUNTIME_CHANGED",
                    "staging_enabled": False,
                    "Canvas_writes": 0,
                    "paid_calls": 0,
                }
            )
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
