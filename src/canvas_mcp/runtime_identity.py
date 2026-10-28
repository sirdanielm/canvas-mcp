"""Unattached source prototype: bounded, self-reported selected-code identity.

No application imports, clients, caller-selected targets or loaded/disk equality
claim. The private core accepts fictional inputs for isolated tests only.
"""
from __future__ import annotations

import hashlib
import importlib.machinery
import math
import os
import re
import stat
import struct
import sys
import types
from pathlib import Path, PurePosixPath
from typing import Any

_TARGETS = (
    ("canvas_server", "canvas_mcp.server", "src/canvas_mcp/server.py", ("create_server",)),
    ("gradebook_server", "canvas_mcp.gradebook.server", "src/canvas_mcp/gradebook/server.py", ("create_server",)),
    ("gradebook_google", "canvas_mcp.gradebook.google", "src/canvas_mcp/gradebook/google.py", ("GoogleSheets", "read_workbook")),
)
# One version-specific SOFTWARE metadata binding; no discovery/search of sys.path.
_DIST_REL = ".venv/lib/python3.12/site-packages/canvas_mcp-1.16.0.dist-info/METADATA"
_MAX_SOURCE = 2_000_000
_CODE_FIELDS = ("co_argcount", "co_posonlyargcount", "co_kwonlyargcount", "co_nlocals",
                "co_stacksize", "co_flags", "co_code", "co_consts", "co_names",
                "co_varnames", "co_freevars", "co_cellvars", "co_name", "co_qualname",
                "co_exceptiontable")


class _Hold(Exception):
    """Fixed reason only; never include the underlying exception or input."""


def _identity(info: os.stat_result) -> tuple[int, ...]:
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns, info.st_nlink)


def _relative(value: str) -> tuple[str, ...]:
    if (type(value) is not str or not value or len(value) > 256 or "\\" in value
            or "\x00" in value or value.startswith("/") or "//" in value
            or any(p in ("", ".", "..") for p in value.split("/"))):
        raise _Hold("UNQUALIFIED_ORIGIN")
    parts = PurePosixPath(value).parts
    if len(parts) > 12:
        raise _Hold("UNQUALIFIED_ORIGIN")
    return parts


def _directories(path: Path) -> list[int]:
    """Walk every directory by descriptor, refusing symlink components."""
    if not path.is_absolute() or ".." in path.parts or len(path.parts) > 64:
        raise _Hold("UNQUALIFIED_ORIGIN")
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_NONBLOCK
    fds: list[int] = []
    try:
        fds.append(os.open(path.anchor, flags))
        for part in path.parts[1:]:
            fds.append(os.open(part, flags, dir_fd=fds[-1]))
        return fds
    except BaseException:
        for fd in reversed(fds):
            os.close(fd)
        raise


def _read_software(root: Path, relative: str, limit: int) -> bytes:
    parts = _relative(relative)
    target = root.joinpath(*parts)
    directories = _directories(target.parent)
    fd: int | None = None
    check: list[int] = []
    try:
        fd = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
                     dir_fd=directories[-1])
        before = os.fstat(fd)
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1 or not 0 < before.st_size <= limit:
            raise _Hold("SOFTWARE_FILE_UNQUALIFIED")
        chunks: list[bytes] = []
        total = 0
        while total <= limit:
            chunk = os.read(fd, min(65_536, limit + 1 - total))
            if not chunk:
                break
            total += len(chunk)
            chunks.append(chunk)
        after = os.fstat(fd)
        current = os.stat(parts[-1], dir_fd=directories[-1], follow_symlinks=False)
        check = _directories(target.parent)
        original_dirs = [(os.fstat(d).st_dev, os.fstat(d).st_ino) for d in directories]
        current_dirs = [(os.fstat(d).st_dev, os.fstat(d).st_ino) for d in check]
        if (total > limit or total != before.st_size or _identity(before) != _identity(after)
                or _identity(after) != _identity(current) or original_dirs != current_dirs):
            raise _Hold("SOFTWARE_CHANGED_DURING_READ")
        return b"".join(chunks)
    finally:
        if fd is not None:
            os.close(fd)
        for item in reversed(check + directories):
            os.close(item)


