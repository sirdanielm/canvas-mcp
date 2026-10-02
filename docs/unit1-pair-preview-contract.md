# Unit 1 accepted-pair publication preview

This is an **unregistered offline prototype**, retained on the reviewed worktree
branch. It is not deployed, authenticated acceptance, a new publisher, or a
working transfer into Edit. `canvas_mcp.gradebook.unit1_preview` performs no
Canvas/Sheet/model calls and exports no write-ready edit envelope or confirmation
token. Both delivery channels remain `NOT_SENT`; publication and pair verification
remain false on every result.

## One handoff, distinct authorities

GrAss owns original-source/result validation and the accepted Unit 1 attempt,
mastery and feedback policy. Its policy-aware review export is a candidate,
not teacher acceptance. LocalGrAss owns the future authenticated, current
teacher-decision export. Canvas owns the permanent identity join, exact remote
target/attempt, publication preflight and eventual independent delivery readback.
Reuse these authorities; do not create another editable approval table or give
grader copies Canvas credentials.

The existing `LocalWorkflow.process` scorer is fictional; do not pass real Unit 1
records through it. The generic case explanation's `actor_authentication` remains
`NOT_IMPLEMENTED`. The local teacher-review layer separately retains account,
draft and immutable acceptance provenance; an integration must verify those
records and current decision/result/academic heads. A JSON `accepted: true`, an
ActorContext, or a hash copied from the pending file does not prove human consent.
The current release bridge remains FakeTransport-only.

## Proposed private envelope

`build_pair_preview(pair, ...)` accepts the original
`kind=grass_unit1_accepted_pair_v1`, integer `schema_version=1` for attempt-bound
checks, or the additive `grass_unit1_accepted_pair_v2`, integer `schema_version=2`
for explicit paper roster/assignment binding. These are proposed interoperability
formats; a real accepted-pair exporter is not yet connected.

| Fields | Meaning |
| --- | --- |
| `case_key`, `academic_assignment_id`, `decision_id` | Exact retained local case, academic assignment and accepted teacher decision; preserve owner tokens |
| `source_revision`, `result_revision`, `policy_revision`, `identity_revision`, `binding_revision` | Opaque substantive owner revisions, preserved verbatim; for example `identity-<digest>` is not stripped |
| `source_sha256`, `result_sha256`, `policy_sha256`, `identity_sha256`, `binding_sha256`, `form_sha256` | Separate exact content digests supplied by the respective owner; never invent hash/revision equivalence |
| `origin`, `course_id`, `canvas_assignment_id`, `canvas_user_id`, `pin`, `section_id`, `form_id`, `paper_attempt` | Exact independently resolved target and printed packet; four-digit PIN and Canvas IDs remain text |
| `raw_score`, `raw_maximum`, `canvas_maximum` | Nonnegative decimal strings, preserving half points; no float coercion into LocalGrAss canonical JSON |
| `scale_contract`, `rounding`, `canonical_projected_score` | Explicit bound native conversion, retained separately from attempt/mastery policy and teacher-final score |
| `score`, `score_units=CANVAS_POINTS`, `feedback` | Exact accepted final Canvas points and newline-normalized feedback; teacher overrides are preserved |

The prototype supports only the current exact printed forms: **CT-A/B → 32**,
**C-A/B/C/D → 40**, **AD-A/B/C/D → 48**. Unknown/alias forms hold. Form identity
and digest must also match the independently retained current binding. It never
selects a form from a course label.

`grass_exam_raw_to_canvas100_v1` requires Canvas maximum `100` and
`NEAREST_WHOLE_POINT`; `RAW_IDENTITY` requires matching raw/Canvas maxima and
rounding `NONE`. The decimal conversion uses exact rational half-up arithmetic
and checks the supplied canonical projected value. A disagreement with the owner
conversion is held. This is scale conformance, not a replacement for the native
attempt/mastery/floor policy. Raw earned points, converted raw score and accepted
teacher-final Canvas score remain three distinct values. No new lowering,
floor, participation or best-attempt policy is selected.

Retain the original external file/receipt hash unchanged. Translating JSON numbers
to schema-defined decimal strings creates a **new envelope with a new digest**.
Do not claim JavaScript, Canvas model and LocalGrAss canonical hash parity.

## Required independent comparisons

The trusted caller supplies `expected_pair_sha256` from an independently retained
owner record and `current_binding` for every substantive scope/revision/digest.
These inputs establish comparison integrity only. Authentication and scoped
RELEASE remain unconnected and are explicit release holds.

The caller also supplies immutable baseline/current normalized snapshots and
optionally a retained exact-assignment/submission `target_context` in the existing
`publish.context` shape. A current snapshot in this function means a supplied
observation, not a fresh live GET. Exact origin/course/assignment/student,
published points target, maximum, visible submission and supported grading context
must agree. The prototype reuses `require_simple_target` without enabling it to
send. Missing exact context or disagreement with the course mirror holds. The
historical course-versus-assignment visibility discrepancy and Canvas UI parity
remain owner issues; local tests do not resolve them.

