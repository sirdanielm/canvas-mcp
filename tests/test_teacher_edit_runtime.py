"""Independent immutable-runtime checks using fictional code and no network."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

RUNTIME_SOURCE = Path(
    os.environ.get(
        "TEACHER_EDIT_RUNTIME_SOURCE",
        str(
            Path(__file__).resolve().parents[1] / "scripts/sdm_teacher_edit_runtime.py"
        ),
    )
)
RUNTIME_BYTES = RUNTIME_SOURCE.read_bytes()
RUNTIME_SHA256 = hashlib.sha256(RUNTIME_BYTES).hexdigest()


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def encoded(value: object) -> bytes:
    return (json.dumps(value, sort_keys=True, indent=2) + "\n").encode()


@pytest.fixture
def runtime(tmp_path):
    release = tmp_path / "release"
    release.mkdir()
    bootstrap = release / "bootstrap.py"
    bootstrap.write_bytes(RUNTIME_BYTES)
    marker = tmp_path / "package-executed"
    objects = tmp_path / "object-created"
    code = {
        "canvas": {
            "canvas_mcp/__init__.py": (
                "from pathlib import Path\n"
                f"Path({str(marker)!r}).write_text('package imported')\n"
            ),
            "canvas_mcp/gradebook/__init__.py": "# Fictional package.\n",
            "canvas_mcp/gradebook/localgrass_application.py": (
                "from pathlib import Path\n"
                "def build_application(*args, **kwargs):\n"
                f"    Path({str(objects)!r}).write_text('unexpected construction')\n"
                "    raise AssertionError('Check must not construct an application')\n"
            ),
        },
        "domain": {
            "localgrass/__init__.py": "# Fictional package.\n",
            "localgrass/teacher_edit_application.py": (
                "def create_controller(*args, **kwargs):\n"
                "    raise AssertionError('Check must not construct a controller')\n"
            ),
            "localgrass/teacher_review.py": (
                "class TeacherReview:\n"
                "    def __init__(self, *args, **kwargs):\n"
                "        raise AssertionError('Check must not construct a review')\n"
            ),
        },
    }
    packages = {}
    for package, files in code.items():
        packages[package] = {}
        for name, content in files.items():
            path = release / package / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content)
            packages[package][name] = sha(path)
    external = {}
    for name in (
        "domain_reader",
        "domain_rules",
        "shared_pin_package",
        "shared_pin_module",
    ):
        path = tmp_path / "external" / name
        path.parent.mkdir(exist_ok=True)
        path.write_text("# Fictional pinned external input.\n")
        external[name] = {"path": str(path), "sha256": sha(path)}
    manifest = {
        "contract": "LOCALGRASS_EDIT_IMMUTABLE_RUNTIME_V1",
        "python": {
            "path": str(Path(sys.executable).resolve()),
            "sha256": sha(Path(sys.executable).resolve()),
        },
        "packages": packages,
        "external": external,
        "support_files": {"bootstrap.py": sha(bootstrap)},
        "source_basis": {"fixture": "fictional-code-only"},
        "created_at_utc": "2026-10-17T00:00:00Z",
    }
    manifest_path = release / "manifest.json"
    manifest_path.write_bytes(encoded(manifest))
    return {
        "release": release,
        "bootstrap": bootstrap,
        "manifest": manifest,
        "path": manifest_path,
        "hash": sha(manifest_path),
        "marker": marker,
        "objects": objects,
    }


def check(runtime, *, driver=None):
    if driver is None:
        command = [
            sys.executable,
            "-I",
            "-B",
            str(runtime["bootstrap"]),
            "--manifest-sha256",
            runtime["hash"],
            "--check",
        ]
    else:
        command = [
            sys.executable,
            "-I",
            "-B",
            "-c",
            driver,
            str(runtime["bootstrap"]),
            runtime["hash"],
        ]
    return subprocess.run(command, capture_output=True, text=True, timeout=30)


def held_before_packages(runtime):
    result = check(runtime)
    assert result.returncode == 2, result.stdout + result.stderr
    assert json.loads(result.stdout)["status"] == "HELD"
    assert not runtime["marker"].exists()
    assert not runtime["objects"].exists()


def reseal(runtime):
    runtime["path"].write_bytes(encoded(runtime["manifest"]))
    runtime["hash"] = sha(runtime["path"])


def test_fresh_subprocess_imports_pinned_code_without_creating_application(runtime):
    result = check(runtime)
    assert result.returncode == 0, result.stdout + result.stderr
    assert json.loads(result.stdout) == {
        "status": "INSTALLED_CODE_BINDINGS_VERIFIED",
        "staging_enabled": False,
        "real_case_checked": False,
        "services_started": 0,
        "network_attempts": 0,
        "Canvas_writes": 0,
        "paid_calls": 0,
    }
    assert runtime["marker"].read_text() == "package imported"
    assert not runtime["objects"].exists()
    assert not (runtime["release"] / "unused-bytecode").exists()
    assert not list(runtime["release"].rglob("*.pyc"))


def test_exact_pinned_empty_python_package_file_is_valid(runtime):
    empty = runtime["release"] / "canvas/canvas_mcp/empty/__init__.py"
    empty.parent.mkdir()
    empty.write_bytes(b"")
    runtime["manifest"]["packages"]["canvas"]["canvas_mcp/empty/__init__.py"] = sha(
        empty
    )
    reseal(runtime)
    result = check(runtime)
    assert result.returncode == 0, result.stdout + result.stderr
    assert json.loads(result.stdout)["status"] == "INSTALLED_CODE_BINDINGS_VERIFIED"


@pytest.mark.parametrize(
    "kind",
    [
        "canvas",
        "domain",
        "reader",
        "rules",
        "pin_package",
        "pin_module",
        "manifest",
        "support",
    ],
)
def test_changed_code_or_authority_pin_holds_before_any_package_execution(
    runtime, kind
):
    if kind == "canvas":
        path = runtime["release"] / "canvas/canvas_mcp/__init__.py"
    elif kind == "domain":
        path = runtime["release"] / "domain/localgrass/teacher_review.py"
    elif kind in {"manifest", "support"}:
        path = runtime["path"] if kind == "manifest" else runtime["bootstrap"]
    else:
        name = {
            "reader": "domain_reader",
            "rules": "domain_rules",
            "pin_package": "shared_pin_package",
            "pin_module": "shared_pin_module",
        }[kind]
        path = Path(runtime["manifest"]["external"][name]["path"])
    path.write_bytes(path.read_bytes() + b"\n# independent changed bytes\n")
    held_before_packages(runtime)


def test_wrong_python_pin_holds_before_packages(runtime):
    runtime["manifest"]["python"]["sha256"] = "0" * 64
    reseal(runtime)
    held_before_packages(runtime)


def test_duplicate_manifest_keys_hold_before_packages(runtime):
    raw = (
        runtime["path"]
        .read_bytes()
        .replace(
            b'"created_at_utc":', b'"created_at_utc": "duplicate", "created_at_utc":', 1
        )
    )
    runtime["path"].write_bytes(raw)
    runtime["hash"] = sha(runtime["path"])
    held_before_packages(runtime)


def test_relative_external_authority_path_holds_before_packages(runtime):
    runtime["manifest"]["external"]["shared_pin_module"]["path"] = (
        "relative/student_pin.py"
    )
    reseal(runtime)
    held_before_packages(runtime)


@pytest.mark.parametrize(
    "relative",
    [
        "canvas/canvas_mcp/unregistered.py",
        "domain/localgrass/notes.txt",
        "canvas/canvas_mcp/__pycache__/__init__.pyc",
        "unregistered.py",
        "__pycache__/bootstrap.pyc",
    ],
)
def test_unknown_file_or_bytecode_holds_before_packages(runtime, relative):
    path = runtime["release"] / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"unregistered fictional bytes")
    held_before_packages(runtime)


@pytest.mark.parametrize(
    "kind", ["file_symlink", "ancestor_symlink", "hardlink", "manifest_symlink"]
)
def test_unsafe_bound_paths_hold_before_packages(runtime, tmp_path, kind):
    target = runtime["release"] / "domain/localgrass/teacher_review.py"
    if kind == "ancestor_symlink":
        folder = target.parent
        moved = tmp_path / "moved-package"
        folder.rename(moved)
        folder.symlink_to(moved, target_is_directory=True)
    else:
        if kind == "manifest_symlink":
            target = runtime["path"]
        retained = tmp_path / "retained-file"
        retained.write_bytes(target.read_bytes())
        target.unlink()
        if kind == "hardlink":
            os.link(retained, target)
        else:
            target.symlink_to(retained)
    held_before_packages(runtime)


def test_retained_admission_rechecks_external_state_before_reentry(runtime):
    driver = r"""