def _canonical(value: Any, budget: list[int], depth: int = 0) -> bytes:
    """Hash input only: exact builtin/code types, no repr/pickle/object hooks."""
    budget[1] -= 1
    if depth > 24 or budget[1] < 0:
        raise _Hold("CODE_LIMIT")
    kind = type(value)
    if value is None:
        tag, raw = b"n", b""
    elif value is Ellipsis:
        tag, raw = b"e", b""
    elif kind is bool:
        tag, raw = b"b", bytes([value])
    elif kind is int:
        if value.bit_length() > 4096:
            raise _Hold("CODE_LIMIT")
        tag, raw = b"i", bytes([value < 0]) + abs(value).to_bytes(max(1, (value.bit_length() + 7) // 8), "big")
    elif kind in (float, complex):
        numbers = (value,) if kind is float else (value.real, value.imag)
        if not all(math.isfinite(number) for number in numbers):
            raise _Hold("NONFINITE_CODE_CONSTANT")
        tag, raw = (b"f" if kind is float else b"j"), b"".join(struct.pack("!d", n) for n in numbers)
    elif kind in (str, bytes):
        if len(value) > 200_000:
            raise _Hold("CODE_LIMIT")
        tag, raw = (b"s", value.encode("utf-8")) if kind is str else (b"y", value)
    elif kind in (tuple, frozenset):
        if len(value) > 1024:
            raise _Hold("CODE_LIMIT")
        pieces = [_canonical(v, budget, depth + 1) for v in value]
        tag, raw = (b"t", b"".join(pieces)) if kind is tuple else (b"z", b"".join(sorted(pieces)))
    elif kind is types.CodeType:
        tag = b"c"
        raw = b"".join(_canonical(getattr(value, field), budget, depth + 1) for field in _CODE_FIELDS)
    else:
        raise _Hold("UNSUPPORTED_CODE_CONSTANT")
    budget[0] -= len(raw) + 5
    if budget[0] < 0:
        raise _Hold("CODE_LIMIT")
    return tag + len(raw).to_bytes(4, "big") + raw


def _code_fingerprint(code: types.CodeType) -> str:
    return hashlib.sha256(b"CANVAS_SELECTED_CODE_V1\x00" + _canonical(code, [400_000, 4096])).hexdigest()


def _declared_metadata(root: Path) -> dict[str, str]:
    try:
        raw = _read_software(root, _DIST_REL, 65_536).decode("utf-8")
        fields: dict[str, list[str]] = {"Name": [], "Version": []}
        for line in raw.splitlines():
            if not line:
                break
            for name in fields:
                prefix = name + ": "
                if line.startswith(prefix):
                    fields[name].append(line[len(prefix):])
        if fields != {"Name": ["canvas-mcp"], "Version": ["1.16.0"]}:
            raise _Hold("DECLARED_METADATA_MISMATCH")
        return {"status": "DECLARED_ON_DISK_ONLY", "name": "canvas-mcp", "version": "1.16.0",
                "origin": "registered_distribution_metadata"}
    except Exception:
        return {"status": "UNKNOWN", "reason": "DECLARED_METADATA_UNAVAILABLE_OR_UNQUALIFIED"}


def _target(root: Path, target: tuple[Any, ...], loaded: dict[str, Any]) -> dict[str, Any]:
    alias, module_name, relative, attributes = target
    unknown = {"target": alias, "status": "UNKNOWN"}
    try:
        module = loaded.get(module_name)  # Fixed keys only; never enumerate sys.modules.
        if module is None:
            return {**unknown, "reason": "MODULE_NOT_LOADED"}
        if type(module) is not types.ModuleType:
            raise _Hold("UNQUALIFIED_MODULE")
        namespace = types.ModuleType.__getattribute__(module, "__dict__")
        expected = str(root.joinpath(*_relative(relative)))
        spec = namespace.get("__spec__")
        if type(spec) is not importlib.machinery.ModuleSpec:
            raise _Hold("UNQUALIFIED_ORIGIN")
        file_origin, spec_origin = namespace.get("__file__"), vars(spec).get("origin")
        if (type(file_origin) is not str or type(spec_origin) is not str
                or file_origin != expected or spec_origin != expected):
            raise _Hold("UNQUALIFIED_ORIGIN")
        item = namespace.get(attributes[0])
        if len(attributes) == 2:
            if type(item) is not type:
                raise _Hold("UNQUALIFIED_CALLABLE")
            item = type.__getattribute__(item, "__dict__").get(attributes[1])
        if (type(item) is not types.FunctionType or type(item.__module__) is not str
                or item.__module__ != module_name):
            raise _Hold("UNQUALIFIED_CALLABLE")
        code = item.__code__
        if code.co_filename != expected:
            raise _Hold("UNQUALIFIED_CODE_ORIGIN")
        fingerprint = _code_fingerprint(code)
        raw = _read_software(root, relative, _MAX_SOURCE)
        again = namespace.get(attributes[0])
        if len(attributes) == 2:
            again = type.__getattribute__(again, "__dict__").get(attributes[1]) if type(again) is type else None
        file_after, spec_after = namespace.get("__file__"), namespace.get("__spec__")
        origin_after = vars(spec_after).get("origin") if type(spec_after) is importlib.machinery.ModuleSpec else None
        if (loaded.get(module_name) is not module or again is not item or item.__code__ is not code
                or type(file_after) is not str or file_after != expected or spec_after is not spec
                or type(origin_after) is not str or origin_after != expected):
            raise _Hold("LOADED_TARGET_CHANGED_DURING_MEASUREMENT")
        return {"target": alias, "status": "OBSERVED_SELF_REPORT", "origin": relative,
                "disk_source_sha256": hashlib.sha256(raw).hexdigest(),
                "loaded_code_sha256": fingerprint, "code_format": "CANVAS_SELECTED_CODE_V1",
                "disk_loaded_equivalence": "NOT_ATTESTED"}
    except _Hold as error:
        return {**unknown, "reason": str(error)}
    except Exception:
        return {**unknown, "reason": "MEASUREMENT_UNAVAILABLE"}


def _collect(root: Path, targets: tuple[Any, ...], loaded: dict[str, Any]) -> dict[str, Any]:
    """Private fictional-test seam. No service caller supplies these arguments."""
    try:
        if type(targets) is not tuple or len(targets) > 3 or type(loaded) is not dict:
            raise _Hold("INVALID_INTERNAL_REGISTRY")
        for entry in targets:
            if type(entry) is not tuple or len(entry) != 4:
                raise _Hold("INVALID_INTERNAL_REGISTRY")
            alias, module_name, relative, attrs = entry
            if (type(alias) is not str or re.fullmatch(r"[a-z][a-z0-9_]{0,47}", alias) is None
                    or type(module_name) is not str or len(module_name) > 128
                    or re.fullmatch(r"[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*", module_name) is None
                    or type(attrs) is not tuple or not 1 <= len(attrs) <= 2
                    or any(type(v) is not str or not v.isidentifier() or len(v) > 64 for v in attrs)):
                raise _Hold("INVALID_INTERNAL_REGISTRY")
            _relative(relative)
        return {"schema": "CANVAS_RUNTIME_IDENTITY_V1", "attestation": "SELF_REPORT_ONLY",
                "declared_distribution": _declared_metadata(root),
                "targets": [_target(root, t, loaded) for t in targets],
                "limitations": ["SELECTED_FUNCTION_CODE_ONLY", "NO_GLOBALS_CLOSURE_DEFAULTS_OR_CLIENT_STATE",
                                "NO_DISK_LOADED_EQUIVALENCE", "NO_THIRD_PARTY_ATTESTATION_OR_READINESS"]}
    except Exception:
        return {"schema": "CANVAS_RUNTIME_IDENTITY_V1", "status": "UNKNOWN", "reason": "INVALID_INTERNAL_REGISTRY"}


def runtime_identity() -> dict[str, Any]:
    """Future service-owned additive field; zero caller parameters or live calls."""
    try:
        if type(__file__) is not str:
            raise _Hold("UNQUALIFIED_ORIGIN")
        return _collect(Path(__file__).absolute().parents[2], _TARGETS, sys.modules)
    except Exception:
        return {"schema": "CANVAS_RUNTIME_IDENTITY_V1", "status": "UNKNOWN", "reason": "UNQUALIFIED_ORIGIN"}
