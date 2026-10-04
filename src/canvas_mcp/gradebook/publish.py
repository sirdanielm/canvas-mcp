"""Explicitly confirmed score/excusal pushes with no uncertain-write retries."""

from __future__ import annotations

import hashlib
import html
import json
import os
import re
from dataclasses import asdict
from datetime import UTC, datetime
from typing import Any

import httpx

from canvas_mcp.core.untrusted_content import contains_fence_markers

from .client import GradebookClient, GradebookError
from .ledger import Ledger
from .model import compare_edits, digest, grade_value, identifier, submission_cell
from .store import Store
from .unit1_canvas_protocol import (
    CanvasTarget,
    ExactObservation,
    FormRequestSpec,
    OriginalGet,
    _component,
    build_form_request_spec,
    compare_comment_readback,
    parse_exact_observation,
)

COMMENT_PLAN = "GRADEBOOK_COMMENT_PUSH_V1"


def comment_envelope(value: dict[str, Any], origin: str, course_id: str) -> None:
    """An exact private proposal, never evidence of teacher acceptance."""
    fields = {
        "schema_version",
        "origin",
        "course_id",
        "user_id",
        "assignment_id",
        "source_sha256",
        "source_revision",
        "decision_sha256",
        "attempt",
        "submitted_at",
        "category",
        "comment",
    }
    if (
        set(value) != fields
        or type(value["schema_version"]) is not int
        or value["schema_version"] != 1
    ):
        raise GradebookError("Invalid exact comment proposal schema.")
    if (value["origin"], value["course_id"]) != (origin, course_id):
        raise GradebookError(
            "Comment proposal belongs to a different course or origin."
        )
    for name in ("course_id", "user_id", "assignment_id"):
        if type(value[name]) is not str or identifier(value[name]) != value[name]:
            raise GradebookError("Comment target identities must be exact text IDs.")
    for name in ("source_sha256", "decision_sha256"):
        if (
            type(value[name]) is not str
            or re.fullmatch(r"[a-f0-9]{64}", value[name]) is None
        ):
            raise GradebookError(
                "An exact retained source and decision reference is required."
            )
    if (
        type(value["source_revision"]) is not str
        or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}", value["source_revision"])
        is None
    ):
        raise GradebookError("An exact retained source revision is required.")
    if type(value["category"]) is not str or value["category"] not in {
        "CONFIRMED_MISSING",
        "WRONG_ASSIGNMENT",
        "FORMATIVE_CORRECTION",
        "UNIT1_FEEDBACK",
    }:
        raise GradebookError("Comment category is outside the reviewed scope.")
    if value["attempt"] is not None and (
        type(value["attempt"]) is not int or value["attempt"] < 0
    ):
        raise GradebookError("Invalid observed Canvas attempt.")
    body = value["comment"]
    if (
        type(body) is not str
        or not 0 < len(body) <= 6000
        or body != body.strip()
        or "\r" in body
        or contains_fence_markers(body)
    ):
        raise GradebookError(
            "Exact normalized feedback is required; provenance markers are forbidden."
        )


def parse_comment_state(
    target: CanvasTarget, state: dict[str, Any]
) -> ExactObservation:
    """Reuse the original-byte parser; do not rewrite Canvas observations."""
    a, s = state["assignment"], state["submission"]
    a_body, s_body = a["body"].encode("utf-8"), s["body"].encode("utf-8")
    return parse_exact_observation(
        target,
        OriginalGet("GET", a["url"], 200, a_body),
        OriginalGet("GET", s["url"], 200, s_body, s["coverage_complete"]),
        expected_assignment_body_sha256=hashlib.sha256(a_body).hexdigest(),
        expected_submission_body_sha256=hashlib.sha256(s_body).hexdigest(),
        comment_only=True,
    )