Paper review remains available when Canvas attempt is unknown. **Paper R2 is not
Canvas attempt 2.** The original `grass_unit1_accepted_pair_v1` retains its
attempt-bound checks. The additive `grass_unit1_accepted_pair_v2` envelope supports
only explicit `target_mode=ROSTER_ASSIGNMENT`, matching the shared architecture
contract for paper assessments. It requires independently retained attribution
revision/digest, exact assignment metadata digest and observed Canvas-state digest
in `current_binding`; a candidate cannot select the mode by itself. Exact assignment
metadata must say `submission_types == ['on_paper']`. Mixed/unknown types hold.

V2 preserves `attempt`, `submitted_at` and `workflow_state` exactly, including an
observed null attempt or zero. `raw_canvas_observations` must carry the retained
original exact-target baseline and current GET objects. The parser requires raw
field presence and valid types before comparing normalized cells; normalization
alone fills missing fields with null and cannot prove observed nulls. Missing raw
evidence holds. Bools do not equal integer attempts. Independently supplied
attempt/timestamp and both snapshot states must agree with the retained binding. The attribution digest is
provenance integrity, not authenticated teacher confirmation: acceptance and
RELEASE remain explicit holds. This does not widen the current capture v1 schema.
Unpublished or invisible paper assignments remain held, just as other targets do.
Attempt-bound mode still holds an unknown attempt. Any mode holds a changed target
cell, higher current score, excusal, changed grading maximum or unknown/true
`teacher_final` protection. Separate `score_permission` and `feedback_permission` claims are retained
independently; neither claim makes the pair executable.

An unchanged target score is `NO_SCORE_CHANGE` only when the current Canvas value
equals the accepted score and all comparisons pass. A changed Canvas cell is held
even if the accepted score equals the original baseline. A score match never
proves feedback delivery: feedback stays `NOT_SENT`, and `verified_pair=false`.

`retain_pair_preview` writes one immutable private **receipt** through the existing
Store, not a Publisher `review` or Edit file. Replay of the exact receipt is a
no-op. Preview data contains private identifiers and feedback and must stay
outside Git/logs/public dashboards. Use aggregate status in unauthenticated
Tools Home; source/feedback review requires the private authenticated owner path.

## Existing interfaces and remaining live connection

The existing `preview_gradebook_changes` service reads live Canvas; this prototype
calls deterministic comparison only with supplied observations. Existing
`Publisher.prepare/confirm/reconcile` supports score/excusal and durable
uncertainty, but sends **no feedback**. `publish.context` and
`matches_proposal` do not verify a comment. There is no current combined pair
readback CLI to invoke or claim as deployed.

The existing receipt/PIN capture port in [grass-capture-contract.md](grass-capture-contract.md)
is the canonical identity path: Canvas ID → exact email → Student Info text PIN,
through the shared private binding. A score snapshot without email and a source
row without Canvas ID is not enough for that join. Hold missing/conflicting
identities; do not fuzzy-match names or invent IDs. Existing score, replayed
advisory suggestion, accepted teacher final and Canvas observation are separate
records.

Future feedback readback must use a reviewed GET-only exact-submission adapter
with comments included. Bind origin/course/assignment/student/attempt and the
expected decision, comment author, remote comment ID and exact normalized body.
Compare to a pre-send comment-ID baseline so an old identical comment cannot
stand in for a newly delivered decision. Verify score and comment independently.
The current score ledger already leaves uncertain sends locked and reconciles
with GET only; the future comment channel needs its own durable send-intent,
uncertainty and readback receipt. Never resend uncertain comments automatically.

Remaining sequence:

1. GrAss completes and validates the current policy-aware score/feedback export.
2. LocalGrAss connects actual private evidence review and an authenticated current
   teacher acceptance export; preserve source/policy/result and original hashes.
3. Canvas resolves exact identity, explicitly supported target mode and actual
   observed submission state, fresh exact assignment visibility/UI parity and
   teacher-final protection. Paper mode does not create an attempt mapping.
4. Connect scoped, authenticated RELEASE and reviewed independent score/comment
   transport, durable uncertainty and readback; only then request a tiny live pilot.

GENERAL TESTING is the existing Sheet canary, not automatic Canvas-write approval.
No legacy reader credential handoff, publication gate or runtime restart is chosen
by this prototype.

## Validation

Run `python -m pytest tests/test_unit1_pair_preview.py tests/test_unit1_delivery_contract.py -v`
in the repository dev environment, then its complete Python suite, Ruff and mypy. Fixtures are fictional.
The exact source canary also compares supported printed-form half-point examples
against GrAss's current native `examCanvasStage.projectScore`. Retained validation
counts and remaining limits belong in the local checkpoint, not live readiness.

