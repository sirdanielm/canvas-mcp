"""Source-only enforcement candidate for the EXISTING Unit2 compact format.

No renderer, grading, I/O, transport, approval, or mutation. The grammar follows
the frozen UNIT2_COMPACT_FEEDBACK_V6 contract. Passing shape validation cannot
establish correct awards, source identity, independent QC, or authorization.
"""

from __future__ import annotations

import hashlib
import json
import re
from fractions import Fraction
from typing import Any, cast

CONTRACT_ID = "UNIT2_COMPACT_FEEDBACK_V6"
FORMAT_CONTRACT_SHA256 = (
    "31547879354c78bb76da56662e74def24568d5c8e04c4bd8e5afe0f6f325511f"
)
NUMERIC_POLICY_SHA256 = (
    "2c0b5f8639bc89532390b949f6686ce599a36a895a5b6efa55b9bf171932ec47"
)
POINTS = r"[0-9]{1,12}(?:/[0-9]{1,12}|\.[0-9]{1,8})?"
ITEM = r"(?:[1-9][0-9]?|100)"
JS_WHITESPACE = "\t\n\v\f\r \u00a0\u1680\u2000\u2001\u2002\u2003\u2004\u2005\u2006\u2007\u2008\u2009\u200a\u2028\u2029\u202f\u205f\u3000\ufeff"
MC = re.compile(
    r"(MC(" + ITEM + r")): read-([A-D]|blank) \| key-([A-D]) \| -(" + POINTS + r")"
)
FRQ = re.compile(
    r"(FRQ(" + ITEM + r")[a-zA-Z]{1,20}): read-(.+) \| key-(.+) \| -(" + POINTS + r")"
)
HELD = re.compile(
    r"((?:MC" + ITEM + r"|FRQ" + ITEM + r"[a-zA-Z]{1,20})): read-unreadable \| held"
)


class CommentContractError(ValueError):
    """Privacy-safe fixed failure codes; never echo a student body."""


def _plain_decode(text: str) -> str:
    """Decode the existing formatter's JSON-escaped unquoted display."""
    # A successful decode of this explicitly quoted JSON value is a string.
    return cast(str, json.loads('"' + text + '"'))


def _quoted_display(text: str) -> str:
    # Validate the existing V6 JSON display; do not normalize the given body.
    encoded = json.dumps(text, ensure_ascii=False)
    encoded = "".join(
        f"\\u{ord(c):04x}" if 0xD800 <= ord(c) <= 0xDFFF else c for c in encoded
    )
    return (
        encoded.replace("|", "\\u007c")
        .replace("\u2028", "\\u2028")
        .replace("\u2029", "\\u2029")
    )


def _valid_read(text: str) -> bool:
    if text in {
        "blank",
        "not-recorded",
        "unreadable",
        "missing",
        "ambiguous",
        "unclear",
        "partial",
    }:
        return True
    try:
        if text.startswith('"'):
            literal, end = json.JSONDecoder().raw_decode(text)
            if not isinstance(literal, str) or text[end:] not in {"", "…"}:
                return False
            if text[:end] != _quoted_display(literal):
                return False
        else:
            # V6 keeps part.observation in private audit only. Student text
            # uses a quoted literal, semantic status, or fixed not-recorded.
            return False
        return (
            bool(literal.strip(JS_WHITESPACE))
            and len(literal) <= 60
            and len(re.findall("[^" + JS_WHITESPACE + "]+", literal)) <= 8
        )
    except (json.JSONDecodeError, TypeError):
        return False


