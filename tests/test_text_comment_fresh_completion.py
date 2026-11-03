"""Synthetic canonical-ledger and HTTP transport tests; no live records."""

import copy
import json
from urllib.parse import parse_qs

import httpx
import pytest

from canvas_mcp.gradebook import text_comment_delivery_v4 as base
from canvas_mcp.gradebook import text_comment_fresh_completion as fresh
from canvas_mcp.gradebook.client import GradebookClient, GradebookError
from canvas_mcp.gradebook.ledger import Ledger
from canvas_mcp.gradebook.store import Store


@pytest.fixture
def configured(tmp_path, monkeypatch):
    root = tmp_path / "private"
    store = Store(root)
    ledger = Ledger(root)
    monkeypatch.setattr(base.time, "time", lambda: 1000)
    counter = 0

    def pin(value):
        nonlocal counter
        counter += 1
        path = root / f"input-{counter}.json"
        path.write_bytes(value if isinstance(value, bytes) else json.dumps(value).encode())
        path.chmod(0o600)
        return base.file_pin(path)

    evidence = pin({"fictional": True})
    assignment = {"id": 20, "course_id": 10, "published": True, "grading_type": "points",
                  "in_closed_grading_period": False, "post_manually": False,
                  "submission_types": ["on_paper"], "moderated_grading": False,
                  "anonymous_grading": False, "group_category_id": None, "points_possible": 100}
    records, submissions = [], {}
    for index in range(3):
        uid = 101 + index
        submission = {"id": 201 + index, "user_id": uid, "assignment_id": 20,
                      "attempt": None, "excused": False, "assignment_visible": True,
                      "grade_matches_current_submission": True, "score": 75, "grade": "75",
                      "submission_comments": []}
        submissions[uid] = submission
        record = {"course_id": 10, "assignment_id": 20, "user_id": uid,
                  "submission_id": submission["id"], "section_id": 30,
                  "attempt": None, "pin": str(1001 + index),
                  "body_ref": pin(f"Fictional feedback {index}\n".encode()),
                  "submission_ref": pin(submission), "assignment_ref": pin(assignment)}
        record["source_ref"] = pin({"kind": "AUDITED_SHEET_TEXT_COMMENT_SOURCE_BINDING",
                                    "target": base.target(record), "body_ref": record["body_ref"],
                                    "audited_resolved": True, "canvas_text_release": True,
                                    "central_mirror_receipt_ref": evidence,
                                    "owner_evidence_refs": [evidence]})
        records.append(record)
    origin = "https://canvas.invalid"
    authority = pin({"kind": "DIRECT_HUMAN_TEXT_COMMENT_RELEASE_BINDING", "origin": origin,
                     "records": [{**base.target(r), "pin": r["pin"], "body_ref": r["body_ref"]} for r in records],
                     "direct_human_approval": True, "text_only": True, "grade_write": False,
                     "pdf_upload": False, "original_human_evidence_ref": evidence})
    manifest = {"kind": "EXACT_AUDITED_SHEET_TEXT_COMMENT_RELEASE_V1", "origin": origin,
                "actor_id": 9, "records": records, "not_before": 1000, "expires": 1100,
                "submission_include": ["visibility", "submission_comments"], "assignment_include": [],
                "authority_ref": authority, "coverage_ref": pin({"kind": "REVIEWED_COMPLETE_SUBMISSION_COMMENTS_GET_CONTRACT",
                    "origin": origin, "include": ["visibility", "submission_comments"],
                    "complete": True, "evidence_ref": evidence})}
    manifest_ref = pin(manifest)
    ancestors = []
    for index, table in enumerate(sorted(fresh.ANCESTOR_TABLES)):
        op = str(index + 1) * 32
        plan_id, _ = store.save("review", {"origin": origin, "actor_id": 9, "items": [
            {"record": r, "body": base.pinned(r["body_ref"]).decode()} for r in records]})
        with ledger.connect() as db:
            db.execute(f"CREATE TABLE IF NOT EXISTS {table} (target TEXT PRIMARY KEY, operation_id TEXT, position INTEGER, plan_id TEXT, phase TEXT, state_id TEXT)")
            db.execute("INSERT INTO operations VALUES(?,?,?,?,?,?)", (op, plan_id, "old-token", 900, "prepared", 800))
            for position, record in enumerate(records):
                target = base.key(origin, record)
                db.execute("INSERT INTO items VALUES(?,?,?,?)", (op, position, target, "planned"))
                db.execute(f"INSERT INTO {table} VALUES(?,?,?,?,?,NULL)", (target, op, position, plan_id, "prepared"))
            snapshot = {"operation": dict(db.execute("SELECT * FROM operations WHERE id=?", (op,)).fetchone()),
                        "items": [dict(x) for x in db.execute("SELECT * FROM items WHERE operation_id=? ORDER BY position", (op,))],
                        "claims": [dict(x) for x in db.execute(f"SELECT * FROM {table} WHERE operation_id=? ORDER BY position", (op,))]}
        ancestors.append({"claim_table": table, "snapshot_ref": pin(snapshot)})
    certificate = {"kind": "FRESH_THREE_TEXT_COMMENT_COMPLETION_V1", "human_event_id": "00000000-0000-4000-8000-000000000001",
                   "original_human_evidence_ref": evidence, "origin": origin, "actor_id": 9,
                   "manifest_sha256": manifest_ref["sha256"], "not_before": 1000, "expires": 1100,
                   "text_only": True, "grade_write": False, "pdf_upload": False,
                   "producer_history": "UNKNOWN_PRESERVED", "records": [
                       {**base.target(r), "pin": r["pin"], "body_ref": r["body_ref"], "source_ref": r["source_ref"]} for r in records],
                   "ancestors": ancestors}
    puts = []
    transport_state = {"lost_reply": False}

    def respond(request):
        path = request.url.path
        if path.endswith("/users/self"):
            value = {"id": 9}
        elif "/submissions/" in path:
            uid = int(path.rsplit("/", 1)[1])
            value = submissions[uid]
            if request.method == "PUT":
                fields = parse_qs(request.content.decode())
                assert set(fields) == {"comment[text_comment]", "comment[group_comment]"}
                assert fields["comment[group_comment]"] == ["false"]
                puts.append(fields)
                value["submission_comments"].append({"id": 300 + uid, "author_id": 9,
                    "comment": fields["comment[text_comment]"][0], "created_at": "2026-10-14T00:00:00Z"})
                if transport_state["lost_reply"]:
                    raise httpx.ReadTimeout("fictional lost response")
        elif path.endswith("/assignments/20"):
            value = assignment
        elif path.endswith("/permissions"):
            value = {"manage_grades": True}
        elif path.endswith("/enrollments"):
            uid = int(request.url.params["user_id"])
            value = [{"user_id": uid, "course_id": 10, "type": "StudentEnrollment", "enrollment_state": "active", "course_section_id": 30}]
        else:
            value = {"id": 10, "workflow_state": "available"}
        return httpx.Response(200, json=value)

    client = GradebookClient(origin, "fictional-token", httpx.MockTransport(respond))

    def make(change=None, current=lambda: None, *, present=None, lease=None, lost_reply=False):
        transport_state["lost_reply"] = lost_reply
        cert = copy.deepcopy(certificate)
        current_manifest = copy.deepcopy(manifest)
        if lease:
            current_manifest["not_before"], current_manifest["expires"] = lease
            cert["not_before"], cert["expires"] = lease
        current_manifest_ref = pin(current_manifest)
        cert["manifest_sha256"] = current_manifest_ref["sha256"]
        if present is not None:
            for record in records:
                submissions[record["user_id"]]["submission_comments"] = ([{
                    "id": 300 + record["user_id"], "author_id": 9,
                    "comment": base.pinned(record["body_ref"]).decode(),
                    "created_at": "2026-10-14T00:00:00Z"}] if present else [])
        if change:
            change(cert)
        ref = pin(cert)
        monkeypatch.setattr(fresh, "REVIEWED_CERTIFICATE_SHA256", ref["sha256"])
        monkeypatch.setattr(base, "REVIEWED_MANIFEST_SHA256", current_manifest_ref["sha256"])
        return fresh.FreshTextCommentCompletion(client, store, ledger, current_manifest_ref,
                                               canonical_root=root, certificate_ref=ref, current_control_check=current)

    return make, client, store, ledger, manifest_ref, certificate, puts


