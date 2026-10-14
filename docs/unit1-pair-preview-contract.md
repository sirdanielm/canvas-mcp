# Unit 1 accepted-pair publication preview

This page describes the **unregistered offline accepted-pair prototypes** merged
through [PR #8](https://github.com/sirdanielm/canvas-mcp/pull/8).
`unit1_preview`, `unit1_delivery_contract` and `unit1_canvas_protocol` do not
authenticate RELEASE or send classroom records. Preview channels remain
`NOT_SENT`, with publication and pair verification false. A merge does not
install or activate a bridge.

Separate bounded local delivery and the existing generic publisher have their
own authorities and receipts. See [current goals and status](goals-and-status.md)
for dated operational facts. The
[full retained specification](https://github.com/sirdanielm/canvas-mcp/blob/d0794b247df2b865150c4805d816b9075768ae92/docs/unit1-pair-preview-contract.md)
preserves implementation details and historical qualifications.

## What the teacher controls mean

The intended chain is saved evidence → proposal → authenticated teacher decision
→ separately authorized release → independent score and comment readback.
**Save draft** preserves edits. **Accept** freezes the reviewed pair and evidence;
it does not send. A publisher response still requires independent verification.
The fictional Teacher Review Demo does not process real papers. Private original
review does not itself create the accepted-pair export or release connection.

## One handoff, distinct authorities

GrAss owns Unit 1 source/result validation and academic policy; LocalGrAss owns
the authenticated teacher-decision export; Canvas owns identity, remote targeting
and delivery. Reuse those authorities and their journals.

`LocalWorkflow.process` remains fictional. Its generic `actor_authentication` is
`NOT_IMPLEMENTED`; the separate local review layer retains authenticated account,
draft and acceptance provenance. A boolean, caller-created ActorContext or copied
hash cannot authenticate consent. The prototype release bridge remains
FakeTransport-only and refuses real advisory owner results. Actual paper-source,
academic-authentication and accepted-pair RELEASE integration remain unfinished.

## Proposed private envelope

`build_pair_preview(pair, ...)` accepts `grass_unit1_accepted_pair_v1` with integer
`schema_version=1` for attempt-bound checks, or `grass_unit1_accepted_pair_v2` with
integer `schema_version=2` for explicit paper roster/assignment binding.

| Fields | Retained meaning |
| --- | --- |
| `case_key`, `academic_assignment_id`, `decision_id` | Exact owner case, academic assignment and decision |
| `source_revision`, `result_revision`, `policy_revision`, `identity_revision`, `binding_revision` | Opaque substantive revisions, preserved verbatim |
| `source_sha256`, `result_sha256`, `policy_sha256`, `identity_sha256`, `binding_sha256`, `form_sha256` | Independent owner content digests |
| `origin`, `course_id`, `canvas_assignment_id`, `canvas_user_id`, `pin`, `section_id`, `form_id`, `paper_attempt` | Exact target and packet binding; IDs/PIN remain text |
| `raw_score`, `raw_maximum`, `canvas_maximum` | Nonnegative decimal strings retaining half points |
| `scale_contract`, `rounding`, `canonical_projected_score` | Explicit conversion, distinct from academic policy |
| `score`, `score_units=CANVAS_POINTS`, `feedback` | Exact accepted points and newline-normalized feedback |

Supported printed forms are **CT-A/B → 32**, **C-A/B/C/D → 40** and
**AD-A/B/C/D → 48**. Unknown aliases or mismatched form digests hold.
`grass_exam_raw_to_canvas100_v1` requires maximum 100 and `NEAREST_WHOLE_POINT`;
exact rational half-up conversion must match the supplied projection.
`RAW_IDENTITY` requires equal maxima and rounding `NONE`. Conversion does not
select floors, attempts, participation or lowering policy. Teacher-final scores
remain distinct from raw and converted scores. Decimal-string translation creates
a new envelope digest; preserve original hashes and never assert cross-language
canonical parity.

## Required independent comparisons

The trusted caller supplies independently retained `expected_pair_sha256`,
`current_binding`, immutable baseline/current snapshots and exact `target_context`
in the `publish.context` shape. Supplied observations do not establish live
freshness or RELEASE. Exact origin, target, points maximum, visibility and supported
grading context must agree; `require_simple_target` grants no send capability.

**Paper R2 is not Canvas attempt 2.** V1 holds unknown attempts. V2 requires
explicit `target_mode=ROSTER_ASSIGNMENT`, attribution revision/digest, assignment
metadata digest and observed-state digest. Metadata must say
`submission_types == ['on_paper']`; mixed or unknown types hold. Retained
`raw_canvas_observations` preserve baseline/current GET field presence and types.
Observed null, zero and unknown are distinct; booleans are not integer attempts.
Keep `attempt`, `submitted_at` and `workflow_state` unchanged. This does not widen
the capture-v1 schema or authenticate attribution.

Changed target cells, higher current grades, excusals, changed maxima and unknown
or true `teacher_final` protection hold. Separate `score_permission` and
`feedback_permission` claims do not make a pair executable. `NO_SCORE_CHANGE`
requires the current accepted score and every comparison to match; it proves no
feedback delivery. `retain_pair_preview` saves an immutable private receipt,
never a publisher review or EDIT envelope. Identical receipt replay is a no-op;
student content stays outside Git and public dashboards.

## Disabled Canvas wire protocol

`CanvasTarget` binds one canonical HTTPS origin and exact target; this prototype
supports only explicit paper roster/assignment mode. `OriginalGet` retains method,
URL, status and body bytes. Submission queries admit visibility/comments only,
rejecting `read_status` and other additions. Independent hashes establish
integrity, not reader authority, freshness or complete comment pagination.

`build_form_request_spec` binds decision, target-binding, author, channel and
payload digests. Separate forms contain no inferred attempt, posting, status or
excusal changes; score text remains exact and cannot decrease or exceed maximum.
Specifications stay non-executable. Controlled mock HTTP tests prove serialization,
not classroom authority. Supplied-data readback cannot establish live visibility.

### Exact comment text and timestamp side effects

Reject surrounding characters removed by Canvas's Ruby `String#strip`, including
ASCII whitespace/NUL; preserve accepted text verbatim. Submission metadata stays
bound. `comment_metadata_sha256` excludes only `updated_at`/`posted_at`, retaining
their raw presence and values. Missing, malformed or backward transitions hold;
existing posting times cannot change/disappear. Null may become a posting time
only under observed automatic posting inside the update interval.

Rebuild changed observation encodings from original pinned GET bytes. A new
comment requires a response-linked ID, exact author/body and unchanged protected
state. Lost responses permit qualified `OBSERVED_APPLIED`, never retry permission.

## Existing interfaces and remaining live connection

The existing score `Publisher.prepare/confirm/reconcile` has durable uncertainty
and sends no feedback through that lane. The separate
`prepare_comment/confirm_comment/reconcile_comment` lane already implements exact
GET/form transport, durable intent and response-linked readback, requiring its
own `--enable-comments` capability and exact approval. See the
[comment workflow](sdm-gradebook-workflow.md#separately-reviewed-student-comments).
Neither lane automatically connects the accepted-pair prototype.

Use the [canonical capture/PIN authority](grass-capture-contract.md): exact Canvas
ID/email → Student Info text PIN. Hold conflicts; never infer identities from names.
Academic suggestions, teacher decisions and Canvas observations remain separate.

## Validation

Run `python -m pytest tests/test_unit1_pair_preview.py tests/test_unit1_delivery_contract.py tests/test_unit1_canvas_protocol.py -v`,
then the repository suite, Ruff and mypy. Fictional fixtures and printed-form
half-point comparison against GrAss `examCanvasStage.projectScore` establish
software behavior, not grading accuracy or release readiness.

## Minimal backend connection still required

`TeacherAuthentication.actor_for_session` supplies DECIDE-only authority.
`WorkflowReleaseBridge` retains its exact fake-transport restriction. Connect the
accepted-pair backend through the existing authorities:

1. Provision assignment-scoped authenticated RELEASE, checking session, expiry,
   revocation and scope; preserve DECIDE-only defaults.
2. Bind the immutable accepted decision, source/policy/result revisions, identity,
   target mode and original observations through a versioned capture/export.
3. Connect existing publisher ledgers and receipts to that decision. Preserve stable
   delivery identity across releases and unresolved-target exclusions. Verified
   replay is a no-op; uncertain work permits GET-only reconciliation.
4. Require fresh permission, enrollment, target, visibility, grade, protection and
   grading-context checks before each send. Preserve higher grades. Report the
   Canvas GET-to-PUT race; do not silently restore drift.
5. Verify score and comment independently, retaining intent/response/readback.
   Require complete prior comment IDs and exact author/body attribution;
   duplicates, old identical text and unknown coverage hold. Preserve consistent
   score/grade null state; a numeric grade disappearing is a conflict.

These are accepted-pair connection requirements, not missing generic publisher
features. The fictional channel seam stays `synthetic_only=true`,
`retry_writes=false`, `student_visibility=NOT_ESTABLISHED`; synthetic
`VERIFIED_APPLIED` or `VERIFIED_UNCHANGED` never verifies a production pair.
