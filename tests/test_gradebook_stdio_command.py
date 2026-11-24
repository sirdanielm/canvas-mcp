"""Drive the actual gradebook registry over stdio and reread the fictional destination."""

import json
import os
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import pytest
from fixtures.gradebook_stdio_destination import COMMENT, GRADE, SUBMISSION, Destination
from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

from canvas_mcp.gradebook.model import digest
from canvas_mcp.gradebook.store import Store

ROOT = Path(__file__).resolve().parents[1]
SERVER = ROOT / "tests/fixtures/gradebook_stdio_server.py"


async def invoke(session: ClientSession, tool: str, arguments: dict[str, Any]) -> dict[str, Any]:
    """Make exactly one tools/call. Keep structured domain errors available to callers."""
    result = await session.call_tool(tool, arguments)
    if result.is_error:
        raise RuntimeError("MCP tool returned an error. Inspect operation status before continuing.")
    if isinstance(result.structured_content, dict):
        return result.structured_content
    if len(result.content) == 1 and result.content[0].type == "text":
        data = json.loads(result.content[0].text)
        if isinstance(data, dict):
            return data
    raise ValueError("The MCP tool did not return an object.")


@asynccontextmanager
async def stdio_session(workspace: Path) -> AsyncIterator[tuple[ClientSession, str]]:
    parameters = StdioServerParameters(
        command=sys.executable,
        args=[str(SERVER), str(workspace / "destination"), str(workspace / "store")],
        cwd=workspace,
        env={
            "HOME": str(workspace),
            "PYTHONPATH": str(ROOT / "src"),
            "PYTHONNOUSERSITE": "1",
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHON_DOTENV_DISABLED": "1",
        },
    )
    async with (
        stdio_client(parameters) as streams,
        ClientSession(*streams, read_timeout_seconds=45.0) as session,
    ):
        handshake = await session.initialize()
        assert handshake.server_info.name == "canvas-gradebook"
        yield session, handshake.protocol_version


def confirm_args(plan: dict[str, Any]) -> dict[str, str]:
    assert plan["publishing_available"] and plan["ready_for_confirmation"]
    return {
        "course": "core",
        "operation_id": plan["operation_id"],
        "confirmation_token": plan["confirmation_token"],
    }


def check_write_and_readback(
    events: list[dict[str, Any]], fields: dict[str, Any]
) -> dict[str, Any]:
    writes = [e for e in events if e["method"] != "GET"]
    assert len(writes) == 1
    assert (writes[0]["method"], writes[0]["path"], writes[0]["fields"]) == (
        "PUT",
        SUBMISSION,
        fields,
    )
    return next(
        event
        for event in events[events.index(writes[0]) + 1 :]
        if event["method"] == "GET" and event["path"] == SUBMISSION
    )