async def comment_state(
    client: GradebookClient, target: CanvasTarget
) -> dict[str, Any]:
    root = f"{client.origin}/api/v1/courses/{target.course_id}/assignments/{target.assignment_id}"
    assignment = await client._get(root)
    submission = await client._get(
        root + "/submissions/" + target.user_id,
        [("include[]", "visibility"), ("include[]", "submission_comments")],
    )
    if assignment.links.get("next") or submission.links.get("next"):
        raise GradebookError(
            "Exact comment GET was paginated; completeness is unverified."
        )
    # Canvas's single-submission serializer includes all readable non-draft
    # comments for include[]=submission_comments; the parser separately rejects
    # missing arrays, malformed identities and duplicate IDs. Not global/draft coverage.
    return {
        "assignment": {
            "url": str(assignment.request.url),
            "body": assignment.content.decode("utf-8"),
        },
        "submission": {
            "url": str(submission.request.url),
            "body": submission.content.decode("utf-8"),
            "coverage_complete": True,
        },
    }


def comment_spec(
    target: CanvasTarget, state: dict[str, Any], envelope: dict[str, Any], author: str
) -> tuple[ExactObservation, FormRequestSpec]:
    observation = parse_comment_state(target, state)
    holds = set(observation.holds) - {
        "teacher_final_authority_not_connected",
        "comment_only_observation",
    }
    if holds:
        raise GradebookError(
            "Exact comment target is held: " + ", ".join(sorted(holds))
        )
    if (
        observation.submission_field("attempt").value,
        observation.submission_field("submitted_at").value,
    ) != (envelope["attempt"], envelope["submitted_at"]):
        raise GradebookError(
            "Canvas attempt does not match the retained source proposal."
        )
    types = observation.assignment_field("submission_types").value
    attempt = None
    if envelope["category"] == "CONFIRMED_MISSING" and (
        envelope["attempt"] not in (None, 0)
        or envelope["submitted_at"] is not None
        or observation.submission_field("workflow_state").value != "unsubmitted"
        or observation.submission_field("score").value is not None
    ):
        raise GradebookError(
            "Missing-work proposal disagrees with the observed submission."
        )
    if types != ("on_paper",):
        if envelope["category"] != "CONFIRMED_MISSING":
            if (
                type(envelope["attempt"]) is not int
                or envelope["attempt"] < 1
                or type(envelope["submitted_at"]) is not str
            ):
                raise GradebookError(
                    "An uploaded-work comment needs a source-bound Canvas attempt."
                )
            attempt = envelope["attempt"]
    binding = digest(
        {
            "target": asdict(target),
            "source_sha256": envelope["source_sha256"],
            "source_revision": envelope["source_revision"],
            "attempt": envelope["attempt"],
            "submitted_at": envelope["submitted_at"],
        }
    )
    component = digest(
        _component(
            target,
            envelope["decision_sha256"],
            binding,
            "COMMENT",
            envelope["comment"],
            author,
            attempt,
        )
    )
    spec = build_form_request_spec(
        observation,
        decision_sha256=envelope["decision_sha256"],
        target_binding_sha256=binding,
        channel="COMMENT",
        payload=envelope["comment"],
        publisher_author_id=author,
        expected_retained_observation_sha256=digest(asdict(observation)),
        expected_component_sha256=component,
        comment_attempt=attempt,
    )
    return observation, spec


def comment_review_html(store: Store, plan: dict[str, Any]) -> str:
    body = plan["envelope"]
    escaped = html.escape(
        json.dumps({k: v for k, v in body.items() if k != "comment"}, indent=2)
    )
    content = (
        '<!doctype html><meta charset="utf-8">'
        "<meta http-equiv=\"Content-Security-Policy\" content=\"default-src 'none'; style-src 'unsafe-inline'\">"
        "<title>Exact Canvas comment review</title><h1>Review one student-visible comment</h1>"
        "<p>This appends feedback. It sends no grade or status change. Existing Canvas posting policy may make feedback or an existing grade visible. "
        "Source hashes bind the proposal; they do not establish academic acceptance. Approve this exact target, source, attempt and text separately.</p>"
        "<pre>"
        + escaped
        + "</pre><h2>Exact comment</h2><pre>"
        + html.escape(body["comment"])
        + "</pre>"
    )
    path = store.root / ("comment-review-" + digest(plan) + ".html")
    if path.is_symlink():
        raise GradebookError("Comment review must not be a symlink.")
    with open(path, "x", opener=lambda p, flags: os.open(p, flags, 0o600)) as stream:
        stream.write(content)
    return str(path)