def inspect_body(
    body: str, *, expected_header: str | None = None
) -> list[dict[str, int | str | None]]:
    issues: list[dict[str, int | str | None]] = []
    if (
        not isinstance(body, str)
        or not body
        or body != body.strip()
        or "\r" in body
        or len(body) > 6000
    ):
        return [{"line": None, "code": "EXACT_NORMALIZED_BODY_REQUIRED"}]
    lines = body.split("\n")
    if not re.fullmatch(
        r"[0-9]{4} \| [^|\x00-\x1f\x7f\u2028\u2029]{1,80} \| [A-Za-z0-9_-]{1,40}",
        lines[0],
    ):
        issues.append({"line": 1, "code": "EXACT_PIN_SECTION_FORM_HEADER_REQUIRED"})
    if expected_header is not None and lines[0] != expected_header:
        issues.append({"line": 1, "code": "RECIPIENT_FORM_HEADER_BINDING_CHANGED"})
    seen = set()
    for number, line in enumerate(lines[1:], 2):
        held, mc, frq = HELD.fullmatch(line), MC.fullmatch(line), FRQ.fullmatch(line)
        if not (held or mc or frq):
            issues.append(
                {
                    "line": number,
                    "code": "EXACT_COMPACT_DEDUCTION_OR_UNREADABLE_HOLD_ROW_REQUIRED",
                }
            )
            continue
        row = held or mc or frq
        assert row is not None  # The no-match branch already continued.
        label = row[1]
        if label in seen:
            issues.append({"line": number, "code": "DUPLICATE_ITEM_PART_DISPLAY"})
        seen.add(label)
        if held:
            continue
        if mc is not None:
            points = mc[5]
        else:
            assert frq is not None  # Matched held rows already continued.
            points = frq[5]
        try:
            if Fraction(points) <= 0:
                raise ValueError
        except (ValueError, ZeroDivisionError):
            issues.append({"line": number, "code": "POSITIVE_EXACT_DEDUCTION_REQUIRED"})
        if mc and mc[3] == mc[4]:
            issues.append(
                {"line": number, "code": "MATCHED_MC_CHOICE_CANNOT_DISPLAY_DEDUCTION"}
            )
        if frq:
            read, cue = frq[3], frq[4]
            if not _valid_read(read):
                issues.append(
                    {
                        "line": number,
                        "code": "BOUND_LITERAL_OR_OBSERVATION_EXCERPT_REQUIRED",
                    }
                )
            try:
                decoded = _plain_decode(cue)
                if (
                    not decoded
                    or decoded != decoded.strip(JS_WHITESPACE)
                    or len(decoded) > 20
                    or len(cue) > 20
                    or any(
                        ord(c) <= 31
                        or ord(c) == 127
                        or c in "\u2028\u2029"
                        or 0xD800 <= ord(c) <= 0xDFFF
                        for c in decoded
                    )
                    or cue != _quoted_display(decoded)[1:-1]
                ):
                    raise ValueError
            except (ValueError, json.JSONDecodeError):
                issues.append(
                    {"line": number, "code": "VALID_FRQ_KEY_CUE_MAX20_REQUIRED"}
                )
    return issues


def require_bound_formatter(
    body: str, formatter: dict[str, Any], *, expected_source_binding: dict[str, Any]
) -> dict[str, Any]:
    """This check supplements the existing pinned formatter, never replaces it.

    Callers must verify file/code/contract/QC refs independently. No attestation
    flag from a draft or model response grants authority through this function.
    """
    if formatter.get("source_version") != CONTRACT_ID:
        raise CommentContractError("BOUND_V6_FORMATTER_REQUIRED")
    if formatter.get("source_binding") != expected_source_binding:
        raise CommentContractError("SOURCE_READING_RESULT_POLICY_BINDING_CHANGED")
    if expected_source_binding.get("policy_sha256") != NUMERIC_POLICY_SHA256:
        raise CommentContractError("CURRENT_NUMERIC_POLICY_BINDING_REQUIRED")
    if formatter.get("compact_text") != body or formatter.get(
        "compact_lines"
    ) != body.split("\n"):
        raise CommentContractError("EXACT_CANONICAL_FORMATTER_BODY_REQUIRED")
    issues = inspect_body(body, expected_header=formatter.get("identity_row"))
    if issues:
        raise CommentContractError(issues[0]["code"])
    if formatter.get("whole_final_numeric") is not None:
        raise CommentContractError("FORMATTER_CANNOT_CREATE_WHOLE_GRADE")
    if any(
        formatter.get(k) is not False
        for k in [
            "publication_allowed",
            "staging_allowed",
            "canvas_write_allowed",
            "automatic_grading_allowed",
            "teacher_acceptance_allowed",
            "teacher_decision_created",
        ]
    ):
        raise CommentContractError("FORMATTER_CANNOT_GRANT_OPERATION_OR_ACCEPTANCE")
    return {
        "contract_id": CONTRACT_ID,
        "format_contract_sha256": FORMAT_CONTRACT_SHA256,
        "body_sha256": hashlib.sha256(body.encode()).hexdigest(),
        "shape_and_formatter_binding": "PASS",
        "academic_correctness": "NOT_ESTABLISHED_BY_THIS_CHECK",
        "teacher_acceptance": False,
        "publication_authority": False,
    }


