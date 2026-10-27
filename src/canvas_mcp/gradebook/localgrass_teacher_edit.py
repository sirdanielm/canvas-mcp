"""Dormant LocalGrAss authenticated decision to native EDIT composition.

Uses the actual LocalGrAss review/source authority and existing central binding
file reader. No login, decision, authority grant, journal or transport is created.
The first qualified lane carries generic computed native points unchanged.
"""

from __future__ import annotations

import copy
import importlib
import re
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation, localcontext
from pathlib import Path
from typing import Any

from .capture import build_case_receipt, intake_digest
from .client import GradebookError
from .model import digest
from .store import Store
from .teacher_edit_transfer import (
    classify_readback,
    prepare_transfer,
    revalidate_transfer,
)

CONTRACT = "LOCALGRASS_TEACHER_EDIT_V1"
UNIT1_WHOLE_PERCENT = "UNIT1_WHOLE_PERCENT_100"


def _need(value: Any, code: str) -> None:
    if not value:
        raise GradebookError(code)


def _amount(value: Any) -> float:
    try:
        _need(type(value) in (str, int, float), "NATIVE_POINT_AMOUNT_REQUIRED")
        amount = Decimal(str(value))
        number = float(amount)
        _need(
            amount.is_finite() and Decimal(str(number)) == amount and amount >= 0,
            "EXACT_NATIVE_POINTS_REQUIRED",
        )
        return number
    except (InvalidOperation, ValueError, OverflowError):
        raise GradebookError("EXACT_NATIVE_POINTS_REQUIRED") from None


