"""Fictional private-policy startup and owner routing; no installed bindings."""

import hashlib
from pathlib import Path

import pytest

from canvas_mcp.gradebook.client import GradebookError
from canvas_mcp.gradebook.owner_config import (
    load_owner_policy,
    private_owner_adapter_supported,
)


def adapter(tmp_path: Path) -> tuple[Path, str]:
    path = tmp_path / "owner.py"
    path.write_text(
        "from canvas_mcp.gradebook.owner_config import OwnerPolicy\n"
        "def scope(course, review, items):\n    return course == '12'\n"
        "def protected(course, items):\n    return course == '12' and bool(items)\n"
        "def owner(publisher):\n    return None\n"
        "def create_owner_policy():\n    return OwnerPolicy(scope, protected, owner)\n"
    , encoding="utf-8")
    path.chmod(0o600)
    return path, hashlib.sha256(path.read_bytes()).hexdigest()


def test_absent_adapter_holds_score_owner_without_enabling_comments() -> None:
    options = load_owner_policy().server_options()
    assert options["source_score_scope"]("12", None, []) is True
    assert options["enable_qualified_comments"] is False
    assert "enable_push" not in options and "enable_comments" not in options
    with pytest.raises(GradebookError, match="policy is required"):
        options["unit1_score_handler_factory"](object())


@pytest.mark.skipif(not private_owner_adapter_supported(), reason="POSIX private adapter file protection unavailable")
def test_explicit_pinned_adapter_keeps_private_scope_in_callables(tmp_path: Path) -> None:
    path, pin = adapter(tmp_path)
    policy = load_owner_policy(path, pin)
    assert policy.source_score_scope("12", None, []) is True
    assert policy.source_score_scope("13", None, []) is False
    assert policy.protected_score_scope("12", [{}]) is True
    assert policy.server_options()["unit1_pair_score_handler_factory"] is None


@pytest.mark.parametrize("mutation", ["hash", "mode", "symlink", "missing_pin"])
@pytest.mark.skipif(not private_owner_adapter_supported(), reason="POSIX private adapter file protection unavailable")
def test_invalid_adapter_is_held_before_source_execution(tmp_path: Path, mutation: str) -> None:
    path, pin = adapter(tmp_path)
    if mutation == "hash":
        pin = "0" * 64
    elif mutation == "mode":
        path.chmod(0o644)
    elif mutation == "symlink":
        link = tmp_path / "linked.py"
        link.symlink_to(path)
        path = link
    with pytest.raises(GradebookError):
        load_owner_policy(path, None if mutation == "missing_pin" else pin)










@pytest.mark.skipif(not private_owner_adapter_supported(), reason="POSIX private adapter file protection unavailable")
def test_adapter_exception_never_discloses_private_values(tmp_path: Path) -> None:
    path = tmp_path / "owner.py"
    sentinel = "fictional student row sentinel"
    path.write_text(
        "from canvas_mcp.gradebook.client import GradebookError\n"
        "def create_owner_policy():\n    raise GradebookError(" + repr(sentinel) + ")\n"
    , encoding="utf-8")
    path.chmod(0o600)
    with pytest.raises(GradebookError) as error:
        load_owner_policy(path, hashlib.sha256(path.read_bytes()).hexdigest())
    assert sentinel not in str(error.value)
    assert str(error.value) == "Private owner adapter initialization failed."






def test_unsupported_private_file_capability_holds_before_filesystem_access(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import canvas_mcp.gradebook.owner_config as config

    monkeypatch.setattr(config, "private_owner_adapter_supported", lambda: False)
    def no_open(*args, **kwargs):
        pytest.fail("Unsupported platform must not open private adapter source")
    monkeypatch.setattr(config.os, "open", no_open)
    with pytest.raises(GradebookError, match="require POSIX"):
        load_owner_policy(tmp_path / "not-opened.py", "0" * 64)
    assert load_owner_policy().server_options()["enable_qualified_comments"] is False
