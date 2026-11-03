"""Student-free actual native record shapes; no domain files or network."""

import copy
import hashlib
import json

import pytest
from test_gradebook import snapshot as snapshot
from test_gradebook_native import binding as binding
from test_private_proposed_edit import scenario as scenario
from test_saved_edit_batch import world as world

from canvas_mcp.gradebook import unit2_native_whole_source as source
from canvas_mcp.gradebook import unit2_private_proposed_edit as edit
from canvas_mcp.gradebook import unit2_saved_edit_batch as batch
from canvas_mcp.gradebook.client import GradebookError
from canvas_mcp.gradebook.model import digest


@pytest.fixture
def native_source(tmp_path):
    class Fixture:
        def __init__(self):
            self.files = {}
            self.docs = {}
            self.calls = []
            self.revoked = False
            self.reject_fidelity = False
            self.packet = {
                "packet_id": "fictional-packet",
                "source_sha256": "1" * 64,
                "academic_sha256": "2" * 64,
                "assessment_id": "fictional-assessment",
                "form_id": "F",
                "pin": "0042",
                "section": "A2",
                "attempt": "R1",
                "schema_version": 1,
            }
            self.policy = {
                "status": "SEALED",
                "grade_operations": [{"op": "to_percent"}],
            }
            self.head = {
                "reading_key": "reading-fake",
                "judgment_key": "judge-fake",
                "result_key": "result-fake",
                "status": "QC_CLEARED",
            }
            criteria = [
                {
                    "criterion_id": "c1",
                    "part_id": "a",
                    "earned_points": "0",
                    "maximum_points": "1",
                    "reason": "Fictional literal α",
                    "status": "PROPOSED",
                    "component": "mastery",
                    "basis": "saved",
                },
                {
                    "criterion_id": "c2",
                    "part_id": "a",
                    "earned_points": "0",
                    "maximum_points": "1",
                    "reason": "Fictional literal β",
                    "status": "PROPOSED",
                    "component": "attempt",
                    "basis": "saved",
                },
            ]
            self.result = dict(
                schema_version=1,
                **{
                    k: self.packet[k]
                    for k in [
                        "packet_id",
                        "source_sha256",
                        "academic_sha256",
                        "assessment_id",
                        "form_id",
                    ]
                },
                reading_key=self.head["reading_key"],
                judgment_key=self.head["judgment_key"],
                status="PROPOSED_REVIEW_REQUIRED",
                holds=[],
                teacher_acceptance="NOT_ACCEPTED",
                publication_status="NOT_AUTHORIZED",
                grade_preview="100/3",
                known_weighted_earned="1",
                weighted_possible="3",
                operation_traces=[
                    {"operation": {"op": "to_percent"}, "before": "1", "after": "100/3"}
                ],
                items=[
                    {
                        "item_id": "MC1",
                        "kind": "MC",
                        "recorded_choice": "B",
                        "earned_points": "1",
                        "maximum_points": "1",
                        "weight": "1",
                        "criteria": [],
                        "status": "PROPOSED",
                    },
                    {
                        "item_id": "FRQ1",
                        "kind": "FRQ",
                        "recorded_choice": None,
                        "earned_points": "0",
                        "maximum_points": "2",
                        "weight": "1",
                        "criteria": criteria,
                        "status": "PROPOSED",
                    },
                ],
                deductions=[
                    {
                        "item_id": "FRQ1",
                        "criterion_id": c["criterion_id"],
                        "points_lost": "1",
                        "reason": c["reason"],
                    }
                    for c in criteria
                ],
            )
            self.body = "0042 | A2 | F\nFRQ1a: read-blank | key-Fictional complete correction | -2"
            self.fidelity = self.put(
                "independent-source-line-fidelity",
                {"synthetic_replay": "passed", "new_science": False},
            )
            self.rebuild()

        def put(self, name, value):
            b = (
                value
                if type(value) is bytes
                else json.dumps(value, ensure_ascii=False).encode()
            )
            p = tmp_path / name
            self.files[str(p)] = b
            p.write_bytes(b)
            return {
                "path": str(p),
                "bytes": len(b),
                "sha256": hashlib.sha256(b).hexdigest(),
            }

        def rebuild(self):
            refs = {k: self.put(k, {"fictional": k}) for k in source.NATIVE_REFS}
            refs.update(
                head_ref=self.put("head", self.head),
                packet_ref=self.put("packet", self.packet),
                policy_ref=self.put("policy", self.policy),
            )
            self.result["policy_sha256"] = refs["policy_ref"]["sha256"]
            refs["result_ref"] = self.put("result", self.result)
            projection = {
                "packet_id": self.result["packet_id"],
                "source_sha256": self.result["source_sha256"],
                "result_key": self.head["result_key"],
                "items": copy.deepcopy(self.result["items"]),
                "holds": [],
                "summary_row": {
                    "grade_preview": self.result["grade_preview"],
                    "teacher_accepted_grade": "",
                    "canvas_status": "NOT_AUTHORIZED",
                    "holds": 0,
                },
                "status": "QC_CLEARED",
                "feedback": source.native_feedback_text(self.result),
            }
            binding = {
                "contract": source.BINDING,
                "source_reading_result_policy_refs": refs,
                "packet_id": self.packet["packet_id"],
                "source_sha256": self.packet["source_sha256"],
                "identity": {
                    k: self.packet[k] for k in ["pin", "section", "form_id", "attempt"]
                },
            }
            source_binding = {
                k: self.result[k]
                for k in [
                    "packet_id",
                    "source_sha256",
                    "reading_key",
                    "form_id",
                    "policy_sha256",
                    "academic_sha256",
                ]
            }
            source_binding.update(
                result_key=self.head["result_key"],
                **{
                    k: refs[n]["sha256"]
                    for k, n in [
                        ("packet_json_sha256", "packet_ref"),
                        ("reading_json_sha256", "reading_ref"),
                        ("result_json_sha256", "result_ref"),
                    ]
                },
            )
            inputs = {
                "source_binding": source_binding,
                "existing_feedback_body": projection["feedback"],
                "items": [
                    {
                        "item": 1,
                        "student_choice": "B",
                        "native_earned_points": "1",
                        "possible_points": "1",
                        "source_binding": {"item_id": "MC1"},
                    }
                ],
                "frq_parts": [
                    {
                        "part_id": "a",
                        "earned_points": "0",
                        "possible_points": "2",
                        "source_binding": {
                            "item_id": "FRQ1",
                            "native_criteria": copy.deepcopy(
                                self.result["items"][1]["criteria"]
                            ),
                        },
                    }
                ],
            }
            output = dict(
                source_version="UNIT2_COMPACT_FEEDBACK_V3",
                source_binding=copy.deepcopy(source_binding),
                compact_text=self.body,
                compact_lines=self.body.split("\n"),
                existing_feedback_body=projection["feedback"],
                student_hold_row_count=0,
                teacher_review_row_count=0,
                teacher_review_required=False,
                whole_final_numeric=None,
                whole_final_disposition="UNCHANGED",
                **dict.fromkeys(
                    [
                        "publication_allowed",
                        "staging_allowed",
                        "canvas_write_allowed",
                        "automatic_grading_allowed",
                        "teacher_acceptance_allowed",
                    ],
                    False,
                ),
            )
            deductions = self.put("deductions", self.result["deductions"])
            qc = {
                "contract": source.QC,
                "verdict": "PASS_CURRENT_SAVED_RESULT_ACADEMIC_QC",
                "findings": [],
                "exact_result_binding": {
                    "current_result_key": self.head["result_key"],
                    **refs,
                },
                "current_actor_proof": {
                    "fictional_authenticated_current_actor": "reviewer-B"
                },
                "historical_actor_origin_gap": "UNAUTHENTICATED_PRESERVED",
                "rational_arithmetic": {
                    "weighted_earned_exact": "1",
                    "weighted_possible_exact": "3",
                    "percentage_exact": "100/3",
                    "matches_saved_preview": True,
                    "rounding_or_floor_or_award_changes": False,
                },
                "component_matrix": [
                    {"item_id": x, "verdict": "SUPPORTED"}
                    for x in ["MC1", "FRQ1", "FRQ1"]
                ],
                "review_scope": {
                    "total_components": 3,
                    "required_items": 2,
                    "deduction_feedback_entries": len(self.result["deductions"]),
                },
                "feedback": {
                    "reviewed_exact_saved_deduction_data": deductions,
                    "all_deduction_scopes_amounts_and_reasons_supported": True,
                    "deduction_text_changes": False,
                    "new_assembled_student_comment_created": False,
                },
            }
            self.docs = {
                "binding_ref": binding,
                "result_ref": self.result,
                "projection_ref": projection,
                "qc_ref": qc,
                "deductions_ref": self.result["deductions"],
                "feedback_input_ref": inputs,
                "feedback_output_ref": output,
            }
            self.request = dict(
                contract=source.REQUEST,
                **{k: self.put(k, v) for k, v in self.docs.items()},
                feedback_ref=self.put("body", self.body.encode()),
            )
            self.request["result_ref"] = refs["result_ref"]
            self.request["deductions_ref"] = deductions

        def alter(self, name, change):
            value = copy.deepcopy(self.docs[name])
            change(value)
            self.docs[name] = value
            self.request[name] = self.put(name, value)

        def current(self, req, bind, native, result, qc):
            self.calls.append("current")
            if self.revoked:
                raise GradebookError("ACTUAL_OWNER_SCOPE_REVOKED")
            assert req == self.request and native["head_ref"] == self.head
            return source.NativeWholeContext(
                "a" * 64, {k: result[k] for k in ["grade_preview", "status", "holds"]}
            )

        def feedback(self, req, *args):
            self.calls.append("fidelity")
            if self.reject_fidelity:
                raise GradebookError("ACTUAL_SOURCE_LINE_FIDELITY_MISSING")
            return source.NativeFeedbackContext(
                *(
                    req[k]["sha256"]
                    for k in [
                        "feedback_input_ref",
                        "feedback_output_ref",
                        "feedback_ref",
                    ]
                ),
                self.fidelity,
            )

        def prepare(self):
            return source.prepare_native_source(
                self.request,
                read_ref=lambda r: self.files[r["path"]],
                current_check=self.current,
                feedback_check=self.feedback,
            )

    return Fixture()


