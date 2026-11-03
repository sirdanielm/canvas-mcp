"""Pure whole-test Unit 2 numeric drafts; no grading, transport or publication.

This is a local candidate wrapper, not a new native producer. The synchronous
owner check must authenticate the exact existing whole grade_preview, complete
source/QC/policy/head evidence, floor provenance, identity and current target.
Supplied counts, hashes and false approval flags establish no such authority.
Teacher-final transfer and publisher gates remain independent and unchanged.
The caller must retain canonical baseline, axes, header and protection checks,
existing writer locks, exact preimage qualification and complete native readback.
This wrapper supplies no source authentication or dispatch authority of its own.
"""

from __future__ import annotations

import copy
import hashlib
import re
from dataclasses import asdict, dataclass
from fractions import Fraction
from typing import Any
from urllib.parse import urlsplit

from .client import GradebookError
from .model import digest
from .teacher_edit_transfer import _location
from .unit2_note_draft import EditOnlyAuthorization, SourceCheck, _id, _source, _state

CONTRACT = "UNIT2_UNAPPROVED_NUMERIC_DRAFT_V5"
START = "[[UNIT2 UNAPPROVED WHOLE NUMERIC "
END = "[[END UNIT2 UNAPPROVED WHOLE NUMERIC]]"
HASH = re.compile(r"[a-f0-9]{64}")
INTEGER = re.compile(r"(?:0|[1-9][0-9]?|100)")
NATIVE_NUMBER = re.compile(r"(?:0|[1-9][0-9]*)(?:\.[0-9]*[1-9]|/[1-9][0-9]*)?")
FLAGS = (
    "is_final",
    "teacher_accepted",
    "publication_allowed",
    "score_delivery_authorized",
    "comment_delivery_authorized",
)


def _need(condition: object, code: str) -> None:
    if not condition:
        raise GradebookError(code)


def _score(value: object, code: str) -> int:
    _need(type(value) is str and INTEGER.fullmatch(value), code)
    return int(str(value))


def _native_preview(value: object) -> Fraction:
    """Parse the owning native number_text syntax without float conversion.

    Finite native fractions use a trimmed exact decimal; reduced p/q is used
    only for a nonterminating fraction. Validate that spelling without emitting
    or substituting a new source preview.
    """
    _need(
        type(value) is str and len(value) <= 160 and NATIVE_NUMBER.fullmatch(value),
        "UNIT2_EXACT_GRADE_PREVIEW_REQUIRED",
    )
    exact = Fraction(str(value))
    _need(0 <= exact <= 100, "UNIT2_EXACT_GRADE_PREVIEW_REQUIRED")
    if "/" in str(value):
        denominator = exact.denominator
        for factor in (2, 5):
            while denominator % factor == 0:
                denominator //= factor
        _need(
            str(exact) == value and denominator != 1,
            "UNIT2_EXACT_GRADE_PREVIEW_REQUIRED",
        )
    return exact


