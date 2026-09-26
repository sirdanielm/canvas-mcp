"""Explicitly confirmed score/excusal pushes with no uncertain-write retries."""

from __future__ import annotations

import html
import os
from datetime import UTC, datetime
from typing import Any

import httpx

from .client import GradebookClient, GradebookError
from .ledger import Ledger
from .model import compare_edits, digest, grade_value, identifier, submission_cell
from .store import Store


class WriteUncertain(GradebookError):
    """The request might have reached Canvas. Readback only; never resend."""


class WriteRejected(GradebookError):
    """Canvas explicitly rejected this individual request."""


def target_key(origin: str, course_id: str, change: dict[str, Any]) -> str:
    return ":".join((origin, course_id, change["user_id"], change["assignment_id"]))


async def context(
    client: GradebookClient, course_id: str, uid: str, aid: str
) -> dict[str, Any]:
    root = f"/courses/{identifier(course_id)}/assignments/{identifier(aid)}"
    assignment = await client.get(root)
    submission = await client.get(
        root + "/submissions/" + identifier(uid), {"include[]": "visibility"}
    )
    if (
        not isinstance(assignment, dict)
        or str(assignment.get("id")) != aid
        or str(assignment.get("course_id")) != course_id
    ):
        raise GradebookError("Assignment identity did not match the reviewed target.")
    if (
        not isinstance(submission, dict)
        or str(submission.get("user_id")) != uid
        or str(submission.get("assignment_id")) != aid
    ):
        raise GradebookError("Submission identity did not match the reviewed target.")
    return {
        "assignment": {
            k: assignment.get(k)
            for k in (
                "id",
                "course_id",
                "published",
                "points_possible",
                "grading_type",
                "moderated_grading",
                "anonymous_grading",
                "group_category_id",
                "use_rubric_for_grading",
                "has_sub_assignments",
                "due_at",
                "grading_standard_id",
                "submission_types",
                "rubric_settings",
            )
        },
        "submission": submission_cell(submission),
        "closed_period": submission.get("in_closed_grading_period"),
    }


def require_simple_target(ctx: dict[str, Any], proposed: Any) -> None:
    assignment, submission = ctx["assignment"], ctx["submission"]
    if assignment["published"] is not True or assignment["grading_type"] != "points":
        raise GradebookError("Only published points assignments can be pushed.")
    if (
        assignment["moderated_grading"] is not False
        or assignment["anonymous_grading"] is not False
    ):
        raise GradebookError(
            "Anonymous or moderated grading requires the Canvas workflow."
        )
    if assignment["group_category_id"] is not None or assignment["has_sub_assignments"]:
        raise GradebookError(
            "Group and multi-part assignments require the Canvas workflow."
        )
    if assignment["use_rubric_for_grading"] or (
        assignment.get("rubric_settings") or {}
    ).get("use_for_grading"):
        raise GradebookError(
            "Rubric-controlled grades require the Canvas rubric workflow."
        )
    if submission["visible"] is not True or ctx["closed_period"] is True:
        raise GradebookError(
            "Assignment visibility or grading-period restrictions block this target."
        )
    if submission.get("grade_matches_current_submission") is False:
        raise GradebookError(
            "A newer submission needs review before changing its grade."
        )
    if submission.get("points_deducted"):
        raise GradebookError(
            "Late-policy deductions require the Canvas grading workflow."
        )
    value = grade_value(proposed)
    before = submission["value"]
    if (
        value is None
        or before == "EX"
        or (
            isinstance(value, (int, float))
            and (
                assignment["points_possible"] is None
                or value > assignment["points_possible"]
                or (isinstance(before, (int, float)) and value < before)
            )
        )
    ):
        raise GradebookError(
            "Blank, decreased, over-maximum, or unexcused grades are held."
        )


async def put_once(
    client: GradebookClient, course_id: str, change: dict[str, Any]
) -> None:
    """One PUT only. No grade comments, posting-policy or status changes."""
    value = grade_value(change["proposed"])
    if value is None:
        raise GradebookError("Blank grades cannot be pushed.")
    payload = (
        {"submission": {"excuse": True}}
        if value == "EX"
        else {"submission": {"posted_grade": format(float(value), ".15g")}}
    )
    url = (
        f"{client.origin}/api/v1/courses/{identifier(course_id)}/assignments/"
        f'{identifier(change["assignment_id"])}/submissions/{identifier(change["user_id"])}'
    )
    try:
        response = await client.http.put(url, json=payload)
    except httpx.HTTPError as exc:
        raise WriteUncertain(
            "Canvas write transport failed; readback required, no retry."
        ) from exc
    if response.status_code in (400, 401, 403, 404, 409, 422, 429):
        raise WriteRejected(
            f"Canvas rejected the write with HTTP {response.status_code}; no retry."
        )
    if response.status_code != 200:
        raise WriteUncertain(
            "Canvas write outcome is uncertain; readback required, no retry."
        )
    # A 200 response is not sufficient: the caller always performs semantic GET readback.


