"""Fictional file-backed source checks; no real Store, network, or writes."""

import copy
import hashlib
import json
import os
from pathlib import Path

import pytest
from test_gradebook import snapshot as snapshot
from test_gradebook_native import binding as binding
from test_unit2_note_draft import applied
from test_unit2_note_draft import scenario as scenario

from canvas_mcp.gradebook.client import GradebookError
from canvas_mcp.gradebook.unit2_manual_partial_owner import (
    FrozenReads,
    ManualSourceError,
    NativeManualBasis,
    OriginalManualPartialOwner,
    exact_manual_body,
    native_runtime,
    read_reference,
)


def file_ref(path):
    raw = path.read_bytes()
    return {
        "path": str(path),
        "bytes": len(raw),
        "sha256": hashlib.sha256(raw).hexdigest(),
    }


def test_exact_file_read_has_no_mutation(tmp_path):
    path = tmp_path / "fictional.json"
    path.write_bytes(b'{"fictional":true}\n')
    ref = file_ref(path)
    before = copy.deepcopy(ref)
    reads = FrozenReads()
    assert reads.document(ref) == {"fictional": True}
    reads.recheck()
    assert ref == before
    assert path.read_bytes() == b'{"fictional":true}\n'


def test_final_read_detects_late_bytes_change(tmp_path):
    path = tmp_path / "fictional.json"
    path.write_bytes(b'{"fictional":true}\n')
    reads = FrozenReads()
    reads.document(file_ref(path))
    path.write_bytes(b'{"fictional":null}\n')
    with pytest.raises(ManualSourceError, match="MANUAL_SOURCE_BYTES_CHANGED"):
        reads.recheck()


def test_external_reference_mutation_cannot_rebase_frozen_read(tmp_path):
    path = tmp_path / "fictional.json"
    path.write_bytes(b'{"fictional":true}\n')
    ref = file_ref(path)
    reads = FrozenReads()
    reads.document(ref)
    path.write_bytes(b'{"fictional":null}\n')
    ref.update(file_ref(path))
    with pytest.raises(ManualSourceError, match="MANUAL_SOURCE_BYTES_CHANGED"):
        reads.recheck()


def test_symlink_source_rejected(tmp_path):
    source = tmp_path / "fictional"
    source.write_bytes(b"fictional")
    link = tmp_path / "alias"
    link.symlink_to(source)
    with pytest.raises(OSError):
        read_reference(file_ref(link))


@pytest.mark.parametrize("raw", [b'{"k":1,"k":2}', b'{"k":NaN}'])
def test_ambiguous_or_nonfinite_json_rejected(tmp_path, raw):
    path = tmp_path / "fictional.json"
    path.write_bytes(raw)
    with pytest.raises(ManualSourceError):
        FrozenReads().document(file_ref(path))


@pytest.mark.parametrize("length", [True, 0, -1, 64 * 1024 * 1024 + 1])
def test_invalid_file_length_not_authority(tmp_path, length):
    path = tmp_path / "fictional.json"
    path.write_bytes(json.dumps({"fictional": True}).encode())
    ref = file_ref(path)
    ref["bytes"] = length
    with pytest.raises(ManualSourceError, match="MANUAL_EXACT_FILE_REFERENCE_REQUIRED"):
        read_reference(ref)


def test_native_reader_has_no_implicit_private_binding():
    with pytest.raises(ManualSourceError, match="NATIVE_READER_REFERENCE_REQUIRED"):
        native_runtime()


def test_native_reader_executes_exact_owner_pinned_source_only(tmp_path):
    path = tmp_path / "fictional_reader.py"
    path.write_text("VALUE = 'FICTIONAL_READER'\n", encoding="utf-8")
    ref = file_ref(path)
    original = copy.deepcopy(ref)
    loaded = native_runtime(ref)
    assert loaded.VALUE == "FICTIONAL_READER"
    assert ref == original
    path.write_text(
        "raise AssertionError('MUST_NOT_EXECUTE_CHANGED_CODE')\n", encoding="utf-8"
    )
    with pytest.raises(ManualSourceError, match="MANUAL_SOURCE_(LENGTH|BYTES)_CHANGED"):
        native_runtime(ref)


def test_native_reader_refuses_parent_symlink_before_loading(tmp_path):
    folder = tmp_path / "source"
    folder.mkdir()
    path = folder / "fictional_reader.py"
    path.write_text("VALUE = 'FICTIONAL'\n", encoding="utf-8")
    alias = tmp_path / "alias"
    alias.symlink_to(folder, target_is_directory=True)
    ref = file_ref(alias / path.name)
    with pytest.raises(ManualSourceError, match="DIRECT_NATIVE_READER_REQUIRED"):
        native_runtime(ref)


def test_native_reader_rejects_changed_reference_before_module_execution(tmp_path):
    path = tmp_path / "fictional_reader.py"
    path.write_text(
        "raise AssertionError('UNPINNED_CODE_MUST_NOT_EXECUTE')\n", encoding="utf-8"
    )
    ref = file_ref(path)
    ref["sha256"] = "0" * 64
    with pytest.raises(ManualSourceError, match="SOURCE_BYTES_CHANGED"):
        native_runtime(ref)


