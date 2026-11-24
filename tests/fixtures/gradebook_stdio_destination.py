"""Fictional Canvas endpoints persisted outside the MCP process for independent readback."""

import json
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl

import httpx

from canvas_mcp.gradebook.model import digest
from canvas_mcp.gradebook.store import Store

ORIGIN = "https://fixture.invalid"
COURSES = {"core": "12"}
COURSE = "/api/v1/courses/12"
ASSIGNMENT = COURSE + "/assignments/21"
SUBMISSION = ASSIGNMENT + "/submissions/101"
COMMENT = "Please include the unit with your answer."
GRADE = 15
SUBMITTED_AT = "2026-09-17T19:00:00Z"

ASSIGNMENT_DATA = {
    "id": 21,
    "course_id": 12,
    "name": "Fictional assignment",
    "published": True,
    "points_possible": 20,
    "grading_type": "points",
    "moderated_grading": False,
    "anonymous_grading": False,
    "group_category_id": None,
    "submission_types": ["on_paper"],
    "use_rubric_for_grading": False,
    "has_sub_assignments": False,
    "rubric_settings": None,
    "post_manually": False,
    "in_closed_grading_period": False,
}
INITIAL_SUBMISSION = {
    "id": 301,
    "user_id": 101,
    "assignment_id": 21,
    "score": 10,
    "grade": "10",
    "workflow_state": "graded",
    "assignment_visible": True,
    "attempt": 2,
    "submitted_at": SUBMITTED_AT,
    "graded_at": "2026-09-17T20:00:00Z",
    "posted_at": None,
    "updated_at": "2026-09-17T20:00:00Z",
    "excused": False,
    "grade_matches_current_submission": True,
    "in_closed_grading_period": False,
    "points_deducted": 0,
    "late_policy_status": None,
    "late": False,
    "missing": False,
    "submission_comments": [
        {"id": 501, "author_id": 777, "comment": "Earlier feedback"}
    ],
}


class Destination:
    """One serialized MCP writer. The test reads the independent destination file."""

    def __init__(self, root: Path) -> None:
        self.path = root / "destination.json"
        self.journal = root / "requests.jsonl"

    def initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("x", encoding="utf-8") as stream:
            json.dump(INITIAL_SUBMISSION, stream)
        self.journal.touch(exist_ok=False)

    def read_submission(self) -> dict[str, Any]:
        return json.loads(self.path.read_text(encoding="utf-8"))

    def requests(self) -> list[dict[str, Any]]:
        return [
            json.loads(line)
            for line in self.journal.read_text(encoding="utf-8").splitlines()
        ]

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self._respond)

    def _respond(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        event = {
            "method": request.method,
            "path": path,
            "query": request.url.params.multi_items(),
        }
        content_type = request.headers.get("content-type")
        fields = None
        if request.content:
            if content_type == "application/json":
                fields = json.loads(request.content)
            elif content_type == "application/x-www-form-urlencoded":
                pairs = parse_qsl(
                    request.content.decode(),
                    keep_blank_values=True,
                    strict_parsing=True,
                )
                fields = dict(pairs)
                assert len(pairs) == len(fields)
            event["fields"] = fields
        with self.journal.open("a", encoding="utf-8") as journal:
            journal.write(json.dumps(event) + "\n")
        assert request.url.copy_with(path="/", query=None) == httpx.URL(ORIGIN + "/")
        assert request.headers["authorization"] == "Bearer fictional"
        submission = self.read_submission()
        if request.method == "GET":
            endpoints = {
                "/api/v1/users/self/profile": {"id": 777},
                COURSE: {
                    "id": 12,
                    "name": "Fictional course",
                    "workflow_state": "available",
                },
                COURSE + "/permissions": {"manage_grades": True},
                COURSE + "/sections": [{"id": 7, "name": "Fictional section"}],
                COURSE + "/enrollments": [
                    {
                        "course_id": 12,
                        "course_section_id": 7,
                        "user_id": 101,
                        "type": "StudentEnrollment",
                        "enrollment_state": "active",
                        "user": {"id": 101, "name": "Fictional learner"},
                    }
                ],
                COURSE + "/assignments": [ASSIGNMENT_DATA],
                ASSIGNMENT: ASSIGNMENT_DATA,
                ASSIGNMENT + "/submissions": [submission],
                SUBMISSION: submission,
            }
            result = endpoints[path]
        else:
            assert (
                request.method == "PUT" and path == SUBMISSION and not request.url.query
            )
            assert fields is not None
            if content_type == "application/json":
                assert set(fields) == {"submission"} and set(fields["submission"]) == {
                    "posted_grade"
                }
                grade = fields["submission"]["posted_grade"]
                submission.update(
                    grade=grade, score=float(grade), graded_at="2026-09-17T20:00:01Z"
                )
            else:
                assert content_type == "application/x-www-form-urlencoded"
                assert set(fields) == {
                    "comment[text_comment]",
                    "comment[group_comment]",
                }
                assert fields["comment[group_comment]"] == "false"
                comments = submission["submission_comments"]
                comments.append(
                    {
                        "id": max(comment["id"] for comment in comments) + 1,
                        "author_id": 777,
                        "comment": fields["comment[text_comment]"],
                    }
                )
                submission["updated_at"] = "2026-09-17T20:00:02Z"
            next_path = self.path.with_suffix(".pending")
            next_path.write_text(json.dumps(submission), encoding="utf-8")
            next_path.replace(self.path)
            result = submission
        return httpx.Response(200, json=result)

    def write_inputs(self, store: Store, snapshot: dict[str, Any]) -> dict[str, str]:
        """Create ordinary teacher inputs. A fresh MCP preview can use the edits file."""
        edits = {
            "course_id": "12",
            "snapshot_id": digest(snapshot),
            "edits": [{"user_id": "101", "assignment_id": "21", "value": GRADE}],
        }
        decision = {
            "course_id": "12",
            "user_id": "101",
            "assignment_id": "21",
            "submission_id": "301",
            "attempt": 2,
            "comment": COMMENT,
        }
        source = {
            "type": "fictional-submission",
            "id": 301,
            "attempt": 2,
            "submitted_at": SUBMITTED_AT,
        }
        envelope = {
            "schema_version": 1,
            "origin": ORIGIN,
            "course_id": "12",
            "user_id": "101",
            "assignment_id": "21",
            "source_revision": "fictional.attempt.2",
            "source_sha256": digest(source),
            "decision_sha256": digest(decision),
            "attempt": 2,
            "submitted_at": SUBMITTED_AT,
            "category": "FORMATIVE_CORRECTION",
            "comment": COMMENT,
        }
        inbox = store.root / "inbox"
        inbox.mkdir(exist_ok=True)
        for name, record in {
            "synthetic-edits.json": edits,
            "synthetic-comment.json": envelope,
            "synthetic-source.json": source,
            "synthetic-decision.json": decision,
        }.items():
            (inbox / name).write_text(json.dumps(record), encoding="utf-8")
        return {
            "edits_filename": "synthetic-edits.json",
            "comments_filename": "synthetic-comment.json",
            "expected_envelope_sha256": digest(envelope),
        }
