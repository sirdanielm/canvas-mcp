"""
Tests for assignment-related MCP tools.

Includes tests for:
- list_assignments
- get_assignment_details
- list_submissions
- get_assignment_analytics
- create_assignment
- update_assignment
"""

from hashlib import sha256
from typing import Any
from unittest.mock import AsyncMock, patch

import httpx
import pytest


class TestVerifiedDraftDescription:
    """The existing update tool completes one bounded draft edit without handoffs."""

    @staticmethod
    def draft(description="<p>Before</p>", **overrides):
        return dict(id=12345, course_id=60366, name="Draft", description=description,
                    published=False, points_possible=10, submission_types=["on_paper"],
                    due_at=None, unlock_at=None, lock_at=None, **overrides)

    @pytest.mark.asyncio
    async def test_edit_and_independent_readback(self, mock_canvas_api):
        before = self.draft()
        after = self.draft("<p>After</p>")
        request = mock_canvas_api["make_canvas_request"]
        request.side_effect = [before, {"id": 12345}, after]
        result = await get_tool_function("update_assignment")(
            60366, 12345, description=after["description"],
            expected_description_sha256=sha256(before["description"].encode()).hexdigest())
        assert "VERIFIED" in result
        assert [c.args[0] for c in request.call_args_list] == ["get", "put", "get"]
        assert request.call_args_list[1].kwargs == {
            "data": {"assignment[description]": after["description"]},
            "use_form_data": True, "retry_rate_limits": False}

    @pytest.mark.asyncio
    async def test_duplicate_is_get_only_even_after_old_source_changed(self, mock_canvas_api):
        request = mock_canvas_api["make_canvas_request"]
        request.return_value = self.draft("<p>After</p>")
        result = await get_tool_function("update_assignment")(
            60366, 12345, description="<p>After</p>", expected_description_sha256="0" * 64)
        assert "ALREADY_CURRENT" in result
        assert [c.args[0] for c in request.call_args_list] == ["get"]

    @pytest.mark.asyncio
    @pytest.mark.parametrize("change", [
        {"published": True}, {"published": None}, {"id": 99}, {"course_id": 99},
        {"description": "someone else's edit"}, {"description": None},
    ])
    async def test_conflicting_unknown_or_published_target_never_writes(self, mock_canvas_api, change):
        before = self.draft()
        before.update(change)
        request = mock_canvas_api["make_canvas_request"]
        request.return_value = before
        result = await get_tool_function("update_assignment")(
            60366, 12345, description="<p>After</p>",
            expected_description_sha256=sha256(b"<p>Before</p>").hexdigest())
        assert "HELD" in result
        assert all(c.args[0] == "get" for c in request.call_args_list)

    @pytest.mark.asyncio
    @pytest.mark.parametrize("failure", [{"error": "timeout"}, None, {"id": 99}])
    async def test_uncertain_put_does_not_read_or_retry(self, mock_canvas_api, failure):
        request = mock_canvas_api["make_canvas_request"]
        request.side_effect = [self.draft(), failure]
        result = await get_tool_function("update_assignment")(
            60366, 12345, description="<p>After</p>",
            expected_description_sha256=sha256(b"<p>Before</p>").hexdigest())
        assert "UNKNOWN" in result
        assert [c.args[0] for c in request.call_args_list].count("put") == 1

    @pytest.mark.asyncio
    async def test_changed_metadata_after_put_is_not_verified(self, mock_canvas_api):
        after = self.draft("<p>After</p>")
        after["points_possible"] = 20
        request = mock_canvas_api["make_canvas_request"]
        request.side_effect = [self.draft(), {"id": 12345}, after]
        result = await get_tool_function("update_assignment")(
            60366, 12345, description="<p>After</p>",
            expected_description_sha256=sha256(b"<p>Before</p>").hexdigest())
        assert "UNVERIFIED" in result
        assert [c.args[0] for c in request.call_args_list].count("put") == 1

    @pytest.mark.asyncio
    @pytest.mark.parametrize("extra", [{"published": True}, {"name": "Other"},
                                      {"points_possible": 20}])
    async def test_description_route_cannot_carry_other_writes(self, mock_canvas_api, extra):
        result = await get_tool_function("update_assignment")(
            60366, 12345, description="<p>After</p>", expected_description_sha256="0" * 64, **extra)
        assert "HELD" in result
        mock_canvas_api["make_canvas_request"].assert_not_called()

    @pytest.mark.asyncio
    @pytest.mark.parametrize("outcome", ["success", "denied", "timeout", "rate_limited"])
    async def test_real_client_serialization_and_no_replay(self, mock_canvas_api, monkeypatch, outcome):
        from urllib.parse import parse_qs

        from canvas_mcp.core.client import make_canvas_request

        monkeypatch.setenv("CANVAS_API_TOKEN", "synthetic-test-token")
        monkeypatch.setenv("CANVAS_API_URL", "https://canvas.invalid/api/v1")
        monkeypatch.setenv("ENABLE_DATA_ANONYMIZATION", "false")
        monkeypatch.setenv("PYTHON_DOTENV_DISABLED", "1")
        calls = []
        html = '<p>After &amp; <a href="https://example.invalid/?a=1&b=2">link</a></p>'

        def exchange(request):
            calls.append(request.method)
            assert str(request.url) == "https://canvas.invalid/api/v1/courses/60366/assignments/12345"
            if request.method == "GET":
                return httpx.Response(200, json=self.draft(html if len(calls) == 3 else "<p>Before</p>"))
            assert request.method == "PUT"
            assert request.headers["content-type"].startswith("application/x-www-form-urlencoded")
            assert parse_qs(request.content.decode()) == {"assignment[description]": [html]}
            if outcome == "denied":
                return httpx.Response(403, json={"error": "Denied"})
            if outcome == "timeout":
                raise httpx.ReadTimeout("synthetic timeout", request=request)
            if outcome == "rate_limited":
                return httpx.Response(429, json={"error": "Rate limited"})
            return httpx.Response(200, json={"id": 12345})

        async with httpx.AsyncClient(transport=httpx.MockTransport(exchange)) as client:
            with patch("canvas_mcp.core.client._get_http_client", return_value=client):
                mock_canvas_api["make_canvas_request"].side_effect = make_canvas_request
                result = await get_tool_function("update_assignment")(
                    60366, 12345, description=html,
                    expected_description_sha256=sha256(b"<p>Before</p>").hexdigest())
        assert calls == (["GET", "PUT", "GET"] if outcome == "success" else ["GET", "PUT"])
        assert {"success": "VERIFIED", "denied": "REJECTED", "timeout": "UNKNOWN", "rate_limited": "UNKNOWN"}[outcome] in result

    @pytest.mark.asyncio
    async def test_reader_supplies_literal_html_hash(self, mock_canvas_api):
        mock_canvas_api["make_canvas_request"].return_value = self.draft()
        result = await get_tool_function("get_assignment_details")(
            60366, 12345, include_description_sha256=True
        )
        assert f"Description SHA-256: {sha256(b'<p>Before</p>').hexdigest()}" in result


    @pytest.mark.asyncio
    @pytest.mark.parametrize("source_hash", ["", "A" * 64, "0" * 63, "g" * 64])
    async def test_invalid_hash_never_reads_or_writes(
        self, mock_canvas_api: Any, source_hash: str
    ) -> None:
        result = await get_tool_function("update_assignment")(
            60366, 12345, description="<p>After</p>",
            expected_description_sha256=source_hash,
        )
        assert "HELD" in result
        mock_canvas_api["make_canvas_request"].assert_not_called()

    @pytest.mark.asyncio
    @pytest.mark.parametrize("guard", [
        {"expect_updated_at": "2026-11-01T12:00:00Z"},
        {"find": "Before", "replace": "After"},
        {"require": ["Before"]},
        {"require": []},
    ])
    async def test_hash_route_does_not_silently_bypass_existing_guards(
        self, mock_canvas_api: Any, guard: dict[str, Any]
    ) -> None:
        result = await get_tool_function("update_assignment")(
            60366, 12345, description="<p>After</p>",
            expected_description_sha256="0" * 64, **guard,
        )
        assert "HELD" in result
        mock_canvas_api["make_canvas_request"].assert_not_called()

    @pytest.mark.asyncio
    @pytest.mark.parametrize("field,value", [
        ("points_possible", True), ("points_possible", float("nan")),
        ("points_possible", float("inf")), ("points_possible", -1),
        ("submission_types", [123]),
    ])
    async def test_malformed_native_metadata_never_writes(
        self, mock_canvas_api: Any, field: str, value: Any
    ) -> None:
        before = self.draft()
        before[field] = value
        request = mock_canvas_api["make_canvas_request"]
        request.return_value = before
        result = await get_tool_function("update_assignment")(
            60366, 12345, description="<p>After</p>",
            expected_description_sha256=sha256(b"<p>Before</p>").hexdigest(),
        )
        assert "HELD" in result
        assert [call.args[0] for call in request.call_args_list] == ["get"]

    @pytest.mark.asyncio
    @pytest.mark.parametrize("field,value", [
        ("published", 0), ("points_possible", 10.0),
        ("submission_types", ["online_upload"]),
    ])
    async def test_readback_preserves_native_types_and_values(
        self, mock_canvas_api: Any, field: str, value: Any
    ) -> None:
        before, after = self.draft(), self.draft("<p>After</p>")
        after[field] = value
        request = mock_canvas_api["make_canvas_request"]
        request.side_effect = [before, {"id": 12345}, after]
        result = await get_tool_function("update_assignment")(
            60366, 12345, description="<p>After</p>",
            expected_description_sha256=sha256(b"<p>Before</p>").hexdigest(),
        )
        assert "UNVERIFIED" in result
        assert [call.args[0] for call in request.call_args_list] == ["get", "put", "get"]

    @pytest.mark.asyncio
    @pytest.mark.parametrize("before_extra,after_extra", [
        ({"grading_type": "points"}, {"grading_type": "percent"}),
        ({"assignment_group_id": 7}, {}),
        ({}, {"peer_reviews": True}),
        ({"peer_reviews": False}, {"peer_reviews": 0}),
    ])
    async def test_optional_stable_settings_cannot_drift_silently(
        self, mock_canvas_api: Any,
        before_extra: dict[str, Any], after_extra: dict[str, Any],
    ) -> None:
        before = {**self.draft(), **before_extra}
        after = {**self.draft("<p>After</p>"), **after_extra}
        request = mock_canvas_api["make_canvas_request"]
        request.side_effect = [before, {"id": 12345}, after]
        result = await get_tool_function("update_assignment")(
            60366, 12345, description="<p>After</p>",
            expected_description_sha256=sha256(b"<p>Before</p>").hexdigest(),
        )
        assert "UNVERIFIED" in result
        assert [call.args[0] for call in request.call_args_list] == ["get", "put", "get"]

    @pytest.mark.asyncio
    async def test_missing_preflight_field_and_failed_readback_remain_held(
        self, mock_canvas_api: Any
    ) -> None:
        request = mock_canvas_api["make_canvas_request"]
        before = self.draft()
        before.pop("due_at")
        request.return_value = before
        kwargs = {"description": "<p>After</p>",
                  "expected_description_sha256": sha256(b"<p>Before</p>").hexdigest()}
        assert "HELD" in await get_tool_function("update_assignment")(60366, 12345, **kwargs)
        assert [call.args[0] for call in request.call_args_list] == ["get"]
        request.reset_mock()
        request.side_effect = [self.draft(), {"id": 12345}, RuntimeError("fictional read failure")]
        assert "UNKNOWN" in await get_tool_function("update_assignment")(60366, 12345, **kwargs)
        assert [call.args[0] for call in request.call_args_list] == ["get", "put", "get"]

    @pytest.mark.asyncio
    @pytest.mark.parametrize("field,value", [
        ("course_id", "0"), ("assignment_id", "١٢"),
        ("assignment_id", "1/2"), ("course_id", True),
        ("expected_sha256", None), ("description", None),
    ])
    async def test_helper_rejects_malformed_arguments_before_request(
        self, field: str, value: Any
    ) -> None:
        from canvas_mcp.tools.assignment_drafts import update_draft_description

        args = {"course_id": "60366", "assignment_id": "12345",
                "description": "<p>After</p>", "expected_sha256": "0" * 64}
        args[field] = value
        request = AsyncMock()
        assert "HELD" in await update_draft_description(request, **args)
        request.assert_not_called()


