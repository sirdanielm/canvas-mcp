"""Fictional file-backed intake + actual original once owner/controlled HTTPX."""

import asyncio
import copy
import hashlib
import json
import socket
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest
from test_gradebook import snapshot as snapshot
from test_gradebook_native import binding as binding
from test_private_proposed_edit import scenario as scenario
from test_reviewed_whole_private_bridge import faithful_manifest as faithful_manifest
from test_reviewed_whole_private_bridge import once as once
from test_reviewed_whole_private_bridge import reviewed as reviewed

from canvas_mcp.gradebook import native
from canvas_mcp.gradebook import unit2_private_proposed_edit as edit
from canvas_mcp.gradebook import unit2_reviewed_whole_source as source
from canvas_mcp.gradebook import unit2_saved_edit_batch as batch
from canvas_mcp.gradebook.client import GradebookClient, GradebookError
from canvas_mcp.gradebook.google import GoogleSheets
from canvas_mcp.gradebook.model import digest
from canvas_mcp.gradebook.unit2_note_draft import EditOnlyAuthorization
from canvas_mcp.gradebook.unit2_private_proposed_owner import (
    OriginalPrivateWholeHost,
    OriginalPrivateWholeOwner,
)

NOW = datetime(2026, 10, 27, 9, 0, tzinfo=UTC)


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def deny(*args, **kwargs):
        raise AssertionError("REAL_NETWORK_FORBIDDEN")

    monkeypatch.setattr(socket.socket, "connect", deny)
    monkeypatch.setattr(socket.socket, "connect_ex", deny)
    monkeypatch.setattr(socket, "create_connection", deny)


