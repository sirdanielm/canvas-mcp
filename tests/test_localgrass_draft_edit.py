"""Draft receiving uses the actual participation planner with fictional rows."""

import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest
from test_gradebook import snapshot as snapshot
from test_gradebook_native import binding as binding
from test_gradebook_native import initial_raw, raw_from_state

from canvas_mcp.gradebook import native
from canvas_mcp.gradebook.client import GradebookError
from canvas_mcp.gradebook.localgrass_draft_edit import LocalGrAssDraftEditConnection
from canvas_mcp.gradebook.model import digest
from canvas_mcp.gradebook.store import Store

STAGE_SOURCE = os.environ.get("LOCALGRASS_PARTICIPATION_STAGE_SOURCE")
STAGE_PATH = Path(STAGE_SOURCE) if STAGE_SOURCE else None
STAGE_SHA256 = os.environ.get("LOCALGRASS_PARTICIPATION_STAGE_SHA256")
FILES_SHA256 = os.environ.get("LOCALGRASS_PARTICIPATION_FILES_SHA256")


def _verify_source_pin(path, expected):
    if not expected or hashlib.sha256(path.read_bytes()).hexdigest() != expected:
        pytest.fail("Explicit reviewed LocalGrAss source SHA256 required or changed")


@pytest.fixture
def case(tmp_path, snapshot, binding, monkeypatch):
    if STAGE_PATH is None:
        pytest.skip(
            "Explicit source and SHA256 required for native LocalGrAss integration"
        )
    assert STAGE_PATH.is_absolute() and STAGE_PATH.is_file()
    _verify_source_pin(STAGE_PATH, STAGE_SHA256)
    _verify_source_pin(STAGE_PATH.parent / "grading_chains.py", FILES_SHA256)
    spec = importlib.util.spec_from_file_location(
        "qualified_participation_fixture", STAGE_PATH
    )
    stage = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(stage)
    snapshot["course_workflow_state"] = "available"
    snapshot["cells"]["101:21"].update(
        attempt=3,
        submitted_at="2026-10-17T00:00:00Z",
        excused=False,
        grade_matches_current_submission=True,
    )
    pins = {
        "registry_sha256": "1" * 64,
        "roster_sha256": "2" * 64,
        "by_pin": {"0042": "101"},
    }
    proposal = {
        "record_ref": "a" * 64,
        "revision_ref": "b" * 64,
        "evaluation_ref": "c" * 64,
        "report_digest": "d" * 64,
        "queue_digest": "e" * 64,
        "policy_sha256": "f" * 64,
        "source_basis_sha256": "3" * 64,
        "student_pin": "0042",
        "assignment_key": "fictional-work",
        "source_target": "fictional-fleet",
        "student_track": "core",
        "band": "FULL",
        "ratio": 1,
        "retained_teacher_owned_score_present": False,
        "retained_teacher_owned_feedback_present": False,
        "confidence": "HIGH",
        "holds": [],
        "semantic_evidence_state": "SOURCE_BOUND_CONFIRMED",
        "evidence_sha256": ["4" * 64],
    }
    report = {
        "report_digest": "d" * 64,
        "queue_digest": "e" * 64,
        "student_registry_sha256": "1" * 64,
        "policy": {
            "contract": "LOCAL_PARTICIPATION_POLICY_V2",
            "state": "TEACHER_AUTHORIZED_REQUIRES_REVIEW",
            "user_decision_ref": "fictional-policy-approval",
        },
        "records": [{"private_analysis": "Retain full fictional analysis."}],
        "created_at": "first",
    }
    state = {"report": report, "proposals": [proposal]}
    stage.fixture_source_calls = []

    def read_workspace(path):
        stage.fixture_source_calls.append(path)
        return copy.deepcopy(state["report"]), copy.deepcopy(state["proposals"])

    monkeypatch.setattr(stage, "workspace_proposals", read_workspace)
    files_spec = importlib.util.spec_from_file_location(
        "existing_fixture_files", STAGE_PATH.parent / "grading_chains.py"
    )
    files = importlib.util.module_from_spec(files_spec)
    files_spec.loader.exec_module(files)
    assignments = tmp_path / "assignments.json"
    assignments.write_text(
        json.dumps(
            [
                {
                    "assignment_key": "fictional-work",
                    "source_target": "fictional-fleet",
                    "student_track": "core",
                    "course_id": "12",
                    "assignment_id": "21",
                    "maximum": 20,
                    "provider": "sdmGrAss",
                    "excluded": False,
                }
            ]
        )
    , encoding="utf-8")
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    args = {
        "workspace": workspace,
        "canvas_store": Store(tmp_path / "canvas"),
        "stage_module": stage,
        "expected_stage_sha256": files.file_sha(STAGE_PATH),
        "canvas_repo": Path(__file__).resolve().parents[1],
        "files": files,
        "assignment_bindings_path": assignments,
        "expected_assignment_bindings_sha256": files.file_sha(assignments),
        "registry_path": tmp_path / "registry.json",
        "selected_record_refs": (proposal["record_ref"],),
    }
    connection = LocalGrAssDraftEditConnection(**args)
    context = {
        "raw": initial_raw(snapshot, binding),
        "binding": binding,
        "baseline": snapshot,
        "current": copy.deepcopy(snapshot),
        "pin_binding": pins,
    }
    metadata = {
        "id": 21,
        "course_id": 12,
        "submission_types": ["online_upload"],
        "external_tool_tag_attributes": None,
    }
    context["current"]["assignments"][0].update(
        assignment_metadata=metadata, assignment_metadata_sha256=digest(metadata)
    )
    return connection, context, state, args