@pytest.fixture
def mock_canvas_api():
    """Fixture to mock Canvas API calls for assignment tools."""
    with patch('canvas_mcp.tools.assignments.get_course_id') as mock_get_id, \
         patch('canvas_mcp.tools.assignments.get_course_code') as mock_get_code, \
         patch('canvas_mcp.tools.assignments.fetch_all_paginated_results') as mock_fetch, \
         patch('canvas_mcp.tools.assignments.make_canvas_request') as mock_request:

        mock_get_id.return_value = "60366"
        mock_get_code.return_value = "badm_350_120251"

        yield {
            'get_course_id': mock_get_id,
            'get_course_code': mock_get_code,
            'fetch_all_paginated_results': mock_fetch,
            'make_canvas_request': mock_request
        }


def get_tool_function(tool_name: str):
    """Get a tool function by name from the registered tools."""
    from fastmcp import FastMCP

    from canvas_mcp.tools.assignments import (
        register_educator_assignment_tools,
        register_shared_assignment_tools,
    )

    # Create a mock MCP server and register tools
    mcp = FastMCP("test")

    # Store captured functions
    captured_functions = {}

    # Override the tool decorator to capture the function
    original_tool = mcp.tool

    def capturing_tool(*args, **kwargs):
        decorator = original_tool(*args, **kwargs)
        def wrapper(fn):
            captured_functions[fn.__name__] = fn
            return decorator(fn)
        return wrapper

    mcp.tool = capturing_tool
    register_shared_assignment_tools(mcp)
    register_educator_assignment_tools(mcp)

    return captured_functions.get(tool_name)