@pytest.fixture
def native_reader_ref():
    """Optional owner-engine integration; both explicit immutable pins required."""
    path = os.environ.get("CANVAS_UNIT2_NATIVE_READER_SOURCE")
    expected = os.environ.get("CANVAS_UNIT2_NATIVE_READER_SHA256")
    if path is None and expected is None:
        pytest.skip(
            "Optional native-owner integration requires explicit source and hash"
        )
    if path is None or expected is None:
        pytest.fail("Native-owner integration requires both source and hash")
    ref = file_ref(Path(path))
    assert ref["sha256"] == expected, "Explicit native-owner source hash changed"
    return ref


@pytest.fixture
def native_case(tmp_path, native_reader_ref):
    """Real native readers over wholly fictional immutable record files."""
    p = native_runtime(native_reader_ref)
    store = p.Store(tmp_path / "fictional-store")

    def save(name, value):
        path = tmp_path / name
        path.write_bytes(value if isinstance(value, bytes) else p.canonical(value))
        return file_ref(path)

    key = save("fictional-key.pdf", b"FICTIONAL_KEY_ONLY")
    rubric = save("fictional-rubric.json", {"fictional": "source"})
    source = store.record("sources", {"source.pdf": b"FICTIONAL_SOURCE_ONLY"})
    pages = store.record(
        "pages",
        {f"page-{n:02d}.png": f"FICTIONAL_PAGE_{n}".encode() for n in range(1, 9)},
    )
    questions = [
        {
            "item_id": "MC01",
            "kind": "MC",
            "prompt": "Fictional MC",
            "page_numbers": [1],
            "correct_letter": "A",
        },
        {
            "item_id": "FRQ01",
            "kind": "FRQ",
            "prompt": "Fictional FRQ",
            "page_numbers": [2],
            "parts": [
                {
                    "part_id": "a",
                    "prompt": "Fictional part",
                    "expected_answer": "Fictional key.",
                }
            ],
        },
    ]
    academic = {
        "schema_version": 1,
        "assessment_id": "UNIT2",
        "forms": [
            {
                "form_id": "DEMO_A",
                "expected_pages": 8,
                "key_sha256": key["sha256"],
                "questions": questions,
            }
        ],
    }
    policy = {
        "schema_version": 1,
        "assessment_id": "UNIT2",
        "status": "SEALED",
        "policy_id": "FICTIONAL",
        "version": "1",
        "acceptance": {
            "decision_id": "FICTIONAL",
            "accepted_by": "FICTIONAL_NOT_REAL_AUTHORITY",
        },
        "source_refs": [{"type": "FICTIONAL_ONLY"}],
        "supported_attempts": ["R1"],
        "blank_response": "ZERO",
        "ambiguous_mc": "HOLD",
        "grade_operations": [{"op": "to_percent"}],
        "forms": {
            "DEMO_A": {
                "items": {
                    "MC01": {"maximum_points": "1", "weight": "1"},
                    "FRQ01": {
                        "maximum_points": "1",
                        "weight": "1",
                        "criteria": [
                            {
                                "criterion_id": "FRQ01/a/c1",
                                "part_id": "a",
                                "component": "MASTERY",
                                "description": "Fictional",
                                "maximum_points": "1",
                                "allowed_points": ["0", "1"],
                            }
                        ],
                    },
                }
            }
        },
    }
    authorities = {
        "academic": save("academic.json", academic),
        "policy": save("policy.json", policy),
        "issued_key": key,
        "mastery_rubric": rubric,
    }
    qmap = p.question_map(academic["forms"][0])
    packet = {
        "schema_version": 1,
        "assessment_id": "UNIT2",
        "form_id": "DEMO_A",
        "pin": "0000",
        "section": "FICTIONAL",
        "attempt": "R1",
        "expected_pages": 8,
        "source_key": source,
        "source_sha256": p.sha(b"FICTIONAL_SOURCE_ONLY"),
        "academic_sha256": authorities["academic"]["sha256"],
        "question_map_sha256": p.sha(p.canonical(qmap)),
    }
    packet["packet_id"] = p.sha(p.canonical(packet))
    store.record(
        "packets",
        {
            "packet.json": packet,
            "academic.json": p.canonical(academic),
            "question-map.json": p.canonical(qmap),
        },
        key=packet["packet_id"],
    )
    identity = {
        "observed_pin": "0000",
        "observed_form_id": "DEMO_A",
        "observed_attempt": "R1",
        "page_number": 1,
        "evidence_note": "Fictional",
        "section_binding": {
            "method": "TEACHER_EXPLICIT",
            "section": "FICTIONAL",
            "attested_by": "FICTIONAL",
        },
    }
    raw = {
        "schema_version": 1,
        "packet_id": packet["packet_id"],
        "source_sha256": packet["source_sha256"],
        "question_map_sha256": packet["question_map_sha256"],
        "reader": {
            "reader_id": "FICTIONAL",
            "method": "FICTIONAL",
            "key_free": True,
            "literal_transcription": True,
        },
        "identity_observation": identity,
        "page_observations": [
            {
                "page_number": n,
                "printed_page_number": n,
                "observed_form_id": "DEMO_A",
                "order_verified": True,
                "complete_visible": True,
                "evidence_note": "Fictional",
                "question_content_verified": True,
                "observed_item_ids": [
                    q["item_id"] for q in questions if n in q["page_numbers"]
                ],
            }
            for n in range(1, 9)
        ],
        "items": [
            {
                "item_id": "MC01",
                "observed_prompt_anchor": "Fictional MC",
                "read_status": "READABLE",
                "recorded_text": "A",
                "evidence_refs": [
                    {"page_number": 1, "region_description": "Fictional"}
                ],
                "diagrams": [],
                "option_marks": {
                    letter: {
                        "state": "CLEAR_MARK" if letter == "A" else "UNMARKED",
                        "observation": "Fictional",
                    }
                    for letter in "ABCD"
                },
            },
            {
                "item_id": "FRQ01",
                "observed_prompt_anchor": "Fictional FRQ",
                "read_status": "READABLE",
                "recorded_text": "Fictional literal.",
                "evidence_refs": [
                    {"page_number": 2, "region_description": "Fictional"}
                ],
                "diagrams": [],
                "parts": [
                    {
                        "part_id": "a",
                        "read_status": "READABLE",
                        "recorded_text": "Fictional literal.",
                        "evidence_refs": [
                            {"page_number": 2, "region_description": "Fictional"}
                        ],
                        "diagrams": [],
                    }
                ],
            },
        ],
    }
    raw_bytes = p.canonical(raw)
    raw_key = store.record(
        "raw-readings",
        {
            "response.json": raw_bytes,
            "receipt.json": {
                "packet_id": packet["packet_id"],
                "body_sha256": p.sha(raw_bytes),
            },
        },
    )
    reading = {
        "schema_version": 1,
        "packet_id": packet["packet_id"],
        "source_sha256": packet["source_sha256"],
        "question_map_sha256": packet["question_map_sha256"],
        "raw_key": raw_key,
        "raw_sha256": p.sha(raw_bytes),
        **p.validate_reading(raw_bytes, packet, qmap),
    }
    reading_key = store.record("readings", {"reading.json": reading})
    head = {
        "packet_key": packet["packet_id"],
        "reading_key": reading_key,
        "result_key": None,
        "pages_key": pages,
        "status": "EVIDENCE_CAPTURED",
        "gates": p.GATES,
    }
    store.state("packet-" + packet["packet_id"], head)
    basis = NativeManualBasis(
        store.root,
        packet["packet_id"],
        authorities,
        native_source_ref=native_reader_ref,
    )
    return {
        "basis": basis,
        "native_source_ref": native_reader_ref,
        "pipeline": p,
        "store": store,
        "packet": packet,
        "reading": reading,
        "head": head,
        "authorities": authorities,
        "pages": pages,
    }


