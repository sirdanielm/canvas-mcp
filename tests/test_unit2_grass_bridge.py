"""Offline bridge checks; native integration uses explicitly supplied code pins."""

from __future__ import annotations

import hashlib
import json
import os
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest

from canvas_mcp.gradebook.model import GradebookError
from canvas_mcp.gradebook.unit2_grass_bridge import (
    load_pinned_module,
    recompute_fictional,
)

BRIDGE_SHA256 = "94465abd6d7ef9c4bb235f44c5ac7b2076e7183bcf432a96374cbc27d8df3120"
PIPELINE_SHA256 = "abc929ef233f3cedec7cb8d36c20af64a5308fa26b27e519f78091bf49f88842"


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def canonical(value: Any) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode()


@pytest.fixture
def native_code() -> tuple[Path, str, Path, str]:
    bridge = os.environ.get("UNIT2_GRASS_BRIDGE_SOURCE")
    pipeline = os.environ.get("UNIT2_NATIVE_PIPELINE_SOURCE")
    if not bridge or not pipeline:
        pytest.skip(
            "Explicit reviewed native source paths are required for offline integration"
        )
    bp, pp = Path(bridge), Path(pipeline)
    assert sha(bp.read_bytes()) == BRIDGE_SHA256
    assert sha(pp.read_bytes()) == PIPELINE_SHA256
    return bp, BRIDGE_SHA256, pp, PIPELINE_SHA256


def fixture_inputs() -> dict[str, Any]:
    """One wholly fictional MC; the native producer owns the scoring rule."""
    marks = {
        letter: {
            "state": "UNCLEAR" if letter == "D" else "UNMARKED",
            "observation": "Fictional test observation " + letter,
        }
        for letter in "ABCD"
    }
    item = {
        "item_id": "MC01",
        "kind": "MC",
        "read_status": "UNREADABLE",
        "recorded_text": "",
        "option_marks": marks,
        "diagrams": [],
        "evidence_refs": [],
        "reassessment": {},
        "response_id": "d" * 64,
        "transcript_sha256": "e" * 64,
    }
    policy_raw = canonical({"fixture_only": True})
    binding = {
        "packet_id": "1" * 64,
        "source_sha256": "2" * 64,
        "reading_key": "3" * 64,
        "result_key": "4" * 64,
        "policy_sha256": sha(policy_raw),
        "before_item_sha256": sha(canonical(item)),
        "form_id": "FICTIONAL_DEMO_FORM",
        "attempt": "R1",
        "item_id": "MC01",
    }
    snapshot = {
        "binding": binding,
        "option_marks_before": deepcopy(marks),
        "current_item": deepcopy(item),
    }
    decision = {
        "contract_id": "grass.unit2.mc-teacher-decision.v1.1",
        "mode": "DEMO",
        "decision_id": "FICTIONAL-DECISION-0001",
        "binding": deepcopy(binding),
        "option_marks_before": deepcopy(marks),
        "choice": "D",
        "reason": "Fictional interface test only",
        "method": {
            "kind": "DEMO",
            "measurement_status": "UNAVAILABLE",
            "measurements": dict.fromkeys("ABCD"),
            "sidecar_sha256": None,
        },
        "actor": {"kind": "DEMO", "attestation": "No real teacher decision"},
    }
    return {
        "snapshot": snapshot,
        "decision": decision,
        "demo_ledger": {},
        "reading": {"items": [deepcopy(item)]},
        "judgment": None,
        "form": {
            "questions": [{"item_id": "MC01", "kind": "MC", "correct_letter": "D"}]
        },
        "policy_spec": {
            "items": {"MC01": {"maximum_points": "1", "weight": "1", "criteria": []}}
        },
        "packet": {
            "packet_id": binding["packet_id"],
            "source_sha256": binding["source_sha256"],
            "form_id": binding["form_id"],
            "attempt": "R1",
            "assessment_id": "FICTIONAL_DEMO_ONLY",
            "academic_sha256": "6" * 64,
        },
        "head": {
            "reading_key": binding["reading_key"],
            "result_key": binding["result_key"],
        },
        "policy_raw": policy_raw,
        "operations": [{"op": "to_percent"}],
        "fixture_only": True,
    }


