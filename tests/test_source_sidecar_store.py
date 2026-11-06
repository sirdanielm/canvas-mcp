import copy
import os
import tempfile
import unittest
from pathlib import Path

from canvas_mcp.gradebook.client import GradebookError
from canvas_mcp.gradebook.source_carrier import capture_source_sidecar
from canvas_mcp.gradebook.source_sidecar_store import (
    read_source_sidecar,
    save_source_sidecar,
)
from canvas_mcp.gradebook.store import Store


@unittest.skipUnless(
    all(hasattr(os, name) for name in ("O_NOFOLLOW", "O_NONBLOCK", "O_DIRECTORY"))
    and os.open in os.supports_dir_fd,
    "Safe descriptor-based sidecar access is unavailable",
)
class SidecarStoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = Store(Path(self.tmp.name) / "private")
        self.snapshot = {
            "schema_version": 1,
            "origin": "https://canvas.example.test",
            "course_id": "10",
            "cells": {"20:30": {"attempt": 2}},
        }
        self.raw = {
            "id": 40,
            "user_id": 20,
            "assignment_id": 30,
            "course_id": 10,
            "attempt": 2,
            "submission_type": "online_upload",
            "attachments": [{"id": 50, "sha256": "a" * 64}],
        }
        self.sidecar = capture_source_sidecar(self.snapshot, [self.raw])
        self.snapshot_id, self.path = self.store.save("snapshot", self.snapshot)

    def test_roundtrip_private_and_legacy_unchanged(self):
        before = self.path.read_bytes()
        sid = save_source_sidecar(self.store, self.snapshot_id, self.sidecar)
        result = read_source_sidecar(self.store, self.snapshot_id, sid)
        self.assertEqual(result["state"], "HELD")
        self.assertEqual(result["observation"], self.sidecar)
        self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual(self.store.load("snapshot", self.snapshot_id), self.snapshot)
        self.assertEqual(os.stat(self.store.root).st_mode & 0o777, 0o700)
        self.assertEqual(
            os.stat(self.store.root / f"source_sidecar-{sid}.json").st_mode & 0o777,
            0o600,
        )
        self.assertFalse(result["observation"]["source_mapping_authority"])
        self.assertFalse(result["observation"]["scan_authority"])
        self.assertEqual(
            sid, save_source_sidecar(self.store, self.snapshot_id, self.sidecar)
        )

    def test_absent_missing_invalid_and_stale(self):
        self.assertEqual(
            read_source_sidecar(self.store, self.snapshot_id, None),
            {"state": "REFERENCE_UNKNOWN"},
        )
        for key in ("f" * 64, "../bad"):
            self.assertEqual(
                read_source_sidecar(self.store, self.snapshot_id, key),
                {"state": "INCOMPLETE"},
            )
        sid = save_source_sidecar(self.store, self.snapshot_id, self.sidecar)
        newer = copy.deepcopy(self.snapshot)
        newer["cells"]["20:30"]["attempt"] = 3
        newer_id, _ = self.store.save("snapshot", newer)
        self.assertEqual(
            read_source_sidecar(self.store, newer_id, sid),
            {"state": "SNAPSHOT_ID_MISMATCH_UNVALIDATED"},
        )

    def test_incomplete_observations_stay_held(self):
        for changes in (
            {"id": None},
            {"attachments": []},
            {"submission_type": "external_tool"},
        ):
            raw = dict(self.raw)
            raw.update(changes)
            obs = capture_source_sidecar(self.snapshot, [raw])
            sid = save_source_sidecar(self.store, self.snapshot_id, obs)
            result = read_source_sidecar(self.store, self.snapshot_id, sid)
            self.assertEqual(result["state"], "INCOMPLETE")
            self.assertEqual(
                result["observation"]["cells"]["20:30"]["status"],
                "HELD_OBSERVATION_ONLY",
            )
        sid = save_source_sidecar(
            self.store, self.snapshot_id, capture_source_sidecar(self.snapshot, [])
        )
        self.assertEqual(
            read_source_sidecar(self.store, self.snapshot_id, sid)["state"],
            "INCOMPLETE",
        )

    def test_reject_extra_data_authority_and_missing_holds_via_generic_store(self):
        for mutation in ("authority", "raw", "hold"):
            obs = copy.deepcopy(self.sidecar)
            if mutation == "authority":
                obs["scan_authority"] = True
            if mutation == "raw":
                obs["cells"]["20:30"]["body"] = "fictional secret"
            if mutation == "hold":
                obs["cells"]["20:30"]["holds"] = []
            with self.subTest(mutation=mutation), self.assertRaises(GradebookError):
                self.store.save(
                    "source_sidecar",
                    {
                        "contract": "CANVAS_SOURCE_SIDECAR_STORE_V1",
                        "snapshot_id": self.snapshot_id,
                        "observation": obs,
                    },
                )

    def test_bounds_context_and_missing_snapshot(self):
        obs = copy.deepcopy(self.sidecar)
        obs["course_id"] = "99"
        with self.assertRaises(GradebookError):
            save_source_sidecar(self.store, self.snapshot_id, obs)
        obs = copy.deepcopy(self.sidecar)
        obs["cells"]["20:30"]["attachments"] *= 101
        with self.assertRaises(GradebookError):
            save_source_sidecar(self.store, self.snapshot_id, obs)
        with self.assertRaises(GradebookError):
            save_source_sidecar(self.store, "f" * 64, self.sidecar)

    def test_corruption_and_symlink_held_incomplete(self):
        sid = save_source_sidecar(self.store, self.snapshot_id, self.sidecar)
        path = self.store.root / f"source_sidecar-{sid}.json"
        path.write_text("{}", encoding="utf-8")
        self.assertEqual(
            read_source_sidecar(self.store, self.snapshot_id, sid),
            {"state": "INCOMPLETE"},
        )
        path.unlink()
        path.symlink_to(self.path)
        self.assertEqual(
            read_source_sidecar(self.store, self.snapshot_id, sid),
            {"state": "INCOMPLETE"},
        )


if __name__ == "__main__":
    unittest.main()


class UnsupportedPlatformTests(unittest.TestCase):
    def test_sidecar_reader_fails_closed_without_dir_fd_support(self):
        from unittest.mock import patch

        with tempfile.TemporaryDirectory() as directory:
            store = Store(Path(directory) / "private")
            with patch("canvas_mcp.gradebook.store._SUPPORTS_OPEN_DIR_FD", False):
                with self.assertRaises(GradebookError):
                    store._load_source_sidecar("a" * 64)


class ImportOrderTests(unittest.TestCase):
    def test_store_and_sidecar_import_in_both_orders(self):
        import subprocess
        import sys

        first = "import canvas_mcp.gradebook.store; import canvas_mcp.gradebook.source_sidecar_store"
        second = "import canvas_mcp.gradebook.source_sidecar_store; import canvas_mcp.gradebook.store"
        for code in (first, second):
            with self.subTest(code=code):
                result = subprocess.run(
                    [sys.executable, "-c", code],
                    capture_output=True,
                    text=True,
                    check=False,
                )
                self.assertEqual(result.returncode, 0, result.stderr)
