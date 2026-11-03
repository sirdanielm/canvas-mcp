"""Fictional source/QC and original once-lifecycle regression tests; no live data."""

import asyncio
import copy
import hashlib
import importlib.util
import json
import socket
import time
from pathlib import Path
from typing import Any

import httpx
import pytest
from test_gradebook import snapshot as snapshot
from test_gradebook_native import binding as binding
from test_private_proposed_edit import scenario as scenario

from canvas_mcp.gradebook import unit2_private_proposed_edit as edit
from canvas_mcp.gradebook import unit2_reviewed_whole_source as source
from canvas_mcp.gradebook.client import GradebookClient, GradebookError
from canvas_mcp.gradebook.google import GoogleSheets
from canvas_mcp.gradebook.model import digest
from canvas_mcp.gradebook.unit2_private_proposed_owner import (
    OriginalPrivateWholeHost,
    OriginalPrivateWholeOwner,
)


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def deny(*args, **kwargs):
        raise AssertionError("REAL_NETWORK_FORBIDDEN")

    monkeypatch.setattr(socket.socket, "connect", deny)
    monkeypatch.setattr(socket.socket, "connect_ex", deny)
    monkeypatch.setattr(socket, "create_connection", deny)


@pytest.fixture
def reviewed(scenario: Any) -> dict[str, Any]:
    memory: dict[str, bytes] = {}

    def put(name: str, value: Any, raw: bool = False) -> dict[str, Any]:
        b = value if raw else json.dumps(value, ensure_ascii=False).encode()
        path = "/fictional-reviewed/" + name
        memory[path] = b
        return {"path": path, "bytes": len(b), "sha256": hashlib.sha256(b).hexdigest()}

    native_ref = put("native", {"grade_preview": None, "holds": ["KEEP"]})
    binding_doc = {
        "source_reading_result_policy_refs": {"result": native_ref},
        "fictional": True,
    }
    proposal = {
        "academic_components_complete": True,
        "remaining_academic_null_components": 0,
        "reused_numeric_components": 1,
        "new_numeric_mastery_components": 1,
        "exact_arithmetic": {
            "private_proposed_percent": "100/3",
            "rounding_applied": False,
            "private_proposed_weighted_earned": "1",
            "weighted_possible": "3",
        },
    }
    body = b"  Fictional complete QC body.\r\n"
    body_ref = put("body", body, True)
    qc = {
        "contract": source.QC,
        "verdict": "PASS_PRIVATE_PROPOSAL_ONLY",
        "substantive_findings": [],
        "source_binding": binding_doc,
        "proposed_exact_arithmetic": copy.deepcopy(proposal["exact_arithmetic"]),
        "no_rounding_or_floor_applied": True,
        "component_review": [{}, {}],
        "feedback": {
            "approved_body": body_ref,
            "exact_UTF8_hash_required_for_downstream_readback": True,
        },
    }
    request = {
        "contract": source.REQUEST,
        "proposal_ref": put("proposal", proposal),
        "binding_ref": put("binding", binding_doc),
        "qc_ref": put("qc", qc),
        "feedback_ref": body_ref,
    }
    identity = scenario["expected_identity_binding_sha256"]

    def current(*args: Any) -> source.ReviewedWholeContext:
        assert args[0] == request
        return source.ReviewedWholeContext(
            identity, {"grade_preview": None, "status": "HELD", "holds": ["KEEP"]}
        )

    def check(req: Any) -> dict[str, Any]:
        return source.prepare_reviewed_source(
            req, read_ref=lambda r: memory[r["path"]], current_check=current
        )

    def stage(profile: Any, ref: Any) -> None:
        assert (
            ref == scenario["unit_sheet_readback_ref"]
            and profile["feedback"].encode() == body
        )

    env = {
        **{k: v for k, v in scenario.items() if not k.startswith("_")},
        "source_request": request,
        "source_check": check,
        "staged_source_check": stage,
    }
    return {
        "env": env,
        "memory": memory,
        "request": request,
        "proposal": proposal,
        "binding_doc": binding_doc,
        "qc": qc,
        "put": put,
        "current": current,
        "body": body,
    }


def prepare(reviewed: dict[str, Any]) -> dict[str, Any]:
    return edit.prepare_private_edit(**reviewed["env"])


