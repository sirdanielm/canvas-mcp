"""Source-only same-ID Unit2 comment edits on the canonical publisher's ledger.

No registration/enablement occurs on import. The existing publisher owner must
inject genuine current source/QC controls; envelope hashes are not acceptance.
No grading, rendering, deletion, append fallback or retry is provided here.
"""

from __future__ import annotations

import copy
import hashlib
import html
import json
import os
import re
import time
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlencode

import httpx
from fastmcp import FastMCP

from .client import GradebookError
from .comment_policy import FORMAT_CONTRACT_SHA256, inspect_body
from .model import digest, identifier
from .publish import (
    OwnerControls,
    Publisher,
    _owner_check,
    _owner_controls,
    comment_clock_limit,
    comment_envelope,
    comment_spec,
    comment_state,
    comment_target_unchanged,
    target_key,
)
from .unit1_canvas_protocol import CanvasTarget

ACTION = "EDIT_EXISTING_COMMENT"
PLAN_KIND = "GRADEBOOK_EXISTING_COMMENT_EDIT_V1"
BASE_FIELDS = {
    "schema_version",
    "origin",
    "course_id",
    "assignment_id",
    "user_id",
    "source_sha256",
    "source_revision",
    "decision_sha256",
    "attempt",
    "submitted_at",
    "category",
    "comment",
}
EDIT_FIELDS = {
    "action",
    "comment_id",
    "old_comment",
    "old_body_sha256",
    "old_comment_sha256",
    "new_body_sha256",
    "qc_sha256",
    "formatter_sha256",
    "format_contract_sha256",
    "expected_header",
    "disposition",
}


def _sha(text: str) -> str:
    try:
        return hashlib.sha256(text.encode("utf-8")).hexdigest()
    except UnicodeError:
        raise GradebookError("Exact UTF-8 comment bodies required.") from None


def _id(value: Any) -> str:
    if type(value) not in (int, str):
        raise GradebookError("Exact comment identity required.")
    result = identifier(value)
    if re.fullmatch(r"[1-9][0-9]*", result) is None:
        raise GradebookError("Exact comment identity required.")
    return result


def _controls(value: OwnerControls | None) -> OwnerControls:
    _owner_controls(value)
    if value is None:
        raise GradebookError("Current source/QC owner controls required; edit held.")
    return value


def _base(envelope: dict[str, Any]) -> dict[str, Any]:
    return {key: envelope[key] for key in BASE_FIELDS}


def _envelope(envelope: dict[str, Any], publisher: Publisher, course_id: str) -> None:
    if type(envelope) is not dict or set(envelope) != BASE_FIELDS | EDIT_FIELDS:
        raise GradebookError("Invalid exact existing-comment edit schema.")
    comment_envelope(_base(envelope), publisher.client.origin, course_id)
    if envelope["action"] != ACTION or envelope["category"] != "UNIT2_FEEDBACK":
        raise GradebookError("Only explicit Unit2 existing-comment EDIT is supported.")
    if (
        type(envelope["comment_id"]) is not str
        or _id(envelope["comment_id"]) != envelope["comment_id"]
    ):
        raise GradebookError("Exact existing comment ID required.")
    for key in (
        "old_body_sha256",
        "old_comment_sha256",
        "new_body_sha256",
        "qc_sha256",
        "formatter_sha256",
        "format_contract_sha256",
    ):
        if (
            type(envelope[key]) is not str
            or re.fullmatch(r"[a-f0-9]{64}", envelope[key]) is None
        ):
            raise GradebookError("Exact source/QC/format/body pins required.")
    old = envelope["old_comment"]
    if (
        type(old) is not dict
        or type(old.get("comment")) is not str
        or _id(old.get("id")) != envelope["comment_id"]
        or digest(old) != envelope["old_comment_sha256"]
        or _sha(old["comment"]) != envelope["old_body_sha256"]
        or _sha(envelope["comment"]) != envelope["new_body_sha256"]
    ):
        raise GradebookError("Exact existing comment preimage/body pins changed.")
    if (
        envelope["format_contract_sha256"] != FORMAT_CONTRACT_SHA256
        or type(envelope["expected_header"]) is not str
        or inspect_body(
            envelope["comment"], expected_header=envelope["expected_header"]
        )
    ):
        raise GradebookError("Current exact Unit2 V6 display binding required.")
    if envelope["disposition"] not in {"CONDITIONAL", "QUALIFIED_FOR_EXACT_REVIEW"}:
        raise GradebookError("Edit qualification disposition is invalid.")


