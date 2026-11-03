"""Original manual-partial owner source checks; no transport or native writes.

The document adapter uses the original custodian's exact manifest slots.
Matching source hashes never supply destination or execution authority.
"""

from __future__ import annotations

import copy
import hashlib
import inspect
import json
import os
import re
import stat
import types
from collections.abc import Callable
from fractions import Fraction
from pathlib import Path
from typing import Any, cast

from .unit2_manual_partial_projection import prepare_partial_projection
from .unit2_note_draft import (
    MANUAL_PARTIAL_CONTRACT,
    MANUAL_PARTIAL_SOURCE,
    prepare_note_draft,
    validate_manual_partial_candidate,
)


class ManualSourceError(ValueError):
    """A precise source hold; never an inferred zero or admission."""


def need(value: object, code: str) -> None:
    if not value:
        raise ManualSourceError(code)


def reference(value: dict[str, Any]) -> dict[str, Any]:
    """Freeze the exact locator/length/digest before any file access."""
    frozen = copy.deepcopy(value)
    need(
        type(frozen) is dict
        and set(frozen) == {"path", "bytes", "sha256"}
        and type(frozen["path"]) is str
        and Path(frozen["path"]).is_absolute()
        and type(frozen["bytes"]) is int
        and 0 < frozen["bytes"] <= 64 * 1024 * 1024
        and type(frozen["sha256"]) is str
        and re.fullmatch(r"[a-f0-9]{64}", frozen["sha256"]),
        "MANUAL_EXACT_FILE_REFERENCE_REQUIRED",
    )
    return frozen


def read_reference(value: dict[str, Any]) -> bytes:
    frozen = reference(value)
    path = Path(frozen["path"])
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        before = os.fstat(fd)
        need(
            stat.S_ISREG(before.st_mode) and before.st_size == frozen["bytes"],
            "MANUAL_SOURCE_LENGTH_CHANGED",
        )
        chunks: list[bytes] = []
        remaining = frozen["bytes"] + 1
        while remaining:
            part = os.read(fd, min(remaining, 1024 * 1024))
            if not part:
                break
            chunks.append(part)
            remaining -= len(part)
        raw = b"".join(chunks)
        after = os.fstat(fd)

        def stamp(s: os.stat_result) -> tuple[int, int, int, int, int]:
            return s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns, s.st_ctime_ns

        need(stamp(before) == stamp(after), "MANUAL_SOURCE_CHANGED_DURING_READ")
        need(
            len(raw) == frozen["bytes"]
            and hashlib.sha256(raw).hexdigest() == frozen["sha256"],
            "MANUAL_SOURCE_BYTES_CHANGED",
        )
        return raw
    finally:
        os.close(fd)


class FrozenReads:
    """Record immutable reads and check them again before returning any proof."""

    def __init__(self) -> None:
        self.refs: dict[str, dict[str, Any]] = {}

    def raw(self, value: dict[str, Any]) -> bytes:
        frozen = reference(value)
        raw = read_reference(frozen)
        self.refs[json.dumps(frozen, sort_keys=True)] = frozen
        return raw

    def document(self, value: dict[str, Any]) -> dict[str, Any]:
        def unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
            out: dict[str, Any] = {}
            for key, item in pairs:
                need(key not in out, "MANUAL_DUPLICATE_DOCUMENT_KEY")
                out[key] = item
            return out

        def reject_constant(_: str) -> Any:
            raise ManualSourceError("MANUAL_NONFINITE_DOCUMENT_VALUE")

        result = json.loads(
            self.raw(value),
            object_pairs_hook=unique,
            parse_constant=reject_constant,
        )
        need(type(result) is dict, "MANUAL_SOURCE_DOCUMENT_REQUIRED")
        return cast(dict[str, Any], result)

    def recheck(self) -> None:
        for value in list(self.refs.values()):
            read_reference(value)


def exact_manual_body(
    reads: FrozenReads,
    original_ref: dict[str, Any],
    companion_ref: dict[str, Any],
) -> str:
    """Verify the observed whitespace companion, never rewrite authored text.

    The source adapter must supply the actual two manifest references. A file
    named canonical-v2 is still manual provenance, not a V2 formatter proof.
    """
    original = reads.raw(original_ref)
    companion = reads.raw(companion_ref)
    expected = original[:-1] if original.endswith(b"\n") else original
    need(companion == expected, "MANUAL_BODY_COMPANION_LINEAGE_MISMATCH")
    return companion.decode("utf-8", errors="strict")


