"""Authenticated LocalGrAss UNAPPROVED proposal to the existing local EDIT owner.

No teacher acceptance, new transport, or publication authority is created. The
existing owner, workbook lock, private plan/receipt store and one-shot executor
are reused; only source and transfer contracts differ from final decisions.
"""

from __future__ import annotations

import copy
import importlib
from typing import Any

from .client import GradebookError
from .localgrass_teacher_edit import (
    UNIT1_WHOLE_PERCENT,
    LocalGrAssEditConnection,
    _amount,
    _need,
)
from .model import digest
from .proposal_edit_transfer import (
    classify_proposal_readback,
    prepare_proposal_transfer,
    revalidate_proposal_transfer,
)

CONTRACT = "LOCALGRASS_UNAPPROVED_EDIT_V1"


class LocalGrAssProposalEditConnection(LocalGrAssEditConnection):
    """Distinct source/plan contract with the same exact native owner lifecycle."""

    contract = CONTRACT

    @staticmethod
    def _source_files(source: Any) -> Any:
        """Keep proposal authority distinct; inherit all native owner setup."""
        try:
            authority = importlib.import_module("localgrass.teacher_edit_proposal")
            files = importlib.import_module("localgrass.teacher_edit_files")
        except ImportError:
            raise GradebookError("LOCAL_PROPOSAL_SOURCE_NOT_CONFIGURED") from None
        _need(
            isinstance(source, authority.AuthenticatedProposalSource),
            "AUTHENTICATED_PROPOSAL_SOURCE_REQUIRED",
        )
        return files

    def _project(
        self,
        snapshot: dict[str, Any],
        current: dict[str, Any],
        pin_binding: dict[str, Any],
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        self.source.assert_current(snapshot)
        authority = importlib.import_module("localgrass.teacher_edit_proposal")
        _need(
            snapshot.get("contract") == authority.PROPOSAL_CONTRACT
            and snapshot.get("approval_state") == "UNAPPROVED"
            and snapshot.get("academic_accepted") is False
            and snapshot.get("publication_allowed") is False,
            "UNAPPROVED_PROPOSAL_REQUIRED",
        )
        payload = snapshot["payload"]
        if payload.get("result_kind") == "GRASS_UNIT1_VERIFIED_OWNER_RESULT_V1":
            _need(
                isinstance(self.source, authority.AuthenticatedUnit1ProposalSource),
                "UNIT1_PROPOSAL_SOURCE_REQUIRED",
            )
            record = self._project_unit1_record(snapshot, current, pin_binding)
        else:
            academic = self.source.review.registry.get_revision(
                importlib.import_module("localgrass.admission").Scope(
                    **payload["dependencies"]["scope"]
                )
            )
            kind = academic.get("scoring_policy", {}).get("policy_kind")
            _need(
                type(kind) is str and kind and not kind.startswith("FICTIONAL"),
                "LOCAL_EDIT_REAL_POLICY_REQUIRED",
            )
            record = self._project_record(snapshot, current, pin_binding)
        maximum = (
            100
            if record["score_scale"] == UNIT1_WHOLE_PERCENT
            else record["raw_maximum"]
        )
        proposal = {
            k: record[k]
            for k in ("evaluation_id", "source_revision", "result_revision", "policy")
        }
        proposal.update(
            proposal_revision=snapshot["proposal_id"],
            approval_state="UNAPPROVED",
            academic_accepted=False,
            total_score=record["proposed_score"],
            points_possible=_amount(maximum),
            score_units="CANVAS_POINTS",
            feedback=payload["feedback"],
        )
        return record, proposal

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
        record, proposal = self._project(snapshot, current, pin_binding)
        transfer = prepare_proposal_transfer(
            record,
            proposal,
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
            "approval_state": "UNAPPROVED",
            "academic_accepted": False,
            "score_delivery_authorized": False,
            "comment_delivery_authorized": False,
        }

    @staticmethod
    def validate_plan(plan: dict[str, Any], *, expected_plan_sha256: str) -> None:
        _need(
            digest(plan) == expected_plan_sha256 and plan.get("contract") == CONTRACT,
            "EXACT_PROPOSAL_CONNECTION_PLAN_CHANGED",
        )
        transfer: Any = plan.get("transfer")
        _need(type(transfer) is dict, "AUTHENTICATED_TARGET_CHANGED")
        record, proposal = transfer.get("record", {}), transfer.get("proposal", {})
        source = plan.get("source_snapshot", {})
        _need(
            type(record) is dict
            and type(record.get("user_id")) is str
            and type(record.get("assignment_id")) is str
            and plan.get("binding") == transfer.get("binding")
            and plan.get("items")
            == [{"key": record["user_id"] + ":" + record["assignment_id"]}]
            and source.get("proposal_id") == proposal.get("proposal_revision")
            and source.get("approval_state")
            == plan.get("approval_state")
            == "UNAPPROVED"
            and source.get("academic_accepted")
            is plan.get("academic_accepted")
            is False
            and plan.get("canvas_writes") == plan.get("sheets_writes") == 0
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
            "EXACT_PROPOSAL_CONNECTION_PLAN_CHANGED",
        )
        _need(
            plan["transfer"].get("preservation") == self.preservation,
            "EXACT_EDIT_PRESERVATION_CHANGED",
        )
        self.source.assert_current(plan["source_snapshot"])
        revalidate_proposal_transfer(
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
        LocalGrAssProposalEditConnection.validate_plan(
            plan, expected_plan_sha256=expected_plan_sha256
        )
        return classify_proposal_readback(
            plan["transfer"], raw, expected_plan_sha256=digest(plan["transfer"])
        )
