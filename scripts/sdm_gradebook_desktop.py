"""Explicit desktop gradebook reads and private reviews; no Canvas publisher."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import re
import sqlite3
import subprocess
import sys
import time
import webbrowser
from collections.abc import Callable
from contextlib import closing
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

os.environ["PYTHON_DOTENV_DISABLED"] = "1"
ROOT = Path(__file__).resolve().parents[1]
UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
HEX = re.compile(r"^[a-f0-9]{64}$")
COVERAGE_COUNTS = (
    "edit_students", "edit_assignments", "canvas_students", "canvas_assignments",
    "added_students", "removed_students", "added_assignments", "removed_assignments",
    "mapped_edit_targets", "missing_edit_targets", "edit_targets_removed_from_canvas",
)


class DesktopHold(Exception):
    """A safe stop requiring inspection, never an automatic retry."""


def digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(
        value, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode()).hexdigest()


def load_json(path: Path, maximum: int = 80_000_000) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file() or path.stat().st_size > maximum:
        raise DesktopHold("Required local evidence is missing or unsafe.")
    try:
        value = json.loads(path.read_text())
    except (OSError, ValueError) as exc:
        raise DesktopHold("Required local evidence cannot be read.") from exc
    if not isinstance(value, dict):
        raise DesktopHold("Required local evidence has an unexpected structure.")
    return value


def safe_coverage(value: Any) -> dict[str, Any]:
    """Admit aggregate integer facts only; ignore arbitrary response labels."""
    if (not isinstance(value, dict)
            or any(type(value.get(k)) is not int or value[k] < 0 for k in COVERAGE_COUNTS)
            or type(value.get("matches_canvas_axes")) is not bool):
        raise DesktopHold("The private review coverage summary is incomplete.")
    safe = {k: value[k] for k in COVERAGE_COUNTS}
    shared_students = safe["edit_students"] - safe["removed_students"]
    shared_assignments = safe["edit_assignments"] - safe["removed_assignments"]
    edit_targets = safe["edit_students"] * safe["edit_assignments"]
    canvas_targets = safe["canvas_students"] * safe["canvas_assignments"]
    shared_targets = shared_students * shared_assignments
    differs = any(safe[k] for k in (
        "added_students", "removed_students", "added_assignments", "removed_assignments"
    ))
    if (shared_students < 0 or shared_assignments < 0
            or shared_students != safe["canvas_students"] - safe["added_students"]
            or shared_assignments != safe["canvas_assignments"] - safe["added_assignments"]
            or safe["mapped_edit_targets"] != edit_targets
            or safe["missing_edit_targets"] != canvas_targets - shared_targets
            or safe["edit_targets_removed_from_canvas"] != edit_targets - shared_targets
            or value["matches_canvas_axes"] is not (not differs)):
        raise DesktopHold("The private review coverage facts are inconsistent.")
    return {**safe, "matches_canvas_axes": not differs}


def artifact(state_dir: Path, kind: str, artifact_id: str | None) -> dict[str, Any]:
    if kind not in {"refresh", "receipt"} or not isinstance(artifact_id, str) or not HEX.fullmatch(artifact_id):
        raise DesktopHold("Verified receipt reference is missing.")
    value = load_json(state_dir / f"{kind}-{artifact_id}.json")
    if digest(value) != artifact_id:
        raise DesktopHold("Saved refresh evidence failed its integrity check.")
    return value


def read_operation(state_dir: Path, workbook_id: str, request_id: str) -> dict[str, Any] | None:
    path = state_dir / "refresh-worker/operations.sqlite3"
    if path.is_symlink() or not path.is_file():
        raise DesktopHold("The installed worker journal is unavailable.")
    if not UUID.fullmatch(request_id):
        raise DesktopHold("Refresh request reference is invalid.")
    try:
        with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=5)) as db:
            row = db.execute("SELECT workbook,status,payload FROM operations WHERE id=?", (request_id,)).fetchone()
    except sqlite3.Error as exc:
        raise DesktopHold("The local refresh journal could not be read.") from exc
    if row is None:
        return None
    if row[0] != workbook_id:
        raise DesktopHold("The refresh belongs to a different workbook.")
    payload = json.loads(row[2])
    if not isinstance(payload, dict):
        raise DesktopHold("The saved refresh operation is incomplete.")
    return {"status": row[1], "payload": payload}


def verified_summary(state_dir: Path, bindings: dict[str, Any], request_id: str, operation: dict[str, Any]) -> dict[str, Any]:
    payload = operation.get("payload", {})
    if (not isinstance(payload, dict) or operation.get("status") != "VERIFIED"
            or type(payload.get("refresh_mode_schema")) is not int or payload.get("refresh_mode_schema") != 1
            or payload.get("refresh_mode") != "GET_ONLY" or payload.get("finalized") is not True):
        raise DesktopHold("A complete finalized GET-only refresh is required.")
    receipt_id = payload.get("receipt_id")
    receipt = artifact(state_dir, "receipt", receipt_id)
    manifest = artifact(state_dir, "refresh", payload.get("manifest_id"))
    books = {b["spreadsheet_id"] for b in bindings.values()}
    request = payload.get("request", {})
    if (not isinstance(request, dict) or set(bindings) != {"core", "advanced"} or len(books) != 1
            or request.get("id") != request_id or request.get("action") != "REFRESH_GET_BOTH"
            or request.get("workbook_id") not in books or manifest.get("request") != request
            or manifest.get("refresh_mode") != "GET_ONLY"
            or manifest.get("binding_digest") != digest(bindings)
            or type(receipt.get("worker_schema")) is not int or receipt.get("worker_schema") != 1
            or receipt.get("request_id") != request_id
            or receipt.get("manifest_id") != payload.get("manifest_id")
            or type(receipt.get("canvas_writes")) is not int or receipt["canvas_writes"] != 0):
        raise DesktopHold("The saved refresh receipt does not match this protected request.")
    try:
        verified_at = datetime.fromisoformat(receipt.get("verified_at", ""))
    except (ValueError, TypeError) as exc:
        raise DesktopHold("The saved receipt has no valid verification time.") from exc
    if verified_at.tzinfo is None:
        raise DesktopHold("The saved receipt verification time lacks its timezone.")
    plans, summaries = manifest.get("plans", {}), receipt.get("summary", {})
    if (not isinstance(plans, dict) or not isinstance(summaries, dict)
            or set(plans) != set(bindings) or set(summaries) != set(bindings)):
        raise DesktopHold("The receipt does not cover both courses.")
    safe = {}
    for course in bindings:
        plan, summary = plans[course], summaries[course]
        if (not isinstance(plan, dict) or not isinstance(summary, dict)
                or plan.get("mode") != "GET_ONLY" or plan.get("edit_preserved") is not True
                or not isinstance(plan.get("baseline_id"), str) or not HEX.fullmatch(plan["baseline_id"])
                or plan.get("baseline_id") != plan.get("previous_baseline_id")
                or summary.get("edit_preserved") is not True
                or any(type(summary.get(k)) is not int or summary[k] < 1 for k in ("students", "assignments"))):
            raise DesktopHold("Complete Edit preservation is not established by this receipt.")
        safe[course] = {k: summary[k] for k in ("students", "assignments", "edit_preserved")}
    return {"state": "VERIFIED", "request_id": request_id, "receipt_id": receipt_id,
            "verified_at": receipt.get("verified_at"), "summary": safe, "canvas_writes": 0}


def poll_refresh(state_dir: Path, bindings: dict[str, Any], request_id: str, *,
                 timeout: float = 720, interval: float = 10,
                 read_operation: Callable[..., Any] = read_operation,
                 emit: Callable[[str], Any] = print,
                 sleep: Callable[[float], Any] = time.sleep) -> dict[str, Any]:
    workbook_id = bindings["core"]["spreadsheet_id"]
    deadline, last = time.monotonic() + timeout, None
    while time.monotonic() < deadline:
        operation = read_operation(state_dir, workbook_id, request_id)
        state = operation.get("status") if operation else "QUEUED"
        if state not in {"QUEUED", "CLAIMING", "CLAIMED", "PREPARED", "SENDING", "VERIFYING", "VERIFIED", "HELD", "UNCERTAIN", "RELEASED"}:
            raise DesktopHold("Refresh journal state is unavailable; ask Codex to inspect the saved request.")
        if state != last:
            emit(f"Refresh progress: {state}")
            last = state
        if state in {"HELD", "UNCERTAIN", "RELEASED"}:
            raise DesktopHold(f"Refresh is {state}. Ask Codex to inspect this existing request; never retry it.")
        if state == "VERIFIED" and operation["payload"].get("finalized") is True:
            return verified_summary(state_dir, bindings, request_id, operation)
        sleep(interval)
    raise DesktopHold("Refresh is still pending. The request remains saved; ask Codex to check it before editing or retrying.")


def request_refresh(repo: Path) -> dict[str, Any]:
    command = [str(repo / ".venv/bin/python"), str(repo / "scripts/sdm_gradebook_worker.py"), "--get-only", "request"]
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=180, check=False)
    except subprocess.TimeoutExpired as exc:
        raise DesktopHold("Request confirmation is uncertain. Inspect the existing queue; never automatically request again.") from exc
    try:
        value = json.loads(result.stdout)
    except ValueError as exc:
        raise DesktopHold("Request status is unavailable. Inspect the existing queue before trying again.") from exc
    if (result.returncode != 0 or value.get("state") not in {"QUEUED", "ALREADY_QUEUED"}
            or not UUID.fullmatch(value.get("request_id", ""))):
        raise DesktopHold("The request was held. Ask Codex to inspect worker readiness and the existing queue.")
    return {"state": value["state"], "request_id": value["request_id"]}


async def private_reviews(repo: Path) -> list[dict[str, Any]]:
    """Read native Edit fields and fresh Canvas; create local reviews only."""
    sys.path.insert(0, str(repo / "src"))
    sys.path.insert(0, str(repo / "scripts"))
    import sdm_gradebook_worker as runtime

    from canvas_mcp.gradebook.native_edit_review import prepare_review
    from canvas_mcp.gradebook.store import Store

    config = runtime.load_config(runtime.DEFAULT_CONFIG)
    bindings = runtime.bindings()
    store = Store(Path(config["state_dir"]))
    google = runtime.google_client(config, bindings)
    canvas = None
    try:
        raw = await google.read_workbook()
        canvas = runtime.canvas_client()
        results = []
        for course in ("core", "advanced"):
            review = await prepare_review(canvas, store, course, bindings[course], raw)
            if (review.get("canvas_writes") != 0 or type(review.get("changes")) is not int
                    or review["changes"] < 0 or not isinstance(review.get("counts"), dict)
                    or any(k not in {"ready_for_review", "review_required"} or type(v) is not int or v < 0
                           for k, v in review["counts"].items())):
                raise DesktopHold("The private review response was incomplete; no publishing is allowed.")
            path = Path(review["review_file"])
            if path.is_symlink() or not path.is_file() or not path.resolve().is_relative_to(store.root):
                raise DesktopHold("The private review file is unavailable.")
            results.append({"course": course, "changes": review["changes"],
                            "counts": review["counts"], "review_file": str(path),
                            "coverage": safe_coverage(review.get("coverage"))})
        return results
    except DesktopHold:
        raise
    except Exception as exc:
        raise DesktopHold("Private review was held by its source, identity or grade checks. Ask Codex to inspect it; no grades or comments were sent.") from exc
    finally:
        await google.close()
        if canvas is not None:
            await canvas.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=["fresh-get", "review"])
    parser.add_argument("--repo", type=Path, default=ROOT)
    parser.add_argument("--no-open", action="store_true")
    args = parser.parse_args(argv)
    repo = args.repo.expanduser().resolve()
    try:
        bindings = load_json(repo / "config/sdm-gradebook-workbooks.json", 100_000)
        config = load_json(Path.home() / ".config/canvas-authoring/gradebook-worker.json", 100_000)
        state_dir = Path(config["state_dir"])
        if args.mode == "fresh-get":
            print("Fresh Canvas GET: Core GET and Adv GET. All Edit grades, formulas and feedback remain preserved.")
            print("Save and pause worksheet editing until VERIFIED. This does not send grades or comments to Canvas.")
            if input("Press Return to request the fresh read, or type cancel: ").strip():
                print("Canceled; no request was made.")
                return 0
            request = request_refresh(repo)
            result = poll_refresh(state_dir, bindings, request["request_id"])
            print("VERIFIED: both GET tabs are fresh; all Edit fields and original baselines were preserved.")
            verified_at = datetime.fromisoformat(result["verified_at"])
            print("Verified at: " + verified_at.astimezone(ZoneInfo("America/New_York")).strftime("%Y-%m-%d %H:%M:%S %Z (NYC)"))
            for course, summary in result["summary"].items():
                print(f"{course.title()}: {summary['students']} students, {summary['assignments']} assignments")
            print(f"Private receipt: {state_dir / ('receipt-' + result['receipt_id'] + '.json')}")
            if not args.no_open:
                webbrowser.open("https://docs.google.com/spreadsheets/d/" + bindings["core"]["spreadsheet_id"] + "/edit")
        else:
            print("Private EDIT review. It reads current grades and prepares a report; it never publishes.")
            print("Score-cell feedback notes remain local staging. Canvas comments require separate exact approval.")
            if input("Press Return to prepare a private review, or type cancel: ").strip():
                print("Canceled; no reads or changes were made.")
                return 0
            results = asyncio.run(private_reviews(repo))
            print("PRIVATE REVIEWS READY — review each proposed score and hold before any separate publication.")
            for result in results:
                counts = result["counts"]
                print(f"{result['course'].title()}: {result['changes']} changes; "
                      f"{counts.get('ready_for_review', 0)} ready for teacher review, "
                      f"{counts.get('review_required', 0)} require additional review")
                coverage = safe_coverage(result.get("coverage"))
                print(f"Coverage: EDIT {coverage['edit_students']} students / {coverage['edit_assignments']} assignments; "
                      f"fresh Canvas {coverage['canvas_students']} students / {coverage['canvas_assignments']} assignments.")
                if not coverage["matches_canvas_axes"]:
                    print(f"Coverage warning: {coverage['added_students']} added and {coverage['removed_students']} removed students; "
                          f"{coverage['added_assignments']} added and {coverage['removed_assignments']} removed assignments; "
                          f"{coverage['missing_edit_targets']} fresh Canvas score slots are outside EDIT.")
                    print("Fresh GET preserves EDIT axes. Resolve removed targets and use a separately reviewed append plan for new coverage. "
                          "This warning does not change grade readiness or authorize publication.")
                print(f"Private review: {result['review_file']}")
                if not args.no_open:
                    webbrowser.open(Path(result["review_file"]).as_uri())
            print("This tool has no publish action. Give Codex the exact approved review and scope for a separately confirmed Canvas operation.")
        return 0
    except (DesktopHold, OSError, KeyError, ValueError) as exc:
        print(f"STOP: {exc if isinstance(exc, DesktopHold) else 'Local gradebook setup is unavailable; ask Codex to inspect it.'}")
        return 2
    except KeyboardInterrupt:
        print("Stopped watching. Any queued request remains saved; check it before retrying.")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