async def test_default_claim_still_blocks(configured):
    make, client, store, ledger, manifest, _, puts = configured
    make()
    try:
        with pytest.raises(GradebookError, match="TEXT_TARGET_PERMANENTLY_CLAIMED"):
            await base.TextCommentDelivery(client, store, ledger, manifest, canonical_root=store.root).prepare()
        assert puts == []
    finally:
        await client.close()


async def test_fresh_completion_same_sender_preserves_ancestors_and_grades(configured):
    make, client, _, ledger, _, certificate, puts = configured
    delivery = make()
    try:
        result = await delivery.prepare()
        assert result["count"] == 3
        outcome = await delivery.confirm(result["plan_id"], result["operation_id"], result["confirmation_token"],
                                         enabled=True, reviewed_plan_sha256=result["plan_id"])
        assert len(puts) == 3
        assert outcome
        assert all(i["status"] == "verified" for i in ledger.operation(result["operation_id"])["items"])
        with ledger.connect() as db:
            for ancestor in certificate["ancestors"]:
                expected = fresh._json_pin(ancestor["snapshot_ref"])
                assert dict(db.execute("SELECT * FROM operations WHERE id=?", (expected["operation"]["id"],)).fetchone()) == expected["operation"]
                assert [dict(x) for x in db.execute("SELECT * FROM items WHERE operation_id=? ORDER BY position", (expected["operation"]["id"],))] == expected["items"]
                assert [dict(x) for x in db.execute(f"SELECT * FROM {ancestor['claim_table']} WHERE operation_id=? ORDER BY position", (expected["operation"]["id"],))] == expected["claims"]
            assert db.execute(f"SELECT producer_history FROM {fresh.DISPOSITIONS}").fetchone()[0] == "UNKNOWN_PRESERVED"
        with pytest.raises(GradebookError):
            await delivery.confirm(result["plan_id"], result["operation_id"], result["confirmation_token"],
                                   enabled=True, reviewed_plan_sha256=result["plan_id"])
        assert len(puts) == 3
    finally:
        await client.close()


