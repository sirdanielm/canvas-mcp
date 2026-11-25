"""Exercise the exclusive registration with a fictional private owner and no network."""

import hashlib
from unittest.mock import AsyncMock, Mock

import pytest
from fastmcp import Client

from canvas_mcp.gradebook.client import GradebookError
from canvas_mcp.gradebook.owner_config import OwnerPolicy, load_owner_policy
from canvas_mcp.gradebook.server import create_server
from canvas_mcp.gradebook.store import Store

COURSES = {"first": "12", "second": "13"}
CHANGE = {"assignment_id": "34", "user_id": "56", "proposed": 10}
OPERATION = "1" * 32
TOKEN = "a" * 43


@pytest.fixture
def setup(tmp_path):
    store = Store(tmp_path / "state")
    owner = Mock()
    owner.prepare = AsyncMock(return_value={"ready_for_confirmation": True})
    owner.confirm = AsyncMock(return_value={"status": "verified"})
    owner.reconcile = AsyncMock(return_value={"canvas_writes": 0})
    owner.status.return_value = {"status": "verified"}
    factory = Mock(return_value=owner)
    policy = OwnerPolicy(
        Mock(return_value=True),
        Mock(return_value=False),
        checklist_score_owner_factory=factory,
    )
    options = dict(
        enable_push=True,
        enable_exact_checklist_profile=True,
        checklist_activation_check=Mock(return_value=None),
        **policy.server_options(),
    )
    return store, owner, factory, options


@pytest.mark.parametrize(
    "override",
    [
        {"enable_push": False},
        {"enable_exact_checklist_profile": False},
        {"enable_exact_checklist_profile": 1},
        {"enable_comments": True},
        {"enable_qualified_comments": True},
        {"comment_releases": {}},
        {"comment_release_factory": Mock()},
        {"get_refresh_control": object()},
        {"unit1_score_handler_factory": Mock()},
        {"unit1_pair_score_handler_factory": Mock()},
        {"source_score_scope": None},
        {"protected_score_scope": None},
        {"checklist_activation_check": None},
        {"checklist_activation_check": lambda: False},
        {"checklist_score_owner_factory": None},
    ],
)
def test_incomplete_or_mixed_profile_holds_before_owner_or_ledger(setup, override):
    store, _, factory, options = setup
    with pytest.raises(GradebookError):
        create_server(Mock(), store, COURSES, **(options | override))
    factory.assert_not_called()
    assert not (store.root / "push-ledger.sqlite3").exists()


def test_policy_keeps_existing_default_surface_unconfigured():
    assert "checklist_score_owner_factory" not in load_owner_policy().server_options()


@pytest.mark.parametrize("factory", ["lambda *args, **kwargs: None", "True"])
def test_pinned_policy_validates_checklist_factory(tmp_path, factory):
    path = tmp_path / "fictional_owner.py"
    path.write_text(
        "from canvas_mcp.gradebook.owner_config import OwnerPolicy\n"
        "def create_owner_policy():\n"
        "    return OwnerPolicy(lambda *args: True, lambda *args: False, "
        f"checklist_score_owner_factory={factory})\n"
    )
    path.chmod(0o600)
    pin = hashlib.sha256(path.read_bytes()).hexdigest()
    if factory == "True":
        with pytest.raises(GradebookError):
            load_owner_policy(path, pin)
    else:
        options = load_owner_policy(path, pin).server_options()
        assert callable(options["checklist_score_owner_factory"])
        assert "enable_exact_checklist_profile" not in options


def test_owner_startup_error_is_private(setup):
    store, _, factory, options = setup
    factory.side_effect = ValueError("private fixture detail")
    with pytest.raises(
        GradebookError, match="Private checklist owner is unavailable"
    ) as error:
        create_server(Mock(), store, COURSES, **options)
    assert "private fixture detail" not in str(error.value)


