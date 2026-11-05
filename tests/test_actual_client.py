"""Exercise the isolated actual client caller using fictional in-memory inputs."""

import unittest

from canvas_mcp.gradebook import client as candidate


class ActualClientTests(unittest.IsolatedAsyncioTestCase):
    async def test_opt_in_sidecar_and_legacy_shape_use_same_raw_fetch(self):
        client = candidate.GradebookClient("https://canvas.example.test", "fictional")
        calls = []

        async def get(path, params):
            calls.append(path)
            if path.endswith("/permissions"):
                return {"manage_grades": True}
            return {"id": 10, "name": "Fixture", "workflow_state": "available"}

        async def pages(path, params):
            calls.append(path)
            if path.endswith("/sections"):
                return [{"id": 11, "name": "Fixture"}]
            if path.endswith("/enrollments"):
                return [
                    {
                        "type": "StudentEnrollment",
                        "enrollment_state": "active",
                        "user_id": 20,
                        "course_section_id": 11,
                        "user": {"id": 20, "name": "Fictional"},
                    }
                ]
            if path.endswith("/assignments"):
                return [
                    {
                        "id": 30,
                        "course_id": 10,
                        "name": "Fixture",
                        "published": True,
                        "grading_type": "points",
                    }
                ]
            if path.endswith("/submissions"):
                return [
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
            raise AssertionError("Unexpected fictional request")

        client.get, client.pages = get, pages
        try:
            legacy = await client.snapshot("10")
            first_calls = calls[:]
            calls.clear()
            paired = await client.snapshot_with_source_sidecar("10")
            self.assertEqual(first_calls, calls)
            self.assertEqual(legacy["cells"], paired["snapshot"]["cells"])
            self.assertNotIn("source_sidecar", legacy)
            cell = paired["source_sidecar"]["cells"]["20:30"]
            self.assertEqual("50", cell["attachments"][0]["canvas_attachment_id"])
            self.assertEqual("HELD_OBSERVATION_ONLY", cell["status"])
            self.assertIn("SAME_FETCH_PROVENANCE_UNVERIFIED", cell["holds"])
            self.assertFalse(paired["source_sidecar"]["scan_authority"])
        finally:
            await client.close()


if __name__ == "__main__":
    unittest.main()
