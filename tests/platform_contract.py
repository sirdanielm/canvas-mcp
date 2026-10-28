"""Declared platform requirements for the fork's separate local operations.

This does not emulate POSIX locks or grant Windows access to private files. Only
actual import dependencies of the declared local components affect collection.
Pure model/PIN tests and the general Canvas MCP remain in the Windows suite.
"""

from __future__ import annotations

import ast
import importlib.util
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE_REQUIREMENTS = {
    "canvas_mcp.gradebook.ledger": "POSIX flock and owner-only push ledger",
    "canvas_mcp.gradebook.worker": "POSIX flock and owner-only refresh journal",
    "canvas_mcp.gradebook.diagnostics": "POSIX flock for private operation telemetry",
    "canvas_mcp.gradebook.google_authorize": "POSIX O_NOFOLLOW/getuid/fchmod credential protection",
    "canvas_mcp.mirror.core": "POSIX owner-only private course mirror files",
    "canvas_mcp.mirror.export_materializer": "POSIX owner-only export files and directory fsync",
}
# These suites load scripts dynamically or own private filesystem fixtures.
# Their importers share those fixtures, so the requirement follows that closure.
TEST_REQUIREMENTS = {
    "test_gradebook_native": "POSIX private Store fixtures with directory fsync",
    "test_gradebook_capture": "POSIX private Store capture fixtures with directory fsync",
    "test_gradebook_scoped_review": "POSIX private Store review artifacts with directory fsync",
    "test_sdm_canvas_launcher": "macOS Keychain launcher and owner-only connection files",
    "test_gradebook_get_controls_install": "macOS local connection installer and private backups",
    "test_teacher_edit_runtime": "POSIX O_NOFOLLOW/getuid immutable local runtime",
    "test_gradebook_worker_cli": "dynamically loaded POSIX refresh worker and private configuration",
}


def module_index(root: Path) -> dict[str, Path]:
    result = {}
    for directory in (root / "src", root / "tests", root / "scripts"):
        for path in directory.rglob("*.py"):
            parts = path.relative_to(directory).with_suffix("").parts
            if parts[-1] == "__init__":
                parts = parts[:-1]
            if parts:
                result[".".join(parts)] = path
    return result


def literal_imports(path: Path, module: str) -> set[str]:
    """Only imports evaluated at module/class definition, excluding lazy bodies."""
    result: set[str] = set()
    package = module if path.name == "__init__.py" else module.rpartition(".")[0]

    class Imports(ast.NodeVisitor):
        def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
            pass

        def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
            pass

        def visit_Import(self, node: ast.Import) -> None:
            result.update(alias.name for alias in node.names)

        def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
            name = node.module or ""
            if node.level:
                name = importlib.util.resolve_name("." * node.level + name, package)
            if name:
                result.add(name)
                result.update(name + "." + alias.name for alias in node.names if alias.name != "*")

    Imports().visit(ast.parse(path.read_text(encoding="utf-8")))
    return result


def dependency_graph(root: Path) -> tuple[dict[str, Path], dict[str, set[str]]]:
    index = module_index(root)
    graph = {name: literal_imports(path, name) & index.keys() for name, path in index.items()}
    return index, graph


def dependency_requirements(module: str, graph: dict[str, set[str]], declared: dict[str, str]) -> tuple[str, ...]:
    visited: set[str] = set()
    pending = [module]
    requirements = set()
    while pending:
        name = pending.pop()
        if name in visited:
            continue
        visited.add(name)
        if name in declared:
            requirements.add(declared[name])
        pending.extend(graph.get(name, ()))
    return tuple(sorted(requirements))


@lru_cache(maxsize=1)
def windows_test_requirements(root: Path = ROOT) -> dict[Path, tuple[str, ...]]:
    index, graph = dependency_graph(root)
    declared = {**SOURCE_REQUIREMENTS, **TEST_REQUIREMENTS}
    return {
        path.resolve(): dependency_requirements(name, graph, declared)
        for name, path in index.items()
        if path.is_relative_to(root / "tests") and path.name.startswith("test_")
    }
