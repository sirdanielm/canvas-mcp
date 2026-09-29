"""Canonical two-course worker integration, fictional GET transport only.

The Google fake models atomic commits using the native projector, while test
assertions independently inspect literal grade cells, stored baselines, HTTP
methods, durable operation state, reference preservation, and write counts.
No planner, native validator, verifier, or artifact-store function is mocked.
"""

import copy
import uuid

import httpx
import pytest
from test_gradebook_native import initial_raw, raw_from_state

from canvas_mcp.gradebook.client import GradebookClient, GradebookError
from canvas_mcp.gradebook.model import normalize_snapshot
from canvas_mcp.gradebook.native import _apply_requests, _state
from canvas_mcp.gradebook.store import Store
from canvas_mcp.gradebook.worker import (
    RefreshWorker,
    metadata_create,
    queue_metadata,
    stamp,
)

BOOK = "fictional-book"
INSTANCE = "11111111-1111-1111-1111-111111111111"
BINDINGS = {
    "core": {
        "label": "Fictional Core",
        "course_id": "12",
        "spreadsheet_id": BOOK,
        "sheets": {"Canvas": 1, "Working": 2, "_Sync": 3},
        "tab_names": {
            "Canvas": "Core GET",
            "Working": "Core Edit",
            "_Sync": "_Core Sync",
        },
        "working_protection_id": 102,
    },
    "advanced": {
        "label": "Fictional Advanced",
        "course_id": "13",
        "spreadsheet_id": BOOK,
        "sheets": {"Canvas": 5, "Working": 6, "_Sync": 7},
        "tab_names": {"Canvas": "Adv GET", "Working": "Adv Edit", "_Sync": "_Adv Sync"},
        "working_protection_id": 106,
    },
}


def fixture_records(cid, uid, aid, score):
    return {
        "course": {"id": cid, "name": "Fictional class"},
        "sections": [{"id": 7, "name": "A1"}],
        "enrollments": [
            {
                "user_id": uid,
                "type": "StudentEnrollment",
                "enrollment_state": "active",
                "course_section_id": 7,
                "user": {"id": uid, "name": "Fictional Student"},
            }
        ],
        "assignments": [
            {
                "id": aid,
                "course_id": cid,
                "name": "Fictional activity",
                "published": True,
                "grading_type": "points",
                "points_possible": 20,
                "position": 1,
            }
        ],
        "submissions": [
            {
                "user_id": uid,
                "assignment_id": aid,
                "score": score,
                "grade": str(score),
                "assignment_visible": True,
                "workflow_state": "graded",
                "attempt": 1,
                "late": False,
                "missing": False,
                "excused": False,
            }
        ],
    }


def fixture_snapshot(records):
    return normalize_snapshot("https://school.example", **records)


def literal(raw, sid, row, col):
    sheet = next(s for s in raw["sheets"] if s["properties"]["sheetId"] == sid)
    value = sheet["data"][0]["rowData"][row - 1]["values"][col - 1].get(
        "userEnteredValue", {}
    )
    return next(iter(value.values()), None)


def set_literal(raw, sid, row, col, value):
    sheet = next(s for s in raw["sheets"] if s["properties"]["sheetId"] == sid)
    sheet["data"][0]["rowData"][row - 1]["values"][col - 1]["userEnteredValue"] = (
        {"numberValue": value}
        if isinstance(value, (int, float))
        else {"stringValue": value}
    )


class FictionalCanvas:
    def __init__(self):
        self.records = {
            "12": fixture_records(12, 101, 21, 18),
            "13": fixture_records(13, 201, 31, 16),
        }
        self.requests = []
        self.fail_course = None

    def handle(self, request):
        self.requests.append(request)
        assert request.method == "GET", "Canvas mutations are forbidden"
        assert request.url.host == "school.example"
        parts = request.url.path.split("/")
        assert parts[:4] == ["", "api", "v1", "courses"]
        cid, suffix = parts[4], "/".join(parts[5:])
        records = self.records[cid]
        if cid == self.fail_course:
            return httpx.Response(503, text="fictional unavailable source")
        if not suffix:
            value = records["course"]
        elif suffix == "permissions":
            value = {"manage_grades": True}
        elif suffix in {"sections", "enrollments", "assignments"}:
            value = records[suffix]
        elif suffix == f"assignments/{records['assignments'][0]['id']}/submissions":
            assert request.url.params.get("include[]") == "visibility"
            value = records["submissions"]
        else:
            raise AssertionError("Unexpected fictional Canvas endpoint")
        return httpx.Response(200, json=copy.deepcopy(value))


