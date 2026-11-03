"""Fictional offline process tests, with no duplicated feedback policy."""

import hashlib
import shutil
import subprocess
from copy import deepcopy

import pytest

from canvas_mcp.gradebook.model import GradebookError
from canvas_mcp.gradebook.unit2_feedback import derive_projection


def runtime(tmp_path, source):
    node = shutil.which("node")
    if not node:
        pytest.skip("Explicit Node runtime unavailable")
    script = tmp_path / "formatter.mjs"
    script.write_text(source, encoding="utf-8")
    return {
        "formatter_path": script,
        "formatter_sha256": hashlib.sha256(script.read_bytes()).hexdigest(),
        "node_path": node,
    }


def test_driver_pinned_bytes_clean_environment_and_immutable_inputs(
    tmp_path, monkeypatch
):
    args = runtime(
        tmp_path, "export function formatFeedback(i,t){return i.projection;}"
    )
    data = {"projection": {"fictional": True}}
    monkeypatch.setenv("CANVAS_API_TOKEN", "FICTIONAL_SECRET_MUST_NOT_PROPAGATE")
    monkeypatch.setenv("NODE_OPTIONS", "--invalid-inherited-option")
    original = subprocess.run

    def inspect_run(*values, **kwargs):
        assert set(kwargs["env"]) == {"PATH", "LANG", "LC_ALL", "TZ"}
        assert kwargs["shell"] is False and kwargs["timeout"] <= 5
        assert args["formatter_path"].read_text(encoding="utf-8") not in values[0][-1]
        return original(*values, **kwargs)

    monkeypatch.setattr(subprocess, "run", inspect_run)
    before = deepcopy(data)
    assert derive_projection(data, deepcopy(data), **args) == {"fictional": True}
    assert data == before


def test_drift_and_hash_change_rejected_before_process(tmp_path, monkeypatch):
    args = runtime(tmp_path, "export function formatFeedback(){return {};}")

    def forbidden(*values, **kwargs):
        pytest.fail("Process must not run after drift")

    monkeypatch.setattr(subprocess, "run", forbidden)
    with pytest.raises(GradebookError):
        derive_projection({"revision": 1}, {"revision": 2}, **args)
    args["formatter_path"].write_text("throw new Error('CHANGED');", encoding="utf-8")
    with pytest.raises(GradebookError, match="hash"):
        derive_projection({}, {}, **args)


@pytest.mark.parametrize(
    "failure", [subprocess.TimeoutExpired("node", 5), OSError("FICTIONAL_SECRET")]
)
def test_runtime_failures_sanitized(tmp_path, monkeypatch, failure):
    args = runtime(tmp_path, "export function formatFeedback(){return {};}")

    def fail(*values, **kwargs):
        raise failure

    monkeypatch.setattr(subprocess, "run", fail)
    with pytest.raises(GradebookError) as exc:
        derive_projection({}, {}, **args)
    assert "FICTIONAL_SECRET" not in str(exc.value)
    assert exc.value.__suppress_context__ is True


def test_missing_export_and_raw_stderr_fail_safely(tmp_path):
    args = runtime(
        tmp_path,
        "export function formatFeedback(){throw new Error('FICTIONAL_SECRET');}",
    )
    with pytest.raises(GradebookError) as exc:
        derive_projection({}, {}, **args)
    assert "FICTIONAL_SECRET" not in str(exc.value)


@pytest.mark.parametrize("timeout", [0, 6, True, float("nan")])
def test_timeout_bounds(tmp_path, timeout):
    args = runtime(tmp_path, "export function formatFeedback(){return {};}")
    with pytest.raises(GradebookError):
        derive_projection({}, {}, timeout_seconds=timeout, **args)
