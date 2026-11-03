"""Fictional existing-ID edits on the real Store/Ledger; denied real network."""

import copy
import hashlib
import json
from datetime import UTC, datetime
from typing import Any
from urllib.parse import parse_qs

import httpx
import pytest
from test_gradebook import snapshot as snapshot
from test_gradebook_publish import comment_system as comment_system
from test_gradebook_publish import prepared_comment
from test_gradebook_publish import system as system

from canvas_mcp.gradebook import comment_edit as edit
from canvas_mcp.gradebook.client import GradebookError
from canvas_mcp.gradebook.comment_policy import FORMAT_CONTRACT_SHA256
from canvas_mcp.gradebook.ledger import Ledger
from canvas_mcp.gradebook.model import digest
from canvas_mcp.gradebook.publish import OwnerControls, Publisher


@pytest.fixture(autouse=True)
def deny_network(monkeypatch: pytest.MonkeyPatch) -> None:
    import socket

    def deny(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("REAL_NETWORK_FORBIDDEN")

    monkeypatch.setattr(socket.socket, "connect", deny)
    monkeypatch.setattr(socket.socket, "connect_ex", deny)
    monkeypatch.setattr(socket, "create_connection", deny)
    monkeypatch.setattr(socket, "getaddrinfo", deny)


@pytest.fixture
def editing(comment_system: Any) -> Any:
    publisher, state, base = comment_system
    state["submission"].update(
        manual_note="Fictional teacher note", formula="=SYNTHETIC"
    )
    state["submission"]["submission_comments"] += [
        {"id": 503, "author_id": 778, "comment": "Unrelated fictional feedback"}
    ]
    state.update(
        edit_puts=[],
        owner_valid=True,
        owner_qc="c" * 64,
        edit_drift={},
        edit_read_failure=False,
    )
    old = copy.deepcopy(state["submission"]["submission_comments"][0])
    body = "0123 | A2 | Core_A\nMC8: read-A | key-D | -1"
    envelope = {
        **base,
        "category": "UNIT2_FEEDBACK",
        "comment": body,
        "action": edit.ACTION,
        "comment_id": "501",
        "old_comment": old,
        "old_body_sha256": hashlib.sha256(old["comment"].encode()).hexdigest(),
        "old_comment_sha256": digest(old),
        "new_body_sha256": hashlib.sha256(body.encode()).hexdigest(),
        "qc_sha256": "c" * 64,
        "formatter_sha256": "d" * 64,
        "format_contract_sha256": FORMAT_CONTRACT_SHA256,
        "expected_header": "0123 | A2 | Core_A",
        "disposition": "QUALIFIED_FOR_EXACT_REVIEW",
    }
    previous = publisher.client.http._transport.handler

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method != "PUT":
            if (
                state["edit_puts"]
                and state["edit_read_failure"]
                and "/submissions/" in request.url.path
            ):
                raise httpx.ReadTimeout("Fictional readback loss")
            return previous(request)
        assert (
            request.url.path
            == "/api/v1/courses/12/assignments/21/submissions/101/comments/501"
        )
        fields = parse_qs(request.content.decode())
        assert set(fields) == {"comment"}
        assert request.headers["Content-Type"] == "application/x-www-form-urlencoded"
        state["edit_puts"].append({"url": str(request.url), "fields": fields})
        op = state.get("current_operation")
        if op:
            assert publisher.ledger.operation(op)["items"][0]["status"] == "sending"
            assert (
                publisher.store.load("push", publisher.ledger.operation(op)["plan_id"])[
                    "action"
                ]
                == edit.ACTION
            )
        behavior = state["behavior"]
        if behavior == "reject":
            return httpx.Response(403)
        if behavior in {"timeout_unapplied", "server_error", "redirect"}:
            if behavior == "timeout_unapplied":
                raise httpx.ReadTimeout("Fictional unknown send")
            return httpx.Response(
                500 if behavior == "server_error" else 302,
                headers={"Location": "https://fictional.invalid/forbidden"},
            )
        selected = state["submission"]["submission_comments"][0]
        selected.update(
            comment=fields["comment"][0], edited_at=datetime.now(UTC).isoformat()
        )
        state["submission"]["updated_at"] = datetime.now(UTC).isoformat()
        state["submission"].update(state["edit_drift"])
        if behavior == "timeout_applied":
            raise httpx.ReadTimeout("Fictional response loss")
        return httpx.Response(
            200, json={**selected, "id": 999 if behavior == "bad_id" else 501}
        )

    publisher.client.http._transport.handler = handler

    async def fresh(course: str, item: dict[str, Any]) -> None:
        assert course == "12" and item["action"] == edit.ACTION

    def check(course: str, item: dict[str, Any]) -> None:
        if not state["owner_valid"]:
            raise GradebookError("Fictional source/QC owner hold")

    def bind(plan: dict[str, Any]) -> dict[str, Any]:
        return {
            "kind": "FICTIONAL_OWNER_BINDING",
            "unit": "UNIT2",
            "source_envelope": digest(plan["envelope"]),
            "current_qc": state["owner_qc"],
        }

    controls = OwnerControls(fresh, check, bind)
    return publisher, state, envelope, controls


async def preview(editing: Any) -> dict[str, Any]:
    publisher, state, envelope, controls = editing
    (publisher.store.root / "inbox/edit.json").write_text(json.dumps(envelope), encoding="utf-8")
    result = await edit.prepare_comment_edit(
        publisher, "12", "edit.json", digest(envelope), owner_controls=controls
    )
    if result["ready_for_confirmation"]:
        state["current_operation"] = result["operation_id"]
    return result


async def confirm(editing: Any, result: dict[str, Any]) -> dict[str, Any]:
    publisher, _, _, controls = editing
    return await edit.confirm_comment_edit(
        publisher,
        "12",
        result["operation_id"],
        result["confirmation_token"],
        enabled=True,
        owner_controls=controls,
    )


async def test_exact_same_id_edit_once_and_all_other_values_preserved(
    editing: Any,
) -> None:
    publisher, state, envelope, _ = editing
    protected = copy.deepcopy(state["submission"])
    result = await preview(editing)
    assert result["expires_in_seconds"] == 600 and not state["edit_puts"]
    operation = publisher.ledger.operation(result["operation_id"])
    assert operation["expires"] - operation["created"] == 600
    text = open(result["review_file"], encoding="utf-8").read()
    assert (
        edit.ACTION in text and "Exact old body" in text and "Exact replacement" in text
    )
    done = await confirm(editing, result)
    assert done["counts"] == {"verified": 1}
    assert len(state["edit_puts"]) == 1
    assert state["edit_puts"][0]["fields"] == {"comment": [envelope["comment"]]}
    assert state["submission"]["submission_comments"][0]["id"] == 501
    assert (
        state["submission"]["submission_comments"][1:]
        == protected["submission_comments"][1:]
    )
    for key in protected.keys() - {"submission_comments", "updated_at"}:
        assert type(state["submission"][key]) is type(protected[key])
        assert state["submission"][key] == protected[key]
    with pytest.raises(GradebookError, match="already consumed"):
        await confirm(editing, result)
    assert len(state["edit_puts"]) == 1


@pytest.mark.parametrize(
    "change",
    [
        "old_body",
        "cid",
        "author",
        "target",
        "attempt",
        "score",
        "typed_grade",
        "manual_note",
        "formula",
        "other_comment",
    ],
)
async def test_freshness_drift_before_send_never_writes(
    editing: Any, change: str
) -> None:
    publisher, state, _, _ = editing
    result = await preview(editing)
    sub = state["submission"]
    if change == "old_body":
        sub["submission_comments"][0]["comment"] = "Changed fictional old text"
    elif change == "cid":
        sub["submission_comments"][0]["id"] = 999
    elif change == "author":
        sub["submission_comments"][0]["author_id"] = 778
    elif change == "other_comment":
        sub["submission_comments"][1]["comment"] = "Changed unrelated text"
    else:
        field, value = {
            "target": ("user_id", 102),
            "attempt": ("attempt", 3),
            "score": ("score", 11),
            "typed_grade": ("grade", 10),
            "manual_note": ("manual_note", "Changed note"),
            "formula": ("formula", "=CHANGED"),
        }[change]
        sub[field] = value
    with pytest.raises(GradebookError):
        await confirm(editing, result)
    assert state["edit_puts"] == []
    assert publisher.ledger.summary(result["operation_id"])["counts"] == {"not_sent": 1}


@pytest.mark.parametrize(
    "field,value",
    [("score", 11), ("grade", 10), ("manual_note", "Changed"), ("formula", "=CHANGED")],
)
async def test_post_send_protected_drift_stays_uncertain(
    editing: Any, field: str, value: Any
) -> None:
    publisher, state, _, _ = editing
    result = await preview(editing)
    state["edit_drift"][field] = value
    done = await confirm(editing, result)
    assert done["counts"] == {"uncertain": 1} and len(state["edit_puts"]) == 1
    with publisher.ledger.connect() as db:
        assert db.execute("SELECT COUNT(*) FROM target_locks").fetchone()[0] == 1


@pytest.mark.parametrize(
    "behavior,outcome",
    [
        ("timeout_applied", "observed_applied"),
        ("timeout_unapplied", "uncertain"),
        ("bad_id", "observed_applied"),
        ("server_error", "uncertain"),
        ("redirect", "uncertain"),
    ],
)
async def test_unknown_outcome_get_only_never_retries(
    editing: Any, behavior: str, outcome: str
) -> None:
    publisher, state, _, _ = editing
    result = await preview(editing)
    state["behavior"] = behavior
    done = await confirm(editing, result)
    assert done["status"] == "uncertain" and len(state["edit_puts"]) == 1
    restarted = Publisher(
        publisher.client, publisher.store, Ledger(publisher.store.root)
    )
    done = await edit.reconcile_comment_edit(restarted, "12", result["operation_id"])
    assert done["counts"] == {outcome: 1}
    with pytest.raises(GradebookError, match="already consumed"):
        await confirm(editing, result)
    assert len(state["edit_puts"]) == 1


async def test_valid_response_lost_get_readback_can_reconcile_after_restart(
    editing: Any,
) -> None:
    publisher, state, _, _ = editing
    result = await preview(editing)
    state["edit_read_failure"] = True
    with pytest.raises(GradebookError):
        await confirm(editing, result)
    assert (
        publisher.ledger.operation(result["operation_id"])["items"][0][
            "response_comment_id"
        ]
        == "501"
    )
    state["edit_read_failure"] = False
    done = await edit.reconcile_comment_edit(publisher, "12", result["operation_id"])
    assert done["counts"] == {"verified": 1} and len(state["edit_puts"]) == 1


@pytest.mark.parametrize(
    "case",
    ["wrong_token", "expired", "disabled", "owner_hold", "qc_drift", "source_body"],
)
async def test_approval_and_source_gates_never_write(
    editing: Any, monkeypatch: pytest.MonkeyPatch, case: str
) -> None:
    publisher, state, envelope, controls = editing
    result = await preview(editing)
    kwargs = {"enabled": True, "owner_controls": controls}
    token = result["confirmation_token"]
    if case == "wrong_token":
        token = "fictional-wrong-token"
    elif case == "expired":
        op = publisher.ledger.operation(result["operation_id"])
        monkeypatch.setattr(
            "canvas_mcp.gradebook.ledger.time.time", lambda: op["expires"] + 0.001
        )
    elif case == "disabled":
        kwargs["enabled"] = False
    elif case == "owner_hold":
        state["owner_valid"] = False
    elif case == "qc_drift":
        state["owner_qc"] = "e" * 64
    elif case == "source_body":
        envelope["comment"] += "Changed"
        (publisher.store.root / "inbox/edit.json").write_text(json.dumps(envelope), encoding="utf-8")
    with pytest.raises(GradebookError):
        await edit.confirm_comment_edit(
            publisher, "12", result["operation_id"], token, **kwargs
        )
    assert state["edit_puts"] == []


async def test_duplicate_intent_cannot_bypass_with_renewed_qc_and_reverted_body(
    editing: Any,
) -> None:
    _, state, envelope, _ = editing
    result = await preview(editing)
    duplicate = await preview(editing)
    state["current_operation"] = result["operation_id"]
    await confirm(editing, result)
    state["submission"]["submission_comments"][0] = copy.deepcopy(
        envelope["old_comment"]
    )
    with pytest.raises(GradebookError, match="may have been sent"):
        await confirm(editing, duplicate)
    state["owner_qc"] = envelope["qc_sha256"] = "e" * 64
    renewed = await preview(editing)
    with pytest.raises(GradebookError, match="may have been sent"):
        await confirm(editing, renewed)
    assert len(state["edit_puts"]) == 1


@pytest.mark.parametrize(
    "field,value",
    [
        ("action", "DELETE"),
        ("category", "UNIT1_FEEDBACK"),
        ("qc_sha256", "bad"),
        ("format_contract_sha256", "f" * 64),
        ("comment_id", "501/other"),
        ("new_body_sha256", "f" * 64),
    ],
)
async def test_invalid_envelope_never_creates_token(
    editing: Any, field: str, value: Any
) -> None:
    publisher, state, envelope, _ = editing
    envelope[field] = value
    with pytest.raises(GradebookError):
        await preview(editing)
    assert not state["edit_puts"]
    with publisher.ledger.connect() as db:
        assert db.execute("SELECT COUNT(*) FROM operations").fetchone()[0] == 0


async def test_conditional_never_becomes_approved_or_prepared(editing: Any) -> None:
    publisher, state, envelope, _ = editing
    envelope["disposition"] = "CONDITIONAL"
    done = await preview(editing)
    assert not done["ready_for_confirmation"] and not state["requests"]
    with publisher.ledger.connect() as db:
        assert db.execute("SELECT COUNT(*) FROM operations").fetchone()[0] == 0


async def test_cross_route_tokens_and_wrong_course_never_consume_edit(
    editing: Any,
) -> None:
    publisher, state, _, controls = editing
    result = await preview(editing)
    with pytest.raises(GradebookError):
        await publisher.confirm_comment(
            "12", result["operation_id"], result["confirmation_token"]
        )
    with pytest.raises(GradebookError, match="owner controls"):
        await publisher.confirm(
            "12", result["operation_id"], result["confirmation_token"]
        )
    with pytest.raises(GradebookError):
        await edit.confirm_comment_edit(
            publisher,
            "13",
            result["operation_id"],
            result["confirmation_token"],
            enabled=True,
            owner_controls=controls,
        )
    assert publisher.ledger.operation(result["operation_id"])["status"] == "prepared"
    assert not state["edit_puts"]


async def test_existing_append_plan_and_score_window_unchanged(
    comment_system: Any,
) -> None:
    publisher, state, _ = comment_system
    result = await prepared_comment(comment_system)
    with pytest.raises(GradebookError, match="not this exact"):
        await edit.reconcile_comment_edit(publisher, "12", result["operation_id"])
    done = await publisher.confirm_comment(
        "12", result["operation_id"], result["confirmation_token"]
    )
    assert done["counts"] == {"verified": 1} and len(state["forms"]) == 1
    assert set(state["forms"][0]) == {"comment[text_comment]", "comment[group_comment]"}
    score_id, _ = publisher.ledger.prepare("f" * 64, ["fictional-other-target"])
    score = publisher.ledger.operation(score_id)
    assert score["expires"] - score["created"] == 600


@pytest.mark.parametrize(
    "field,value",
    [
        ("group_comment_id", 12),
        ("group_comment_id", False),
        ("provisional_grade_id", 0),
        ("assessment_request_id", 12),
        ("draft", True),
        ("draft", 0),
        ("hidden", None),
        ("anonymous", True),
        ("author_id", 778),
    ],
)
async def test_unsupported_or_foreign_comment_is_held_before_preview(
    editing: Any, field: str, value: Any
) -> None:
    publisher, state, envelope, _ = editing
    state["submission"]["submission_comments"][0][field] = value
    envelope["old_comment"] = copy.deepcopy(
        state["submission"]["submission_comments"][0]
    )
    envelope["old_comment_sha256"] = digest(envelope["old_comment"])
    with pytest.raises(GradebookError):
        await preview(editing)
    assert not state["edit_puts"]
    with publisher.ledger.connect() as db:
        assert db.execute("SELECT COUNT(*) FROM operations").fetchone()[0] == 0


@pytest.mark.parametrize(
    "extra", ["posted_grade", "url", "method", "delete", "comment[text_comment]"]
)
async def test_no_extra_transport_or_score_fields(editing: Any, extra: str) -> None:
    _, state, envelope, _ = editing
    envelope[extra] = "forbidden"
    with pytest.raises(GradebookError, match="schema"):
        await preview(editing)
    assert not state["edit_puts"]


async def test_final_owner_revocation_and_expiry_crossing_before_put(
    editing: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    publisher, state, _, controls = editing
    result = await preview(editing)
    operation = publisher.ledger.operation(result["operation_id"])

    def expires_after_final_get(course: str, envelope: dict[str, Any]) -> None:
        monkeypatch.setattr(
            "canvas_mcp.gradebook.ledger.time.time",
            lambda: operation["expires"] + 0.001,
        )

    timed = OwnerControls(
        controls.fresh_before_context, expires_after_final_get, controls.bind_plan
    )
    with pytest.raises(GradebookError, match="expired before send"):
        await edit.confirm_comment_edit(
            publisher,
            "12",
            result["operation_id"],
            result["confirmation_token"],
            enabled=True,
            owner_controls=timed,
        )
    assert not state["edit_puts"]
    assert publisher.ledger.summary(result["operation_id"])["counts"] == {"not_sent": 1}


async def test_source_revoked_during_last_get_stops_before_sending(
    editing: Any,
) -> None:
    publisher, state, _, _ = editing
    result = await preview(editing)
    previous = publisher.client.http._transport.handler

    def revoked(request: httpx.Request) -> httpx.Response:
        response = previous(request)
        if request.method == "GET" and "/submissions/" in request.url.path:
            state["owner_valid"] = False
        return response

    publisher.client.http._transport.handler = revoked
    with pytest.raises(GradebookError, match="owner hold"):
        await confirm(editing, result)
    assert not state["edit_puts"]


async def test_unresolved_edit_blocks_append_via_same_existing_target_lock(
    editing: Any,
) -> None:
    publisher, state, envelope, _ = editing
    result = await preview(editing)
    publisher.ledger.claim(result["operation_id"], result["confirmation_token"])
    publisher.ledger.mark(result["operation_id"], 0, "sending")
    append = {key: envelope[key] for key in edit.BASE_FIELDS}
    path = publisher.store.root / "inbox/append.json"
    path.write_text(json.dumps(append), encoding="utf-8")
    ordinary = await publisher.prepare_comment("12", "append.json", digest(append))
    with pytest.raises(GradebookError, match="unresolved push"):
        await publisher.confirm_comment(
            "12", ordinary["operation_id"], ordinary["confirmation_token"]
        )
    assert not state["edit_puts"] and not state["forms"]


async def test_prior_operations_keep_exact_expiries_and_prepared_reconcile_is_noop(
    editing: Any,
) -> None:
    publisher, state, _, _ = editing
    old_id, _ = publisher.ledger.prepare(
        "f" * 64,
        ["fictional-legacy-target"],
        comment_delivery_ids=["e" * 64],
        comment_approval_seconds=1800,
    )
    original = publisher.ledger.operation(old_id)
    result = await preview(editing)
    prepared = publisher.ledger.operation(result["operation_id"])
    requests = list(state["requests"])
    done = await edit.reconcile_comment_edit(publisher, "12", result["operation_id"])
    assert done["status"] == "prepared" and state["requests"] == requests
    assert publisher.ledger.operation(result["operation_id"]) == prepared
    await confirm(editing, result)
    assert publisher.ledger.operation(old_id) == original


async def test_optional_mcp_seam_is_off_by_default_and_exposes_no_body_or_url(
    editing: Any,
) -> None:
    from fastmcp import Client, FastMCP

    publisher, state, envelope, controls = editing
    disabled = FastMCP("fictional-disabled-edit-seam")
    edit.register_comment_edit_tools(disabled, publisher, {"core": "12"})
    async with Client(disabled) as client:
        assert not await client.list_tools()
    server = FastMCP("fictional-enabled-edit-seam")
    edit.register_comment_edit_tools(
        server, publisher, {"core": "12"}, owner_controls=controls, enabled=True
    )
    (publisher.store.root / "inbox/edit.json").write_text(json.dumps(envelope), encoding="utf-8")
    async with Client(server) as client:
        tools = {tool.name: tool for tool in await client.list_tools()}
        assert set(tools) == {
            "prepare_existing_comment_edit",
            "confirm_existing_comment_edit",
            "reconcile_existing_comment_edit",
        }
        assert set(
            tools["prepare_existing_comment_edit"].input_schema["properties"]
        ) == {"course", "proposal_filename", "expected_envelope_sha256"}
        assert set(
            tools["confirm_existing_comment_edit"].input_schema["properties"]
        ) == {"course", "operation_id", "confirmation_token"}
        rejected = await client.call_tool(
            "prepare_existing_comment_edit",
            {
                "course": "other",
                "proposal_filename": "edit.json",
                "expected_envelope_sha256": digest(envelope),
            },
        )
        assert "error" in rejected.data
        result = (
            await client.call_tool(
                "prepare_existing_comment_edit",
                {
                    "course": "core",
                    "proposal_filename": "edit.json",
                    "expected_envelope_sha256": digest(envelope),
                },
            )
        ).data
        assert result["action"] == edit.ACTION and not state["edit_puts"]
        state["current_operation"] = result["operation_id"]
        done = (
            await client.call_tool(
                "confirm_existing_comment_edit",
                {
                    "course": "core",
                    "operation_id": result["operation_id"],
                    "confirmation_token": result["confirmation_token"],
                },
            )
        ).data
        assert done["counts"] == {"verified": 1} and len(state["edit_puts"]) == 1


async def test_no_owner_controls_or_already_exact_body_never_creates_operation(
    editing: Any,
) -> None:
    publisher, state, envelope, controls = editing
    (publisher.store.root / "inbox/edit.json").write_text(json.dumps(envelope), encoding="utf-8")
    with pytest.raises(GradebookError, match="owner controls"):
        await edit.prepare_comment_edit(publisher, "12", "edit.json", digest(envelope))
    selected = state["submission"]["submission_comments"][0]
    selected["comment"] = envelope["comment"]
    envelope["old_comment"] = copy.deepcopy(selected)
    envelope["old_body_sha256"] = envelope["new_body_sha256"]
    envelope["old_comment_sha256"] = digest(selected)
    result = await preview(editing)
    assert not result["ready_for_confirmation"] and not state["edit_puts"]
    with publisher.ledger.connect() as db:
        assert db.execute("SELECT COUNT(*) FROM operations").fetchone()[0] == 0


async def test_operation_tokens_cannot_be_carried_between_edit_previews(
    editing: Any,
) -> None:
    publisher, state, _, controls = editing
    first = await preview(editing)
    second = await preview(editing)
    with pytest.raises(GradebookError, match="does not match"):
        await edit.confirm_comment_edit(
            publisher,
            "12",
            second["operation_id"],
            first["confirmation_token"],
            enabled=True,
            owner_controls=controls,
        )
    assert publisher.ledger.operation(second["operation_id"])["status"] == "prepared"
    assert not state["edit_puts"]


async def test_explicit_rejection_is_terminal_without_fallback_or_retry(
    editing: Any,
) -> None:
    _, state, _, _ = editing
    result = await preview(editing)
    state["behavior"] = "reject"
    done = await confirm(editing, result)
    assert done["counts"] == {"rejected": 1} and len(state["edit_puts"]) == 1
    with pytest.raises(GradebookError, match="already consumed"):
        await confirm(editing, result)
    assert len(state["edit_puts"]) == 1 and state["forms"] == []


async def test_selected_attempt_metadata_drift_never_writes(editing: Any) -> None:
    _, state, _, _ = editing
    result = await preview(editing)
    state["submission"]["submission_comments"][0]["attempt"] = 3
    with pytest.raises(GradebookError):
        await confirm(editing, result)
    assert not state["edit_puts"]


@pytest.mark.parametrize("seconds", [600, 900, 1800])
async def test_new_edit_uses_configured_comment_window_without_renewing_old_operation(editing: Any, seconds: int) -> None:
    publisher, state, envelope, controls = editing
    earlier = await preview(editing)
    original = publisher.ledger.operation(earlier["operation_id"])
    configured = Publisher(publisher.client, publisher.store, publisher.ledger,
                           comment_approval_seconds=seconds)
    current = await preview((configured, state, envelope, controls))
    operation = publisher.ledger.operation(current["operation_id"])
    assert current["expires_in_seconds"] == seconds
    assert current["expires_at"] == operation["expires"]
    assert operation["expires"] - operation["created"] == seconds
    assert publisher.ledger.operation(earlier["operation_id"]) == original
    assert state["edit_puts"] == []