def test_actual_native_shape_has_honest_common_profile(native_source):
    n = native_source
    p = n.prepare()
    assert (
        p["author_contract"] == source.AUTHOR
        and p["actual_authored_body_version"] == source.BODY
    )
    assert p["feedback"] == n.body and p["score_text"] == "100/3"
    assert p["native_context"] == {
        "grade_preview": "100/3",
        "status": "PROPOSED_REVIEW_REQUIRED",
        "holds": [],
    }
    assert p["original_feedback_format_status"]["is_body_QC_passed"] is False
    assert p["original_feedback_format_status"]["new_comment_assembly"] is False
    assert p["source_math_validation"]["reason_entries_preserved_in_native_export"] == 2
    assert n.calls == ["current", "fidelity"]
    assert all(
        p[k] is False
        for k in ["teacher_accepted", "live_write_allowed", "publication_allowed"]
    )


@pytest.mark.parametrize(
    "field,value",
    [
        ("holds", [{"reason": "UNREADABLE"}]),
        ("grade_preview", None),
        ("teacher_acceptance", "TEACHER_ACCEPTED"),
        ("publication_status", "AUTHORIZED"),
        ("status", "HELD"),
        ("schema_version", True),
        ("operation_traces", []),
    ],
)
def test_native_null_hold_acceptance_never_become_complete(native_source, field, value):
    n = native_source
    n.result[field] = value
    n.rebuild()
    with pytest.raises(GradebookError):
        n.prepare()