async def put_comment_once(
    client: GradebookClient, spec: FormRequestSpec, before: ExactObservation
) -> str:
    """One append through the existing publisher transport; no automatic retry."""
    try:
        response = await client.http.put(
            spec.url,
            content=spec.encoded_body,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
    except httpx.HTTPError as exc:
        raise WriteUncertain(
            "Comment transport failed; readback only, no retry."
        ) from exc
    if response.status_code in (400, 401, 403, 404, 409, 422, 429):
        raise WriteRejected(
            f"Canvas rejected the comment with HTTP {response.status_code}; no retry."
        )
    if response.status_code != 200:
        raise WriteUncertain("Comment outcome is uncertain; readback only.")
    try:
        raw = response.json()
        if (
            str(raw["assignment_id"]) != spec.target.assignment_id
            or str(raw["user_id"]) != spec.target.user_id
        ):
            raise ValueError
        old = {c.comment_id for c in before.comments}
        matches = [
            c
            for c in raw["submission_comments"]
            if str(c.get("id")) not in old
            and str(c.get("author_id")) == spec.publisher_author_id
            and c.get("comment") == spec.payload
        ]
        if len(matches) != 1:
            raise ValueError
        cid = identifier(matches[0]["id"])
        if str(int(cid)) != cid:
            raise ValueError
        return cid
    except (ValueError, KeyError, TypeError, AttributeError, GradebookError):
        raise WriteUncertain(
            "Comment response identity was not verified; readback only."
        ) from None


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
        f"{identifier(change['assignment_id'])}/submissions/{identifier(change['user_id'])}"
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
    """Verify the result without discarding the reviewed target's safety state."""
    cell = ctx["submission"]
    expected = item["expected"]["submission"]
    excusing = item["proposed"] == "EX"
    # Grade text, graded_at and posted_at may change when Canvas grades/posts
    # under the existing posting policy. Neither a score nor an excusal owns
    # visibility, grading-period or attempt protections.
    unchanged = (
        "visible",
        "attempt",
        "submitted_at",
    )
    # Canvas clears derived late/missing flags and late-policy status when
    # excusing. Grading can also clear a computed missing flag, but cannot
    # clear an explicitly assigned missing status or introduce a new one.
    missing_matches = (
        cell["missing"] is False
        if excusing
        else cell["missing"] == expected["missing"]
        or (cell["missing"] is False and expected["late_policy_status"] is None)
    )
    # A successful grade can establish the current-attempt flag, but cannot
    # lose a previously observed true flag or introduce a newer-attempt hold.
    current_grade_matches = (
        cell["grade_matches_current_submission"]
        is expected["grade_matches_current_submission"]
    ) or (
        expected["grade_matches_current_submission"] is None
        and cell["grade_matches_current_submission"] is True
    )
    # Canvas clears a zero deduction to null when the result is no longer
    # late. Preserve that documented effect, not a new/changed deduction.
    deducted, before_deducted = cell["points_deducted"], expected["points_deducted"]
    deductions_match = (
        not isinstance(deducted, bool)
        and not isinstance(before_deducted, bool)
        and deducted == before_deducted
    ) or (
        deducted is None
        and type(before_deducted) in (int, float)
        and before_deducted == 0
        and cell["late"] is False
    )
    return bool(
        cell["value"] == item["proposed"]
        and cell["excused"] == excusing
        and all(
            type(cell[field]) is type(expected[field])
            and cell[field] == expected[field]
            for field in unchanged
        )
        and current_grade_matches
        and deductions_match
        and type(ctx["closed_period"]) is type(item["expected"]["closed_period"])
        and ctx["closed_period"] == item["expected"]["closed_period"]
        and ctx["assignment"] == item["expected"]["assignment"]
        and cell["workflow_state"] in (expected["workflow_state"], "graded")
        and missing_matches
        and cell["late"] == (False if excusing else expected["late"])
        and cell["late_policy_status"]
        == (None if excusing else expected["late_policy_status"])
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
        if plan.get("kind") == COMMENT_PLAN:
            raise GradebookError(
                "Use the separately enabled comment confirmation tool."
            )
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
        if plan.get("kind") == COMMENT_PLAN:
            raise GradebookError("Use comment reconciliation for this operation.")
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

    async def _comment_scope(self, course_id: str, envelope: dict[str, Any]) -> str:
        current = await self.client.snapshot(
            course_id
        )  # Existing permission/roster boundary.
        if (
            (
                current.get("origin"),
                current.get("course_id"),
                current.get("course_workflow_state"),
            )
            != (self.client.origin, course_id, "available")
            or envelope["user_id"] not in {s["id"] for s in current["students"]}
            or envelope["assignment_id"]
            not in {a["id"] for a in current["assignments"]}
        ):
            raise GradebookError(
                "Comment target is not active and published in the configured course."
            )
        profile = await self.client.get("/users/self/profile")
        if not isinstance(profile, dict):
            raise GradebookError("Comment publisher identity is unavailable.")
        return identifier(profile.get("id"))

    async def prepare_comment(
        self, course_id: str, filename: str, expected_envelope_sha256: str
    ) -> dict[str, Any]:
        """Preview one exact source-bound comment; append nothing, accept no grade."""
        if not filename.endswith(".json"):
            raise GradebookError("Use a private JSON comment proposal in the inbox.")
        envelope = self.store.read_edits(filename)
        if digest(envelope) != expected_envelope_sha256:
            raise GradebookError(
                "Comment source proposal changed; retain the exact owner reference."
            )
        comment_envelope(envelope, self.client.origin, course_id)
        author = await self._comment_scope(course_id, envelope)
        target = CanvasTarget(
            self.client.origin,
            course_id,
            envelope["assignment_id"],
            envelope["user_id"],
        )
        state = await comment_state(self.client, target)
        _, spec = comment_spec(target, state, envelope, author)
        plan = {
            "kind": COMMENT_PLAN,
            "schema_version": 1,
            "origin": self.client.origin,
            "course_id": course_id,
            "created_at": datetime.now(UTC).isoformat(),
            "filename": filename,
            "envelope_sha256": expected_envelope_sha256,
            "envelope": envelope,
            "expected": state,
            "author": author,
            "delivery_id": spec.component_sha256,
        }
        plan_id, _ = self.store.save("push", plan)
        display = comment_review_html(self.store, plan)
        operation_id, token = self.ledger.prepare(
            plan_id,
            [target_key(self.client.origin, course_id, envelope)],
            comment_delivery_ids=[spec.component_sha256],
        )
        return {
            "ready_for_confirmation": True,
            "operation_id": operation_id,
            "confirmation_token": token,
            "expires_in_seconds": 600,
            "review_file": display,
            "changes": 1,
            "canvas_writes": 0,
            "notice": "Approve this exact student-visible comment separately. A source digest or proposal is not teacher acceptance. Existing Canvas posting policy applies.",
        }

    def _comment_plan(self, course_id: str, operation_id: str) -> dict[str, Any]:
        operation = self.ledger.operation(operation_id)
        plan = self.store.load("push", operation["plan_id"])
        if plan.get("kind") != COMMENT_PLAN or (plan["course_id"], plan["origin"]) != (
            course_id,
            self.client.origin,
        ):
            raise GradebookError("Operation is not this course's exact comment plan.")
        return plan

    async def confirm_comment(
        self, course_id: str, operation_id: str, token: str
    ) -> dict[str, Any]:
        """One explicit confirmation uses the existing durable ledger, no retries."""
        plan = self._comment_plan(course_id, operation_id)
        envelope = plan["envelope"]
        target = CanvasTarget(
            self.client.origin,
            course_id,
            envelope["assignment_id"],
            envelope["user_id"],
        )
        with self.ledger.exclusive(operation_id):
            self.ledger.claim(operation_id, token)
            try:
                if (
                    digest(self.store.read_edits(plan["filename"]))
                    != plan["envelope_sha256"]
                ):
                    raise GradebookError(
                        "Source comment proposal changed after preview; nothing sent."
                    )
                if await self._comment_scope(course_id, envelope) != plan["author"]:
                    raise GradebookError(
                        "Publisher identity changed after preview; nothing sent."
                    )
                fresh = await comment_state(self.client, target)
                before, spec = comment_spec(target, fresh, envelope, plan["author"])
                if (
                    fresh != plan["expected"]
                    or spec.component_sha256 != plan["delivery_id"]
                ):
                    raise GradebookError(
                        "Canvas comment target changed after preview; nothing sent."
                    )
                self.ledger.mark(operation_id, 0, "sending")
                try:
                    cid = await put_comment_once(self.client, spec, before)
                except WriteRejected:
                    self.ledger.mark(operation_id, 0, "rejected")
                    return self.ledger.finish(operation_id)
                except WriteUncertain:
                    self.ledger.mark(operation_id, 0, "uncertain")
                    return self.ledger.finish(operation_id)
                self.ledger.save_comment_response(operation_id, 0, cid)
                after_state = await comment_state(self.client, target)
                result = compare_comment_readback(
                    spec,
                    before,
                    parse_comment_state(target, after_state),
                    publisher_author_id=plan["author"],
                    response_received=True,
                    response_comment_id=cid,
                )
                receipt_id, _ = self.store.save(
                    "receipt",
                    {
                        "kind": "GRADEBOOK_COMMENT_READBACK_V1",
                        "operation_id": operation_id,
                        "delivery_id": spec.component_sha256,
                        "source_envelope_sha256": plan["envelope_sha256"],
                        "response_comment_id": cid,
                        "before": plan["expected"],
                        "after": after_state,
                        "comparison": asdict(result),
                        "at": datetime.now(UTC).isoformat(),
                    },
                )
                self.ledger.mark(
                    operation_id,
                    0,
                    "verified" if result.stored_verified else "uncertain",
                )
                return {
                    **self.ledger.finish(operation_id),
                    "readback_receipt_id": receipt_id,
                }
            except BaseException:
                # Cancellation/crash after sending retains the existing uncertain lock.
                self.ledger.finish(operation_id)
                raise

    async def reconcile_comment(
        self, course_id: str, operation_id: str
    ) -> dict[str, Any]:
        """GET only, including after process restart; never append again."""
        plan = self._comment_plan(course_id, operation_id)
        with self.ledger.exclusive(operation_id):
            operation = self.ledger.operation(operation_id)
            if operation["status"] == "prepared" or operation["items"][0][
                "status"
            ] not in ("sending", "uncertain"):
                return self.ledger.finish(operation_id)
            envelope = plan["envelope"]
            if await self._comment_scope(course_id, envelope) != plan["author"]:
                raise GradebookError(
                    "Publisher identity changed; comment reconciliation remains held."
                )
            target = CanvasTarget(
                self.client.origin,
                course_id,
                envelope["assignment_id"],
                envelope["user_id"],
            )
            before, spec = comment_spec(
                target, plan["expected"], envelope, plan["author"]
            )
            after_state = await comment_state(self.client, target)
            cid = operation["items"][0]["response_comment_id"]
            result = compare_comment_readback(
                spec,
                before,
                parse_comment_state(target, after_state),
                publisher_author_id=plan["author"],
                response_received=cid is not None,
                response_comment_id=cid,
            )
            receipt_id, _ = self.store.save(
                "receipt",
                {
                    "kind": "GRADEBOOK_COMMENT_RECONCILIATION_V1",
                    "operation_id": operation_id,
                    "delivery_id": spec.component_sha256,
                    "response_comment_id": cid,
                    "after": after_state,
                    "comparison": asdict(result),
                    "at": datetime.now(UTC).isoformat(),
                },
            )
            state = (
                "verified"
                if result.stored_verified
                else "observed_applied"
                if result.outcome == "OBSERVED_APPLIED"
                else "uncertain"
            )
            self.ledger.mark(operation_id, 0, state)
            return {
                **self.ledger.finish(operation_id),
                "readback_receipt_id": receipt_id,
            }