def test_draft_stage_uses_canonical_participation_policy_and_retains_report(case):
    c, ctx, source, _ = case
    plan = c.prepare(**ctx)
    assert plan["contract"] == "LOCALGRASS_UNAPPROVED_PARTICIPATION_EDIT_V1"
    assert (
        plan["source_lane"] == "SDMGRASS_FORMATIVE"
        and plan["delivery_policy"] == "SCORE_ONLY"
    )
    assert plan["source_report"] == source["report"]
    assert plan["transfer"]["proposals"] == source["proposals"]
    assert plan["transfer"]["items"][0]["points"] == 20
    assert "UNAPPROVED" in plan["transfer"]["items"][0]["cell"]["note"]
    assert plan["teacher_approval"] is plan["publication_allowed"] is False
    assert (
        plan["score_delivery_authorized"]
        is plan["comment_delivery_authorized"]
        is False
    )
    assert "decision" not in plan and "is_final" not in json.dumps(plan)
    c.revalidate(
        plan,
        expected_plan_sha256=digest(plan),
        raw=ctx["raw"],
        current=ctx["current"],
        pin_binding=ctx["pin_binding"],
    )


def test_changed_source_and_module_pin_hold_revalidation(case):
    c, ctx, state, _ = case
    plan = c.prepare(**ctx)
    state["proposals"][0]["evaluation_ref"] = "5" * 64
    with pytest.raises(GradebookError, match="PARTICIPATION_SOURCE_CHANGED"):
        c.revalidate(
            plan,
            expected_plan_sha256=digest(plan),
            raw=ctx["raw"],
            current=ctx["current"],
            pin_binding=ctx["pin_binding"],
        )
    c.stage_sha256 = "0" * 64
    with pytest.raises(GradebookError, match="PARTICIPATION_SOURCE_PIN_CHANGED"):
        c.prepare(**ctx)


def test_readback_needs_no_source_or_module_file_access(case, monkeypatch):
    c, ctx, _, _ = case
    plan = c.prepare(**ctx)
    state = native._state(ctx["raw"])
    native._apply_requests(state, plan["transfer"]["requests"], ctx["binding"])
    monkeypatch.setattr(
        c.stage,
        "workspace_proposals",
        lambda _: (_ for _ in ()).throw(AssertionError("source unavailable")),
    )
    c.stage_sha256 = "0" * 64
    assert (
        c.classify(plan, raw_from_state(state), expected_plan_sha256=digest(plan))[
            "status"
        ]
        == "PLANNED_OUTPUT_OBSERVED"
    )
    assert (
        c.classify(plan, ctx["raw"], expected_plan_sha256=digest(plan))["status"]
        == "BEFORE_STILL_PRESENT"
    )


def test_volatile_report_time_does_not_change_saved_source_identity(case):
    c, ctx, state, _ = case
    plan = c.prepare(**ctx)
    state["report"]["created_at"] = "later"
    c.revalidate(
        plan,
        expected_plan_sha256=digest(plan),
        raw=ctx["raw"],
        current=ctx["current"],
        pin_binding=ctx["pin_binding"],
    )


@pytest.mark.parametrize(
    "change", ["analytical", "assignment", "pin", "attempt", "teacher_note"]
)
def test_real_existing_policy_and_destination_holds_remain(case, change):
    c, ctx, state, args = case
    if change == "analytical":
        state["report"]["policy"]["contract"] = "NATIVE_ACADEMIC_RAW_IDENTITY"
        with pytest.raises(GradebookError, match="PARTICIPATION_POLICY_REQUIRED"):
            c.prepare(**ctx)
        return
    if change == "assignment":
        args["assignment_bindings_path"].write_text("[]", encoding="utf-8")
        with pytest.raises(GradebookError, match="ASSIGNMENT_BINDINGS_CHANGED"):
            c.prepare(**ctx)
        return
    if change == "pin":
        ctx["pin_binding"]["registry_sha256"] = "9" * 64
    elif change == "attempt":
        ctx["current"]["cells"]["101:21"]["attempt"] = 4
    else:
        ctx["raw"]["sheets"][1]["data"][0]["rowData"][5]["values"][2][
            "note"
        ] = "Existing teacher-owned feedback"
    if change == "pin":
        with pytest.raises(GradebookError, match="PARTICIPATION_PIN_AUTHORITY_CHANGED"):
            c.prepare(**ctx)
    else:
        plan = c.prepare(**ctx)
        assert plan["transfer"]["requests"] == [] and plan["transfer"]["holds"]