def _target(publisher: Publisher, envelope: dict[str, Any]) -> CanvasTarget:
    return CanvasTarget(
        publisher.client.origin,
        envelope["course_id"],
        envelope["assignment_id"],
        envelope["user_id"],
    )


def _selected(state: dict[str, Any], cid: str) -> dict[str, Any]:
    comments = json.loads(state["submission"]["body"])["submission_comments"]
    matches = [c for c in comments if type(c) is dict and _id(c.get("id")) == cid]
    if len(matches) != 1:
        raise GradebookError("Existing comment membership is missing or ambiguous.")
    return matches[0]


def _admit(
    publisher: Publisher, envelope: dict[str, Any], state: dict[str, Any], author: str
) -> None:
    # Reuse all maintained permission/attempt/protected-state admission, without
    # using the append request specification or its readback comparator to send.
    comment_spec(_target(publisher, envelope), state, _base(envelope), author)
    old = _selected(state, envelope["comment_id"])
    if _id(old.get("author_id")) != author:
        raise GradebookError("Canvas edit requires the original comment author; held.")
    if any(
        key in old and old[key] is not None
        for key in ("group_comment_id", "provisional_grade_id", "assessment_request_id")
    ) or any(
        key in old and old[key] is not False for key in ("draft", "hidden", "anonymous")
    ):
        raise GradebookError(
            "Unsupported grouped/draft/provisional comment; edit held."
        )


def _delivery(envelope: dict[str, Any]) -> str:
    # Stable intent even if source/QC receipts are renewed: no duplicate edit of
    # the same ID/old/new bodies can bypass the existing durable delivery fence.
    return digest(
        {
            key: envelope[key]
            for key in (
                "action",
                "origin",
                "course_id",
                "assignment_id",
                "user_id",
                "comment_id",
                "old_body_sha256",
                "new_body_sha256",
            )
        }
    )


def _binding(controls: OwnerControls, plan: dict[str, Any]) -> dict[str, Any]:
    unbound = {key: value for key, value in plan.items() if key != "owner_binding"}
    bound = controls.bind_plan(copy.deepcopy(unbound))
    if type(bound) is not dict or not bound:
        raise GradebookError("Exact current owner qualification binding required.")
    digest(bound)  # Reject unserializable/nonfinite claimed bindings.
    return bound


def _review(publisher: Publisher, plan: dict[str, Any]) -> str:
    envelope = plan["envelope"]
    value = (
        '<!doctype html><meta charset="utf-8">'
        '<meta http-equiv="Content-Security-Policy" content="default-src \'none\'">'
        "<title>Exact existing-comment edit review</title><h1>EDIT_EXISTING_COMMENT</h1>"
        "<p>Replace only this existing comment ID. No deletion, new comment, score "
        "or acceptance is authorized by this artifact. Approve this exact old/new "
        "body, target and source/QC binding separately.</p><pre>"
        + html.escape(
            json.dumps(
                {
                    k: v
                    for k, v in envelope.items()
                    if k not in {"old_comment", "comment"}
                },
                indent=2,
            )
        )
        + "</pre><h2>Exact old body</h2><pre>"
        + html.escape(envelope["old_comment"]["comment"])
        + "</pre><h2>Exact replacement</h2><pre>"
        + html.escape(envelope["comment"])
        + "</pre>"
    )
    path = publisher.store.root / ("comment-edit-review-" + digest(plan) + ".html")
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as stream:
        stream.write(value)
        stream.flush()
        os.fsync(stream.fileno())
    return str(path)


