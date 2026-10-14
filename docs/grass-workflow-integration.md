# GrAss integration and authority boundaries

The goal is a usable chain from original evidence to teacher-approved final
score/feedback pairs, followed by independent Canvas verification. The current
[goals and status](goals-and-status.md) distinguishes maintained source, installed
tools, completed bounded work and remaining holds. Passing tests, a saved draft
or a successful request establishes only its own stage.

## Ownership

| Repository | Responsibility |
| --- | --- |
| Canvas MCP | Authenticated Canvas observations, the gradebook mirror and permanent PIN source, target preflight, separately gated score/comment transport and readback |
| sdmGrAss | Grader runtime, lifecycle controls, desktop imports and diagnostic QC |
| GrAss | Academic policy, original paper/question evidence, saved results and proposal exports |
| LocalGrAss | Local review experience, durable drafts, immutable revisions and authenticated final decisions |

LocalGrAss maintains the canonical [architecture contract](https://github.com/sirdanielm/LocalGrAss/blob/main/docs/GRASS_GREENFIELD_ARCHITECTURE_CONTRACT.md)
and production connection plans. Each repository retains its authority and
installation boundaries.
Quinn and local AI are optional future adapters.

## What is usable now

The installed gradebook worker supports explicit GET-only requests. A verified
refresh establishes captured Canvas observations and preservation of EDIT
fields; it does not approve proposals or publish feedback notes. A fresh GET can
contain students or assignments absent from EDIT. That coverage difference
requires a separately reviewed append plan, with preserved physical axes and
baselines. See the [gradebook workflow](sdm-gradebook-workflow.md) and
[worker runbook](sdm-gradebook-worker.md).

A bounded, authenticated Unit 1 workflow has been exercised in the local
installation with verified scores, full-feedback delivery and independent
readback. Historical feedback and missing-source holds remain separate. That
authorized scope grants no general release authority; its operational adapters
are not all published in Git.

The public [Unit 1 preview and wire contract](unit1-pair-preview-contract.md)
remains an offline contract. General policy/source admission, an accepted-pair
exporter and authenticated release connections require their own implementation
and qualification. The standalone Canvas publishers do not establish teacher
consent or connect those upstream stages automatically.

## One approved handoff

1. **Admit the evidence.** Bind original bytes/pages, issued form, rubric,
   academic policy, producer membership and exact student/assignment identity.
   Canvas point totals and participation policies require explicit academic
   authority. Missing context is a hold.
2. **Review the complete pair.** Show the original paper beside its question,
   rubric, proposed points, reason and editable full feedback. Question edits
   roll up to one final assignment decision. Save drafts and Hold reasons
   against the exact revision; unsaved edits are not durable. Source confirmation,
   saving and acceptance are distinct.
3. **Approve an exact scope.** Authenticate the teacher decision and separately
   authorize release of its targets, score/body vector and validity window.
   Caller-created actor objects, copied hashes and confirmation tokens do not
   establish human approval. Recheck source and authority before dispatch.
4. **Preflight and send separately.** Use fresh target, permission, enrollment,
   protection and attempt observations. Preserve higher grades and existing
   comments. Record immutable plans and durable send intent before transport.
   A lost response enters reconciliation; it never authorizes a resend.
5. **Verify each channel.** A score match does not establish feedback delivery.
   Verify the exact score independently from comment author, body and retained
   history. Preserve source, result, policy, identity, decision, operation and
   readback references through restarts.

The newest desktop import/QC attempt remains authoritative when held, failed or
interrupted. Read its aggregate status before older results. QC completion
authorizes no grading or publication; no automatic Codex hook is implied.

## Remaining integration

Connect real policy and source providers to the existing
[receipt/PIN capture port](grass-capture-contract.md) and durable review journal.
Qualify original-page ownership and legibility, exact saved decisions, scoped
release and score/comment recovery as one execution path. A restored database
or quarantined worker remains held until evidence stores, exclusive ownership
and current authority are verified. Keep archive admission and optional AI
stages separate from classroom decisions.

Use the [permanent PIN policy](STUDENT-PIN-POLICY.md) for authorized local copies.
Originals, crosswalks, student records, credentials and detailed receipts stay
outside Git and the website tree. Public reports contain aggregate findings.

## Historical evidence

The complete earlier guide is retained at immutable revision
[`d0794b2`](https://github.com/sirdanielm/canvas-mcp/blob/d0794b247df2b865150c4805d816b9075768ae92/docs/grass-workflow-integration.md),
including the [October 1 connection checkpoint](https://github.com/sirdanielm/canvas-mcp/blob/d0794b247df2b865150c4805d816b9075768ae92/docs/grass-workflow-integration.md#connection-checkpoint--october-1-2026)
and [October 2 paper-review coordination](https://github.com/sirdanielm/canvas-mcp/blob/d0794b247df2b865150c4805d816b9075768ae92/docs/grass-workflow-integration.md#paper-review-dashboard-coordination--october-2-2026).
Those dated receipts do not describe current permissions or readiness.
