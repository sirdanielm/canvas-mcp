"""Requirement-based tests for course file retrieval and provenance."""

import httpx
import pytest
from test_course_mirror import make_snapshot

from canvas_mcp.mirror.assets import download_files, verify_assets
from canvas_mcp.mirror.core import GetClient, MirrorError, read_json


async def file_snapshot(tmp_path):
    def mutate(path, body):
        if path.endswith("/files"):
            return [
                {
                    "id": 17,
                    "size": 5,
                    "url": "https://fcps.instructure.com/files/17/download?download_frd=1",
                    "filename": "../../untrusted.txt",
                    "folder_id": 2,
                }
            ]
        return body

    return await make_snapshot(tmp_path / "captures", mutate)


@pytest.mark.asyncio
async def test_redirect_does_not_forward_token_and_bytes_verify(tmp_path):
    snapshot = await file_snapshot(tmp_path)
    seen = []

    def handle(request):
        seen.append(request)
        if request.url.host == "fcps.instructure.com":
            assert request.headers["Authorization"] == "Bearer synthetic-secret"
            return httpx.Response(
                302,
                headers={
                    "Location": "https://a5990-17.cluster33.canvas-user-content.com/signed-file"
                },
            )
        assert "authorization" not in request.headers
        return httpx.Response(200, content=b"hello")

    transport = httpx.MockTransport(handle)
    client = GetClient("synthetic-secret", transport=transport)
    target = tmp_path / "assets"
    try:
        result = await download_files(snapshot, target, client, transport=transport)
    finally:
        await client.close()
    assert result["status"] == "COMPLETE"
    assert verify_assets(target, snapshot)["ok"]
    receipt = read_json(target / "assets-manifest.json")
    assert receipt["files"][0]["id"] == "17"
    assert receipt["files"][0]["size"] == 5
    assert (target / "core/files/17/content.bin").read_bytes() == b"hello"
    assert "synthetic-secret" not in (target / "assets-manifest.json").read_text()
    assert len(seen) == 2


@pytest.mark.asyncio
async def test_bad_file_origin_and_redirect_stop_before_unsafe_request(tmp_path):
    snapshot = await file_snapshot(tmp_path)
    calls = []
    transport = httpx.MockTransport(
        lambda r: (
            calls.append(r)
            or httpx.Response(302, headers={"Location": "http://evil.test/file"})
        )
    )
    client = GetClient("synthetic", transport=transport)
    try:
        with pytest.raises(MirrorError, match="FILE_REDIRECT_NOT_ALLOWED"):
            await download_files(
                snapshot, tmp_path / "assets", client, transport=transport
            )
        assert len(calls) == 1
    finally:
        await client.close()
    assert read_json(tmp_path / "assets/assets-manifest.json")["status"] == "INCOMPLETE"


@pytest.mark.asyncio
async def test_size_mismatch_no_success_and_partial_bytes_not_published(tmp_path):
    snapshot = await file_snapshot(tmp_path)
    transport = httpx.MockTransport(lambda r: httpx.Response(200, content=b"bad"))
    client = GetClient("synthetic", transport=transport)
    target = tmp_path / "assets"
    try:
        with pytest.raises(MirrorError, match="FILE_SIZE_MISMATCH"):
            await download_files(snapshot, target, client, transport=transport)
    finally:
        await client.close()
    assert not (target / "core/files/17/content.bin").exists()
    assert not verify_assets(target, snapshot)["ok"]


@pytest.mark.asyncio
async def test_403_is_an_exact_file_hold_with_no_retry(tmp_path):
    snapshot = await file_snapshot(tmp_path)
    seen = []
    transport = httpx.MockTransport(
        lambda r: seen.append(r) or httpx.Response(403, text="private payload")
    )
    client = GetClient("synthetic", transport=transport)
    try:
        with pytest.raises(MirrorError, match="FILE_HTTP_403"):
            await download_files(
                snapshot, tmp_path / "assets", client, transport=transport
            )
    finally:
        await client.close()
    assert len(seen) == 1
    v = read_json(tmp_path / "assets/assets-manifest.json")
    assert v["error"] == "FILE_HTTP_403"
    assert v["files"][0]["course"] == "core"
    assert v["files"][0]["id"] == "17"
    assert "private payload" not in str(v)