def native_runtime(
    source_ref: dict[str, Any] | None = None,
) -> types.ModuleType:
    """Load only owner-supplied pinned code; no private path or discovery default.

    The trusted owner must independently qualify this source reference. A
    manifest or source candidate cannot select the runtime used to judge it.
    """
    need(type(source_ref) is dict, "MANUAL_NATIVE_READER_REFERENCE_REQUIRED")
    frozen = reference(cast(dict[str, Any], source_ref))
    path = Path(frozen["path"])
    need(
        ".." not in path.parts
        and not any(item.is_symlink() for item in (path, *path.parents)),
        "MANUAL_DIRECT_NATIVE_READER_REQUIRED",
    )
    raw = read_reference(frozen)
    module = types.ModuleType("manual_partial_verified_native")
    module.__file__ = str(path)
    try:
        exec(compile(raw, str(path), "exec"), module.__dict__)
    except Exception:
        raise ManualSourceError("MANUAL_NATIVE_READER_INITIALIZATION_FAILED") from None
    return module


class ReadOnlyNativeStore:
    """Existing Store.load/state path without constructing or changing a Store."""

    def __init__(self, root: Path, pipeline: types.ModuleType) -> None:
        need(
            root.is_absolute() and root.resolve() == root and root.is_dir(),
            "MANUAL_EXISTING_OWNER_STORE_REQUIRED",
        )
        self.root, self.pipeline = root, pipeline

    def load(self, group: str, key: str) -> Any:
        return self.pipeline.Store.load(self, group, key)

    def state(self, name: str) -> Any:
        need(
            re.fullmatch(r"packet-[a-f0-9]{64}", name),
            "MANUAL_NATIVE_PACKET_HEAD_ONLY",
        )
        return self.pipeline.strict_json(
            self.pipeline.read_direct(self.root / "state" / (name + ".json"))
        )


class NativeManualBasis:
    """Real native currentness and authority replay for the result-absent lane.

    Registered authority references are trusted constructor arguments supplied
    by the existing owner, not selected from a manual manifest or request.
    """

    def __init__(
        self,
        store_root: Path,
        packet_id: str,
        current_authority_refs: dict[str, dict[str, Any]],
        *,
        native_source_ref: dict[str, Any] | None = None,
    ) -> None:
        need(re.fullmatch(r"[a-f0-9]{64}", packet_id), "MANUAL_PACKET_ID_REQUIRED")
        need(
            set(current_authority_refs)
            == {"academic", "policy", "issued_key", "mastery_rubric"},
            "MANUAL_REGISTERED_AUTHORITIES_REQUIRED",
        )
        self.authorities = {
            role: reference(value) for role, value in current_authority_refs.items()
        }
        need(type(native_source_ref) is dict, "MANUAL_NATIVE_READER_REFERENCE_REQUIRED")
        self.native_source_ref = reference(cast(dict[str, Any], native_source_ref))
        self.pipeline = native_runtime(self.native_source_ref)
        self.store = ReadOnlyNativeStore(store_root, self.pipeline)
        self.packet_id = packet_id

    def replay(self, reads: FrozenReads) -> tuple[Any, ...]:
        reads.raw(self.native_source_ref)
        p = self.pipeline
        head, packet, academic, qmap = p.packet_records(self.store, self.packet_id)
        reading = p.reading_records(self.store, head, packet, qmap)
        need(
            head.get("result_key") is None,
            "MANUAL_EXPECTED_ABSENT_NATIVE_RESULT_CHANGED",
        )
        registered = {
            role: reads.raw(value) for role, value in self.authorities.items()
        }
        packet_record = self.store.load("packets", self.packet_id)
        need(
            registered["academic"] == packet_record["files"]["academic.json"],
            "MANUAL_REGISTERED_ACADEMIC_MISMATCH",
        )
        form = p.package_form(academic, packet["form_id"])
        policy = p.strict_json(registered["policy"])
        spec, _ = p.validate_policy(policy, academic, form)
        need(
            packet["attempt"] in policy.get("supported_attempts", [])
            and form["key_sha256"] == self.authorities["issued_key"]["sha256"],
            "MANUAL_CURRENT_FORM_KEY_POLICY_MISMATCH",
        )
        source = self.store.load("sources", packet["source_key"])["files"]["source.pdf"]
        need(
            hashlib.sha256(source).hexdigest() == packet["source_sha256"],
            "MANUAL_CURRENT_SOURCE_MISMATCH",
        )
        return head, packet, academic, qmap, reading, policy, spec


