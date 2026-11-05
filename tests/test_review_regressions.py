import copy
import os
import subprocess
import sys

from test_source_sidecar_store import SidecarStoreTests

from canvas_mcp.gradebook.client import GradebookError
from canvas_mcp.gradebook.source_sidecar_store import (
    read_source_sidecar,
    save_source_sidecar,
)


class ReviewRegressions(SidecarStoreTests):
    def test_reject_origin_query_even_matching_snapshot(self):
        bad = copy.deepcopy(self.snapshot)
        bad["origin"] = "https://canvas.example.test/?token=fictional"
        bid, _ = self.store.save("snapshot", bad)
        side = copy.deepcopy(self.sidecar)
        side["origin"] = bad["origin"]
        with self.assertRaises(GradebookError):
            save_source_sidecar(self.store, bid, side)

    def test_reject_arbitrary_hold_text(self):
        side = copy.deepcopy(self.sidecar)
        side["cells"]["20:30"]["holds"].append("FICTIONAL_STUDENT_PRIVATE_INFORMATION")
        with self.assertRaises(GradebookError):
            save_source_sidecar(self.store, self.snapshot_id, side)

    def test_fifo_fails_closed_without_blocking(self):
        sid = "e" * 64
        os.mkfifo(self.store.root / f"source_sidecar-{sid}.json")
        code = 'from pathlib import Path; from canvas_mcp.gradebook.store import Store; from canvas_mcp.gradebook.source_sidecar_store import read_source_sidecar; import sys; print(read_source_sidecar(Store(Path(sys.argv[1])),sys.argv[2],sys.argv[3])["state"])'
        result = subprocess.run(
            [sys.executable, "-c", code, str(self.store.root), self.snapshot_id, sid],
            capture_output=True,
            text=True,
            timeout=2,
        )
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout.strip(), "INCOMPLETE")

    def test_empty_cells_are_incomplete(self):
        empty = dict(self.snapshot, cells={})
        eid, _ = self.store.save("snapshot", empty)
        obs = dict(self.sidecar, cells={})
        sid = save_source_sidecar(self.store, eid, obs)
        self.assertEqual(
            read_source_sidecar(self.store, eid, sid)["state"], "INCOMPLETE"
        )

    def test_no_reference_does_not_prove_absence(self):
        save_source_sidecar(self.store, self.snapshot_id, self.sidecar)
        self.assertEqual(
            read_source_sidecar(self.store, self.snapshot_id, None)["state"],
            "REFERENCE_UNKNOWN",
        )


class RaceAndOriginTests(SidecarStoreTests):
    def test_racing_replacement_with_symlink_and_fifo_fails_closed(self):
        from unittest.mock import patch

        for kind in ("symlink", "fifo"):
            sid = save_source_sidecar(self.store, self.snapshot_id, self.sidecar)
            target = self.store.root / f"source_sidecar-{sid}.json"
            original_open = os.open
            swapped = []

            def swapping_open(
                path,
                flags,
                *args,
                _target=target,
                _kind=kind,
                _original_open=original_open,
                _swapped=swapped,
                **kwargs,
            ):
                if path == _target.name:
                    _swapped.append(True)
                    _target.unlink()
                    if _kind == "symlink":
                        _target.symlink_to(self.path)
                    else:
                        os.mkfifo(_target)
                return _original_open(path, flags, *args, **kwargs)

            with patch("canvas_mcp.gradebook.store.os.open", side_effect=swapping_open):
                self.assertEqual(
                    read_source_sidecar(self.store, self.snapshot_id, sid),
                    {"state": "INCOMPLETE"},
                )
            self.assertEqual(swapped, [True])
            target.unlink()

    def test_query_fragment_userinfo_and_paths_rejected(self):
        for origin in (
            "https://canvas.example.test/?",
            "https://canvas.example.test/#",
            "https://user@canvas.example.test",
            "https://canvas.example.test/path",
            "http://canvas.example.test",
            "https://canvas.example.test:bad",
        ):
            with self.subTest(origin=origin):
                snapshot = copy.deepcopy(self.snapshot)
                snapshot["origin"] = origin
                bid, _ = self.store.save("snapshot", snapshot)
                side = copy.deepcopy(self.sidecar)
                side["origin"] = origin.rstrip("/")
                with self.assertRaises(GradebookError):
                    save_source_sidecar(self.store, bid, side)