def test_actual_native_replay_without_result_or_score(native_case):
    case = native_case
    root = case["store"].root
    before = {str(p): p.read_bytes() for p in root.rglob("*") if p.is_file()}
    head, packet, _, _, reading, _, _ = case["basis"].replay(FrozenReads())
    assert head["result_key"] is None
    assert reading == case["reading"]
    assert packet == case["packet"]
    assert before == {str(p): p.read_bytes() for p in root.rglob("*") if p.is_file()}


def test_native_page_drift_fails_final_replay(native_case):
    case = native_case
    reads = FrozenReads()
    first = case["basis"].replay(reads)
    page = case["store"].root / "pages" / case["pages"] / "page-08.png"
    page.write_bytes(b"CHANGED_FICTIONAL_PAGE")
    reads.recheck()
    with pytest.raises(ValueError, match="STORED_HASH_MISMATCH"):
        assert first == case["basis"].replay(FrozenReads())


def test_registered_policy_change_fails(native_case):
    case = native_case
    Path(case["authorities"]["policy"]["path"]).write_bytes(b"changed")
    with pytest.raises(ManualSourceError):
        case["basis"].replay(FrozenReads())


def test_new_native_result_does_not_get_rebased(native_case):
    case = native_case
    head = copy.deepcopy(case["head"])
    head["result_key"] = "a" * 64
    case["store"].state("packet-" + case["packet"]["packet_id"], head)
    with pytest.raises(
        ManualSourceError, match="MANUAL_EXPECTED_ABSENT_NATIVE_RESULT_CHANGED"
    ):
        case["basis"].replay(FrozenReads())


@pytest.mark.parametrize("suffix", [b"", b"\n"])
def test_exact_original_manual_body_whitespace_companion(tmp_path, suffix):
    original, companion = tmp_path / "original.txt", tmp_path / "canonical-v2.txt"
    original.write_bytes(b"Fictional conditional correction." + suffix)
    companion.write_bytes(b"Fictional conditional correction.")
    reads = FrozenReads()
    assert (
        exact_manual_body(reads, file_ref(original), file_ref(companion))
        == "Fictional conditional correction."
    )
    reads.recheck()


def test_body_wording_change_never_accepted_as_whitespace(tmp_path):
    original, companion = tmp_path / "original.txt", tmp_path / "canonical-v2.txt"
    original.write_bytes(b"Fictional conditional correction.\n")
    companion.write_bytes(b"Changed fictional correction.")
    with pytest.raises(
        ManualSourceError, match="MANUAL_BODY_COMPANION_LINEAGE_MISMATCH"
    ):
        exact_manual_body(FrozenReads(), file_ref(original), file_ref(companion))


