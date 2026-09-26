"""Synthetic-only regression coverage for mirror safety and deterministic changes."""

import httpx
import pytest

from canvas_mcp.mirror.core import (
    COURSES,
    GetClient,
    MirrorError,
    audit,
    capture,
    check_proposal,
    diff,
    link_inventory,
    private_write,
    read_json,
    resources_check,
    sha,
    stage_description,
    status,
    verify,
)


def fixture_body(path):
    if path.endswith("/modules/7/items"):
        return [{"id": 71, "type": "Assignment", "content_id": 9, "published": True}]
    if path.endswith("/assignments"):
        return [
            {
                "id": 9,
                "name": "Synthetic task",
                "description": "<p>Old</p>",
                "published": True,
                "points_possible": 20,
                "all_dates": [],
                "updated_at": "A",
            }
        ]
    if path.endswith("/modules"):
        return [{"id": 7, "items_count": 1}]
    if path.endswith("/settings"):
        return {"setting": True}
    if path.endswith("/" + COURSES["core"]):
        return {"id": int(COURSES["core"]), "workflow_state": "available"}
    return []


async def make_snapshot(root, mutate=None):
    def handle(request):
        assert request.method == "GET"
        assert request.url.host == "fcps.instructure.com"
        body = fixture_body(request.url.path)
        if mutate:
            body = mutate(request.url.path, body)
        return httpx.Response(200, json=body)

    client = GetClient("synthetic-secret", transport=httpx.MockTransport(handle))
    try:
        return await capture(root, client, ["core"])
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_capture_qc_and_audit(tmp_path):
    snapshot = await make_snapshot(tmp_path)
    assert verify(snapshot)["ok"]
    assert audit(snapshot)["findings"] == []
    assert audit(snapshot)["counts"]["core"]["assignments"] == 1
    manifest = read_json(snapshot / "manifest.json")
    assert all(x["method"] == "GET" for x in manifest["entries"])
    assert "synthetic-secret" not in (snapshot / "manifest.json").read_text()
    assert (snapshot / "manifest.json").stat().st_mode & 0o077 == 0


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "suffix",
    [
        "/students/submissions",
        "/enrollments",
        "/../users/self",
        "//evil.test",
        "/modules/1/../items",
    ],
)
async def test_reject_noncontent_paths_before_transport(suffix):
    def forbidden(request):
        pytest.fail("Network was reached")

    client = GetClient("secret", transport=httpx.MockTransport(forbidden))
    try:
        with pytest.raises(MirrorError, match="ENDPOINT_NOT_ALLOWED"):
            await client.read("core", suffix, True)
    finally:
        await client.close()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "target",
    [
        "https://evil.test/api/v1/courses/363308/assignments?page=2",
        "/api/v1/courses/363308/sections?page=2",
        "https://fcps.instructure.com@evil.test/path",
        "https://fcps.instructure.com:443/api/v1/courses/363308/assignments?page=2",
    ],
)
async def test_pagination_never_leaks_credentials(target):
    calls = []

    def handle(request):
        calls.append(request)
        return httpx.Response(
            200, json=[{"id": 1}], headers={"Link": f'<{target}>; rel="next"'}
        )

    client = GetClient("secret", transport=httpx.MockTransport(handle))
    try:
        with pytest.raises(MirrorError, match="PAGINATION_TARGET_CHANGED"):
            await client.read("core", "/assignments", True)
        assert len(calls) == 1
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_complete_pagination_and_duplicate_identity():
    def handle(request):
        if request.url.params.get("page") == "2":
            return httpx.Response(200, json=[{"id": 2}])
        return httpx.Response(
            200,
            json=[{"id": 1}],
            headers={"Link": '</api/v1/courses/363308/assignments?page=2>; rel="next"'},
        )

    client = GetClient("secret", transport=httpx.MockTransport(handle))
    try:
        assert await client.read("core", "/assignments", True) == [{"id": 1}, {"id": 2}]
    finally:
        await client.close()
    client = GetClient(
        "secret",
        transport=httpx.MockTransport(
            lambda r: httpx.Response(200, json=[{"id": 1}, {"id": 1}])
        ),
    )
    try:
        with pytest.raises(MirrorError, match="DUPLICATE_OBJECT_ID"):
            await client.read("core", "/assignments", True)
    finally:
        await client.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [301, 401, 403, 404])
