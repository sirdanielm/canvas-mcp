# Goals and status

Direction updated October 17, 2026; delivery aggregates retain their October 14
capture date. The October 17 qualification is dated separately below. This is not
a live monitor or new permission to grade or publish.
Detailed identities, source links, approvals and delivery receipts stay in the
private authenticated workbench.

## Reviewed source acceptance — October 17

[PR29](https://github.com/sirdanielm/canvas-mcp/pull/29) merged as
`fee655db516a936cbe4efb34452954e99d962614`, from reviewed head
`a75ed0d4a1a9d5459b605679eaf13072699df92e`. The merged and reviewed trees
match. Both independent code reviews cleared the unchanged implementation.
The configured offline suite passed 3,471 tests with 21 optional skips and no
failures/errors; exact-head hosted Python, code-API, confirmation and security
checks passed. Ruff and mypy (91 source files) passed.

The reviewed authentication/preservation followup is now source-accepted:
[LocalGrAss PR46](https://github.com/sirdanielm/LocalGrAss/pull/46), head
`32f7283adb7b7cfed20926ccc985d366a7ca7806`, merged as `02021af30f2c0e3d48ea798c978b9a80e2f81119`;
[Canvas PR31](https://github.com/sirdanielm/canvas-mcp/pull/31), head
`f164e5535911d098c1ba7f801a5388401965e255`, merged as
`eac0e7c19c1871f336f2c02135b51d5fe97f315b`. It adds the trusted-host application review alternative
and [exact operator-owned native preservation](teacher-edit-preservation.md).
The validated text-PIN serialization repair retains canonical identity holds;
the native same-decision repair prevents duplicate marked feedback after a fresh
exact permit. The final configured Canvas suite passed 3,508 tests with 21
optional skips; Ruff and mypy (91 source files) passed. Final Domain validation:
1,609 run, 1,599 passed, ten optional skips; tracked-file publication guard and final integration review passed. Hosted checks: all exact-head workflows passed, including Python 3.11/3.12/3.13, code-API build/tests, confirmation proofs, lint/types and security.

These are source acceptance and deterministic fictional software checks.
Existing native grades, custom notes, original baselines, failed reads and
uncertain history remain protected. Retain genuine exact human approval and
current authenticated acceptance; do not repeat valid approval because source
merged. Installation and the separately owned live case/canary use their own
current receipts. This review performed no service/account action, real EDIT
send or Canvas write. Use the
[current source and restart limits](teacher-edit-transfer.md#reviewed-source-and-restart-limits).

## Dated local qualification — October 17

One genuinely accepted Unit 1 case completed **one native EDIT batch**, independently
verified **26/26**, with zero paid calls and Canvas writes. The old note, prior whole
cell/history, both original Sync B2 baselines and unrelated EDIT content are preserved.
The isolated `release-20261017T1058Z` manifest is
`35861063af3b915146e644512ec2c0e1593a8c7a243917f8ea14a9a50d906add`, using merged PR31/46 heads
Canvas `f164e5535911d098c1ba7f801a5388401965e255` and Domain
`32f7283adb7b7cfed20926ccc985d366a7ca7806`. Private owner receipts retain exact evidence.
This qualifies one case and that isolated runtime; global rollout is separate.
The completed plan must not be replayed. The October 17 source reconciliation
retained operational main `16b06b5`, local edits and original recovery preimages.
It did not restart services or advance an installed release.

The local overlay qualified read startup offline with 14 tools registered,
deferring optional owner-factory checks to the action boundary. The original sealed writer
configuration pin remains held. That startup repair is local; this source/docs
publication does not install it or establish shared-service liveness.

## Grading flow

Preserve two intake lanes: **Canvas submissions** and **teacher-folder/paper
evidence**. Both retain exact source, identity, assignment, form and attempt
bindings. A paper reassessment label never supplies a Canvas attempt number.
Reuse valid saved observations and results before commissioning another read.

```text
Canvas submissions ──────┐
Teacher folders/papers ──┴─> preserved evidence -> saved result
                            -> score + feedback proposals
                            -> local QC/review -> Grader Proposals
                            -> exact teacher decision -> central EDIT
                            -> separate Canvas delivery -> independent readback
```

This is the intended complete path, with distinct implementation boundaries.
GrAss's protected proposal importer is implemented; the general revision-bound
teacher-decision-to-EDIT transfer remains a
[separate integration](https://github.com/sirdanielm/GrAss/blob/main/docs/CENTRAL_GRADE_HANDOFF.md#teacher-decision-to-edit-remaining-integration).
The [authenticated native transfer composition](teacher-edit-transfer.md) joins
LocalGrAss teacher/source authority to exact selection, destination preflight,
one-shot local EDIT execution and semantic readback. The optional authenticated
`LocalEditApplication`, Canvas `build_application` factory and immutable runtime
admission are implemented and tested with fictional records and controlled
transports. Staging defaults to off; configuration/runtime checks create no
account, database, client or teacher decision.

The typed Unit 1 adapter now preserves independently verified owner results,
their accepted per-question attempt/mastery policy and authenticated teacher
corrections in `FORM_POINTS`. An exact section and explicit central mapping are
required: same-maximum `RAW_IDENTITY`, or the reviewed Unit 1 100-point,
whole-percent `ROUND_HALF_UP` profile bound to its exact form, source maximum and
existing policy receipt. No score conversion is inferred. Literal null Canvas
attempts are retained for observed paper-only work without inventing zero.
Every real canary requires a currently admitted source and genuine teacher
acceptance. An existing advisory pair or learner selection does not supply that
acceptance. Generic fictional scoring and held results remain ineligible.
Source, installed bindings,
authenticated acceptance and native canary readback retain separate evidence.
Score and full feedback derive from the same reviewed result but retain separate
release permissions, transport state and independent destination verification.

## Priorities

1. Reliable grades and useful teacher-reviewed score-plus-feedback pairs.
2. Dependable Canvas → protected GET → preserved EDIT → reviewed Canvas sync,
   with higher existing grades protected and score/feedback verified separately.
3. A durable workbench that shows each purpose, owner, evidence, decision,
   blocker, next action and completion proof without reconstructing chat history.
4. Evidence-first Unit 2 work: inventory originals and literal answers, bind issued
   forms/keys and the sealed R1 policy, then review bounded proposals. Keep R2
   policy questions and grader/provider integration held separately.

The on-demand Python/Codex Unit 2 helper exists outside this repository. Its
[domain contract](https://github.com/sirdanielm/GrAss/blob/main/docs/UNIT2_TEST_GRADING.md)
records the adopted point allocation, sealed R1 rubric and supervised-pilot
mechanics. Real handwriting accuracy and classroom throughput remain unverified;
R2 eligibility/selection and automatic crop/review work remain separate limits.
Use that maintained contract rather than duplicating policy here. Documentation
and helper availability grant no automatic grading, paid-call, scheduling or
Canvas-write authority.

## Unit 1 outcome

| Result | Verified aggregate |
| --- | --- |
| Approved scores confirmed | 166: 41 new verified writes and 125 existing/higher no-ops |
| Full feedback bodies confirmed | 163: 72 new verified writes and 91 exact existing no-ops |
| Higher existing scores preserved | 13, including 12 fractional raw values |
| Historical comment holds | 3: current absence was observed, but original execution history is unavailable |
| Source/identity holds | 7: four missing-source records, one cut-off page and two identity joins |

Scores and feedback use separate publication/readback evidence. Native GET/EDIT
point parity alone does not prove feedback delivery. Historical uncertain sends
require reconciliation of retained execution evidence; absence today is not
permission to replay an append-only comment.

Whole-percent presentation applies only to the Unit 1 final test. Preserve higher
existing raw grades even when their display rounds to an integer percentage.
A source or identity hold is unresolved work, not a zero, a completed grade or
permission to guess a student match.

## Dated gradebook evidence

The October 14 finalized GET-only refresh covered 173 populated student keys
across two courses and 24 assignment keys per course. Complete native readback preserved EDIT
grades, formulas, feedback notes and the original `_Sync!B2` baselines. The local
GET-only worker and institutional-account workbook menu were verified at the
operational checkpoint. Current liveness still requires a fresh matching READY
heartbeat; the Mac must remain awake, online and authenticated.

Maintained source includes separately guarded score/comment publishers and
recovery paths. Source, installed worker/menu bindings and operational liveness
require independent verification. Read
[repository maintenance](repository-maintenance.md) for safe synchronization;
publishing a branch does not install its code or reconcile private overlays.

## Next work and ownership

- Resolve the three historical comment histories and seven source/identity holds
  through their evidence owners. Do not resend or manufacture missing evidence.
- Retain the checkout recovery receipt and completed case evidence; no replay.
  Keep the sealed-writer pin hold. Read startup has offline qualification only;
  coordinate any fresh service connection with its current operator.
  Other cases follow the [activation agenda](teacher-edit-transfer.md#activation-agenda-and-restart-sequence)
  from their first unfinished gate, including genuine acceptance and exact grade/note
  preservation. Broader staging, paid calls and Canvas writes remain off.
- Keep GET-only source and installed overlays aligned through reviewed promotion
  and exact adopted-source readback before any activation.
- Continue the durable workbench and Unit 2 evidence/policy work in
  [LocalGrAss](https://github.com/sirdanielm/LocalGrAss). Canvas owns exact target
  resolution, observations, publisher gates and installed Canvas bindings.

The older accepted-pair/fake-release prototype remains separately unconnected;
bounded local Unit 1 delivery does not activate that general bridge. See the
[Unit 1 contract](unit1-pair-preview-contract.md), [gradebook workflow](sdm-gradebook-workflow.md)
and [integration boundaries](grass-workflow-integration.md).
