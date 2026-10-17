# Goals and status

Direction updated October 16, 2026; the aggregate operational evidence below is
from October 14. This is not a live monitor or new permission to grade or publish.
Detailed identities, source links, approvals and delivery receipts stay in the
private authenticated workbench.

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
one-shot local EDIT execution and semantic readback for generic Canvas-capture
results with explicit native-point bindings. This lane is qualified with real
local authentication and mocked external transports. Installed application
bindings and a live canary remain separate qualifications; held paper/form
results remain ineligible. Score and full feedback derive
from the same reviewed result but retain separate release permissions, transport
state and independent destination verification.

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
- Complete and review the exact teacher-decision-to-EDIT handoff, preserving
  existing teacher values, score units, source/result revisions and repeat-safe
  reconciliation. Run the domain-owned fleet canary before unattended staging.
- Keep GET-only source and installed overlays aligned through reviewed promotion
  and exact adopted-source readback before any activation.
- Continue the durable workbench and Unit 2 evidence/policy work in
  [LocalGrAss](https://github.com/sirdanielm/LocalGrAss). Canvas owns exact target
  resolution, observations, publisher gates and installed Canvas bindings.

The older accepted-pair/fake-release prototype remains separately unconnected;
bounded local Unit 1 delivery does not activate that general bridge. See the
[Unit 1 contract](unit1-pair-preview-contract.md), [gradebook workflow](sdm-gradebook-workflow.md)
and [integration boundaries](grass-workflow-integration.md).
