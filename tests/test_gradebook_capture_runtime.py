"""Exact shared-reader runtime contract; fictional files and no services."""

from pathlib import Path
from unittest.mock import Mock, patch

import pytest
from test_gradebook_capture import captured as captured

from canvas_mcp.gradebook.capture import build_case_receipt, intake_digest
from canvas_mcp.gradebook.client import GradebookError


def test_explicit_runtime_reaches_exact_reader_without_changing_receipt(
    captured, tmp_path
):
    store, _, receipt_id, shared, kwargs, rows, roster = captured
    runtime = tmp_path / "reviewed-runtime"
    runtime.mkdir()
    with patch(
        "canvas_mcp.gradebook.capture.load_shared_pin_module", return_value=shared
    ):
        legacy = build_case_receipt(store, receipt_id, **kwargs)

        def read_table(path, raw, sheet, *, runtime):
            assert (
                path == roster
                and raw == roster.read_bytes()
                and sheet == "Student Info"
            )
            assert runtime == tmp_path / "reviewed-runtime"
            return ["Canvas ID", "Email", "Student Number"], rows

        shared.read_table = Mock(side_effect=read_table)
        explicit = build_case_receipt(
            store, receipt_id, **kwargs, identity_runtime_root=runtime
        )
    assert explicit == legacy
    assert intake_digest(explicit) == intake_digest(legacy)
    shared.read_table.assert_called_once_with(
        roster, roster.read_bytes(), "Student Info", runtime=runtime
    )


def test_omitted_or_none_runtime_retains_three_positional_argument_contract(captured):
    store, _, receipt_id, shared, kwargs, rows, roster = captured

    def legacy_reader(path, raw, sheet):
        assert (path, raw, sheet) == (roster, roster.read_bytes(), "Student Info")
        return ["Canvas ID", "Email", "Student Number"], rows

    shared.read_table = Mock(side_effect=legacy_reader)
    with patch(
        "canvas_mcp.gradebook.capture.load_shared_pin_module", return_value=shared
    ):
        first = build_case_receipt(store, receipt_id, **kwargs)
        second = build_case_receipt(
            store, receipt_id, **kwargs, identity_runtime_root=None
        )
    assert first == second
    assert shared.read_table.call_count == 2
    assert all(not call.kwargs for call in shared.read_table.call_args_list)


@pytest.mark.parametrize(
    "kind", ["relative", "missing", "file", "symlink", "ancestor", "parent", "string"]
)
def test_unsafe_explicit_runtime_holds_before_shared_module_import(
    captured, tmp_path, kind
):
    root = tmp_path / "runtime"
    root.mkdir()
    regular = tmp_path / "regular-file"
    regular.write_bytes(b"fictional")
    link = tmp_path / "runtime-link"
    link.symlink_to(root, target_is_directory=True)
    nested = root / "nested"
    nested.mkdir()
    values = {
        "relative": Path("relative"),
        "missing": tmp_path / "missing",
        "file": regular,
        "symlink": link,
        "ancestor": link / "nested",
        "parent": root / ".." / "runtime",
        "string": str(root),
    }
    store, _, receipt_id, _, kwargs, _, _ = captured
    with patch("canvas_mcp.gradebook.capture.load_shared_pin_module") as load:
        with pytest.raises(GradebookError, match="EXPLICIT_IDENTITY_RUNTIME_REQUIRED"):
            build_case_receipt(
                store, receipt_id, **kwargs, identity_runtime_root=values[kind]
            )
        load.assert_not_called()


def test_explicit_runtime_never_falls_back_to_an_incompatible_legacy_reader(
    captured, tmp_path
):
    store, _, receipt_id, shared, kwargs, rows, _ = captured
    runtime = tmp_path / "runtime"
    runtime.mkdir()

    def legacy_reader(path, raw, sheet):
        return ["Canvas ID", "Email", "Student Number"], rows

    shared.read_table = Mock(side_effect=legacy_reader)
    with patch(
        "canvas_mcp.gradebook.capture.load_shared_pin_module", return_value=shared
    ):
        with pytest.raises(GradebookError, match="CANONICAL_IDENTITY_UNAVAILABLE"):
            build_case_receipt(
                store, receipt_id, **kwargs, identity_runtime_root=runtime
            )
    assert shared.read_table.call_count == 1
    assert shared.read_table.call_args.kwargs == {"runtime": runtime}