def _form_proof(proof: dict[str, Any], candidate: dict[str, Any]) -> None:
    """Validate the form-bound item proof; the owner authenticates its origins.

    question_map_sha256 is the native canonical qmap digest from packet.json,
    not the pretty artifact's byte hash. The owner must independently replay
    question_map(package_form(academic, packet.form_id)) and bind result kinds
    and IDs. Explicit authenticated kind:ID composites may disambiguate issued
    raw namespaces; this function never invents or normalizes those IDs.
    """
    _need(
        type(proof) is dict
        and set(proof)
        == {
            "contract",
            "form_id",
            "packet_sha256",
            "academic_sha256",
            "result_sha256",
            "policy_sha256",
            "question_map_sha256",
            "expected_items",
            "actual_items",
        }
        and proof["contract"] == "UNIT2_NATIVE_FORM_PROOF_V1"
        and type(proof["form_id"]) is str
        and 0 < len(proof["form_id"]) <= 100
        and proof["form_id"].strip() == proof["form_id"]
        and all(
            proof[key] == candidate["source_pins"][key]
            for key in (
                "packet_sha256",
                "academic_sha256",
                "result_sha256",
                "policy_sha256",
            )
        )
        and type(proof["question_map_sha256"]) is str
        and HASH.fullmatch(proof["question_map_sha256"]),
        "UNIT2_NATIVE_FORM_BINDING_REQUIRED",
    )
    for field in ("expected_items", "actual_items"):
        mapping = proof[field]
        _need(
            type(mapping) is dict and set(mapping) == {"MC", "FRQ"},
            "UNIT2_NATIVE_FORM_ITEMS_REQUIRED",
        )
        for kind in ("MC", "FRQ"):
            items = mapping[kind]
            _need(
                type(items) is list
                and (len(items) in (20, 24) if kind == "MC" else len(items) == 4)
                and all(
                    type(item) is str and 0 < len(item) <= 200 and item.strip() == item
                    for item in items
                )
                and len(set(items)) == len(items),
                "UNIT2_NATIVE_FORM_ITEMS_REQUIRED",
            )
        _need(
            not set(mapping["MC"]).intersection(mapping["FRQ"]),
            "UNIT2_NATIVE_FORM_KIND_COLLISION",
        )
    _need(
        proof["expected_items"] == proof["actual_items"]
        and sum(len(items) for items in proof["actual_items"].values())
        == candidate["native_item_count"],
        "UNIT2_NATIVE_FORM_INCOMPLETE",
    )


@dataclass(frozen=True)
class V7FeedbackContext:
    """Trusted caller inputs, never loaded from a staging request or plan.

    The original owner separately authenticates current native records, cue
    authority and the independent expected binding. This contains no grant.
    """

    expected_source_binding: dict[str, Any]
    formatter_source: bytes
    format_contract: bytes
    native_adapter_source: bytes


def _v7_feedback(
    proof: dict[str, Any], candidate: dict[str, Any], context: V7FeedbackContext | None
) -> None:
    _need(type(context) is V7FeedbackContext, "UNIT2_V7_OWNER_CONTEXT_REQUIRED")
    assert context is not None
    from . import comment_policy
    from .comment_policy import CommentContractError

    validator = getattr(comment_policy, "require_bound_v7_formatter", None)
    if not callable(validator):
        raise GradebookError("UNIT2_V7_CONSUMER_NOT_INSTALLED")

    formatter = proof["formatter"]
    _need(type(formatter) is dict, "UNIT2_V7_TYPED_FORMATTER_REQUIRED")
    binding = context.expected_source_binding
    _need(type(binding) is dict, "UNIT2_V7_OWNER_CONTEXT_REQUIRED")
    links = {
        "source_sha256": "source_sha256",
        "packet_sha256": "packet_json_sha256",
        "reading_sha256": "reading_json_sha256",
        "result_sha256": "result_json_sha256",
        "academic_sha256": "academic_sha256",
        "policy_sha256": "policy_sha256",
    }
    _need(
        all(
            binding.get(remote) == candidate["source_pins"][local]
            for local, remote in links.items()
        ),
        "UNIT2_V7_NATIVE_BYTE_BINDING_HELD",
    )
    try:
        checked = validator(
            proof["body"],
            formatter,
            expected_source_binding=copy.deepcopy(binding),
            formatter_source=context.formatter_source,
            format_contract=context.format_contract,
            native_adapter_source=context.native_adapter_source,
        )
    except CommentContractError as exc:
        raise GradebookError("UNIT2_V7_FEEDBACK_HELD: " + str(exc)) from None
    _need(
        checked["formatter_source_sha256"] == proof["formatter_sha256"]
        and checked["format_contract_sha256"] == proof["contract_sha256"]
        and checked["native_adapter_sha256"] == proof["native_adapter_sha256"],
        "UNIT2_V7_CODE_PROOF_PINS_REQUIRED",
    )
    # Known child losses preserve a null parent; they cannot establish a whole
    # numeric total even if an untrusted candidate claims zero native holds.
    _need(
        not formatter["known_criterion_losses"]
        and formatter["student_hold_row_count"] == 0
        and formatter["teacher_review_required"] is False
        and all(part["earned_points"] is not None for part in formatter["frq_parts"]),
        "UNIT2_V7_PARTIAL_FEEDBACK_HELD",
    )


