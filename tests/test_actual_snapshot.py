"""Fictional adapter exercise against the actual CanvasMCP snapshot normalizer."""

import copy
import unittest

from canvas_mcp.gradebook.model import normalize_snapshot
from canvas_mcp.gradebook.source_carrier import capture_source_sidecar


class ActualNormalizerTests(unittest.TestCase):
    def test_sidecar_uses_exact_normalized_cell_scope_without_changing_snapshot(self):
        course = {"id": 10, "name": "Fictional", "workflow_state": "available"}
        sections = [{"id": 11, "name": "Fixture"}]
        enrollments = [
            {
                "type": "StudentEnrollment",
                "enrollment_state": "active",
                "user_id": 20,
                "course_section_id": 11,
                "user": {"id": 20, "name": "Fictional"},
            }
        ]
        assignments = [
            {
                "id": 30,
                "course_id": 10,
                "name": "Fixture",
                "published": True,
                "grading_type": "points",
            }
        ]
        raw = [
            {
                "id": 40,
                "user_id": 20,
                "assignment_id": 30,
                "attempt": 2,
                "submission_type": "online_upload",
                "attachments": [{"id": 50}],
                "assignment_visible": True,
                "workflow_state": "submitted",
                "score": None,
            }
        ]
        normalized = normalize_snapshot(
            "https://canvas.example.test",
            course,
            sections,
            enrollments,
            assignments,
            raw,
        )
        before = copy.deepcopy(normalized)
        sidecar = capture_source_sidecar(normalized, raw)
        self.assertEqual(normalized, before)
        self.assertNotIn("attachments", normalized["cells"]["20:30"])
        self.assertEqual(
            "50", sidecar["cells"]["20:30"]["attachments"][0]["canvas_attachment_id"]
        )
        self.assertIn(
            "ARTIFACT_VERSION_UNAVAILABLE", sidecar["cells"]["20:30"]["holds"]
        )
        self.assertIn(
            "DOWNSTREAM_ARTIFACT_BINDING_UNVERIFIED", sidecar["cells"]["20:30"]["holds"]
        )
        self.assertFalse(sidecar["scan_authority"])


if __name__ == "__main__":
    unittest.main()