def run_fixture(
    native_code: tuple[Path, str, Path, str], **changes: Any
) -> dict[str, Any]:
    bp, bh, pp, ph = native_code
    values = fixture_inputs()
    values.update(changes)
    return recompute_fictional(
        bridge_path=bp, bridge_sha256=bh, pipeline_path=pp, pipeline_sha256=ph, **values
    )


def build_fixture(
    bridge_path: Path | None = None,
    pipeline_path: Path | None = None,
) -> dict[str, Any]:
    """Return runnable real-code kwargs: fictional MC total 50 and pending FRQ.

    Explicit paths or the two test environment variables select reviewed code
    only. This function opens no saved reading, target, roster, or source media.
    """
    bridge = bridge_path or Path(os.environ["UNIT2_GRASS_BRIDGE_SOURCE"])
    pipeline = pipeline_path or Path(os.environ["UNIT2_NATIVE_PIPELINE_SOURCE"])
    values = fixture_inputs()
    reading, questions, policy_items = [], [], {}
    for number in range(1, 21):
        item = deepcopy(values["snapshot"]["current_item"])
        item["item_id"] = f"MC{number:02d}"
        for letter, mark in item["option_marks"].items():
            selected = "A" if number == 1 else "D"
            mark["state"] = (
                ("UNCLEAR" if number == 13 else "CLEAR_MARK")
                if letter == selected
                else "UNMARKED"
            )
        item["read_status"] = "UNREADABLE" if number == 13 else "READABLE"
        reading.append(item)
        questions.append(
            {"item_id": item["item_id"], "kind": "MC", "correct_letter": "D"}
        )
        policy_items[item["item_id"]] = {
            "maximum_points": "2.5",
            "weight": "1",
            "criteria": [],
        }
    selected_item = deepcopy(reading[12])
    values["snapshot"]["current_item"] = selected_item
    values["snapshot"]["option_marks_before"] = deepcopy(selected_item["option_marks"])
    values["snapshot"]["binding"].update(
        {"item_id": "MC13", "before_item_sha256": sha(canonical(selected_item))}
    )
    values["decision"]["binding"] = deepcopy(values["snapshot"]["binding"])
    values["decision"]["option_marks_before"] = deepcopy(selected_item["option_marks"])
    reading.append(
        {
            "item_id": "FRQ01",
            "kind": "FRQ",
            "read_status": "UNREADABLE",
            "recorded_text": "",
            "parts": [],
            "diagrams": [],
            "evidence_refs": [],
        }
    )
    questions.append({"item_id": "FRQ01", "kind": "FRQ"})
    policy_items["FRQ01"] = {"maximum_points": "50", "weight": "1", "criteria": []}
    values.update(
        {
            "reading": {"items": reading},
            "form": {"questions": questions},
            "policy_spec": {"items": policy_items},
            "bridge_path": bridge,
            "bridge_sha256": BRIDGE_SHA256,
            "pipeline_path": pipeline,
            "pipeline_sha256": PIPELINE_SHA256,
        }
    )
    return values


def test_complete_fictional_component_50_and_pending_frq(
    native_code: tuple[Path, str, Path, str],
) -> None:
    values = build_fixture(native_code[0], native_code[2])
    original = deepcopy(values)
    result = recompute_fictional(**values)
    assert values == original
    assert result["before_result"]["known_weighted_earned"] == "45"
    assert result["after_result"]["known_weighted_earned"] == "47.5"
    assert result["after_result"]["weighted_possible"] == "100"
    assert result["after_result"]["grade_preview"] is None
    assert result["after_result"]["holds"] == [
        {"item_id": "FRQ01", "reason": "UNREADABLE"}
    ]
    assert len([r for r in result["after_result"]["items"] if r["kind"] == "MC"]) == 20


def test_loader_rejects_changed_pin(tmp_path: Path) -> None:
    code = tmp_path / "source.py"
    code.write_text("VALUE = 1\n", encoding="utf-8")
    with pytest.raises(GradebookError, match="Pinned code changed"):
        load_pinned_module(code, "0" * 64)


def test_loader_allows_unexecuted_canonical_main_guard(tmp_path: Path) -> None:
    code = tmp_path / "guarded.py"
    raw = (
        b"VALUE = 1\ndef main():\n    raise AssertionError('CLI must not execute')\n"
        b"if __name__ == '__main__':\n    raise SystemExit(main())\n"
    )
    code.write_bytes(raw)
    module = load_pinned_module(code, sha(raw))
    assert module.VALUE == 1
    assert callable(module.main)
    assert not (tmp_path / "__pycache__").exists()


