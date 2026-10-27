"""Real authenticated retained proposal to mocked native EDIT, no live systems."""

import copy
import json
import os

import pytest

if not os.environ.get("LOCALGRASS_TEST_ROOT"):
    pytest.skip(
        "Explicit reviewed LocalGrAss checkout required", allow_module_level=True
    )

from test_gradebook import snapshot as snapshot
from test_gradebook_native import binding as binding
from test_gradebook_native import raw_from_state
from test_localgrass_teacher_edit import integrated_source

from canvas_mcp.gradebook import native
from canvas_mcp.gradebook.client import GradebookError
from canvas_mcp.gradebook.localgrass_edit_execution import execute_local_edit_once
from canvas_mcp.gradebook.localgrass_teacher_edit import LocalGrAssEditConnection
from canvas_mcp.gradebook.model import digest
from canvas_mcp.gradebook.teacher_edit_transfer import prepare_transfer


@pytest.fixture
def proposed(tmp_path, snapshot, binding, monkeypatch):
    yield from integrated_source(
        tmp_path, snapshot, binding, monkeypatch, proposal=True
    )


@pytest.mark.asyncio
async def test_unaccepted_pair_stages_and_reads_back_without_acceptance(
    proposed, tmp_path
):
    connection, context, domain, *_ = proposed
    before = domain.registry.connection.total_changes
    plan = connection.prepare(**context)
    assert plan["approval_state"] == "UNAPPROVED"
    assert plan["academic_accepted"] is False
    assert "decision" not in plan["transfer"]
    assert plan["transfer"]["proposal"]["total_score"] == 10
    assert (
        domain.registry.connection.execute(
            "SELECT COUNT(*) FROM workflow_teacher_acceptances"
        ).fetchone()[0]
        == 0
    )
    state = {"raw": context["raw"]}
    sends = []
    output = tmp_path / "existing-stage-output"

    def read():
        return {
            "raw": state["raw"],
            "current": context["current"],
            "pin_binding": context["pin_binding"],
        }

    def write(book, requests):
        receipts = sorted((output / digest(plan)).glob("receipt-*.json"))
        assert json.loads(receipts[-1].read_text())["status"] == "SENDING"
        assert book == "fictional-book" and len(requests) == 1
        update = requests[0]["updateCells"]
        cell = update["rows"][0]["values"][0]
        assert cell["userEnteredValue"] == {"numberValue": 10}
        assert "UNAPPROVED advisory proposal" in cell["note"]
        assert "Teacher-reviewed final content" not in cell["note"]
        assert cell["note"].endswith(domain.source.read()["payload"]["feedback"])
        after = native._state(state["raw"])
        after["sheets"][2]["cells"]["5:2"].update(cell)
        state["raw"] = raw_from_state(after)
        sends.append(copy.deepcopy(requests))

    for _ in range(2):
        result = await execute_local_edit_once(
            connection,
            plan,
            expected_plan_sha256=digest(plan),
            output_root=output,
            read_context=read,
            write_requests=write,
            enabled=True,
        )
        assert result["status"] == "PLANNED_OUTPUT_OBSERVED"
        assert result["canvas_writes"] == 0
        assert result["publication_allowed"] is False
    assert len(sends) == 1
    assert domain.registry.connection.total_changes == before


@pytest.mark.parametrize(
    "change", ["pin", "attempt", "preimage", "source", "draft", "accepted"]
)
def test_exact_source_target_and_preimage_changes_hold(proposed, change):
    connection, context, domain, *_ = proposed
    plan = connection.prepare(**context)
    if change == "pin":
        context["pin_binding"]["by_pin"]["0042"] = "102"
    elif change == "attempt":
        context["current"]["cells"]["101:21"]["attempt"] = 4
    elif change == "preimage":
        state = native._state(context["raw"])
        state["sheets"][2]["cells"]["5:2"]["note"] = "Teacher's later correction"
        context["raw"] = raw_from_state(state)
    elif change == "source":
        domain.original.write_bytes(b"X" * domain.original.stat().st_size)
    else:
        domain.review.save_draft(
            domain.token,
            domain.csrf,
            domain.case_key,
            domain.proposal_id,
            None,
            0,
            "7",
            "Teacher has now decided.",
        )
        if change == "accepted":
            domain.review.accept_draft(domain.token, domain.csrf, domain.case_key, 1)
    with pytest.raises((GradebookError, ValueError)):
        connection.revalidate(
            plan,
            expected_plan_sha256=digest(plan),
            raw=context["raw"],
            current=context["current"],
            pin_binding=context["pin_binding"],
        )


