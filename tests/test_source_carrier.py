import copy
import unittest

from canvas_mcp.gradebook.source_carrier import CarrierError, capture_source_sidecar


def snapshot():
    return {
        "schema_version": 1,
        "origin": "https://canvas.example.test",
        "course_id": "10",
        "cells": {"20:30": {"attempt": 2, "value": 5}},
    }


def submission():
    return {
        "id": 40,
        "user_id": 20,
        "assignment_id": 30,
        "attempt": 2,
        "submission_type": "online_upload",
        "body": "PRIVATE_CANARY",
        "attachments": [
            {
                "id": 50,
                "sha256": "a" * 64,
                "display_name": "PRIVATE_CANARY",
                "url": "PRIVATE_CANARY",
            }
        ],
    }


class SourceCarrierTests(unittest.TestCase):
    def test_observes_supplied_fields_but_never_claims_authority(self):
        base, raw = snapshot(), submission()
        before = copy.deepcopy((base, raw))
        result = capture_source_sidecar(base, [raw])
        item = result["cells"]["20:30"]
        self.assertEqual(item["reported_submission_object_id"], "40")
        self.assertEqual(item["observed_attempt"], 2)
        self.assertEqual(
            item["attachments"],
            [
                {
                    "canvas_attachment_id": "50",
                    "observed_version": {
                        "kind": "reported_unverified_sha256",
                        "value": "a" * 64,
                    },
                }
            ],
        )
        self.assertEqual("HELD_OBSERVATION_ONLY", item["status"])
        self.assertIn("DOWNSTREAM_ARTIFACT_BINDING_UNVERIFIED", item["holds"])
        self.assertIn("CURRENT_ATTEMPT_NOT_INDEPENDENTLY_VERIFIED", item["holds"])
        self.assertIn("SAME_FETCH_PROVENANCE_UNVERIFIED", item["holds"])
        self.assertFalse(result["scan_authority"])
        self.assertFalse(result["source_mapping_authority"])
        self.assertNotIn("PRIVATE_CANARY", repr(result))
        self.assertEqual((base, raw), before)

    def test_missing_fields_and_no_version_hold(self):
        raw = submission()
        raw.pop("id")
        raw["attempt"] = None
        raw["attachments"] = [{"id": 50, "modified_at": "2099-01-01"}]
        item = capture_source_sidecar(snapshot(), [raw])["cells"]["20:30"]
        self.assertIsNone(item["reported_submission_object_id"])
        self.assertIsNone(item["observed_attempt"])
        self.assertIsNone(item["attachments"][0]["observed_version"])
        self.assertLessEqual(
            {
                "NATIVE_SUBMISSION_ID_UNAVAILABLE",
                "NATIVE_ATTEMPT_UNAVAILABLE",
                "ARTIFACT_VERSION_UNAVAILABLE",
            },
            set(item["holds"]),
        )

    def test_different_attempt_never_claims_currentness(self):
        first = submission()
        second = copy.deepcopy(first)
        second["attempt"] = 3
        a = capture_source_sidecar(snapshot(), [first])["cells"]["20:30"]
        b = capture_source_sidecar(snapshot(), [second])["cells"]["20:30"]
        self.assertNotEqual(a["observed_attempt"], b["observed_attempt"])
        self.assertEqual(a["status"], b["status"])
        self.assertIn("CURRENT_ATTEMPT_NOT_INDEPENDENTLY_VERIFIED", b["holds"])
        self.assertIn("SNAPSHOT_ATTEMPT_MISMATCH", b["holds"])

    def test_external_tool_never_imports_attachment_claims(self):
        raw = submission()
        raw["submission_type"] = "basic_lti_launch"
        item = capture_source_sidecar(snapshot(), [raw])["cells"]["20:30"]
        self.assertEqual([], item["attachments"])
        self.assertIn("SUBMISSION_TYPE_UNSUPPORTED", item["holds"])

    def test_multiple_and_duplicate_attachments_are_held(self):
        raw = submission()
        raw["attachments"] += [{"id": 51}, {"id": 50}]
        item = capture_source_sidecar(snapshot(), [raw])["cells"]["20:30"]
        self.assertEqual(2, len(item["attachments"]))
        self.assertIn("DUPLICATE_ATTACHMENT_ID", item["holds"])
        self.assertIn("ARTIFACT_VERSION_UNAVAILABLE", item["holds"])
        self.assertIn("MULTIPLE_ATTACHMENTS_REQUIRE_EXACT_BINDING", item["holds"])

    def test_invalid_attempt_and_malformed_attachment_are_held(self):
        raw = submission()
        raw["attempt"] = True
        raw["attachments"] = [None, {"id": True}, {"id": 51, "sha256": "bad"}]
        item = capture_source_sidecar(snapshot(), [raw])["cells"]["20:30"]
        self.assertIsNone(item["observed_attempt"])
        self.assertLessEqual(
            {
                "NATIVE_ATTEMPT_UNAVAILABLE",
                "ATTACHMENTS_MALFORMED",
                "ATTACHMENT_ID_UNAVAILABLE",
                "ARTIFACT_VERSION_UNAVAILABLE",
            },
            set(item["holds"]),
        )

    def test_out_of_scope_records_do_not_create_cells(self):
        raw = submission()
        raw["user_id"] = 99
        item = capture_source_sidecar(snapshot(), [raw])["cells"]["20:30"]
        self.assertEqual(["SUBMISSION_OBSERVATION_UNAVAILABLE"], item["holds"])

    def test_missing_snapshot_attempt_has_explicit_hold(self):
        base = snapshot()
        base["cells"]["20:30"]["attempt"] = None
        item = capture_source_sidecar(base, [submission()])["cells"]["20:30"]
        self.assertIn("SNAPSHOT_ATTEMPT_UNAVAILABLE", item["holds"])

    def test_sensitive_or_malformed_origins_are_rejected(self):
        for origin in (
            "https://user:password@canvas.example.test",
            "https://@canvas.example.test",
            "https://canvas.example.test:bad",
            "https://canvas.example.test:99999",
            "https://canvas.example.test/?token=secret",
            "https://canvas.example.test/#secret",
            "http://canvas.example.test",
            "https://canvas.example.test/private",
        ):
            base = snapshot()
            base["origin"] = origin
            with self.assertRaises(CarrierError):
                capture_source_sidecar(base, [submission()])

    def test_course_context_mismatch_is_never_silently_accepted(self):
        raw = submission()
        self.assertIn(
            "SUBMISSION_COURSE_UNAVAILABLE",
            capture_source_sidecar(snapshot(), [raw])["cells"]["20:30"]["holds"],
        )
        raw["course_id"] = None
        self.assertIn(
            "SUBMISSION_COURSE_UNAVAILABLE",
            capture_source_sidecar(snapshot(), [raw])["cells"]["20:30"]["holds"],
        )
        raw["course_id"] = 999
        self.assertIn(
            "SUBMISSION_COURSE_MISMATCH",
            capture_source_sidecar(snapshot(), [raw])["cells"]["20:30"]["holds"],
        )

    def test_duplicate_submission_is_rejected(self):
        with self.assertRaisesRegex(CarrierError, "Duplicate"):
            capture_source_sidecar(snapshot(), [submission(), submission()])

    def test_snapshot_schema_and_context_are_strict(self):
        for change in ({"schema_version": True}, {"course_id": None}, {"cells": []}):
            base = snapshot()
            base.update(change)
            with self.assertRaises(CarrierError):
                capture_source_sidecar(base, [submission()])

    def test_unknown_submission_type_is_not_copied(self):
        raw = submission()
        raw["submission_type"] = "PRIVATE_CANARY"
        result = capture_source_sidecar(snapshot(), [raw])
        self.assertNotIn("PRIVATE_CANARY", repr(result))
        self.assertIn("SUBMISSION_TYPE_UNSUPPORTED", result["cells"]["20:30"]["holds"])


if __name__ == "__main__":
    unittest.main()