@pytest.fixture
def manual_case(native_case, tmp_path):
    """Exact named manifest slots from sanitized original-custodian metadata."""
    case = native_case
    p, store, packet, reading = (
        case["pipeline"],
        case["store"],
        case["packet"],
        case["reading"],
    )

    def save(name, value):
        path = tmp_path / name
        path.write_bytes(value if isinstance(value, bytes) else p.canonical(value))
        return file_ref(path)

    authorities = copy.deepcopy(case["authorities"])
    authorities["numeric_allocation"] = save(
        "allocation.json", {"fictional": "allocation"}
    )
    authorities["issued_student_pdf"] = save(
        "issued.pdf", b"FICTIONAL_ISSUED_REFERENCE"
    )
    raw_path = store.root / "raw-readings" / reading["raw_key"] / "response.json"
    strict_ref = file_ref(raw_path)
    literal_ref = save(
        "prekey-literal.json",
        {"fictional": "original literal before schema conversion"},
    )
    frozen_literal = save("frozen-literal.json", Path(literal_ref["path"]).read_bytes())
    prekey = save(
        "prekey-index.json",
        {
            "source_sha256": packet["source_sha256"],
            "pre_key_freeze": True,
            "post_key_literal_changes_forbidden": True,
            "no_prior_key_or_rubric_access_by_reader": True,
            "inputs": [
                {
                    "name": "FICTIONAL_LITERAL",
                    "original_path": literal_ref["path"],
                    "frozen_path": frozen_literal["path"],
                    "bytes": literal_ref["bytes"],
                    "sha256": literal_ref["sha256"],
                }
            ],
        },
    )
    freeze_rows = []
    for n, ref in enumerate(authorities.values()):
        frozen = save(f"frozen-authority-{n}", Path(ref["path"]).read_bytes())
        freeze_rows.append(
            {
                "original": ref["path"],
                "frozen": frozen["path"],
                "bytes": ref["bytes"],
                "sha256": ref["sha256"],
            }
        )
    academic_freeze = save("academic-index.json", {"files": freeze_rows})
    qualification = {
        "source_sha256": packet["source_sha256"],
        "form_id": packet["form_id"],
        "attempt": packet["attempt"],
        "qualified_capture_candidate_sha256": strict_ref["sha256"],
        "literal_sha256": literal_ref["sha256"],
        "policy_status": "SEALED",
        "prekey_chronology_valid": True,
    }
    for field, role in [
        ("academic_package_sha256", "academic"),
        ("key_pdf_sha256", "issued_key"),
        ("policy_sha256", "policy"),
        ("mastery_rubric_sha256", "mastery_rubric"),
        ("numeric_allocation_sha256", "numeric_allocation"),
        ("issued_student_pdf_sha256", "issued_student_pdf"),
    ]:
        qualification[field] = authorities[role]["sha256"]
    qual_ref = save("qualification.json", qualification)
    rows = [
        {
            "row_id": "FICTIONAL_MC_ROW",
            "item_id": "MC01",
            "component": "MC_CORRECTNESS",
            "status": "CONDITIONAL_PROPOSAL",
            "maximum_points": "1",
            "proposed_points": "1",
            "known_points_lost": "0",
            "hold_reason": None,
        },
        {
            "row_id": "FICTIONAL_FRQ_ROW",
            "item_id": "FRQ01",
            "part_id": "a",
            "criterion_id": "FRQ01/a/c1",
            "component": "MASTERY",
            "status": "HELD",
            "maximum_points": "1",
            "proposed_points": None,
            "known_points_lost": None,
            "hold_reason": "FICTIONAL_UNREADABLE",
        },
    ]
    proposal = {
        "source_sha256": packet["source_sha256"],
        "literal_sha256": literal_ref["sha256"],
        "binding_qualification_sha256": qual_ref["sha256"],
        "rows": rows,
        "counts": {},
        "whole_test_grade": None,
        "whole_test_preview_computed": False,
        "whole_packet_complete": False,
        "teacher_accepted": False,
        "independent_student_QC": False,
    }
    rows[0]["citation"] = "fictional.mc.key:opaque"
    rows[1].update(
        citation="fictional.mastery.key:opaque", factor=None, reason="Fictional hold."
    )
    holds = {
        "source_sha256": packet["source_sha256"],
        "held_rows": [
            {
                "row_id": "FICTIONAL_FRQ_ROW",
                "item_id": "FRQ01",
                "part_id": "a",
                "reason": "FICTIONAL_UNREADABLE",
                "detail": "Fictional original unresolved observation.",
                "proposed_points": None,
            }
        ],
    }
    original_body = save(
        "original-body.txt",
        b"Fictional partial correction. Unreadable evidence remains held.\n",
    )
    body = save(
        "body.canonical-v2.txt",
        b"Fictional partial correction. Unreadable evidence remains held.",
    )
    lineage = {
        "original_path": original_body["path"],
        "original_sha256": original_body["sha256"],
        "canonical_path": body["path"],
        "canonical_sha256": body["sha256"],
        "independent_QC": False,
        "teacher_acceptance": False,
        "publication": False,
        "canonical_equals_original_without_single_terminal_LF": True,
    }
    inputs = {
        "STRICT-CAPTURE-CANDIDATE.private.json": strict_ref,
        "decisions.private.json": save(
            "decisions.json",
            {
                "FRQ01": {
                    "a": [
                        {
                            "factor": None,
                            "hold": "FICTIONAL_UNREADABLE",
                            "reason": "Fictional hold.",
                        }
                    ]
                }
            },
        ),
        "SCORING-BINDING-QUALIFICATION.private.json": qual_ref,
        "CONDITIONAL-PROPOSALS.private.json": save("proposals.json", proposal),
        "TEACHER-REVIEW-HOLDS.private.json": save("holds.json", holds),
        "CLEAN-STUDENT-FEEDBACK-BODY.canonical-v2.proposal.txt": body,
        "CANONICAL-V2-LINEAGE.private.json": save("lineage.json", lineage),
        "PRIVATE-FEEDBACK.private.json": save("feedback.json", {"feedback": []}),
        "CITATIONS.private.json": save(
            "citations.json",
            {
                "fictional.mc.key:opaque": {
                    "policy_json_pointer": "/forms/DEMO_A/items/MC01"
                },
                "fictional.mastery.key:opaque": {
                    "policy_json_pointer": "/forms/DEMO_A/items/FRQ01/criteria/0"
                },
            },
        ),
        "EXACT-ARITHMETIC.private.json": save("arithmetic.json", []),
    }
    page_images = []
    for n in range(1, 9):
        page = file_ref(store.root / "pages" / case["pages"] / f"page-{n:02d}.png")
        page_images.append(
            {
                "page_number": n,
                "prepared_image_path": page["path"],
                "prepared_image_sha256": page["sha256"],
                "source_sha256": packet["source_sha256"],
            }
        )
    provenance = save(
        "provenance.json",
        {
            "draft_sha256": strict_ref["sha256"],
            "draft_path": strict_ref["path"],
            "preparation": {"packet_id": packet["packet_id"]},
            "page_images": page_images,
        },
    )
    manifest = {
        "contract": "ORIGINAL_PACKET_SAVED_PROPOSALS_QC_ADVANCE_V1",
        "owner_thread_id": "FICTIONAL_ORIGINAL_OWNER",
        "source_sha256": packet["source_sha256"],
        "packet_key": packet["packet_id"],
        "form_id": packet["form_id"],
        "attempt": packet["attempt"],
        "current_head": file_ref(
            store.root / "state" / ("packet-" + packet["packet_id"] + ".json")
        ),
        "native_reading_key": case["head"]["reading_key"],
        "native_reading": file_ref(
            store.root / "readings" / case["head"]["reading_key"] / "reading.json"
        ),
        "native_packet": file_ref(
            store.root / "packets" / packet["packet_id"] / "packet.json"
        ),
        "academic_refs": list(authorities.values()),
        "inputs": inputs,
        "teacher_acceptance": False,
        "canvas_publication": False,
    }
    manifest_ref = save("manifest.json", manifest)

    def owner(**kw):
        return OriginalManualPartialOwner(
            manifest_ref,
            store.root,
            authorities,
            expected_original_owner="FICTIONAL_ORIGINAL_OWNER",
            prekey_freeze_ref=prekey,
            academic_freeze_ref=academic_freeze,
            reading_provenance_ref=provenance,
            native_source_ref=case["native_source_ref"],
            **kw,
        )

    return {
        **case,
        "owner": owner,
        "manifest": manifest,
        "manifest_ref": manifest_ref,
        "proposal": proposal,
        "holds": holds,
        "save": save,
        "authorities": authorities,
        "literal_ref": literal_ref,
        "strict_ref": strict_ref,
        "provenance": provenance,
    }