class TestCreateAssignment:
    """Tests for create_assignment tool."""

    @pytest.mark.asyncio
    async def test_create_assignment_basic(self, mock_canvas_api):
        """Test basic assignment creation with minimal parameters."""
        mock_canvas_api['make_canvas_request'].return_value = {
            "id": 12345,
            "name": "Test Assignment",
            "published": False,
            "submission_types": ["none"],
            "html_url": "https://canvas.example.com/courses/60366/assignments/12345"
        }

        create_assignment = get_tool_function('create_assignment')
        assert create_assignment is not None

        result = await create_assignment("badm_350_120251", "Test Assignment")

        # Verify API was called correctly
        mock_canvas_api['get_course_id'].assert_called_once_with("badm_350_120251")
        mock_canvas_api['make_canvas_request'].assert_called_once()

        # Verify the call was a POST with correct data
        call_args = mock_canvas_api['make_canvas_request'].call_args
        assert call_args[0][0] == "post"
        assert "/courses/60366/assignments" in call_args[0][1]
        assert call_args[1]['data']['assignment']['name'] == "Test Assignment"
        assert call_args[1]['data']['assignment']['published'] is False

        # Verify output
        assert "successfully" in result
        assert "Test Assignment" in result
        assert "12345" in result
        assert "Published: No" in result

    @pytest.mark.asyncio
    async def test_create_assignment_with_all_options(self, mock_canvas_api):
        """Test assignment creation with all parameters populated."""
        mock_canvas_api['make_canvas_request'].return_value = {
            "id": 12346,
            "name": "Full Assignment",
            "description": "<p>Test description</p>",
            "published": True,
            "points_possible": 100,
            "due_at": "2026-01-26T23:59:00Z",
            "submission_types": ["online_text_entry", "online_upload"],
            "grading_type": "points",
            "peer_reviews": True,
            "html_url": "https://canvas.example.com/courses/60366/assignments/12346"
        }

        create_assignment = get_tool_function('create_assignment')
        result = await create_assignment(
            "badm_350_120251",
            "Full Assignment",
            description="<p>Test description</p>",
            submission_types="online_text_entry,online_upload",
            due_at="2026-01-26T23:59:00Z",
            points_possible=100,
            grading_type="points",
            published=True,
            peer_reviews=True,
            allowed_extensions="pdf,docx"
        )

        # Verify API call data
        call_args = mock_canvas_api['make_canvas_request'].call_args
        assignment_data = call_args[1]['data']['assignment']

        assert assignment_data['name'] == "Full Assignment"
        assert assignment_data['description'] == "<p>Test description</p>"
        assert assignment_data['submission_types'] == ["online_text_entry", "online_upload"]
        # parse_date converts to isoformat which uses +00:00 instead of Z
        assert assignment_data['due_at'] in ["2026-01-26T23:59:00Z", "2026-01-26T23:59:00+00:00"]
        assert assignment_data['points_possible'] == 100
        assert assignment_data['grading_type'] == "points"
        assert assignment_data['published'] is True
        assert assignment_data['peer_reviews'] is True
        assert assignment_data['allowed_extensions'] == ["pdf", "docx"]

        # Verify output
        assert "successfully" in result
        assert "Full Assignment" in result
        assert "Points: 100" in result
        assert "Published: Yes" in result

    @pytest.mark.asyncio
    async def test_create_assignment_error_handling(self, mock_canvas_api):
        """Test error handling when API fails."""
        mock_canvas_api['make_canvas_request'].return_value = {"error": "Unauthorized"}

        create_assignment = get_tool_function('create_assignment')
        result = await create_assignment("badm_350_120251", "Test Assignment")

        assert "Error" in result
        assert "Unauthorized" in result

    @pytest.mark.asyncio
    async def test_create_assignment_invalid_grading_type(self, mock_canvas_api):
        """Test validation of invalid grading_type."""
        create_assignment = get_tool_function('create_assignment')
        result = await create_assignment(
            "badm_350_120251",
            "Test Assignment",
            grading_type="invalid_type"
        )

        assert "Invalid grading_type" in result
        assert "invalid_type" in result
        # Should not have called the API
        mock_canvas_api['make_canvas_request'].assert_not_called()

    @pytest.mark.asyncio
    async def test_create_assignment_invalid_submission_type(self, mock_canvas_api):
        """Test validation of invalid submission_types."""
        create_assignment = get_tool_function('create_assignment')
        result = await create_assignment(
            "badm_350_120251",
            "Test Assignment",
            submission_types="online_text_entry,invalid_type"
        )

        assert "Invalid submission_type" in result
        assert "invalid_type" in result
        # Should not have called the API
        mock_canvas_api['make_canvas_request'].assert_not_called()

    @pytest.mark.asyncio
    async def test_create_assignment_submission_types_parsing(self, mock_canvas_api):
        """Test that comma-separated submission_types are correctly parsed."""
        mock_canvas_api['make_canvas_request'].return_value = {
            "id": 12347,
            "name": "Multi-Type Assignment",
            "published": False,
            "submission_types": ["online_text_entry", "online_url", "online_upload"]
        }

        create_assignment = get_tool_function('create_assignment')
        _result = await create_assignment(
            "badm_350_120251",
            "Multi-Type Assignment",
            submission_types="online_text_entry, online_url, online_upload"  # Note spaces
        )

        # Verify submission_types were parsed correctly (with whitespace stripped)
        call_args = mock_canvas_api['make_canvas_request'].call_args
        assignment_data = call_args[1]['data']['assignment']
        assert assignment_data['submission_types'] == ["online_text_entry", "online_url", "online_upload"]

    @pytest.mark.asyncio
    async def test_create_assignment_valid_date_parsing(self, mock_canvas_api):
        """Test that valid dates are parsed and formatted correctly."""
        mock_canvas_api['make_canvas_request'].return_value = {
            "id": 12348,
            "name": "Dated Assignment",
            "published": False,
            "due_at": "2026-01-26T23:59:00Z"
        }

        create_assignment = get_tool_function('create_assignment')
        result = await create_assignment(
            "badm_350_120251",
            "Dated Assignment",
            due_at="2026-01-26T23:59:00Z",
            unlock_at="2026-01-20T00:00:00Z",
            lock_at="2026-02-01T23:59:00Z"
        )

        # Verify dates were parsed and sent to API
        call_args = mock_canvas_api['make_canvas_request'].call_args
        assignment_data = call_args[1]['data']['assignment']
        assert "due_at" in assignment_data
        assert "unlock_at" in assignment_data
        assert "lock_at" in assignment_data
        assert "successfully" in result

    @pytest.mark.asyncio
    async def test_create_assignment_invalid_date_format(self, mock_canvas_api):
        """Test validation of invalid date formats."""
        create_assignment = get_tool_function('create_assignment')
        result = await create_assignment(
            "badm_350_120251",
            "Test Assignment",
            due_at="not-a-valid-date"
        )

        assert "Invalid date format" in result
        assert "due_at" in result
        assert "not-a-valid-date" in result
        # Should not have called the API
        mock_canvas_api['make_canvas_request'].assert_not_called()

    @pytest.mark.asyncio
    async def test_create_assignment_invalid_unlock_at_format(self, mock_canvas_api):
        """Test validation of invalid unlock_at date format."""
        create_assignment = get_tool_function('create_assignment')
        result = await create_assignment(
            "badm_350_120251",
            "Test Assignment",
            unlock_at="yesterday"
        )

        assert "Invalid date format" in result
        assert "unlock_at" in result
        # Should not have called the API
        mock_canvas_api['make_canvas_request'].assert_not_called()

    @pytest.mark.asyncio
    async def test_create_assignment_automatic_peer_reviews_without_peer_reviews(self, mock_canvas_api):
        """Test validation that automatic_peer_reviews requires peer_reviews=True."""
        create_assignment = get_tool_function('create_assignment')
        result = await create_assignment(
            "badm_350_120251",
            "Test Assignment",
            automatic_peer_reviews=True,
            peer_reviews=False  # This combination is invalid
        )

        assert "Invalid configuration" in result
        assert "automatic_peer_reviews" in result
        assert "peer_reviews" in result
        # Should not have called the API
        mock_canvas_api['make_canvas_request'].assert_not_called()


