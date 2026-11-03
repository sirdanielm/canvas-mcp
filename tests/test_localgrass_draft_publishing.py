"""Fictional draft-to-publish qualification through the existing owner and ledger.

All HTTP uses MockTransport. Only the explicitly named synthetic approval step
can reach the fictional Canvas PUT; this test confers no real publication scope.
"""

import asyncio
import copy
import json
import os
import time
from types import SimpleNamespace

import httpx
import pytest
from test_gradebook import snapshot as snapshot
from test_gradebook_native import binding as binding
from test_gradebook_native import raw_from_state
from test_gradebook_proposal_preview import scenario as scenario
from test_localgrass_draft_edit import case as case
from test_localgrass_draft_edit import draft_case as draft_case
from test_localgrass_draft_edit import reader_case as reader_case

from canvas_mcp.gradebook import native, native_edit_review
from canvas_mcp.gradebook.client import GradebookClient, GradebookError
from canvas_mcp.gradebook.google import GoogleSheets
from canvas_mcp.gradebook.ledger import Ledger
from canvas_mcp.gradebook.localgrass_edit_owner import LocalGrAssEditOwner
from canvas_mcp.gradebook.model import digest
from canvas_mcp.gradebook.proposal_preview import prepare_preview
from canvas_mcp.gradebook.publish import Publisher
from canvas_mcp.gradebook.worker import RefreshJournal, RefreshJournalBusy


