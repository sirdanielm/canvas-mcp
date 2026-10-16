"""Private previews describe teacher review without claiming publish approval."""

from pathlib import Path

from test_gradebook import snapshot as snapshot

from canvas_mcp.gradebook.model import compare_edits, digest
from canvas_mcp.gradebook.publish import write_review_html
from canvas_mcp.gradebook.store import Store


def test_ready_preview_requires_teacher_review_and_creates_no_publisher_state(
    tmp_path, snapshot
):
    store = Store(tmp_path)
    store.save("snapshot", snapshot)
    review = compare_edits(
        snapshot,
        snapshot,
        {
            "course_id": "12",
            "snapshot_id": digest(snapshot),
            "edits": [{"user_id": "101", "assignment_id": "21", "value": 20}],
        },
    )
    display = Path(write_review_html(store, review)).read_text()
    assert "Ready for teacher review" in display
    assert "Ready for confirmation" not in display
    assert "No grades have been sent by this review" in display
    assert review["canvas_writes"] == 0
    assert not list(tmp_path.glob("push-*"))
    assert not (tmp_path / "ledger.sqlite3").exists()