@pytest.mark.skipif(os.name != "posix", reason="Private gradebook store requires POSIX directory fsync")
async def test_grade_and_comment_commands_over_stdio(tmp_path: Path) -> None:
    destination = Destination(tmp_path / "destination")
    destination.initialize()
    initial = destination.read_submission()
    store = Store(tmp_path / "store")
    async with stdio_session(tmp_path) as (session, protocol):
        tools = {tool.name for tool in (await session.list_tools()).tools}
        assert {"confirm_gradebook_push", "confirm_gradebook_comment_push"} <= tools
        capture = await invoke(session, "get_canvas_gradebook", {"course": "core"})
        assert capture["canvas_writes"] == 0
        baseline = store.load("snapshot", capture["snapshot_id"])
        inputs = destination.write_inputs(store, baseline)
        review = await invoke(
            session,
            "preview_gradebook_changes",
            {
                "course": "core",
                "snapshot_id": capture["snapshot_id"],
                "edits_filename": inputs["edits_filename"],
            },
        )
        assert review["changes"] == 1 and review["canvas_writes"] == 0
        plan = await invoke(
            session,
            "prepare_gradebook_push",
            {
                "course": "core",
                "review_id": review["review_id"],
            },
        )
        grade_args = confirm_args(plan)
        events = destination.requests()
        assert all(event["method"] == "GET" for event in events)
        assert destination.read_submission() == initial
        grade = await invoke(session, "confirm_gradebook_push", grade_args)
        assert grade["counts"] == {"verified": 1}
        check_write_and_readback(
            destination.requests()[len(events) :],
            {
                "submission": {"posted_grade": str(GRADE)},
            },
        )
        graded = destination.read_submission()
        assert initial["score"] == 10 and graded["score"] == GRADE
        assert graded["grade"] == str(GRADE)
        assert graded["submission_comments"] == initial["submission_comments"]

        events = destination.requests()
        comment_plan = await invoke(
            session,
            "prepare_gradebook_comment_push",
            {
                "course": "core",
                "comments_filename": inputs["comments_filename"],
                "expected_envelope_sha256": inputs["expected_envelope_sha256"],
            },
        )
        comment_args = confirm_args(comment_plan)
        assert all(
            event["method"] == "GET" for event in destination.requests()[len(events) :]
        )
        assert destination.read_submission() == graded
        events = destination.requests()
        comment = await invoke(session, "confirm_gradebook_comment_push", comment_args)
        assert comment["counts"] == {"verified": 1}
        get = check_write_and_readback(
            destination.requests()[len(events) :],
            {
                "comment[group_comment]": "false",
                "comment[text_comment]": COMMENT,
            },
        )
        assert ["include[]", "submission_comments"] in get["query"]
        receipt = store.load("receipt", comment["readback_receipt_id"])
        assert receipt["operation_id"] == comment_args["operation_id"]
        assert receipt["comparison"]["stored_verified"] is True
        after = destination.read_submission()
        expected_comment = {"id": 502, "author_id": 777, "comment": COMMENT}
        assert str(expected_comment["id"]) == receipt["response_comment_id"]
        assert after["submission_comments"] == graded["submission_comments"] + [
            expected_comment
        ]
        assert json.loads(receipt["after"]["submission"]["body"]) == after
        assert {key for key in after if after[key] != graded[key]} == {
            "submission_comments",
            "updated_at",
        }

    events = destination.requests()
    async with stdio_session(tmp_path) as (restarted, _):
        for lane, args in (
            ("gradebook_push", grade_args),
            ("gradebook_comment_push", comment_args),
        ):
            status = await invoke(
                restarted,
                "reconcile_" + lane,
                {
                    "course": "core",
                    "operation_id": args["operation_id"],
                },
            )
            assert status["counts"] == {"verified": 1}
            duplicate = await invoke(restarted, "confirm_" + lane, args)
            assert "already consumed" in duplicate["error"]
        fresh = await invoke(restarted, "get_canvas_gradebook", {"course": "core"})
        assert (
            store.load("snapshot", fresh["snapshot_id"])["cells"]["101:21"]["value"]
            == GRADE
        )
    requests = destination.requests()
    assert all(e["method"] == "GET" for e in requests[len(events) :])
    assert [e["method"] for e in requests if e["method"] != "GET"] == ["PUT", "PUT"]
    assert destination.read_submission() == after
    # Retain only synthetic evidence and receipt references in the test output directory.
    report = {
        "destination": "fictional Canvas fixture",
        "transport": "MCP stdio",
        "protocol_version": protocol,
        "server": "canvas-gradebook",
        "baseline_snapshot": capture["snapshot_id"],
        "fresh_snapshot": fresh["snapshot_id"],
        "grade_operation": grade_args["operation_id"],
        "grade_before": initial["score"],
        "grade_readback": after["score"],
        "comment_operation": comment_args["operation_id"],
        "comment_receipt": comment["readback_receipt_id"],
        "comment_readback": expected_comment,
        "before_sha256": digest(initial),
        "after_sha256": digest(after),
        "requests_sha256": digest(requests),
        "destination_writes": 2,
        "reconciliation_and_replay_writes": 0,
    }
    (tmp_path / "stdio-proof.json").write_text(
        json.dumps(report, indent=2) + "\n", encoding="utf-8"
    )