def test_original_exact_schema_real_readers_produce_partial_source(manual_case):
    case = manual_case
    owner = case["owner"]()
    before = {
        str(p): p.read_bytes() for p in case["store"].root.rglob("*") if p.is_file()
    }
    source = owner.verify_source()
    assert (
        source["body"]
        == "Fictional partial correction. Unreadable evidence remains held."
    )
    assert source["manual_context"]["native_context"] == {
        "result_key": None,
        "grade_preview": None,
        "holds": None,
    }
    assert source["manual_context"]["remaining_holds"] == case["holds"]["held_rows"]
    assert source["manual_context"]["actual_authored_body_version"] is None
    assert source["manual_context"]["review_state"] == {
        "status": "NOT_REVIEWED",
        "ref": None,
    }
    assert (
        source["source_pins"]["captured_raw_sha256"]
        != source["source_pins"]["literal_sha256"]
    )
    assert source["source_pins"]["reading_sha256"] != case["head"]["reading_key"]
    assert "result_sha256" not in source["source_pins"]
    assert owner.verification_receipt["target_or_designation_authenticated"] is False
    assert before == {
        str(p): p.read_bytes() for p in case["store"].root.rglob("*") if p.is_file()
    }


def test_missing_destination_is_explicit_not_an_authentic_source_stub(manual_case):
    owner = manual_case["owner"]()
    candidate = owner.prepare_candidate({"fictional_target": True})
    with pytest.raises(
        ManualSourceError, match="MANUAL_OWNER_DESTINATION_QUALIFICATION_NOT_CONFIGURED"
    ):
        owner.source_check(candidate, {}, {})
    with pytest.raises(
        ManualSourceError, match="MANUAL_NO_CURRENT_SUCCESSFUL_SOURCE_CHECK"
    ):
        _ = owner.verification_receipt


def test_source_mutation_after_prior_success_clears_receipt(manual_case):
    case = manual_case
    owner = case["owner"]()
    owner.verify_source()
    Path(case["manifest"]["inputs"]["decisions.private.json"]["path"]).write_bytes(
        b"CHANGED"
    )
    with pytest.raises(ManualSourceError):
        owner.verify_source()
    with pytest.raises(
        ManualSourceError, match="MANUAL_NO_CURRENT_SUCCESSFUL_SOURCE_CHECK"
    ):
        _ = owner.verification_receipt


