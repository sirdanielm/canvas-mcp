# Goals and verified status

Checkpoint: October 14, 2026. These are dated aggregate results, not a live monitor
or a new permission to grade or publish. Detailed identities, source links,
approvals and delivery receipts stay in the private authenticated workbench.

## Priorities

1. Reliable grades and useful teacher-reviewed score-plus-feedback pairs.
2. Dependable Canvas → protected GET → preserved EDIT → reviewed Canvas sync,
   with higher existing grades protected and score/feedback verified separately.
3. A durable workbench that shows each purpose, owner, evidence, decision,
   blocker, next action and completion proof without reconstructing chat history.
4. Evidence-first Unit 2 work: inventory originals and literal answers, bind issued
   forms/keys, seal the scoring policy, then review bounded proposals. Unit 2
   grader/provider integration remains a proposal rather than an active publisher.

The on-demand Python/Codex Unit 2 helper exists outside this repository. Its
numeric policy remains **UNSEALED**; the whole-test 50/50 MC/FRQ split is a proposal.
Use the [central Unit 2 contract](https://github.com/sirdanielm/GrAss/blob/main/docs/UNIT2_TEST_GRADING.md)
for policy decisions and real-packet validation before considering publisher
adoption. Documentation and helper availability grant no automatic grading,
paid-call, scheduling or Canvas-write authority.

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

## Gradebook and repository state

The last finalized GET-only refresh covered 173 populated student keys across two
courses and 24 assignment keys per course. Complete native readback preserved EDIT
grades, formulas, feedback notes and the original `_Sync!B2` baselines. The local
GET-only worker and institutional-account workbook menu were verified at the
operational checkpoint. Current liveness still requires a fresh matching READY
heartbeat; the Mac must remain awake, online and authenticated.

Public `main` includes the existing guarded score/comment publishers and recovery
paths. [PR #24](https://github.com/sirdanielm/canvas-mcp/pull/24) holds the reviewed
public GET-only/native-review implementation; at this checkpoint it is an open
draft, not a merged or newly deployed release. The operational checkout retains
private source overlays and live bindings. Primary main was clean and matched
GitHub; this does not imply the operational checkout is fully synchronized.

## Next work and ownership

- Resolve the three historical comment histories and seven source/identity holds
  through their evidence owners. Do not resend or manufacture missing evidence.
- Promote the reviewed GET-only source through the repository's validation/review
  workflow, then separately reconcile private installed overlays and verify their
  source bindings before activation.
- Continue the durable workbench and Unit 2 evidence/policy work in
  [LocalGrAss](https://github.com/sirdanielm/LocalGrAss). Canvas owns exact target
  resolution, observations, publisher gates and installed Canvas bindings.

The older accepted-pair/fake-release prototype remains separately unconnected;
bounded local Unit 1 delivery does not activate that general bridge. See the
[Unit 1 contract](unit1-pair-preview-contract.md), [gradebook workflow](sdm-gradebook-workflow.md)
and [integration boundaries](grass-workflow-integration.md).