@pytest.fixture
def draft_case(case):
    """Shared real-planner fixture for owner/publisher composition tests."""
    connection, context, source_state, args = case
    return SimpleNamespace(
        connection=connection,
        context=context,
        source_state=source_state,
        source_workspace=connection.workspace,
        assignment_path=connection.assignment_path,
        stage_module=connection.stage,
        files=connection.files,
        source_calls=connection.stage.fixture_source_calls,
        constructor_args=args,
    )


@pytest.mark.parametrize(
    "field,value,code",
    [
        (
            "external_tool_tag_attributes",
            {"url": "https://edpuzzle.com/fictional"},
            "EXCLUDED_PROVIDER",
        ),
        ("submission_types", ["external_tool"], "EXTERNAL_TOOL_REVIEW_REQUIRED"),
    ],
)
def test_draft_rejects_actual_assignment_external_tool_metadata(
    case, field, value, code
):
    connection, context, _, _ = case
    assignment = context["current"]["assignments"][0]
    metadata = assignment["assignment_metadata"]
    metadata[field] = value
    assignment["assignment_metadata_sha256"] = digest(metadata)
    with pytest.raises(GradebookError, match=code):
        connection.prepare(**context)


def test_draft_requires_explicit_provider_exclusion_and_raw_assignment_detail(case):
    connection, context, _, args = case
    context["current"]["assignments"][0].pop("assignment_metadata")
    with pytest.raises(GradebookError, match="ASSIGNMENT_METADATA_REQUIRED"):
        connection.prepare(**context)


def test_assignment_targets_are_exact_fresh_source_membership(case):
    connection, context, source, _ = case
    assert connection.assignment_targets(
        course_id="12", pin_binding=context["pin_binding"]
    ) == ["21"]
    source["proposals"] = []
    with pytest.raises(GradebookError, match="PARTICIPATION_SOURCE_CHANGED"):
        connection.assignment_targets(
            course_id="12", pin_binding=context["pin_binding"]
        )


@pytest.mark.parametrize(
    "field,code",
    [("provider", "ASSIGNMENT_PROVIDER_REQUIRED"), ("excluded", "EXCLUDED_PROVIDER")],
)
def test_central_provider_and_exclusion_are_required_not_invented(case, field, code):
    connection, context, _, args = case
    path = args["assignment_bindings_path"]
    entries = json.loads(path.read_text(encoding="utf-8"))
    entries[0].pop(field)
    path.write_text(json.dumps(entries), encoding="utf-8")
    connection.assignment_sha256 = connection.files.file_sha(path)
    with pytest.raises(GradebookError, match=code):
        connection.prepare(**context)


def test_changed_actual_assignment_detail_revokes_draft_preflight(case):
    connection, context, _, _ = case
    plan = connection.prepare(**context)
    assignment = context["current"]["assignments"][0]
    assignment["assignment_metadata"]["description"] = "Changed exact assignment detail"
    assignment["assignment_metadata_sha256"] = digest(assignment["assignment_metadata"])
    with pytest.raises(GradebookError, match="EXACT_TRANSFER_PLAN_CHANGED"):
        connection.revalidate(
            plan,
            expected_plan_sha256=digest(plan),
            raw=context["raw"],
            current=context["current"],
            pin_binding=context["pin_binding"],
        )


