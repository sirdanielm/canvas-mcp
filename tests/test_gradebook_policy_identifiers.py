"""Public schema/policy spellings remain identical across source representation."""

import pytest

from canvas_mcp.gradebook import paired_readiness, percent_rounding


@pytest.mark.parametrize(
    ("actual", "expected"),
    [
        (
            paired_readiness.CANDIDATE_POINTS_FIELD,
            "candidate_publish_points_preserving_higher_canvas",
        ),
        (
            paired_readiness.TEACHER_PREVIEW_REQUIRED,
            "exact_teacher_preview_approval_required",
        ),
        (
            percent_rounding.OWNER_ROUNDING_REQUIRED,
            "source_qualified_owner_rounding_required",
        ),
        (
            percent_rounding.DERIVATIVE_BINDING_REQUIRED,
            "rounded_derivative_requires_source_binding",
        ),
    ],
)
def test_schema_and_policy_identifiers_are_preserved(actual, expected):
    assert actual == expected
