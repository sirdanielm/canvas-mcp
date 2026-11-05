import copy

from test_source_sidecar_store import SidecarStoreTests

from canvas_mcp.gradebook.client import GradebookError
from canvas_mcp.gradebook.source_sidecar_store import (
    read_source_sidecar,
    save_source_sidecar,
)


class SecondReview(SidecarStoreTests):
    def test_deep_json_generic_load_fails_closed(self):
        sid = "a" * 64
        (self.store.root / f"source_sidecar-{sid}.json").write_text(
            "[" * 20000 + "0" + "]" * 20000, encoding="utf-8"
        )
        with self.assertRaises(GradebookError):
            self.store.load("source_sidecar", sid)

    def test_deep_json_wrapper_is_incomplete(self):
        sid = "b" * 64
        (self.store.root / f"source_sidecar-{sid}.json").write_text(
            "[" * 20000 + "0" + "]" * 20000, encoding="utf-8"
        )
        self.assertEqual(
            read_source_sidecar(self.store, self.snapshot_id, sid),
            {"state": "INCOMPLETE"},
        )

    def test_invalid_dns_labels_and_empty_port(self):
        for origin in (
            "https://-bad.example.test",
            "https://bad-.example.test",
            "https://good.-bad.test",
            "https://canvas.example.test:",
        ):
            with self.subTest(origin=origin):
                snapshot = copy.deepcopy(self.snapshot)
                snapshot["origin"] = origin
                snapshot_id, _ = self.store.save("snapshot", snapshot)
                side = copy.deepcopy(self.sidecar)
                side["origin"] = origin
                with self.assertRaises(GradebookError):
                    save_source_sidecar(self.store, snapshot_id, side)

    def test_safe_dns_labels_and_explicit_port_are_accepted(self):
        origin = "https://canvas-1.school.example:8443"
        snapshot = copy.deepcopy(self.snapshot)
        snapshot["origin"] = origin
        snapshot_id, _ = self.store.save("snapshot", snapshot)
        side = copy.deepcopy(self.sidecar)
        side["origin"] = origin
        sid = save_source_sidecar(self.store, snapshot_id, side)
        self.assertEqual(
            read_source_sidecar(self.store, snapshot_id, sid)["state"], "HELD"
        )

    def test_overlong_dns_labels_rejected(self):
        origin = "https://" + "a" * 64 + ".example.test"
        snapshot = copy.deepcopy(self.snapshot)
        snapshot["origin"] = origin
        snapshot_id, _ = self.store.save("snapshot", snapshot)
        side = copy.deepcopy(self.sidecar)
        side["origin"] = origin
        with self.assertRaises(GradebookError):
            save_source_sidecar(self.store, snapshot_id, side)