async def prepare_comment_edit(
    publisher: Publisher,
    course_id: str,
    filename: str,
    expected_envelope_sha256: str,
    *,
    owner_controls: OwnerControls | None = None,
) -> dict[str, Any]:
    """Preview only; caller supplies a private inbox filename and owner digest."""
    controls = _controls(owner_controls)
    if not filename.endswith(".json"):
        raise GradebookError("Use an exact private JSON edit proposal.")
    envelope = publisher.store.read_edits(filename)
    if digest(envelope) != expected_envelope_sha256:
        raise GradebookError("Edit proposal changed; retain the exact owner reference.")
    _envelope(envelope, publisher, course_id)
    if envelope["disposition"] != "QUALIFIED_FOR_EXACT_REVIEW":
        return {
            "ready_for_confirmation": False,
            "canvas_writes": 0,
            "action": ACTION,
            "hold": "Conditional proposal remains conditional.",
        }
    await controls.fresh_before_context(course_id, copy.deepcopy(envelope))
    author = await publisher._comment_scope(course_id, envelope)
    state = await comment_state(publisher.client, _target(publisher, envelope))
    _admit(publisher, envelope, state, author)
    if (
        digest(_selected(state, envelope["comment_id"]))
        != envelope["old_comment_sha256"]
    ):
        raise GradebookError("Existing comment preimage changed; no preview prepared.")
    if envelope["old_comment"]["comment"] == envelope["comment"]:
        return {
            "ready_for_confirmation": False,
            "canvas_writes": 0,
            "action": ACTION,
            "hold": "Existing body already exactly matches; no edit.",
        }
    _owner_check(controls, course_id, copy.deepcopy(envelope))
    plan: dict[str, Any] = {
        "kind": PLAN_KIND,
        "action": ACTION,
        "origin": publisher.client.origin,
        "course_id": course_id,
        "created_at": datetime.now(UTC).isoformat(),
        "filename": filename,
        "envelope_sha256": expected_envelope_sha256,
        "envelope": envelope,
        "expected": state,
        "author": author,
        "delivery_id": _delivery(envelope),
    }
    plan["owner_binding"] = _binding(controls, plan)
    plan_id, _ = publisher.store.save("push", plan)
    display = _review(publisher, plan)
    operation_id, token = publisher.ledger.prepare(
        plan_id,
        [target_key(publisher.client.origin, course_id, envelope)],
        comment_delivery_ids=[plan["delivery_id"]],
        comment_approval_seconds=publisher.comment_approval_seconds,
    )
    return {
        "ready_for_confirmation": True,
        "action": ACTION,
        "operation_id": operation_id,
        "confirmation_token": token,
        "expires_in_seconds": publisher.comment_approval_seconds,
        "expires_at": publisher.ledger.operation(operation_id)["expires"],
        "review_file": display,
        "canvas_writes": 0,
        "notice": "Exact separate approval of this existing-ID edit is required.",
    }


def _plan(publisher: Publisher, course_id: str, operation_id: str) -> dict[str, Any]:
    operation = publisher.ledger.operation(operation_id)
    plan = publisher.store.load("push", operation["plan_id"])
    if (
        plan.get("kind"),
        plan.get("action"),
        plan.get("origin"),
        plan.get("course_id"),
    ) != (PLAN_KIND, ACTION, publisher.client.origin, course_id):
        raise GradebookError("Operation is not this exact existing-comment EDIT.")
    envelope = plan["envelope"]
    _envelope(envelope, publisher, course_id)
    if (
        envelope["disposition"] != "QUALIFIED_FOR_EXACT_REVIEW"
        or digest(envelope) != plan["envelope_sha256"]
        or _delivery(envelope) != plan["delivery_id"]
        or len(operation["items"]) != 1
        or operation["items"][0]["target"]
        != target_key(publisher.client.origin, course_id, envelope)
        or operation["items"][0].get("delivery_id") != plan["delivery_id"]
    ):
        raise GradebookError("Exact edit plan/ledger binding changed; held.")
    return plan


