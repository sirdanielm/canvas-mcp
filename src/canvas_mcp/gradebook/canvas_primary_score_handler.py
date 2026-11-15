"""Source-owned preparation only for an exact Canvas-primary staged advisory.

No owner policy is installed here. Confirmation remains mechanically disabled;
the application must supply genuine source, receipt, protection and user-scope
authorities and complete independent qualification before any future sender.
"""

from __future__ import annotations

import copy
import html
import os
from collections.abc import Callable
from typing import Any, cast
from urllib.parse import urlsplit

from .canvas_primary_owner import CanvasPrimaryEditConnection
from .canvas_primary_publication_intent import prepare_publication_intent
from .client import GradebookError
from .localgrass_edit_owner import LocalGrAssEditOwner
from .model import digest
from .owner_config import OwnerPolicy

KIND = "CANVAS_PRIMARY_SCORE_OWNER_V1"


def _need(value: Any, code: str) -> None:
    if not value:
        raise GradebookError(code)


def _write_handoff_preview(store: Any, review: dict[str, Any]) -> str:
    """Write a private, truthful advisory preview; no operation is created."""
    baseline = store.load("snapshot", review["baseline_id"])
    _need(
        type(review.get("changes")) is list and len(review["changes"]) == 1,
        "PRIMARY_PUBLICATION_SCOPE_CHANGED",
    )
    change = review["changes"][0]
    students = [x for x in baseline["students"] if x.get("id") == change["user_id"]]
    assignments = [
        x for x in baseline["assignments"] if x.get("id") == change["assignment_id"]
    ]
    _need(
        len(students) == len(assignments) == 1
        and type(students[0].get("name")) is str
        and bool(students[0]["name"].strip())
        and type(assignments[0].get("name")) is str
        and bool(assignments[0]["name"].strip()),
        "PRIMARY_HANDOFF_IDENTITY_HELD",
    )

    def escape(value: Any) -> str:
        return html.escape("—" if value is None else str(value))

    cell = baseline["cells"].get(change["user_id"] + ":" + change["assignment_id"])
    _need(
        type(cell) is dict
        and type(cell.get("attempt")) is int
        and type(cell.get("submitted_at")) is str
        and bool(cell["submitted_at"].strip()),
        "PRIMARY_HANDOFF_SOURCE_HELD",
    )
    values = [
        students[0]["name"],
        change["user_id"],
        ", ".join(students[0].get("sections", [])),
        assignments[0]["name"],
        cell["attempt"],
        cell["submitted_at"],
        change["current"],
        change["proposed"],
    ]
    # Offer only the exact Canvas-provided assignment URL, never a URL from
    # student work; if unavailable, the user can navigate by the displayed name.
    link = ""
    metadata = assignments[0].get("assignment_metadata")
    candidate = metadata.get("html_url") if isinstance(metadata, dict) else None
    origin = baseline.get("origin")
    if type(candidate) is str and type(origin) is str:
        try:
            parsed, base = urlsplit(candidate), urlsplit(origin)
            exact_path = (
                "/courses/"
                + str(baseline["course_id"])
                + "/assignments/"
                + change["assignment_id"]
            )
            if (
                parsed.scheme == base.scheme == "https"
                and parsed.hostname == base.hostname
                and parsed.username is None
                and parsed.password is None
                and parsed.port in (None, 443)
                and base.port in (None, 443)
                and base.username is None
                and base.password is None
                and base.path in ("", "/")
                and not base.query
                and not base.fragment
                and parsed.path == exact_path
                and not parsed.query
                and not parsed.fragment
            ):
                link = (
                    '<p><a href="'
                    + html.escape(candidate, quote=True)
                    + '">Open the Canvas assignment</a> and select the student in SpeedGrader.</p>'
                )
        except ValueError:
            pass
    content = (
        "<!doctype html><html lang='en'><meta charset='utf-8'>"
        '<meta http-equiv="Content-Security-Policy" content="default-src &#39;none&#39;; style-src &#39;unsafe-inline&#39;">'
        "<title>Canvas participation advisory</title><h1>Canvas participation advisory</h1>"
        "<p>Unapproved source-based advisory. No Canvas grade or comment was sent. "
        "The user must perform the final Canvas action. Before acting, verify the same "
        "submission and that the current grade is still lower or blank; otherwise leave it unchanged. "
        "Do not change comments or protected targets.</p><table><thead><tr>"
        "<th>Student</th><th>Canvas ID</th><th>Section</th><th>Assignment</th><th>Attempt</th>"
        "<th>Submitted at</th><th>Canvas at review</th><th>Proposed points</th>"
        "</tr></thead><tbody><tr>"
        + "".join("<td>" + escape(value) + "</td>" for value in values)
        + "</tr></tbody></table><p>Course: "
        + escape(baseline.get("course_name"))
        + "; Canvas snapshot: "
        + escape(baseline.get("fetched_at"))
        + "</p>"
        + link
        + "<p>Review reference: "
        + escape(digest(review))
        + "</p></html>"
    )
    path = store.root / ("canvas-primary-handoff-" + digest(review) + ".html")
    _need(not path.is_symlink(), "PRIMARY_HANDOFF_FILE_HELD")
    try:
        with open(
            path,
            "x",
            encoding="utf-8",
            opener=lambda p, flags: os.open(p, flags, 0o600),
        ) as stream:
            stream.write(content)
    except FileExistsError:
        _need(path.read_text(encoding="utf-8") == content, "PRIMARY_HANDOFF_FILE_HELD")
    return str(path)