def test_destination_callback_late_page_drift_is_rejected(manual_case):
    case = manual_case

    def changed_page(*_):
        page = case["store"].root / "pages" / case["pages"] / "page-08.png"
        page.write_bytes(b"LATE_FICTIONAL_CHANGE")

    owner = case["owner"](destination_check=changed_page)
    candidate = owner.prepare_candidate({"fictional_target": True})
    with pytest.raises(ValueError, match="STORED_HASH_MISMATCH"):
        owner.source_check(candidate, {}, {})
    with pytest.raises(
        ManualSourceError, match="MANUAL_NO_CURRENT_SUCCESSFUL_SOURCE_CHECK"
    ):
        _ = owner.verification_receipt


def rebind_document(case, role, value):
    case["manifest"]["inputs"][role] = case["save"]("replacement-" + role, value)
    case["manifest_ref"].update(case["save"]("manifest.json", case["manifest"]))


@pytest.mark.parametrize("status", ["HELD", "PROPOSED", "CONDITIONAL_PROPOSAL"])
def test_original_held_decision_cannot_be_promoted_by_rehashed_derivatives(
    manual_case, status
):
    case = manual_case
    decisions_ref = case["manifest"]["inputs"]["decisions.private.json"]
    original_decisions = Path(decisions_ref["path"]).read_bytes()
    proposal = copy.deepcopy(case["proposal"])
    proposal["rows"][1].update(
        status=status, proposed_points="1", known_points_lost="0"
    )
    if status == "PROPOSED":
        proposal["rows"][1]["hold_reason"] = None
    holds = copy.deepcopy(case["holds"])
    holds["held_rows"] = []
    rebind_document(case, "CONDITIONAL-PROPOSALS.private.json", proposal)
    rebind_document(case, "TEACHER-REVIEW-HOLDS.private.json", holds)
    assert Path(decisions_ref["path"]).read_bytes() == original_decisions
    with pytest.raises(ManualSourceError):
        case["owner"]().verify_source()


def decision_rows():
    def criterion(cid, part, component, maximum):
        return {
            "criterion_id": cid,
            "part_id": part,
            "component": component,
            "maximum_points": maximum,
            "allowed_points": ["0", maximum],
        }

    criteria = [
        criterion("Z-first", "a", "MASTERY", "1/2"),
        criterion("physical", "a", "ATTEMPT", "1/4"),
        criterion("B-other-part", "b", "MASTERY", "1/2"),
        criterion("A-second", "a", "MASTERY", "1/2"),
    ]
    spec = {
        "items": {
            "FRQ": {"maximum_points": "7/4", "criteria": criteria},
            "MC": {"maximum_points": "1"},
        }
    }
    decisions = {
        "FRQ": {
            "a": [
                {"factor": "1", "reason": "First supported."},
                {
                    "factor": None,
                    "hold": "ORIGINAL_SECOND_HOLD",
                    "reason": "Second unresolved.",
                },
            ],
            "b": [{"factor": "0", "reason": "Supported zero."}],
        }
    }
    rows = []
    for index, c in enumerate(criteria):
        held = c["criterion_id"] == "A-second"
        zero = c["criterion_id"] == "B-other-part"
        row = {
            **c,
            "item_id": "FRQ",
            "row_id": c["criterion_id"],
            "citation": "opaque.key:" + str(index),
            "status": "HELD" if held else "CONDITIONAL_PROPOSAL",
            "proposed_points": None if held else "0" if zero else c["maximum_points"],
            "known_points_lost": None if held else c["maximum_points"] if zero else "0",
            "hold_reason": "ORIGINAL_SECOND_HOLD" if held else None,
            "reason": "Second unresolved."
            if held
            else "Supported zero."
            if zero
            else "Physical marks."
            if c["component"] == "ATTEMPT"
            else "First supported.",
        }
        if c["component"] == "MASTERY":
            row["factor"] = None if held else "0" if zero else "1"
        rows.append(row)
    rows.append(
        {
            "row_id": "MC",
            "item_id": "MC",
            "component": "MC_CORRECTNESS",
            "maximum_points": "1",
            "status": "CONDITIONAL_PROPOSAL",
            "proposed_points": "1",
            "known_points_lost": "0",
            "hold_reason": None,
            "citation": "opaque.mc.key",
        }
    )
    citations = {
        "opaque.key:" + str(i): {
            "policy_json_pointer": "/forms/FICTIONAL/items/FRQ/criteria/" + str(i)
        }
        for i in range(4)
    }
    citations["opaque.mc.key"] = {"policy_json_pointer": "/forms/FICTIONAL/items/MC"}
    holds = {
        "held_rows": [
            {
                "row_id": "A-second",
                "item_id": "FRQ",
                "proposed_points": None,
                "reason": "ORIGINAL_SECOND_HOLD",
            }
        ]
    }
    return {
        "proposal": {"rows": rows},
        "holds": holds,
        "spec": spec,
        "decisions": decisions,
        "citation_entries": citations,
        "form_id": "FICTIONAL",
    }


def test_exact_decision_order_excludes_attempt_and_other_parts_without_sorting():
    case = decision_rows()
    # Reverse derived rows: each original criterion citation, not row order,
    # still identifies its decision and the supported zero remains numeric.
    case["proposal"]["rows"].reverse()
    OriginalManualPartialOwner._rows(**case)


def test_swapped_held_criteria_cannot_pass_by_equal_null_count():
    case = decision_rows()
    first, held = case["proposal"]["rows"][0], case["proposal"]["rows"][3]
    first.update(
        status="HELD",
        factor=None,
        proposed_points=None,
        known_points_lost=None,
        hold_reason="ORIGINAL_SECOND_HOLD",
    )
    held.update(
        status="CONDITIONAL_PROPOSAL",
        factor="1",
        proposed_points="1/2",
        known_points_lost="0",
        hold_reason=None,
    )
    case["holds"]["held_rows"][0]["row_id"] = first["row_id"]
    with pytest.raises(ManualSourceError):
        OriginalManualPartialOwner._rows(**case)