def _feedback_proof(
    proof: dict[str, Any],
    candidate: dict[str, Any],
    *,
    v7_feedback_context: V7FeedbackContext | None = None,
) -> str:
    """Bind a legacy whole body or explicit V7 output without rendering it.

    The existing formatter/contract/projection pin names match the MC note
    adapter. projection_sha256 identifies the saved canonical projection bytes.
    Hash shape and body equality do not authenticate a source: the independent
    owner callback must verify the exact saved projection, body and all pins.
    """
    is_v7 = (
        type(proof) is dict
        and proof.get("source_version") == "UNIT2_COMPACT_FEEDBACK_V7"
    )
    _need(
        type(proof) is dict
        and set(proof)
        == {
            "contract",
            "source_version",
            "component_scope",
            "body",
            "body_sha256",
            "source_binding",
            "formatter_sha256",
            "contract_sha256",
            "projection_sha256",
        }
        | ({"formatter", "native_adapter_sha256"} if is_v7 else set())
        and proof["contract"]
        == (
            "UNIT2_WHOLE_FEEDBACK_PROOF_V2"
            if is_v7
            else "UNIT2_WHOLE_FEEDBACK_PROOF_V1"
        )
        and (
            is_v7
            or proof["source_version"]
            in {"UNIT2_COMPACT_FEEDBACK_V2", "UNIT2_COMPACT_FEEDBACK_V3"}
        )
        and proof["component_scope"] == "WHOLE_TEST",
        "UNIT2_FEEDBACK_PROOF_REQUIRED",
    )
    body: str = proof["body"]
    _need(
        type(body) is str
        and 0 < len(body) <= 50_000
        and bool(body.strip())
        and START not in body
        and END not in body,
        "UNIT2_FEEDBACK_BODY_REQUIRED",
    )
    try:
        body_sha256 = hashlib.sha256(body.encode("utf-8")).hexdigest()
    except UnicodeError:
        raise GradebookError("UNIT2_FEEDBACK_BODY_REQUIRED") from None
    _need(
        all(
            type(proof[key]) is str and HASH.fullmatch(proof[key])
            for key in (
                "body_sha256",
                "formatter_sha256",
                "contract_sha256",
                "projection_sha256",
            )
        )
        and body_sha256 == proof["body_sha256"],
        "UNIT2_FEEDBACK_PINS_REQUIRED",
    )
    fields = {
        "source_sha256",
        "packet_sha256",
        "reading_sha256",
        "reading_manifest_sha256",
        "result_sha256",
        "policy_sha256",
        "academic_sha256",
        "current_head_sha256",
    }
    _need(
        type(proof["source_binding"]) is dict
        and proof["source_binding"]
        == {key: candidate["source_pins"][key] for key in fields},
        "UNIT2_FEEDBACK_SOURCE_HELD",
    )
    if is_v7:
        _v7_feedback(proof, candidate, v7_feedback_context)
    else:
        _need(v7_feedback_context is None, "UNIT2_EXPLICIT_FEEDBACK_VERSION_REQUIRED")
    return body


