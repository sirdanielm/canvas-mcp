"""Actual offline CLI over wholly fictional private export files."""

import copy
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from test_u3_feedback_staging import stage_inputs as stage_inputs

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from stage_u3_feedback_export import stage_export

from canvas_mcp.gradebook.client import GradebookError

private_store_required = pytest.mark.skipif(
    os.name != "posix", reason="POSIX owner-only Store and directory fsync"
)


def export_bytes(cases):
    return json.dumps(
        {"contract": "CANVAS_U3_FEEDBACK_STAGING_INPUT_V1", "cases": cases}
    ).encode()


def test_every_case_retained_in_source_order_including_invalid(stage_inputs):
    bad = copy.deepcopy(stage_inputs)
    bad["findings"]["record_hash"] = "changed"
    raw = export_bytes([stage_inputs, bad, stage_inputs])
    result = stage_export(raw, hashlib.sha256(raw).hexdigest())
    assert result["source_case_count"] == 3
    assert [v["source_position"] for v in result["staged"]] == [0, 1, 2]
    assert result["staged"][1]["stage"]["retained_input"] == bad
    assert result["staged"][1]["stage"]["holds"] == ["U3_FINDINGS_BINDING"]
    assert all(v["stage"]["publication_allowed"] is False for v in result["staged"])
    assert result["canvas_writes"] == 0


@pytest.mark.parametrize("identity_field", ["course_id", "assignment_id", "user_id"])
def test_large_decimal_identity_retains_valid_neighbor_cases(stage_inputs, identity_field):
    old_limit = sys.get_int_max_str_digits()
    try:
        sys.set_int_max_str_digits(4300)
        bad = copy.deepcopy(stage_inputs)
        bad["target"] = {
            "origin": "https://canvas.example", "course_id": "11",
            "assignment_id": "22", "user_id": "33", "attempt": 1,
            "submitted_at": "2026-01-01T00:00:00Z",
        }
        bad["target"][identity_field] = "9" * 5000
        raw = export_bytes([stage_inputs, bad, stage_inputs])
        result = stage_export(raw, hashlib.sha256(raw).hexdigest())
    finally:
        sys.set_int_max_str_digits(old_limit)
    assert [row["source_position"] for row in result["staged"]] == [0, 1, 2]
    assert result["staged"][1]["stage"]["retained_input"] == bad
    assert result["staged"][1]["stage"]["holds"] == ["U3_EXACT_TARGET"]
    assert result["staged"][0]["stage"] == result["staged"][2]["stage"]
    assert all(not row["stage"]["publication_allowed"] for row in result["staged"])
    assert all(row["stage"]["publisher_envelope"] is None for row in result["staged"])


@pytest.mark.parametrize(
    "raw",
    [
        b'{"contract":"CANVAS_U3_FEEDBACK_STAGING_INPUT_V1","contract":"other","cases":[]}',
        b'{"x":NaN}',
        b'{"x":Infinity}',
        b'{"x":-Infinity}',
        b'{"x":1e10000}',
        b'{"x":-1e10000}',
        b"\xff",
        b"[]",
    ],
)
def test_ambiguous_or_invalid_json_rejects_without_normalization(raw):
    with pytest.raises(GradebookError):
        stage_export(raw, hashlib.sha256(raw).hexdigest())


def test_changed_export_or_unbounded_input_refuses(stage_inputs):
    raw = export_bytes([stage_inputs])
    with pytest.raises(GradebookError, match="BYTES_CHANGED"):
        stage_export(raw, "0" * 64)
    with pytest.raises(GradebookError, match="TOO_LARGE"):
        stage_export(b" " * 5_000_001, "0" * 64)


@private_store_required
def test_numeric_overflow_in_case_does_not_crash_or_partially_stage(
    stage_inputs, tmp_path
):
    raw = export_bytes([stage_inputs, stage_inputs]).replace(
        b'"state": "HELD"', b'"extra":1e10000,"state":"HELD"', 1
    )
    with pytest.raises(GradebookError, match="U3_EXPORT_JSON_REQUIRED"):
        stage_export(raw, hashlib.sha256(raw).hexdigest())
    output = tmp_path / "overflow"
    result = run_cli(raw, output)
    assert result.returncode == 1 and b"Traceback" not in result.stderr
    assert json.loads(result.stdout)["canvas_writes"] == 0
    assert not list(output.iterdir())


def run_cli(raw, output):
    script = Path(__file__).resolve().parents[1] / "scripts/stage_u3_feedback_export.py"
    return subprocess.run(
        [
            sys.executable,
            str(script),
            "--expected-sha256",
            hashlib.sha256(raw).hexdigest(),
            "--output-dir",
            str(output),
        ],
        input=raw,
        capture_output=True,
        timeout=20,
    )


