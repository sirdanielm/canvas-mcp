"""Typed paper-to-EDIT integration with authenticated fictional owner fixtures."""

import copy
import hashlib
import importlib.util
import json
import os
import sys
from pathlib import Path

import pytest
from test_gradebook import snapshot as snapshot
from test_gradebook_native import binding as binding
from test_gradebook_native import initial_raw, raw_from_state
from test_localgrass_application import configured as configured
from test_localgrass_edit_owner import composed as composed
from test_localgrass_teacher_edit import integrated as integrated

from canvas_mcp.gradebook import localgrass_application as application
from canvas_mcp.gradebook import native
from canvas_mcp.gradebook.client import GradebookError
from canvas_mcp.gradebook.localgrass_teacher_edit import LocalGrAssEditConnection
from canvas_mcp.gradebook.model import digest
from canvas_mcp.gradebook.store import Store

external = os.environ.get("LOCALGRASS_TEST_ROOT")
if not external:
    pytest.skip(
        "Explicit reviewed LocalGrAss test checkout required", allow_module_level=True
    )
root = Path(external)
sys.path[:0] = [str(root), str(root / "tests")]
spec = importlib.util.spec_from_file_location(
    "unit1_authenticated_fixture", root / "tests/test_teacher_edit_unit1.py"
)
assert spec is not None and spec.loader is not None
domain_fixture = importlib.util.module_from_spec(spec)
spec.loader.exec_module(domain_fixture)


@pytest.fixture
def unit1(tmp_path, snapshot, binding):
    domain = domain_fixture.AuthenticatedUnit1SourceTests()
    domain.setUp()
    try:
        source = domain.source
        selected = source.read()
        maximum = float(selected["payload"]["computation"]["maximum"])
        snapshot["course_workflow_state"] = "available"
        snapshot["assignments"][0]["points_possible"] = maximum
        for student in snapshot["students"]:
            if student["id"] == "101":
                student["sections"] = ["Fictional"]
        snapshot["cells"]["101:21"].update(
            value=2,
            grade="2",
            attempt=3,
            submitted_at="2026-10-10T12:00:00Z",
            grade_matches_current_submission=True,
        )
        mapping = [
            {
                "assignment_key": selected["assignment_id"],
                "student_track": selected["payload"]["dependencies"]["scope"]["track"],
                "course_id": "12",
                "assignment_id": "21",
                "section": "Fictional",
                "score_scale": "RAW_IDENTITY",
                "maximum": maximum,
            }
        ]
        path = tmp_path / "reviewed-mapping.json"
        path.write_text(json.dumps(mapping))
        store = Store(tmp_path / "canvas")
        connection = LocalGrAssEditConnection(
            source,
            store,
            assignment_bindings_path=path,
            expected_assignment_bindings_sha256=hashlib.sha256(
                path.read_bytes()
            ).hexdigest(),
            section="Fictional",
            registry_path=tmp_path / "existing-registry.json",
            shared_tool=tmp_path / "existing-shared-tool.py",
        )
        identity = selected["source_receipt"]["identity"]
        context = {
            "raw": initial_raw(snapshot, binding),
            "binding": binding,
            "baseline": snapshot,
            "current": copy.deepcopy(snapshot),
            "pin_binding": {
                "registry_sha256": identity["registry_sha256"],
                "roster_sha256": identity["snapshot_sha256"],
                "by_pin": {"0000": "101"},
            },
        }
        yield connection, context, domain, mapping, path
    finally:
        domain.doCleanups()


def test_authenticated_owner_points_and_full_final_feedback_prepare_without_canvas_capture(
    unit1,
):
    connection, context, domain, _, _ = unit1
    before = domain.fx.registry.connection.total_changes
    plan = connection.prepare(**context)
    record, decision = plan["transfer"]["record"], plan["transfer"]["decision"]
    assert record["raw_score"] == 24.5
    assert decision["total_score"] == 25
    assert record["raw_maximum"] == decision["points_possible"] == 32
    assert record["form"] == "CT-A"
    assert record["paper_attempt"] == domain.fx.fx.expected["subject"]["attempt"]
    assert record["canvas_attempt"] == 3
    assert plan["canvas_writes"] == plan["sheets_writes"] == 0
    assert domain.fx.registry.connection.total_changes == before
    assert not (connection.store.root / "receipt").exists()
    update = plan["transfer"]["requests"][0]["updateCells"]
    assert update["fields"] == "userEnteredValue,note"
    assert update["rows"][0]["values"][0]["userEnteredValue"] == {"numberValue": 25}
    assert update["rows"][0]["values"][0]["note"].endswith(decision["feedback"])
    connection.revalidate(
        plan,
        expected_plan_sha256=digest(plan),
        raw=context["raw"],
        current=context["current"],
        pin_binding=context["pin_binding"],
    )


