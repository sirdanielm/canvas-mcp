"""Shared verifier reader routing stays complete on every supported platform."""

from pathlib import Path

import pytest
from test_course_asset_plan import make_plan_inputs

from canvas_mcp.mirror.assets import verify_assets
from canvas_mcp.mirror.core import MirrorError, read_json, require_valid, verify


@pytest.mark.parametrize("validator", ["verify", "require_valid", "verify_assets"])
def test_shared_verifier_uses_supplied_reader_for_every_input(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, validator: str
) -> None:
    baseline, assets, _ = make_plan_inputs(tmp_path)
    assert verify(baseline)["ok"]
    assert verify_assets(assets, baseline)["ok"]
    cached = {
        path.resolve(): path.read_bytes()
        for root in (baseline, assets)
        for path in root.rglob("*")
        if path.is_file()
    }
    seen: set[Path] = set()

    def from_cache(path: Path) -> bytes:
        seen.add(path.resolve())
        return cached[path.resolve()]

    def forbidden(*args: object, **kwargs: object) -> bytes:
        pytest.fail("Verifier bypassed the supplied reader")

    monkeypatch.setattr(Path, "read_bytes", forbidden)
    monkeypatch.setattr(Path, "read_text", forbidden)
    if validator == "verify_assets":
        result = verify_assets(assets, baseline, read_bytes=from_cache)
        assert set(cached) == seen
    elif validator == "require_valid":
        result = require_valid(baseline, read_bytes=from_cache)
        assert seen == {path for path in cached if path.is_relative_to(baseline)}
    else:
        result = verify(baseline, read_bytes=from_cache)
        assert seen == {path for path in cached if path.is_relative_to(baseline)}
    assert result["ok"]


def test_callback_json_keeps_utf8_and_safe_error_contract(tmp_path: Path) -> None:
    path = tmp_path / "not-opened.json"
    assert read_json(path, read_bytes=lambda _: b'{"ok":true}') == {"ok": True}
    for body in (b"not JSON", b"\xff", '{"ok":true}'.encode("utf-16")):
        with pytest.raises(MirrorError, match="^LOCAL_JSON_UNREADABLE$"):
            read_json(path, read_bytes=lambda _, body=body: body)


def test_bounded_reader_refusal_is_never_replaced_with_a_disk_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    baseline, assets, _ = make_plan_inputs(tmp_path)
    calls = 0

    def refuse(path: Path) -> bytes:
        nonlocal calls
        calls += 1
        raise MirrorError("CALLER_INPUT_BOUND_HELD")

    def forbidden(*args: object, **kwargs: object) -> bytes:
        pytest.fail("Verifier fell back to a filesystem read after refusal")

    monkeypatch.setattr(Path, "read_bytes", forbidden)
    monkeypatch.setattr(Path, "read_text", forbidden)
    with pytest.raises(MirrorError, match="^CALLER_INPUT_BOUND_HELD$"):
        verify_assets(assets, baseline, read_bytes=refuse)
    assert calls == 1