@pytest.mark.asyncio
async def test_other_file_id_storage_account_and_cluster_are_not_contacted(tmp_path):
    snapshot = await file_snapshot(tmp_path)
    for number, host in enumerate(
        [
            "a5990-18.cluster33.canvas-user-content.com",
            "a5991-17.cluster33.canvas-user-content.com",
            "a5990-17.cluster34.canvas-user-content.com",
        ]
    ):
        seen = []
        transport = httpx.MockTransport(
            lambda r, seen=seen, host=host: (
                seen.append(r)
                or httpx.Response(
                    302, headers={"Location": "https://" + host + "/file"}
                )
            )
        )
        client = GetClient("synthetic", transport=transport)
        try:
            with pytest.raises(MirrorError, match="FILE_REDIRECT_NOT_ALLOWED"):
                await download_files(
                    snapshot, tmp_path / f"wrong-{number}", client, transport=transport
                )
        finally:
            await client.close()
        assert len(seen) == 1


@pytest.mark.asyncio
async def test_self_consistent_omission_receipt_cannot_replace_pinned_source(tmp_path):
    from canvas_mcp.mirror.core import private_write

    snapshot = await file_snapshot(tmp_path)
    transport = httpx.MockTransport(lambda r: httpx.Response(200, content=b"hello"))
    client = GetClient("synthetic", transport=transport)
    target = tmp_path / "assets"
    try:
        await download_files(snapshot, target, client, transport=transport)
    finally:
        await client.close()
    path = target / "assets-manifest.json"
    value = read_json(path)
    value.update(files=[], expected_count=0, expected_bytes=0)
    private_write(path, value, replace=True)
    result = verify_assets(target, snapshot)
    assert not result["ok"]
    assert "ASSET_SOURCE_INVENTORY_MISMATCH" in result["errors"]
    assert "ASSET_SOURCE_IDENTITY_SET_MISMATCH" in result["errors"]


@pytest.mark.asyncio
async def test_invalid_declared_sizes_stop_before_sum_or_transport(tmp_path):
    from canvas_mcp.mirror.assets import MAX_FILE_BYTES

    for number, sizes in enumerate(
        [
            [-1, 1],
            [True, 1],
            [MAX_FILE_BYTES + 1, -MAX_FILE_BYTES],
            [MAX_FILE_BYTES + 1, 0],
        ]
    ):

        def mutate(path, body, sizes=sizes):
            if path.endswith("/files"):
                return [
                    {
                        "id": 17 + i,
                        "size": size,
                        "url": f"https://fcps.instructure.com/files/{17 + i}/download",
                    }
                    for i, size in enumerate(sizes)
                ]
            return body

        snapshot = await make_snapshot(tmp_path / f"captures-{number}", mutate)
        transport = httpx.MockTransport(
            lambda r: pytest.fail("No request is allowed for an invalid inventory")
        )
        client = GetClient("synthetic", transport=transport)
        try:
            with pytest.raises(MirrorError, match="FILE_SIZE_BOUND_REQUIRED"):
                await download_files(
                    snapshot, tmp_path / f"assets-{number}", client, transport=transport
                )
        finally:
            await client.close()
        assert not (tmp_path / f"assets-{number}").exists()


@pytest.mark.asyncio
async def test_unsupported_assets_schema_is_not_verified(tmp_path):
    from canvas_mcp.mirror.core import private_write

    snapshot = await file_snapshot(tmp_path)
    transport = httpx.MockTransport(lambda r: httpx.Response(200, content=b"hello"))
    client = GetClient("synthetic", transport=transport)
    target = tmp_path / "assets"
    try:
        await download_files(snapshot, target, client, transport=transport)
    finally:
        await client.close()
    path = target / "assets-manifest.json"
    value = read_json(path)
    value["schema_version"] = 999
    private_write(path, value, replace=True)
    assert "ASSET_MANIFEST_INCOMPLETE" in verify_assets(target, snapshot)["errors"]