async def test_http_failures_do_not_echo_body_or_retry(status):
    client = GetClient(
        "secret",
        transport=httpx.MockTransport(
            lambda r: httpx.Response(
                status,
                text="private response",
                headers={"Location": "https://evil.test"},
            )
        ),
    )
    try:
        with pytest.raises(MirrorError, match=f"HTTP_{status}") as failure:
            await client.read("core", "/assignments", True)
        assert "private" not in str(failure.value)
        assert client.requests == 1
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_long_retry_after_stops_without_early_retry():
    client = GetClient(
        "secret",
        transport=httpx.MockTransport(
            lambda r: httpx.Response(429, headers={"Retry-After": "120"})
        ),
    )
    try:
        with pytest.raises(MirrorError, match="SERVER_BACKOFF_REQUIRED"):
            await client.read("core", "/assignments", True)
        assert client.requests == 1
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_failure_preserves_partial_without_replacing_baseline(tmp_path):
    old = await make_snapshot(tmp_path)
    old_manifest = (old / "manifest.json").read_bytes()

    def fail(path, body):
        return {"not": "a list"} if path.endswith("/assignments") else body

    with pytest.raises(MirrorError, match="COLLECTION_SHAPE_INVALID"):
        await make_snapshot(tmp_path, fail)
    assert (old / "manifest.json").read_bytes() == old_manifest
    new = next(p for p in tmp_path.iterdir() if p != old)
    assert read_json(new / "manifest.json")["status"] == "INCOMPLETE"
    assert not verify(new)["ok"]
    with pytest.raises(MirrorError, match="SNAPSHOT_FAILED_QC"):
        diff(old, new)


@pytest.mark.asyncio
async def test_unpublished_course_rejected(tmp_path):
    def change(path, body):
        if path.endswith("/" + COURSES["core"]):
            body["workflow_state"] = "unpublished"
        return body

    with pytest.raises(MirrorError, match="COURSE_NOT_PUBLISHED"):
        await make_snapshot(tmp_path, change)


@pytest.mark.asyncio
async def test_module_count_race_stops_capture(tmp_path):
    with pytest.raises(MirrorError, match="MODULE_ITEM_COUNT_CHANGED"):
        await make_snapshot(
            tmp_path,
            lambda path, body: [] if path.endswith("/modules/7/items") else body,
        )


@pytest.mark.asyncio
async def test_hash_and_manifest_scope_tampering_detected(tmp_path):
    snapshot = await make_snapshot(tmp_path)
    path = snapshot / "core/objects/assignments.json"
    path.write_text("[]")
    assert "HASH_MISMATCH" in verify(snapshot)["errors"]
    manifest = read_json(snapshot / "manifest.json")
    manifest["entries"] = [x for x in manifest["entries"] if x["key"] != "assignments"]
    private_write(snapshot / "manifest.json", manifest, replace=True)
    assert "REQUIRED_ENDPOINT_MISSING" in verify(snapshot)["errors"]


@pytest.mark.asyncio
async def test_delta_ignores_volatile_but_catches_instructional_change(tmp_path):
    before = await make_snapshot(tmp_path)

    def change(path, body):
        if path.endswith("/assignments"):
            body[0].update(
                description="<p>Changed</p>", updated_at="B", needs_grading_count=99
            )
        return body

    after = await make_snapshot(tmp_path, change)
    delta = diff(before, after)
    assert delta["counts"] == {"changed": 1}
    assert delta["changes"][0]["fields"] == ["description"]
    assert diff(after, after)["changes"] == []