def google_draft_case(case):
    """Pin a truthful, exact-case fictional Google Assignments draft review."""
    connection, context, source, args = case
    assignment = context["current"]["assignments"][0]
    metadata = assignment["assignment_metadata"]
    metadata.update(
        submission_types=["external_tool"],
        external_tool_tag_attributes={
            "url": "https://assignments.google.com/lti/a/fictional-case"
        },
    )
    assignment["assignment_metadata_sha256"] = digest(metadata)
    proposal = source["proposals"][0]
    review = {
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
    review.update(
        contract="CANVAS_GOOGLE_ASSIGNMENTS_DRAFT_REVIEW_V1",
        provider="GOOGLE_ASSIGNMENTS",
        source_provider="sdmGrAss",
        origin=context["current"]["origin"],
        course_id="12",
        assignment_id="21",
        assignment_metadata_sha256=digest(metadata),
        review_ref="6" * 64,
        scope="LOCAL_UNAPPROVED_EDIT_ONLY",
        source_lane="SDMGRASS_FORMATIVE",
        delivery_policy="SCORE_ONLY",
        publication_allowed=False,
    )
    path = args["assignment_bindings_path"]
    rows = json.loads(path.read_text(encoding="utf-8"))
    rows[0]["external_tool_draft_review"] = review
    path.write_text(json.dumps(rows), encoding="utf-8")
    connection.assignment_sha256 = connection.files.file_sha(path)
    return case, rows, review


def test_exact_google_assignments_case_can_stage_unapproved_without_metadata_rewrite(
    case,
):
    case, _, _ = google_draft_case(case)
    connection, context, _, _ = case
    before = copy.deepcopy(context["current"]["assignments"][0]["assignment_metadata"])
    plan = connection.prepare(**context)
    assert plan["items"] == [{"key": "101:21"}]
    assert plan["review_state"] == "UNAPPROVED" and plan["publication_allowed"] is False
    assert (
        plan["delivery_policy"] == "SCORE_ONLY"
        and plan["comment_delivery_authorized"] is False
    )
    assert context["current"]["assignments"][0]["assignment_metadata"] == before
    assert (
        plan["transfer"]["current_basis"]["targets"][0]["assignment"][
            "assignment_metadata"
        ]
        == before
    )


def persist_google_review(case, rows):
    connection, _, _, args = case
    path = args["assignment_bindings_path"]
    path.write_text(json.dumps(rows), encoding="utf-8")
    connection.assignment_sha256 = connection.files.file_sha(path)


@pytest.mark.parametrize(
    "field,value",
    [
        ("revision_ref", "7" * 64),
        ("record_ref", "8" * 64),
        ("queue_digest", "9" * 64),
        ("source_provider", "OTHER_SOURCE"),
        ("source_target", "different-fleet"),
        ("assignment_metadata_sha256", "0" * 64),
        ("provider", "OTHER_LTI"),
        ("delivery_policy", "SCORE_AND_FEEDBACK"),
        ("publication_allowed", True),
    ],
)
def test_google_review_does_not_admit_other_case_metadata_source_or_channel(
    case, field, value
):
    case, rows, review = google_draft_case(case)
    review[field] = value
    persist_google_review(case, rows)
    connection, context, _, _ = case
    with pytest.raises(
        GradebookError, match="GOOGLE_ASSIGNMENTS_DRAFT_REVIEW_REQUIRED"
    ):
        connection.prepare(**context)


@pytest.mark.parametrize(
    "url",
    [
        "https://assignments.google.com.attacker.invalid/lti/a/fictional",
        "http://assignments.google.com/lti/a/fictional",
        "https://user:pass@assignments.google.com/lti/a/fictional",
        "https://assignments.google.com:444/lti/a/fictional",
        "https://assignments.google.com/unreviewed/fictional",
    ],
)
def test_google_review_keeps_exact_reviewed_provider_url_family(case, url):
    case, rows, review = google_draft_case(case)
    connection, context, _, _ = case
    assignment = context["current"]["assignments"][0]
    metadata = assignment["assignment_metadata"]
    metadata["external_tool_tag_attributes"]["url"] = url
    assignment["assignment_metadata_sha256"] = digest(metadata)
    review["assignment_metadata_sha256"] = digest(metadata)
    persist_google_review(case, rows)
    with pytest.raises(
        GradebookError, match="GOOGLE_ASSIGNMENTS_DRAFT_REVIEW_REQUIRED"
    ):
        connection.prepare(**context)


def test_google_permit_never_overrides_edpuzzle_exclusion(case):
    case, rows, review = google_draft_case(case)
    connection, context, _, _ = case
    assignment = context["current"]["assignments"][0]
    metadata = assignment["assignment_metadata"]
    metadata["external_tool_tag_attributes"][
        "url"
    ] = "https://edpuzzle.com/lti/a/fictional"
    assignment["assignment_metadata_sha256"] = digest(metadata)
    review["assignment_metadata_sha256"] = digest(metadata)
    persist_google_review(case, rows)
    with pytest.raises(GradebookError, match="EXCLUDED_PROVIDER"):
        connection.prepare(**context)


def test_google_review_is_bound_to_each_proposal_not_any_shared_assignment_case(case):
    case, _, _ = google_draft_case(case)
    connection, context, source, _ = case
    other = copy.deepcopy(source["proposals"][0])
    other["record_ref"] = "8" * 64
    source["proposals"].append(other)
    connection.selected_record_refs = (
        source["proposals"][0]["record_ref"],
        other["record_ref"],
    )
    with pytest.raises(
        GradebookError, match="GOOGLE_ASSIGNMENTS_DRAFT_REVIEW_REQUIRED"
    ):
        connection.prepare(**context)


READER_STAGE_SOURCE = os.environ.get("LOCALGRASS_READER_STAGE_SOURCE")
READER_STAGE_PATH = Path(READER_STAGE_SOURCE) if READER_STAGE_SOURCE else None
READER_STAGE_SHA256 = os.environ.get("LOCALGRASS_READER_STAGE_SHA256")


@pytest.fixture
def reader_case(case, tmp_path, monkeypatch):
    """Mock only source reconstruction; real qualified reader-row planner executes."""
    if READER_STAGE_PATH is None:
        pytest.skip("Explicit source and SHA256 required for native reader integration")
    assert READER_STAGE_PATH.is_absolute() and READER_STAGE_PATH.is_file()
    _verify_source_pin(READER_STAGE_PATH, READER_STAGE_SHA256)
    _, context, source, args = case
    spec = importlib.util.spec_from_file_location(
        "qualified_reader_stage_fixture", READER_STAGE_PATH
    )
    stage = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(stage)
    artifact = tmp_path / "fictional-reader.txt"
    artifact.write_text(
        "Fictional reader observations tied to retained image evidence."
    , encoding="utf-8")
    bundle = tmp_path / "fictional-reader-bundle.json"
    bundle.write_text(
        json.dumps(
            {"contract": "PARTICIPATION_VISUAL_READER_BUNDLE_V1", "fictional": True}
        )
    , encoding="utf-8")
    artifact_pin = hashlib.sha256(artifact.read_bytes()).hexdigest()
    bundle_pin = hashlib.sha256(bundle.read_bytes()).hexdigest()
    policy_pin = digest(source["report"]["policy"])
    provenance = {
        "kind": "ASSISTANT_VISUAL_ADVISORY",
        "reader_ref": "fictional-reader-run",
        "artifact_path": str(artifact),
        "artifact_sha256": artifact_pin,
        "original_sha256": source["proposals"][0]["evidence_sha256"],
        "template_sha256": ["5" * 64],
        "citation_frame": "EXIF_ORIENTED_TOP_LEFT",
    }
    row = copy.deepcopy(source["proposals"][0])
    row.update(
        confidence="READER_ADVISORY",
        semantic_evidence_state="SOURCE_BOUND_READER_ADVISORY",
        reader_bundle_sha256=bundle_pin,
        reader_artifact_sha256=artifact_pin,
        reader_request_ref="6" * 64,
        reader_reply_sha256="7" * 64,
        reader_advisory_ref="8" * 64,
        reader_provenance=provenance,
        reader_provenance_sha256=digest(provenance),
        reader_template_sha256=["5" * 64],
        reader_question_observations={"Q1": "ATTEMPT_CONFIRMED"},
        native_question_observations={"Q1": "UNCERTAIN"},
        policy_sha256=policy_pin,
        teacher_approval=False,
        publication_allowed=False,
    )
    source["proposals"] = [row]
    source["report"]["records"] = [
        {"status": "UNRESOLVED", "question_observations": {"Q1": "UNCERTAIN"}}
    ]
    calls = []

    def reconstruct(workspace, path, **pins):
        calls.append({"workspace": workspace, "path": path, **pins})
        if (
            hashlib.sha256(Path(path).read_bytes()).hexdigest()
            != pins["expected_bundle_sha256"]
        ):
            raise stage.StageHold("READER_BUNDLE_CHANGED")
        if (
            hashlib.sha256(artifact.read_bytes()).hexdigest()
            != pins["expected_reader_artifact_sha256"]
        ):
            raise stage.StageHold("READER_ARTIFACT_CHANGED")
        if digest(source["report"]["policy"]) != pins["expected_policy_sha256"]:
            raise stage.StageHold("CURRENT_POLICY_BINDING_CHANGED")
        return copy.deepcopy(source["report"]), copy.deepcopy(source["proposals"])

    monkeypatch.setattr(stage, "workspace_reader_proposals", reconstruct)
    monkeypatch.setattr(
        stage,
        "workspace_proposals",
        lambda _: (_ for _ in ()).throw(AssertionError("No reader fallback")),
    )
    reader_kwargs = {
        "reader_bundle_path": bundle,
        "expected_reader_bundle_sha256": bundle_pin,
        "expected_policy_sha256": policy_pin,
        "expected_reader_artifact_sha256": artifact_pin,
    }
    args = {
        **args,
        "stage_module": stage,
        "expected_stage_sha256": hashlib.sha256(
            READER_STAGE_PATH.read_bytes()
        ).hexdigest(),
        **reader_kwargs,
    }
    connection = LocalGrAssDraftEditConnection(**args)
    return SimpleNamespace(
        connection=connection,
        context=context,
        source_state=source,
        source_workspace=connection.workspace,
        assignment_path=connection.assignment_path,
        stage_module=stage,
        files=connection.files,
        source_calls=calls,
        constructor_args=args,
        reader_kwargs=reader_kwargs,
        reader_artifact=artifact,
    )


def test_explicit_reader_opt_in_retains_advisory_confidence_and_native_unresolved(
    reader_case,
):
    c = reader_case
    plan = c.connection.prepare(**c.context)
    row = plan["transfer"]["proposals"][0]
    assert row["confidence"] == "READER_ADVISORY"
    assert row["semantic_evidence_state"] == "SOURCE_BOUND_READER_ADVISORY"
    assert row["native_question_observations"] == {"Q1": "UNCERTAIN"}
    assert plan["source_report"]["records"][0]["status"] == "UNRESOLVED"
    assert plan["teacher_approval"] is plan["publication_allowed"] is False
    assert (
        plan["reader_binding"]["bundle_sha256"]
        == c.reader_kwargs["expected_reader_bundle_sha256"]
    )
    c.connection.revalidate(
        plan,
        expected_plan_sha256=digest(plan),
        raw=c.context["raw"],
        current=c.context["current"],
        pin_binding=c.context["pin_binding"],
    )
    assert len(c.source_calls) >= 4
    assert all(
        call["expected_reader_artifact_sha256"]
        == c.reader_kwargs["expected_reader_artifact_sha256"]
        for call in c.source_calls
    )


def test_reader_opt_in_requires_all_four_external_pins(case):
    _, _, _, args = case
    with pytest.raises(GradebookError, match="EXPLICIT_READER_BINDING_REQUIRED"):
        LocalGrAssDraftEditConnection(
            **args, reader_bundle_path=Path("/private/tmp/fictional-bundle")
        )


@pytest.mark.parametrize(
    "drift,code",
    [
        ("bundle", "READER_BUNDLE_CHANGED"),
        ("artifact", "READER_ARTIFACT_CHANGED"),
        ("policy", "CURRENT_POLICY_BINDING_CHANGED"),
        ("revision", "PARTICIPATION_SOURCE_CHANGED"),
    ],
)
def test_reader_source_is_reconstructed_before_every_preflight(
    reader_case, drift, code
):
    case = reader_case
    plan = case.connection.prepare(**case.context)
    if drift == "bundle":
        case.reader_kwargs["reader_bundle_path"].write_text("changed bundle", encoding="utf-8")
    elif drift == "artifact":
        case.reader_artifact.write_text("changed visual reader artifact", encoding="utf-8")
    elif drift == "policy":
        case.source_state["report"]["policy"]["version"] = "changed policy"
    else:
        case.source_state["proposals"][0]["revision_ref"] = "9" * 64
    expected_error = (
        GradebookError if drift == "revision" else case.stage_module.StageHold
    )
    with pytest.raises(expected_error, match=code):
        case.connection.revalidate(
            plan,
            expected_plan_sha256=digest(plan),
            raw=case.context["raw"],
            current=case.context["current"],
            pin_binding=case.context["pin_binding"],
        )


def test_reader_confidence_cannot_be_relabelled_as_native_high(reader_case):
    case = reader_case
    case.source_state["proposals"][0]["confidence"] = "HIGH"
    with pytest.raises(GradebookError, match="READER_SOURCE_BINDING_CHANGED"):
        case.connection.prepare(**case.context)


def test_native_default_does_not_implicitly_admit_reader_confidence(case):
    connection, context, source, _ = case
    source["proposals"][0].update(
        confidence="READER_ADVISORY",
        semantic_evidence_state="SOURCE_BOUND_READER_ADVISORY",
    )
    with pytest.raises(GradebookError, match="EXPLICIT_READER_BINDING_REQUIRED"):
        connection.prepare(**context)


def test_reader_binding_is_in_retained_plan_and_revalidation(reader_case):
    case = reader_case
    plan = case.connection.prepare(**case.context)
    plan["reader_binding"]["artifact_sha256"] = "0" * 64
    with pytest.raises(GradebookError, match="EXACT_CONNECTION_PLAN_CHANGED"):
        case.connection.revalidate(
            plan,
            expected_plan_sha256=digest(plan),
            raw=case.context["raw"],
            current=case.context["current"],
            pin_binding=case.context["pin_binding"],
        )


def test_reader_readback_remains_available_after_source_artifacts_disappear(
    reader_case, monkeypatch
):
    case = reader_case
    plan = case.connection.prepare(**case.context)
    actual = native._state(case.context["raw"])
    native._apply_requests(
        actual, plan["transfer"]["requests"], case.context["binding"]
    )
    case.reader_artifact.unlink()
    case.reader_kwargs["reader_bundle_path"].unlink()
    monkeypatch.setattr(
        case.stage_module,
        "workspace_reader_proposals",
        lambda *a, **kw: (_ for _ in ()).throw(AssertionError("Reader unavailable")),
    )
    result = case.connection.classify(
        plan, raw_from_state(actual), expected_plan_sha256=digest(plan)
    )
    assert (
        result["status"] == "PLANNED_OUTPUT_OBSERVED"
        and result["retry_writes"] is False
    )


@pytest.mark.parametrize(
    "field",
    [
        "reader_bundle_path",
        "expected_reader_bundle_sha256",
        "expected_policy_sha256",
        "expected_reader_artifact_sha256",
    ],
)
def test_every_reader_opt_in_component_is_required_together(reader_case, field):
    args = dict(reader_case.constructor_args)
    args[field] = None
    with pytest.raises(GradebookError, match="EXPLICIT_READER_BINDING_REQUIRED"):
        LocalGrAssDraftEditConnection(**args)


@pytest.fixture
def current_attempt_case(case, tmp_path, monkeypatch):
    """Exercise Canvas pin plumbing; LocalGrAss separately owns permit semantics."""
    _, context, source, args = case
    path = tmp_path / "fictional-current-attempt-review.json"
    permit = {
        "contract": "FICTIONAL_LOCAL_ATTEMPT_REVIEW",
        "record_ref": source["proposals"][0]["record_ref"],
        "scope": "LOCAL_UNAPPROVED_EDIT_ONLY",
    }
    path.write_text(json.dumps(permit), encoding="utf-8")
    stage = args["stage_module"]
    original = stage.prepare_stage
    calls = []

    def prepare(*a, **kwargs):
        review = kwargs.pop("current_attempt_review", None)
        calls.append(copy.deepcopy(review))
        plan = original(*a, **kwargs)
        if review is not None:
            plan["current_attempt_review"] = copy.deepcopy(review)
            plan.pop("plan_id")
            plan["plan_id"] = stage.digest(plan)
        return plan

    monkeypatch.setattr(stage, "prepare_stage", prepare)
    args = {
        **args,
        "current_attempt_review_path": path,
        "expected_current_attempt_review_sha256": args["files"].file_sha(path),
    }
    connection = LocalGrAssDraftEditConnection(**args)
    return SimpleNamespace(
        connection=connection,
        context=context,
        path=path,
        permit=permit,
        source_calls=calls,
        constructor_args=args,
    )


def test_current_attempt_review_plumbing_binds_exact_file_and_inner_permit(
    current_attempt_case,
):
    c = current_attempt_case
    plan = c.connection.prepare(**c.context)
    assert plan["current_attempt_review_binding"] == {
        "path": str(c.path),
        "sha256": c.constructor_args["expected_current_attempt_review_sha256"],
    }
    assert plan["transfer"]["current_attempt_review"] == c.permit
    assert c.source_calls == [c.permit]
    c.connection.revalidate(
        plan,
        expected_plan_sha256=digest(plan),
        raw=c.context["raw"],
        current=c.context["current"],
        pin_binding=c.context["pin_binding"],
    )
    assert c.source_calls == [c.permit, c.permit]


@pytest.mark.parametrize(
    "kwargs",
    [
        {"current_attempt_review_path": Path("/private/tmp/fictional-review")},
        {"expected_current_attempt_review_sha256": "1" * 64},
        {
            "current_attempt_review_path": Path("relative-review"),
            "expected_current_attempt_review_sha256": "1" * 64,
        },
        {
            "current_attempt_review_path": Path("/private/tmp/fictional-review"),
            "expected_current_attempt_review_sha256": "bad",
        },
    ],
)
def test_current_attempt_review_constructor_requires_complete_absolute_pins(
    case, kwargs
):
    *_, args = case
    with pytest.raises(
        GradebookError, match="EXPLICIT_CURRENT_ATTEMPT_REVIEW_REQUIRED"
    ):
        LocalGrAssDraftEditConnection(**args, **kwargs)


def test_current_attempt_review_file_mutation_blocks_preflight(current_attempt_case):
    c = current_attempt_case
    plan = c.connection.prepare(**c.context)
    c.path.write_text(json.dumps({**c.permit, "changed": True}), encoding="utf-8")
    with pytest.raises(GradebookError, match="CURRENT_ATTEMPT_REVIEW_CHANGED"):
        c.connection.revalidate(
            plan,
            expected_plan_sha256=digest(plan),
            raw=c.context["raw"],
            current=c.context["current"],
            pin_binding=c.context["pin_binding"],
        )
    assert c.source_calls == [c.permit]


def test_current_attempt_review_plan_cannot_change_bound_file_scope(
    current_attempt_case,
):
    c = current_attempt_case
    plan = c.connection.prepare(**c.context)
    plan["current_attempt_review_binding"]["sha256"] = "0" * 64
    with pytest.raises(GradebookError, match="EXACT_CONNECTION_PLAN_CHANGED"):
        c.connection.revalidate(
            plan,
            expected_plan_sha256=digest(plan),
            raw=c.context["raw"],
            current=c.context["current"],
            pin_binding=c.context["pin_binding"],
        )


@pytest.mark.parametrize("change", ["match", "missing", "partial", "path", "hash"])
def test_current_attempt_review_owner_config_must_match_trusted_connection(
    current_attempt_case, tmp_path, change
):
    from canvas_mcp.gradebook.localgrass_edit_owner import LocalGrAssEditOwner

    c = current_attempt_case
    connection = c.connection
    repo = tmp_path / "configured-repo"
    (repo / "config").mkdir(parents=True)
    (repo / "config/sdm-gradebook-workbooks.json").write_text(
        json.dumps({"core": c.context["binding"]})
    , encoding="utf-8")
    worker = tmp_path / "worker.json"
    worker.write_text(json.dumps({"state_dir": str(connection.store.root)}), encoding="utf-8")
    config = {
        "course": "core",
        "spreadsheet_id": c.context["binding"]["spreadsheet_id"],
        "assignment_bindings_path": str(connection.assignment_path),
        "assignment_bindings_sha256": connection.assignment_sha256,
        "pin_registry": str(connection.registry_path),
        "canvas_repo": str(repo),
        "worker_config": str(worker),
        "current_attempt_review_path": str(c.path),
        "current_attempt_review_sha256": c.constructor_args[
            "expected_current_attempt_review_sha256"
        ],
    }
    if change == "missing":
        config.pop("current_attempt_review_path")
        config.pop("current_attempt_review_sha256")
    elif change == "partial":
        config.pop("current_attempt_review_sha256")
    elif change == "path":
        config["current_attempt_review_path"] = str(tmp_path / "another-review.json")
    elif change == "hash":
        config["current_attempt_review_sha256"] = "0" * 64
    path = tmp_path / "configuration.json"
    path.write_text(json.dumps(config), encoding="utf-8")
    owner = object.__new__(LocalGrAssEditOwner)
    owner.connection = connection
    owner.binding = c.context["binding"]
    owner.config_path = path
    owner.config_sha256 = connection.files.file_sha(path)
    owner._pin_defaults = SimpleNamespace(DEFAULT_REGISTRY=connection.registry_path)
    if change == "match":
        assert owner._configuration() == config
    else:
        with pytest.raises(
            GradebookError, match="EXACT_CURRENT_ATTEMPT_CONFIG_REQUIRED"
        ):
            owner._configuration()


def test_current_attempt_review_detects_change_during_load(
    current_attempt_case, monkeypatch
):
    c = current_attempt_case
    original = c.connection.files.load

    def mutate(path):
        value = original(path)
        if Path(path) == c.path:
            c.path.write_text(json.dumps({**value, "changed_during_read": True}), encoding="utf-8")
        return value

    monkeypatch.setattr(c.connection.files, "load", mutate)
    with pytest.raises(GradebookError, match="CURRENT_ATTEMPT_REVIEW_CHANGED"):
        c.connection.prepare(**c.context)
    assert c.source_calls == []


def test_current_attempt_review_derives_runtime_metadata_binding_without_file_change(
    current_attempt_case,
):
    c = current_attempt_case
    before = c.connection.assignment_path.read_bytes()
    plan = c.connection.prepare(**c.context)
    raw_entries = c.connection.files.load(c.connection.assignment_path)
    runtime = copy.deepcopy(raw_entries)
    runtime[0]["provider_metadata_sha256"] = c.context["current"]["assignments"][0][
        "assignment_metadata_sha256"
    ]
    assert plan["transfer"]["assignment_bindings_sha256"] == digest(runtime)
    assert c.connection.assignment_path.read_bytes() == before


def test_current_attempt_review_wrong_file_hash_holds_before_stage(
    current_attempt_case,
):
    c = current_attempt_case
    args = {**c.constructor_args, "expected_current_attempt_review_sha256": "0" * 64}
    connection = LocalGrAssDraftEditConnection(**args)
    with pytest.raises(GradebookError, match="CURRENT_ATTEMPT_REVIEW_CHANGED"):
        connection.prepare(**c.context)
    assert c.source_calls == []


def test_current_attempt_review_inner_permit_cannot_be_detached_from_bound_plan(
    current_attempt_case,
):
    c = current_attempt_case
    plan = c.connection.prepare(**c.context)
    plan.pop("current_attempt_review_binding")
    with pytest.raises(GradebookError, match="CURRENT_ATTEMPT_REVIEW_BINDING_CHANGED"):
        c.connection.validate_plan(plan, expected_plan_sha256=digest(plan))


def test_current_attempt_review_unsupported_stage_holds_before_invocation(
    current_attempt_case, monkeypatch
):
    c = current_attempt_case
    calls = []

    def legacy_stage(
        proposals,
        *,
        raw,
        binding,
        baseline,
        current,
        pin_binding,
        assignment_bindings,
        owner,
        source_check,
    ):
        calls.append(True)
        raise AssertionError("Unsupported stage must not run")

    monkeypatch.setattr(c.connection.stage, "prepare_stage", legacy_stage)
    with pytest.raises(GradebookError, match="CURRENT_ATTEMPT_REVIEW_UNSUPPORTED"):
        c.connection.prepare(**c.context)
    assert calls == []
