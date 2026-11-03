"""Joint real-stage current-attempt checks; fictional data and no transports."""

import copy
import json
from types import SimpleNamespace

import pytest
from test_gradebook import snapshot as snapshot
from test_gradebook_native import binding as binding
from test_gradebook_native import initial_raw, raw_from_state
from test_localgrass_draft_edit import case as case

from canvas_mcp.gradebook import native
from canvas_mcp.gradebook.client import GradebookError
from canvas_mcp.gradebook.localgrass_draft_edit import LocalGrAssDraftEditConnection
from canvas_mcp.gradebook.model import digest


@pytest.fixture
def attempt_case(case, tmp_path):
    connection, ctx, source, args = case
    baseline_cell = ctx["baseline"]["cells"]["101:21"]
    baseline_cell.update(
        value=None,
        grade=None,
        attempt=None,
        submitted_at=None,
        graded_at=None,
        posted_at=None,
        late=False,
        points_deducted=None,
        workflow_state="unsubmitted",
    )
    current_cell = ctx["current"]["cells"]["101:21"]
    current_cell.update(
        value=None,
        grade=None,
        attempt=1,
        submitted_at="2026-10-18T00:30:00Z",
        graded_at=None,
        posted_at=None,
        late=True,
        points_deducted=0,
        workflow_state="submitted",
        excused=False,
        grade_matches_current_submission=True,
    )
    ctx["raw"] = initial_raw(ctx["baseline"], ctx["binding"])
    return SimpleNamespace(
        connection=connection,
        ctx=ctx,
        source=source,
        args=args,
        review_path=tmp_path / "attempt-review.json",
    )


def bind_review(c):
    target = c.connection.files.load(c.connection.assignment_path)[0]
    target["provider_metadata_sha256"] = c.ctx["current"]["assignments"][0][
        "assignment_metadata_sha256"
    ]
    permit = {
        "contract": "LOCAL_PARTICIPATION_CURRENT_ATTEMPT_REVIEW_V1",
        "scope": "UNAPPROVED_DRAFT_ONLY",
        "authority_sha256": "9" * 64,
        "proposal_sha256": digest(c.source["proposals"][0]),
        "baseline_sha256": digest(c.ctx["baseline"]),
        "native_before_sha256": c.connection.stage.digest(native._state(c.ctx["raw"])),
        "current_cell_sha256": digest(c.ctx["current"]["cells"]["101:21"]),
        "origin": c.ctx["current"]["origin"],
        "course_id": "12",
        "user_id": "101",
        "assignment_id": "21",
        "current_attempt": 1,
        "maximum": 20,
        "assignment_binding_sha256": digest(target),
        "provider_metadata_sha256": target["provider_metadata_sha256"],
    }
    c.review_path.write_text(json.dumps(permit), encoding="utf-8")
    c.connection = LocalGrAssDraftEditConnection(
        **c.args,
        current_attempt_review_path=c.review_path,
        expected_current_attempt_review_sha256=c.connection.files.file_sha(
            c.review_path
        ),
    )
    return permit


def assert_held(c):
    before = copy.deepcopy(c.ctx["raw"])
    try:
        plan = c.connection.prepare(**c.ctx)
    except GradebookError:
        pass
    else:
        assert plan["transfer"]["items"] == plan["transfer"]["requests"] == []
        assert plan["transfer"]["holds"]
    assert c.ctx["raw"] == before


def test_default_new_ungraded_attempt_remains_held(attempt_case):
    c = attempt_case
    plan = c.connection.prepare(**c.ctx)
    assert plan["transfer"]["items"] == []
    assert plan["transfer"]["holds"][0]["code"] == "CANVAS_COMPARISON_HELD"


def test_explicit_review_stages_one_cell_preserving_original_baseline(attempt_case):
    c = attempt_case
    permit = bind_review(c)
    before = copy.deepcopy(native._state(c.ctx["raw"]))
    original_raw = copy.deepcopy(c.ctx["raw"])
    original_baseline = copy.deepcopy(c.ctx["baseline"])
    plan = c.connection.prepare(**c.ctx)
    transfer = plan["transfer"]
    assert len(transfer["items"]) == len(transfer["requests"]) == 1
    assert transfer["holds"] == transfer["already_present"] == []
    assert transfer["current_attempt_review"] == permit
    assert transfer["baseline"] == original_baseline == c.ctx["baseline"]
    assert plan["teacher_approval"] is plan["publication_allowed"] is False
    assert plan["delivery_policy"] == "SCORE_ONLY"
    item = transfer["items"][0]
    assert item["points"] == 20 and "UNAPPROVED" in item["cell"]["note"]
    actual = copy.deepcopy(before)
    native._apply_requests(actual, transfer["requests"], c.ctx["binding"])
    expected = copy.deepcopy(before)
    expected["sheets"][item["sheet_id"]]["cells"][
        f"{item['row']}:{item['column']}"
    ].update(item["cell"])
    assert actual == expected
    sync = c.ctx["binding"]["sheets"]["_Sync"]
    assert actual["sheets"][sync] == before["sheets"][sync]
    assert c.ctx["raw"] == original_raw
    c.connection.revalidate(
        plan,
        expected_plan_sha256=digest(plan),
        raw=c.ctx["raw"],
        current=c.ctx["current"],
        pin_binding=c.ctx["pin_binding"],
    )


@pytest.mark.parametrize(
    "field,value", [("attempt", 2), ("submitted_at", "2026-10-18T00:31:00Z")]
)
def test_current_attempt_drift_before_send_holds(attempt_case, field, value):
    c = attempt_case
    bind_review(c)
    plan = c.connection.prepare(**c.ctx)
    assert len(plan["transfer"]["items"]) == 1
    c.ctx["current"]["cells"]["101:21"][field] = value
    with pytest.raises(GradebookError):
        c.connection.revalidate(
            plan,
            expected_plan_sha256=digest(plan),
            raw=c.ctx["raw"],
            current=c.ctx["current"],
            pin_binding=c.ctx["pin_binding"],
        )


@pytest.mark.parametrize(
    "guard", ["teacher_grade", "excusal", "deduction", "pending", "custom_note"]
)
def test_explicit_review_preserves_existing_guards(attempt_case, guard):
    c = attempt_case
    cell = c.ctx["current"]["cells"]["101:21"]
    if guard == "teacher_grade":
        cell.update(value=10, grade="10", workflow_state="graded")
    elif guard == "excusal":
        cell.update(excused=True)
    elif guard == "deduction":
        cell.update(points_deducted=2)
    else:
        state = native._state(c.ctx["raw"])
        target = state["sheets"][c.ctx["binding"]["sheets"]["Working"]]["cells"]["5:2"]
        if guard == "pending":
            target["userEnteredValue"] = {"numberValue": 7}
        else:
            target["note"] = "Existing teacher note must be retained."
        c.ctx["raw"] = raw_from_state(state)
    bind_review(c)
    assert_held(c)