@pytest.fixture
def draft_publishing(draft_case, tmp_path, monkeypatch, request):
    external = os.environ.get("LOCALGRASS_TEST_ROOT")
    if not external:
        pytest.skip("Explicit qualified LocalGrAss file primitives required")
    monkeypatch.syspath_prepend(external)
    c = (
        request.getfixturevalue("reader_case")
        if getattr(request, "param", None) == "reader"
        else draft_case
    )
    files = c.files
    c.source_state["report"]["records"][0].setdefault(
        "private_analysis", "Retain full fictional analysis."
    )
    c.source_state["report"]["records"][0]["source_feedback"] = (
        "Complete private analytical feedback.\nSecond item retained verbatim."
    )
    store = c.connection.store
    store.save("snapshot", c.context["baseline"])
    repo = tmp_path / "configured-canvas-owner"
    (repo / "config").mkdir(parents=True)
    (repo / "config/sdm-gradebook-workbooks.json").write_text(
        json.dumps({"core": c.context["binding"]})
    , encoding="utf-8")
    output = tmp_path / "existing-participation-history"
    output.mkdir(mode=0o700)
    runtime = tmp_path / "existing-runtime"
    runtime.mkdir()
    worker = tmp_path / "worker.json"
    worker.write_text(json.dumps({"state_dir": str(store.root)}), encoding="utf-8")
    config_path = tmp_path / "staging.json"
    config_path.write_text(
        json.dumps(
            {
                "course": "core",
                "spreadsheet_id": c.context["binding"]["spreadsheet_id"],
                "assignment_bindings_path": str(c.connection.assignment_path),
                "assignment_bindings_sha256": c.connection.assignment_sha256,
                "pin_registry": str(c.connection.registry_path),
                "canvas_repo": str(repo),
                "output_root": str(output),
                "runtime_root": str(runtime),
                "worker_config": str(worker),
            }
        )
    , encoding="utf-8")
    monkeypatch.setattr(
        "localgrass.teacher_edit_identity.canonical_pin_binding",
        lambda *_: copy.deepcopy(c.context["pin_binding"]),
    )
    credential = tmp_path / "fictional-google.json"
    credential.write_text(
        json.dumps(
            {
                "tokens": {
                    "gradebook": {
                        "type": "authorized_user",
                        "client_id": "fictional-client",
                        "client_secret": "fictional-secret",
                        "refresh_token": "fictional-refresh",
                    }
                }
            }
        )
    , encoding="utf-8")
    credential.chmod(0o600)
    state = {
        "raw": copy.deepcopy(c.context["raw"]),
        "sheets_posts": [],
        "canvas_requests": [],
        "canvas_puts": [],
        "approved": None,
        "lose_reply": False,
        "submission": {
            "user_id": 101,
            "assignment_id": 21,
            "score": 10,
            "grade": "10",
            "workflow_state": "graded",
            "assignment_visible": True,
            "attempt": 3,
            "submitted_at": "2026-10-17T00:00:00Z",
            "excused": False,
            "grade_matches_current_submission": True,
            "submission_comments": [{"id": 31, "comment": "Existing teacher comment"}],
        },
        "assignment": {
            "id": 21,
            "course_id": 12,
            "name": "Test activity",
            "position": 1,
            "published": True,
            "points_possible": 20,
            "grading_type": "points",
            "moderated_grading": False,
            "anonymous_grading": False,
            "group_category_id": None,
            "submission_types": ["online_upload"],
            "external_tool_tag_attributes": None,
        },
    }
    journal = RefreshJournal(store.root, c.context["binding"]["spreadsheet_id"])

    def canvas_transport(request):
        path = request.url.path
        state["canvas_requests"].append((request.method, path))
        if request.method == "PUT":
            assert state["approved"] is not None
            body = json.loads(request.content)
            assert body == {"submission": {"posted_grade": "20"}}
            operation = ledger.operation(state["approved"]["operation_id"])
            assert operation["items"][0]["status"] == "sending"
            state["canvas_puts"].append(body)
            state["submission"].update(score=20, grade="20")
            if state["lose_reply"]:
                raise httpx.ReadTimeout("Fictional lost reply", request=request)
            return httpx.Response(200, json=state["submission"])
        assert request.method == "GET"
        if path.endswith("/permissions"):
            value = {"manage_grades": True}
        elif path.endswith("/sections"):
            value = [{"id": 7, "name": "A1"}, {"id": 8, "name": "B1"}]
        elif path.endswith("/enrollments"):
            value = [
                {
                    "user_id": 101,
                    "type": "StudentEnrollment",
                    "enrollment_state": "active",
                    "course_section_id": section,
                    "user": {
                        "id": 101,
                        "name": "Synthetic Student",
                        "sortable_name": "Student, Synthetic",
                    },
                }
                for section in (7, 8)
            ]
        elif path.endswith("/assignments"):
            value = [state["assignment"]]
        elif path.endswith("/submissions"):
            value = [state["submission"]]
        elif path.endswith("/submissions/101"):
            value = state["submission"]
        elif path.endswith("/assignments/21"):
            value = state["assignment"]
        else:
            assert path == "/api/v1/courses/12"
            value = {"id": 12, "name": "Synthetic class", "workflow_state": "available"}
        return httpx.Response(200, json=value)

    def sheets_transport(request):
        assert (
            request.method == "POST" and str(request.url) == google.url + ":batchUpdate"
        )
        with pytest.raises(RefreshJournalBusy):
            with journal.exclusive():
                pass
        receipts = sorted(output.glob("*/receipt-*.json"))
        assert json.loads(receipts[-1].read_text(encoding="utf-8"))["status"] == "SENDING"
        requests = json.loads(request.content)["requests"]
        state["sheets_posts"].append(copy.deepcopy(requests))
        assert len(requests) == 1
        assert requests[0]["updateCells"]["fields"] == "userEnteredValue,note"
        current = native._state(state["raw"])
        native._apply_requests(current, requests, c.context["binding"])
        state["raw"] = raw_from_state(current)
        return httpx.Response(200, json={"spreadsheetId": google.workbook_id})

    canvas = GradebookClient(
        c.context["baseline"]["origin"],
        "fictional",
        httpx.MockTransport(canvas_transport),
    )
    google = GoogleSheets(
        c.context["binding"]["spreadsheet_id"],
        credential,
        transport=httpx.MockTransport(sheets_transport),
    )

    async def read_workbook():
        google._authorized = True
        google._access_token = google._validated_token = "fictional-validated-token"
        google._expires_at = time.monotonic() + 300
        return copy.deepcopy(state["raw"])

    monkeypatch.setattr(google, "read_workbook", read_workbook)
    ledger = Ledger(store.root)
    owner = LocalGrAssEditOwner(
        c.connection,
        canvas,
        google,
        journal,
        staging_config_path=config_path,
        expected_staging_config_sha256=files.file_sha(config_path),
        binding=c.context["binding"],
    )
    result = SimpleNamespace(
        case=c,
        owner=owner,
        publisher=Publisher(canvas, store, ledger),
        state=state,
        canvas=canvas,
        google=google,
        store=store,
        output=output,
    )
    yield result
    asyncio.run(canvas.close())
    asyncio.run(google.close())


