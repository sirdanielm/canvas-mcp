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

`build_pair_preview(pair, ...)` expects `kind=grass_unit1_accepted_pair_v1` and
integer `schema_version=1`. This is a proposed interoperability format; a real
accepted-pair exporter is not yet connected.

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
Canvas attempt 2.** Independently supplied `canvas_attempt` and
`canvas_submitted_at` must match both retained snapshots before this score becomes
a preview candidate. Unknown attempt, changed target cell, higher current score,
excused target, changed grading maximum or unknown/true `teacher_final` protection
holds. Separate `score_permission` and `feedback_permission` claims are retained
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
3. Canvas resolves exact identity and paper-to-Canvas attempt mapping, fresh exact
   assignment visibility/UI parity and teacher-final protection.
4. Connect scoped, authenticated RELEASE and reviewed independent score/comment
   transport, durable uncertainty and readback; only then request a tiny live pilot.

GENERAL TESTING is the existing Sheet canary, not automatic Canvas-write approval.
No legacy reader credential handoff, publication gate or runtime restart is chosen
by this prototype.

## Validation

Run `python -m pytest tests/test_unit1_pair_preview.py -v` in the repository dev
environment, then its complete Python suite, Ruff and mypy. Fixtures are fictional.
The exact source canary also compares supported printed-form half-point examples
against GrAss's current native `examCanvasStage.projectScore`. Retained validation
counts and remaining limits belong in the local checkpoint, not live readiness.