@pytest.fixture
def world(tmp_path, scenario):
    class World:
        def __init__(self):
            self.root = tmp_path / "original-operations"
            self.root.mkdir(mode=0o700)
            self.out = tmp_path / "reports"
            self.out.mkdir(mode=0o700)
            self.clients = []
            self.states = {}
            self.created = []
            self.scope_calls = []
            self.revoked = False
            locks = []
            for name in ["original-workbook.lock", "original-stage.lock"]:
                p = tmp_path / name
                p.touch(mode=0o600)
                s = p.stat()
                locks.append((p, s.st_dev, s.st_ino))
            config = self.put(
                "original-config",
                {
                    "output_root": str(self.root),
                    "locks": [[str(p), d, i] for p, d, i in locks],
                },
            )
            self.owner = OriginalPrivateWholeOwner(
                self.root,
                tuple(locks),
                original_history_check=self.predecessors,
                original_history_config_ref=config,
            )
            self.manifest = {
                "contract": batch.CONTRACT,
                "batch_id": "fictional-batch",
                "job_slot": {
                    "task_id": "fictional-current-task",
                    "owner": "original-owner",
                    "input_sha256": "a" * 64,
                },
                "created_at": NOW.isoformat(),
                "cases": [],
            }

        def predecessors(self):
            # The bounded fictional predecessor namespace is genuinely empty. Concrete
            # legacy record shapes are exercised below through the original owner.
            assert self.root.is_dir()

        def put(self, name, value):
            p = tmp_path / name
            b = (
                value
                if type(value) is bytes
                else (json.dumps(value, ensure_ascii=False) + "\n").encode()
            )
            p.write_bytes(b)
            p.chmod(0o600)
            return {
                "path": str(p),
                "bytes": len(b),
                "sha256": hashlib.sha256(b).hexdigest(),
            }

        def load(self, ref):
            return json.loads(batch.read_reference(ref))

        def add(self, name, *, given=None):
            target = copy.deepcopy(scenario["target"])
            target["user_id"] = str(100 + len(self.states))
            raw = copy.deepcopy(scenario["raw"])
            for sid in [1, 2]:
                edit._cell(raw, sid, 5, 0)["userEnteredValue"] = {
                    "stringValue": target["user_id"]
                }
            if given is not None:
                edit._cell(raw, 2, 5, 2)["userEnteredValue"] = (
                    {"numberValue": given}
                    if type(given) is int
                    else {"stringValue": given}
                )
            body_ref = self.put(
                name + "-body",
                ("  Complete fictional α " + name + " feedback.\r\n").encode(),
            )
            head_ref = self.put(
                name + "-head",
                {
                    "target": target,
                    "official_attempt": "R1",
                    "native_score": None,
                    "holds": ["KEEP"],
                },
            )
            native_ref = self.put(
                name + "-native", {"grade_preview": None, "holds": ["KEEP"]}
            )
            binding_doc = {
                "target": target,
                "head_ref": head_ref,
                "source_reading_result_policy_refs": {"result": native_ref},
                "fictional_source_family": "COMPLETE_REVIEWED_SOURCE",
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
            qc = {
                "contract": source.QC,
                "verdict": "PASS_PRIVATE_PROPOSAL_ONLY",
                "substantive_findings": [],
                "source_binding": binding_doc,
                "proposed_exact_arithmetic": copy.deepcopy(
                    proposal["exact_arithmetic"]
                ),
                "no_rounding_or_floor_applied": True,
                "component_review": [{}, {}],
                "feedback": {
                    "approved_body": body_ref,
                    "exact_UTF8_hash_required_for_downstream_readback": True,
                },
                "reviewer": "independent-B",
                "author": "author-A",
                "reviewed_at": NOW.isoformat(),
                "review_scope": "WHOLE_TEST",
            }
            req = {
                "contract": source.REQUEST,
                "proposal_ref": self.put(name + "-proposal", proposal),
                "binding_ref": self.put(name + "-binding", binding_doc),
                "qc_ref": self.put(name + "-qc", qc),
                "feedback_ref": body_ref,
            }

            def current(request, b, p, q):
                assert (
                    request == req
                    and b == binding_doc
                    and q == self.load(req["qc_ref"])
                )
                head = self.load(b["head_ref"])
                assert (
                    head["target"] == target
                    and head["official_attempt"] == "R1"
                    and head["native_score"] is None
                    and head["holds"] == ["KEEP"]
                )
                return source.ReviewedWholeContext(
                    source.source_digest(binding_doc),
                    {"grade_preview": None, "status": "HELD", "holds": ["KEEP"]},
                )

            def source_check(request):
                return source.prepare_reviewed_source(
                    request, read_ref=batch.read_reference, current_check=current
                )

            profile = source_check(req)
            stage_ref = self.put(
                name + "-stage",
                {
                    "profile_sha256": source.source_digest(profile),
                    "score_text": profile["score_text"],
                    "feedback_sha256": body_ref["sha256"],
                    "target": target,
                    "state": "NOT_ACCEPTED",
                },
            )
            proof = {
                "contract": "UNIT2_PRIVATE_FINAL_ROUNDING_V1",
                "mode": "NEAREST_WHOLE_PERCENT",
                "boundary": "COMPLETE_ELIGIBLE_PRIVATE_WHOLE",
                "tie_breaker": "UNSPECIFIED",
                "floor_status": "NONE_APPLICABLE",
                "source_request_sha256": profile["source_request_sha256"],
                "source_profile_sha256": source.source_digest(profile),
                "target": target,
                "authority_ref": self.put(
                    name + "-round-authority",
                    {
                        "mode": "NEAREST_WHOLE_PERCENT",
                        "applicable_floor": "NONE_APPLICABLE",
                        "target": target,
                    },
                ),
            }
            case = {
                "case_id": name,
                "source_request_ref": self.put(name + "-request", req),
                "source_author": source.AUTHOR,
                "expected_source_profile_sha256": source.source_digest(profile),
                "qc_ref": req["qc_ref"],
                "body_ref": body_ref,
                "readable_ref": self.put(
                    name + "-readable", b"# Fictional complete saved proposal\n"
                ),
                "sheet_readback_ref": stage_ref,
                "rounding_proof_ref": self.put(name + "-round-proof", proof),
                "target": target,
                "expected_identity_binding_sha256": profile["identity_binding_sha256"],
            }
            state = {
                "raw": raw,
                "sends": 0,
                "source_check": source_check,
                "profile": profile,
                "proof": proof,
                "fail_readback": False,
                "bad_qc": False,
                "preflight_changed": False,
                "factory_error": False,
                "case": case,
                "reads": 0,
            }
            self.states[name] = state
            self.manifest["cases"].append(case)
            return case

        def authority(self, slot, action):
            assert slot["job_slot"] == self.manifest["job_slot"] and action in [
                "READ_ONLY",
                "EDIT_ONCE",
                "UNKNOWN_GET_ONLY",
            ]
            assert slot["case"] is None or slot["case"] in self.manifest["cases"]
            self.scope_calls.append(action)
            if self.revoked:
                raise GradebookError("FICTIONAL_CURRENT_OWNER_REVOKED")

        def services(self, case):
            name = case["case_id"]
            s = self.states[name]
            self.created.append(name)
            if s["factory_error"]:
                raise GradebookError("FICTIONAL_FACTORY_HELD")
            credential = self.put(
                name + "-credential",
                {
                    "tokens": {
                        "gradebook": {
                            "type": "authorized_user",
                            "client_id": "fictional",
                            "client_secret": "fictional",
                            "refresh_token": "fictional",
                        }
                    }
                },
            )

            def transport(request):
                assert request.method == "POST" and request.url.path.endswith(
                    ":batchUpdate"
                )
                payload = json.loads(request.content)
                assert (
                    set(payload) == {"requests", "includeSpreadsheetInResponse"}
                    and payload["includeSpreadsheetInResponse"] is False
                    and len(payload["requests"]) == 1
                )
                u = payload["requests"][0]["updateCells"]
                assert u["fields"] == "userEnteredValue,note"
                assert (
                    type(u["rows"][0]["values"][0]["userEnteredValue"]["numberValue"])
                    is int
                )
                s["sends"] += 1
                edit._cell(
                    s["raw"],
                    u["start"]["sheetId"],
                    u["start"]["rowIndex"],
                    u["start"]["columnIndex"],
                ).update(copy.deepcopy(u["rows"][0]["values"][0]))
                if s.get("cancel_after_send"):
                    raise asyncio.CancelledError()
                return httpx.Response(
                    200,
                    json={
                        "spreadsheetId": scenario["binding"]["spreadsheet_id"],
                        "replies": [{}],
                    },
                )

            g = GoogleSheets(
                scenario["binding"]["spreadsheet_id"],
                credential["path"],
                transport=httpx.MockTransport(transport),
            )
            g._authorized = True
            g._access_token = g._validated_token = "FICTIONAL"
            g._expires_at = time.monotonic() + 1000
            c = GradebookClient(
                "https://fictional.invalid",
                "FICTIONAL",
                transport=httpx.MockTransport(lambda r: httpx.Response(500)),
            )
            self.clients.extend([g.http, c.http])

            async def reader(gg, cc):
                assert gg is g and cc is c
                s["reads"] += 1
                if s["fail_readback"] and s["sends"]:
                    raise httpx.ReadTimeout("fictional")
                raw = copy.deepcopy(s["raw"])
                if s["preflight_changed"] and s["reads"] > 1:
                    raw["sheets"][0]["properties"]["title"] += " CHANGED"
                observed = copy.deepcopy(scenario["canvas_observation"])
                observed["target"] = case["target"]
                return {"raw": raw, "canvas_observation": observed}

            def stage(profile, ref):
                doc = self.load(ref)
                assert ref == case["sheet_readback_ref"] and doc == {
                    "profile_sha256": source.source_digest(profile),
                    "score_text": profile["score_text"],
                    "feedback_sha256": case["body_ref"]["sha256"],
                    "target": case["target"],
                    "state": "NOT_ACCEPTED",
                }

            def target(raw, bound, selected, observed, identity):

                if s.get("target_hold"):
                    raise GradebookError("FICTIONAL_METADATA_PERMISSION_HELD")
                assert (
                    bound == scenario["binding"]
                    and selected == case["target"]
                    and observed["target"] == selected
                    and identity == case["expected_identity_binding_sha256"]
                )
                assert (
                    native._state(raw)["sheets"][2]["properties"]["title"]
                    == "Core Edit"
                )

            def rounding(profile, target, proof):
                authority = self.load(proof["authority_ref"])
                assert (
                    proof == s["proof"]
                    and target == case["target"]
                    and authority
                    == {
                        "mode": "NEAREST_WHOLE_PERCENT",
                        "applicable_floor": "NONE_APPLICABLE",
                        "target": target,
                    }
                )

            def qc(profile, ref, target, body_ref):
                doc = self.load(ref)
                if s["bad_qc"]:
                    raise GradebookError("FICTIONAL_INDEPENDENT_QC_HELD")
                assert (
                    ref == case["qc_ref"]
                    and doc["reviewer"] != doc["author"]
                    and doc["review_scope"] == "WHOLE_TEST"
                    and doc["verdict"] == "PASS_PRIVATE_PROPOSAL_ONLY"
                    and not doc["substantive_findings"]
                    and datetime.fromisoformat(doc["reviewed_at"]) <= NOW
                    and doc["source_binding"]["target"] == target
                    and doc["feedback"]["approved_body"] == body_ref
                    and profile["feedback"].encode() == batch.read_reference(body_ref)
                )

            host = OriginalPrivateWholeHost(
                g,
                c,
                read_context=reader,
                owner_check=lambda: self.authority(
                    {
                        "job_slot": self.manifest["job_slot"],
                        "manifest_ref": None,
                        "case": case,
                    },
                    "READ_ONLY",
                ),
                source_check=s["source_check"],
                staged_source_check=stage,
                target_check=target,
                rounding_check=rounding,
            )
            auth = EditOnlyAuthorization(
                origin=case["target"]["origin"],
                course_id=case["target"]["course_id"],
                assignment_id=case["target"]["assignment_id"],
                approval_reference="FICTIONAL AUTHORIZED PRIVATE EDIT ONLY",
            )
            return batch.CaseRuntime(host, auth, copy.deepcopy(scenario["binding"]), qc)

        def run(self, execute=False):
            ref = self.put(
                "manifest-" + str(len(list(self.out.iterdir()))), self.manifest
            )
            return asyncio.run(
                batch.run_saved_batch(
                    ref,
                    original_owner=self.owner,
                    services_for=self.services,
                    authority_check=self.authority,
                    output_root=self.out,
                    execute=execute,
                    clock=lambda: NOW,
                )
            )

    return World()


def test_real_original_once_two_case_batch_repeat_skips_actual_delivery(world):
    world.add("first")
    world.add("second")
    r = world.run(True)
    assert r["new_delivered_pairs"] == r["new_send_attempts"] == 2
    assert [s["sends"] for s in world.states.values()] == [1, 1]
    assert all(c.is_closed for c in world.clients)
    calls = list(world.created)
    again = world.run(True)
    assert (
        again["verified_no_ops"] == 2
        and again["new_send_attempts"] == 0
        and world.created == calls
    )
    assert all(x["status"] == "NO_OP_DELIVERED" for x in again["results"])
    for directory in world.root.iterdir():
        assert json.loads((directory / "closure.json").read_text(encoding="utf-8")) == {
            "status": "CLOSED",
            "clients_awaited": True,
        }
        p = json.loads((directory / "intent.json").read_text(encoding="utf-8"))["plan"]
        assert (
            p["original_exact_percent"] == "100/3"
            and p["staged_final_percent"] == 33
            and p["source"]["native_context"]["grade_preview"] is None
            and p["source"]["native_context"]["holds"] == ["KEEP"]
        )


def test_one_held_qc_isolated_from_other_genuinely_eligible_case(world):
    world.add("held")
    world.states["held"]["bad_qc"] = True
    world.add("eligible")
    r = world.run(True)
    assert (
        r["results"][0]["reason"] == "FICTIONAL_INDEPENDENT_QC_HELD"
        and r["new_delivered_pairs"] == 1
    )
    assert (
        world.states["held"]["sends"] == 0
        and world.states["eligible"]["sends"] == 1
        and all(c.is_closed for c in world.clients)
    )


@pytest.mark.parametrize("given", [0, "EX"])
def test_given_zero_or_EX_never_written_and_other_case_continues(world, given):
    world.add("given", given=given)
    world.add("eligible")
    r = world.run(True)
    assert (
        r["results"][0]["status"] == "HELD"
        and world.states["given"]["sends"] == 0
        and r["new_delivered_pairs"] == 1
    )


def test_unknown_is_get_only_and_stops_new_effects_then_resume_does_not_resend(world):
    world.add("uncertain")
    world.states["uncertain"]["fail_readback"] = True
    world.add("later")
    r = world.run(True)
    assert (
        r["results"][0]["status"] == "READBACK_UNCERTAIN"
        and r["new_send_attempts"] == 1
        and world.states["later"]["sends"] == 0
    )
    d = next(world.root.iterdir())
    old = (d / "terminal.json").read_bytes()
    world.states["uncertain"]["fail_readback"] = False
    again = world.run(True)
    assert (
        again["results"][0]["status"] == "HELD_UNKNOWN_GET_ONLY"
        and again["results"][0]["observed_status"] == "PLANNED_OUTPUT_OBSERVED"
    )
    assert (
        world.states["uncertain"]["sends"] == 1
        and world.states["later"]["sends"] == 0
        and (d / "terminal.json").read_bytes() == old
    )
    assert "UNKNOWN_GET_ONLY" in world.scope_calls


def test_dry_run_saves_readable_structured_plan_without_intent(world):
    world.add("dry")
    r = world.run(False)
    assert r["results"][0]["status"] == "PREPARED_NOT_EXECUTED" and not list(
        world.root.iterdir()
    )
    p = Path(r["output_directory"])
    assert (
        (p / "result.md").is_file()
        and (p / "result.private.json").is_file()
        and (p / "dry/plan.private.json").is_file()
    )


@pytest.mark.parametrize(
    "kind", ["future", "naive", "extra", "duplicate_target", "four_cases"]
)
def test_manifest_clock_exact_fields_duplicates_and_bound(world, kind):
    world.add("a")
    if kind == "future":
        world.manifest["created_at"] = (NOW + timedelta(seconds=1)).isoformat()
    if kind == "naive":
        world.manifest["created_at"] = "2026-10-27T09:00:00"
    if kind == "extra":
        world.manifest["new_authority_flag"] = True
    if kind == "duplicate_target":
        c = world.add("b")
        c["target"] = copy.deepcopy(world.manifest["cases"][0]["target"])
    if kind == "four_cases":
        world.add("b")
        world.add("c")
        world.add("d")
    with pytest.raises(batch.BatchHold):
        world.run(True)
    assert not world.created and not list(world.root.iterdir())


def test_tampered_body_and_wrong_source_type_are_held(world):
    c = world.add("wrong")
    c["source_author"] = edit.AUTHOR
    r = world.run(True)
    assert (
        r["new_send_attempts"] == 0
        and r["results"][0]["reason"] == "BATCH_EXACT_COMPLETE_SOURCE_BODY_REQUIRED"
    )


def test_owner_revocation_stops_before_client_or_effect(world):
    world.add("a")
    world.revoked = True
    with pytest.raises(GradebookError, match="OWNER_REVOKED"):
        world.run(True)
    assert not world.created and not list(world.root.iterdir())


def test_preflight_protected_metadata_change_creates_no_intent(world):
    world.add("a")
    world.states["a"]["preflight_changed"] = True
    r = world.run(True)
    assert (
        r["results"][0]["status"] == "HELD_BEFORE_SEND" and r["new_send_attempts"] == 0
    )
    assert all(not (p / "intent.json").exists() for p in world.root.iterdir())


def test_completed_case_excluded_without_reopening_qc_or_factory(world):
    world.add("already")
    world.run(True)
    world.states["already"]["factory_error"] = True
    world.states["already"]["bad_qc"] = True
    created = list(world.created)
    r = world.run(True)
    assert (
        r["verified_no_ops"] == 1
        and r["new_send_attempts"] == 0
        and world.created == created
    )


@pytest.mark.parametrize(
    "key",
    ["qc_ref", "body_ref", "readable_ref", "sheet_readback_ref", "rounding_proof_ref"],
)
def test_each_saved_proof_hash_is_checked_before_effect(world, key):
    c = world.add("a")
    Path(c[key]["path"]).write_bytes(b"changed")
    r = world.run(True)
    assert (
        r["results"][0]["status"] == "HELD"
        and r["new_send_attempts"] == 0
        and not list(world.root.iterdir())
        and all(x.is_closed for x in world.clients)
    )


def test_partial_profile_cannot_use_complete_batch_contract(world):
    c = world.add("partial")
    old = world.states["partial"]["source_check"]
    profile = old(world.load(c["source_request_ref"]))
    profile["scope"] = "MC_AND_FRQ_PARTIAL"
    c["expected_source_profile_sha256"] = source.source_digest(profile)
    world.states["partial"]["source_check"] = lambda req: copy.deepcopy(profile)
    r = world.run(True)
    assert (
        r["results"][0]["reason"] == "BATCH_EXACT_COMPLETE_SOURCE_BODY_REQUIRED"
        and r["new_send_attempts"] == 0
    )


def test_current_metadata_permission_hold_not_defaulted_away(world):
    world.add("a")
    world.states["a"]["target_hold"] = True
    r = world.run(True)
    assert r["results"][0]["status"] == "HELD" and r["new_send_attempts"] == 0
    assert not list(world.root.iterdir())


def test_boolean_cannot_impersonate_successful_qc_checker(world):
    world.add("a")
    old = world.services

    def wrong(case):
        service = old(case)
        return batch.CaseRuntime(
            service.host, service.authorization, service.binding, lambda *args: True
        )

    world.services = wrong
    r = world.run(True)
    assert (
        r["results"][0]["reason"] == "BATCH_CURRENT_INDEPENDENT_QC_REQUIRED"
        and r["new_send_attempts"] == 0
    )


def test_async_qc_checker_cannot_impersonate_current_authority(world):
    world.add("a")
    old = world.services

    async def wrong(*args):
        return None

    def service(case):
        good = old(case)
        return batch.CaseRuntime(good.host, good.authorization, good.binding, wrong)

    world.services = service
    r = world.run(True)
    assert (
        r["results"][0]["reason"] == "BATCH_SYNCHRONOUS_AUTHENTIC_CHECK_REQUIRED"
        and r["new_send_attempts"] == 0
    )


@pytest.mark.parametrize("value", [True, 1.0, -1])
def test_typed_target_attempt_never_coerced(world, value):
    c = world.add("a")
    c["target"]["attempt"] = value
    with pytest.raises(batch.BatchHold, match="TARGET_ATTEMPT"):
        world.run(True)
    assert not world.created


def test_unknown_target_future_field_is_not_dropped(world):
    c = world.add("a")
    c["target"]["new_teacher_authority"] = True
    with pytest.raises(batch.BatchHold, match="EXACT_TARGET"):
        world.run(True)


def test_callback_rebinding_is_held_without_an_intent(world):
    world.add("a")
    old = world.services

    def service(case):
        good = old(case)
        wrong = copy.deepcopy(good.binding)
        wrong["course_id"] = "999"
        return batch.CaseRuntime(good.host, good.authorization, wrong, good.qc_check)

    world.services = service
    r = world.run(True)
    assert r["results"][0]["status"] == "HELD" and r["new_send_attempts"] == 0


def test_cancel_after_possible_effect_persists_unknown_and_never_moves_to_next(world):
    world.add("a")
    world.add("b")
    world.states["a"]["cancel_after_send"] = True
    with pytest.raises(asyncio.CancelledError):
        world.run(True)
    assert world.states["a"]["sends"] == 1 and world.states["b"]["sends"] == 0
    directory = next(world.root.iterdir())
    assert (
        json.loads((directory / "terminal.json").read_text(encoding="utf-8"))["status"]
        == "READBACK_UNCERTAIN"
    )
    report = next(world.out.glob("*/a/result.private.json"))
    v = json.loads(report.read_text(encoding="utf-8"))
    assert (
        v["status"] == "HELD_UNKNOWN_GET_ONLY"
        and v["interrupted"] is True
        and v["new_send_attempts"] == 1
    )
    assert all(c.is_closed for c in world.clients)


def test_duplicate_json_key_and_symlink_refs_are_rejected(world, tmp_path):
    c = world.add("a")
    ref = world.put("duplicate", b'{"contract":"bad","contract":"also-bad"}')
    with pytest.raises(batch.BatchHold, match="DUPLICATE"):
        batch.load_manifest(ref, clock=lambda: NOW)
    link = tmp_path / "symlink"
    link.symlink_to(c["body_ref"]["path"])
    r = {**c["body_ref"], "path": str(link)}
    with pytest.raises(batch.BatchHold, match="DIRECT_REFERENCE"):
        batch.read_reference(r)


def test_all_observed_legacy_families_and_old_qc_gap_use_original_verifiers(
    world, faithful_manifest
):
    (owner, old_host, old_plan, _), directory, intent, terminal, readback, verify = (
        faithful_manifest
    )
    world.owner = owner
    world.root = owner.root
    owner.manifest_history_check = verify
    # Explicit old source/QC cache GAP, never reconstructed or needed for this new
    # independently reviewed source; original durable effect still verifies.
    old_qc = next(directory.glob("historical-qc.json"))
    old_qc.unlink()
    embedded = owner.root / "old-embedded-plan"
    embedded.mkdir(mode=0o700)
    state = json.loads(json.dumps(native._state(old_plan["before_raw"])))
    legacy_plan = {"after_state": state}
    records = {
        "intent.json": {
            "contract": "ORIGINAL_NOTE_HISTORY",
            "plan": legacy_plan,
            "plan_sha256": digest(legacy_plan),
        },
        "terminal.json": {
            "status": "PLANNED_OUTPUT_OBSERVED",
            "send_attempts": 1,
            "plan_sha256": digest(legacy_plan),
        },
        "readback.json": {
            "status": "PLANNED_OUTPUT_OBSERVED",
            "native_state": state,
            "fingerprint": digest(state),
            "raw": old_plan["before_raw"],
        },
        "closure.json": {"status": "CLOSED"},
    }
    for n, v in records.items():
        p = embedded / n
        p.write_text(json.dumps(v), encoding="utf-8")
        p.chmod(0o600)
    held = owner.root / "old-presend-hold"
    held.mkdir(mode=0o700)
    for n, v in {
        "terminal.json": {"status": "HELD_BEFORE_SEND", "send_attempts": 0},
        "closure.json": {"status": "CLOSED"},
    }.items():
        p = held / n
        p.write_text(json.dumps(v), encoding="utf-8")
        p.chmod(0o600)
    before = {
        str(p): p.read_bytes() for d in [directory, embedded, held] for p in d.iterdir()
    }
    world.add("new")
    r = world.run(True)
    assert (
        r["new_delivered_pairs"] == 1
        and owner.fixture_closed_history_evidence["historical_source_provenance"]
        == "GAP"
    )
    assert before == {
        str(p): p.read_bytes() for d in [directory, embedded, held] for p in d.iterdir()
    }
    asyncio.run(old_host.close())


@pytest.mark.parametrize("damage", ["unknown", "missing_closure", "readback_tamper"])
def test_unresolved_legacy_history_is_never_skipped(world, faithful_manifest, damage):
    (owner, old_host, _, _), directory, intent, terminal, readback, verify = (
        faithful_manifest
    )
    world.owner = owner
    world.root = owner.root
    owner.manifest_history_check = verify
    if damage == "unknown":
        terminal["status"] = "READBACK_UNCERTAIN"
        p = directory / "terminal.json"
        p.write_text(json.dumps(terminal), encoding="utf-8")
    if damage == "missing_closure":
        (directory / "closure.json").unlink()
    if damage == "readback_tamper":
        readback["raw"]["sheets"][0]["properties"]["title"] = "TAMPER"
        p = directory / "readback.json"
        p.write_text(json.dumps(readback), encoding="utf-8")
    world.add("new")
    r = world.run(True)
    assert (
        r["new_send_attempts"] == 0
        and r["new_delivered_pairs"] == 0
        and world.states["new"]["sends"] == 0
    )
    asyncio.run(old_host.close())


def test_author5_source_and_body_flags_preserved_with_separate_independent_qc(
    world, scenario
):
    case = world.add("author5")
    state = world.states["author5"]
    # Reuse the original fictional AUTHOR5 producer fixture; no relabelling as
    # the independent-reviewed source variant. Its separate current QC proof
    # below is file-backed and does not flip the original body/native flags.
    request = copy.deepcopy(scenario["source_request"])
    profile = scenario["source_check"](request)
    case["source_request_ref"] = world.put("author5-original-request", request)
    case["source_author"] = edit.AUTHOR
    case["expected_source_profile_sha256"] = source.source_digest(profile)
    case["expected_identity_binding_sha256"] = profile["identity_binding_sha256"]
    case["body_ref"] = world.put("author5-literal-body", profile["feedback"].encode())
    case["sheet_readback_ref"] = world.put(
        "author5-actual-fictional-sheet",
        {
            "profile_sha256": source.source_digest(profile),
            "score_text": profile["score_text"],
            "feedback_sha256": case["body_ref"]["sha256"],
            "target": case["target"],
            "state": "NOT_ACCEPTED",
        },
    )
    qc_doc = {
        "contract": "FICTIONAL_INDEPENDENT_AUTHOR5_WHOLE_QC_V1",
        "source_profile_sha256": source.source_digest(profile),
        "target": case["target"],
        "body_ref": case["body_ref"],
        "reviewer": "B",
        "author": "A",
        "scope": "WHOLE_TEST",
        "verdict": "PASS_PRIVATE_PROPOSAL_ONLY",
    }
    case["qc_ref"] = world.put("author5-independent-QC", qc_doc)
    proof = copy.deepcopy(state["proof"])
    proof.update(
        source_request_sha256=profile["source_request_sha256"],
        source_profile_sha256=source.source_digest(profile),
    )
    state["proof"] = proof
    case["rounding_proof_ref"] = world.put("author5-correct-round-proof", proof)
    state["source_check"] = scenario["source_check"]
    old = world.services

    def services(selected):
        good = old(selected)

        def qc(current, ref, target, body_ref):
            actual = world.load(ref)
            assert (
                actual == qc_doc
                and actual["source_profile_sha256"] == source.source_digest(current)
                and actual["target"] == target
                and actual["body_ref"] == body_ref
                and actual["reviewer"] != actual["author"]
                and actual["scope"] == "WHOLE_TEST"
                and actual["verdict"] == "PASS_PRIVATE_PROPOSAL_ONLY"
            )

        return batch.CaseRuntime(good.host, good.authorization, good.binding, qc)

    world.services = services
    result = world.run(True)
    assert result["new_delivered_pairs"] == 1 and state["sends"] == 1
    intent = json.loads(next(world.root.iterdir()).joinpath("intent.json").read_text(encoding="utf-8"))
    actual = intent["plan"]["source"]
    assert (
        actual["author_contract"] == edit.AUTHOR
        and actual["actual_authored_body_version"] == edit.BODY_VERSION
    )
    assert actual["original_feedback_format_status"]["is_body_QC_passed"] is False
    assert (
        actual["review_state"]["status"] == "NOT_REVIEWED"
        and actual["teacher_accepted"] is False
    )


def test_numeric_json_spelling_is_not_silently_normalized_outside_original_contract(
    world,
):
    world.add("a")
    old = world.services

    def services(case):
        good = old(case)
        original = good.host.reader

        async def reader(g, c):
            value = await original(g, c)
            if world.states["a"]["sends"]:
                edit._cell(value["raw"], 2, 5, 2)["userEnteredValue"]["numberValue"] = (
                    33.0
                )
            return value

        good.host.reader = reader
        return good

    world.services = services
    result = world.run(True)
    assert (
        result["results"][0]["status"] == "DIVERGED"
        and result["unresolved_original_effects_remain_fenced"] is True
    )
    assert world.states["a"]["sends"] == 1 and result["retry_writes"] is False


def test_case_custody_authority_precedes_any_private_reference_read_and_isolated(
    world, monkeypatch
):
    denied = world.add("denied")
    world.add("permitted")
    original_authority = world.authority

    def authority(context, action):
        if context["case"] is not None and context["case"]["case_id"] == "denied":
            raise GradebookError("FICTIONAL_SOURCE_CUSTODY_DENIED")
        return original_authority(context, action)

    world.authority = authority
    original_reader = batch.read_reference

    def reader(ref):
        assert ref != denied["source_request_ref"], (
            "DENIED_REFERENCE_MUST_NOT_BE_OPENED"
        )
        return original_reader(ref)

    monkeypatch.setattr(batch, "read_reference", reader)
    result = world.run(True)
    assert result["results"][0]["reason"] == "FICTIONAL_SOURCE_CUSTODY_DENIED"
    assert "denied" not in world.created and result["new_delivered_pairs"] == 1


def test_invalid_runtime_authorization_still_closes_original_clients(world):
    world.add("a")
    old = world.services

    def services(case):
        good = old(case)
        return batch.CaseRuntime(good.host, True, good.binding, good.qc_check)

    world.services = services
    result = world.run(True)
    assert result["new_send_attempts"] == 0 and result["results"][0]["status"] == "HELD"
    assert world.clients and all(c.is_closed for c in world.clients)


def test_unknown_terminal_count_is_not_fabricated_as_zero(world, monkeypatch):
    from canvas_mcp.gradebook import (
        unit2_private_proposed_owner as original_owner_module,
    )

    world.add("a")
    world.add("b")
    original_save = original_owner_module._save

    def fail_terminal(path, value):
        if path.name == "terminal.json":
            raise OSError("FICTIONAL_TERMINAL_IO_FAILURE")
        return original_save(path, value)

    monkeypatch.setattr(original_owner_module, "_save", fail_terminal)
    result = world.run(True)
    assert world.states["a"]["sends"] == 1 and world.states["b"]["sends"] == 0
    assert result["new_send_attempts"] is None
    assert (
        result["known_new_send_attempts"] == 0
        and result["unknown_send_attempt_case_count"] == 1
    )
    assert result["results"][0]["status"] == "HELD_UNKNOWN_GET_ONLY"
    assert result["unresolved_original_effects_remain_fenced"] is True
    assert all(c.is_closed for c in world.clients)