async def test_noop_consumes_event_even_if_comments_later_disappear(configured):
    make, client, _, ledger, _, _, puts = configured
    try:
        result = await make(present=True).prepare()
        assert result["status"] == "NO_OP"
        with ledger.connect() as db:
            row = db.execute(f"SELECT * FROM {fresh.DISPOSITIONS}").fetchone()
            assert row["operation_id"] is None and row["outcome"] == "NO_OP"
            assert db.execute("SELECT COUNT(*) FROM operations").fetchone()[0] == 2
        with pytest.raises(GradebookError, match="COMPLETION_EVENT_ALREADY_CLAIMED"):
            await make(present=False, lease=(999, 1099)).prepare()
        assert puts == []
    finally:
        await client.close()


async def test_expired_authority_before_confirm_never_sends(configured, monkeypatch):
    make, client, _, _, _, _, puts = configured
    delivery = make()
    try:
        result = await delivery.prepare()
        monkeypatch.setattr(base.time, "time", lambda: 1200)
        with pytest.raises(GradebookError, match="EXPIRED"):
            await delivery.confirm(result["plan_id"], result["operation_id"], result["confirmation_token"],
                                   enabled=True, reviewed_plan_sha256=result["plan_id"])
        assert puts == []
    finally:
        await client.close()


async def test_uncertain_put_reconciles_without_retry(configured):
    make, client, _, ledger, _, _, puts = configured
    delivery = make(lost_reply=True)
    try:
        result = await delivery.prepare()
        await delivery.confirm(result["plan_id"], result["operation_id"], result["confirmation_token"],
                               enabled=True, reviewed_plan_sha256=result["plan_id"])
        assert len(puts) == 1
        assert ledger.operation(result["operation_id"])["items"][0]["status"] == "uncertain"
        await delivery.reconcile(result["plan_id"], result["operation_id"])
        assert len(puts) == 1
        assert ledger.operation(result["operation_id"])["items"][0]["status"] == "observed_applied"
        with pytest.raises(GradebookError):
            await delivery.confirm(result["plan_id"], result["operation_id"], result["confirmation_token"],
                                   enabled=True, reviewed_plan_sha256=result["plan_id"])
        assert len(puts) == 1
    finally:
        await client.close()