def _timestamp(value: Any) -> datetime:
    if type(value) is not str:
        raise ValueError
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError
    return parsed


def _clock(
    old: dict[str, Any],
    new: dict[str, Any],
    field: str,
    start: str,
    end: str,
    *,
    allow_added: bool = False,
) -> bool:
    if (
        field in old
        and field in new
        and old[field] == new[field]
        and type(old[field]) is type(new[field])
    ):
        return True
    if field not in old and field not in new:
        return True
    if field not in new or (field not in old and not allow_added):
        return False
    try:
        value = _timestamp(new[field])
        if old.get(field) is not None and value < _timestamp(old[field]):
            return False
        return (
            -5 <= (value - _timestamp(start)).total_seconds()
            and (value - _timestamp(end)).total_seconds() <= 5
        )
    except (ValueError, TypeError, OverflowError):
        return False


def _matches(plan: dict[str, Any], state: dict[str, Any], start: str, end: str) -> bool:
    """Only selected ID's body/edited_at and bounded submission clocks may move."""
    try:
        envelope = plan["envelope"]
        expected = copy.deepcopy(plan["expected"])
        old_sub = json.loads(expected["submission"]["body"])
        new_sub = json.loads(state["submission"]["body"])
        old = _selected(expected, envelope["comment_id"])
        new = _selected(state, envelope["comment_id"])
        if (
            new["comment"] != envelope["comment"]
            or not _clock(old, new, "edited_at", start, end, allow_added=True)
            or not _clock(old_sub, new_sub, "updated_at", start, end)
        ):
            return False
        replacement = copy.deepcopy(old)
        replacement["comment"] = envelope["comment"]
        if "edited_at" in new:
            replacement["edited_at"] = new["edited_at"]
        if digest(replacement) != digest(new):
            return False
        # Keep original list ordering and every unrelated comment's exact object.
        for index, item in enumerate(old_sub["submission_comments"]):
            if _id(item["id"]) == envelope["comment_id"]:
                old_sub["submission_comments"][index] = replacement
        if "updated_at" in new_sub:
            old_sub["updated_at"] = new_sub["updated_at"]
        expected["submission"]["body"] = json.dumps(old_sub)
        return comment_target_unchanged(
            expected,
            state,
            max_clock_advance_seconds=comment_clock_limit(plan["created_at"]),
        )
    except (GradebookError, KeyError, TypeError, ValueError):
        return False