async def prepared_draft(c):
    before = native._state(c.state["raw"])
    prepared = await c.owner.prepare()
    plan = c.store.load("review", prepared["plan_id"])
    assert plan["source_report"] == c.case.source_state["report"]
    assert (
        plan["source_report"]["records"][0]["private_analysis"]
        == "Retain full fictional analysis."
    )
    assert plan["teacher_approval"] is plan["publication_allowed"] is False
    assert c.state["sheets_posts"] == c.state["canvas_puts"] == []
    staged = await c.owner.execute(prepared["plan_id"], enabled=True)
    assert staged["status"] == "PLANNED_OUTPUT_OBSERVED"
    assert staged["review_state"] == "UNAPPROVED"
    assert staged["teacher_approval"] is staged["publication_allowed"] is False
    assert c.state["canvas_puts"] == [] and len(c.state["sheets_posts"]) == 1
    after = native._state(c.state["raw"])
    original_cell = before["sheets"][2]["cells"]["5:2"]
    staged_cell = after["sheets"][2]["cells"]["5:2"]
    assert staged_cell["userEnteredValue"] == {"numberValue": 20}
    assert staged_cell["note"].startswith(original_cell.get("note", ""))
    assert "UNAPPROVED" in staged_cell["note"]
    after["sheets"][2]["cells"]["5:2"] = original_cell
    assert (
        after == before
    )  # Full GET, reference, EDIT context and original B2 retained.
    request_start = len(c.state["canvas_requests"])
    review = await native_edit_review.prepare_review(
        c.canvas,
        c.store,
        "core",
        c.case.context["binding"],
        c.state["raw"],
    )
    assert review["counts"] == {"ready_for_review": 1}
    assert review["canvas_writes"] == review["sheets_writes"] == 0
    fresh_requests = c.state["canvas_requests"][request_start:]
    assert fresh_requests and all(method == "GET" for method, _ in fresh_requests)
    push = await c.publisher.prepare("12", review["review_id"])
    assert push["ready_for_confirmation"] is True and push["canvas_writes"] == 0
    assert c.state["canvas_puts"] == []
    return prepared, push