class TestUpdateAssignment:
    """Tests for update_assignment tool."""

    @pytest.mark.asyncio
    async def test_update_assignment_basic(self, mock_canvas_api):
        """Test basic assignment update with name change."""
        mock_canvas_api['make_canvas_request'].return_value = {
            "id": 12345,
            "name": "Updated Assignment Name",
            "published": False,
            "submission_types": ["none"],
            "html_url": "https://canvas.example.com/courses/60366/assignments/12345"
        }

        update_assignment = get_tool_function('update_assignment')
        assert update_assignment is not None

        result = await update_assignment("badm_350_120251", 12345, name="Updated Assignment Name")

        # Verify API was called correctly
        mock_canvas_api['get_course_id'].assert_called_once_with("badm_350_120251")
        mock_canvas_api['make_canvas_request'].assert_called_once()

        # Verify the call was a PUT with correct data
        call_args = mock_canvas_api['make_canvas_request'].call_args
        assert call_args[0][0] == "put"
        assert "/courses/60366/assignments/12345" in call_args[0][1]
        assert call_args[1]['data']['assignment']['name'] == "Updated Assignment Name"

        # Verify output
        assert "successfully" in result
        assert "Updated Assignment Name" in result
        assert "Updated fields: name" in result

    @pytest.mark.asyncio
    async def test_update_assignment_multiple_fields(self, mock_canvas_api):
        """Test updating multiple fields at once."""
        mock_canvas_api['make_canvas_request'].return_value = {
            "id": 12345,
            "name": "Updated Name",
            "description": "<p>New description</p>",
            "published": True,
            "points_possible": 150,
            "due_at": "2026-02-15T23:59:00Z",
            "submission_types": ["online_text_entry", "online_upload"],
            "html_url": "https://canvas.example.com/courses/60366/assignments/12345"
        }

        update_assignment = get_tool_function('update_assignment')
        result = await update_assignment(
            "badm_350_120251",
            12345,
            name="Updated Name",
            description="<p>New description</p>",
            points_possible=150,
            due_at="2026-02-15T23:59:00Z",
            published=True
        )

        # Verify API call data
        call_args = mock_canvas_api['make_canvas_request'].call_args
        assignment_data = call_args[1]['data']['assignment']

        assert assignment_data['name'] == "Updated Name"
        assert assignment_data['description'] == "<p>New description</p>"
        assert assignment_data['points_possible'] == 150
        assert assignment_data['published'] is True

        # Verify output includes updated fields
        assert "successfully" in result
        assert "Updated fields:" in result
        assert "name" in result

    @pytest.mark.asyncio
    async def test_update_assignment_no_fields(self, mock_canvas_api):
        """Test that error is returned when no fields are provided."""
        update_assignment = get_tool_function('update_assignment')
        result = await update_assignment("badm_350_120251", 12345)

        assert "No fields provided to update" in result
        # Should not have called the API
        mock_canvas_api['make_canvas_request'].assert_not_called()

    @pytest.mark.asyncio
    async def test_update_assignment_error_handling(self, mock_canvas_api):
        """Test error handling when API fails."""
        mock_canvas_api['make_canvas_request'].return_value = {"error": "Assignment not found"}

        update_assignment = get_tool_function('update_assignment')
        result = await update_assignment("badm_350_120251", 99999, name="New Name")

        assert "Error" in result
        assert "Assignment not found" in result

    @pytest.mark.asyncio
    async def test_update_assignment_invalid_grading_type(self, mock_canvas_api):
        """Test validation of invalid grading_type."""
        update_assignment = get_tool_function('update_assignment')
        result = await update_assignment(
            "badm_350_120251",
            12345,
            grading_type="invalid_type"
        )

        assert "Invalid grading_type" in result
        assert "invalid_type" in result
        # Should not have called the API
        mock_canvas_api['make_canvas_request'].assert_not_called()

    @pytest.mark.asyncio
    async def test_update_assignment_invalid_submission_type(self, mock_canvas_api):
        """Test validation of invalid submission_types."""
        update_assignment = get_tool_function('update_assignment')
        result = await update_assignment(
            "badm_350_120251",
            12345,
            submission_types="online_text_entry,invalid_type"
        )

        assert "Invalid submission_type" in result
        assert "invalid_type" in result
        # Should not have called the API
        mock_canvas_api['make_canvas_request'].assert_not_called()

    @pytest.mark.asyncio
    async def test_update_assignment_invalid_date_format(self, mock_canvas_api):
        """Test validation of invalid date formats."""
        update_assignment = get_tool_function('update_assignment')
        result = await update_assignment(
            "badm_350_120251",
            12345,
            due_at="not-a-valid-date"
        )

        assert "Invalid date format" in result
        assert "due_at" in result
        assert "not-a-valid-date" in result
        # Should not have called the API
        mock_canvas_api['make_canvas_request'].assert_not_called()

    @pytest.mark.asyncio
    async def test_update_assignment_automatic_peer_reviews_without_peer_reviews(self, mock_canvas_api):
        """Test validation that automatic_peer_reviews requires peer_reviews=True."""
        update_assignment = get_tool_function('update_assignment')
        result = await update_assignment(
            "badm_350_120251",
            12345,
            automatic_peer_reviews=True,
            peer_reviews=False  # This combination is invalid
        )

        assert "Invalid configuration" in result
        assert "automatic_peer_reviews" in result
        assert "peer_reviews" in result
        # Should not have called the API
        mock_canvas_api['make_canvas_request'].assert_not_called()

    @pytest.mark.asyncio
    async def test_update_assignment_publish_only(self, mock_canvas_api):
        """Test updating only the published status."""
        mock_canvas_api['make_canvas_request'].return_value = {
            "id": 12345,
            "name": "Test Assignment",
            "published": True,
            "html_url": "https://canvas.example.com/courses/60366/assignments/12345"
        }

        update_assignment = get_tool_function('update_assignment')
        result = await update_assignment("badm_350_120251", 12345, published=True)

        # Verify only published was sent
        call_args = mock_canvas_api['make_canvas_request'].call_args
        assignment_data = call_args[1]['data']['assignment']
        assert assignment_data == {"published": True}

        assert "successfully" in result
        assert "Published: Yes" in result