async def confirm_comment_edit(
    publisher: Publisher,
    course_id: str,
    operation_id: str,
    token: str,
    *,
    enabled: bool = False,
    owner_controls: OwnerControls | None = None,
) -> dict[str, Any]:
    """Once-only fixed-endpoint PUT; uncertainty permits GET reconciliation only."""
    if enabled is not True:
        raise GradebookError("Existing-comment editing is not enabled.")
    controls = _controls(owner_controls)
    plan = _plan(publisher, course_id, operation_id)
    envelope = plan["envelope"]
    with publisher.ledger.exclusive(operation_id):
        publisher.ledger.claim(operation_id, token)
        try:
            if (
                digest(publisher.store.read_edits(plan["filename"]))
                != plan["envelope_sha256"]
            ):
                raise GradebookError(
                    "Edit source/body changed after preview; nothing sent."
                )
            await controls.fresh_before_context(course_id, copy.deepcopy(envelope))
            if _binding(controls, plan) != plan["owner_binding"]:
                raise GradebookError(
                    "Edit source/QC qualification changed; nothing sent."
                )
            if await publisher._comment_scope(course_id, envelope) != plan["author"]:
                raise GradebookError("Publisher identity changed; nothing sent.")
            fresh = await comment_state(publisher.client, _target(publisher, envelope))
            _admit(publisher, envelope, fresh, plan["author"])
            if digest(_selected(fresh, envelope["comment_id"])) != envelope[
                "old_comment_sha256"
            ] or not comment_target_unchanged(
                plan["expected"],
                fresh,
                max_clock_advance_seconds=comment_clock_limit(plan["created_at"]),
            ):
                raise GradebookError(
                    "Existing CID/body/target/state changed; nothing sent."
                )
            _owner_check(controls, course_id, copy.deepcopy(envelope))
            if time.time() > publisher.ledger.operation(operation_id)["expires"]:
                raise GradebookError("Edit preview expired before send; nothing sent.")
            # The immutable plan is the exact durable intent; 'sending' is
            # committed before the one transport call. No schema/expiry rewrite.
            publisher.ledger.mark(operation_id, 0, "sending")
            url = (
                publisher.client.origin
                + "/api/v1/courses/"
                + course_id
                + "/assignments/"
                + envelope["assignment_id"]
                + "/submissions/"
                + envelope["user_id"]
                + "/comments/"
                + envelope["comment_id"]
            )
            started = datetime.now(UTC).isoformat()
            try:
                response = await publisher.client.http.put(
                    url,
                    content=urlencode({"comment": envelope["comment"]}).encode(),
                    headers={"Content-Type": "application/x-www-form-urlencoded"},
                    follow_redirects=False,
                )
            except httpx.HTTPError:
                publisher.ledger.mark(operation_id, 0, "uncertain")
                return publisher.ledger.finish(operation_id)
            if response.status_code in (400, 401, 403, 404, 409, 422, 429):
                publisher.ledger.mark(operation_id, 0, "rejected")
                return publisher.ledger.finish(operation_id)
            try:
                raw = response.json()
                valid = (
                    response.status_code == 200
                    and type(raw) is dict
                    and _id(raw.get("id")) == envelope["comment_id"]
                    and _id(raw.get("author_id")) == plan["author"]
                    and raw.get("comment") == envelope["comment"]
                )
            except (ValueError, TypeError, GradebookError):
                valid = False
            if not valid:
                publisher.ledger.mark(operation_id, 0, "uncertain")
                return publisher.ledger.finish(operation_id)
            publisher.ledger.save_comment_response(
                operation_id, 0, envelope["comment_id"]
            )
            after = await comment_state(publisher.client, _target(publisher, envelope))
            # Bind readback to the actual final preflight, not a reconstructed GET.
            comparison = {**plan, "expected": fresh}
            held = False
            try:
                _admit(publisher, envelope, after, plan["author"])
            except GradebookError:
                held = True
            matched = not held and _matches(
                comparison, after, started, datetime.now(UTC).isoformat()
            )
            receipt, _ = publisher.store.save(
                "receipt",
                {
                    "kind": "GRADEBOOK_EXISTING_COMMENT_EDIT_READBACK_V1",
                    "action": ACTION,
                    "operation_id": operation_id,
                    "delivery_id": plan["delivery_id"],
                    "response_comment_id": envelope["comment_id"],
                    "send_preflight": fresh,
                    "after": after,
                    "stored_verified": matched,
                    "academic_acceptance": False,
                    "readback_admission_held": held,
                },
            )
            publisher.ledger.mark(
                operation_id, 0, "verified" if matched else "uncertain"
            )
            return {
                **publisher.ledger.finish(operation_id),
                "readback_receipt_id": receipt,
            }
        except BaseException:
            publisher.ledger.finish(operation_id)
            raise