class FictionalGoogle:
    def __init__(self, raw):
        self.raw = copy.deepcopy(raw)
        self.raw["developerMetadata"] = []
        self.grade_batches = []
        self.reads = 0
        self.lose_after_commit = False
        self.fail_before_commit = False
        self.corrupt_note_after_commit = False
        self.intervening_edit = False

    def enqueue(self):
        request = {
            "v": 1,
            "id": str(uuid.uuid4()),
            "action": "REFRESH_BOTH",
            "created_at": stamp(),
            "workbook_id": BOOK,
        }
        metadata = metadata_create("request", request)["createDeveloperMetadata"][
            "developerMetadata"
        ]
        metadata["metadataId"] = 99
        assert "request" not in queue_metadata(self.raw)
        self.raw["developerMetadata"].append(metadata)
        return request

    async def metadata(self):
        return copy.deepcopy(self.raw)

    async def read_workbook(self):
        self.reads += 1
        if self.intervening_edit and self.reads == 2:
            set_literal(self.raw, 2, 6, 3, 19)
        return copy.deepcopy(self.raw)

    async def send_preflighted_batch(self, requests):
        return await self.batch(requests)

    async def batch(self, requests):
        grade = any("updateCells" in r for r in requests)
        if grade:
            self.grade_batches.append(copy.deepcopy(requests))
            if self.fail_before_commit:
                raise TimeoutError("Fictional timeout before commit")
        # Stage every mutation first. Invalid metadata means no part commits.
        staged = copy.deepcopy(self.raw)
        per_course = {course: [] for course in BINDINGS}
        for request in requests:
            if "createDeveloperMetadata" in request:
                item = copy.deepcopy(
                    request["createDeveloperMetadata"]["developerMetadata"]
                )
                if any(
                    m["metadataId"] == item["metadataId"]
                    for m in staged["developerMetadata"]
                ):
                    raise GradebookError("Duplicate fictional metadata ID")
                staged["developerMetadata"].append(item)
            elif "updateDeveloperMetadata" in request:
                update = request["updateDeveloperMetadata"]
                mid = update["dataFilters"][0]["developerMetadataLookup"]["metadataId"]
                found = [
                    m for m in staged["developerMetadata"] if m["metadataId"] == mid
                ]
                assert len(found) == 1
                found[0].update(copy.deepcopy(update["developerMetadata"]))
            elif "deleteDeveloperMetadata" in request:
                mid = request["deleteDeveloperMetadata"]["dataFilter"][
                    "developerMetadataLookup"
                ]["metadataId"]
                staged["developerMetadata"] = [
                    m for m in staged["developerMetadata"] if m["metadataId"] != mid
                ]
            else:
                kind, data = next(iter(request.items()))
                if kind == "updateProtectedRange":
                    owner = next(
                        c
                        for c, b in BINDINGS.items()
                        if b["working_protection_id"]
                        == data["protectedRange"]["protectedRangeId"]
                    )
                else:
                    sid = data.get("sheetId")
                    for field in ("start", "range", "properties"):
                        if (
                            isinstance(data.get(field), dict)
                            and "sheetId" in data[field]
                        ):
                            sid = data[field]["sheetId"]
                    owner = next(
                        c for c, b in BINDINGS.items() if sid in b["sheets"].values()
                    )
                per_course[owner].append(request)
        if grade:
            state = _state(staged)
            for course, updates in per_course.items():
                _apply_requests(state, updates, BINDINGS[course])
            rendered = raw_from_state(state)
            rendered["developerMetadata"] = staged["developerMetadata"]
            staged = rendered
            if self.corrupt_note_after_commit:
                staged["sheets"][0]["data"][0]["rowData"][5]["values"][2][
                    "note"
                ] = "Corrupted fictional note"
        self.raw = staged
        if grade and self.lose_after_commit:
            raise TimeoutError("Fictional response lost after atomic commit")
        return {}