# Explicit opt-in consumer seam. Existing V6 callers above retain their exact
# grammar and source binding. This function registers no tool or transport.
V7_CONTRACT_ID = "UNIT2_COMPACT_FEEDBACK_V7"
V7_FORMATTER_SHA256 = "2be2dfdf14c7bb1a39a4247971fc003cea01149351378440b9e056805989e881"
V7_FORMAT_CONTRACT_SHA256 = (
    "c9aaf424a7648f8ec7034e57e88b442c8f9bcad18711d539920bfcdb5a40811f"
)
V7_NATIVE_ADAPTER_SHA256 = (
    "64445a0645e2cbcc4e031371abc77ef7feded44df100e2f58dd62d7f95c06d81"
)
V7_KNOWN = re.compile(
    r"(FRQ("
    + ITEM
    + r")[a-zA-Z]{1,20}): read-(.+) \| key-(.+) \| known -("
    + POINTS
    + r")"
)


def _v7_require(condition: bool, code: str) -> None:
    if not condition:
        raise CommentContractError(code)


def _v7_equal(left: Any, right: Any) -> bool:
    """Compare JSON types too: Python's True must not equal a numeric award."""
    return json.dumps(left, sort_keys=True, allow_nan=False) == json.dumps(
        right, sort_keys=True, allow_nan=False
    )


def _v7_points(value: Any) -> Fraction:
    _v7_require(
        isinstance(value, str) and re.fullmatch(POINTS, value) is not None,
        "V7_NATIVE_EXACT_POINTS_REQUIRED",
    )
    try:
        return Fraction(value)
    except (ValueError, ZeroDivisionError) as exc:
        raise CommentContractError("V7_NATIVE_EXACT_POINTS_REQUIRED") from exc


def _v7_rational(value: Fraction) -> str:
    return (
        str(value.numerator)
        if value.denominator == 1
        else f"{value.numerator}/{value.denominator}"
    )


def _v7_display_points(value: Fraction) -> str:
    denominator, twos, fives = value.denominator, 0, 0
    while denominator % 2 == 0:
        denominator //= 2
        twos += 1
    while denominator % 5 == 0:
        denominator //= 5
        fives += 1
    places = max(twos, fives)
    if denominator != 1 or places > 8 or places == 0:
        return _v7_rational(value)
    scaled = value.numerator * 2 ** (places - twos) * 5 ** (places - fives)
    digits = str(scaled).zfill(places + 1)
    return (digits[:-places] + "." + digits[-places:]).rstrip("0").rstrip(".")


def _v7_read(part: dict[str, Any]) -> str:
    """Check the pinned excerpt rule, without changing any source/audit text."""
    literal = part.get("literal_text")
    if isinstance(literal, str) and literal.strip(JS_WHITESPACE):
        rest = literal.lstrip(JS_WHITESPACE)
        words = list(re.finditer("[^" + JS_WHITESPACE + "]+", rest))
        end = words[7].end() if len(words) > 8 else len(rest)
        bounded = rest[:end][:60].rstrip(JS_WHITESPACE)
        truncated = bool(rest[len(bounded) :].strip(JS_WHITESPACE))
        return _quoted_display(bounded) + ("…" if truncated else "")
    return (
        "not-recorded"
        if part["read_status"] == "READABLE"
        else str(part["read_status"]).lower()
    )