import pathlib, runpy, sys
loaded = runpy.run_path(sys.argv[1], run_name="independent_probe")
guard = loaded["Admission"](pathlib.Path(sys.argv[1]).parent / "manifest.json", sys.argv[2])
guard()
import json
manifest = json.loads((pathlib.Path(sys.argv[1]).parent / "manifest.json").read_text())
path = pathlib.Path(manifest["external"]["domain_reader"]["path"])
path.write_bytes(path.read_bytes() + b"changed during idle interval")
try:
    guard()
except loaded["RuntimeHold"]:
    print("REENTRY_HELD")
else:
    raise AssertionError("Retained guard accepted changed canonical reader")
"""
    result = check(runtime, driver=driver)
    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.strip() == "REENTRY_HELD"
    assert not runtime["marker"].exists()


@pytest.mark.parametrize(
    "api",
    [
        "connect",
        "connect_ex",
        "send",
        "sendall",
        "sendto",
        "sendmsg",
        "sendfile",
        "bind",
        "listen",
        "getaddrinfo",
    ],
)
def test_check_refuses_even_caught_network_attempts_without_any_real_syscall(
    runtime, api
):
    init = runtime["release"] / "canvas/canvas_mcp/__init__.py"
    calls = {
        "connect": "socket.socket().connect(('127.0.0.1', 1))",
        "connect_ex": "socket.socket().connect_ex(('127.0.0.1', 1))",
        "send": "socket.socket().send(b'fictional')",
        "sendall": "socket.socket().sendall(b'fictional')",
        "sendto": "socket.socket(socket.AF_INET, socket.SOCK_DGRAM).sendto(b'fictional', ('127.0.0.1', 1))",
        "sendmsg": "socket.socket().sendmsg([b'fictional'])",
        "sendfile": "socket.socket().sendfile(io.BytesIO(b'fictional'))",
        "bind": "socket.socket().bind(('127.0.0.1', 0))",
        "listen": "socket.socket().listen(1)",
        "getaddrinfo": "socket.getaddrinfo('fiction.invalid', 1)",
    }
    init.write_text(
        "import io, socket\ntry:\n    " + calls[api] + "\nexcept Exception:\n    pass\n"
    )
    runtime["manifest"]["packages"]["canvas"]["canvas_mcp/__init__.py"] = sha(init)
    reseal(runtime)
    driver = r"""
