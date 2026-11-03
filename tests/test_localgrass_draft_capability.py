"""Portable capability guards; no LocalGrAss checkout or native transport."""

from types import ModuleType

import pytest

from canvas_mcp.gradebook.client import GradebookError
from canvas_mcp.gradebook.localgrass_draft_edit import (
    _require_current_attempt_review_support,
)


def test_optional_attempt_review_rejects_legacy_planner_without_calling_it():
    stage = ModuleType("fictional_legacy_stage")
    calls = []

    def prepare_stage(proposals, *, raw, binding):
        calls.append(True)
        raise AssertionError("Unsupported planner must not execute")

    stage.prepare_stage = prepare_stage
    with pytest.raises(GradebookError, match="CURRENT_ATTEMPT_REVIEW_UNSUPPORTED"):
        _require_current_attempt_review_support(stage)
    assert calls == []


@pytest.mark.parametrize("variadic", [False, True])
def test_optional_attempt_review_recognizes_supported_signature_without_execution(
    variadic,
):
    stage = ModuleType("fictional_supported_stage")
    calls = []

    if variadic:

        def prepare_stage(proposals, **kwargs):
            calls.append(True)

    else:

        def prepare_stage(proposals, *, current_attempt_review=None):
            calls.append(True)

    stage.prepare_stage = prepare_stage
    _require_current_attempt_review_support(stage)
    assert calls == []


def test_optional_attempt_review_rejects_uninspectable_planner():
    stage = ModuleType("fictional_missing_stage")
    with pytest.raises(GradebookError, match="CURRENT_ATTEMPT_REVIEW_UNSUPPORTED"):
        _require_current_attempt_review_support(stage)
