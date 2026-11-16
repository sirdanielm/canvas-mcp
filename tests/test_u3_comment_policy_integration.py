"""Fictional U3 transport checks; no academic policy or source admission implied."""

import copy
import json
from typing import Any

import pytest
from test_gradebook import snapshot as snapshot
from test_gradebook_publish import assert_target_locked, prepared_comment
from test_gradebook_publish import comment_system as comment_system
from test_gradebook_publish import system as system
from test_unit2_comment_policy_integration import COMPACT

from canvas_mcp.gradebook import publish
from canvas_mcp.gradebook.client import GradebookError
from canvas_mcp.gradebook.ledger import Ledger
from canvas_mcp.gradebook.publish import Publisher
from canvas_mcp.gradebook.store import Store

# Deliberately fictional narrative, not an issued U3 rubric, score or acceptance.
FULL_U3_FEEDBACK = (
    "Item 1 — retained response: “A + B → C”.\n"
    "Feedback: Explain how your written evidence supports the conclusion; "
    "keep the original labels in your explanation.\n\n"
    "Item 2 — retained observation: the second explanation is incomplete.\n"
    "Feedback: Revisit the stated relationship and include the missing reasoning. "
    "Use the same units (µg) throughout.\n"
    "Next step: Review both explanations before revising your work."
)


@pytest.fixture
def u3_comment_system(comment_system: Any) -> tuple[Any, ...]:
    publisher, state, envelope = comment_system
    state["assignment"]["submission_types"] = ["online_upload"]
    envelope.update(category="UNIT3_FEEDBACK", comment=FULL_U3_FEEDBACK)
    return publisher, state, envelope


def test_unit3_full_feedback_is_explicit_without_unit2_compaction(
    u3_comment_system: Any,
) -> None:
    _, _, envelope = u3_comment_system
    retained = copy.deepcopy(envelope)
    publish.comment_envelope(envelope, envelope["origin"], "12")
    assert envelope == retained
    # Unit2 retains its separate compact policy even for identical text.
    with pytest.raises(GradebookError, match="compact feedback policy"):
        publish.comment_envelope(
            {**envelope, "category": "UNIT2_FEEDBACK"}, envelope["origin"], "12"
        )
    publish.comment_envelope(
        {**envelope, "category": "UNIT2_FEEDBACK", "comment": COMPACT},
        envelope["origin"],
        "12",
    )


@pytest.mark.parametrize(
    "category",
    ["CONFIRMED_MISSING", "WRONG_ASSIGNMENT", "FORMATIVE_CORRECTION", "UNIT1_FEEDBACK"],
)
def test_existing_comment_categories_keep_full_text_contract(
    u3_comment_system: Any, category: str
) -> None:
    _, _, envelope = u3_comment_system
    publish.comment_envelope(
        {**envelope, "category": category}, envelope["origin"], "12"
    )


async def test_unit3_upload_exact_text_comment_only_form_and_independent_readback(
    u3_comment_system: Any,
) -> None:
    publisher, state, envelope = u3_comment_system
    before = copy.deepcopy(state["submission"])
    preview = await prepared_comment(u3_comment_system)
    assert preview["canvas_writes"] == 0 and state["forms"] == []
    # A retained source and preview do not consume or supply teacher approval.
    with pytest.raises(GradebookError, match="does not match"):
        await publisher.confirm_comment("12", preview["operation_id"], "wrong-token")
    assert state["forms"] == []
    assert publisher.ledger.operation(preview["operation_id"])["status"] == "prepared"
    result = await publisher.confirm_comment(
        "12", preview["operation_id"], preview["confirmation_token"]
    )
    assert result["counts"] == {"verified": 1}
    assert state["forms"] == [
        {
            "comment[text_comment]": [FULL_U3_FEEDBACK],
            "comment[group_comment]": ["false"],
            "comment[attempt]": ["2"],
        }
    ]
    assert state["puts"] == []
    assert {
        k: v
        for k, v in state["submission"].items()
        if k not in {"submission_comments", "updated_at"}
    } == {
        k: v
        for k, v in before.items()
        if k not in {"submission_comments", "updated_at"}
    }
    assert state["submission"]["submission_comments"] == before[
        "submission_comments"
    ] + [{"id": 502, "author_id": 777, "comment": FULL_U3_FEEDBACK}]
    receipt = publisher.store.load("receipt", result["readback_receipt_id"])
    assert receipt["comparison"]["stored_verified"] is True
    assert receipt["comparison"]["publication_authorized"] is False
    assert receipt["response_comment_id"] == "502"
    assert receipt["source_envelope_sha256"] == publish.digest(envelope)
    assert state["requests"][-3:] == [
        ("PUT", "/api/v1/courses/12/assignments/21/submissions/101"),
        ("GET", "/api/v1/courses/12/assignments/21"),
        ("GET", "/api/v1/courses/12/assignments/21/submissions/101"),
    ]