def _rounding_proof(
    proof: dict[str, Any], candidate: dict[str, Any], target: dict[str, Any]
) -> None:
    """Bind a separate teacher display rule; the owner authenticates authority.

    This never changes the sealed native policy. UNSPECIFIED permits nearest
    non-ties only; it does not inherit another assessment's half-tie rule.
    """
    _need(
        type(proof) is dict
        and set(proof)
        == {
            "contract",
            "mode",
            "application_order",
            "tie_breaker",
            "assessment",
            "paper_attempt",
            "evidence_ref",
            "evidence_sha256",
            "scope",
            "source_binding",
        }
        and proof["contract"] == "UNIT2_TEACHER_ROUNDING_V1"
        and proof["mode"] == "NEAREST_WHOLE_PERCENT"
        and proof["application_order"] == "FLOOR_THEN_ROUND"
        and proof["tie_breaker"] == "UNSPECIFIED"
        and proof["assessment"] == "UNIT2"
        and proof["paper_attempt"] == "R1"
        and type(proof["evidence_ref"]) is str
        and 0 < len(proof["evidence_ref"].strip()) <= 300
        and type(proof["evidence_sha256"]) is str
        and HASH.fullmatch(proof["evidence_sha256"]),
        "UNIT2_ROUNDING_PROOF_REQUIRED",
    )
    _need(
        type(proof["scope"]) is dict
        and proof["scope"]
        == {key: target[key] for key in ("origin", "course_id", "assignment_id")}
        and type(proof["source_binding"]) is dict
        and proof["source_binding"]
        == {
            key: candidate["source_pins"][key]
            for key in (
                "source_sha256",
                "packet_sha256",
                "reading_sha256",
                "reading_manifest_sha256",
                "result_sha256",
                "policy_sha256",
                "academic_sha256",
                "current_head_sha256",
            )
        },
        "UNIT2_ROUNDING_BINDING_HELD",
    )