def _v7_known_losses(
    parts: list[dict[str, Any]], binding: dict[str, Any]
) -> list[dict[str, Any]]:
    """Recheck only existing native awards; never fill a null or award points."""
    losses: list[dict[str, Any]] = []
    part_ids: set[tuple[int, str]] = set()
    criterion_ids: set[str] = set()
    for part in parts:
        question, part_id = part["question"], part["part_id"]
        _v7_require(
            type(question) is int
            and 1 <= question <= 100
            and isinstance(part_id, str)
            and re.fullmatch(r"[A-Za-z]{1,20}", part_id) is not None
            and part["read_status"]
            in {
                "READABLE",
                "BLANK",
                "UNREADABLE",
                "MISSING",
                "AMBIGUOUS",
                "UNCLEAR",
                "PARTIAL",
            }
            and (question, part_id) not in part_ids,
            "V7_REAL_UNIQUE_PART_REQUIRED",
        )
        part_ids.add((question, part_id))
        parent_earned = part["earned_points"]
        if parent_earned is not None:
            _v7_points(parent_earned)
        source = part.get("source_binding")
        if not isinstance(source, dict) or "native_criteria" not in source:
            continue  # Legacy non-native holds supply no known-loss proof.
        criteria = source["native_criteria"]
        if not isinstance(criteria, list):
            raise CommentContractError("V7_NATIVE_CRITERIA_REQUIRED")
        native_unresolved: list[str] = []
        for criterion in criteria:
            cid = criterion["criterion_id"]
            _v7_require(
                isinstance(cid, str) and bool(cid) and cid not in criterion_ids,
                "V7_UNIQUE_ORIGINAL_CRITERION_REQUIRED",
            )
            criterion_ids.add(cid)
            if criterion["earned_points"] is None:
                native_unresolved.append(cid)
        # Derived display omissions cannot hide a native hold or turn its null
        # parent into a numeric/bool value. Check this before the resolved skip.
        _v7_require(
            _v7_equal(native_unresolved, source.get("unresolved_criterion_ids", []))
            and (parent_earned is None) == bool(native_unresolved),
            "V7_NATIVE_PARENT_NULL_RELATIONSHIP_REQUIRED",
        )
        if parent_earned is not None:
            continue
        binding_keys = (
            "packet_id",
            "source_sha256",
            "reading_key",
            "result_key",
            "form_id",
            "attempt",
            "academic_sha256",
            "policy_sha256",
            "key_sha256",
        )
        _v7_require(
            bool(criteria)
            and all(
                binding.get(k) is not None and source.get(k) == binding[k]
                for k in binding_keys
            )
            and source.get("item_id") == f"FRQ{question:02d}"
            and source.get("part_id") == part_id,
            "V7_KNOWN_SOURCE_BINDING_CHANGED",
        )
        unresolved: list[str] = []
        known, maxima = Fraction(0), Fraction(0)
        for criterion in criteria:
            _v7_require(
                criterion["part_id"] == part_id
                and criterion["component"] in {"ATTEMPT", "MASTERY"},
                "V7_NATIVE_CRITERION_SCOPE_CHANGED",
            )
            maximum = _v7_points(criterion["maximum_points"])
            _v7_require(maximum > 0, "V7_NATIVE_EXACT_POINTS_REQUIRED")
            maxima += maximum
            if criterion["earned_points"] is None:
                unresolved.append(criterion["criterion_id"])
                continue
            earned = _v7_points(criterion["earned_points"])
            _v7_require(earned <= maximum, "V7_NATIVE_EXACT_POINTS_REQUIRED")
            known += earned
            if criterion["component"] != "MASTERY" or earned == maximum:
                continue
            losses.append(
                {
                    "criterion_id": criterion["criterion_id"],
                    "question": question,
                    "part_id": part_id,
                    "component": "MASTERY",
                    "maximum_points": criterion["maximum_points"],
                    "earned_points": criterion["earned_points"],
                    "deduction": _v7_rational(maximum - earned),
                    "source_binding": source,
                }
            )
        _v7_require(
            bool(unresolved)
            and _v7_equal(unresolved, source["unresolved_criterion_ids"])
            and known == _v7_points(source["known_criterion_points"])
            and maxima == _v7_points(part["possible_points"]),
            "V7_PARENT_MUST_REMAIN_GENUINELY_UNRESOLVED",
        )
    return losses