class CanvasPrimaryScoreHandler:
    """Single staged case, canonical Publisher/Store, and no enabled confirm."""

    def __init__(
        self,
        *,
        publisher: Any,
        owner: LocalGrAssEditOwner,
        stage_plan_id: str,
        verify_stage_receipt: Callable[..., Any],
        verify_approval_scope: Callable[..., Any],
    ) -> None:
        _need(
            isinstance(owner, LocalGrAssEditOwner)
            and isinstance(owner.connection, CanvasPrimaryEditConnection)
            and publisher.client is owner.canvas
            and publisher.store is owner.connection.store
            and type(stage_plan_id) is str
            and len(stage_plan_id) == 64
            and all(c in "0123456789abcdef" for c in stage_plan_id)
            and callable(verify_stage_receipt)
            and callable(verify_approval_scope),
            "PRIMARY_PUBLICATION_OWNER_REQUIRED",
        )
        self.publisher, self.owner, self.stage_plan_id = publisher, owner, stage_plan_id
        self.verify_stage_receipt, self.verify_approval_scope = (
            verify_stage_receipt,
            verify_approval_scope,
        )

    def recognizes_review(self, review_id: str) -> bool:
        return review_id == self.stage_plan_id

    def protects_items(self, course_id: str, items: Any) -> bool:
        """Exclusive opt-in policy holds all generic scores, never a bypass.

        A deployment that must coexist with other owners needs a separately
        reviewed multiplexer. This handler itself cannot clear any other scope.
        """
        return True

    def _retained(self) -> tuple[dict[str, Any], dict[str, Any]]:
        conn = cast(CanvasPrimaryEditConnection, self.owner.connection)
        plan = conn.store.load("review", self.stage_plan_id)
        conn.validate_plan(plan, expected_plan_sha256=self.stage_plan_id)
        directory = self.owner.output_root / self.stage_plan_id
        stored = conn.files.load(directory / "plan.json")
        _need(
            digest(stored) == self.stage_plan_id and stored == plan,
            "PRIMARY_STAGING_HISTORY_HELD",
        )
        receipts = sorted(directory.glob("receipt-*.json"))
        _need(0 < len(receipts) <= 10000, "PRIMARY_STAGING_HISTORY_HELD")
        return plan, conn.files.load(receipts[-1])

    def _intent(
        self, plan: dict[str, Any], receipt: dict[str, Any], ctx: dict[str, Any]
    ) -> dict[str, Any]:
        return prepare_publication_intent(
            connection=cast(CanvasPrimaryEditConnection, self.owner.connection),
            stage_plan=plan,
            expected_stage_plan_sha256=self.stage_plan_id,
            stage_receipt=receipt,
            raw=ctx["raw"],
            current=ctx["current"],
            pin_binding=ctx["pin_binding"],
            verify_stage_receipt=self.verify_stage_receipt,
            verify_approval_scope=self.verify_approval_scope,
        )

    async def prepare(
        self, publisher: Any, course_id: str, review_id: str
    ) -> dict[str, Any]:
        _need(
            publisher is self.publisher
            and self.recognizes_review(review_id)
            and course_id
            == cast(CanvasPrimaryEditConnection, self.owner.connection).record["course_id"],
            "PRIMARY_PUBLICATION_OWNER_REQUIRED",
        )
        with self.owner.journal.exclusive():
            self.owner._check_owner()
            plan, receipt = self._retained()
            ctx = await self.owner._context()
            prepared = self._intent(plan, receipt, ctx)
        operation = prepared["operation_current_baseline"]
        operation_id, _ = publisher.store.save("snapshot", operation)
        _need(
            operation_id == prepared["intent"]["operation_current_baseline_sha256"],
            "PRIMARY_PUBLICATION_BASELINE_CHANGED",
        )
        review = copy.deepcopy(prepared["review"])
        review["canvas_primary_publication_intent"] = copy.deepcopy(prepared["intent"])
        source_review_id, _ = publisher.store.save("review", review)
        display = _write_handoff_preview(publisher.store, review)
        return {
            "ready_for_confirmation": False,
            "preview_ready": True,
            "source_review_id": source_review_id,
            "review_file": display,
            "publication_confirm_enabled": False,
            "canvas_writes": 0,
            "notice": "Private source-owned preview only. No publication operation or token was created; final Canvas action requires user handoff.",
        }

    def matches_plan(self, course_id: str, plan: dict[str, Any]) -> bool:
        """Recognize only this retained intent and its exact score target."""
        try:
            marker = plan.get("owner_binding")
            _need(
                course_id
                == cast(CanvasPrimaryEditConnection, self.owner.connection).record[
                    "course_id"
                ]
                and plan.get("course_id") == course_id
                and type(marker) is dict
                and set(marker)
                == {
                    "kind",
                    "source_review_id",
                    "stage_plan_sha256",
                    "source_intent_sha256",
                    "operation_current_baseline_sha256",
                }
                and marker["kind"] == KIND
                and marker["stage_plan_sha256"] == self.stage_plan_id,
                "PRIMARY_PUBLICATION_OWNER_REQUIRED",
            )
            marker = cast(dict[str, Any], marker)
            review = self.publisher.store.load("review", marker["source_review_id"])
            intent = review["canvas_primary_publication_intent"]
            stage = self.owner.connection.store.load("review", self.stage_plan_id)
            conn = cast(CanvasPrimaryEditConnection, self.owner.connection)
            target_expected = {
                k: conn.record[k] for k in ("course_id", "user_id", "assignment_id")
            }
            _need(
                intent.get("contract") == "CANVAS_PRIMARY_SCORE_PUBLICATION_INTENT_V1"
                and intent.get("target") == target_expected
                and intent.get("score") == conn.proposal["total_score"]
                and intent.get("score_only") is True
                and intent.get("approval_scope") == "LOWER_OR_BLANK_ONLY"
                and intent.get("source_evidence_sha256") == digest(conn.evidence)
                and intent.get("original_sync_baseline_sha256")
                == digest(stage["transfer"]["baseline"])
                and intent.get("protection_registry_sha256")
                == stage["primary_plan"]["protection_registry_sha256"],
                "PRIMARY_PUBLICATION_OWNER_REQUIRED",
            )
            _need(
                digest(intent) == marker["source_intent_sha256"]
                and intent["stage_plan_sha256"] == self.stage_plan_id
                and intent["operation_current_baseline_sha256"]
                == marker["operation_current_baseline_sha256"]
                and review["baseline_id"] == marker["operation_current_baseline_sha256"]
                and type(plan.get("items")) is list
                and len(plan["items"]) == 1,
                "PRIMARY_PUBLICATION_OWNER_REQUIRED",
            )
            item = plan["items"][0]
            target = intent["target"]
            _need(
                item.get("user_id") == target["user_id"]
                and item.get("assignment_id") == target["assignment_id"]
                and item.get("proposed") == intent["score"],
                "PRIMARY_PUBLICATION_OWNER_REQUIRED",
            )
            return True
        except (GradebookError, KeyError, TypeError, ValueError):
            return False

    def status(self, course_id: str, operation_id: str) -> dict[str, Any]:
        operation = self.publisher.ledger.operation(operation_id)
        plan = self.publisher.store.load("push", operation["plan_id"])
        _need(self.matches_plan(course_id, plan), "PRIMARY_PUBLICATION_OWNER_REQUIRED")
        return dict(self.publisher.ledger.summary(operation_id))

    async def confirm(
        self, publisher: Any, course_id: str, operation_id: str, token: str
    ) -> dict[str, Any]:
        raise GradebookError("PRIMARY_PUBLICATION_CONFIRM_NOT_INSTALLED")

    async def reconcile(
        self, publisher: Any, course_id: str, operation_id: str
    ) -> dict[str, Any]:
        _need(
            publisher is self.publisher
            and course_id
            == cast(CanvasPrimaryEditConnection, self.owner.connection).record["course_id"],
            "PRIMARY_PUBLICATION_OWNER_REQUIRED",
        )
        operation = publisher.ledger.operation(operation_id)
        plan = publisher.store.load("push", operation["plan_id"])
        _need(self.matches_plan(course_id, plan), "PRIMARY_PUBLICATION_OWNER_REQUIRED")
        result: dict[str, Any] = await publisher.reconcile(course_id, operation_id)
        return result


def make_exclusive_primary_owner_policy(
    *,
    handler_factory: Callable[[Any], Any],
    protected_scope: Callable[[str, Any], bool],
) -> OwnerPolicy:
    """Build a private opt-in policy; generic score publication stays held.

    Existing source owners need an independently reviewed multiplexer instead
    of replacement. No registry, user approval or confirmation is created here.
    """
    _need(
        callable(handler_factory) and callable(protected_scope),
        "PRIMARY_PUBLICATION_OWNER_REQUIRED",
    )

    def all_scores_owned(_course: str, _review: str | None, _items: Any) -> bool:
        return True

    class ExclusiveScopeHandler:
        def __init__(self, delegate: Any) -> None:
            _need(delegate is not None, "PRIMARY_PUBLICATION_OWNER_REQUIRED")
            self.delegate = delegate

        def protects_items(self, _course: str, _items: Any) -> bool:
            return True

        def __getattr__(self, name: str) -> Any:
            return getattr(self.delegate, name)

    def exclusive_factory(publisher: Any) -> Any:
        return ExclusiveScopeHandler(handler_factory(publisher))

    return OwnerPolicy(
        all_scores_owned, protected_scope, pair_score_handler_factory=exclusive_factory
    )
