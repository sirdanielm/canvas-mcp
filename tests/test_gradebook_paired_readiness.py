import copy
import hashlib
import json
import sys
from pathlib import Path

import pytest

from canvas_mcp.gradebook.client import GradebookError
from canvas_mcp.gradebook.paired_readiness import (
    build_paired_readiness,
    load_paired_proposal,
    write_paired_review,
)


@pytest.fixture
def proposal():
    body = "Exact feedback <script>send()</script> α"
    encoded = body.encode()
    ref = {"path": "/private/source.json", "sha256": "a" * 64}
    records = []
    for i in range(166):
        records.append({
            "student_pin": f"{i:04d}", "course_id": "10", "assignment_id": "20",
            "canvas_user_id": str(i + 1), "course_lane": "Core",
            "source_final_percent": 60, "candidate_publish_points_preserving_higher_canvas": 70,
            "feedback_exact": body, "feedback_sha256": hashlib.sha256(encoded).hexdigest(),
            "feedback_utf8_bytes": len(encoded), "exact_source_joined_pair": True,
            "exact_saved_uid_current_pin_binding": True, "broader_history_provisional": False,
            "teacher_final_approval": False, "canvas_delivery_verified": False,
            "feedback_delivery_verified": False, "grade_source_ref": ref,
            "feedback_body_source_ref": ref, "independent_scope_ref": None,
            "current_status_exact": "Saved review only", "latest_saved_canvas_cell": {
                "visible": True, "value": 65, "excused": False,
                "grade_matches_current_submission": True, "points_deducted": None,
            }, "latest_saved_canvas_fetched_at": "2026-01-01T00:00:00+00:00",
        })
    return {"records_private": records, "approval_contract": {"draft": True},
            "limitations": ["No delivery authority"]}


def test_staged_is_never_approved_or_send_ready(proposal):
    before = copy.deepcopy(proposal)
    result = build_paired_readiness(proposal, proposal_sha256="a" * 64)
    assert proposal == before
    summary = result["aggregate_summary"]
    assert summary["pairs_staged"] == 166
    assert summary["approval_ready"] == summary["send_ready"] == 0
    assert summary["operations_prepared"] == summary["leases_created"] == 0
    assert summary["canvas_writes"] == 0
    assert all(x["state"] == "STAGED_NO_SEND" for x in result["records_private"])
    assert result["records_private"][0]["pair"] == proposal["records_private"][0]


@pytest.mark.parametrize("field,value", [
    ("feedback_exact", "changed"), ("feedback_utf8_bytes", True),
    ("teacher_final_approval", True), ("exact_source_joined_pair", False),
    ("candidate_publish_points_preserving_higher_canvas", float("nan")),
    ("source_final_percent", True), ("canvas_user_id", []),
    ("student_pin", "1"), ("grade_source_ref", {"path": "relative", "sha256": "a" * 64}),
    ("latest_saved_canvas_fetched_at", "2026-01-01"),
    ("feedback_exact", "\ud800"), ("feedback_exact", "body\x00tail"),
])
def test_malformed_evidence_holds_with_static_error(proposal, field, value):
    proposal["records_private"][0][field] = value
    with pytest.raises(GradebookError) as exc:
        build_paired_readiness(proposal, proposal_sha256="a" * 64)
    assert "changed" not in str(exc.value)
    assert "Canvas" not in str(exc.value)


def test_duplicate_target_holds(proposal):
    proposal["records_private"][1] = copy.deepcopy(proposal["records_private"][0])
    with pytest.raises(GradebookError):
        build_paired_readiness(proposal, proposal_sha256="a" * 64)


def test_source_scope_is_documentary_and_retained(proposal):
    scope = {"latest_independent_review_ref": {
        "path": "/private/independent.json", "sha256": "b" * 64,
        "bytes": 10, "json_pointer": "/record",
    }, "scope_class": "Saved scope only"}
    proposal["records_private"][0]["independent_scope_ref"] = scope
    result = build_paired_readiness(proposal, proposal_sha256="a" * 64)
    assert result["records_private"][0]["pair"]["independent_scope_ref"] == scope
    assert result["aggregate_summary"]["send_ready"] == 0


def test_individual_safety_holds_are_retained(proposal):
    records = proposal["records_private"]
    records[0]["latest_saved_canvas_cell"] = None
    records[1]["latest_saved_canvas_cell"].update(value="EX", excused=True)
    records[2]["latest_saved_canvas_cell"]["grade_matches_current_submission"] = False
    records[3]["latest_saved_canvas_cell"]["points_deducted"] = 2
    records[4]["latest_saved_canvas_cell"]["value"] = 90
    result = build_paired_readiness(proposal, proposal_sha256="a" * 64)
    counts = result["aggregate_summary"]["blocker_counts"]
    assert all(counts[k] == 1 for k in ("submission_evidence_required", "excused_target_protected",
               "newer_submission_review_required", "late_policy_review_required", "decrease_held"))


@pytest.mark.skipif(sys.platform == "win32", reason="Private review file modes require POSIX owner-only files")
def test_private_html_escapes_body_and_returns_no_rows(proposal, tmp_path):
    result = write_paired_review(tmp_path / "review", proposal, proposal_sha256="a" * 64)
    text = Path(result["review_file"]).read_text(encoding="utf-8")
    assert "&lt;script&gt;send()&lt;/script&gt;" in text
    assert "<script>" not in text
    assert "default-src 'none'" in text
    assert "records_private" not in result
    assert Path(result["review_file"]).stat().st_mode & 0o777 == 0o600
    assert (tmp_path / "review").stat().st_mode & 0o777 == 0o700


def test_pinned_read_rejects_wrong_sha_and_symlink(proposal, tmp_path):
    path = tmp_path / "proposal.json"
    raw = json.dumps(proposal).encode()
    path.write_bytes(raw)
    expected = hashlib.sha256(raw).hexdigest()
    assert load_paired_proposal(path, expected) == proposal
    with pytest.raises(GradebookError):
        load_paired_proposal(path, "b" * 64)
    link = tmp_path / "link.json"
    link.symlink_to(path)
    with pytest.raises(GradebookError):
        load_paired_proposal(link, expected)