@pytest.mark.asyncio
async def test_only_verified_three_host_chain_reaches_final_storage(tmp_path):
    snapshot = await file_snapshot(tmp_path)
    seen = []

    def handle(request):
        seen.append(request)
        if request.url.host == "fcps.instructure.com":
            assert request.headers["Authorization"] == "Bearer synthetic"
            return httpx.Response(
                302,
                headers={
                    "Location": "https://a5990-17.cluster33.canvas-user-content.com/file"
                },
            )
        assert "authorization" not in request.headers
        if request.url.host == "a5990-17.cluster33.canvas-user-content.com":
            return httpx.Response(
                302,
                headers={
                    "Location": "https://inst-fs-iad-prod.inscloudgate.net/file?token=synthetic-signed-token"
                },
            )
        assert request.url.host == "inst-fs-iad-prod.inscloudgate.net"
        return httpx.Response(200, content=b"hello")

    transport = httpx.MockTransport(handle)
    client = GetClient("synthetic", transport=transport)
    try:
        await download_files(snapshot, tmp_path / "assets", client, transport=transport)
    finally:
        await client.close()
    assert len(seen) == 3
    assert (
        "synthetic-signed-token"
        not in (tmp_path / "assets/assets-manifest.json").read_text()
    )


@pytest.mark.asyncio
async def test_final_storage_cannot_skip_the_file_bound_first_storage(tmp_path):
    snapshot = await file_snapshot(tmp_path)
    seen = []
    transport = httpx.MockTransport(
        lambda r: (
            seen.append(r)
            or httpx.Response(
                302,
                headers={"Location": "https://inst-fs-iad-prod.inscloudgate.net/file"},
            )
        )
    )
    client = GetClient("synthetic", transport=transport)
    try:
        with pytest.raises(MirrorError, match="FILE_REDIRECT_NOT_ALLOWED"):
            await download_files(
                snapshot, tmp_path / "assets", client, transport=transport
            )
    finally:
        await client.close()
    assert len(seen) == 1


@pytest.mark.asyncio
async def test_complete_four_host_chain_never_forwards_bearer(tmp_path):
    snapshot = await file_snapshot(tmp_path)
    seen = []

    def handle(request):
        seen.append(request)
        if request.url.host == "fcps.instructure.com":
            assert "authorization" in request.headers
            return httpx.Response(
                302,
                headers={
                    "Location": "https://a5990-17.cluster33.canvas-user-content.com/file"
                },
            )
        assert "authorization" not in request.headers
        if request.url.host == "a5990-17.cluster33.canvas-user-content.com":
            return httpx.Response(
                302,
                headers={"Location": "https://inst-fs-iad-prod.inscloudgate.net/file"},
            )
        if request.url.host == "inst-fs-iad-prod.inscloudgate.net":
            return httpx.Response(
                302,
                headers={
                    "Location": "https://cdn.inst-fs-iad-prod.inscloudgate.net/file?token=synthetic-token"
                },
            )
        assert request.url.host == "cdn.inst-fs-iad-prod.inscloudgate.net"
        return httpx.Response(200, content=b"hello")

    transport = httpx.MockTransport(handle)
    client = GetClient("synthetic", transport=transport)
    try:
        await download_files(snapshot, tmp_path / "assets", client, transport=transport)
    finally:
        await client.close()
    assert len(seen) == 4
    assert verify_assets(tmp_path / "assets", snapshot)["ok"]


@pytest.mark.asyncio
async def test_cdn_cannot_skip_gateway(tmp_path):
    snapshot = await file_snapshot(tmp_path)
    seen = []

    def handle(request):
        seen.append(request)
        target = (
            "a5990-17.cluster33.canvas-user-content.com"
            if request.url.host == "fcps.instructure.com"
            else "cdn.inst-fs-iad-prod.inscloudgate.net"
        )
        return httpx.Response(302, headers={"Location": "https://" + target + "/file"})

    transport = httpx.MockTransport(handle)
    client = GetClient("synthetic", transport=transport)
    try:
        with pytest.raises(MirrorError, match="FILE_REDIRECT_NOT_ALLOWED"):
            await download_files(
                snapshot, tmp_path / "assets", client, transport=transport
            )
    finally:
        await client.close()
    assert len(seen) == 2