def test_reviewed_variant_truthful_source_and_literal_body(reviewed):
    plan = prepare(reviewed)
    assert plan["source"]["author_contract"] == source.AUTHOR
    assert plan["source"]["actual_authored_body_version"] == source.BODY
    assert (
        source.BODY
        in plan["requests"][0]["updateCells"]["rows"][0]["values"][0]["note"]
    )
    assert plan["source"]["feedback"].encode() == reviewed["body"]
    assert plan["source"]["native_context"]["grade_preview"] is None
    assert plan["source"]["native_context"]["holds"] == ["KEEP"]
    assert plan["source"]["teacher_accepted"] is False


def test_incomplete_and_wrong_qc_sources_refused(reviewed):
    for field, value in [
        ("academic_components_complete", False),
        ("remaining_academic_null_components", 1),
    ]:
        p = copy.deepcopy(reviewed["proposal"])
        p[field] = value
        req = copy.deepcopy(reviewed["request"])
        req["proposal_ref"] = reviewed["put"]("bad-" + field, p)
        with pytest.raises(GradebookError, match="COMPLETE_SUPPORTED"):
            source.prepare_reviewed_source(
                req,
                read_ref=lambda r: reviewed["memory"][r["path"]],
                current_check=reviewed["current"],
            )


def test_no_qc_body_or_reference_rebinding(reviewed):
    req = copy.deepcopy(reviewed["request"])
    req["feedback_ref"] = reviewed["put"]("wrongbody", b"changed", True)
    with pytest.raises(GradebookError, match="EXACT_APPROVED_FEEDBACK"):
        source.prepare_reviewed_source(
            req,
            read_ref=lambda r: reviewed["memory"][r["path"]],
            current_check=reviewed["current"],
        )

    def reader(ref):
        b = reviewed["memory"][ref["path"]]
        ref["sha256"] = "f" * 64
        ref["path"] = "/changed"
        return b

    result = source.prepare_reviewed_source(
        reviewed["request"], read_ref=reader, current_check=reviewed["current"]
    )
    assert result["original_case_unchanged"] == reviewed["request"]


def test_dictionary_cannot_impersonate_owner_context(reviewed):
    with pytest.raises(GradebookError, match="OWNER_CONTEXT"):
        source.prepare_reviewed_source(
            reviewed["request"],
            read_ref=lambda r: reviewed["memory"][r["path"]],
            current_check=lambda *a: {"identity": "fake"},
        )


def test_rounding_is_explicit_and_keeps_raw_rational(reviewed):
    env = reviewed["env"]
    profile = env["source_check"](env["source_request"])
    proof = {
        "contract": "UNIT2_PRIVATE_FINAL_ROUNDING_V1",
        "mode": "NEAREST_WHOLE_PERCENT",
        "boundary": "COMPLETE_ELIGIBLE_PRIVATE_WHOLE",
        "tie_breaker": "UNSPECIFIED",
        "floor_status": "NONE_APPLICABLE",
        "source_request_sha256": profile["source_request_sha256"],
        "source_profile_sha256": source.source_digest(profile),
        "target": env["target"],
        "authority_ref": env["unit_sheet_readback_ref"],
    }

    def authority(s, target, given):
        assert s == profile and target == env["target"] and given == proof

    plan = edit.prepare_private_edit(
        **env,
        score_representation=edit.FINAL_NEAREST,
        final_rounding_proof=proof,
        rounding_check=authority,
    )
    assert (
        plan["staged_final_percent"] == 33 and plan["original_exact_percent"] == "100/3"
    )
    with pytest.raises(GradebookError):
        edit.prepare_private_edit(
            **env,
            score_representation=edit.FINAL_NEAREST,
            final_rounding_proof=proof,
            rounding_check=lambda *a: True,
        )