def prepare_numeric_draft(
    candidate: dict[str, Any],
    *,
    raw: dict[str, Any],
    binding: dict[str, Any],
    target: dict[str, Any],
    identity_binding: dict[str, Any],
    canvas_observation: dict[str, Any],
    floor_proof: dict[str, Any],
    form_proof: dict[str, Any],
    feedback_proof: dict[str, Any],
    rounding_proof: dict[str, Any],
    authorization: EditOnlyAuthorization,
    source_check: SourceCheck,
    v7_feedback_context: V7FeedbackContext | None = None,
) -> dict[str, Any]:
    """Plan one integer and exact whole feedback in an UNAPPROVED cell update.

    The exact native preview remains unchanged. A separately authenticated,
    scoped teacher administrative floor may derive max(complete native, 40)
    for this local draft; it never changes the native policy or accepts a grade.
    The separately authenticated nearest-percent rule applies after that floor,
    using exact rational arithmetic. Exact-half ties remain held because their
    policy is unspecified. Unknown or incomplete previews remain held. Canvas
    UNGRADED/None and an explicitly attested absent floor are distinct facts.
    None currentness stays a downstream final-review hold, never True.
    """
    candidate = copy.deepcopy(candidate)
    binding = copy.deepcopy(binding)
    target = copy.deepcopy(target)
    identity_binding = copy.deepcopy(identity_binding)
    canvas_observation = copy.deepcopy(canvas_observation)
    floor_proof = copy.deepcopy(floor_proof)
    form_proof = copy.deepcopy(form_proof)
    feedback_proof = copy.deepcopy(feedback_proof)
    rounding_proof = copy.deepcopy(rounding_proof)
    _need(
        type(candidate) is dict
        and set(candidate)
        == {
            "contract",
            "status",
            "component_scope",
            "native_item_count",
            "native_hold_count",
            "grade_preview",
            "points_possible",
            "source_pins",
            "target",
            *FLAGS,
        },
        "UNIT2_WHOLE_CANDIDATE_SCHEMA_REQUIRED",
    )
    _need(
        candidate["contract"] == "UNIT2_WHOLE_NUMERIC_DRAFT_V1"
        and candidate["status"] == "PROPOSED_REVIEW_REQUIRED"
        and candidate["component_scope"] == "WHOLE_TEST"
        and type(candidate["native_item_count"]) is int
        and 1 <= candidate["native_item_count"] <= 100
        and type(candidate["native_hold_count"]) is int
        and candidate["native_hold_count"] == 0
        and type(candidate["points_possible"]) is int
        and candidate["points_possible"] == 100
        and all(candidate[key] is False for key in FLAGS),
        "UNIT2_WHOLE_PROPOSAL_REQUIRED",
    )
    administrative = type(floor_proof) is dict and "contract" in floor_proof
    earned = _native_preview(candidate["grade_preview"])
    pins = candidate["source_pins"]
    _need(
        type(pins) is dict
        and {
            "source_sha256",
            "packet_sha256",
            "reading_sha256",
            "reading_manifest_sha256",
            "result_sha256",
            "policy_sha256",
            "academic_sha256",
            "current_head_sha256",
        }
        <= set(pins)
        and all(
            type(key) is str
            and key.endswith("_sha256")
            and type(value) is str
            and HASH.fullmatch(value)
            for key, value in pins.items()
        ),
        "UNIT2_WHOLE_SOURCE_PINS_REQUIRED",
    )
    _form_proof(form_proof, candidate)
    feedback_body = _feedback_proof(
        feedback_proof, candidate, v7_feedback_context=v7_feedback_context
    )
    if feedback_proof["source_version"] == "UNIT2_COMPACT_FEEDBACK_V7":
        formatter = feedback_proof["formatter"]
        _need(
            type(identity_binding) is dict
            and type(formatter.get("identity")) is dict
            and formatter["identity"].get("verified") is True
            and formatter["identity"].get("pin") == identity_binding.get("pin")
            and formatter["identity"].get("test_form") == form_proof["form_id"]
            and formatter.get("form") == form_proof["form_id"],
            "UNIT2_V7_IDENTITY_FORM_BINDING_HELD",
        )
    _need(
        type(target) is dict
        and set(target)
        == {
            "origin",
            "course_id",
            "assignment_id",
            "user_id",
            "attempt",
            "submitted_at",
            "submission_types",
        }
        and candidate["target"] == target,
        "UNIT2_EXACT_TARGET_REQUIRED",
    )
    origin = target["origin"]
    _need(
        type(origin) is str
        and urlsplit(origin).scheme == "https"
        and bool(urlsplit(origin).netloc)
        and not urlsplit(origin).username
        and not urlsplit(origin).password
        and not urlsplit(origin).query
        and not urlsplit(origin).fragment
        and urlsplit(origin).path in ("", "/")
        and all(_id(target[key]) for key in ("course_id", "assignment_id", "user_id")),
        "UNIT2_EXACT_TARGET_REQUIRED",
    )
    _need(
        target["submission_types"] == ["on_paper"]
        and target["attempt"] is None
        and target["submitted_at"] is None,
        "UNIT2_OBSERVED_PAPER_NULL_REQUIRED",
    )
    _need(
        type(identity_binding) is dict
        and set(identity_binding)
        == {
            "pin",
            "user_id",
            "registry_sha256",
            "roster_sha256",
        }
        and identity_binding["user_id"] == target["user_id"]
        and type(identity_binding["pin"]) is str
        and re.fullmatch(r"[0-9]{4}", identity_binding["pin"])
        and all(
            type(identity_binding[key]) is str and HASH.fullmatch(identity_binding[key])
            for key in ("registry_sha256", "roster_sha256")
        ),
        "UNIT2_EXACT_IDENTITY_REQUIRED",
    )
    _need(
        type(canvas_observation) is dict
        and set(canvas_observation)
        == {
            "target",
            "grade_observation",
            "score",
            "grade",
            "excused",
            "visible",
            "workflow_state",
            "grade_matches_current_submission",
            "closed_period",
            "observation_sha256",
        }
        and canvas_observation["target"] == target
        and canvas_observation["grade_observation"] == "UNGRADED"
        and canvas_observation["score"] is None
        and canvas_observation["grade"] is None
        and canvas_observation["excused"] is False
        and canvas_observation["visible"] is True
        and canvas_observation["workflow_state"] in ("unsubmitted", "submitted")
        and (
            canvas_observation["grade_matches_current_submission"] is None
            or canvas_observation["grade_matches_current_submission"] is True
        )
        and (
            canvas_observation["closed_period"] is None
            or type(canvas_observation["closed_period"]) is bool
        )
        and type(canvas_observation["observation_sha256"]) is str
        and HASH.fullmatch(canvas_observation["observation_sha256"]),
        "UNIT2_CURRENT_CANVAS_UNGRADED_REQUIRED",
    )
    _need(
        canvas_observation["closed_period"] is not True,
        "UNIT2_CLOSED_PERIOD_HELD",
    )
    floor_fields = {
        "status",
        "value",
        "policy_sha256",
        "evidence_sha256",
        "evidence_ref",
    }
    admin_fields = {
        "contract",
        "application",
        "assessment",
        "paper_attempt",
        "scope",
        "source_binding",
    }
    _need(
        type(floor_proof) is dict
        and set(floor_proof)
        == floor_fields | (admin_fields if administrative else set())
        and floor_proof["policy_sha256"] == pins["policy_sha256"]
        and type(floor_proof["evidence_sha256"]) is str
        and HASH.fullmatch(floor_proof["evidence_sha256"])
        and type(floor_proof["evidence_ref"]) is str
        and 0 < len(floor_proof["evidence_ref"].strip()) <= 300,
        "UNIT2_EXPLICIT_FLOOR_PROOF_REQUIRED",
    )
    if administrative:
        # This is a separate teacher administrative decision. It must not be
        # presented as a field that the unchanged native policy already had.
        _need(
            floor_proof["contract"] == "UNIT2_TEACHER_ADMIN_FLOOR_V1"
            and floor_proof["application"] == "MAX_COMPLETE_NATIVE_GRADE_AND_FLOOR"
            and floor_proof["status"] == "DEFINED"
            and floor_proof["value"] == "40"
            and floor_proof["assessment"] == "UNIT2"
            and floor_proof["paper_attempt"] == "R1"
            and type(floor_proof["scope"]) is dict
            and floor_proof["scope"]
            == {key: target[key] for key in ("origin", "course_id", "assignment_id")}
            and type(floor_proof["source_binding"]) is dict
            and floor_proof["source_binding"]
            == {
                key: pins[key]
                for key in (
                    "source_sha256",
                    "packet_sha256",
                    "result_sha256",
                    "current_head_sha256",
                )
            },
            "UNIT2_ADMIN_FLOOR_BINDING_HELD",
        )
    elif floor_proof["status"] == "DEFINED":
        # Historical five-field proofs are minimum-admission guards only.
        # They do not authorize deriving a different reported draft grade.
        floor = _score(floor_proof["value"], "UNIT2_EXACT_POLICY_FLOOR_REQUIRED")
        _need(earned >= floor, "UNIT2_BELOW_POLICY_FLOOR_HELD")
    else:
        _need(
            floor_proof["status"] == "NO_ASSESSMENT_FLOOR_DEFINED"
            and floor_proof["value"] is None,
            "UNIT2_UNKNOWN_POLICY_FLOOR_HELD",
        )
    _rounding_proof(rounding_proof, candidate, target)
    _need(
        type(authorization) is EditOnlyAuthorization
        and authorization.mode == "EDIT_ONLY"
        and (authorization.origin, authorization.course_id, authorization.assignment_id)
        == (origin, target["course_id"], target["assignment_id"])
        and type(authorization.approval_reference) is str
        and 0 < len(authorization.approval_reference.strip()) <= 300,
        "UNIT2_EDIT_ONLY_AUTHORIZATION_REQUIRED",
    )
    # This independent owner callback authenticates actual policy-floor meaning,
    # zero native source holds and current producer readiness; it never accepts.
    _source(
        source_check,
        candidate,
        target,
        identity_binding,
        canvas_observation,
        floor_proof,
        form_proof,
        feedback_proof,
        rounding_proof,
    )
    raw_grade_preview = candidate["grade_preview"]
    projected = max(earned, Fraction(40)) if administrative else earned
    whole, remainder = divmod(projected.numerator, projected.denominator)
    _need(2 * remainder != projected.denominator, "UNIT2_ROUNDING_TIE_HELD")
    score = whole + (1 if 2 * remainder > projected.denominator else 0)
    staged_grade_preview = str(score)
    floor_applied = projected != earned
    rounding_applied = Fraction(score) != projected
    before = _state(raw)
    _need(
        before["spreadsheetId"] == binding.get("spreadsheet_id")
        and str(binding.get("course_id")) == target["course_id"]
        and type(binding.get("sheets")) is dict
        and type(binding.get("tab_names")) is dict,
        "UNIT2_BOUND_WORKBOOK_REQUIRED",
    )
    _need(
        set(binding["sheets"])
        == set(binding["tab_names"])
        == {"Canvas", "Working", "_Sync"}
        and all(type(sid) is int for sid in binding["sheets"].values())
        and len(set(binding["sheets"].values())) == 3,
        "UNIT2_BOUND_WORKBOOK_REQUIRED",
    )
    for role, sid in binding["sheets"].items():
        _need(
            str(sid) in before["sheets"]
            and before["sheets"][str(sid)]["properties"]["title"]
            == binding["tab_names"][role],
            "UNIT2_BOUND_TAB_CHANGED",
        )
    sid = binding["sheets"]["Working"]
    cells = before["sheets"][str(sid)]["cells"]
    row, col = _location(cells, target)
    address = f"{row}:{col}"
    old = cells.get(address, {})
    old_note = old.get("note", "")
    _need(type(old_note) is str, "UNIT2_NATIVE_NOTE_REQUIRED")
    selection = {
        "candidate": candidate,
        "binding": binding,
        "target": target,
        "identity_binding": identity_binding,
        "canvas_observation": canvas_observation,
        "floor_proof": floor_proof,
        "form_proof": form_proof,
        "feedback_proof": feedback_proof,
        "rounding_proof": rounding_proof,
        "authorization": asdict(authorization),
    }
    selection_sha256 = digest(selection)
    block = (
        START + selection_sha256 + "]]\n"
        "UNAPPROVED whole-test numeric draft for teacher review: "
        + staged_grade_preview
        + "/100.\n"
        + "Native whole-test preview: "
        + raw_grade_preview
        + "/100.\n"
        + (
            "Administrative draft floor: 40/100; staged draft: "
            + staged_grade_preview
            + "/100.\n"
            if administrative
            else ""
        )
        + "Not a final teacher grade; no academic acceptance or Canvas delivery authorized.\n"
        + "Nearest whole percent: "
        + staged_grade_preview
        + "/100; exact-half ties held pending policy.\n"
        + "Canonical whole-test feedback:\n"
        + feedback_body
        + "\n"
        + END
    )
    after = copy.deepcopy(before)
    if START in old_note or END in old_note:
        _need(
            (old_note == block or old_note.endswith("\n\n" + block))
            and old_note.count(START) == old_note.count(END) == 1
            and digest(old.get("userEnteredValue")) == digest({"numberValue": score}),
            "UNIT2_CONFLICTING_NUMERIC_DRAFT_HELD",
        )
        requests: list[dict[str, Any]] = []
        status = "NO_CHANGE"
    else:
        _need(not old.get("userEnteredValue"), "UNIT2_BLANK_DESTINATION_REQUIRED")
        note = old_note + ("\n\n" if old_note else "") + block
        _need(len(note) <= 50_000, "UNIT2_NOTE_CAPACITY_HELD")
        replacement = {"userEnteredValue": {"numberValue": score}, "note": note}
        after["sheets"][str(sid)]["cells"].setdefault(address, {}).update(replacement)
        requests = [
            {
                "updateCells": {
                    "start": {"sheetId": sid, "rowIndex": row, "columnIndex": col},
                    "rows": [{"values": [replacement]}],
                    "fields": "userEnteredValue,note",
                }
            }
        ]
        status = "PREPARED_UNAPPROVED_NUMERIC_DRAFT"
    return {
        "contract": CONTRACT,
        "status": status,
        **selection,
        "selection_sha256": selection_sha256,
        "raw_grade_preview": raw_grade_preview,
        "raw_grade_exact": str(earned),
        "post_floor_grade_exact": str(projected),
        "staged_grade_preview": staged_grade_preview,
        "floor_applied": floor_applied,
        "rounding_applied": rounding_applied,
        "before_state": before,
        "after_state": after,
        "before_fingerprint": digest(before),
        "after_fingerprint": digest(after),
        "requests": requests,
        "canvas_requests": [],
        "currentness_hold": "FINAL_CURRENTNESS_REVIEW_REQUIRED"
        if canvas_observation["grade_matches_current_submission"] is None
        else None,
        "grading_period_hold": "CLOSED_PERIOD_UNCONFIRMED"
        if canvas_observation["closed_period"] is None
        else None,
        **dict.fromkeys(FLAGS, False),
        "canvas_writes": 0,
        "sheets_writes": 0,
        "numeric_grade_disposition": "UNAPPROVED_LOCAL_DRAFT_ONLY",
    }