async def approve_exact_synthetic_push(c, push):
    """The ONE synthetic teacher approval; never reuse as real authorization."""
    operation = c.publisher.ledger.operation(push["operation_id"])
    plan = c.store.load("push", operation["plan_id"])
    assert len(plan["items"]) == 1
    assert {
        k: plan["items"][0][k] for k in ("user_id", "assignment_id", "proposed")
    } == {
        "user_id": "101",
        "assignment_id": "21",
        "proposed": 20,
    }
    assert c.state["approved"] is None
    c.state["approved"] = {
        "operation_id": push["operation_id"],
        "plan_sha256": digest(plan),
    }
    return await c.publisher.confirm(
        "12", push["operation_id"], push["confirmation_token"]
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("lost_reply", [False, True])
async def test_draft_then_one_approval_score_only_readback_never_resends(
    draft_publishing, lost_reply
):
    c = draft_publishing
    staged, push = await prepared_draft(c)
    c.state["lose_reply"] = lost_reply
    result = await approve_exact_synthetic_push(c, push)
    assert result["counts"] == ({"uncertain": 1} if lost_reply else {"verified": 1})
    assert c.state["canvas_puts"] == [{"submission": {"posted_grade": "20"}}]
    assert c.state["submission"]["submission_comments"] == [
        {"id": 31, "comment": "Existing teacher comment"}
    ]
    with pytest.raises(GradebookError, match="already consumed"):
        await c.publisher.confirm(
            "12", push["operation_id"], push["confirmation_token"]
        )
    reconciled = await c.publisher.reconcile("12", push["operation_id"])
    assert reconciled["counts"] == (
        {"observed_applied": 1} if lost_reply else {"verified": 1}
    )
    assert len(c.state["canvas_puts"]) == 1
    assert c.state["canvas_requests"][-1] == (
        "GET",
        "/api/v1/courses/12/assignments/21/submissions/101",
    )
    assert (
        c.store.load("review", staged["plan_id"])["source_report"]
        == (c.case.source_state["report"])
    )
    readback = await c.owner.execute(staged["plan_id"], enabled=True)
    assert readback["status"] == "PLANNED_OUTPUT_OBSERVED"
    assert len(c.state["sheets_posts"]) == 1
    assert (
        c.case.source_state["report"]["records"][0]["private_analysis"]
        == "Retain full fictional analysis."
    )


def test_analytical_score_only_is_not_admitted_as_participation(scenario):
    row = scenario["proposals"][0]
    row.update(source_lane="SDMGRASS_ANALYTICAL", delivery_policy="SCORE_ONLY")
    binding = scenario["assignment_bindings"][0]
    binding.update(
        source_lane="SDMGRASS_ANALYTICAL",
        delivery_policy="SCORE_ONLY",
        proposal_sha256=digest(row),
    )
    plan = prepare_preview(**scenario)
    assert plan["envelope"]["edits"] == [] and plan["proposals"] == []
    assert plan["holds"][0]["code"] == "SOURCE_LANE_REQUIRED"
    assert plan["canvas_writes"] == 0


@pytest.mark.asyncio
async def test_existing_teacher_note_blocks_draft_without_clobber(draft_publishing):
    c = draft_publishing
    state = native._state(c.state["raw"])
    note = "Teacher-owned correction and full private feedback remain."
    state["sheets"][2]["cells"]["5:2"]["note"] = note
    c.state["raw"] = raw_from_state(state)
    before = copy.deepcopy(c.state["raw"])
    prepared = await c.owner.prepare()
    plan = c.store.load("review", prepared["plan_id"])
    assert plan["transfer"]["requests"] == []
    assert (
        plan["transfer"]["holds"][0]["code"]
        == "EXISTING_TEACHER_EDIT_OR_NOTE_PRESERVED"
    )
    assert plan["source_report"] == c.case.source_state["report"]
    await c.owner.execute(prepared["plan_id"], enabled=True)
    assert c.state["raw"] == before
    assert c.state["sheets_posts"] == c.state["canvas_puts"] == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "metadata,code",
    [
        (
            {
                "external_tool_tag_attributes": {
                    "url": "https://edpuzzle.example.invalid/activity"
                }
            },
            "EXCLUDED_PROVIDER",
        ),
        ({"submission_types": ["external_tool"]}, "EXTERNAL_TOOL_REVIEW_REQUIRED"),
        (
            {
                "submission_types": ["external_tool"],
                "external_tool_tag_attributes": {
                    "url": "https://assignments.google.com/lti/a/unreviewed-fictional-activity"
                },
            },
            "EXTERNAL_TOOL_REVIEW_REQUIRED",
        ),
    ],
)
async def test_fresh_assignment_exclusion_blocks_draft_before_any_send(
    draft_publishing, metadata, code
):
    c = draft_publishing
    c.state["assignment"].update(metadata)
    before = copy.deepcopy(c.state["raw"])
    with pytest.raises(GradebookError, match=code):
        await c.owner.prepare()
    assert c.state["raw"] == before
    assert c.state["sheets_posts"] == c.state["canvas_puts"] == []
    assert ("GET", "/api/v1/courses/12/assignments/21") in c.state["canvas_requests"]