@pytest.mark.parametrize(
    "field,value",
    [
        ("maximum", 100),
        ("score_scale", "PERCENT"),
        ("section", "other"),
        ("course_id", "99"),
        ("assignment_key", "other"),
    ],
)
def test_typed_adapter_never_infers_mapping_or_converts_form_points(
    unit1, field, value
):
    connection, context, _, mapping, path = unit1
    mapping[0][field] = value
    path.write_text(json.dumps(mapping))
    connection.assignment_sha256 = hashlib.sha256(path.read_bytes()).hexdigest()
    with pytest.raises(GradebookError):
        connection.prepare(**context)


@pytest.mark.parametrize(
    "change", ["attempt", "submission_time", "teacher_note", "identity", "source"]
)
def test_prepared_typed_plan_holds_current_target_or_source_drift(unit1, change):
    connection, context, domain, _, _ = unit1
    plan = connection.prepare(**context)
    if change == "attempt":
        context["current"]["cells"]["101:21"]["attempt"] = 4
    elif change == "submission_time":
        context["current"]["cells"]["101:21"]["submitted_at"] = "2026-10-11T12:00:00Z"
    elif change == "teacher_note":
        state = native._state(context["raw"])
        state["sheets"][2]["cells"]["5:2"]["note"] = "Retained teacher correction"
        context["raw"] = raw_from_state(state)
    elif change == "identity":
        context["pin_binding"]["roster_sha256"] = "f" * 64
    else:
        domain.fx.workflow.paper_source_reader = None
    with pytest.raises((GradebookError, domain_fixture.AuthenticatedSourceError)):
        connection.revalidate(
            plan,
            expected_plan_sha256=digest(plan),
            raw=context["raw"],
            current=context["current"],
            pin_binding=context["pin_binding"],
        )


@pytest.mark.parametrize("attempt", [None, -1, True])
def test_paper_attempt_never_supplies_missing_canvas_attempt(unit1, attempt):
    connection, context, _, _, _ = unit1
    context["current"]["cells"]["101:21"]["attempt"] = attempt
    with pytest.raises(GradebookError, match="OBSERVED_CANVAS_ATTEMPT_REQUIRED"):
        connection.prepare(**context)


def test_actual_zero_canvas_attempt_is_retained_and_later_submission_holds(unit1):
    connection, context, _, _, _ = unit1
    context["current"]["cells"]["101:21"].update(attempt=0, submitted_at=None)
    context["baseline"]["cells"]["101:21"].update(attempt=0, submitted_at=None)
    context["raw"] = initial_raw(context["baseline"], context["binding"])
    plan = connection.prepare(**context)
    assert plan["transfer"]["record"]["canvas_attempt"] == 0
    assert plan["transfer"]["record"]["paper_attempt"] != "0"
    context["current"]["cells"]["101:21"]["attempt"] = 1
    with pytest.raises(GradebookError):
        connection.revalidate(
            plan,
            expected_plan_sha256=digest(plan),
            raw=context["raw"],
            current=context["current"],
            pin_binding=context["pin_binding"],
        )


def test_unit1_factory_reuses_real_acceptance_without_generic_intake(configured, unit1):
    c, value, path, kwargs, _ = configured
    connection, _, domain, _, _ = unit1
    value["contract"] = application.UNIT1_CONTRACT
    value.pop("source_root")
    value.update(
        decision_id=domain.source.decision_id,
        source_receipt_id=domain.source.receipt_id,
        identity_runtime_root=str(domain.source.identity_runtime_root),
        section="Fictional",
    )
    domain.review.workflow.identity_runtime_root = domain.source.identity_runtime_root
    c.config.update(
        runtime_root=value["identity_runtime_root"],
        assignment_bindings_path=str(connection.assignment_path),
        assignment_bindings_sha256=connection.assignment_sha256,
    )
    c.config_path.write_text(json.dumps(c.config))
    value["staging_config_sha256"] = hashlib.sha256(
        c.config_path.read_bytes()
    ).hexdigest()
    path.write_text(json.dumps(value))
    before = domain.fx.registry.connection.total_changes
    factory = application.build_owner_factory(
        domain.review, None, c.canvas, c.google, c.store, c.journal, **kwargs()
    )
    owner = factory(domain.token, domain.csrf)
    selected = owner.connection.source.read()
    assert selected["payload"]["computation"]["units"] == "FORM_POINTS"
    assert selected["decision"]["score"] == "25"
    assert not hasattr(owner.connection.source, "intake")
    assert domain.fx.registry.connection.total_changes == before
    assert c.calls == {"canvas_reads": 0, "sheets_reads": 0, "posts": []}
    domain.review.workflow.identity_runtime_root = None
    with pytest.raises(GradebookError, match="LOCAL_EDIT_IDENTITY_RUNTIME_CHANGED"):
        application.build_owner_factory(
            domain.review, None, c.canvas, c.google, c.store, c.journal, **kwargs()
        )