def test_original_decision_permutation_is_not_a_new_order_authority():
    case = decision_rows()
    case["decisions"]["FRQ"]["a"].reverse()
    with pytest.raises(ManualSourceError):
        OriginalManualPartialOwner._rows(**case)


@pytest.mark.parametrize("suffix", ["1", "2", "4", "03", "-1", "-"])
def test_unfiltered_criterion_citation_index_must_select_exact_identity(suffix):
    case = decision_rows()
    case["citation_entries"]["opaque.key:3"]["policy_json_pointer"] = (
        "/forms/FICTIONAL/items/FRQ/criteria/" + suffix
    )
    with pytest.raises(ManualSourceError):
        OriginalManualPartialOwner._rows(**case)


@pytest.mark.parametrize(
    "pointer",
    [
        "#/forms/FICTIONAL/items/FRQ/criteria/3",
        "/forms/OTHER/items/FRQ/criteria/3",
        "/forms/FICTIONAL/items/OTHER/criteria/3",
    ],
)
def test_citation_does_not_escape_form_item_or_literal_pointer_scope(pointer):
    case = decision_rows()
    case["citation_entries"]["opaque.key:3"]["policy_json_pointer"] = pointer
    with pytest.raises(ManualSourceError):
        OriginalManualPartialOwner._rows(**case)


@pytest.mark.parametrize("key", [" opaque.key:3", "opaque.key:3 ", "opaque.key"])
def test_citation_lookup_uses_exact_opaque_key_without_trim_or_dotpath(key):
    case = decision_rows()
    case["proposal"]["rows"][3]["citation"] = key
    with pytest.raises(ManualSourceError, match="MANUAL_EXACT_CITATION_KEY_REQUIRED"):
        OriginalManualPartialOwner._rows(**case)


def test_original_held_decision_row_cannot_be_omitted():
    case = decision_rows()
    case["proposal"]["rows"] = [
        r for r in case["proposal"]["rows"] if r["row_id"] != "A-second"
    ]
    case["holds"]["held_rows"] = []
    with pytest.raises(ManualSourceError, match="MANUAL_ORIGINAL_DECISION_ROW_OMITTED"):
        OriginalManualPartialOwner._rows(**case)


@pytest.mark.parametrize(
    "field,value",
    [("reason", "Changed reason."), ("hold_reason", "Changed hold."), ("factor", "0")],
)
def test_exact_original_held_reason_and_null_factor_preserved(field, value):
    case = decision_rows()
    case["proposal"]["rows"][3][field] = value
    with pytest.raises(ManualSourceError):
        OriginalManualPartialOwner._rows(**case)


def test_mc_and_attempt_have_no_mastery_factor_or_decision_slot():
    case = decision_rows()
    assert "factor" not in case["proposal"]["rows"][1]
    assert "factor" not in case["proposal"]["rows"][4]
    OriginalManualPartialOwner._rows(**case)


@pytest.mark.parametrize("form_id,token", [("F/~A", "F~1~0A"), ("F~1A", "F~01A")])
def test_policy_pointer_tokens_unescape_once_in_required_order(form_id, token):
    case = decision_rows()
    row = case["proposal"]["rows"][3]
    citation = {"policy_json_pointer": "/forms/" + token + "/items/FRQ/criteria/3"}
    assert (
        OriginalManualPartialOwner._citation_target(
            citation, row, case["spec"], form_id
        )["criterion_id"]
        == "A-second"
    )


def test_missing_actual_decisions_never_uses_fictitious_root_judgment_ref(manual_case):
    case = manual_case
    case["manifest"]["judgment_ref"] = case["manifest"]["inputs"].pop(
        "decisions.private.json"
    )
    case["manifest_ref"].update(case["save"]("manifest.json", case["manifest"]))
    with pytest.raises(ManualSourceError, match="MANUAL_ORIGINAL_INPUT_SLOT_MISSING"):
        case["owner"]().verify_source()


def test_native_record_key_cannot_replace_raw_byte_hash(manual_case):
    case = manual_case
    role = "SCORING-BINDING-QUALIFICATION.private.json"
    qualification = json.loads(
        Path(case["manifest"]["inputs"][role]["path"]).read_bytes()
    )
    qualification["qualified_capture_candidate_sha256"] = case["head"]["reading_key"]
    rebind_document(case, role, qualification)
    with pytest.raises(
        ManualSourceError, match="MANUAL_ACADEMIC_QUALIFICATION_BINDING_MISMATCH"
    ):
        case["owner"]().verify_source()


def test_coherently_rehashed_wrong_hold_ledger_is_rejected(manual_case):
    case = manual_case
    holds = copy.deepcopy(case["holds"])
    holds["held_rows"] = []
    rebind_document(case, "TEACHER-REVIEW-HOLDS.private.json", holds)
    with pytest.raises(ManualSourceError, match="MANUAL_ORIGINAL_HOLD_SET_MISMATCH"):
        case["owner"]().verify_source()