@pytest.mark.parametrize(
    "name,change",
    [
        ("qc_ref", lambda v: v.update(verdict="QC_CLEARED")),
        ("qc_ref", lambda v: v.update(current_actor_proof={})),
        (
            "qc_ref",
            lambda v: v["exact_result_binding"].update(current_result_key="other"),
        ),
        ("qc_ref", lambda v: v.update(findings=["held"])),
        ("qc_ref", lambda v: v["component_matrix"].pop()),
        ("qc_ref", lambda v: v["feedback"].update(deduction_text_changes=True)),
        ("qc_ref", lambda v: v["rational_arithmetic"].update(percentage_exact=True)),
        (
            "qc_ref",
            lambda v: v["rational_arithmetic"].update(percentage_exact="33.333"),
        ),
        ("projection_ref", lambda v: v.update(result_key="other")),
        ("projection_ref", lambda v: v.update(status="TEACHER_ACCEPTED")),
        (
            "projection_ref",
            lambda v: v["summary_row"].update(teacher_accepted_grade="80"),
        ),
        (
            "projection_ref",
            lambda v: v["summary_row"].update(canvas_status="AUTHORIZED"),
        ),
        ("projection_ref", lambda v: v["summary_row"].update(holds=True)),
        ("projection_ref", lambda v: v.update(feedback="Missing native reason")),
        ("projection_ref", lambda v: v["items"].pop()),
        ("deductions_ref", lambda v: v.pop()),
        (
            "deductions_ref",
            lambda v: v.append(
                {"item_id": "MC2", "points_lost": "1", "reason": "invented"}
            ),
        ),
        (
            "feedback_input_ref",
            lambda v: v["frq_parts"][0]["source_binding"]["native_criteria"].pop(),
        ),
        ("feedback_input_ref", lambda v: v["frq_parts"][0].update(earned_points="1")),
        (
            "feedback_input_ref",
            lambda v: v["items"][0].update(native_earned_points="0"),
        ),
        (
            "feedback_input_ref",
            lambda v: v["source_binding"].update(result_json_sha256="0" * 64),
        ),
        ("feedback_output_ref", lambda v: v.update(compact_text="changed")),
        ("feedback_output_ref", lambda v: v.update(teacher_review_required=True)),
        (
            "feedback_output_ref",
            lambda v: v.update(source_version="UNIT2_COMPACT_FEEDBACK_V7"),
        ),
    ],
)
def test_source_result_qc_render_omission_and_extra_negatives(
    native_source, name, change
):
    n = native_source
    n.alter(name, change)
    with pytest.raises(GradebookError):
        n.prepare()