def _plan(plan: dict[str, Any], expected_plan_sha256: str) -> None:
    _need(
        type(expected_plan_sha256) is str
        and HASH.fullmatch(expected_plan_sha256)
        and digest(plan) == expected_plan_sha256
        and plan.get("contract") == CONTRACT
        and all(plan.get(key) is False for key in FLAGS)
        and plan.get("canvas_requests") == [],
        "UNIT2_NUMERIC_PLAN_CHANGED",
    )


def revalidate_numeric_draft(
    plan: dict[str, Any],
    *,
    raw: dict[str, Any],
    expected_plan_sha256: str,
    source_check: SourceCheck,
    v7_feedback_context: V7FeedbackContext | None = None,
) -> None:
    """Require every native preimage field and independently requalify sources."""
    _plan(plan, expected_plan_sha256)
    _need(
        digest(_state(raw)) == plan["before_fingerprint"],
        "UNIT2_STALE_NUMERIC_PREIMAGE",
    )
    fresh = prepare_numeric_draft(
        plan["candidate"],
        raw=raw,
        binding=plan["binding"],
        target=plan["target"],
        identity_binding=plan["identity_binding"],
        canvas_observation=plan["canvas_observation"],
        floor_proof=plan["floor_proof"],
        form_proof=plan["form_proof"],
        feedback_proof=plan["feedback_proof"],
        rounding_proof=plan["rounding_proof"],
        authorization=EditOnlyAuthorization(**plan["authorization"]),
        source_check=source_check,
        v7_feedback_context=v7_feedback_context,
    )
    _need(digest(fresh) == expected_plan_sha256, "UNIT2_NUMERIC_PLAN_CHANGED")