async def test_unit3_expired_approval_sends_nothing(u3_comment_system: Any) -> None:
    publisher, state, _ = u3_comment_system
    preview = await prepared_comment(u3_comment_system)
    with publisher.ledger.connect() as db:
        db.execute(
            "UPDATE operations SET expires=0 WHERE id=?", (preview["operation_id"],)
        )
    with pytest.raises(GradebookError, match="expired"):
        await publisher.confirm_comment(
            "12", preview["operation_id"], preview["confirmation_token"]
        )
    assert state["forms"] == []


@pytest.mark.parametrize(
    "field", ["source_sha256", "source_revision", "decision_sha256", "comment"]
)
async def test_unit3_changed_source_after_preview_sends_nothing(
    u3_comment_system: Any, field: str
) -> None:
    publisher, state, envelope = u3_comment_system
    preview = await prepared_comment(u3_comment_system)
    envelope[field] = (
        "c" * 64 if field.endswith("sha256") else envelope[field] + "changed"
    )
    (publisher.store.root / "inbox/comment.json").write_text(
        json.dumps(envelope), encoding="utf-8"
    )
    with pytest.raises(GradebookError, match="changed after preview"):
        await publisher.confirm_comment(
            "12", preview["operation_id"], preview["confirmation_token"]
        )
    assert state["forms"] == []
    assert publisher.ledger.summary(preview["operation_id"])["counts"] == {
        "not_sent": 1
    }


@pytest.mark.parametrize(
    "changes",
    [
        {"attempt": 3},
        {"submitted_at": "2026-09-18T19:00:00Z"},
        {"score": 11, "grade": "11"},
    ],
)
async def test_unit3_changed_current_target_stops_before_send(
    u3_comment_system: Any, changes: dict[str, Any]
) -> None:
    publisher, state, _ = u3_comment_system
    preview = await prepared_comment(u3_comment_system)
    state["submission"].update(changes)
    with pytest.raises(GradebookError):
        await publisher.confirm_comment(
            "12", preview["operation_id"], preview["confirmation_token"]
        )
    assert state["forms"] == []
    assert publisher.ledger.summary(preview["operation_id"])["counts"] == {
        "not_sent": 1
    }


@pytest.mark.parametrize("failure", ["lost_response", "unavailable_readback"])
async def test_unit3_uncertain_write_survives_restart_and_never_resends(
    u3_comment_system: Any, failure: str
) -> None:
    publisher, state, _ = u3_comment_system
    preview = await prepared_comment(u3_comment_system)
    if failure == "lost_response":
        state["behavior"] = "timeout_applied"
        result = await publisher.confirm_comment(
            "12", preview["operation_id"], preview["confirmation_token"]
        )
        assert result["counts"] == {"uncertain": 1}
    else:
        state["fail_readback"] = True
        with pytest.raises(GradebookError, match="Canvas read failed"):
            await publisher.confirm_comment(
                "12", preview["operation_id"], preview["confirmation_token"]
            )
    assert_target_locked(publisher, preview["operation_id"])
    assert len(state["forms"]) == 1
    restarted = Publisher(
        publisher.client, Store(publisher.store.root), Ledger(publisher.store.root)
    )
    with pytest.raises(GradebookError, match="already consumed"):
        await restarted.confirm_comment(
            "12", preview["operation_id"], preview["confirmation_token"]
        )
    state["fail_readback"] = False
    result = await restarted.reconcile_comment("12", preview["operation_id"])
    assert result["counts"] == {
        "observed_applied" if failure == "lost_response" else "verified": 1
    }
    duplicate = await prepared_comment((restarted, state, u3_comment_system[2]))
    with pytest.raises(GradebookError, match="may have been sent"):
        await restarted.confirm_comment(
            "12", duplicate["operation_id"], duplicate["confirmation_token"]
        )
    assert len(state["forms"]) == 1 and state["puts"] == []
    assert state["submission"]["score"] == 10 and state["submission"]["grade"] == "10"


async def test_unit3_readback_with_newer_attempt_remains_uncertain(
    u3_comment_system: Any,
) -> None:
    publisher, state, _ = u3_comment_system
    preview = await prepared_comment(u3_comment_system)
    state["after_put"] = {"attempt": 3}
    result = await publisher.confirm_comment(
        "12", preview["operation_id"], preview["confirmation_token"]
    )
    assert result["counts"] == {"uncertain": 1}
    assert_target_locked(publisher, preview["operation_id"])
    with pytest.raises(GradebookError, match="already consumed"):
        await publisher.confirm_comment(
            "12", preview["operation_id"], preview["confirmation_token"]
        )
    assert len(state["forms"]) == 1 and state["puts"] == []
