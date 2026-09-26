"""Read-only Canvas transport with complete, same-endpoint pagination."""

from __future__ import annotations

import asyncio
from typing import Any
from urllib.parse import urljoin, urlsplit

import httpx


class GradebookError(Exception):
    """Safe operational error: never include Canvas bodies or credentials."""


class GradebookClient:
    """A dedicated GET-only client; raw identities never enter MCP results.

    The general MCP client anonymizes model-facing responses. This adapter's
    different destination is a teacher's private workbook, so it retains exact
    Canvas IDs and names locally, without changing that global privacy gate.
    """

    def __init__(self, origin: str, token: str, transport: Any = None) -> None:
        parsed = urlsplit(origin)
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
            or parsed.path not in ("", "/")
        ):
            raise GradebookError("Invalid Canvas origin.")
        self.origin = origin.rstrip("/")
        self.http = httpx.AsyncClient(
            headers={"Authorization": "Bearer " + token},
            timeout=30,
            follow_redirects=False,
            transport=transport,
        )

    async def close(self) -> None:
        await self.http.aclose()

    async def _get(self, url: str, params: Any = None) -> httpx.Response:
        for attempt in range(3):
            try:
                response = await self.http.get(url, params=params)
            except httpx.HTTPError as exc:
                raise GradebookError(
                    "Canvas read failed; previous snapshot retained."
                ) from exc
            if response.status_code == 429 and attempt < 2:
                await asyncio.sleep(2**attempt)
                continue
            if response.status_code != 200:
                raise GradebookError(
                    f"Canvas read returned HTTP {response.status_code}; previous snapshot retained."
                )
            return response
        raise GradebookError("Canvas read was rate limited.")

    async def get(self, path: str, params: Any = None) -> Any:
        response = await self._get(self.origin + "/api/v1" + path, params)
        try:
            return response.json()
        except ValueError as exc:
            raise GradebookError("Canvas returned invalid JSON.") from exc

    async def pages(self, path: str, params: Any = None) -> list[dict[str, Any]]:
        initial = self.origin + "/api/v1" + path
        expected = urlsplit(initial)
        url = initial
        seen: set[str] = set()
        records: list[dict[str, Any]] = []
        for _ in range(1000):
            parsed = urlsplit(url)
            if (parsed.scheme, parsed.netloc, parsed.path) != (
                expected.scheme,
                expected.netloc,
                expected.path,
            ) or parsed.fragment:
                raise GradebookError("Canvas pagination changed origin or endpoint.")
            if url in seen:
                raise GradebookError("Canvas pagination repeated a page.")
            seen.add(url)
            response = await self._get(url, params)
            params = None
            try:
                page = response.json()
            except ValueError as exc:
                raise GradebookError("Canvas returned invalid JSON.") from exc
            if not isinstance(page, list) or any(not isinstance(r, dict) for r in page):
                raise GradebookError("Canvas returned an unexpected page shape.")
            records.extend(page)
            next_url = response.links.get("next", {}).get("url")
            if not next_url:
                return records
            url = urljoin(url, next_url)
        raise GradebookError("Canvas pagination exceeded the safety limit.")

    async def snapshot(self, course_id: str) -> dict[str, Any]:
        from .model import normalize_snapshot

        if not course_id.isascii() or not course_id.isdecimal():
            raise GradebookError("Course ID must be numeric.")
        root = f"/courses/{course_id}"
        course = await self.get(root, {"include[]": "permissions"})
        if not isinstance(course, dict) or str(course.get("id")) != course_id:
            raise GradebookError("Canvas course identity did not match.")
        permissions = await self.get(
            root + "/permissions", {"permissions[]": "manage_grades"}
        )
        if (
            not isinstance(permissions, dict)
            or permissions.get("manage_grades") is not True
        ):
            raise GradebookError("Canvas did not confirm grade-management permission.")
        # Sequential reads keep request pressure low and fail before publishing
        # a snapshot if any component is incomplete.
        sections = await self.pages(root + "/sections", {"per_page": 100})
        enrollments = await self.pages(
            root + "/enrollments",
            [
                ("per_page", "100"),
                ("type[]", "StudentEnrollment"),
                ("state[]", "active"),
            ],
        )
        assignments = await self.pages(root + "/assignments", {"per_page": 100})
        submissions = await self.pages(
            root + "/students/submissions",
            {
                "per_page": 100,
                "student_ids[]": "all",
                "include[]": "visibility",
            },
        )
        return normalize_snapshot(
            self.origin, course, sections, enrollments, assignments, submissions
        )