def test_author5_plan_bytes_still_match_predecessor(scenario):
    pre = Path(__file__).parent / "private_proposal_predecessor.py"
    spec = importlib.util.spec_from_file_location(
        "canvas_mcp.gradebook.private_proposal_predecessor_fixture", pre
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert digest(
        module.prepare_private_edit(
            **{k: v for k, v in scenario.items() if not k.startswith("_")}
        )
    ) == digest(
        edit.prepare_private_edit(
            **{k: v for k, v in scenario.items() if not k.startswith("_")}
        )
    )


@pytest.fixture
def once(tmp_path, reviewed):
    root = tmp_path / "existing-operations"
    root.mkdir(mode=0o700)
    locks = []
    for name in ["existing-workbook.lock", "existing-stage.lock"]:
        p = tmp_path / name
        p.touch(mode=0o600)
        st = p.stat()
        locks.append((p, st.st_dev, st.st_ino))
    cfg = tmp_path / "original-config.json"
    cfg.write_text(
        json.dumps(
            {"output_root": str(root), "locks": [[str(p), d, i] for p, d, i in locks]}
        )
    , encoding="utf-8")
    cfg.chmod(0o600)
    ref = {"path": str(cfg), "sha256": hashlib.sha256(cfg.read_bytes()).hexdigest()}
    owner = OriginalPrivateWholeOwner(
        root,
        tuple(locks),
        original_history_check=lambda: None,
        original_history_config_ref=ref,
    )
    credential = tmp_path / "fictional-credential.json"
    credential.write_text(
        json.dumps(
            {
                "tokens": {
                    "gradebook": {
                        "type": "authorized_user",
                        "client_id": "fictional",
                        "client_secret": "fictional",
                        "refresh_token": "fictional",
                    }
                }
            }
        )
    , encoding="utf-8")
    credential.chmod(0o600)
    plan = prepare(reviewed)
    state = {"raw": copy.deepcopy(plan["before_raw"]), "sends": 0, "closed": 0}

    def transport(request):
        assert request.method == "POST" and request.url.path.endswith(":batchUpdate")
        assert json.loads(request.content) == {
            "requests": plan["requests"],
            "includeSpreadsheetInResponse": False,
        }
        state["sends"] += 1
        state["raw"] = copy.deepcopy(plan["after_raw"])
        return httpx.Response(
            200,
            json={
                "spreadsheetId": reviewed["env"]["binding"]["spreadsheet_id"],
                "replies": [{} for _ in plan["requests"]],
            },
        )

    google = GoogleSheets(
        reviewed["env"]["binding"]["spreadsheet_id"],
        credential,
        transport=httpx.MockTransport(transport),
    )
    google._authorized = True
    google._access_token = google._validated_token = "FICTIONAL"
    google._expires_at = time.monotonic() + 1000
    canvas = GradebookClient(
        "https://fictional.invalid",
        "FICTIONAL",
        transport=httpx.MockTransport(lambda r: httpx.Response(500)),
    )

    async def read(g, c):
        assert g is google and c is canvas
        return {
            "raw": copy.deepcopy(state["raw"]),
            "canvas_observation": reviewed["env"]["canvas_observation"],
        }

    host = OriginalPrivateWholeHost(
        google,
        canvas,
        read_context=read,
        owner_check=lambda: None,
        source_check=reviewed["env"]["source_check"],
        staged_source_check=reviewed["env"]["staged_source_check"],
        target_check=reviewed["env"]["target_check"],
        rounding_check=None,
    )
    return owner, host, plan, state


def test_original_once_exact_pair_and_no_second_send(once):
    owner, host, plan, state = once
    result = asyncio.run(
        owner.execute(
            plan, host, expected_plan_sha256=digest(plan), review_check=lambda p: None
        )
    )
    assert result["status"] == "PLANNED_OUTPUT_OBSERVED" and state["sends"] == 1
    operation = owner.root / result["operation_id"]
    assert json.loads((operation / "closure.json").read_text(encoding="utf-8"))["status"] == "CLOSED"
    assert (
        json.loads((operation / "readback.json").read_text(encoding="utf-8"))["raw"]
        == plan["after_raw"]
    )
    again = asyncio.run(
        owner.execute(
            plan, host, expected_plan_sha256=digest(plan), review_check=lambda p: None
        )
    )
    assert again["status"] == "PLANNED_OUTPUT_OBSERVED" and state["sends"] == 1


def test_original_unknown_history_blocks_without_send(once):
    owner, host, plan, state = once
    old = owner.root / "original-uncertain"
    old.mkdir(mode=0o700)
    p = old / "intent.json"
    p.write_text("{}", encoding="utf-8")
    p.chmod(0o600)
    with pytest.raises(GradebookError, match="UNSETTLED"):
        asyncio.run(
            owner.execute(
                plan,
                host,
                expected_plan_sha256=digest(plan),
                review_check=lambda p: None,
            )
        )
    assert state["sends"] == 0


def test_changed_teacher_preimage_refuses_before_intent(once):
    owner, host, plan, state = once
    state["raw"]["sheets"][0]["properties"]["title"] += " changed"
    result = asyncio.run(
        owner.execute(
            plan, host, expected_plan_sha256=digest(plan), review_check=lambda p: None
        )
    )
    assert result["status"] == "HELD_BEFORE_SEND" and state["sends"] == 0
    assert not (owner.root / result["operation_id"] / "intent.json").exists()


def test_source_math_mismatch_even_if_qc_copies_it_is_held(reviewed):
    proposal = copy.deepcopy(reviewed["proposal"])
    proposal["exact_arithmetic"]["private_proposed_weighted_earned"] = "2"
    qc = copy.deepcopy(reviewed["qc"])
    qc["proposed_exact_arithmetic"] = proposal["exact_arithmetic"]
    request = copy.deepcopy(reviewed["request"])
    request["proposal_ref"] = reviewed["put"]("bad-math", proposal)
    request["qc_ref"] = reviewed["put"]("bad-math-qc", qc)
    with pytest.raises(GradebookError, match="EXACT_ARITHMETIC"):
        source.prepare_reviewed_source(
            request,
            read_ref=lambda r: reviewed["memory"][r["path"]],
            current_check=reviewed["current"],
        )


def test_duplicate_source_json_keys_held(reviewed):
    req = copy.deepcopy(reviewed["request"])
    req["proposal_ref"] = reviewed["put"](
        "duplicate",
        b'{"academic_components_complete":false,"academic_components_complete":true}',
        True,
    )
    with pytest.raises(GradebookError, match="DUPLICATE_JSON_KEY"):
        source.prepare_reviewed_source(
            req,
            read_ref=lambda r: reviewed["memory"][r["path"]],
            current_check=reviewed["current"],
        )


def test_async_owner_context_cannot_imply_approval(reviewed):
    async def wrong(*args):
        return reviewed["current"](*args)

    with pytest.raises(GradebookError, match="SYNCHRONOUS_CURRENT_OWNER"):
        source.prepare_reviewed_source(
            reviewed["request"],
            read_ref=lambda r: reviewed["memory"][r["path"]],
            current_check=wrong,
        )


def test_send_failure_with_unchanged_readback_never_retries(once):
    owner, host, plan, state = once

    async def failed(requests):
        state["sends"] += 1
        raise httpx.ReadTimeout("fictional uncertain response")

    host.google.send_preflighted_batch = failed
    result = asyncio.run(
        owner.execute(
            plan, host, expected_plan_sha256=digest(plan), review_check=lambda p: None
        )
    )
    assert (
        result["status"] == "BEFORE_STILL_PRESENT" and result["retry_writes"] is False
    )
    assert result["send_attempts"] == state["sends"] == 1
    second = asyncio.run(
        owner.execute(
            plan, host, expected_plan_sha256=digest(plan), review_check=lambda p: None
        )
    )
    assert second["status"] == "BEFORE_STILL_PRESENT" and state["sends"] == 1


def test_exact_number_but_wrong_note_readback_is_diverged(once):
    owner, host, plan, state = once

    async def changed(requests):
        state["sends"] += 1
        state["raw"] = copy.deepcopy(plan["after_raw"])
        edit._cell(state["raw"], 2, 5, 2)["note"] += " changed"

    host.google.send_preflighted_batch = changed
    result = asyncio.run(
        owner.execute(
            plan, host, expected_plan_sha256=digest(plan), review_check=lambda p: None
        )
    )
    assert result["status"] == "DIVERGED" and result["retry_writes"] is False
    assert state["sends"] == 1


def test_owner_revocation_before_send_is_a_hold(once):
    owner, host, plan, state = once
    count = 0

    def owner_check():
        nonlocal count
        count += 1
        if count >= 4:
            raise GradebookError("FICTIONAL_OWNER_CHANGED")

    host.owner_check = owner_check
    result = asyncio.run(
        owner.execute(
            plan, host, expected_plan_sha256=digest(plan), review_check=lambda p: None
        )
    )
    assert result["status"] == "HELD_BEFORE_SEND" and state["sends"] == 0


def test_rejected_review_closes_clients_and_creates_no_intent(once):
    owner, host, plan, state = once

    def reject(plan):
        raise GradebookError("FICTIONAL_REVIEW_HOLD")

    with pytest.raises(GradebookError, match="REVIEW_HOLD"):
        asyncio.run(
            owner.execute(
                plan, host, expected_plan_sha256=digest(plan), review_check=reject
            )
        )
    assert host.google.http.is_closed and host.canvas.http.is_closed
    assert not list(owner.root.iterdir()) and state["sends"] == 0


def test_readback_failure_preserves_uncertainty_and_never_resends(once):
    owner, host, plan, state = once
    original = host.reader
    count = 0

    async def read(g, c):
        nonlocal count
        count += 1
        if count >= 3:
            raise httpx.ReadTimeout("fictional readback failure")
        return await original(g, c)

    host.reader = read
    result = asyncio.run(
        owner.execute(
            plan, host, expected_plan_sha256=digest(plan), review_check=lambda p: None
        )
    )
    assert result["status"] == "READBACK_UNCERTAIN" and result["retry_writes"] is False
    assert result["send_attempts"] == state["sends"] == 1
    with pytest.raises(httpx.ReadTimeout):
        asyncio.run(
            owner.execute(
                plan,
                host,
                expected_plan_sha256=digest(plan),
                review_check=lambda p: None,
            )
        )
    assert state["sends"] == 1


def test_hash_bound_source_bytes_changed_is_held(reviewed):
    request = reviewed["request"]
    reviewed["memory"][request["qc_ref"]["path"]] += b" "
    with pytest.raises(GradebookError, match="BYTES_CHANGED"):
        source.prepare_reviewed_source(
            request,
            read_ref=lambda r: reviewed["memory"][r["path"]],
            current_check=reviewed["current"],
        )


def test_qc_coverage_missing_component_is_held(reviewed):
    qc = copy.deepcopy(reviewed["qc"])
    qc["component_review"].pop()
    request = copy.deepcopy(reviewed["request"])
    request["qc_ref"] = reviewed["put"]("missing-coverage", qc)
    with pytest.raises(GradebookError, match="QC_COVERAGE"):
        source.prepare_reviewed_source(
            request,
            read_ref=lambda r: reviewed["memory"][r["path"]],
            current_check=reviewed["current"],
        )


def test_protection_change_after_send_is_diverged(once):
    owner, host, plan, state = once

    async def change(requests):
        state["sends"] += 1
        state["raw"] = copy.deepcopy(plan["after_raw"])
        state["raw"]["sheets"][0]["protectedRanges"] = [
            {"description": "fictional changed"}
        ]

    host.google.send_preflighted_batch = change
    result = asyncio.run(
        owner.execute(
            plan, host, expected_plan_sha256=digest(plan), review_check=lambda p: None
        )
    )
    assert result["status"] == "DIVERGED" and state["sends"] == 1
    assert result["retry_writes"] is False


def test_original_persisted_legacy_native_keys_remain_compatible(once):
    from canvas_mcp.gradebook import native

    owner, host, plan, state = once
    previous = owner.root / "original-successful-note"
    previous.mkdir(mode=0o700)
    # Literal JSON persistence is part of the existing once-history contract.
    raw = copy.deepcopy(plan["before_raw"])
    native_state = json.loads(json.dumps(native._state(raw)))
    old_plan = {"after_state": native_state}
    old_sha = digest(old_plan)
    values = {
        "intent.json": {"plan": old_plan, "plan_sha256": old_sha},
        "terminal.json": {
            "status": "PLANNED_OUTPUT_OBSERVED",
            "send_attempts": 1,
            "plan_sha256": old_sha,
        },
        "readback.json": {
            "status": "PLANNED_OUTPUT_OBSERVED",
            "raw": raw,
            "native_state": native_state,
            "fingerprint": digest(native_state),
        },
        "closure.json": {"status": "CLOSED"},
    }
    for name, value in values.items():
        p = previous / name
        p.write_text(json.dumps(value), encoding="utf-8")
        p.chmod(0o600)
    result = asyncio.run(
        owner.execute(
            plan, host, expected_plan_sha256=digest(plan), review_check=lambda p: None
        )
    )
    assert result["status"] == "PLANNED_OUTPUT_OBSERVED" and state["sends"] == 1


@pytest.fixture
def manifest_history(once):
    owner, host, plan, state = once
    d = owner.root / "original-note-manifest"
    d.mkdir(mode=0o700)
    reference = {"path": "/fictional/manifest", "sha256": "a" * 64}
    intent = {
        "manifest": reference,
        "manifest_sha256": reference["sha256"],
        "operation_id": d.name,
        "config_ref": {"path": "/fictional/config", "sha256": "b" * 64},
        "native_preimage": {"path": "/fictional/before", "sha256": "c" * 64},
        "requests": [{"fictional": "existing-note-only"}],
        "canvas_writes": 0,
        "numeric_writes": 0,
    }
    terminal = {
        "status": "PLANNED_OUTPUT_OBSERVED",
        "send_attempts": 1,
        "manifest": reference,
        "operation_id": d.name,
        "canvas_writes": 0,
        "numeric_writes": 0,
    }
    readback = {"status": "PLANNED_OUTPUT_OBSERVED", "raw": plan["before_raw"]}
    for name, value in [
        ("intent.json", intent),
        ("terminal.json", terminal),
        ("readback.json", readback),
        ("closure.json", {"status": "CLOSED"}),
    ]:
        p = d / name
        p.write_text(json.dumps(value), encoding="utf-8")
        p.chmod(0o600)
    return once, d, intent, terminal, readback


def test_manifest_history_missing_real_checker_cannot_send(manifest_history):
    (owner, host, plan, state), d, i, t, r = manifest_history
    with pytest.raises(GradebookError, match="MANIFEST_HISTORY_VERIFIER_REQUIRED"):
        asyncio.run(
            owner.execute(
                plan,
                host,
                expected_plan_sha256=digest(plan),
                review_check=lambda p: None,
            )
        )
    assert state["sends"] == 0


def test_manifest_history_explicit_checker_receives_exact_copies(manifest_history):
    (owner, host, plan, state), d, i, t, r = manifest_history
    seen = []

    def original(directory, intent, terminal, readback):
        assert directory == d and intent == i and terminal == t and readback == r
        seen.append(True)
        intent["manifest"]["sha256"] = "f" * 64

    owner.manifest_history_check = original
    result = asyncio.run(
        owner.execute(
            plan, host, expected_plan_sha256=digest(plan), review_check=lambda p: None
        )
    )
    assert (
        result["status"] == "PLANNED_OUTPUT_OBSERVED"
        and seen == [True]
        and state["sends"] == 1
    )
    assert json.loads((d / "intent.json").read_bytes()) == i


def test_manifest_history_failed_verification_cannot_send(manifest_history):
    (owner, host, plan, state), d, i, t, r = manifest_history

    def reject(*args):
        raise GradebookError("FICTIONAL_MANIFEST_BODY_CHANGED")

    owner.manifest_history_check = reject
    with pytest.raises(GradebookError, match="BODY_CHANGED"):
        asyncio.run(
            owner.execute(
                plan,
                host,
                expected_plan_sha256=digest(plan),
                review_check=lambda p: None,
            )
        )
    assert state["sends"] == 0


def test_manifest_history_numeric_or_reference_tamper_cannot_use_checker(
    manifest_history,
):
    (owner, host, plan, state), d, i, t, r = manifest_history
    calls = []
    owner.manifest_history_check = lambda *args: calls.append(True)
    i["numeric_writes"] = 1
    (d / "intent.json").write_text(json.dumps(i), encoding="utf-8")
    with pytest.raises(GradebookError, match="MANIFEST_HISTORY_VERIFIER_REQUIRED"):
        asyncio.run(
            owner.execute(
                plan,
                host,
                expected_plan_sha256=digest(plan),
                review_check=lambda p: None,
            )
        )
    assert state["sends"] == 0 and not calls


def test_manifest_reference_mismatch_holds_before_callback(manifest_history):
    (owner, host, plan, state), d, i, t, r = manifest_history
    calls = []
    owner.manifest_history_check = lambda *args: calls.append(True)
    i["manifest_sha256"] = "f" * 64
    (d / "intent.json").write_text(json.dumps(i), encoding="utf-8")
    with pytest.raises(GradebookError, match="MANIFEST_HISTORY_VERIFIER_REQUIRED"):
        asyncio.run(
            owner.execute(
                plan,
                host,
                expected_plan_sha256=digest(plan),
                review_check=lambda p: None,
            )
        )
    assert state["sends"] == 0 and not calls


def test_manifest_uncertain_status_stays_held(manifest_history):
    (owner, host, plan, state), d, i, t, r = manifest_history
    owner.manifest_history_check = lambda *args: None
    t["status"] = "READBACK_UNCERTAIN"
    (d / "terminal.json").write_text(json.dumps(t), encoding="utf-8")
    with pytest.raises(GradebookError, match="HISTORY_UNSETTLED"):
        asyncio.run(
            owner.execute(
                plan,
                host,
                expected_plan_sha256=digest(plan),
                review_check=lambda p: None,
            )
        )
    assert state["sends"] == 0


def test_manifest_unclosed_clients_stay_held(manifest_history):
    (owner, host, plan, state), d, i, t, r = manifest_history
    owner.manifest_history_check = lambda *args: None
    (d / "closure.json").write_text(json.dumps({"status": "CLIENT_CLEANUP_HELD"}), encoding="utf-8")
    with pytest.raises(GradebookError, match="CLIENTS_UNSETTLED"):
        asyncio.run(
            owner.execute(
                plan,
                host,
                expected_plan_sha256=digest(plan),
                review_check=lambda p: None,
            )
        )
    assert state["sends"] == 0


@pytest.fixture
def faithful_manifest(once):
    from original_note_compiler import compile_copy
    from original_note_history import full_raw_matches

    from canvas_mcp.gradebook import native
    from canvas_mcp.gradebook.unit2_private_proposed_owner import (
        verify_original_note_manifest,
    )

    owner, host, plan, state = once
    directory = owner.root / "old-original-manifest"
    directory.mkdir(mode=0o700)

    def put(name, value, raw=False):
        data = value if raw else json.dumps(value).encode()
        path = directory / name
        path.write_bytes(data)
        path.chmod(0o600)
        return {
            "path": str(path),
            "bytes": len(data),
            "sha256": hashlib.sha256(data).hexdigest(),
        }

    before = copy.deepcopy(plan["before_raw"])
    before["developerMetadata"] = [
        {
            "metadataId": 2026092904,
            "metadataKey": "sdm.gradebook.refresh.heartbeat.v1",
            "visibility": "DOCUMENT",
            "location": {"locationType": "SPREADSHEET", "spreadsheet": True},
            "metadataValue": json.dumps(
                {
                    "v": 1,
                    "workbook_id": plan["binding"]["spreadsheet_id"],
                    "state": "READY",
                    "refresh_mode": "GET_ONLY",
                    "updated_at": "2026-10-20T00:00:00Z",
                }
            ),
        }
    ]
    old = copy.deepcopy(edit._cell(before, 2, 5, 2))
    note = old.get("note", "")
    body = "fictional exact historical note"
    body_ref = put("body.txt", body.encode(), True)
    dummy = put("source.json", {"fictional": True})
    old_qc_ref = put("historical-qc.json", {"historical": "fictional QC"})
    manifest = {
        "candidates": [
            {
                "location": {"sheetId": 2, "rowIndex": 5, "columnIndex": 2},
                "target": plan["target"],
                "before_cell": old,
                "before_note": note,
                "body": body,
                "body_sha256": hashlib.sha256(body.encode()).hexdigest(),
                "after_note": note
                + "\n\n[UNIT2 CLEANED FEEDBACK BEGIN]\n"
                + body
                + "\n[UNIT2 CLEANED FEEDBACK END]\n",
                "copy_boundary_kind": "PRESERVE_ALL_OLD_NOTE_APPEND_CURRENT_BODY",
                "preservation": {"prefix": note, "old_body": "", "suffix": ""},
                "identity_binding": {
                    "row_keys": [
                        {
                            "column_index": 0,
                            "userEnteredValue": edit._cell(before, 2, 5, 0)[
                                "userEnteredValue"
                            ],
                        }
                    ],
                    "column_keys": [
                        {
                            "row_index": 4,
                            "userEnteredValue": edit._cell(before, 2, 4, 2)[
                                "userEnteredValue"
                            ],
                        }
                    ],
                },
                "body_ref": body_ref,
                "source_record_ref": dummy,
                "capture_ref": dummy,
                "pins": [old_qc_ref],
            }
        ]
    }
    bindings = {"fictional": plan["binding"]}
    book = plan["binding"]["spreadsheet_id"]
    origin = plan["target"]["origin"]
    old_plan = compile_copy(manifest, before, bindings, workbook_id=book, origin=origin)
    mr = put("manifest.json", manifest)
    br = put("before.json", before)
    config = {
        "contract": "ROOT_EXISTING_TRANSPORT_NOTE_COPY_V1",
        "execution_admitted": True,
        "output_root": str(owner.root),
        "operation_id": directory.name,
        "manifest": mr,
        "native_preimage": br,
    }
    intent = {
        "manifest": mr,
        "manifest_sha256": mr["sha256"],
        "native_preimage": br,
        "config_ref": put("config.json", config),
        "operation_id": directory.name,
        "requests": old_plan["requests"],
        "send_attempts": 0,
        "status": "SENDING",
        "retry_writes": False,
        "candidate_count": 1,
        "prepared_count": 1,
        "already_present_count": 0,
        "canvas_writes": 0,
        "numeric_writes": 0,
    }
    terminal = {
        **{
            k: v
            for k, v in intent.items()
            if k
            in [
                "operation_id",
                "manifest",
                "candidate_count",
                "prepared_count",
                "already_present_count",
                "canvas_writes",
                "numeric_writes",
            ]
        },
        "status": "PLANNED_OUTPUT_OBSERVED",
        "send_attempts": 1,
        "staged_count": 1,
        "retry_writes": False,
    }
    rb = {
        "status": "PLANNED_OUTPUT_OBSERVED",
        "raw": old_plan["after_raw"],
        "native_state": json.loads(json.dumps(native._state(old_plan["after_raw"]))),
    }

    def reader(ref):
        return Path(ref["path"]).read_bytes()

    def verify(d, i, t, r):
        evidence = verify_original_note_manifest(
            d,
            i,
            t,
            r,
            root=owner.root,
            read_ref=reader,
            compile_copy=compile_copy,
            full_raw_matches=full_raw_matches,
            bindings=bindings,
            workbook_id=book,
            origin=origin,
        )

        assert evidence["closed_effect_resolved"] is True
        owner.fixture_closed_history_evidence = evidence
        return None

    for name, value in [
        ("intent.json", intent),
        ("terminal.json", terminal),
        ("readback.json", rb),
        ("closure.json", {"status": "CLOSED"}),
    ]:
        put(name, value)
    return once, directory, intent, terminal, rb, verify


def test_real_original_compiler_and_readback_verifier_composition(faithful_manifest):
    (owner, host, plan, state), d, i, t, r, verify = faithful_manifest
    assert verify(d, i, t, r) is None
    owner.manifest_history_check = verify
    result = asyncio.run(
        owner.execute(
            plan, host, expected_plan_sha256=digest(plan), review_check=lambda p: None
        )
    )
    assert result["status"] == "PLANNED_OUTPUT_OBSERVED" and state["sends"] == 1


def test_original_manifest_requests_cannot_be_rebound(faithful_manifest):
    once, d, i, t, r, verify = faithful_manifest
    i = copy.deepcopy(i)
    i["requests"][0]["updateCells"]["rows"][0]["values"][0]["note"] = "wrong"
    with pytest.raises(GradebookError, match="DURABLE_CLOSED_EFFECT_REQUIRED"):
        verify(d, i, t, r)


def test_original_manifest_wrong_readback_is_not_historical_success(faithful_manifest):
    once, d, i, t, r, verify = faithful_manifest
    r = copy.deepcopy(r)
    edit._cell(r["raw"], 2, 5, 2)["note"] += " wrong"
    with pytest.raises(GradebookError, match="DURABLE_CLOSED_EFFECT_REQUIRED"):
        verify(d, i, t, r)


def test_original_manifest_config_hash_is_required(faithful_manifest):
    once, d, i, t, r, verify = faithful_manifest
    i = copy.deepcopy(i)
    i["config_ref"]["sha256"] = "f" * 64
    (d / "intent.json").write_text(json.dumps(i), encoding="utf-8")
    with pytest.raises(GradebookError, match="REF_CHANGED"):
        verify(d, i, t, r)


def test_closed_effect_survives_missing_old_qc_cache_as_visible_gap(faithful_manifest):
    (owner, host, plan, state), d, i, t, r, verify = faithful_manifest
    (d / "historical-qc.json").unlink()
    assert verify(d, i, t, r) is None
    evidence = owner.fixture_closed_history_evidence
    assert evidence["historical_source_provenance"] == "GAP"
    assert len(evidence["missing_historical_source_refs"]) == 1
    assert evidence["old_source_QC_requalified"] is False
    assert evidence["current_write_or_source_authority_granted"] is False
    owner.manifest_history_check = verify
    result = asyncio.run(
        owner.execute(
            plan, host, expected_plan_sha256=digest(plan), review_check=lambda p: None
        )
    )
    assert result["status"] == "PLANNED_OUTPUT_OBSERVED" and state["sends"] == 1


def test_missing_old_execution_record_still_blocks(faithful_manifest):
    once, d, i, t, r, verify = faithful_manifest
    (d / "intent.json").unlink()
    with pytest.raises(FileNotFoundError):
        verify(d, i, t, r)


def test_missing_old_readback_still_blocks(faithful_manifest):
    once, d, i, t, r, verify = faithful_manifest
    (d / "readback.json").unlink()
    with pytest.raises(FileNotFoundError):
        verify(d, i, t, r)


def test_old_unclosed_effect_cannot_use_provenance_gap_rule(faithful_manifest):
    once, d, i, t, r, verify = faithful_manifest
    (d / "historical-qc.json").unlink()
    (d / "closure.json").write_text(json.dumps({"status": "CLIENT_CLEANUP_HELD"}), encoding="utf-8")
    with pytest.raises(GradebookError, match="DURABLE_CLOSED_EFFECT_REQUIRED"):
        verify(d, i, t, r)


def test_old_possible_effect_timeout_not_resolved_by_source_cache_gap(
    faithful_manifest,
):
    once, d, i, t, r, verify = faithful_manifest
    (d / "historical-qc.json").unlink()
    t["status"] = "READBACK_UNCERTAIN"
    (d / "terminal.json").write_text(json.dumps(t), encoding="utf-8")
    with pytest.raises(GradebookError, match="RESOLVED_EFFECT_REQUIRED"):
        verify(d, i, t, r)