async def test_four_tools_route_only_to_configured_owner(setup):
    store, owner, factory, options = setup
    server = create_server(Mock(), store, COURSES, **options)
    args = {"course": "first", "operation_id": OPERATION}
    async with Client(server) as mcp:
        tools = {t.name: t for t in await mcp.list_tools()}
        assert set(tools) == {
            "prepare_gradebook_push",
            "confirm_gradebook_push",
            "get_gradebook_push_status",
            "reconcile_gradebook_push",
        }
        assert tools["confirm_gradebook_push"].annotations.destructive_hint is True
        assert tools["prepare_gradebook_push"].annotations.read_only_hint is False
        assert tools["reconcile_gradebook_push"].annotations.read_only_hint is False
        assert tools["get_gradebook_push_status"].annotations.read_only_hint is True
        review_id, _ = store.save("review", {"course_id": "12", "changes": [CHANGE]})
        await mcp.call_tool(
            "prepare_gradebook_push", {"course": "first", "review_id": review_id}
        )
        await mcp.call_tool(
            "confirm_gradebook_push", {**args, "confirmation_token": TOKEN}
        )
        await mcp.call_tool("get_gradebook_push_status", args)
        await mcp.call_tool("reconcile_gradebook_push", args)
    assert factory.call_args.args[0].store is store
    owner.prepare.assert_awaited_once_with("12", review_id)
    owner.confirm.assert_awaited_once_with("12", OPERATION, TOKEN)
    owner.status.assert_called_once_with("12", OPERATION)
    owner.reconcile.assert_awaited_once_with("12", OPERATION)


@pytest.mark.parametrize(
    "invalid",
    [
        {"course": "12"},
        {"operation_id": "../push"},
        {"confirmation_token": "x"},
    ],
)
async def test_unbound_or_malformed_request_stops_before_owner(setup, invalid):
    store, owner, _, options = setup
    server = create_server(Mock(), store, COURSES, **options)
    async with Client(server) as mcp:
        args = {
            "course": "first",
            "operation_id": OPERATION,
            "confirmation_token": TOKEN,
        }
        result = await mcp.call_tool("confirm_gradebook_push", args | invalid)
    assert result.data["retry_writes"] is False
    owner.confirm.assert_not_awaited()


async def test_withdrawn_activation_stops_all_calls_and_owner_final_guard(setup):
    store, owner, factory, options = setup
    server = create_server(Mock(), store, COURSES, **options)
    # The launcher may withdraw approval after registration.
    options["checklist_activation_check"].return_value = False
    with pytest.raises(GradebookError):
        factory.call_args.kwargs["assert_active"]()
    async with Client(server) as mcp:
        args = {"course": "first", "operation_id": OPERATION}
        for name, params in (
            ("prepare_gradebook_push", {"course": "first", "review_id": "a" * 64}),
            ("confirm_gradebook_push", {**args, "confirmation_token": TOKEN}),
            ("get_gradebook_push_status", args),
            ("reconcile_gradebook_push", args),
        ):
            assert "error" in (await mcp.call_tool(name, params)).data
    assert not owner.method_calls


def test_mutable_policy_rechecked_on_exact_stored_review(setup):
    store, _, factory, options = setup
    create_server(Mock(), store, COURSES, **options)
    guard = factory.call_args.kwargs["assert_target_authority"]
    review_id, _ = store.save("review", {"course_id": "12", "changes": [CHANGE]})
    target = {"course_id": "12", "review_id": review_id, **CHANGE}
    assert guard("12", review_id, target) is None
    options["source_score_scope"].assert_called_with("12", review_id, [CHANGE])
    options["protected_score_scope"].assert_called_with("12", [CHANGE])
    for key in ("user_id", "assignment_id", "course_id", "review_id"):
        with pytest.raises(GradebookError):
            guard("12", review_id, target | {key: "different"})
    with pytest.raises(GradebookError):
        guard("13", review_id, target)
    for name, denial in (("source_score_scope", 1), ("protected_score_scope", True)):
        options[name].return_value = denial
        with pytest.raises(GradebookError):
            guard("12", review_id, target)
        options[name].return_value = name == "source_score_scope"
    options["checklist_activation_check"].return_value = False
    with pytest.raises(GradebookError):
        guard("12", review_id, target)


@pytest.mark.parametrize("changes", [[], [CHANGE, CHANGE], [{}]])
def test_guard_requires_one_exact_target(setup, changes):
    store, _, factory, options = setup
    create_server(Mock(), store, COURSES, **options)
    review_id, _ = store.save("review", {"course_id": "12", "changes": changes})
    with pytest.raises(GradebookError):
        factory.call_args.kwargs["assert_target_authority"](
            "12", review_id, {"review_id": review_id, "course_id": "12"}
        )
    options["source_score_scope"].assert_not_called()