import runpy, socket, sys
def intercept(*args, **kwargs):
    raise AssertionError("Independent sentinel blocked syscall before OS/network")
for name in ("connect", "connect_ex", "send", "sendall", "sendto", "sendmsg", "sendfile", "bind", "listen"):
    if hasattr(socket.socket, name):
        setattr(socket.socket, name, intercept)
socket.getaddrinfo = intercept
loaded = runpy.run_path(sys.argv[1], run_name="independent_probe")
raise SystemExit(loaded["main"](["--manifest-sha256", sys.argv[2], "--check"]))
"""
    result = check(runtime, driver=driver)
    assert result.returncode == 2, result.stdout + result.stderr
    assert json.loads(result.stdout)["status"] == "HELD"
    assert not runtime["objects"].exists()


def test_existing_application_module_is_refused_before_new_package_execution(runtime):
    driver = r"""
import pathlib, runpy, sys, types
loaded = runpy.run_path(sys.argv[1], run_name="independent_probe")
sys.modules["canvas_mcp"] = types.ModuleType("canvas_mcp")
try:
    loaded["load_application"](pathlib.Path(sys.argv[1]).parent / "manifest.json", sys.argv[2])
except loaded["RuntimeHold"]:
    print("PREIMPORTED_APPLICATION_HELD")
else:
    raise AssertionError("Existing foreign module was accepted")
"""
    result = check(runtime, driver=driver)
    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.strip() == "PREIMPORTED_APPLICATION_HELD"
    assert not runtime["marker"].exists()