@pytest.mark.asyncio
async def test_proposal_is_local_and_conflict_checked(tmp_path):
    before = await make_snapshot(tmp_path)
    proposal = tmp_path / "proposal.json"
    result = stage_description(before, "core", "9", "<p>New</p>", proposal)
    assert result["status"] == "DRAFT_NOT_AUTHORIZED"
    assert (
        check_proposal(before, proposal)["status"] == "BASELINE_MATCH_NOT_AUTHORIZATION"
    )

    def change(path, body):
        if path.endswith("/assignments"):
            body[0]["points_possible"] = 25
        return body

    after = await make_snapshot(tmp_path, change)
    assert check_proposal(after, proposal)["status"] == "CONFLICT_REVIEW_REQUIRED"
    data = read_json(proposal)
    data["proposed_description"] = "tampered"
    private_write(proposal, data, replace=True)
    with pytest.raises(MirrorError, match="PROPOSAL_HASH_MISMATCH"):
        check_proposal(before, proposal)
    with pytest.raises(FileExistsError):
        stage_description(before, "core", "9", "another", proposal)


def test_resource_escape_and_hash_verification(tmp_path):
    g = tmp_path / "google-resources"
    private_write(g / "files/file.json", {"synthetic": True})
    blob = (g / "files/file.json").read_bytes()
    resource = {
        "id": "safe",
        "export": {
            "relative_path": "files/file.json",
            "sha256": sha(blob),
            "bytes": len(blob),
        },
    }
    private_write(g / "manifest.json", {"resources": [resource]})
    assert resources_check(tmp_path)["ok"]
    resource["export"]["relative_path"] = "../../secret"
    private_write(g / "manifest.json", {"resources": [resource]}, replace=True)
    assert not resources_check(tmp_path)["ok"]


@pytest.mark.asyncio
async def test_links_keep_lti_unknown_and_extract_direct_google_id(tmp_path):
    def change(path, body):
        if path.endswith("/assignments"):
            body[0][
                "description"
            ] = '<a href="https://docs.google.com/document/d/synthetic-doc/edit">File</a><a href="mailto:private@example.test">email</a>'
            body[0]["external_tool_tag_attributes"] = {
                "url": "https://assignments.google.com/lti/example"
            }
        return body

    snapshot = await make_snapshot(tmp_path, change)
    result = link_inventory(snapshot)
    assert result["google_resource_ids"] == 1
    assert result["opaque_lti_links"] == 1
    assert all(x["host"] != "private@example.test" for x in result["links"])
    lti = next(x for x in result["links"] if x["status"] == "OPAQUE_LTI")
    assert lti["google_file_id"] is None
    assert status(tmp_path)["snapshots"][0]["qc_ok"] is True


@pytest.mark.asyncio
async def test_diff_removal_from_complete_empty_collection(tmp_path):
    before = await make_snapshot(tmp_path)

    def change(path, body):
        if path.endswith("/assignments"):
            return []
        return body

    after = await make_snapshot(tmp_path, change)
    changes = diff(before, after)["changes"]
    assert len(changes) == 1 and changes[0]["change"] == "removed_from_snapshot"
    assert audit(after)["findings"][0]["code"] == "ASSIGNMENT_REFERENCE_UNRESOLVED"


@pytest.mark.asyncio
async def test_duplicate_placement_is_review_finding(tmp_path):
    def change(path, body):
        if path.endswith("/modules"):
            body[0]["items_count"] = 2
        elif path.endswith("/modules/7/items"):
            body.append(
                {"id": 72, "type": "Assignment", "content_id": 9, "published": True}
            )
        return body

    snapshot = await make_snapshot(tmp_path, change)
    assert audit(snapshot)["findings"] == [
        {"course": "core", "code": "REPEATED_ASSIGNMENT_PLACEMENT", "id": "9"}
    ]


@pytest.mark.asyncio
async def test_transient_retries_are_bounded(monkeypatch):
    delays = []

    async def sleep(delay):
        delays.append(delay)

    monkeypatch.setattr("canvas_mcp.mirror.core.asyncio.sleep", sleep)
    client = GetClient(
        "secret", transport=httpx.MockTransport(lambda r: httpx.Response(503))
    )
    try:
        with pytest.raises(MirrorError, match="HTTP_503"):
            await client.read("core", "/assignments", True)
        assert client.requests == 3
        assert delays == [1, 2]
    finally:
        await client.close()