def _unit1_native_score(value: Any, maximum: float, scale: str) -> float:
    amount = _amount(value)
    _need(0 < maximum and amount <= maximum, "UNIT1_FORM_SCORE_OUT_OF_RANGE")
    if scale == "RAW_IDENTITY":
        return amount
    _need(scale == UNIT1_WHOLE_PERCENT, "UNIT1_EXPLICIT_SCORE_SCALE_REQUIRED")
    with localcontext() as context:
        context.prec = 48
        percent = Decimal(str(amount)) * 100 / Decimal(str(maximum))
        return float(percent.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


class LocalGrAssEditConnection:
    """Compose existing application objects; never construct from MCP input.

    The application supplies an AuthenticatedDecisionSource backed by the actual
    TeacherReview session and SourceIntake. Central assignments use the existing
    pinned assignment-bindings file; PINs use the existing shared registry.
    Neither constructor nor methods execute any native write.
    """

    contract = CONTRACT

    @staticmethod
    def _source_files(source: Any) -> Any:
        """Authenticate the concrete source contract before shared initialization."""
        try:
            authority = importlib.import_module("localgrass.teacher_edit_source")
            files = importlib.import_module("localgrass.teacher_edit_files")
        except ImportError:
            raise GradebookError("LOCAL_SOURCE_NOT_CONFIGURED") from None
        _need(
            isinstance(source, authority.AuthenticatedDecisionSource),
            "AUTHENTICATED_SOURCE_REQUIRED",
        )
        return files

    def __init__(
        self,
        source: Any,
        canvas_store: Store,
        *,
        assignment_bindings_path: Path,
        expected_assignment_bindings_sha256: str,
        section: str,
        registry_path: Path,
        shared_tool: Path,
        preservation: dict[str, Any] | None = None,
    ) -> None:
        files = self._source_files(source)
        _need(isinstance(canvas_store, Store), "EXISTING_CANVAS_STORE_REQUIRED")
        _need(
            all(
                isinstance(p, Path) and p.is_absolute()
                for p in (assignment_bindings_path, registry_path, shared_tool)
            ),
            "EXPLICIT_LOCAL_BINDINGS_REQUIRED",
        )
        _need(type(section) is str and section.strip(), "EXPLICIT_SECTION_REQUIRED")
        self.source, self.store, self.files = source, canvas_store, files
        self.assignment_path = assignment_bindings_path
        self.assignment_sha256 = expected_assignment_bindings_sha256
        self.preservation = copy.deepcopy(preservation)
        self.section, self.registry_path, self.shared_tool = (
            section,
            registry_path,
            shared_tool,
        )

    def _project(
        self,
        snapshot: dict[str, Any],
        current: dict[str, Any],
        pin_binding: dict[str, Any],
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        # read() is not a JSON flag check: this concrete source reauthenticates
        # the session/receipt/head/dependencies and verifies original bytes.
        self.source.assert_current(snapshot)
        payload = snapshot["payload"]
        if payload.get("result_kind") == "GRASS_UNIT1_VERIFIED_OWNER_RESULT_V1":
            return self._project_unit1(snapshot, current, pin_binding)
        record = self._project_record(snapshot, current, pin_binding)
        maximum = _amount(payload["computation"]["maximum"])
        decision = {
            k: record[k]
            for k in ("evaluation_id", "source_revision", "result_revision", "policy")
        }
        decision.update(
            decision_revision=snapshot["decision_id"],
            is_final=True,
            total_score=_amount(snapshot["decision"]["score"]),
            points_possible=maximum,
            score_units="CANVAS_POINTS",
            feedback=snapshot["decision"]["feedback"],
        )
        return record, decision

    def _project_record(
        self,
        snapshot: dict[str, Any],
        current: dict[str, Any],
        pin_binding: dict[str, Any],
    ) -> dict[str, Any]:
        """Rebuild the exact target from verified generic source evidence."""
        receipt, payload = snapshot["source_receipt"], snapshot["payload"]
        deps = payload["dependencies"]
        _need(
            snapshot["source_verified"] is True
            and not payload["holds"]
            and payload.get("result_kind") is None
            and payload["computation"]["status"] == "COMPUTED",
            "GENERIC_COMPUTED_RESULT_REQUIRED",
        )
        _need(
            self.files.file_sha(self.assignment_path) == self.assignment_sha256,
            "ASSIGNMENT_BINDINGS_CHANGED",
        )
        assignments = self.files.load(self.assignment_path)
        _need(
            self.files.file_sha(self.assignment_path) == self.assignment_sha256
            and type(assignments) is list,
            "ASSIGNMENT_BINDINGS_CHANGED",
        )
        selected = [
            a
            for a in assignments
            if type(a) is dict
            and a.get("assignment_key") == snapshot["assignment_id"]
            and a.get("student_track") == deps["scope"]["track"]
            and str(a.get("course_id")) == receipt["course_id"]
            and str(a.get("assignment_id")) == receipt["canvas_assignment_id"]
            and a.get("section") == self.section
        ]
        _need(len(selected) == 1, "EXACT_CENTRAL_ASSIGNMENT_REQUIRED")
        target = selected[0]
        _need(
            target.get("score_scale") == "RAW_IDENTITY",
            "EXPLICIT_RAW_IDENTITY_REQUIRED",
        )
        identity = receipt["identity"]
        _need(
            pin_binding["registry_sha256"] == identity["registry_sha256"]
            and pin_binding["roster_sha256"] == identity["snapshot_sha256"],
            "CURRENT_PIN_AUTHORITY_CHANGED",
        )
        uid = pin_binding["by_pin"].get(identity["student_pin"])
        _need(type(uid) is str, "CANONICAL_PIN_NOT_JOINED")
        rebuilt = build_case_receipt(
            self.store,
            receipt["capture_revision"],
            expected_origin=current["origin"],
            expected_course_id=receipt["course_id"],
            assignment_id=receipt["canvas_assignment_id"],
            academic_assignment_id=snapshot["assignment_id"],
            user_id=uid,
            case_id=receipt["case_id"],
            sources=receipt["sources"],
            records=receipt["records"],
            expected_record_keys=receipt["expected_record_keys"],
            registry_path=self.registry_path,
            shared_tool=self.shared_tool,
            identity_runtime_root=self.source.identity_runtime_root,
        )
        _need(
            intake_digest(rebuilt) == intake_digest(receipt),
            "ADMITTED_CAPTURE_BINDING_CHANGED",
        )
        capture = self.store.load("receipt", receipt["capture_revision"])
        original = self.store.load("snapshot", capture["snapshot_id"])
        key = uid + ":" + receipt["canvas_assignment_id"]
        observed, now = original["cells"].get(key), current["cells"].get(key)
        _need(
            type(observed) is dict
            and type(now) is dict
            and type(observed.get("attempt")) is int
            and observed["attempt"] == now.get("attempt")
            and observed.get("submitted_at") == now.get("submitted_at"),
            "ORIGINAL_CANVAS_ATTEMPT_CHANGED",
        )
        maximum = _amount(payload["computation"]["maximum"])
        _need(
            maximum > 0 and _amount(target["maximum"]) == maximum,
            "NATIVE_POINT_SCALE_CHANGED",
        )
        # This is the Canvas-capture lane. No paper reassessment/form or
        # assessment-specific normalization is inferred from a generic result.
        record = {
            "evaluation_id": snapshot["result_id"],
            "result_revision": snapshot["result_id"],
            "source_revision": deps["evidence"]["evidence_revision"],
            "source_key": snapshot["case_key"],
            "state": "READY_FOR_REVIEW",
            "policy": deps["scope"]["policy_revision"],
            "section": self.section,
            "pin": identity["student_pin"],
            "course_id": receipt["course_id"],
            "user_id": uid,
            "assignment_id": receipt["canvas_assignment_id"],
            "paper_attempt": "CANVAS_CAPTURE",
            "form": "NOT_APPLICABLE",
            "canvas_attempt": observed["attempt"],
            "raw_score": _amount(payload["computation"]["total"]),
            "raw_maximum": maximum,
            "proposed_score": _amount(payload["computation"]["total"]),
            "score_scale": "RAW_IDENTITY",
        }
        return record

    def _project_unit1(
        self,
        snapshot: dict[str, Any],
        current: dict[str, Any],
        pin_binding: dict[str, Any],
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        """Map authenticated form points through one explicitly reviewed scale."""
        authority = importlib.import_module("localgrass.teacher_edit_unit1")
        _need(
            isinstance(self.source, authority.AuthenticatedUnit1DecisionSource),
            "UNIT1_SOURCE_AUTHORITY_REQUIRED",
        )
        record = self._project_unit1_record(snapshot, current, pin_binding)
        maximum = record["raw_maximum"]
        scale = record["score_scale"]
        native_maximum = 100 if scale == UNIT1_WHOLE_PERCENT else maximum
        decision = {
            key: record[key]
            for key in ("evaluation_id", "source_revision", "result_revision", "policy")
        }
        decision.update(
            decision_revision=snapshot["decision_id"],
            is_final=True,
            total_score=_unit1_native_score(
                snapshot["decision"]["score"], maximum, scale
            ),
            points_possible=native_maximum,
            score_units="CANVAS_POINTS",
            feedback=snapshot["decision"]["feedback"],
        )
        return record, decision

    def _project_unit1_record(
        self,
        snapshot: dict[str, Any],
        current: dict[str, Any],
        pin_binding: dict[str, Any],
    ) -> dict[str, Any]:
        """Rebuild form/scale/target only; callers validate concrete authority."""
        payload, receipt = snapshot["payload"], snapshot["source_receipt"]
        deps, computation = payload["dependencies"], payload["computation"]
        _need(
            snapshot["source_verified"] is True
            and not payload["holds"]
            and computation["status"] == "VERIFIED_OWNER_RESULT"
            and computation["units"] == "FORM_POINTS"
            and receipt["producer"] == "GRASS_UNIT1_VERIFIED_OWNER_RESULT_V1",
            "UNIT1_SOURCE_RESULT_HELD",
        )
        paper, identity = receipt["paper"], receipt["identity"]
        subject = paper["subject"]
        _need(
            subject["section"] == self.section
            and subject["pin"] == identity["student_pin"],
            "UNIT1_PAPER_SCOPE_CHANGED",
        )
        _need(
            self.files.file_sha(self.assignment_path) == self.assignment_sha256,
            "ASSIGNMENT_BINDINGS_CHANGED",
        )
        assignments = self.files.load(self.assignment_path)
        _need(
            self.files.file_sha(self.assignment_path) == self.assignment_sha256
            and type(assignments) is list,
            "ASSIGNMENT_BINDINGS_CHANGED",
        )
        selected = [
            row
            for row in assignments
            if type(row) is dict
            and row.get("assignment_key") == snapshot["assignment_id"]
            and row.get("student_track") == deps["scope"]["track"]
            and str(row.get("course_id")) == current["course_id"]
            and row.get("section") == self.section
        ]
        _need(len(selected) == 1, "EXACT_CENTRAL_ASSIGNMENT_REQUIRED")
        target = selected[0]
        maximum = _amount(computation["maximum"])
        native_maximum = _amount(target["maximum"])
        scale = target.get("score_scale")
        if not isinstance(scale, str):
            raise GradebookError("UNIT1_EXPLICIT_SCORE_SCALE_REQUIRED")
        _need(
            maximum > 0 and scale in {"RAW_IDENTITY", UNIT1_WHOLE_PERCENT},
            "UNIT1_EXPLICIT_SCORE_SCALE_REQUIRED",
        )
        if scale == "RAW_IDENTITY":
            _need(native_maximum == maximum, "UNIT1_SAME_MAX_POINTS_REQUIRED")
        else:
            _need(
                native_maximum == 100
                and _amount(target.get("source_maximum")) == maximum
                and target.get("form_id") == subject["formId"]
                and type(target.get("scale_policy_ref")) is str
                and re.fullmatch(r"sha256:[a-f0-9]{64}", target["scale_policy_ref"]),
                "UNIT1_PERCENT_MAP_REQUIRED",
            )
        _need(
            pin_binding["registry_sha256"] == identity["registry_sha256"]
            and pin_binding["roster_sha256"] == identity["snapshot_sha256"],
            "CURRENT_PIN_AUTHORITY_CHANGED",
        )
        uid = pin_binding["by_pin"].get(identity["student_pin"])
        _need(type(uid) is str, "CANONICAL_PIN_NOT_JOINED")
        aid = str(target["assignment_id"])
        observed = current["cells"].get(uid + ":" + aid)
        observed_null = (
            type(observed) is dict
            and "attempt" in observed
            and observed["attempt"] is None
            and observed.get("submitted_at") is None
        )
        _need(
            type(observed) is dict
            and (
                observed_null
                or type(observed.get("attempt")) is int
                and observed["attempt"] >= 0
            ),
            "OBSERVED_CANVAS_ATTEMPT_REQUIRED",
        )
        record = {
            "evaluation_id": snapshot["result_id"],
            "result_revision": snapshot["result_id"],
            "source_revision": deps["evidence"]["evidence_revision"],
            "source_key": snapshot["case_key"],
            "state": "READY_FOR_REVIEW",
            "policy": deps["scope"]["policy_revision"],
            "section": self.section,
            "pin": identity["student_pin"],
            "course_id": current["course_id"],
            "user_id": uid,
            "assignment_id": aid,
            "paper_attempt": subject["attempt"],
            "form": subject["formId"],
            "canvas_attempt": observed["attempt"],
            "raw_score": _amount(computation["total"]),
            "raw_maximum": maximum,
            "proposed_score": _unit1_native_score(computation["total"], maximum, scale),
            "score_scale": scale,
        }
        if scale == UNIT1_WHOLE_PERCENT:
            record["score_scale_policy_ref"] = target["scale_policy_ref"]
        if observed_null:
            record["canvas_attempt_observation"] = "UNIT1_PAPER_OBSERVED_NULL"
        return record

    def _check(self, snapshot: dict[str, Any], current: dict[str, Any]) -> Any:
        def check(
            record: dict[str, Any], decision: dict[str, Any], pins: dict[str, Any]
        ) -> None:
            try:
                actual_record, actual_decision = self._project(snapshot, current, pins)
                _need(
                    actual_record == record and actual_decision == decision,
                    "AUTHENTICATED_SELECTION_CHANGED",
                )
            except GradebookError:
                raise
            except Exception:
                raise GradebookError("AUTHENTICATED_SELECTION_HELD") from None

        return check

    def prepare(
        self,
        *,
        raw: dict[str, Any],
        binding: dict[str, Any],
        baseline: dict[str, Any],
        current: dict[str, Any],
        pin_binding: dict[str, Any],
    ) -> dict[str, Any]:
        snapshot = self.source.read()
        record, decision = self._project(snapshot, current, pin_binding)
        transfer = prepare_transfer(
            record,
            decision,
            raw=raw,
            binding=binding,
            baseline=baseline,
            current=current,
            pin_binding=pin_binding,
            source_check=self._check(snapshot, current),
            preservation=self.preservation,
        )
        return {
            "contract": CONTRACT,
            "binding": copy.deepcopy(binding),
            "items": [{"key": record["user_id"] + ":" + record["assignment_id"]}],
            "source_snapshot": copy.deepcopy(snapshot),
            "assignment_bindings_sha256": self.assignment_sha256,
            "transfer": transfer,
            "canvas_writes": 0,
            "sheets_writes": 0,
            "score_delivery_authorized": False,
            "comment_delivery_authorized": False,
        }

    @staticmethod
    def validate_plan(plan: dict[str, Any], *, expected_plan_sha256: str) -> None:
        """Bind execution/history scope to the authenticated inner transfer."""
        _need(
            digest(plan) == expected_plan_sha256 and plan.get("contract") == CONTRACT,
            "EXACT_CONNECTION_PLAN_CHANGED",
        )
        transfer = plan.get("transfer")
        if not isinstance(transfer, dict):
            raise GradebookError("AUTHENTICATED_TARGET_CHANGED")
        record = transfer.get("record", {})
        _need(
            type(record) is dict
            and type(record.get("user_id")) is str
            and type(record.get("assignment_id")) is str
            and plan.get("binding") == transfer.get("binding")
            and plan.get("items")
            == [{"key": record["user_id"] + ":" + record["assignment_id"]}]
            and plan.get("canvas_writes") == 0
            and plan.get("sheets_writes") == 0
            and plan.get("score_delivery_authorized") is False
            and plan.get("comment_delivery_authorized") is False,
            "AUTHENTICATED_TARGET_CHANGED",
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
            plan["assignment_bindings_sha256"] == self.assignment_sha256,
            "EXACT_CONNECTION_PLAN_CHANGED",
        )
        _need(
            plan["transfer"].get("preservation") == self.preservation,
            "EXACT_EDIT_PRESERVATION_CHANGED",
        )
        self.source.assert_current(plan["source_snapshot"])
        revalidate_transfer(
            plan["transfer"],
            expected_plan_sha256=digest(plan["transfer"]),
            raw=raw,
            current=current,
            pin_binding=pin_binding,
            source_check=self._check(plan["source_snapshot"], current),
        )

    @staticmethod
    def classify(
        plan: dict[str, Any], raw: dict[str, Any], *, expected_plan_sha256: str
    ) -> dict[str, Any]:
        LocalGrAssEditConnection.validate_plan(
            plan, expected_plan_sha256=expected_plan_sha256
        )
        return classify_readback(
            plan["transfer"], raw, expected_plan_sha256=digest(plan["transfer"])
        )