@private_store_required
def test_cli_private_full_readback_safe_stdout_and_immutable_reuse(
    stage_inputs, tmp_path
):
    raw = export_bytes([stage_inputs])
    output = tmp_path / "private-stage"
    first = run_cli(raw, output)
    assert first.returncode == 0, first.stderr
    summary = json.loads(first.stdout)
    assert summary["state"] == "STAGED_UNAPPROVED" and summary["cases"] == 1
    assert summary["canvas_writes"] == summary["sheets_writes"] == 0
    assert b"fictional-packet" not in first.stdout and b"recordHash" not in first.stdout
    artifact = Path(summary["private_artifact"])
    retained = artifact.read_bytes()
    assert (
        json.loads(retained)["staged"][0]["stage"]["retained"]["envelope"]
        == stage_inputs["envelope"]
    )
    assert artifact.stat().st_mode & 0o777 == 0o600
    assert output.stat().st_mode & 0o777 == 0o700
    second = run_cli(raw, output)
    assert second.returncode == 0 and second.stdout == first.stdout
    assert artifact.read_bytes() == retained


@private_store_required
def test_nonprivate_or_symlinked_output_refuses_without_chmod(stage_inputs, tmp_path):
    output = tmp_path / "not-private"
    # A single non-owner traversal bit is sufficient to violate private-root
    # policy; the empty negative fixture need not be world-readable.
    output.mkdir(mode=0o710)
    os.chmod(output, 0o710)
    raw = export_bytes([stage_inputs])
    denied = run_cli(raw, output)
    assert denied.returncode == 1
    assert output.stat().st_mode & 0o777 == 0o710 and not list(output.iterdir())
    link = tmp_path / "link"
    link.symlink_to(output, target_is_directory=True)
    assert run_cli(raw, link).returncode == 1


def test_untrusted_input_cannot_supply_an_authority_callback(stage_inputs):
    stage_inputs["source_check"] = {"approved": True}
    raw = export_bytes([stage_inputs])
    plan = stage_export(raw, hashlib.sha256(raw).hexdigest())
    assert plan["staged"][0]["stage"]["holds"] == ["U3_EXPORT_CASE_SCHEMA"]


@private_store_required
@pytest.mark.parametrize("identity_field", ["course_id", "assignment_id", "user_id"])
def test_cli_retains_large_identity_with_safe_stdout(
    stage_inputs, tmp_path, identity_field
):
    bad = copy.deepcopy(stage_inputs)
    bad["target"] = {
        "origin": "https://canvas.example", "course_id": "11",
        "assignment_id": "22", "user_id": "33", "attempt": 1,
        "submitted_at": "2026-01-01T00:00:00Z",
    }
    bad["target"][identity_field] = "9" * 5000
    raw = export_bytes([stage_inputs, bad, stage_inputs])
    child_env = {**os.environ, "PYTHONINTMAXSTRDIGITS": "4300"}
    script = Path(__file__).resolve().parents[1] / "scripts/stage_u3_feedback_export.py"
    child = subprocess.run(
        [sys.executable, str(script), "--expected-sha256",
         hashlib.sha256(raw).hexdigest(), "--output-dir", str(tmp_path / "private")],
        input=raw, capture_output=True, timeout=20, env=child_env,
    )
    assert child.returncode == 0, child.stderr
    summary = json.loads(child.stdout)
    assert summary["cases"] == 3 and not summary["publication_allowed"]
    assert b"9999999999" not in child.stdout and b"fictional-packet" not in child.stdout
    assert b"Traceback" not in child.stderr
    saved = json.loads(Path(summary["private_artifact"]).read_bytes())
    assert [row["source_position"] for row in saved["staged"]] == [0, 1, 2]
    assert saved["staged"][1]["stage"]["retained_input"] == bad
    assert saved["staged"][1]["stage"]["holds"] == ["U3_EXACT_TARGET"]
    assert all(row["stage"]["publisher_envelope"] is None for row in saved["staged"])
    assert saved["canvas_writes"] == saved["sheets_writes"] == 0


@pytest.mark.parametrize("capability", ["nonposix", "missing_getuid"])
def test_unsupported_private_output_holds_before_creating_directory(
    monkeypatch, tmp_path, capsys, capability
):
    from types import SimpleNamespace

    import stage_u3_feedback_export as cli

    output = tmp_path / "must-not-exist"
    capabilities = SimpleNamespace(name="posix")
    if capability == "nonposix":
        capabilities.name = "nt"
        capabilities.getuid = lambda: 123
    monkeypatch.setattr(cli, "os", capabilities)
    monkeypatch.setattr(sys, "argv", [
        "stage_u3_feedback_export.py", "--expected-sha256", "0" * 64,
        "--output-dir", str(output),
    ])
    assert cli.main() == 1
    summary = json.loads(capsys.readouterr().out)
    assert summary["error"] == "U3_STAGING_HELD_CHECK_PRIVATE_INPUT_OR_OUTPUT"
    assert not summary["publication_allowed"] and not output.exists()