@pytest.mark.parametrize("guard", [
    "if __name__ != '__main__':\n    VALUE = 2\n",
    "if __name__ == '__main__':\n    VALUE = 2\nelse:\n    VALUE = 3\n",
    "if True:\n    VALUE = 2\n",
])
def test_loader_rejects_other_top_level_conditionals(tmp_path: Path, guard: str) -> None:
    code = tmp_path / "unguarded.py"
    raw = ("VALUE = 1\n" + guard).encode()
    code.write_bytes(raw)
    with pytest.raises(GradebookError, match="Definition-only"):
        load_pinned_module(code, sha(raw))


def test_loader_rejects_initializer_io(tmp_path: Path) -> None:
    code = tmp_path / "source.py"
    raw = b"VALUE = open('forbidden', 'w')\n"
    code.write_bytes(raw)
    with pytest.raises(GradebookError, match="initializer"):
        load_pinned_module(code, sha(raw))
    assert not (tmp_path / "forbidden").exists()


def test_actual_native_recompute_and_originals_preserved(
    native_code: tuple[Path, str, Path, str],
) -> None:
    original = fixture_inputs()
    before = deepcopy(original)
    bp, bh, pp, ph = native_code
    result = recompute_fictional(
        bridge_path=bp,
        bridge_sha256=bh,
        pipeline_path=pp,
        pipeline_sha256=ph,
        **original,
    )
    assert original == before
    assert result["status"] == "DEMO_NOT_TEACHER_ACCEPTED"
    assert result["native_arithmetic_recomputed"] is True
    assert result["before_result"]["grade_preview"] is None
    assert result["before_result"]["holds"] == [
        {"item_id": "MC01", "reason": "UNREADABLE"}
    ]
    assert result["after_result"]["known_weighted_earned"] == "1"
    assert result["after_result"]["grade_preview"] == "100"
    assert result["after_result"]["holds"] == []
    for letter in "ABC":
        assert (
            result["after_reading"]["items"][0]["option_marks"][letter]
            == original["snapshot"]["current_item"]["option_marks"][letter]
        )
    assert result["after_result"]["teacher_acceptance"] == "NOT_ACCEPTED"
    assert (
        result["store_writes"] == result["canvas_writes"] == result["paid_calls"] == 0
    )


@pytest.mark.parametrize("choice", ["A", "BLANK", "UNRESOLVED"])
def test_unsupported_or_unresolved_keeps_native_hold(
    native_code: tuple[Path, str, Path, str],
    choice: str,
) -> None:
    decision = fixture_inputs()["decision"]
    decision["choice"] = choice
    result = run_fixture(native_code, decision=decision)
    assert result["before_result"] == result["after_result"]
    assert result["after_result"]["grade_preview"] is None


def test_nonfictional_mode_rejected_before_code_load() -> None:
    values = fixture_inputs()
    values["fixture_only"] = False
    with pytest.raises(GradebookError, match="fictional"):
        recompute_fictional(
            bridge_path=Path("unopened"),
            bridge_sha256="0" * 64,
            pipeline_path=Path("unopened"),
            pipeline_sha256="0" * 64,
            **values,
        )


def test_changed_policy_binding_rejected(
    native_code: tuple[Path, str, Path, str],
) -> None:
    with pytest.raises(GradebookError, match="bindings"):
        run_fixture(native_code, policy_raw=b"{}")


def test_native_stale_decision_is_rejected(
    native_code: tuple[Path, str, Path, str],
) -> None:
    decision = fixture_inputs()["decision"]
    decision["binding"]["reading_key"] = "f" * 64
    with pytest.raises(ValueError, match="STALE_OR_WRONG_PRESTATE_BINDING"):
        run_fixture(native_code, decision=decision)


def test_native_repeat_preserves_original_plan(
    native_code: tuple[Path, str, Path, str],
) -> None:
    first = run_fixture(native_code)
    repeated = run_fixture(
        native_code, demo_ledger=first["validated_plan"]["demo_ledger"]
    )
    assert repeated["validated_plan"]["status"] == "REPEAT_NOOP"
    assert repeated["validated_plan"]["plan"] == first["validated_plan"]["plan"]
    assert repeated["before_result"] == first["before_result"]
    assert repeated["after_result"] == first["after_result"]