@pytest.fixture
async def scenario(tmp_path):
    old = {
        "core": fixture_snapshot(fixture_records(12, 101, 21, 10)),
        "advanced": fixture_snapshot(fixture_records(13, 201, 31, 12)),
    }
    raw = initial_raw(old["core"], BINDINGS["core"])
    raw["sheets"].extend(
        initial_raw(old["advanced"], BINDINGS["advanced"])["sheets"][:3]
    )
    # Preserve a pre-existing teacher proposal; this is never a Canvas write.
    set_literal(raw, 2, 6, 3, 20)
    for sheet in raw["sheets"]:
        if sheet["properties"]["sheetId"] in {1, 2, 5, 6}:
            sheet["properties"]["gridProperties"]["columnCount"] = 40
    google = FictionalGoogle(raw)
    request = google.enqueue()
    store = Store(tmp_path)
    for baseline in old.values():
        store.save("snapshot", baseline)
    source = FictionalCanvas()
    client = GradebookClient(
        "https://school.example", "fictional-token", httpx.MockTransport(source.handle)
    )
    worker = RefreshWorker(google, client, store, BINDINGS, INSTANCE)
    try:
        yield worker, google, source, request, old
    finally:
        await client.close()


async def test_real_canonical_two_course_batch_preserves_original_pending_baseline(
    scenario,
):
    worker, google, source, request, old = scenario
    reference = copy.deepcopy(
        next(s for s in google.raw["sheets"] if s["properties"]["sheetId"] == 4)
    )
    result = await worker.step()
    assert result["state"] == "VERIFIED"
    assert result["canvas_writes"] == 0
    assert result["summary"] == {
        "core": {"students": 1, "assignments": 1, "pending_edits": 1},
        "advanced": {"students": 1, "assignments": 1, "pending_edits": 0},
    }
    assert len(google.grade_batches) == 1
    written = {
        r["updateCells"]["start"]["sheetId"]
        for r in google.grade_batches[0]
        if "updateCells" in r
    }
    assert written == {1, 2, 3, 5, 6, 7}
    assert literal(google.raw, 1, 6, 3) == 18  # Core GET observes fresh Canvas.
    assert literal(google.raw, 2, 6, 3) == 20  # Core Edit retains teacher proposal.
    assert literal(google.raw, 5, 6, 3) == 16
    assert literal(google.raw, 6, 6, 3) == 16  # Untouched Advanced accepts Canvas.
    baseline_id, current_id = literal(google.raw, 3, 2, 2), literal(google.raw, 3, 9, 2)
    baseline = worker.store.load("snapshot", baseline_id)
    current = worker.store.load("snapshot", current_id)
    assert baseline["cells"]["101:21"]["value"] == 10
    assert current["cells"]["101:21"]["value"] == 18
    assert baseline_id != current_id
    assert baseline["working_baseline"]["retained_cells"] == ["101:21"]
    assert (
        next(s for s in google.raw["sheets"] if s["properties"]["sheetId"] == 4)
        == reference
    )
    assert all(
        s["properties"]["gridProperties"]["columnCount"] == 40
        for s in google.raw["sheets"]
        if s["properties"]["sheetId"] in {1, 2, 5, 6}
    )
    assert all(r.method == "GET" for r in source.requests)
    assert {
        r.url.path for r in source.requests if r.url.path.endswith("/submissions")
    } == {
        "/api/v1/courses/12/assignments/21/submissions",
        "/api/v1/courses/13/assignments/31/submissions",
    }
    op = worker.journal.get(request["id"])
    assert op["status"] == "VERIFIED"
    receipt = worker.store.load("receipt", op["payload"]["receipt_id"])
    assert receipt["canvas_writes"] == 0
    assert (await worker.step())["state"] == "IDLE"
    assert len(google.grade_batches) == 1


