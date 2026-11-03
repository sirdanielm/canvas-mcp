"""Pure Unit1 compact-consumer candidate; no grading, catalog I/O or transport.

The owner supplies an independently pinned expected projection and a trusted
adapter to the existing KEY_AUTHORED_FRQ_CUE_INDEX_V1 lookup. Payload flags,
matching numbers and this shape check never establish academic acceptance.
No Unit2 numeric-policy/formatter adapter or runtime action is invoked.
"""

from __future__ import annotations

import copy
import hashlib
import json
import re
from collections.abc import Callable
from dataclasses import dataclass
from fractions import Fraction
from typing import Any

from canvas_mcp.gradebook.comment_policy import _quoted_display, inspect_body

PROFILE = "UNIT1_COMPACT_FEEDBACK_V1_CANDIDATE"
CATEGORY = "UNIT1_FEEDBACK"
PROJECTION = "UNIT1_BOUND_LOSS_PROJECTION_V1"
CATALOG_SCHEMA = "KEY_AUTHORED_FRQ_CUE_INDEX_V1"
CATALOG_CONTRACT_SHA256 = (
    "246a8b6b67fb03b8648b6907959d5cdc20a3c12c86183c7989fc52debec92ff2"
)
BINDING_FIELDS = {
    "unit",
    "form_id",
    "source_sha256",
    "reading_sha256",
    "result_sha256",
    "key_sha256",
    "academic_sha256",
    "policy_sha256",
}
KEY_FIELDS = {"unit", "form_id", "key_sha256", "academic_sha256", "policy_sha256"}
ROLES = {"raw", "percent", "accepted_final", "transport"}
FACT_FIELDS = {
    "fact_id",
    "item_id",
    "part_id",
    "criterion_id",
    "kind",
    "deduction",
    "read_display",
    "key_choice",
    "holds",
    "earned_points",
    "student_unreadable",
}
PAYLOAD_FIELDS = {
    "profile",
    "category",
    "unit",
    "binding",
    "header",
    "projection",
    "loss_facts_ref",
    "catalog_schema",
    "catalog_contract_sha256",
    "catalog_revision_sha256",
    "body",
}
SHA = re.compile(r"[a-f0-9]{64}")
AMOUNT = re.compile(r"[0-9]{1,12}(?:/[0-9]{1,12}|\.[0-9]{1,8})?")
NATIVE_ITEM = re.compile(r"[A-Za-z0-9_.:-]{1,100}")


class Unit1Hold(ValueError):
    """Fixed privacy-safe preparation code; never echo payload values."""


@dataclass(frozen=True)
class ExpectedUnit1:
    """Caller-held current expectations, not a serialized acceptance claim.

    Source authority, actual immutable-byte pins and genuine catalog/review
    custody must be verified by the existing owner before construction. No
    default real Unit1 key, scale, acceptance or weighting is supplied here.
    """

    binding: dict[str, Any]
    header: str
    projection_sha256: str
    loss_facts_ref: dict[str, Any]
    units: dict[str, dict[str, str]]
    representation_units: dict[str, str]
    current_key_authority: dict[str, Any] | None
    catalog_revision_sha256: str | None


def projection_digest(value: Any) -> str:
    """Preserve JSON types, exact rational strings, nulls and native IDs."""
    return hashlib.sha256(
        json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        ).encode()
    ).hexdigest()


def _need(ok: bool, code: str) -> None:
    if not ok:
        raise Unit1Hold(code)


def _text(value: Any, *, limit: int = 200) -> bool:
    return (
        type(value) is str
        and 0 < len(value) <= limit
        and not any(
            ord(c) < 32
            or ord(c) == 127
            or c in "\u2028\u2029"
            or 0xD800 <= ord(c) <= 0xDFFF
            for c in value
        )
    )


def _sha(value: Any) -> bool:
    return type(value) is str and SHA.fullmatch(value) is not None


