"""CI dependencies and the explicit boundary of local POSIX-only tooling."""

from pathlib import Path

import pytest
import yaml
from platform_contract import (
    SOURCE_REQUIREMENTS,
    TEST_REQUIREMENTS,
    dependency_graph,
    dependency_requirements,
    literal_imports,
    windows_test_requirements,
)

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("job", ["test", "test-windows"])
def test_test_jobs_install_both_declared_local_extras(job: str) -> None:
    workflow = yaml.safe_load((ROOT / ".github/workflows/canvas-mcp-testing.yml").read_text(encoding="utf-8"))
    steps = workflow["jobs"][job]["steps"]
    install = next(step["run"] for step in steps if step.get("name") == "Install dependencies")
    assert '".[local-exports,local-keychain]"' in install



def test_only_declared_dependency_closure_requires_platform_skip() -> None:
    graph = {
        "portable": {"data"}, "data": set(), "fixture": {"posix"},
        "suite": {"fixture"}, "posix": {"suite"}, "unrelated": set(),
    }
    declared = {"posix": "POSIX lock required"}
    assert dependency_requirements("suite", graph, declared) == ("POSIX lock required",)
    assert dependency_requirements("portable", graph, declared) == ()
    assert dependency_requirements("unrelated", graph, declared) == ()


def test_relative_imports_are_resolved_but_lazy_bodies_do_not_hide_pure_data(tmp_path: Path) -> None:
    module = tmp_path / "consumer.py"
    module.write_text("from . import worker\nfrom .model import digest\ndef later():\n    import unrelated\n", encoding="utf-8")
    imports = literal_imports(module, "canvas_mcp.gradebook.consumer")
    assert "canvas_mcp.gradebook.worker" in imports
    assert "canvas_mcp.gradebook.model" in imports
    assert "unrelated" not in imports


def test_real_general_mcp_and_pure_gradebook_pin_modules_remain_collected() -> None:
    requirements = windows_test_requirements()
    for name in [
        "tests/tools/test_courses.py", "tests/core/test_client.py", "tests/test_http_transport.py",
        "tests/test_gradebook.py", "tests/test_gradebook_policy_identifiers.py",
        "tests/test_gradebook_workbook.py", "tests/test_pseudonymize_export.py",
        "tests/test_gradebook_percent_rounding.py", "tests/test_gradebook_refresh.py",
    ]:
        assert requirements[(ROOT / name).resolve()] == (), name
    assert requirements[(ROOT / "tests/test_comment_clock_preflight.py").resolve()]
    assert requirements[(ROOT / "tests/test_gradebook_worker.py").resolve()]
    assert requirements[(ROOT / "tests/test_sdm_canvas_launcher.py").resolve()]


def test_every_declared_requirement_has_real_source_and_only_declared_closure_is_used() -> None:
    index, graph = dependency_graph(ROOT)
    declared = {**SOURCE_REQUIREMENTS, **TEST_REQUIREMENTS}
    assert declared.keys() <= index.keys()
    requirements = windows_test_requirements()
    for name, path in index.items():
        if path.resolve() in requirements:
            assert requirements[path.resolve()] == dependency_requirements(name, graph, declared)
    for name in ("canvas_mcp.gradebook.ledger", "canvas_mcp.gradebook.worker", "canvas_mcp.gradebook.diagnostics"):
        assert "fcntl" in literal_imports(index[name], name)


def test_platform_collector_reports_the_skip_and_never_imports_unsupported_module(request) -> None:
    import conftest

    path = ROOT / "tests/test_gradebook_worker.py"
    assert conftest._module_for_platform(path, request.session, "linux") is None
    module = conftest._module_for_platform(path, request.session, "win32")
    assert isinstance(module, conftest.UnsupportedWindowsLocalModule)
    with pytest.raises(pytest.skip.Exception, match="Windows local capability unavailable:.*POSIX flock"):
        module.collect()
    assert conftest._module_for_platform(ROOT / "tests/tools/test_courses.py", request.session, "win32") is None


def test_private_primary_registry_declares_its_actual_platform_requirement(request) -> None:
    import conftest

    path = ROOT / "tests/test_canvas_primary_protection.py"
    requirements = windows_test_requirements()
    assert requirements[path.resolve()]
    module = conftest._module_for_platform(path, request.session, "win32")
    assert isinstance(module, conftest.UnsupportedWindowsLocalModule)
    with pytest.raises(pytest.skip.Exception, match="Windows local capability unavailable:.*O_NOFOLLOW"):
        module.collect()
    # The portable missing-capability checks in this module must still execute.
    assert requirements[Path(__file__).resolve()] == ()


@pytest.mark.parametrize("missing", ["O_NOFOLLOW", "O_NONBLOCK", "getuid"])
def test_primary_registry_missing_primitive_holds_before_open(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, missing: str
) -> None:
    from types import SimpleNamespace

    from canvas_mcp.gradebook import canvas_primary_protection as protection
    from canvas_mcp.gradebook.client import GradebookError

    def forbidden_open(*args, **kwargs):
        raise AssertionError("Private registry opened without its platform protection")

    capabilities = SimpleNamespace(
        O_RDONLY=0, O_NOFOLLOW=1, O_NONBLOCK=2, getuid=lambda: 1, open=forbidden_open
    )
    delattr(capabilities, missing)
    monkeypatch.setattr(protection, "os", capabilities)
    with pytest.raises(GradebookError, match="^PROTECTION_REGISTRY_HELD$"):
        protection.read_protection_registry(tmp_path / "unopened.json", "a" * 64)