async def test_second_refresh_retains_first_original_baseline_and_conflict(scenario):
    worker, google, source, _, _ = scenario
    assert (await worker.step())["state"] == "VERIFIED"
    source.records["12"]["submissions"][0].update(score=19, grade="19")
    request = google.enqueue()
    assert (await worker.step())["state"] == "VERIFIED"
    assert len(google.grade_batches) == 2  # One per distinct teacher request.
    assert literal(google.raw, 1, 6, 3) == 19
    assert literal(google.raw, 2, 6, 3) == 20
    baseline = worker.store.load("snapshot", literal(google.raw, 3, 2, 2))
    assert baseline["cells"]["101:21"]["value"] == 10
    op = worker.journal.get(request["id"])
    manifest = worker.store.load("refresh", op["payload"]["manifest_id"])
    review = worker.store.load("review", manifest["plans"]["core"]["review_id"])
    assert "canvas_changed_since_baseline" in review["changes"][0]["reasons"]
    assert review["changes"][0]["baseline"] == 10


async def test_real_worker_lost_response_after_commit_reconciles_without_repeat(
    scenario,
):
    worker, google, _, request, _ = scenario
    google.lose_after_commit = True
    assert (await worker.step())["state"] == "VERIFIED"
    assert len(google.grade_batches) == 1
    assert literal(google.raw, 1, 6, 3) == 18
    assert literal(google.raw, 2, 6, 3) == 20
    restarted = RefreshWorker(google, worker.canvas, worker.store, BINDINGS, INSTANCE)
    assert (await restarted.step())["state"] == "IDLE"
    assert restarted.journal.get(request["id"])["status"] == "VERIFIED"
    assert len(google.grade_batches) == 1


async def test_real_worker_uncertain_before_commit_never_retransmits(scenario):
    worker, google, source, request, _ = scenario
    google.fail_before_commit = True
    assert (await worker.step())["state"] == "UNCERTAIN"
    canvas_calls = len(source.requests)
    assert literal(google.raw, 1, 6, 3) == 10
    assert literal(google.raw, 2, 6, 3) == 20
    restarted = RefreshWorker(google, worker.canvas, worker.store, BINDINGS, INSTANCE)
    assert (await restarted.step())["state"] == "UNCERTAIN"
    assert len(google.grade_batches) == 1
    assert len(source.requests) == canvas_calls  # Recovery reads Google only.
    assert restarted.journal.get(request["id"])["status"] == "UNCERTAIN"
    assert set(queue_metadata(google.raw)) >= {"request", "claim", "status"}


async def test_real_native_note_corruption_holds_even_when_all_grades_match(scenario):
    worker, google, source, request, _ = scenario
    google.corrupt_note_after_commit = True
    assert (await worker.step())["state"] == "UNCERTAIN"
    assert literal(google.raw, 1, 6, 3) == 18
    assert literal(google.raw, 2, 6, 3) == 20
    assert literal(google.raw, 5, 6, 3) == 16
    assert worker.journal.get(request["id"])["status"] == "UNCERTAIN"
    assert len(google.grade_batches) == 1
    assert (await worker.step())["state"] == "UNCERTAIN"
    assert len(google.grade_batches) == 1


@pytest.mark.parametrize("failure", ["advanced_get", "intervening_edit"])
async def test_real_worker_preparation_failure_writes_neither_course(scenario, failure):
    worker, google, source, request, _ = scenario
    if failure == "advanced_get":
        source.fail_course = "13"
    else:
        google.intervening_edit = True
    with pytest.raises(GradebookError):
        await worker.step()
    assert google.grade_batches == []
    assert literal(google.raw, 1, 6, 3) == 10
    assert literal(google.raw, 5, 6, 3) == 12
    assert literal(google.raw, 2, 6, 3) == (19 if failure == "intervening_edit" else 20)
    assert worker.journal.get(request["id"])["status"] == "HELD"