def matches_proposal(ctx: dict[str, Any], item: dict[str, Any]) -> bool:
    cell = ctx["submission"]
    expected = item["expected"]["submission"]
    return bool(
        cell["value"] == item["proposed"]
        and cell["excused"] == (item["proposed"] == "EX")
        and cell["attempt"] == expected["attempt"]
        and cell["submitted_at"] == expected["submitted_at"]
        and ctx["assignment"] == item["expected"]["assignment"]
    )


def write_review_html(store: Store, review: dict[str, Any]) -> str:
    """Private teacher artifact; escape all Canvas-authored text, no scripts."""
    baseline = store.load("snapshot", review["baseline_id"])
    students = {s["id"]: s for s in baseline["students"]}
    assignments = {a["id"]: a for a in baseline["assignments"]}

    def escape(value: Any) -> str:
        return html.escape("—" if value is None else str(value))

    rows = []
    for change in review["changes"]:
        student = students.get(change["user_id"], {})
        assignment = assignments.get(change["assignment_id"], {})
        values = [
            student.get("name", "Unavailable target"),
            ", ".join(student.get("sections", [])),
            assignment.get("name", "Unavailable assignment"),
            change["baseline"],
            change["current"],
            change["proposed"],
            ", ".join(change["reasons"]) or "Ready for confirmation",
        ]
        rows.append(
            "<tr>" + "".join("<td>" + escape(v) + "</td>" for v in values) + "</tr>"
        )
    content = """<!doctype html><html lang="en"><meta charset="utf-8">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'">
<title>Canvas gradebook change review</title><style>
body{font:16px system-ui;margin:32px;color:#2d3b45}table{border-collapse:collapse;width:100%}
th,td{border:1px solid #dfe3e6;padding:10px;text-align:left}th{background:#f2f3f4}
h1{color:#0869b2}p{max-width:900px}</style><h1>Canvas gradebook change review</h1>
<p>These are teacher-entered proposals. No grades have been sent by this review.
Blank cells do not clear grades. Holds must be resolved before a push. A confirmed
push can make grades visible under the course's existing Canvas posting policy.</p>"""
    content += "<p>Review reference: " + digest(review) + "</p><table><thead><tr>"
    content += "".join(
        "<th>" + x + "</th>"
        for x in [
            "Student",
            "Section",
            "Assignment",
            "Original",
            "Canvas now",
            "Proposed",
            "Review status",
        ]
    )
    content += "</tr></thead><tbody>" + "".join(rows) + "</tbody></table></html>"
    path = store.root / ("review-" + digest(review) + ".html")
    if path.is_symlink():
        raise GradebookError("Review file must not be a symlink.")
    try:
        with open(
            path, "x", opener=lambda p, flags: os.open(p, flags, 0o600)
        ) as stream:
            stream.write(content)
    except FileExistsError:
        if path.read_text() != content:
            raise GradebookError(
                "Existing review display failed integrity verification."
            ) from None
    return str(path)