def classify_readback(
    plan: dict[str, Any],
    raw: dict[str, Any],
    *,
    expected_plan_sha256: str,
) -> dict[str, Any]:
    """Full native comparison only; uncertainty never grants a retry or finality."""
    _plan(plan, expected_plan_sha256)
    actual = _state(raw)
    actual_fingerprint = digest(actual)
    status = (
        "PLANNED_OUTPUT_OBSERVED"
        if actual_fingerprint == plan["after_fingerprint"]
        else "BEFORE_STILL_PRESENT"
        if actual_fingerprint == plan["before_fingerprint"]
        else "DIVERGED"
    )
    return {
        "contract": CONTRACT,
        "status": status,
        "plan_sha256": expected_plan_sha256,
        "actual_fingerprint": actual_fingerprint,
        "feedback_proof_sha256": digest(plan["feedback_proof"]),
        "rounding_proof_sha256": digest(plan["rounding_proof"]),
        "currentness_hold": plan["currentness_hold"],
        "grading_period_hold": plan["grading_period_hold"],
        "retry_writes": False,
        "teacher_accepted": False,
        "is_final": False,
        "publication_allowed": False,
        "score_delivery_verified": False,
        "comment_delivery_verified": False,
        "canvas_writes": 0,
        "sheets_writes": 0,
    }