def test_current_authority_and_independent_body_proof_are_real_boundaries(
    native_source,
):
    n = native_source
    n.revoked = True
    with pytest.raises(GradebookError, match="SCOPE_REVOKED"):
        n.prepare()
    n.revoked = False
    n.reject_fidelity = True
    with pytest.raises(GradebookError, match="FIDELITY_MISSING"):
        n.prepare()
    n.reject_fidelity = False
    n.files[n.fidelity["path"]] = b"tampered"
    with pytest.raises(GradebookError, match="BYTES_CHANGED"):
        n.prepare()


def test_native_profile_is_rejected_on_body_math_and_authority_mutation(native_source):
    n = native_source
    p = n.prepare()
    for field, value in [
        ("feedback", "changed"),
        ("score_text", "40"),
        ("teacher_accepted", True),
    ]:
        v = copy.deepcopy(p)
        v[field] = value
        with pytest.raises(GradebookError):
            source.validate_native_profile(n.request, v)


def test_shared_edit_planner_native_branch_preserves_original_context_and_body(
    native_source, scenario
):
    n = native_source
    profile = n.prepare()
    identity = scenario["expected_identity_binding_sha256"]

    def check(req):
        assert req == n.request
        p = n.prepare()
        p["identity_binding_sha256"] = identity
        return p

    env = {k: v for k, v in scenario.items() if not k.startswith("_")}
    env.update(
        source_request=n.request,
        source_check=check,
        staged_source_check=lambda p, r: None,
    )
    before = copy.deepcopy(env["raw"])
    plan = edit.prepare_private_edit(**env)
    assert env["raw"] == before
    assert plan["source"]["native_context"] == profile["native_context"]
    update = plan["requests"][0]["updateCells"]["rows"][0]["values"][0]
    assert update["userEnteredValue"] == {"stringValue": "100/3"}
    assert (
        update["note"].endswith(n.body + "\n" + edit.END)
        and source.BODY in update["note"]
    )
    assert update["note"].startswith("Teacher manual prefix\r\n")
    assert (
        edit.classify_private_edit_readback(
            plan, plan["after_raw"], expected_plan_sha256=digest(plan)
        )["status"]
        == "PLANNED_OUTPUT_OBSERVED"
    )