def _v7_check_known_rows(formatter: dict[str, Any]) -> tuple[list[str], set[str]]:
    parts, binding = formatter["frq_parts"], formatter["source_binding"]
    _v7_require(isinstance(parts, list) and len(parts) <= 128, "V7_PARTS_REQUIRED")
    losses = _v7_known_losses(parts, binding)
    _v7_require(
        not losses or binding["form_id"] == formatter["form"],
        "V7_KNOWN_FORM_BINDING_CHANGED",
    )
    _v7_require(
        _v7_equal(formatter["known_criterion_losses"], losses),
        "V7_COMPLETE_NATIVE_KNOWN_LOSS_MANIFEST_REQUIRED",
    )
    cues = formatter["student_criterion_key_cues"]
    _v7_require(
        isinstance(cues, dict) and set(cues) == {row["criterion_id"] for row in losses},
        "V7_EXACT_CRITERION_CUE_SET_REQUIRED",
    )
    display, lines, labels = [], [], set()
    for row in losses:
        part = next(
            p
            for p in parts
            if p["question"] == row["question"] and p["part_id"] == row["part_id"]
        )
        cue = cues[row["criterion_id"]]
        _v7_require(
            isinstance(cue, dict)
            and set(cue)
            == {
                "text",
                "criterion_id",
                "academic_sha256",
                "policy_sha256",
                "key_sha256",
                "authority_reference",
            }
            and cue["criterion_id"] == row["criterion_id"]
            and all(
                isinstance(binding.get(k), str)
                and re.fullmatch(r"[0-9a-f]{64}", binding[k]) is not None
                and cue[k] == binding[k]
                for k in ("academic_sha256", "policy_sha256", "key_sha256")
            )
            and isinstance(cue["authority_reference"], str)
            and re.fullmatch(
                r"academic:/forms/[0-9]+/questions/[0-9]+/parts/[0-9]+/expected_answer",
                cue["authority_reference"],
            )
            is not None
            and isinstance(cue["text"], str),
            "V7_BOUND_CRITERION_CUE_REQUIRED",
        )
        label = f"FRQ{row['question']}{row['part_id']}"
        line = (
            f"{label}: read-{_v7_read(part)} | key-{_quoted_display(cue['text'])[1:-1]}"
            f" | known -{_v7_display_points(Fraction(row['deduction']))}"
        )
        # Reuse the exact V6 read/cue/ASCII label and positive-point grammar on
        # one row at a time. Only the typed V7 scope permits repeated labels.
        ordinary = line.replace(" | known -", " | -")
        _v7_require(
            not inspect_body(formatter["identity_row"] + "\n" + ordinary),
            "V7_KNOWN_ROW_LITERAL_CUE_OR_POINTS_INVALID",
        )
        display.append(
            {
                **row,
                "display_kind": "KNOWN_MASTERY_CRITERION_LOSS",
                "parent_earned_points": None,
                "compact_line": line,
            }
        )
        lines.append(line)
        labels.add(label)
        teacher = f"{label}: read-{part['read_status'].lower()} | held"
        pending = [
            d
            for d in formatter["frq_display"]
            if d["question"] == row["question"] and d["part_id"] == row["part_id"]
        ]
        _v7_require(
            len(pending) == 1
            and pending[0]["deduction"] == "PENDING"
            and pending[0]["compact_line"] == teacher
            and formatter["teacher_review_lines"].count(teacher) == 1,
            "V7_PARENT_HOLD_MUST_REMAIN_IN_TEACHER_REVIEW",
        )
        held = f"{label}: read-unreadable | held"
        _v7_require(
            formatter["compact_lines"].count(held)
            == (1 if part["read_status"] == "UNREADABLE" else 0),
            "V7_SOURCE_UNREADABLE_NOTICE_CHANGED",
        )
    _v7_require(
        _v7_equal(formatter["known_criterion_display"], display),
        "V7_EXACT_TYPED_KNOWN_DISPLAY_REQUIRED",
    )
    return lines, labels