@pytest.mark.parametrize("field", ["note", "score"])
def test_existing_teacher_edits_are_not_overwritten(proposed, field):
    connection, context, *_ = proposed
    state = native._state(context["raw"])
    cell = state["sheets"][2]["cells"]["5:2"]
    if field == "note":
        cell["note"] = "Teacher's private correction"
    else:
        cell["userEnteredValue"] = {"numberValue": 8}
    context["raw"] = raw_from_state(state)
    with pytest.raises(GradebookError, match="EXISTING_TEACHER_(NOTE|EDIT)_PRESERVED"):
        connection.prepare(**context)


def test_accepted_apis_refuse_unapproved_source_or_selection(proposed):
    connection, context, _, _, _, kwargs, store = proposed
    with pytest.raises(GradebookError, match="AUTHENTICATED_SOURCE_REQUIRED"):
        LocalGrAssEditConnection(connection.source, store, **kwargs)
    plan = connection.prepare(**context)
    with pytest.raises(GradebookError, match="TEACHER_DECISION_INCOMPLETE"):
        prepare_transfer(
            plan["transfer"]["record"],
            plan["transfer"]["proposal"],
            **context,
            source_check=lambda *unused: None,
        )


@pytest.mark.asyncio
async def test_uncertain_proposal_send_is_not_replayed(proposed, tmp_path):
    connection, context, *_ = proposed
    plan = connection.prepare(**context)
    sends = []

    def write(*args):
        sends.append(args)
        raise TimeoutError("fictional uncertain send")

    def read():
        return {
            "raw": context["raw"],
            "current": context["current"],
            "pin_binding": context["pin_binding"],
        }

    for _ in range(2):
        result = await execute_local_edit_once(
            connection,
            plan,
            expected_plan_sha256=digest(plan),
            output_root=tmp_path / "existing-owner-root",
            read_context=read,
            write_requests=write,
            enabled=True,
        )
        assert result["status"] == "UNCERTAIN_RECONCILIATION_REQUIRED"
    assert len(sends) == 1


@pytest.fixture
def unit1_proposed(tmp_path, snapshot, binding):
    from test_localgrass_unit1_transfer import unit1_source

    yield from unit1_source(tmp_path, snapshot, binding, proposal=True)


def test_unit1_unapproved_pair_uses_bound_form_points_without_acceptance(
    unit1_proposed,
):
    connection, context, domain, *_ = unit1_proposed
    before = domain.fx.registry.connection.total_changes
    plan = connection.prepare(**context)
    proposal = plan["transfer"]["proposal"]
    assert proposal["total_score"] == 24.5
    assert proposal["points_possible"] == 32
    assert proposal["approval_state"] == "UNAPPROVED"
    assert proposal["academic_accepted"] is False
    assert domain.fx.count("workflow_teacher_acceptances") == 0
    assert domain.fx.registry.connection.total_changes == before
    assert (
        "UNAPPROVED advisory proposal"
        in plan["transfer"]["requests"][0]["updateCells"]["rows"][0]["values"][0][
            "note"
        ]
    )
    connection.revalidate(
        plan,
        expected_plan_sha256=digest(plan),
        raw=context["raw"],
        current=context["current"],
        pin_binding=context["pin_binding"],
    )


@pytest.fixture
def proposal_owner(proposed, tmp_path, monkeypatch):
    from test_localgrass_edit_owner import composed_source

    yield from composed_source(proposed, tmp_path, monkeypatch)