def native_world(world, native_source, *, given=None):
    """Compose the real original owner/controlled transport, honest native QC."""
    n = native_source
    case = world.add("native", given=given)
    state = world.states["native"]
    p = n.prepare()
    case.update(
        source_request_ref=world.put("native-current-request", n.request),
        source_author=source.AUTHOR,
        expected_source_profile_sha256=source.source_digest(p),
        qc_ref=n.request["qc_ref"],
        body_ref=n.request["feedback_ref"],
        expected_identity_binding_sha256=p["identity_binding_sha256"],
    )
    state.update(source_check=lambda req: n.prepare(), profile=p)
    case["sheet_readback_ref"] = world.put(
        "native-real-fixture-stage",
        {
            "profile_sha256": source.source_digest(p),
            "score_text": p["score_text"],
            "feedback_sha256": case["body_ref"]["sha256"],
            "target": case["target"],
            "state": "NOT_ACCEPTED",
        },
    )
    proof = state["proof"]
    proof.update(
        source_request_sha256=p["source_request_sha256"],
        source_profile_sha256=source.source_digest(p),
    )
    case["rounding_proof_ref"] = world.put("native-current-rounding-proof", proof)
    original_services = world.services

    def services(selected):
        runtime = original_services(selected)

        def native_qc(profile, ref, target, bodyref):
            if state["bad_qc"]:
                raise GradebookError("CURRENT_NATIVE_QC_HELD")
            assert (
                ref == n.request["qc_ref"]
                and target == case["target"]
                and bodyref == n.request["feedback_ref"]
            )
            assert world.load(ref) == n.docs["qc_ref"]
            assert (
                profile["author_contract"] == source.AUTHOR
                and profile["feedback"] == n.body
            )

        return batch.CaseRuntime(
            runtime.host, runtime.authorization, runtime.binding, native_qc
        )

    world.services = services
    return state


def test_native_original_once_numeric_full_body_readback_and_repeat_noop(
    world, native_source
):
    state = native_world(world, native_source)
    result = world.run(True)
    assert result["new_delivered_pairs"] == result["new_send_attempts"] == 1
    assert state["sends"] == 1
    again = world.run(True)
    assert (
        again["new_delivered_pairs"] == again["new_send_attempts"] == 0
        and state["sends"] == 1
    )
    assert all(c.is_closed for c in world.clients)


def test_native_unknown_is_get_only_never_resent(world, native_source):
    state = native_world(world, native_source)
    state["fail_readback"] = True
    result = world.run(True)
    assert (
        result["results"][0]["status"] == "READBACK_UNCERTAIN" and state["sends"] == 1
    )
    state["fail_readback"] = False
    again = world.run(True)
    assert again["results"][0]["status"] == "HELD_UNKNOWN_GET_ONLY"
    assert state["sends"] == 1


@pytest.mark.parametrize("given", [0, "EX", 80])
def test_native_given_zero_excused_manual_higher_is_preserved(
    world, native_source, given
):
    state = native_world(world, native_source, given=given)
    before = copy.deepcopy(state["raw"])
    result = world.run(True)
    assert result["new_delivered_pairs"] == result["new_send_attempts"] == 0
    assert state["sends"] == 0 and state["raw"] == before