async def reconcile_comment_edit(
    publisher: Publisher,
    course_id: str,
    operation_id: str,
) -> dict[str, Any]:
    """Read existing target only; never create a new token or retransmit a PUT."""
    plan = _plan(publisher, course_id, operation_id)
    with publisher.ledger.exclusive(operation_id):
        operation = publisher.ledger.operation(operation_id)
        if operation["status"] == "prepared" or operation["items"][0]["status"] not in {
            "sending",
            "uncertain",
        }:
            return publisher.ledger.finish(operation_id)
        envelope = plan["envelope"]
        if await publisher._comment_scope(course_id, envelope) != plan["author"]:
            raise GradebookError(
                "Publisher identity changed; edit reconciliation held."
            )
        state = await comment_state(publisher.client, _target(publisher, envelope))
        now = datetime.now(UTC)
        end = min(
            now, datetime.fromtimestamp(operation["expires"] + 300, UTC)
        ).isoformat()
        held = False
        try:
            _admit(publisher, envelope, state, plan["author"])
        except GradebookError:
            held = True
        matched = not held and _matches(plan, state, plan["created_at"], end)
        linked = operation["items"][0]["response_comment_id"] == envelope["comment_id"]
        result = (
            "verified"
            if matched and linked
            else "observed_applied"
            if matched
            else "uncertain"
        )
        receipt, _ = publisher.store.save(
            "receipt",
            {
                "kind": "GRADEBOOK_EXISTING_COMMENT_EDIT_RECONCILIATION_V1",
                "action": ACTION,
                "operation_id": operation_id,
                "after": state,
                "outcome": result,
                "same_comment_id": envelope["comment_id"],
                "academic_acceptance": False,
                "readback_admission_held": held,
            },
        )
        publisher.ledger.mark(operation_id, 0, result)
        return {**publisher.ledger.finish(operation_id), "readback_receipt_id": receipt}


def register_comment_edit_tools(
    server: FastMCP,
    publisher: Publisher,
    courses: dict[str, str],
    *,
    owner_controls: OwnerControls | None = None,
    enabled: bool = False,
) -> None:
    """Optional owner wiring seam; default off, no second publisher or launcher.

    This trusted configuration is not a tool argument. The canonical owner must
    review and explicitly connect it; this module never changes server.py.
    """
    if enabled is not True:
        return
    from mcp.types import ToolAnnotations

    controls = _controls(owner_controls)
    configured = dict(courses)
    if not configured or any(
        type(key) is not str or type(value) is not str or _id(value) != value
        for key, value in configured.items()
    ):
        raise GradebookError("Exact configured edit courses required.")

    def resolve(course: str) -> str:
        if course not in configured:
            raise GradebookError("Use an explicitly configured course alias.")
        return configured[course]

    @server.tool(annotations=ToolAnnotations(read_only_hint=True))
    async def prepare_existing_comment_edit(
        course: str,
        proposal_filename: str,
        expected_envelope_sha256: str,
    ) -> dict[str, Any]:
        """Prepare exact existing-ID EDIT preview; sends no Canvas change."""
        try:
            return await prepare_comment_edit(
                publisher,
                resolve(course),
                proposal_filename,
                expected_envelope_sha256,
                owner_controls=controls,
            )
        except GradebookError as exc:
            return {"error": str(exc), "canvas_writes": 0, "retry_writes": False}
        except Exception:
            return {"error": "Existing-comment edit preview held.", "canvas_writes": 0}

    @server.tool(
        annotations=ToolAnnotations(
            read_only_hint=False,
            destructive_hint=True,
            idempotent_hint=False,
        )
    )
    async def confirm_existing_comment_edit(
        course: str,
        operation_id: str,
        confirmation_token: str,
    ) -> dict[str, Any]:
        """Confirm this exact separately approved existing-comment EDIT once."""
        try:
            return await confirm_comment_edit(
                publisher,
                resolve(course),
                operation_id,
                confirmation_token,
                enabled=True,
                owner_controls=controls,
            )
        except GradebookError as exc:
            return {
                "error": str(exc),
                "operation_id": operation_id,
                "retry_writes": False,
            }
        except Exception:
            return {
                "error": "Edit outcome held; inspect durable state; GET recovery only.",
                "operation_id": operation_id,
                "retry_writes": False,
            }

    @server.tool(annotations=ToolAnnotations(read_only_hint=True))
    async def reconcile_existing_comment_edit(
        course: str, operation_id: str
    ) -> dict[str, Any]:
        """GET-only same-ID readback; never resend an existing-comment edit."""
        try:
            return await reconcile_comment_edit(
                publisher, resolve(course), operation_id
            )
        except GradebookError as exc:
            return {"error": str(exc), "retry_writes": False}
        except Exception:
            return {
                "error": "Existing-comment edit readback held; no retry.",
                "retry_writes": False,
            }
