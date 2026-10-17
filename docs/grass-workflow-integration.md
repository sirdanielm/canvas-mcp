# GrAss integration and authority boundaries

The direction is two intake lanes—Canvas submissions and teacher-folder/paper
evidence—producing score and feedback from the same saved result. Local tools
inspect, qualify and stage the pair for teacher review, followed by an exact
central EDIT handoff and separately authorized Canvas delivery/readback. The
[grading flow](goals-and-status.md#grading-flow) records which transitions remain
integration work. The current
[goals and status](goals-and-status.md) distinguishes maintained source, installed
tools, completed bounded work and remaining holds. Passing tests, a saved draft
or a successful request establishes only its own stage.

## Ownership

| Repository | Responsibility |
| --- | --- |
| Canvas MCP | Authenticated Canvas observations, the gradebook mirror and permanent PIN source, target preflight, separately gated score/comment transport and readback |
| sdmGrAss | Assignment-grader engines, profile policy contracts and fleet lifecycle controls |
| GrAss | Academic policy, original paper/question evidence, saved results and proposal exports |
| LocalGrAss | Shared local import/QC tools, review experience, durable drafts, immutable revisions and authenticated final decisions |

LocalGrAss maintains the canonical [architecture contract](https://github.com/sirdanielm/LocalGrAss/blob/main/docs/GRASS_GREENFIELD_ARCHITECTURE_CONTRACT.md)
and production connection plans. Each repository retains its authority and
installation boundaries.
Quinn and local AI are optional future adapters.

## Implemented boundaries

The installed gradebook worker supports explicit GET-only requests. A verified
refresh establishes captured Canvas observations and preservation of EDIT
fields; it does not approve proposals or publish feedback notes. A fresh GET can
contain students or assignments absent from EDIT. That coverage difference
requires a separately reviewed append plan, with preserved physical axes and
baselines. See the [gradebook workflow](sdm-gradebook-workflow.md) and
[worker runbook](sdm-gradebook-worker.md).

A bounded, authenticated Unit 1 workflow has dated local-installation evidence
for scores, full-feedback delivery and independent readback. See the
[October 14 outcome](goals-and-status.md#unit-1-outcome). Historical feedback and
missing-source holds remain separate. That
authorized scope grants no general release authority; its operational adapters
are not all published in Git.

The public [Unit 1 preview and wire contract](unit1-pair-preview-contract.md)
remains an offline contract. General policy/source admission, an accepted-pair
exporter and authenticated release connections require their own qualification.

The source-only `proposal_preview.prepare_preview` consumer projects explicitly
selected GrAss summative and sdmGrAss formative results through the existing
`model.compare_edits` contract and immutable `Store` review artifacts. It creates
no transport, queue, source admission or teacher decision. A trusted owner
revalidates the original request, source, result, rubric, configuration and
identity references; opaque producer IDs and digests are retained verbatim.
The independent binding supplies the exact Canvas origin/target/attempt,
canonical PIN join, actual assignment metadata, assessment floor and teacher
correction/final state. The 25-row resource limit does not broaden that selection.

Every output remains **UNAPPROVED**, with score and comment approval separately
false. Higher grades, excusals, teacher corrections and assessment floors hold
changes. Ordinary held and already-matching results retain their complete pair
for review without edit requests. Edpuzzle is excluded using actual assignment
metadata at selection and retention; its diagnostic references confer no staging
authority. No score conversion or feedback rewrite is inferred. Repeated
substantive previews reuse the existing immutable artifact; only the named
Canvas observation/report timestamps are excluded from comparison identity.
These offline fixtures do not establish installation, browser access, unattended
processing or live delivery. Standalone publishers do not establish consent.

GrAss's [local proposal importer](https://github.com/sirdanielm/GrAss/blob/main/docs/CENTRAL_LOCAL_IMPORTER.md)
reconciles saved results into the protected **Grader Proposals** inbox while
preserving teacher fields and GET/EDIT. It does not transfer a teacher decision
into EDIT. The
[revision-bound transfer contract](https://github.com/sirdanielm/GrAss/blob/main/docs/CENTRAL_GRADE_HANDOFF.md#teacher-decision-to-edit-remaining-integration)
defines that remaining connection. Keep the two intake domains' provenance and
the score/comment channels' release and readback states distinct through it.

## Intended end-to-end handoff

1. **Admit the evidence.** Bind original bytes/pages, issued form, rubric,
   academic policy, producer membership and exact student/assignment identity.
   Canvas point totals and participation policies require explicit academic
   authority. Missing context is a hold.
2. **Review the complete pair.** Show the original paper beside its question,
   rubric, proposed points, reason and editable full feedback. Question edits
   roll up to one final assignment decision. Save drafts and Hold reasons
   against the exact revision; unsaved edits are not durable. Source confirmation,
   saving and acceptance are distinct.
   A transfer into EDIT must bind that exact decision, saved result and selected
   destination, preserving teacher values and holding changed/conflicting targets.
   A repeated transfer with matching content is a no-op. This general transfer
   is a contract to implement, not an existing automatic action.
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

Implement and qualify the teacher-decision-to-EDIT contract using the existing
proposal inbox and publication policy. Test the domain-owned fleet canary before
unattended staging; do not add another roster, approval ledger or publisher.

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
