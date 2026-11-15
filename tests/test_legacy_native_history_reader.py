"""Fictional offline coverage of the bounded legacy history reader."""

import json

import pytest

from canvas_mcp.gradebook.client import GradebookError
from canvas_mcp.gradebook.localgrass_edit_execution import _load_prior_plan


class Files:
    MAX_JSON = 256

    @staticmethod
    def encoded(value):
        return (
            json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + "\n"
        ).encode()

    @staticmethod
    def read_bytes(path, maximum):
        raw = path.read_bytes()
        if len(raw) > maximum:
            raise ValueError("INPUT_TYPE_OR_SIZE_HOLD")
        return raw


def run(tmp_path, raw):
    path = tmp_path / "plan.json"
    path.write_bytes(raw)
    return _load_prior_plan(Files, path)


def test_exact_legacy_pretty_roundtrip_preserves_strings(tmp_path):
    value = {
        "contract": "LOCALGRASS_TEACHER_EDIT_V1",
        "items": [{"text": ' a \\" b '}] * 7,
    }
    raw = Files.encoded(value)
    assert len(raw) > Files.MAX_JSON
    assert len(raw) < 2 * Files.MAX_JSON
    assert run(tmp_path, raw) == value


def test_small_nonlegacy_and_escaped_string_are_accepted(tmp_path):
    value = {"contract": "OTHER", "value": "literal whitespace  \\t \\"}
    assert run(tmp_path, json.dumps(value).encode()) == value


def test_oversized_raw_and_canonical_contents_both_hold(tmp_path):
    with pytest.raises(ValueError, match="INPUT_TYPE_OR_SIZE_HOLD"):
        run(tmp_path, b" " * (2 * Files.MAX_JSON + 1))
    value = {"contract": "LOCALGRASS_TEACHER_EDIT_V1", "value": "x" * 300}
    with pytest.raises(GradebookError, match="NATIVE_HISTORY_CONTENT_SIZE_HOLD"):
        run(tmp_path, Files.encoded(value))


def test_large_unknown_or_noncanonical_pretty_history_holds(tmp_path):
    value = {"contract": "OTHER", "items": [{"a": 1}] * 13}
    raw = Files.encoded(value)
    assert Files.MAX_JSON < len(raw) < 2 * Files.MAX_JSON
    with pytest.raises(GradebookError, match="NATIVE_HISTORY_LEGACY_FORMAT_HOLD"):
        run(tmp_path, raw)
    value["contract"] = "LOCALGRASS_TEACHER_EDIT_V1"
    raw = Files.encoded(value) + b" "
    with pytest.raises(GradebookError, match="NATIVE_HISTORY_LEGACY_FORMAT_HOLD"):
        run(tmp_path, raw)


@pytest.mark.parametrize(
    "raw,code",
    [
        (b'{"a":1,"a":2}', "DUPLICATE_JSON_KEY"),
        (b'{"a":NaN}', "NONFINITE_JSON"),
        (b"{", "INVALID_NATIVE_HISTORY_JSON"),
        (b"[]", "PRIOR_NATIVE_PLAN_UNVERIFIED"),
    ],
)
def test_strict_json_holds(tmp_path, raw, code):
    with pytest.raises(GradebookError, match=code):
        run(tmp_path, raw)