MANIFEST = "ORIGINAL_PACKET_SAVED_PROPOSALS_QC_ADVANCE_V1"
SLOTS = {
    "raw": "STRICT-CAPTURE-CANDIDATE.private.json",
    "decisions": "decisions.private.json",
    "proposal": "CONDITIONAL-PROPOSALS.private.json",
    "holds": "TEACHER-REVIEW-HOLDS.private.json",
    "qualification": "SCORING-BINDING-QUALIFICATION.private.json",
    "body": "CLEAN-STUDENT-FEEDBACK-BODY.canonical-v2.proposal.txt",
    "lineage": "CANONICAL-V2-LINEAGE.private.json",
    "feedback": "PRIVATE-FEEDBACK.private.json",
    "citations": "CITATIONS.private.json",
    "arithmetic": "EXACT-ARITHMETIC.private.json",
}


def exact(value: object) -> Fraction:
    need(type(value) is str, "MANUAL_EXACT_RATIONAL_STRING_REQUIRED")
    try:
        return Fraction(cast(str, value))
    except (ValueError, ZeroDivisionError):
        raise ManualSourceError("MANUAL_EXACT_RATIONAL_STRING_REQUIRED") from None


class OriginalManualPartialOwner:
    """Original manifest → genuine read-only native/manual binding → consumers.

    All constructor references come from the original owner's admitted controls.
    They are not accepted from a proposed candidate or request. Destination
    qualification remains the existing writer/publisher's responsibility: no
    partial designation, source row, identity map or permission is created here.
    A source-only verification works without a destination; consumer calls fail
    explicitly until that owner's authentic destination checker is supplied.
    """

    def __init__(
        self,
        manifest_ref: dict[str, Any],
        store_root: Path,
        current_authority_refs: dict[str, dict[str, Any]],
        *,
        expected_original_owner: str,
        prekey_freeze_ref: dict[str, Any],
        academic_freeze_ref: dict[str, Any],
        reading_provenance_ref: dict[str, Any],
        review_ref: dict[str, Any] | None = None,
        actual_authored_body_version: str | None = None,
        destination_check: Callable[..., object] | None = None,
        native_source_ref: dict[str, Any] | None = None,
    ) -> None:
        need(type(native_source_ref) is dict, "MANUAL_NATIVE_READER_REFERENCE_REQUIRED")
        self.native_source_ref = reference(cast(dict[str, Any], native_source_ref))
        self.manifest_ref = reference(manifest_ref)
        self.store_root = store_root
        self.authorities = {
            role: reference(value) for role, value in current_authority_refs.items()
        }
        need(
            set(self.authorities)
            == {
                "academic",
                "policy",
                "issued_key",
                "mastery_rubric",
                "numeric_allocation",
                "issued_student_pdf",
            },
            "MANUAL_REGISTERED_SIX_AUTHORITIES_REQUIRED",
        )
        need(
            type(expected_original_owner) is str and expected_original_owner.strip(),
            "MANUAL_ORIGINAL_OWNER_REQUIRED",
        )
        self.expected_owner = expected_original_owner
        self.prekey_ref = reference(prekey_freeze_ref)
        self.academic_freeze_ref = reference(academic_freeze_ref)
        self.provenance_ref = reference(reading_provenance_ref)
        self.review_ref = reference(review_ref) if review_ref is not None else None
        # Authored-version text must come from a separately verified original
        # source label. A canonical-v2 filename provides no such version.
        need(
            actual_authored_body_version is None,
            "MANUAL_AUTHORED_VERSION_NOT_DECLARED_BY_THIS_SCHEMA",
        )
        self.destination_check = destination_check
        self._last: dict[str, Any] | None = None

    @property
    def verification_receipt(self) -> dict[str, Any]:
        need(self._last is not None, "MANUAL_NO_CURRENT_SUCCESSFUL_SOURCE_CHECK")
        return copy.deepcopy(cast(dict[str, Any], self._last))

    @staticmethod
    def _freeze_files(
        reads: FrozenReads, rows: Any, original: str, frozen: str
    ) -> None:
        need(type(rows) is list and rows, "MANUAL_FREEZE_INDEX_REQUIRED")
        for row in rows:
            common = {"bytes": row["bytes"], "sha256": row["sha256"]}
            before = reads.raw({"path": row[original], **common})
            after = reads.raw({"path": row[frozen], **common})
            need(before == after, "MANUAL_FROZEN_COPY_CHANGED")

    @staticmethod
    def _decision_index(
        decisions: dict[str, Any], spec: dict[str, Any]
    ) -> dict[tuple[str, str, str], dict[str, Any]]:
        """Original frozen-policy order; never row/key sorting or null counts."""
        indexed = {}
        for item_id, parts in decisions.items():
            need(type(parts) is dict, "MANUAL_ORIGINAL_DECISION_PARTS_REQUIRED")
            criteria = spec["items"][item_id]["criteria"]
            for part_id, values in parts.items():
                samepart = [
                    c
                    for c in criteria
                    if c["part_id"] == part_id and c["component"] == "MASTERY"
                ]
                need(
                    type(values) is list and len(values) == len(samepart) and values,
                    "MANUAL_ORIGINAL_DECISION_CRITERION_COUNT_MISMATCH",
                )
                for criterion, decision in zip(samepart, values, strict=True):
                    need(
                        type(decision) is dict
                        and "factor" in decision
                        and type(decision.get("reason")) is str,
                        "MANUAL_ORIGINAL_DECISION_REQUIRED",
                    )
                    if decision["factor"] is None:
                        need(
                            type(decision.get("hold")) is str
                            and decision["hold"].strip(),
                            "MANUAL_ORIGINAL_HELD_DECISION_REASON_REQUIRED",
                        )
                    else:
                        exact(decision["factor"])
                        need(
                            "hold" not in decision,
                            "MANUAL_SUPPORTED_DECISION_RETAINS_HOLD",
                        )
                    indexed[(item_id, part_id, criterion["criterion_id"])] = decision
        return indexed

    @staticmethod
    def _citation_target(
        citation: dict[str, Any],
        row: dict[str, Any],
        spec: dict[str, Any],
        form_id: str,
    ) -> dict[str, Any]:
        pointer = citation.get("policy_json_pointer")
        need(
            type(pointer) is str and pointer.startswith("/"),
            "MANUAL_CRITERION_CITATION_POINTER_REQUIRED",
        )
        pointer = cast(str, pointer)
        tokens = pointer[1:].split("/")
        need(
            all(re.search(r"~(?![01])", token) is None for token in tokens),
            "MANUAL_CRITERION_CITATION_POINTER_REQUIRED",
        )
        tokens = [token.replace("~1", "/").replace("~0", "~") for token in tokens]
        prefix = ["forms", form_id, "items", row["item_id"]]
        if row["component"] == "MC_CORRECTNESS":
            need(tokens == prefix, "MANUAL_MC_CITATION_SCOPE_MISMATCH")
            return cast(dict[str, Any], spec["items"][row["item_id"]])
        need(
            len(tokens) == 6
            and tokens[:5] == prefix + ["criteria"]
            and re.fullmatch(r"0|[1-9][0-9]*", tokens[5]),
            "MANUAL_CRITERION_CITATION_SCOPE_MISMATCH",
        )
        criteria = spec["items"][row["item_id"]]["criteria"]
        index = int(tokens[5])
        need(index < len(criteria), "MANUAL_CRITERION_CITATION_INDEX_MISMATCH")
        criterion = criteria[index]
        need(
            criterion["criterion_id"] == row["criterion_id"]
            and criterion["part_id"] == row["part_id"]
            and criterion["component"] == row["component"]
            and row["component"] in {"MASTERY", "ATTEMPT"},
            "MANUAL_CRITERION_CITATION_IDENTITY_MISMATCH",
        )
        return cast(dict[str, Any], criterion)

    @staticmethod
    def _rows(
        proposal: dict[str, Any],
        holds: dict[str, Any],
        spec: dict[str, Any],
        decisions: dict[str, Any],
        citation_entries: dict[str, Any],
        form_id: str,
    ) -> None:
        rows = proposal.get("rows")
        need(type(rows) is list and rows, "MANUAL_ORIGINAL_ROWS_REQUIRED")
        rows = cast(list[dict[str, Any]], rows)
        ids = [row["row_id"] for row in rows]
        need(len(set(ids)) == len(ids), "MANUAL_DUPLICATE_COMPONENT_ROW")
        held = {}
        original_decisions = OriginalManualPartialOwner._decision_index(decisions, spec)
        seen_decisions: set[tuple[str, str, str]] = set()
        for row in rows:
            item = spec["items"][row["item_id"]]
            citation_key = row.get("citation")
            need(
                type(citation_key) is str and citation_key in citation_entries,
                "MANUAL_EXACT_CITATION_KEY_REQUIRED",
            )
            citation_key = cast(str, citation_key)
            citation = citation_entries[citation_key]
            need(type(citation) is dict, "MANUAL_CITATION_RECORD_REQUIRED")
            cited_target = OriginalManualPartialOwner._citation_target(
                citation, row, spec, form_id
            )
            if row["component"] == "MC_CORRECTNESS":
                maximum = exact(item["maximum_points"])
            else:
                matched = [
                    c
                    for c in item["criteria"]
                    if c["criterion_id"] == row["criterion_id"]
                ]
                need(
                    len(matched) == 1
                    and matched[0]["component"] == row["component"]
                    and matched[0]["part_id"] == row["part_id"],
                    "MANUAL_CURRENT_CRITERION_MISMATCH",
                )
                maximum = exact(matched[0]["maximum_points"])
            need(
                exact(row["maximum_points"]) == maximum,
                "MANUAL_CURRENT_COMPONENT_MAXIMUM_MISMATCH",
            )
            earned, lost = row["proposed_points"], row["known_points_lost"]
            need(
                row["status"] in {"HELD", "CONDITIONAL_PROPOSAL"}
                and (
                    (row["status"] == "HELD" and earned is None and lost is None)
                    or (
                        row["status"] == "CONDITIONAL_PROPOSAL"
                        and earned is not None
                        and lost is not None
                        and row.get("hold_reason") is None
                    )
                ),
                "MANUAL_ORIGINAL_ROW_STATUS_NULL_MISMATCH",
            )
            if row["component"] == "MASTERY":
                criterion = cited_target
                key = (row["item_id"], row["part_id"], criterion["criterion_id"])
                need(
                    key in original_decisions and key not in seen_decisions,
                    "MANUAL_ORIGINAL_DECISION_IDENTITY_MISMATCH",
                )
                seen_decisions.add(key)
                decision = original_decisions[key]
                need(
                    row["reason"] == decision["reason"],
                    "MANUAL_ORIGINAL_DECISION_REASON_CHANGED",
                )
                if decision["factor"] is None:
                    need(
                        row["status"] == "HELD"
                        and row["factor"] is None
                        and earned is None
                        and lost is None
                        and row["hold_reason"] == decision["hold"],
                        "MANUAL_ORIGINAL_HELD_DECISION_PROMOTED",
                    )
                else:
                    factor = exact(decision["factor"])
                    need(
                        row["status"] == "CONDITIONAL_PROPOSAL"
                        and row["hold_reason"] is None
                        and exact(row["factor"]) == factor
                        and exact(earned) == maximum * factor,
                        "MANUAL_ORIGINAL_SUPPORTED_DECISION_CHANGED",
                    )
            if earned is None:
                need(
                    lost is None
                    and type(row.get("hold_reason")) is str
                    and row["hold_reason"],
                    "MANUAL_UNRESOLVED_COMPONENT_MUST_REMAIN_HELD",
                )
                held[row["row_id"]] = row
            else:
                award = exact(earned)
                need(
                    0 <= award <= maximum and exact(lost) == maximum - award,
                    "MANUAL_SAVED_COMPONENT_ARITHMETIC_MISMATCH",
                )
                if row["component"] != "MC_CORRECTNESS":
                    need(
                        award in [exact(x) for x in matched[0]["allowed_points"]],
                        "MANUAL_SAVED_AWARD_NOT_IN_CURRENT_POLICY",
                    )
        need(
            seen_decisions == set(original_decisions),
            "MANUAL_ORIGINAL_DECISION_ROW_OMITTED",
        )
        ledger = holds.get("held_rows")
        need(
            type(ledger) is list
            and len({r["row_id"] for r in ledger}) == len(ledger)
            and {r["row_id"] for r in ledger} == set(held),
            "MANUAL_ORIGINAL_HOLD_SET_MISMATCH",
        )
        ledger = cast(list[dict[str, Any]], ledger)
        for row in ledger:
            original = held[row["row_id"]]
            need(
                row["proposed_points"] is None
                and row["reason"] == original["hold_reason"]
                and row["item_id"] == original["item_id"],
                "MANUAL_ORIGINAL_HOLD_REASON_CHANGED",
            )

    def verify_source(self) -> dict[str, Any]:
        """Authenticate actual source documents; no target/admission is inferred."""
        self._last = None
        reads = FrozenReads()
        manifest = reads.document(self.manifest_ref)
        need(
            manifest.get("contract") == MANIFEST
            and manifest.get("owner_thread_id") == self.expected_owner,
            "MANUAL_ORIGINAL_MANIFEST_OWNER_MISMATCH",
        )
        native = NativeManualBasis(
            self.store_root,
            manifest["packet_key"],
            {
                k: self.authorities[k]
                for k in ("academic", "policy", "issued_key", "mastery_rubric")
            },
            native_source_ref=self.native_source_ref,
        )
        basis = native.replay(reads)
        head, packet, _, _, reading, policy, spec = basis
        need(
            all(
                manifest[k] == packet[k]
                for k in ("source_sha256", "form_id", "attempt")
            )
            and manifest["native_reading_key"] == head["reading_key"],
            "MANUAL_CURRENT_PACKET_READING_MISMATCH",
        )
        for role, expected_path, current in [
            (
                "current_head",
                self.store_root / "state" / ("packet-" + packet["packet_id"] + ".json"),
                head,
            ),
            (
                "native_packet",
                self.store_root / "packets" / packet["packet_id"] / "packet.json",
                packet,
            ),
            (
                "native_reading",
                self.store_root / "readings" / head["reading_key"] / "reading.json",
                reading,
            ),
        ]:
            need(
                Path(manifest[role]["path"]) == expected_path
                and reads.document(manifest[role]) == current,
                "MANUAL_CURRENT_NATIVE_RECORD_BINDING_MISMATCH",
            )
        refs = manifest["inputs"]
        need(
            all(name in refs for name in SLOTS.values()),
            "MANUAL_ORIGINAL_INPUT_SLOT_MISSING",
        )
        for value in refs.values():
            reads.raw(value)
        for value in manifest["academic_refs"]:
            reads.raw(value)
        docs = {
            role: reads.document(refs[SLOTS[role]])
            for role in ("decisions", "qualification", "proposal", "holds", "lineage")
        }
        strict_ref = refs[SLOTS["raw"]]
        raw = reads.raw(strict_ref)
        native_raw = native.store.load("raw-readings", reading["raw_key"])["files"][
            "response.json"
        ]
        need(
            raw == native_raw and strict_ref["sha256"] == reading["raw_sha256"],
            "MANUAL_CAPTURED_RAW_READING_MISMATCH",
        )
        qualification, proposal, holds = (
            docs["qualification"],
            docs["proposal"],
            docs["holds"],
        )
        expected = {
            "source_sha256": packet["source_sha256"],
            "form_id": packet["form_id"],
            "attempt": packet["attempt"],
            "qualified_capture_candidate_sha256": strict_ref["sha256"],
            "policy_status": "SEALED",
            "prekey_chronology_valid": True,
        }
        need(
            all(qualification.get(k) == v for k, v in expected.items()),
            "MANUAL_ACADEMIC_QUALIFICATION_BINDING_MISMATCH",
        )
        for field, role in [
            ("academic_package_sha256", "academic"),
            ("key_pdf_sha256", "issued_key"),
            ("policy_sha256", "policy"),
            ("mastery_rubric_sha256", "mastery_rubric"),
            ("numeric_allocation_sha256", "numeric_allocation"),
            ("issued_student_pdf_sha256", "issued_student_pdf"),
        ]:
            reads.raw(self.authorities[role])
            need(
                qualification.get(field) == self.authorities[role]["sha256"]
                and self.authorities[role] in manifest["academic_refs"],
                "MANUAL_REGISTERED_QUALIFICATION_PIN_MISMATCH:" + role,
            )
        need(
            proposal["source_sha256"]
            == holds["source_sha256"]
            == packet["source_sha256"]
            and proposal["literal_sha256"] == qualification["literal_sha256"]
            and proposal["binding_qualification_sha256"]
            == refs[SLOTS["qualification"]]["sha256"],
            "MANUAL_PROPOSAL_LITERAL_QUALIFICATION_MISMATCH",
        )
        need(
            proposal["whole_test_grade"] is None
            and proposal["whole_test_preview_computed"] is False
            and proposal["whole_packet_complete"] is False
            and proposal["teacher_accepted"] is False
            and manifest["teacher_acceptance"] is False
            and manifest["canvas_publication"] is False,
            "MANUAL_PARTIAL_NULL_AND_TEACHER_FLAGS_REQUIRED",
        )
        academic_freeze = reads.document(self.academic_freeze_ref)
        self._freeze_files(reads, academic_freeze["files"], "original", "frozen")
        need(
            all(
                any(
                    row["original"] == auth["path"]
                    and row["sha256"] == auth["sha256"]
                    and row["bytes"] == auth["bytes"]
                    for row in academic_freeze["files"]
                )
                for auth in self.authorities.values()
            ),
            "MANUAL_CURRENT_REGISTERED_ACADEMIC_FREEZE_MISMATCH",
        )
        citation_entries = reads.document(refs[SLOTS["citations"]])
        self._rows(
            proposal,
            holds,
            spec,
            docs["decisions"],
            citation_entries,
            packet["form_id"],
        )
        prekey = reads.document(self.prekey_ref)
        need(
            prekey["source_sha256"] == packet["source_sha256"]
            and prekey["pre_key_freeze"] is True
            and prekey["post_key_literal_changes_forbidden"] is True
            and prekey["no_prior_key_or_rubric_access_by_reader"] is True,
            "MANUAL_PREKEY_SOURCE_CHRONOLOGY_MISMATCH",
        )
        self._freeze_files(reads, prekey["inputs"], "original_path", "frozen_path")
        need(
            any(
                row["sha256"] == qualification["literal_sha256"]
                for row in prekey["inputs"]
            ),
            "MANUAL_PREKEY_LITERAL_HASH_NOT_BOUND",
        )
        provenance = reads.document(self.provenance_ref)
        need(
            {"draft_path", "draft_sha256", "preparation", "page_images"}
            <= set(provenance),
            "MANUAL_NATIVE_CAPTURE_PROVENANCE_REQUIRED",
        )
        need(
            provenance["preparation"]["packet_id"] == packet["packet_id"],
            "MANUAL_NATIVE_CAPTURE_PROVENANCE_MISMATCH",
        )
        # Bind the historical draft at its own locator first. This supported
        # source profile is the custodian-confirmed unchanged-copy lineage:
        # exact bytes, not a field alias or overwritten historical hash, must
        # also equal the separately qualified strict/native raw response.
        draft_ref = {
            "path": provenance["draft_path"],
            "sha256": provenance["draft_sha256"],
            "bytes": Path(provenance["draft_path"]).stat().st_size,
        }
        need(
            reads.raw(draft_ref) == raw, "MANUAL_CAPTURE_DRAFT_UNCHANGED_COPY_REQUIRED"
        )
        pages = native.store.load("pages", head["pages_key"])
        for page in provenance["page_images"]:
            raw_page = pages["files"][f"page-{page['page_number']:02d}.png"]
            path = Path(page["prepared_image_path"])
            page_ref = {
                "path": str(path),
                "bytes": len(raw_page),
                "sha256": page["prepared_image_sha256"],
            }
            need(
                reads.raw(page_ref) == raw_page
                and page["source_sha256"] == packet["source_sha256"],
                "MANUAL_CURRENT_IMAGE_BINDING_MISMATCH",
            )
        need(
            len(provenance["page_images"]) == packet["expected_pages"]
            and all(
                type(page["page_number"]) is int for page in provenance["page_images"]
            )
            and {page["page_number"] for page in provenance["page_images"]}
            == set(range(1, packet["expected_pages"] + 1)),
            "MANUAL_SOURCE_PAGE_PROVENANCE_INCOMPLETE",
        )
        lineage = docs["lineage"]
        body_ref = refs[SLOTS["body"]]
        original_ref = {
            "path": lineage["original_path"],
            "sha256": lineage["original_sha256"],
            "bytes": Path(lineage["original_path"]).stat().st_size,
        }
        need(
            body_ref["path"] == lineage["canonical_path"]
            and body_ref["sha256"] == lineage["canonical_sha256"]
            and reads.raw(original_ref).endswith(b"\n"),
            "MANUAL_BODY_LINEAGE_REFERENCE_MISMATCH",
        )
        body = exact_manual_body(reads, original_ref, body_ref)
        # Later review is separate from original pre-review flags. Do not call
        # an unimplemented report/start semantic adapter a passed review. A
        # saved report can be retained as provenance with truthful UNKNOWN.
        review_state = {"status": "NOT_REVIEWED", "ref": None}
        if self.review_ref is not None:
            reads.document(self.review_ref)
            review_state = {"status": "UNKNOWN", "ref": None}
        pins = {
            "source_sha256": packet["source_sha256"],
            "reading_sha256": manifest["native_reading"]["sha256"],
            "judgment_sha256": refs[SLOTS["decisions"]]["sha256"],
            "policy_sha256": self.authorities["policy"]["sha256"],
            "proposal_sha256": refs[SLOTS["proposal"]]["sha256"],
            "body_sha256": body_ref["sha256"],
            "literal_sha256": qualification["literal_sha256"],
            "captured_raw_sha256": strict_ref["sha256"],
            "manifest_sha256": self.manifest_ref["sha256"],
        }
        context = {
            "whole_test_proposed_score": None,
            "native_context": {
                "result_key": None,
                "grade_preview": None,
                "holds": None,
            },
            "remaining_holds": copy.deepcopy(holds["held_rows"]),
            "original_proposal_ref": copy.deepcopy(refs[SLOTS["proposal"]]),
            "actual_authored_body_version": None,
            "review_state": review_state,
            "original_manifest_contract": MANIFEST,
        }
        reads.recheck()
        need(native.replay(FrozenReads()) == basis, "MANUAL_FINAL_NATIVE_BASIS_CHANGED")
        result = {"body": body, "source_pins": pins, "manual_context": context}
        self._last = {
            "contract": "ORIGINAL_MANUAL_PARTIAL_SOURCE_BINDING_VERIFIED_V1",
            "manifest_ref": copy.deepcopy(self.manifest_ref),
            "current_native_packet_id": packet["packet_id"],
            "checked_refs": copy.deepcopy(list(reads.refs.values())),
            "native_context": copy.deepcopy(context["native_context"]),
            "separate_review_provenance_ref": copy.deepcopy(self.review_ref),
            "capture_draft_ref": copy.deepcopy(draft_ref),
            "captured_raw_ref": copy.deepcopy(strict_ref),
            "review_state": copy.deepcopy(review_state),
            "teacher_accepted": False,
            "publication_allowed": False,
            "target_or_designation_authenticated": False,
        }
        return result

    def prepare_candidate(self, target: dict[str, Any]) -> dict[str, Any]:
        source = self.verify_source()
        candidate = {
            "contract": MANUAL_PARTIAL_CONTRACT,
            "source_version": MANUAL_PARTIAL_SOURCE,
            "component_scope": "MANUAL_PARTIAL",
            **source,
            "target": copy.deepcopy(target),
            "teacher_accepted": False,
            "publication_allowed": False,
        }
        validate_manual_partial_candidate(candidate)
        return candidate

    def source_check(
        self,
        candidate: dict[str, Any],
        destination: dict[str, Any],
        context: dict[str, Any],
    ) -> None:
        self._last = None
        try:
            need(
                candidate == self.prepare_candidate(candidate["target"]),
                "MANUAL_CANDIDATE_ORIGINAL_SOURCE_CHANGED",
            )
            need(
                self.destination_check is not None,
                "MANUAL_OWNER_DESTINATION_QUALIFICATION_NOT_CONFIGURED",
            )
            assert self.destination_check is not None
            result = self.destination_check(
                copy.deepcopy(candidate),
                copy.deepcopy(destination),
                copy.deepcopy(context),
            )
            if inspect.iscoroutine(result):
                result.close()
            need(result is None, "MANUAL_OWNER_DESTINATION_QUALIFICATION_REQUIRED")
            # Destination callbacks may read mutable owner controls. Re-run real
            # source/native replay last, and do not carry a stale success proof.
            need(
                candidate == self.prepare_candidate(candidate["target"]),
                "MANUAL_FINAL_SOURCE_CHANGED",
            )
        except BaseException:
            self._last = None
            raise

    def prepare_note(self, *, target: dict[str, Any], **context: Any) -> dict[str, Any]:
        return prepare_note_draft(
            self.prepare_candidate(target),
            target=target,
            source_check=self.source_check,
            **context,
        )

    def prepare_sheet(
        self,
        *,
        target: dict[str, Any],
        designation: dict[str, Any],
        snapshot: dict[str, Any],
    ) -> dict[str, Any]:
        return prepare_partial_projection(
            self.prepare_candidate(target),
            designation,
            snapshot,
            source_check=self.source_check,
        )