class Publisher:
    def __init__(self, client: GradebookClient, store: Store, ledger: Ledger) -> None:
        self.client, self.store, self.ledger = client, store, ledger

    async def prepare(self, course_id: str, review_id: str) -> dict[str, Any]:
        review = self.store.load("review", review_id)
        baseline = self.store.load("snapshot", review["baseline_id"])
        if (baseline["course_id"], baseline["origin"]) != (
            course_id,
            self.client.origin,
        ):
            raise GradebookError("Review does not match the course and origin.")
        edits = {
            "course_id": course_id,
            "snapshot_id": digest(baseline),
            "edits": [
                {
                    "user_id": c["user_id"],
                    "assignment_id": c["assignment_id"],
                    "value": c["proposed"],
                }
                for c in review["changes"]
            ],
        }
        current = await self.client.snapshot(course_id)
        if current.get("course_workflow_state") != "available":
            raise GradebookError("Only an active, available course can accept a push.")
        self.store.save("snapshot", current)
        fresh = compare_edits(baseline, current, edits)
        fresh_id, _ = self.store.save("review", fresh)
        display = write_review_html(self.store, fresh)
        if not fresh["changes"] or fresh["counts"].get("review_required"):
            return {
                "ready_for_confirmation": False,
                "review_id": fresh_id,
                "review_file": display,
                "counts": fresh["counts"],
                "canvas_writes": 0,
            }
        if len(fresh["changes"]) > 25:
            raise GradebookError(
                "Push is limited to 25 reviewed changes per operation."
            )
        items = []
        for change in fresh["changes"]:
            ctx = await context(
                self.client, course_id, change["user_id"], change["assignment_id"]
            )
            key = change["user_id"] + ":" + change["assignment_id"]
            if ctx["submission"] != current["cells"][key]:
                raise GradebookError(
                    "Canvas changed during push preparation; prepare a new review."
                )
            require_simple_target(ctx, change["proposed"])
            items.append({**change, "expected": ctx})
        plan = {
            "schema_version": 1,
            "origin": self.client.origin,
            "course_id": course_id,
            "review_id": fresh_id,
            "current_id": digest(current),
            "created_at": datetime.now(UTC).isoformat(),
            "items": items,
        }
        plan_id, _ = self.store.save("push", plan)
        operation_id, token = self.ledger.prepare(
            plan_id, [target_key(self.client.origin, course_id, c) for c in items]
        )
        return {
            "ready_for_confirmation": True,
            "operation_id": operation_id,
            "confirmation_token": token,
            "expires_in_seconds": 600,
            "review_file": display,
            "review_id": fresh_id,
            "changes": len(items),
            "notice": "Show the private review to the teacher and get approval of this exact push. Existing Canvas posting policies apply.",
            "canvas_writes": 0,
        }

    async def confirm(
        self, course_id: str, operation_id: str, token: str
    ) -> dict[str, Any]:
        operation = self.ledger.operation(operation_id)
        plan = self.store.load("push", operation["plan_id"])
        if (plan["course_id"], plan["origin"]) != (course_id, self.client.origin):
            raise GradebookError(
                "Push operation belongs to a different course or origin."
            )
        with self.ledger.exclusive(operation_id):
            self.ledger.claim(operation_id, token)
            try:
                current = await self.client.snapshot(
                    course_id
                )  # permission + active roster
                if current.get("course_workflow_state") != "available":
                    raise GradebookError("Course is no longer available; push held.")
                active = {s["id"] for s in current["students"]}
                published = {a["id"] for a in current["assignments"]}
                # Reject the entire operation before the first PUT if any target changed.
                for item in plan["items"]:
                    if (
                        item["user_id"] not in active
                        or item["assignment_id"] not in published
                        or current["cells"].get(
                            item["user_id"] + ":" + item["assignment_id"]
                        )
                        != item["expected"]["submission"]
                    ):
                        raise GradebookError(
                            "Canvas changed after the preview; no push may start."
                        )
                for index, item in enumerate(plan["items"]):
                    live = await context(
                        self.client, course_id, item["user_id"], item["assignment_id"]
                    )
                    if live != item["expected"]:
                        self.ledger.mark(operation_id, index, "conflict")
                        break
                    require_simple_target(live, item["proposed"])
                    self.ledger.mark(operation_id, index, "sending")
                    try:
                        await put_once(self.client, course_id, item)
                    except WriteRejected:
                        self.ledger.mark(operation_id, index, "rejected")
                        break
                    except WriteUncertain:
                        self.ledger.mark(operation_id, index, "uncertain")
                        break
                    result = await context(
                        self.client, course_id, item["user_id"], item["assignment_id"]
                    )
                    if not matches_proposal(result, item):
                        self.ledger.mark(operation_id, index, "uncertain")
                        break
                    self.ledger.mark(operation_id, index, "verified")
            except Exception:
                # Any item at 'sending' remains uncertain, including cancellation/crash
                # (a process crash skips this block, leaving the same durable state).
                self.ledger.finish(operation_id)
                raise
            return self.ledger.finish(operation_id)

    async def reconcile(self, course_id: str, operation_id: str) -> dict[str, Any]:
        operation = self.ledger.operation(operation_id)
        plan = self.store.load("push", operation["plan_id"])
        if (plan["course_id"], plan["origin"]) != (course_id, self.client.origin):
            raise GradebookError(
                "Push operation belongs to a different course or origin."
            )
        with self.ledger.exclusive(operation_id):
            if operation["status"] == "prepared":
                return self.ledger.summary(operation_id)
            for item in operation["items"]:
                if item["status"] not in ("sending", "uncertain"):
                    continue
                target = plan["items"][item["position"]]
                live = await context(
                    self.client, course_id, target["user_id"], target["assignment_id"]
                )
                if matches_proposal(live, target):
                    self.ledger.mark(operation_id, item["position"], "observed_applied")
                else:
                    self.ledger.mark(operation_id, item["position"], "uncertain")
            return self.ledger.finish(operation_id)
