import json

from test_source_sidecar_store import SidecarStoreTests

from canvas_mcp.gradebook.model import digest
from canvas_mcp.gradebook.source_sidecar_store import read_source_sidecar


class MismatchReview(SidecarStoreTests):
    def test_invalid_observation_and_nonexistent_source_snapshot_is_unvalidated_mismatch(
        self,
    ):
        envelope = {
            "contract": "CANVAS_SOURCE_SIDECAR_STORE_V1",
            "snapshot_id": "f" * 64,
            "observation": {"invalid": "fictional"},
        }
        sidecar_id = digest(envelope)
        (self.store.root / f"source_sidecar-{sidecar_id}.json").write_text(
            json.dumps(envelope), encoding="utf-8"
        )
        self.assertEqual(
            read_source_sidecar(self.store, self.snapshot_id, sidecar_id),
            {"state": "SNAPSHOT_ID_MISMATCH_UNVALIDATED"},
        )

    def test_reject_non_numeric_course_in_generic_snapshot(self):
        import copy

        from canvas_mcp.gradebook.client import GradebookError
        from canvas_mcp.gradebook.source_sidecar_store import save_source_sidecar

        bad = copy.deepcopy(self.snapshot)
        bad["course_id"] = "PRIVATE_STUDENT_TEXT"
        snapshot_id, _ = self.store.save("snapshot", bad)
        sidecar = copy.deepcopy(self.sidecar)
        sidecar["course_id"] = bad["course_id"]
        with self.assertRaises(GradebookError):
            save_source_sidecar(self.store, snapshot_id, sidecar)