def configure_reviewed_google_draft(c):
    """Pin one fictional, specifically reviewed external-tool draft destination."""
    c.state["assignment"].update(
        submission_types=["external_tool"],
        external_tool_tag_attributes={
            "url": "https://assignments.google.com/lti/a/fictional-activity"
        },
    )
    assignments = c.case.files.load(c.case.assignment_path)
    target = assignments[0]
    source = c.case.source_state["proposals"][0]
    target["external_tool_draft_review"] = {
        "contract": "CANVAS_GOOGLE_ASSIGNMENTS_DRAFT_REVIEW_V1",
        "provider": "GOOGLE_ASSIGNMENTS",
        "source_provider": target["provider"],
        "origin": c.case.context["baseline"]["origin"],
        "course_id": "12",
        "assignment_id": "21",
        **{
            key: source[key]
            for key in (
                "assignment_key",
                "source_target",
                "student_track",
                "record_ref",
                "revision_ref",
                "queue_digest",
            )
        },
        "assignment_metadata_sha256": digest(c.state["assignment"]),
        "review_ref": "6" * 64,
        "scope": "LOCAL_UNAPPROVED_EDIT_ONLY",
        "source_lane": "SDMGRASS_FORMATIVE",
        "delivery_policy": "SCORE_ONLY",
        "publication_allowed": False,
    }
    c.case.files.write(c.case.assignment_path, assignments)
    assignment_sha = c.case.files.file_sha(c.case.assignment_path)
    # Only fictional temporary bindings are repinned; no installed pin is read
    # or changed. Reconstruct the owner to exercise the actual pinned boundary.
    args = {
        **c.case.constructor_args,
        "expected_assignment_bindings_sha256": assignment_sha,
    }
    connection = type(c.case.connection)(**args)
    config = c.case.files.load(c.owner.config_path)
    config["assignment_bindings_sha256"] = assignment_sha
    c.case.files.write(c.owner.config_path, config)
    c.owner = LocalGrAssEditOwner(
        connection,
        c.canvas,
        c.google,
        c.owner.journal,
        staging_config_path=c.owner.config_path,
        expected_staging_config_sha256=c.case.files.file_sha(c.owner.config_path),
        binding=c.case.context["binding"],
    )
    c.case.connection = connection
    return copy.deepcopy(c.state["assignment"])


@pytest.mark.asyncio
async def test_exact_google_review_stages_truthful_metadata_then_one_score_only_push(
    draft_publishing,
):
    c = draft_publishing
    metadata = configure_reviewed_google_draft(c)
    staged, push = await prepared_draft(c)
    local_plan = c.store.load("review", staged["plan_id"])
    observed = local_plan["transfer"]["current_basis"]["targets"][0]["assignment"]
    assert observed["assignment_metadata"] == metadata
    assert observed["assignment_metadata_sha256"] == digest(metadata)
    assert metadata["submission_types"] == ["external_tool"]
    assert metadata["external_tool_tag_attributes"]["url"].startswith(
        "https://assignments.google.com/lti/a/"
    )
    result = await approve_exact_synthetic_push(c, push)
    assert result["counts"] == {"verified": 1}
    assert c.state["canvas_puts"] == [{"submission": {"posted_grade": "20"}}]
    with pytest.raises(GradebookError, match="already consumed"):
        await c.publisher.confirm(
            "12", push["operation_id"], push["confirmation_token"]
        )
    assert (await c.publisher.reconcile("12", push["operation_id"]))["counts"] == {
        "verified": 1
    }
    assert len(c.state["canvas_puts"]) == 1
    assert c.state["assignment"] == metadata
    assert c.state["canvas_requests"][-1] == (
        "GET",
        "/api/v1/courses/12/assignments/21/submissions/101",
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "change,code",
    [
        ("metadata", "GOOGLE_ASSIGNMENTS_DRAFT_REVIEW_REQUIRED"),
        ("edpuzzle", "EXCLUDED_PROVIDER"),
    ],
)
async def test_google_review_cannot_admit_changed_metadata_or_edpuzzle(
    draft_publishing, change, code
):
    c = draft_publishing
    configure_reviewed_google_draft(c)
    if change == "metadata":
        c.state["assignment"]["name"] = "Changed fresh assignment details"
    else:
        c.state["assignment"]["external_tool_tag_attributes"]["url"] = (
            "https://edpuzzle.example.invalid/activity"
        )
    before = copy.deepcopy(c.state["raw"])
    with pytest.raises(GradebookError, match=code):
        await c.owner.prepare()
    assert c.state["raw"] == before
    assert c.state["sheets_posts"] == c.state["canvas_puts"] == []