def _ref(value: Any) -> bool:
    return (
        type(value) is dict
        and set(value) == {"path", "bytes", "sha256"}
        and _text(value["path"], limit=4096)
        and value["path"].startswith("/")
        and type(value["bytes"]) is int
        and 0 < value["bytes"] <= 2_000_000
        and _sha(value["sha256"])
    )


def _number(value: Any, *, positive: bool = False) -> None:
    _need(
        type(value) is str and AMOUNT.fullmatch(value) is not None,
        "EXACT_UNIT1_RATIONAL_STRING_REQUIRED",
    )
    try:
        number = Fraction(value)
    except (ValueError, ZeroDivisionError):
        raise Unit1Hold("EXACT_UNIT1_RATIONAL_STRING_REQUIRED") from None
    _need(
        number > 0 if positive else number >= 0,
        "POSITIVE_UNIT1_LOSS_REQUIRED"
        if positive
        else "NONNEGATIVE_UNIT1_VALUE_REQUIRED",
    )


def _binding(value: Any) -> None:
    _need(
        type(value) is dict and set(value) == BINDING_FIELDS,
        "EXACT_UNIT1_SOURCE_BINDING_REQUIRED",
    )
    _need(value["unit"] == "UNIT1", "CROSS_UNIT_BINDING_REFUSED")
    _need(
        type(value["form_id"]) is str
        and re.fullmatch(r"[A-Za-z0-9_-]{1,40}", value["form_id"]) is not None,
        "EXACT_UNIT1_FORM_REQUIRED",
    )
    _need(
        all(_sha(v) for k, v in value.items() if k.endswith("sha256")),
        "EXACT_UNIT1_SOURCE_BINDING_REQUIRED",
    )


def _cue(
    lookup: Callable[[dict[str, Any], str], dict[str, Any]],
    binding: dict[str, Any],
    revision: str,
) -> tuple[str, dict[str, Any]]:
    # Existing shared lookup verifies index/source/review bytes. The injected
    # adapter must call that exact qualified function; it is not an attestation
    # read from the candidate payload, and this consumer performs no file I/O.
    result = lookup(copy.deepcopy(binding), revision)
    _need(type(result) is dict, "REVIEWED_EXACT_CUE_REQUIRED")
    _need(
        result.get("status") == "FOUND_REVIEWED_KEY_FACTS",
        "MISSING_OR_UNREVIEWED_EXACT_KEY_CUE",
    )
    _need(result.get("binding") == binding, "CUE_NATIVE_OR_KEY_BINDING_CHANGED")
    cue = result.get("cue")
    if type(cue) is not dict:
        raise Unit1Hold("EXACT_SHARED_CUE_REFERENCE_REQUIRED")
    _need(
        set(cue)
        == {
            "text",
            "criterion_id",
            "academic_sha256",
            "policy_sha256",
            "key_sha256",
            "authority_reference",
        },
        "EXACT_SHARED_CUE_REFERENCE_REQUIRED",
    )
    _need(
        all(
            cue[k] == binding[k]
            for k in ("criterion_id", "academic_sha256", "policy_sha256", "key_sha256")
        ),
        "CUE_NATIVE_OR_KEY_BINDING_CHANGED",
    )
    _need(_text(cue["authority_reference"]), "EXACT_SHARED_CUE_REFERENCE_REQUIRED")
    text = cue["text"]
    _need(
        _text(text, limit=20) and text == text.strip(), "KEY_CUE_DISPLAY_BOUND_REQUIRED"
    )
    displayed = _quoted_display(text)[1:-1]
    _need(len(displayed) <= 20, "KEY_CUE_DISPLAY_BOUND_REQUIRED")
    _need(_ref(result.get("review_ref")), "KEY_CUE_REVIEW_REF_REQUIRED")
    permissions = result.get("permissions")
    _need(
        type(permissions) is dict
        and set(permissions)
        == {
            "grading",
            "score_change",
            "acceptance",
            "publication",
        }
        and all(value is False for value in permissions.values())
        and result.get("key_pdf_bytes_verified") is False,
        "CATALOG_LOOKUP_CANNOT_CREATE_AUTHORITY",
    )
    return displayed, copy.deepcopy(result["review_ref"])