@pytest.mark.parametrize("change", [
    lambda c: c["records"][0].update(user_id=999),
    lambda c: c["records"][0].update(source_ref=c["original_human_evidence_ref"]),
    lambda c: c.update(grade_write=True),
    lambda c: c.update(expires=999),
    lambda c: c.update(producer_history="ZERO_SEND"),
    lambda c: c.update(records=c["records"][:1]),
])
async def test_bad_certificate_holds_without_put(configured, change):
    make, client, _, _, _, _, puts = configured
    try:
        with pytest.raises(GradebookError):
            await make(change).prepare()
        assert puts == []
    finally:
        await client.close()


@pytest.mark.parametrize("sql", [
    "UPDATE operations SET expires=1050 WHERE id='11111111111111111111111111111111'",
    "UPDATE operations SET status='running' WHERE id='11111111111111111111111111111111'",
    "UPDATE items SET status='sending' WHERE operation_id='11111111111111111111111111111111'",
    "INSERT INTO target_locks SELECT target,'foreign' FROM items LIMIT 1",
])
async def test_changed_or_active_ancestor_holds(configured, sql):
    make, client, _, ledger, _, _, puts = configured
    with ledger.connect() as db:
        db.execute(sql)
    try:
        with pytest.raises(GradebookError):
            await make().prepare()
        assert puts == []
    finally:
        await client.close()


async def test_current_gate_and_closed_table_enum(configured):
    make, client, _, _, _, _, puts = configured
    delivery = make(current=lambda: False)
    try:
        with pytest.raises(GradebookError, match="CURRENT_COMPLETION"):
            await delivery.prepare()
        delivery._claim_table = lambda: "unsafe;DROP TABLE operations"
        with pytest.raises(GradebookError, match="UNREVIEWED_CLAIM_TABLE"):
            delivery._checked_claim_table()
        assert puts == []
    finally:
        await client.close()


@pytest.mark.parametrize("generic_enabled", [False, True])
async def test_sealed_comment_release_opt_in_does_not_enable_generic_publisher(tmp_path, generic_enabled):
    from fastmcp import Client

    from canvas_mcp.gradebook.server import create_server
    from canvas_mcp.gradebook.text_comments_mcp import QualifiedTextRelease

    class FictionalDelivery:
        manifest_ref = {"path": "/fictional/reviewed.json", "sha256": "a" * 64, "bytes": 1}
        def _authority(self, manifest):
            raise AssertionError("Tool listing must not inspect or publish a release")

    calls = []
    def release_factory(publisher):
        calls.append(publisher)
        return {"a" * 64: QualifiedTextRelease(FictionalDelivery(), lambda: None)}

    client = GradebookClient("https://canvas.invalid", "fictional-token",
        transport=httpx.MockTransport(lambda request: pytest.fail("No network during registration")))
    try:
        server = create_server(client, Store(tmp_path), {"core": "12"},
            enable_qualified_comments=True, comment_release_factory=release_factory,
            enable_comments=generic_enabled)
        async with Client(server) as mcp:
            names = {tool.name for tool in await mcp.list_tools()}
        assert len(calls) == 1
        assert "confirm_submission_comments" in names
        assert ("confirm_gradebook_comment_push" in names) is generic_enabled
        assert "confirm_gradebook_push" not in names
    finally:
        await client.close()


async def test_explicit_canonical_root_mismatch_is_held_before_transport(configured, tmp_path):
    make, client, _, _, _, _, puts = configured
    delivery = make()
    delivery.canonical_root = tmp_path / "different-private-store"
    try:
        with pytest.raises(GradebookError, match="SHARED_CANONICAL_STATE_REQUIRED"):
            await delivery.prepare()
        assert puts == []
    finally:
        await client.close()