@pytest.mark.asyncio
async def test_existing_owner_prepares_executes_and_reconciles_unapproved_pair(
    proposal_owner,
):
    c = proposal_owner
    before = c.domain.registry.connection.total_changes
    prepared = await c.owner.prepare()
    plan_id = prepared["plan_id"]
    plan = c.store.load("review", plan_id)
    assert plan["approval_state"] == "UNAPPROVED"
    for _ in range(2):
        result = await c.owner.execute(plan_id, enabled=True)
        assert result["status"] == "PLANNED_OUTPUT_OBSERVED"
        assert result["canvas_writes"] == 0
        assert result["publication_allowed"] is False
    assert len(c.calls["posts"]) == 1
    assert c.domain.registry.connection.total_changes == before
    assert (
        c.domain.registry.connection.execute(
            "SELECT COUNT(*) FROM workflow_teacher_acceptances"
        ).fetchone()[0]
        == 0
    )
    assert (
        "UNAPPROVED advisory proposal"
        in native._state(c.state["raw"])["sheets"][2]["cells"]["5:2"]["note"]
    )


def test_unit1_proposal_percent_scale_uses_advisory_not_teacher_final(unit1_proposed):
    from test_localgrass_unit1_transfer import percent_mapping

    connection, context, domain, *_ = percent_mapping(unit1_proposed)
    plan = connection.prepare(**context)
    assert plan["transfer"]["record"]["raw_score"] == 24.5
    assert plan["transfer"]["proposal"]["total_score"] == 77
    assert plan["transfer"]["proposal"]["points_possible"] == 100
    assert domain.fx.count("workflow_teacher_acceptances") == 0


@pytest.fixture
def proposal_configured(proposal_owner, tmp_path):
    from test_localgrass_application import configured_source

    return configured_source(proposal_owner, tmp_path)


@pytest.mark.asyncio
async def test_configured_factory_runs_unapproved_route_without_acceptance(
    proposal_configured,
):
    from canvas_mcp.gradebook import localgrass_application as application

    c, value, _, kwargs, owners = proposal_configured
    assert value["contract"] == application.PROPOSAL_CONTRACT
    assert "decision_id" not in value
    factory = application.build_owner_factory(*owners(), **kwargs())
    owner = factory(c.domain.token, c.domain.csrf)
    assert owner.connection.source.result_id == value["result_id"]
    assert not hasattr(owner.connection.source, "decision_id")
    prepared = await owner.prepare()
    result = await owner.execute(prepared["plan_id"], enabled=True)
    assert result["status"] == "PLANNED_OUTPUT_OBSERVED"
    assert len(c.calls["posts"]) == 1
    assert (
        c.domain.registry.connection.execute(
            "SELECT COUNT(*) FROM workflow_teacher_acceptances"
        ).fetchone()[0]
        == 0
    )


def test_accepted_browser_application_cannot_adopt_proposal_configuration(
    proposal_configured,
):
    from canvas_mcp.gradebook import localgrass_application as application

    _, _, _, kwargs, owners = proposal_configured
    with pytest.raises(GradebookError, match="PROPOSAL_CONFIG_REQUIRES_OWNER_WORKFLOW"):
        application.build_application(*owners(), **kwargs())


def test_proposal_configuration_rejects_decision_alias_and_missing_case(
    proposal_configured,
):
    from canvas_mcp.gradebook import localgrass_application as application

    c, value, path, kwargs, owners = proposal_configured
    value["decision_id"] = value["result_id"]
    path.write_text(json.dumps(value))
    with pytest.raises(GradebookError, match="CONFIGURATION_INVALID"):
        application.load_configuration(path, kwargs()["expected_config_sha256"])
    value.pop("decision_id")
    value["result_id"] = "f" * 64
    path.write_text(json.dumps(value))
    factory = application.build_owner_factory(*owners(), **kwargs())
    with pytest.raises(GradebookError, match="LOCAL_EDIT_CASE_OR_CONFIG_HELD"):
        factory(c.domain.token, c.domain.csrf)
    assert c.calls["posts"] == []