def _qualify(
    candidate: dict[str, Any],
    expected: ExpectedUnit1,
    lookup_cue: Callable[[dict[str, Any], str], dict[str, Any]],
) -> dict[str, Any]:
    _need(
        type(candidate) is dict and set(candidate) == PAYLOAD_FIELDS,
        "EXACT_UNIT1_COMPACT_PAYLOAD_REQUIRED",
    )
    _need(
        candidate["profile"] == PROFILE
        and candidate["category"] == CATEGORY
        and candidate["unit"] == "UNIT1",
        "EXPLICIT_UNIT1_PROFILE_CATEGORY_REQUIRED",
    )
    _binding(candidate["binding"])
    _binding(expected.binding)
    _need(
        candidate["binding"] == expected.binding,
        "CURRENT_SOURCE_OR_KEY_REVISION_CHANGED",
    )
    _need(
        _text(expected.header) and candidate["header"] == expected.header,
        "CURRENT_UNIT1_IDENTITY_HEADER_REQUIRED",
    )
    _need(
        expected.header.rsplit(" | ", 1)[-1] == expected.binding["form_id"],
        "CURRENT_UNIT1_FORM_HEADER_CHANGED",
    )
    _need(
        _ref(candidate["loss_facts_ref"])
        and _ref(expected.loss_facts_ref)
        and candidate["loss_facts_ref"] == expected.loss_facts_ref,
        "CURRENT_UNIT1_LOSS_FACTS_REF_REQUIRED",
    )
    key_authority = expected.current_key_authority
    _need(
        type(key_authority) is dict
        and set(key_authority) == KEY_FIELDS
        and key_authority == {k: expected.binding[k] for k in KEY_FIELDS},
        "CURRENT_UNIT1_KEY_AUTHORITY_NOT_QUALIFIED",
    )
    _need(
        candidate["catalog_schema"] == CATALOG_SCHEMA
        and candidate["catalog_contract_sha256"] == CATALOG_CONTRACT_SHA256,
        "SHARED_KEY_REFERENCE_CONTRACT_REQUIRED",
    )
    revision = expected.catalog_revision_sha256
    if type(revision) is not str or not _sha(revision):
        raise Unit1Hold("CURRENT_CATALOG_REVISION_REQUIRED")
    _need(
        candidate["catalog_revision_sha256"] == revision,
        "CURRENT_CATALOG_REVISION_REQUIRED",
    )
    _need(
        type(expected.units) is dict and bool(expected.units),
        "UNIT1_UNIT_REGISTRY_REQUIRED",
    )
    for unit_id, unit in expected.units.items():
        _need(
            _text(unit_id)
            and type(unit) is dict
            and set(unit) == {"unit", "unit_id", "dimension"}
            and unit["unit"] == "UNIT1"
            and unit["unit_id"] == unit_id
            and _text(unit["dimension"]),
            "CROSS_UNIT_OR_UNTYPED_UNITS_REFUSED",
        )
    projection = candidate["projection"]
    _need(
        type(projection) is dict
        and set(projection)
        == {
            "schema",
            "display_map",
            "representations",
            "facts",
            "holds",
        }
        and projection["schema"] == PROJECTION,
        "UNIT1_TYPED_LOSS_PROJECTION_REQUIRED",
    )
    try:
        actual_projection_sha = projection_digest(projection)
    except (TypeError, ValueError, UnicodeError):
        raise Unit1Hold("UNIT1_TYPED_LOSS_PROJECTION_REQUIRED") from None
    _need(
        _sha(expected.projection_sha256)
        and actual_projection_sha == expected.projection_sha256,
        "APPROVED_UNIT1_TYPED_PROJECTION_CHANGED",
    )
    _need(
        type(projection["holds"]) is list
        and all(_text(h) for h in projection["holds"]),
        "LITERAL_HOLD_STATE_REQUIRED",
    )
    representations = projection["representations"]
    _need(
        type(representations) is dict
        and set(representations) == ROLES
        and type(expected.representation_units) is dict
        and set(expected.representation_units) == ROLES,
        "FOUR_SCORE_REPRESENTATIONS_REQUIRED",
    )
    for role, value in representations.items():
        _need(
            type(value) is dict
            and set(value) == {"value", "unit_id"}
            and type(value["unit_id"]) is str
            and value["unit_id"] in expected.units
            and value["unit_id"] == expected.representation_units[role],
            "UNIT1_REPRESENTATION_UNITS_CHANGED",
        )
        if value["value"] is not None:
            _number(value["value"])
    mapping = projection["display_map"]
    _need(
        type(mapping) is list and 0 < len(mapping) <= 200,
        "EXPLICIT_NATIVE_TO_DISPLAY_MAP_REQUIRED",
    )
    native: dict[str, dict[str, Any]] = {}
    displayed: set[tuple[str, int]] = set()
    for row in mapping:
        _need(
            type(row) is dict and set(row) == {"item_id", "kind", "display_number"},
            "EXPLICIT_NATIVE_TO_DISPLAY_MAP_REQUIRED",
        )
        item = row["item_id"]
        _need(
            type(item) is str and NATIVE_ITEM.fullmatch(item) is not None,
            "OPAQUE_UNIT1_NATIVE_ITEM_REQUIRED",
        )
        _need(
            type(row["kind"]) is str
            and row["kind"] in {"MC", "FRQ"}
            and type(row["display_number"]) is int
            and 1 <= row["display_number"] <= 100,
            "EXPLICIT_DISPLAY_NUMBER_1_TO_100_REQUIRED",
        )
        axis = (row["kind"], row["display_number"])
        _need(
            item not in native and axis not in displayed, "AMBIGUOUS_NATIVE_DISPLAY_MAP"
        )
        native[item] = row
        displayed.add(axis)
    facts = projection["facts"]
    _need(
        type(facts) is list and len(facts) <= 200,
        "UNIT1_TYPED_LOSS_PROJECTION_REQUIRED",
    )
    lines = [expected.header]
    seen: set[str] = set()
    fact_ids: set[str] = set()
    reviews = []
    for fact in facts:
        _need(
            type(fact) is dict and set(fact) == FACT_FIELDS,
            "UNIT1_TYPED_LOSS_FACT_REQUIRED",
        )
        _need(
            _text(fact["fact_id"]) and fact["fact_id"] not in fact_ids,
            "UNIQUE_NATIVE_LOSS_FACT_REQUIRED",
        )
        fact_ids.add(fact["fact_id"])
        item = fact["item_id"]
        _need(type(item) is str and item in native, "UNMAPPED_NATIVE_UNIT1_ITEM")
        row = native[item]
        _need(
            type(fact["holds"]) is list
            and all(_text(h) for h in fact["holds"])
            and type(fact["student_unreadable"]) is bool,
            "LITERAL_HOLD_STATE_REQUIRED",
        )
        _need(
            type(fact["kind"]) is str and fact["kind"] in {"DEDUCTION", "HELD"},
            "EXPLICIT_UNIT1_FACT_KIND_REQUIRED",
        )
        if fact["earned_points"] is not None:
            _number(fact["earned_points"])
        if row["kind"] == "MC":
            _need(
                fact["part_id"] is None and fact["criterion_id"] is None,
                "MC_NATIVE_TYPE_MISMATCH",
            )
            label = f"MC{row['display_number']}"
        else:
            _need(
                type(fact["part_id"]) is str
                and re.fullmatch(r"[A-Za-z]{1,20}", fact["part_id"]) is not None
                and _text(fact["criterion_id"])
                and fact["key_choice"] is None,
                "FRQ_NATIVE_TYPE_MISMATCH",
            )
            label = f"FRQ{row['display_number']}{fact['part_id']}"
        if fact["kind"] == "HELD":
            _need(
                fact["deduction"] is None
                and fact["earned_points"] is None
                and bool(fact["holds"]),
                "HELD_NULL_AWARD_AND_DEDUCTION_REQUIRED",
            )
            if not fact["student_unreadable"]:
                continue  # Private criterion/source holds are retained verbatim.
            _need(
                fact["read_display"] == "unreadable",
                "LITERAL_UNREADABLE_STATUS_REQUIRED",
            )
            line = f"{label}: read-unreadable | held"
        else:
            loss = fact["deduction"]
            _need(
                type(loss) is dict
                and set(loss) == {"amount", "unit_id"}
                and type(loss["unit_id"]) is str
                and loss["unit_id"] in expected.units,
                "EXPLICIT_UNIT1_DEDUCTION_UNITS_REQUIRED",
            )
            _number(loss["amount"], positive=True)
            _need(
                fact["student_unreadable"] is False,
                "UNREADABLE_FACT_CANNOT_BECOME_DEDUCTION",
            )
            read = fact["read_display"]
            _need(type(read) is str, "LITERAL_READ_DISPLAY_REQUIRED")
            if row["kind"] == "MC":
                _need(
                    read in {"A", "B", "C", "D", "blank"}
                    and type(fact["key_choice"]) is str
                    and fact["key_choice"] in {"A", "B", "C", "D"}
                    and read != fact["key_choice"],
                    "MC_NATIVE_TYPE_MISMATCH",
                )
                cue = fact["key_choice"]
            else:
                binding = {k: expected.binding[k] for k in KEY_FIELDS}
                binding.update(
                    item_id=item,
                    part_id=fact["part_id"],
                    criterion_id=fact["criterion_id"],
                )
                cue, review = _cue(lookup_cue, binding, revision)
                reviews.append(review)
            line = f"{label}: read-{read} | key-{cue} | -{loss['amount']}"
        _need(label not in seen, "MULTI_CRITERION_PART_DISPLAY_PROFILE_REQUIRED")
        seen.add(label)
        lines.append(line)
    body = candidate["body"]
    _need(
        type(body) is str and body == "\n".join(lines),
        "EXACT_UNIT1_BOUND_ROWS_REQUIRED",
    )
    _need(
        not inspect_body(body, expected_header=expected.header),
        "COMMON_COMPACT_DISPLAY_REQUIRED",
    )
    return {
        "status": "QUALIFIED_SOURCE_ONLY",
        "profile": PROFILE,
        "category": CATEGORY,
        "unit": "UNIT1",
        "body_sha256": hashlib.sha256(body.encode()).hexdigest(),
        "projection_sha256": expected.projection_sha256,
        "catalog_schema": CATALOG_SCHEMA,
        "cue_review_refs": reviews,
        "native_identifiers_and_rational_strings_preserved": True,
        "score_representations_recomputed": False,
        "permissions": _permissions(),
        "academic_acceptance": "NOT_ESTABLISHED_BY_THIS_CONSUMER",
        "transport": "IN_PLACE_ONLY_WHERE_SUPPORTED_SEPARATE_GATES_REQUIRED",
    }


def _permissions() -> dict[str, bool]:
    return dict.fromkeys(
        [
            "grading",
            "score_change",
            "acceptance",
            "staging",
            "preview",
            "publication",
        ],
        False,
    )


def qualify_unit1_compact(
    candidate: dict[str, Any],
    *,
    expected: ExpectedUnit1,
    lookup_cue: Callable[[dict[str, Any], str], dict[str, Any]],
) -> dict[str, Any]:
    """Qualify supplied text/facts only; preserve programming errors as errors.

    The injected resolver uses the pinned shared catalog's lookupCue API through
    an owner-qualified language seam. REVIEW_REQUIRED remains HOLD; this module
    never opens files, calls Node, invents cues or authenticates the caller.
    """
    try:
        return _qualify(candidate, expected, lookup_cue)
    except Unit1Hold as exc:
        return {"status": "HOLD", "code": str(exc), "permissions": _permissions()}
