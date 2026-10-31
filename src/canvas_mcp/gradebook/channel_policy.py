"""Outbound policy for the two existing grading lanes; no action authority."""

from .client import GradebookError

LANE_DELIVERY = {
    "GRASS_SUMMATIVE": "SCORE_AND_FEEDBACK",
    "SDMGRASS_FORMATIVE": "SCORE_ONLY",
}


def lane_delivery(source_lane: str, declared: str | None = None) -> str:
    expected = LANE_DELIVERY.get(source_lane)
    if expected is None or declared is not None and declared != expected:
        raise GradebookError("DELIVERY_POLICY_CHANGED")
    return expected
