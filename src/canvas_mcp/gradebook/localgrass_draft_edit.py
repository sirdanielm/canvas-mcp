"""Receive genuine V2 participation drafts through the existing native stage.

Trusted application composition supplies the qualified producer module, current
workspace and independent central bindings. No teacher decision, scorer, client,
controller or publisher is constructed. Existing owner/executor history is reused.
"""

from __future__ import annotations

import copy
import hashlib
import inspect
import json
import re
from pathlib import Path
from types import ModuleType
from typing import Any
from urllib.parse import urlsplit

from . import native
from .client import GradebookError
from .model import digest, identifier
from .proposal_preview import _metadata
from .store import Store

CONTRACT = "LOCALGRASS_UNAPPROVED_PARTICIPATION_EDIT_V1"
STAGE_CONTRACT = "LOCAL_PARTICIPATION_EDIT_STAGE_V1"
APPROVALS = (
    "teacher_approval",
    "score_approval",
    "comment_approval",
    "publication_allowed",
    "score_delivery_authorized",
    "comment_delivery_authorized",
)


def _need(value: Any, code: str) -> None:
    if not value:
        raise GradebookError(code)


def _portable(value: Any) -> Any:
    return json.loads(json.dumps(value, allow_nan=False))


def _require_current_attempt_review_support(stage_module: ModuleType) -> None:
    """Hold an optional permit before invoking an incompatible pinned planner."""
    try:
        inspect.signature(stage_module.prepare_stage).bind_partial(
            current_attempt_review={}
        )
    except (AttributeError, TypeError, ValueError):
        raise GradebookError("CURRENT_ATTEMPT_REVIEW_UNSUPPORTED") from None


def _google_assignments_draft_review(
    target: dict[str, Any],
    proposal: dict[str, Any],
    observed: dict[str, Any],
    baseline: dict[str, Any],
    current: dict[str, Any],
) -> None:
    """Honor one pinned local-only Google mapping; retain truthful raw metadata."""
    review = target.get("external_tool_draft_review")
    if not isinstance(review, dict):
        raise GradebookError("GOOGLE_ASSIGNMENTS_DRAFT_REVIEW_REQUIRED")
    metadata = observed["assignment_metadata"]
    tag = metadata.get("external_tool_tag_attributes")
    try:
        url = urlsplit(tag["url"])
        allowed_url = (
            url.scheme == "https"
            and url.hostname == "assignments.google.com"
            and url.username is None
            and url.password is None
            and url.port in (None, 443)
            and url.path.startswith("/lti/a/")
            and len(url.path) > len("/lti/a/")
        )
    except (KeyError, TypeError, ValueError):
        allowed_url = False
    _need(
        metadata.get("submission_types") == ["external_tool"]
        and allowed_url
        and target.get("provider") == "sdmGrAss"
        and baseline["origin"] == current["origin"]
        and baseline["course_id"] == current["course_id"] == str(target["course_id"]),
        "GOOGLE_ASSIGNMENTS_DRAFT_REVIEW_REQUIRED",
    )
    expected = {
        key: proposal[key]
        for key in (
            "assignment_key",
            "source_target",
            "student_track",
            "record_ref",
            "revision_ref",
            "queue_digest",
        )
    }
    expected.update(
        contract="CANVAS_GOOGLE_ASSIGNMENTS_DRAFT_REVIEW_V1",
        provider="GOOGLE_ASSIGNMENTS",
        source_provider="sdmGrAss",
        origin=current["origin"],
        course_id=current["course_id"],
        assignment_id=str(target["assignment_id"]),
        assignment_metadata_sha256=digest(metadata),
        scope="LOCAL_UNAPPROVED_EDIT_ONLY",
        source_lane="SDMGRASS_FORMATIVE",
        delivery_policy="SCORE_ONLY",
    )
    _need(
        all(review.get(key) == value for key, value in expected.items())
        and review.get("publication_allowed") is False
        and type(review.get("review_ref")) is str
        and re.fullmatch(r"[a-f0-9]{64}", review["review_ref"]),
        "GOOGLE_ASSIGNMENTS_DRAFT_REVIEW_REQUIRED",
    )