## Minimal backend connection still required

The current `TeacherAuthentication.actor_for_session` yields a fresh authenticated
**DECIDE-only** actor. `WorkflowReleaseBridge` rechecks the current saved decision,
proposal, result and accepted academic/evidence dependencies inside every
send-intent transaction, but its simulator enforces the exact fake transport class
and fake case target. The existing Canvas Publisher's confirmation token binds a
reviewed edit request; it does not authenticate a teacher acceptance or RELEASE.
There is no legitimate live transport substitution at either seam today.

Connect the missing backend in this order, reusing current authorities:

1. Extend the existing authenticated account/session seam with an explicitly
   provisioned, assignment-scoped RELEASE capability; preserve DECIDE-only as the
   default. Recheck the account/session, expiry, revocation and scope at action
   time. Never accept a caller-created ActorContext as authentication. No new
   approval table or independent teacher-decision store is needed.
2. Add an immutable versioned target binding linked to the current accepted
   decision and the registered source/identity authority. Declare ATTEMPT_BOUND
   or ROSTER_ASSIGNMENT support explicitly; retain the actual submission state,
   assignment metadata, score scale, teacher-final provenance and their digests.
   Coordinate a versioned capture/export contract with LocalGrAss; reject v1
   receipts that lack required mode semantics instead of silently widening them.
3. Reuse the existing registry transaction and accepted decision/result/academic
   heads when reserving durable delivery components. Store the exact channel
   payload and baseline before send. A production delivery ledger may add tables
   to that same private store; it must not manufacture new approval authority or
   change the synthetic bridge's exact FakeTransport restriction. Exclude the
   wider Canvas origin/course/assignment/student target across decisions and
   local paper attempts while any send outcome is uncertain. A unique stable
   delivery identity binds the accepted decision, target-binding revision, channel
   and exact payload independently of release token, expiry and refreshed preflight.
   Renewing RELEASE resumes that identity: verified replay is a no-op; uncertain
   replay is GET-only and cannot append feedback twice.
4. Admit each real send only through that authenticated release transaction and
   fresh exact GET preflight. Recheck course permission, active roster, target,
   current grade, excusal, teacher-final protection, visibility, publication,
   special grading, closed period, late deductions and current-submission state.
   Preserve higher grades; never publish an unpublished assignment as a side
   effect. Canvas has no general atomic GET-to-PUT grade compare-and-swap, so
   retain and report that race and hold readback drift.
5. Implement separate score and submission-comment channels, using the existing
   configured account and bounded requests. On the exact submission PUT endpoint,
   score sends only `submission[posted_grade]`; comment sends only
   `comment[text_comment]` and `comment[group_comment]=false`. For paper mode omit
   `comment[attempt]`; for supported attempt-bound mode send only its verified
   Canvas attempt. Use Canvas form serialization, never change posting/status,
   and never combine a retryable grade update with an append-only comment.
   [Canvas submission API](https://developerdocs.instructure.com/services/canvas/resources/submissions)
6. Independently GET the exact submission with visibility and submission comments
   after each send. Verify score and feedback separately against retained intent.
   Score readback must recheck target/metadata/protection/state, not just numeric
   equality. A new comment must have a response-linked ID absent from the complete
   pre-send ID baseline, correct author, exact target and exact approved body.
   Unknown comment coverage, old identical comments, duplicates and foreign
   authors hold. Save response and readback receipts durably. A lost response
   permits qualified OBSERVED_APPLIED evidence, not confirmed delivery; recovery
   is GET-only and never automatically resends an uncertain comment.

`unit1_delivery_contract` is the bounded fictional protocol test seam for these
comparisons. It performs no network, persistence or release authentication and
cannot substitute for the connection above. Synthetic verification does not mark
a production pair verified. The real account/role extension, immutable accepted
pair exporter, versioned capture, production ledger and live adapter remain held.

The fictional channel API consists of `build_component_contract` and
`verify_component`. The caller supplies independent expected decision, target
binding and payload digests; the synthetic delivery ID includes the decision,
binding, channel and exact payload, never the release token. Results are always
`synthetic_only=true`, `retry_writes=false`, and
`student_visibility=NOT_ESTABLISHED`. Only response-linked independent readback
can yield synthetic `VERIFIED_APPLIED`; a lost response yields unverified
`OBSERVED_APPLIED` or `UNCERTAIN`. An exact score no-op can be
`VERIFIED_UNCHANGED`, which says nothing about feedback. Explicit
`score_side_effects=CANVAS_POINTS_GRADED` permits narrowly modeled grading state
and valid timezone-aware grading timestamp effects; comment delivery cannot alter
score, grade or submission state. Request-form serialization and a real HTTP port
are not implemented by this module.