def require_bound_v7_formatter(
    body: str,
    formatter: dict[str, Any],
    *,
    expected_source_binding: dict[str, Any],
    formatter_source: bytes,
    format_contract: bytes,
    native_adapter_source: bytes,
) -> dict[str, Any]:
    """Explicit V7 shape/binding check; no transport registration or authority.

    Supply actual independently obtained code/contract bytes, never version
    labels alone. Owners must separately verify native input, exact academic
    authority/cues, QC, current target/body/state, approval and transport wiring.
    This checks existing typed awards for consistency; it neither grades nor
    changes a parent total, null, hold, proposal, source or formatter object.
    """
    _v7_require(
        isinstance(body, str)
        and isinstance(formatter, dict)
        and isinstance(expected_source_binding, dict),
        "V7_TYPED_FORMATTER_OUTPUT_REQUIRED",
    )
    for content, expected in (
        (formatter_source, V7_FORMATTER_SHA256),
        (format_contract, V7_FORMAT_CONTRACT_SHA256),
        (native_adapter_source, V7_NATIVE_ADAPTER_SHA256),
    ):
        _v7_require(
            isinstance(content, bytes)
            and hashlib.sha256(content).hexdigest() == expected,
            "V7_EXACT_SOURCE_CONTRACT_ADAPTER_BYTES_REQUIRED",
        )
    _v7_require(
        formatter.get("source_version") == V7_CONTRACT_ID,
        "BOUND_EXPLICIT_V7_FORMATTER_REQUIRED",
    )
    _v7_require(
        _v7_equal(formatter.get("source_binding"), expected_source_binding),
        "SOURCE_READING_RESULT_POLICY_BINDING_CHANGED",
    )
    _v7_require(
        expected_source_binding.get("policy_sha256") == NUMERIC_POLICY_SHA256,
        "CURRENT_NUMERIC_POLICY_BINDING_REQUIRED",
    )
    _v7_require(
        formatter.get("compact_text") == body
        and formatter.get("compact_lines") == body.split("\n"),
        "EXACT_CANONICAL_FORMATTER_BODY_REQUIRED",
    )
    _v7_require(
        "whole_final_numeric" in formatter
        and formatter["whole_final_numeric"] is None
        and formatter.get("whole_final_disposition") == "UNCHANGED"
        and formatter.get("provisional") is True
        and formatter.get("category_gate") == "CLOSED"
        and formatter.get("component_possible") == "50"
        and all(
            formatter.get(k) is False
            for k in (
                "publication_allowed",
                "staging_allowed",
                "canvas_write_allowed",
                "automatic_grading_allowed",
                "teacher_acceptance_allowed",
                "teacher_decision_created",
            )
        ),
        "FORMATTER_CANNOT_GRANT_OPERATION_OR_ACCEPTANCE",
    )
    try:
        known_lines, known_labels = _v7_check_known_rows(formatter)
        ordinary, known, held = [], [], []
        phase = 0
        for line in body.split("\n")[1:]:
            if V7_KNOWN.fullmatch(line):
                _v7_require(phase <= 1, "V7_CANONICAL_ROW_ORDER_REQUIRED")
                phase = 1
                known.append(line)
            elif HELD.fullmatch(line):
                phase = 2
                held.append(line)
            else:
                _v7_require(phase == 0, "V7_CANONICAL_ROW_ORDER_REQUIRED")
                _v7_require(
                    line.split(":", 1)[0] not in known_labels,
                    "V7_RESOLVED_PARENT_CHILD_DOUBLE_COUNT",
                )
                ordinary.append(line)
        _v7_require(known == known_lines, "V7_EXACT_KNOWN_BODY_ROWS_REQUIRED")
        base = "\n".join([body.split("\n")[0], *ordinary, *held])
        issues = inspect_body(base, expected_header=formatter["identity_row"])
        _v7_require(
            not issues and len(body) <= 6000, "V7_BASE_COMPACT_GRAMMAR_REQUIRED"
        )
        for key, count in (
            ("known_criterion_loss_row_count", len(known)),
            ("resolved_item_part_deduction_row_count", len(ordinary)),
            ("deduction_row_count", len(ordinary) + len(known)),
            ("student_hold_row_count", len(held)),
            ("teacher_review_row_count", len(formatter["teacher_review_lines"]) - 1),
        ):
            _v7_require(
                type(formatter[key]) is int and formatter[key] == count,
                "V7_EXACT_ROW_COUNTS_REQUIRED",
            )
        _v7_require(
            formatter["feedback_required"] is bool(ordinary or known or held)
            and formatter["teacher_review_required"]
            is (len(formatter["teacher_review_lines"]) > 1)
            and formatter["teacher_review_lines"][0] == formatter["identity_row"]
            and formatter["teacher_review_text"]
            == "\n".join(formatter["teacher_review_lines"]),
            "V7_FEEDBACK_AND_TEACHER_REVIEW_BINDING_CHANGED",
        )
    except (KeyError, TypeError, ValueError, StopIteration, AttributeError) as exc:
        if isinstance(exc, CommentContractError):
            raise
        raise CommentContractError("V7_TYPED_FORMATTER_OUTPUT_REQUIRED") from exc
    return {
        "contract_id": V7_CONTRACT_ID,
        "format_contract_sha256": V7_FORMAT_CONTRACT_SHA256,
        "formatter_source_sha256": V7_FORMATTER_SHA256,
        "native_adapter_sha256": V7_NATIVE_ADAPTER_SHA256,
        "body_sha256": hashlib.sha256(body.encode()).hexdigest(),
        "shape_and_formatter_binding": "PASS",
        "academic_correctness": "NOT_ESTABLISHED_BY_THIS_CHECK",
        "teacher_acceptance": False,
        "publication_authority": False,
        "transport_adoption": False,
    }