def test_component_deduction_checked_without_computing_whole_total(manual_case):
    case = manual_case
    proposal = copy.deepcopy(case["proposal"])
    proposal["rows"][0]["known_points_lost"] = "1/3"
    rebind_document(case, "CONDITIONAL-PROPOSALS.private.json", proposal)
    with pytest.raises(
        ManualSourceError, match="MANUAL_SAVED_COMPONENT_ARITHMETIC_MISMATCH"
    ):
        case["owner"]().verify_source()


def test_later_review_not_relabelled_as_native_or_canonical_clearance(manual_case):
    case = manual_case
    review = case["save"](
        "fictional-separate-review.json",
        {"contract": "FICTIONAL_SOURCE_REVIEW", "component_dispositions": []},
    )
    owner = case["owner"](review_ref=review)
    source = owner.verify_source()
    assert source["manual_context"]["review_state"] == {
        "status": "UNKNOWN",
        "ref": None,
    }
    assert owner.verification_receipt["separate_review_provenance_ref"] == review
    assert source["manual_context"]["native_context"]["result_key"] is None


def test_separate_historical_draft_requires_actual_unchanged_copy(manual_case):
    case = manual_case
    provenance = json.loads(Path(case["provenance"]["path"]).read_bytes())
    provenance.update(
        draft_path=case["literal_ref"]["path"],
        draft_sha256=case["literal_ref"]["sha256"],
    )
    Path(case["provenance"]["path"]).write_bytes(case["pipeline"].canonical(provenance))
    case["provenance"].update(file_ref(Path(case["provenance"]["path"])))
    owner = case["owner"]()
    with pytest.raises(
        ManualSourceError, match="MANUAL_CAPTURE_DRAFT_UNCHANGED_COPY_REQUIRED"
    ):
        owner.verify_source()
    with pytest.raises(
        ManualSourceError, match="MANUAL_NO_CURRENT_SUCCESSFUL_SOURCE_CHECK"
    ):
        _ = owner.verification_receipt


def test_separate_historical_draft_locator_preserved_when_exact_bytes_match(
    manual_case,
):
    case = manual_case
    copied = case["save"](
        "earlier-draft.json", Path(case["strict_ref"]["path"]).read_bytes()
    )
    provenance = json.loads(Path(case["provenance"]["path"]).read_bytes())
    provenance.update(draft_path=copied["path"], draft_sha256=copied["sha256"])
    Path(case["provenance"]["path"]).write_bytes(case["pipeline"].canonical(provenance))
    case["provenance"].update(file_ref(Path(case["provenance"]["path"])))
    owner = case["owner"]()
    owner.verify_source()
    proof = owner.verification_receipt
    assert proof["capture_draft_ref"] == copied
    assert proof["captured_raw_ref"] == case["strict_ref"]
    assert proof["capture_draft_ref"]["path"] != proof["captured_raw_ref"]["path"]


def test_real_owner_checker_and_installed_note_consumer_compose(manual_case, scenario):
    case = manual_case
    scenario["identity_binding"]["pin"] = case["packet"]["pin"]
    expected_target = copy.deepcopy(scenario["target"])
    expected_identity = copy.deepcopy(scenario["identity_binding"])
    calls = []

    def fictional_destination_checker(candidate, target, identity):
        # Fictional target seam only; the source verification under test uses
        # actual native record readers and the exact original-manifest shape.
        assert target == expected_target == candidate["target"]
        assert identity == expected_identity
        assert identity["pin"] == case["packet"]["pin"]
        calls.append("qualified fictional destination")

    owner = case["owner"](destination_check=fictional_destination_checker)
    kwargs = {
        k: scenario[k]
        for k in ("target", "raw", "binding", "identity_binding", "authorization")
    }
    original = copy.deepcopy(kwargs["raw"])
    plan = owner.prepare_note(**kwargs)
    assert kwargs["raw"] == original
    assert calls == ["qualified fictional destination"]
    assert plan["numeric_grade_disposition"] == "UNCHANGED"
    assert plan["teacher_accepted"] is False
    assert plan["publication_allowed"] is False
    assert plan["canvas_requests"] == []
    assert plan["requests"][0]["updateCells"]["fields"] == "note"
    kwargs["raw"] = applied(plan)
    repeat = owner.prepare_note(**kwargs)
    assert repeat["status"] == "NO_CHANGE"
    assert repeat["requests"] == []


def test_unconfigured_real_destination_stops_consumer_before_any_plan(
    manual_case, scenario
):
    owner = manual_case["owner"]()
    kwargs = {
        k: scenario[k]
        for k in ("target", "raw", "binding", "identity_binding", "authorization")
    }
    with pytest.raises(GradebookError, match="UNIT2_SOURCE_QUALIFICATION_REQUIRED"):
        owner.prepare_note(**kwargs)
    with pytest.raises(
        ManualSourceError, match="MANUAL_NO_CURRENT_SUCCESSFUL_SOURCE_CHECK"
    ):
        _ = owner.verification_receipt


@pytest.mark.parametrize("kind", ["RuntimeError", "ValueError"])
def test_native_reader_private_initialization_error_is_fixed_and_redacted(
    tmp_path, kind
):
    path = tmp_path / "fictional_reader.py"
    path.write_text(
        f"raise {kind}('FICTIONAL_PRIVATE_NATIVE_SENTINEL')\n", encoding="utf-8"
    )
    with pytest.raises(
        ManualSourceError, match="NATIVE_READER_INITIALIZATION_FAILED"
    ) as held:
        native_runtime(file_ref(path))
    assert "FICTIONAL_PRIVATE_NATIVE_SENTINEL" not in str(held.value)
    assert held.value.__suppress_context__ is True