@pytest.mark.asyncio
@pytest.mark.parametrize("draft_publishing", ["reader"], indirect=True)
async def test_explicit_reader_google_draft_retains_native_hold_and_never_resends(
    draft_publishing,
):
    c = draft_publishing
    metadata = configure_reviewed_google_draft(c)
    staged, push = await prepared_draft(c)
    plan = c.store.load("review", staged["plan_id"])
    row = plan["transfer"]["proposals"][0]
    assert row["confidence"] == "READER_ADVISORY"
    assert row["semantic_evidence_state"] == "SOURCE_BOUND_READER_ADVISORY"
    assert row["native_question_observations"] == {"Q1": "UNCERTAIN"}
    assert row["reader_question_observations"] == {"Q1": "ATTEMPT_CONFIRMED"}
    assert plan["source_report"]["records"][0]["status"] == "UNRESOLVED"
    assert plan["source_report"]["records"][0]["question_observations"] == {
        "Q1": "UNCERTAIN"
    }
    assert plan["reader_binding"] == c.case.connection.reader_binding
    assert plan["teacher_approval"] is plan["publication_allowed"] is False
    observed = plan["transfer"]["current_basis"]["targets"][0]["assignment"]
    assert observed["assignment_metadata"] == metadata
    assert c.case.source_calls
    for call in c.case.source_calls:
        assert call["path"] == c.case.reader_kwargs["reader_bundle_path"]
        assert (
            call["expected_bundle_sha256"]
            == c.case.reader_kwargs["expected_reader_bundle_sha256"]
        )
        assert (
            call["expected_policy_sha256"]
            == c.case.reader_kwargs["expected_policy_sha256"]
        )
        assert (
            call["expected_reader_artifact_sha256"]
            == c.case.reader_kwargs["expected_reader_artifact_sha256"]
        )
    source_reads = len(c.case.source_calls)
    result = await c.owner.execute(staged["plan_id"], enabled=True)
    assert result["status"] == "PLANNED_OUTPUT_OBSERVED"
    assert len(c.case.source_calls) == source_reads
    assert len(c.state["sheets_posts"]) == 1 and c.state["canvas_puts"] == []
    assert c.state["approved"] is None
    assert c.publisher.ledger.summary(push["operation_id"])["status"] == "prepared"


@pytest.mark.asyncio
@pytest.mark.parametrize("draft_publishing", ["reader"], indirect=True)
async def test_reader_artifact_drift_after_preparation_blocks_existing_owner_send(
    draft_publishing,
):
    c = draft_publishing
    configure_reviewed_google_draft(c)
    prepared = await c.owner.prepare()
    before = copy.deepcopy(c.state["raw"])
    c.case.reader_artifact.write_text("Changed fictional reader observation.", encoding="utf-8")
    with pytest.raises(c.case.stage_module.StageHold, match="READER_ARTIFACT_CHANGED"):
        await c.owner.execute(prepared["plan_id"], enabled=True)
    assert c.state["raw"] == before
    assert c.state["sheets_posts"] == c.state["canvas_puts"] == []
    assert not list(c.output.glob("*/receipt-*.json"))
    assert c.state["approved"] is None