class TestAssignmentTools:
    """Test assignment tool functions."""

    @pytest.mark.asyncio
    async def test_list_assignments(self):
        """Test listing assignments."""
        mock_assignments = [
            {"id": 1, "name": "Assignment 1", "due_at": "2024-02-15", "points_possible": 100},
            {"id": 2, "name": "Assignment 2", "due_at": "2024-03-01", "points_possible": 50}
        ]

        with patch('canvas_mcp.core.client.fetch_all_paginated_results', new_callable=AsyncMock) as mock_fetch:
            mock_fetch.return_value = mock_assignments

            from canvas_mcp.core.client import fetch_all_paginated_results

            result = await fetch_all_paginated_results("/courses/12345/assignments", {})

            assert len(result) == 2
            assert result[0]["name"] == "Assignment 1"

    @pytest.mark.asyncio
    async def test_get_assignment_details(self):
        """Test getting assignment details."""
        mock_assignment = {
            "id": 67890,
            "name": "Test Assignment",
            "description": "Test description",
            "points_possible": 100
        }

        with patch('canvas_mcp.core.client.make_canvas_request', new_callable=AsyncMock) as mock_request:
            mock_request.return_value = mock_assignment

            from canvas_mcp.core.client import make_canvas_request

            result = await make_canvas_request("get", "/courses/12345/assignments/67890")

            assert result["name"] == "Test Assignment"
            assert result["points_possible"] == 100

    @pytest.mark.asyncio
    async def test_list_submissions(self):
        """Test listing submissions."""
        mock_submissions = [
            {"user_id": 1001, "score": 85, "submitted_at": "2024-02-14"},
            {"user_id": 1002, "score": 92, "submitted_at": "2024-02-14"}
        ]

        with patch('canvas_mcp.core.client.fetch_all_paginated_results', new_callable=AsyncMock) as mock_fetch:
            mock_fetch.return_value = mock_submissions

            from canvas_mcp.core.client import fetch_all_paginated_results

            result = await fetch_all_paginated_results("/courses/12345/assignments/67890/submissions", {})

            assert len(result) == 2
            assert result[0]["score"] == 85

    @pytest.mark.asyncio
    async def test_assignment_analytics(self):
        """Test assignment analytics calculation."""
        from statistics import mean, median

        scores = [85, 92, 78, 95, 88]

        avg = mean(scores)
        med = median(scores)

        assert avg == 87.6
        assert med == 88

    @pytest.mark.asyncio
    async def test_empty_submissions(self):
        """Test handling empty submissions list."""
        with patch('canvas_mcp.core.client.fetch_all_paginated_results', new_callable=AsyncMock) as mock_fetch:
            mock_fetch.return_value = []

            from canvas_mcp.core.client import fetch_all_paginated_results

            result = await fetch_all_paginated_results("/courses/12345/assignments/67890/submissions", {})

            assert result == []

    @pytest.mark.asyncio
    async def test_assignment_error_handling(self):
        """Test error handling in assignment operations."""
        with patch('canvas_mcp.core.client.make_canvas_request', new_callable=AsyncMock) as mock_request:
            mock_request.return_value = {"error": "Assignment not found"}

            from canvas_mcp.core.client import make_canvas_request

            result = await make_canvas_request("get", "/courses/12345/assignments/99999")

            assert "error" in result


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