class LocalGrAssDraftEditConnection:
    """Adapt the qualified participation stage to the existing Canvas owner API."""

    contract = CONTRACT

    def __init__(
        self,
        workspace: Path,
        canvas_store: Store,
        *,
        stage_module: ModuleType,
        expected_stage_sha256: str,
        canvas_repo: Path,
        files: ModuleType,
        assignment_bindings_path: Path,
        expected_assignment_bindings_sha256: str,
        registry_path: Path,
        selected_record_refs: tuple[str, ...],
        reader_bundle_path: Path | None = None,
        expected_reader_bundle_sha256: str | None = None,
        expected_policy_sha256: str | None = None,
        expected_reader_artifact_sha256: str | None = None,
        current_attempt_review_path: Path | None = None,
        expected_current_attempt_review_sha256: str | None = None,
    ) -> None:
        _need(
            isinstance(stage_module, ModuleType)
            and isinstance(files, ModuleType)
            and isinstance(canvas_store, Store),
            "TRUSTED_PARTICIPATION_COMPOSITION_REQUIRED",
        )
        _need(
            all(
                isinstance(p, Path) and p.is_absolute()
                for p in (
                    workspace,
                    canvas_repo,
                    assignment_bindings_path,
                    registry_path,
                )
            ),
            "EXPLICIT_LOCAL_BINDINGS_REQUIRED",
        )
        _need(
            type(selected_record_refs) is tuple
            and 0 < len(selected_record_refs) <= 25
            and all(type(ref) is str and bool(ref) for ref in selected_record_refs)
            and len(set(selected_record_refs)) == len(selected_record_refs),
            "EXPLICIT_PARTICIPATION_SELECTION_REQUIRED",
        )
        _need(
            all(
                type(v) is str and re.fullmatch(r"[a-f0-9]{64}", v)
                for v in (expected_stage_sha256, expected_assignment_bindings_sha256)
            ),
            "PARTICIPATION_SOURCE_PIN_REQUIRED",
        )
        _need(
            all(
                callable(getattr(stage_module, name, None))
                for name in ("workspace_proposals", "prepare_stage", "canvas_owner")
            )
            and all(
                callable(getattr(files, name, None))
                for name in ("file_sha", "load", "local_path")
            ),
            "TRUSTED_PARTICIPATION_COMPOSITION_REQUIRED",
        )
        self.reader_binding: dict[str, str] | None = None
        reader_values = (
            reader_bundle_path,
            expected_reader_bundle_sha256,
            expected_policy_sha256,
            expected_reader_artifact_sha256,
        )
        if any(value is not None for value in reader_values):
            _need(
                isinstance(reader_bundle_path, Path)
                and reader_bundle_path.is_absolute()
                and all(
                    type(pin) is str and re.fullmatch(r"[a-f0-9]{64}", pin)
                    for pin in reader_values[1:]
                )
                and callable(getattr(stage_module, "workspace_reader_proposals", None)),
                "EXPLICIT_READER_BINDING_REQUIRED",
            )
            self.reader_binding = {
                "bundle_path": str(reader_bundle_path),
                "bundle_sha256": str(expected_reader_bundle_sha256),
                "policy_sha256": str(expected_policy_sha256),
                "artifact_sha256": str(expected_reader_artifact_sha256),
            }
        self.current_attempt_review_binding: dict[str, str] | None = None
        if (
            current_attempt_review_path is not None
            or expected_current_attempt_review_sha256 is not None
        ):
            _need(
                isinstance(current_attempt_review_path, Path)
                and current_attempt_review_path.is_absolute()
                and type(expected_current_attempt_review_sha256) is str
                and re.fullmatch(
                    r"[a-f0-9]{64}", expected_current_attempt_review_sha256
                ),
                "EXPLICIT_CURRENT_ATTEMPT_REVIEW_REQUIRED",
            )
            self.current_attempt_review_binding = {
                "path": str(current_attempt_review_path),
                "sha256": str(expected_current_attempt_review_sha256),
            }
        self.workspace, self.store, self.stage, self.files = (
            workspace,
            canvas_store,
            stage_module,
            files,
        )
        self.stage_sha256 = expected_stage_sha256
        self.assignment_path, self.assignment_sha256 = (
            assignment_bindings_path,
            expected_assignment_bindings_sha256,
        )
        self.registry_path, self.preservation = registry_path, None
        self.selected_record_refs = selected_record_refs
        self._stage_pin()
        self.owner = self.stage.canvas_owner(canvas_repo)

    def _stage_pin(self) -> None:
        try:
            filename = self.stage.__file__
            if filename is None:
                raise TypeError("missing module file")
            path = Path(filename)
            observed = hashlib.sha256(path.read_bytes()).hexdigest()
        except (AttributeError, TypeError, OSError):
            raise GradebookError("PARTICIPATION_SOURCE_PIN_CHANGED") from None
        _need(observed == self.stage_sha256, "PARTICIPATION_SOURCE_PIN_CHANGED")

    def _current_attempt_review(self) -> dict[str, Any] | None:
        binding = self.current_attempt_review_binding
        if binding is None:
            return None
        path = Path(binding["path"])
        try:
            _need(
                self.files.file_sha(path) == binding["sha256"],
                "CURRENT_ATTEMPT_REVIEW_CHANGED",
            )
            review = self.files.load(path)
            _need(
                type(review) is dict and self.files.file_sha(path) == binding["sha256"],
                "CURRENT_ATTEMPT_REVIEW_CHANGED",
            )
        except Exception:
            raise GradebookError("CURRENT_ATTEMPT_REVIEW_CHANGED") from None
        return review  # type: ignore[no-any-return]

    def _assignments(self) -> list[dict[str, Any]]:
        _need(
            self.files.file_sha(self.assignment_path) == self.assignment_sha256,
            "ASSIGNMENT_BINDINGS_CHANGED",
        )
        assignments = self.files.load(self.assignment_path)
        _need(
            self.files.file_sha(self.assignment_path) == self.assignment_sha256
            and type(assignments) is list
            and all(type(a) is dict for a in assignments),
            "ASSIGNMENT_BINDINGS_CHANGED",
        )
        return assignments  # type: ignore[no-any-return]

    def _source(
        self, pin_binding: dict[str, Any]
    ) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        self._stage_pin()
        if self.reader_binding is None:
            report, proposals = self.stage.workspace_proposals(self.workspace)
        else:
            pins = self.reader_binding
            report, proposals = self.stage.workspace_reader_proposals(
                self.workspace,
                Path(pins["bundle_path"]),
                expected_bundle_sha256=pins["bundle_sha256"],
                expected_policy_sha256=pins["policy_sha256"],
                expected_reader_artifact_sha256=pins["artifact_sha256"],
            )
        policy = report.get("policy", {})
        _need(
            policy.get("contract") == "LOCAL_PARTICIPATION_POLICY_V2"
            and policy.get("state") == "TEACHER_AUTHORIZED_REQUIRES_REVIEW"
            and bool(policy.get("user_decision_ref")),
            "PARTICIPATION_POLICY_REQUIRED",
        )
        _need(
            report.get("student_registry_sha256") == pin_binding.get("registry_sha256"),
            "PARTICIPATION_PIN_AUTHORITY_CHANGED",
        )
        selected = [
            p
            for ref in self.selected_record_refs
            for p in proposals
            if p.get("record_ref") == ref
        ]
        _need(
            len(selected) == len(self.selected_record_refs)
            and len({p["record_ref"] for p in selected}) == len(selected),
            "PARTICIPATION_SOURCE_CHANGED",
        )
        _need(
            all(
                p.get("report_digest") == report.get("report_digest") for p in selected
            ),
            "PARTICIPATION_SOURCE_CHANGED",
        )
        if self.reader_binding is None:
            _need(
                all(
                    p.get("confidence") == "HIGH"
                    and p.get("semantic_evidence_state") == "SOURCE_BOUND_CONFIRMED"
                    for p in selected
                ),
                "EXPLICIT_READER_BINDING_REQUIRED",
            )
        else:
            pins = self.reader_binding
            _need(
                digest(report["policy"]) == pins["policy_sha256"]
                and all(
                    p.get("confidence") == "READER_ADVISORY"
                    and p.get("semantic_evidence_state")
                    == "SOURCE_BOUND_READER_ADVISORY"
                    and p.get("reader_bundle_sha256") == pins["bundle_sha256"]
                    and p.get("reader_artifact_sha256") == pins["artifact_sha256"]
                    and p.get("policy_sha256") == pins["policy_sha256"]
                    for p in selected
                ),
                "READER_SOURCE_BINDING_CHANGED",
            )
        return copy.deepcopy(report), copy.deepcopy(selected)

    def _source_check(
        self,
        expected_report: dict[str, Any],
        expected: list[dict[str, Any]],
        pin_binding: dict[str, Any],
    ) -> Any:
        def check(selected: list[dict[str, Any]]) -> None:
            report, actual = self._source(pin_binding)
            _need(
                report.get("report_digest") == expected_report.get("report_digest")
                and actual == expected == selected,
                "PARTICIPATION_SOURCE_CHANGED",
            )

        return check

    def _selected_assignments(
        self,
        proposals: list[dict[str, Any]],
        course_id: str,
        *,
        assignments: list[dict[str, Any]] | None = None,
    ) -> list[dict[str, Any]]:
        if assignments is None:
            assignments = self._assignments()
        targets = []
        for proposal in proposals:
            matches = [
                a
                for a in assignments
                if all(
                    a.get(k) == proposal.get(k)
                    for k in ("assignment_key", "source_target", "student_track")
                )
                and str(a.get("course_id")) == course_id
            ]
            _need(len(matches) == 1, "EXACT_CENTRAL_ASSIGNMENT_REQUIRED")
            targets.append(matches[0])
        return targets

    def assignment_targets(
        self,
        *,
        course_id: str,
        pin_binding: dict[str, Any],
    ) -> list[str]:
        """Return exact selected IDs for owner-held raw assignment GETs only."""
        _need(
            type(course_id) is str and identifier(course_id) == course_id,
            "EXACT_CENTRAL_ASSIGNMENT_REQUIRED",
        )
        _, proposals = self._source(pin_binding)
        ids = [
            str(target["assignment_id"])
            for target in self._selected_assignments(proposals, course_id)
        ]
        _need(
            all(identifier(aid) == aid for aid in ids),
            "EXACT_CENTRAL_ASSIGNMENT_REQUIRED",
        )
        return list(dict.fromkeys(ids))

    def _prepare_stage(
        self,
        proposals: list[dict[str, Any]],
        report: dict[str, Any],
        *,
        raw: dict[str, Any],
        binding: dict[str, Any],
        baseline: dict[str, Any],
        current: dict[str, Any],
        pin_binding: dict[str, Any],
    ) -> dict[str, Any]:
        assignments = self._assignments()
        targets = self._selected_assignments(
            proposals, str(binding["course_id"]), assignments=assignments
        )
        for proposal, target in zip(proposals, targets, strict=True):
            aid = str(target["assignment_id"])
            matches = [a for a in current["assignments"] if a.get("id") == aid]
            _need(len(matches) == 1, "ASSIGNMENT_METADATA_REQUIRED")
            observed = matches[0]
            _need(
                type(target.get("provider")) is str
                and bool(target["provider"].strip()),
                "ASSIGNMENT_PROVIDER_REQUIRED",
            )
            try:
                _metadata(
                    {
                        **target,
                        "course_id": str(binding["course_id"]),
                        "assignment_id": aid,
                        "assignment_metadata": observed.get("assignment_metadata"),
                        "assignment_metadata_sha256": observed.get(
                            "assignment_metadata_sha256"
                        ),
                    }
                )
            except GradebookError as error:
                if (
                    str(error) != "EXTERNAL_TOOL_REVIEW_REQUIRED"
                    or "external_tool_draft_review" not in target
                ):
                    raise
                _google_assignments_draft_review(
                    target, proposal, observed, baseline, current
                )
            if self.current_attempt_review_binding is not None:
                # Bind the local permit to verified provider metadata without
                # changing the independently pinned assignment file.
                target["provider_metadata_sha256"] = observed[
                    "assignment_metadata_sha256"
                ]
        current_attempt_review = self._current_attempt_review()
        if current_attempt_review is not None:
            _require_current_attempt_review_support(self.stage)
        extra = (
            {"current_attempt_review": current_attempt_review}
            if current_attempt_review is not None
            else {}
        )
        try:
            plan = self.stage.prepare_stage(
                proposals,
                raw=raw,
                binding=binding,
                baseline=baseline,
                current=current,
                pin_binding=pin_binding,
                assignment_bindings=assignments,
                owner=self.owner,
                source_check=self._source_check(report, proposals, pin_binding),
                **extra,
            )
        except self.stage.StageHold as error:
            raise GradebookError(str(error)) from None
        if current_attempt_review is not None:
            _need(
                plan.get("current_attempt_review") == current_attempt_review,
                "CURRENT_ATTEMPT_REVIEW_BINDING_CHANGED",
            )
        return _portable(plan)  # type: ignore[no-any-return]

    def prepare(
        self,
        *,
        raw: dict[str, Any],
        binding: dict[str, Any],
        baseline: dict[str, Any],
        current: dict[str, Any],
        pin_binding: dict[str, Any],
    ) -> dict[str, Any]:
        report, proposals = self._source(pin_binding)
        transfer = self._prepare_stage(
            proposals,
            report,
            raw=raw,
            binding=binding,
            baseline=baseline,
            current=current,
            pin_binding=pin_binding,
        )
        plan = {
            "contract": CONTRACT,
            "binding": copy.deepcopy(binding),
            "items": [{"key": item["key"]} for item in transfer["items"]],
            "transfer": transfer,
            "source_report": report,
            "selected_record_refs": list(self.selected_record_refs),
            "source_module_sha256": self.stage_sha256,
            "assignment_bindings_sha256": self.assignment_sha256,
            "source_lane": "SDMGRASS_FORMATIVE",
            "delivery_policy": "SCORE_ONLY",
            "review_state": "UNAPPROVED",
            "canvas_writes": 0,
            "sheets_writes": 0,
            **dict.fromkeys(APPROVALS, False),
        }
        if self.reader_binding is not None:
            plan["reader_binding"] = copy.deepcopy(self.reader_binding)
        if self.current_attempt_review_binding is not None:
            plan["current_attempt_review_binding"] = copy.deepcopy(
                self.current_attempt_review_binding
            )
        return plan

    @staticmethod
    def validate_plan(plan: dict[str, Any], *, expected_plan_sha256: str) -> None:
        _need(
            digest(plan) == expected_plan_sha256 and plan.get("contract") == CONTRACT,
            "EXACT_CONNECTION_PLAN_CHANGED",
        )
        transfer = plan.get("transfer")
        if not isinstance(transfer, dict) or transfer.get("contract") != STAGE_CONTRACT:
            raise GradebookError("PARTICIPATION_STAGE_PLAN_CHANGED")
        _need(
            transfer.get("plan_id")
            == digest({k: v for k, v in transfer.items() if k != "plan_id"}),
            "PARTICIPATION_STAGE_PLAN_CHANGED",
        )
        attempt_binding = plan.get("current_attempt_review_binding")
        _need(
            (attempt_binding is None and "current_attempt_review" not in transfer)
            or (
                isinstance(attempt_binding, dict)
                and set(attempt_binding) == {"path", "sha256"}
                and type(transfer.get("current_attempt_review")) is dict
            ),
            "CURRENT_ATTEMPT_REVIEW_BINDING_CHANGED",
        )
        _need(
            plan.get("binding") == transfer.get("binding")
            and plan.get("items")
            == [{"key": item["key"]} for item in transfer["items"]]
            and plan.get("selected_record_refs")
            == [p["record_ref"] for p in transfer["proposals"]]
            and plan.get("source_lane") == "SDMGRASS_FORMATIVE"
            and plan.get("delivery_policy") == "SCORE_ONLY"
            and plan.get("review_state") == "UNAPPROVED"
            and all(plan.get(k) is False for k in APPROVALS)
            and plan.get("canvas_writes") == plan.get("sheets_writes") == 0
            and transfer.get("teacher_approval") is False
            and transfer.get("publication_allowed") is False
            and transfer.get("canvas_writes") == 0,
            "DRAFT_IS_NOT_PUBLICATION_AUTHORITY",
        )

    def revalidate(
        self,
        plan: dict[str, Any],
        *,
        expected_plan_sha256: str,
        raw: dict[str, Any],
        current: dict[str, Any],
        pin_binding: dict[str, Any],
    ) -> None:
        self.validate_plan(plan, expected_plan_sha256=expected_plan_sha256)
        _need(
            plan["source_module_sha256"] == self.stage_sha256
            and plan["assignment_bindings_sha256"] == self.assignment_sha256
            and plan["selected_record_refs"] == list(self.selected_record_refs)
            and plan.get("reader_binding") == self.reader_binding
            and plan.get("current_attempt_review_binding")
            == self.current_attempt_review_binding,
            "EXACT_CONNECTION_PLAN_CHANGED",
        )
        report, proposals = self._source(pin_binding)
        _need(
            report.get("report_digest") == plan["source_report"].get("report_digest")
            and proposals == plan["transfer"]["proposals"],
            "PARTICIPATION_SOURCE_CHANGED",
        )
        transfer = plan["transfer"]
        _need(
            _portable(native._state(raw)) == transfer["before_state"],
            "TRANSFER_DESTINATION_CHANGED",
        )
        _need(
            digest(pin_binding) == transfer["pin_binding_sha256"],
            "PIN_AUTHORITY_CHANGED",
        )
        fresh = self._prepare_stage(
            proposals,
            report,
            raw=raw,
            binding=plan["binding"],
            baseline=transfer["baseline"],
            current=current,
            pin_binding=pin_binding,
        )
        _need(fresh == transfer, "EXACT_TRANSFER_PLAN_CHANGED")

    @staticmethod
    def classify(
        plan: dict[str, Any], raw: dict[str, Any], *, expected_plan_sha256: str
    ) -> dict[str, Any]:
        LocalGrAssDraftEditConnection.validate_plan(
            plan, expected_plan_sha256=expected_plan_sha256
        )
        actual = _portable(native._state(raw))
        transfer = plan["transfer"]
        status = (
            "PLANNED_OUTPUT_OBSERVED"
            if actual == transfer["after_state"]
            else (
                "BEFORE_STILL_PRESENT"
                if actual == transfer["before_state"]
                else "DIVERGED"
            )
        )
        return {
            "contract": CONTRACT,
            "status": status,
            "actual_fingerprint": digest(actual),
            "retry_writes": False,
            "canvas_writes": 0,
            "sheets_writes": 0,
            "score_delivery_verified": False,
            "comment_delivery_verified": False,
        }
