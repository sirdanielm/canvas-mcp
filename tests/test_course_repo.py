"""Independent requirements for an offline editable course repository."""

import json

import pytest
from test_course_mirror import make_snapshot

from canvas_mcp.mirror.core import MirrorError, read_json, sha
from canvas_mcp.mirror.repo import materialize, repo_diff


@pytest.mark.asyncio
async def test_lossless_source_and_unchanged_roundtrip(tmp_path):
    snapshot = await make_snapshot(tmp_path / "captures")
    destination = tmp_path / "editable"
    receipt = materialize(snapshot, destination)
    manifest = read_json(destination / "repo-manifest.json")
    assert receipt["completeness"] == "PARTIAL_CONTENT_ONLY"
    assert manifest["status"] == "LOCAL_ONLY_NOT_AUTHORIZED"
    assert manifest["canvas_writes"] == 0
    assert manifest["source_manifest_sha256"] == sha(
        (snapshot / "manifest.json").read_bytes()
    )
    assert (destination / "source/manifest.json").read_bytes() == (
        snapshot / "manifest.json"
    ).read_bytes()
    assert (destination / "source/core/objects/assignments.json").read_bytes() == (
        snapshot / "core/objects/assignments.json"
    ).read_bytes()
    assert repo_diff(destination)["changes"] == []
    assert not (destination / ".git").exists()
    assert (destination / "repo-manifest.json").stat().st_mode & 0o077 == 0


@pytest.mark.asyncio
async def test_html_edit_has_exact_identity_and_baseline(tmp_path):
    snapshot = await make_snapshot(tmp_path / "captures")
    destination = tmp_path / "editable"
    materialize(snapshot, destination)
    (destination / "working/core/assignments/9/description.html").write_text(
        "<p>New</p>"
    )
    result = repo_diff(destination)
    assert result["status"] == "DRAFT_NOT_AUTHORIZED"
    assert result["canvas_writes"] == 0
    assert len(result["changes"]) == 1
    change = result["changes"][0]
    assert change["course_id"] == "363308"
    assert change["object_id"] == "9"
    assert change["endpoint"] == "assignments"
    assert change["fields"] == ["description"]
    assert change["before"]["description"] == "<p>Old</p>"
    assert change["proposed"]["description"] == "<p>New</p>"
    assert change["baseline_object_sha256"]
    assert result["fresh_get_required"] is True


@pytest.mark.asyncio
async def test_conflicting_json_html_and_identity_edits_hold(tmp_path):
    snapshot = await make_snapshot(tmp_path / "captures")
    destination = tmp_path / "editable"
    materialize(snapshot, destination)
    path = destination / "working/core/assignments/9/object.json"
    value = read_json(path)
    value["description"] = "<p>JSON change</p>"
    path.write_text(json.dumps(value))
    (path.parent / "description.html").write_text("<p>HTML change</p>")
    assert repo_diff(destination)["status"] == "CONFLICT_REVIEW_REQUIRED"
    value["id"] = 999
    path.write_text(json.dumps(value))
    assert "SOURCE_IDENTITY_CHANGED" in repo_diff(destination)["holds"]


@pytest.mark.asyncio
async def test_source_tamper_is_rejected_and_destination_never_overwritten(tmp_path):
    snapshot = await make_snapshot(tmp_path / "captures")
    destination = tmp_path / "editable"
    materialize(snapshot, destination)
    with pytest.raises(MirrorError, match="DESTINATION_EXISTS"):
        materialize(snapshot, destination)
    (destination / "source/core/objects/assignments.json").write_text("[]")
    with pytest.raises(MirrorError, match="SNAPSHOT_FAILED_QC"):
        repo_diff(destination)


@pytest.mark.asyncio
async def test_missing_file_and_symlink_escape_are_holds(tmp_path):
    snapshot = await make_snapshot(tmp_path / "captures")
    destination = tmp_path / "editable"
    materialize(snapshot, destination)
    path = destination / "working/core/assignments/9/description.html"
    path.unlink()
    assert "WORKING_FILE_MISSING" in repo_diff(destination)["holds"]
    outside = tmp_path / "outside.html"
    outside.write_text("private")
    path.symlink_to(outside)
    with pytest.raises(MirrorError, match="UNSAFE_LOCAL_PATH"):
        repo_diff(destination)


@pytest.mark.asyncio
async def test_unknown_fields_and_null_removal_are_not_silently_ignored(tmp_path):
    def mutate(path, body):
        if path.endswith("/assignments"):
            body[0]["optional"] = None
        return body

    snapshot = await make_snapshot(tmp_path / "captures", mutate)
    destination = tmp_path / "editable"
    materialize(snapshot, destination)
    path = destination / "working/core/assignments/9/object.json"
    value = read_json(path)
    del value["optional"]
    path.write_text(json.dumps(value))
    result = repo_diff(destination)
    assert result["changes"][0]["fields"] == ["optional"]
    assert "UNSUPPORTED_EDIT_FIELD" in result["holds"]
    assert result["canvas_writes"] == 0


@pytest.mark.asyncio
async def test_forged_index_and_added_files_are_rejected(tmp_path):
    snapshot = await make_snapshot(tmp_path / "captures")
    destination = tmp_path / "editable"
    materialize(snapshot, destination)
    path = destination / "repo-manifest.json"
    value = read_json(path)
    value["objects"] = []
    path.write_text(json.dumps(value))
    with pytest.raises(MirrorError, match="REPO_INDEX_MISMATCH"):
        repo_diff(destination)


@pytest.mark.asyncio
async def test_crlf_unicode_html_roundtrips_exactly(tmp_path):
    def mutate(path, body):
        if path.endswith("/assignments"):
            body[0]["description"] = "<p>Éléments</p>\r\n<p>第二</p>"
        return body

    snapshot = await make_snapshot(tmp_path / "captures", mutate)
    destination = tmp_path / "editable"
    materialize(snapshot, destination)
    assert repo_diff(destination)["changes"] == []
    assert (
        destination / "working/core/assignments/9/description.html"
    ).read_bytes() == "<p>Éléments</p>\r\n<p>第二</p>".encode()


@pytest.mark.asyncio
async def test_only_exact_historical_scope_admits_unpublished_source(tmp_path):
    import httpx

    from canvas_mcp.mirror.core import COURSES, GetClient, capture, verify

    def handle(request):
        if request.url.path.endswith("/" + COURSES["historical_311463"]):
            return httpx.Response(
                200, json={"id": 311463, "workflow_state": "unpublished"}
            )
        if request.url.path.endswith("/settings"):
            return httpx.Response(200, json={})
        return httpx.Response(200, json=[])

    client = GetClient("synthetic", transport=httpx.MockTransport(handle))
    try:
        snapshot = await capture(tmp_path, client, ["historical_311463"])
        assert verify(snapshot)["ok"]
    finally:
        await client.close()
    from canvas_mcp.mirror.core import course_state_allowed

    assert not course_state_allowed("core", "unpublished")
    assert not course_state_allowed("advanced", "completed")
    assert not course_state_allowed("historical_311462", "deleted")
