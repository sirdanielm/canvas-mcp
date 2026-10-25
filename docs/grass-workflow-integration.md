# GrAss integration and authority boundaries

Canvas submissions and teacher-folder/paper evidence feed saved results and
reviewable proposals. Reuse valid evidence and results before commissioning
another read. Ordinary participation drafts and authenticated accepted tests
have different staging requirements; both retain exact source and target
bindings. The [goals and methods](goals-and-status.md#grading-flow) define those
routes, and the [current agenda](goals-and-status.md#next-work-and-ownership)
owns next work.

## Ownership

| Owner | Responsibility |
| --- | --- |
| Canvas MCP | Authenticated observations, permanent PIN source, exact identity/attempt targeting, protected GET/EDIT integrity, local execution, separately gated Canvas score/comment transport and readback |
| sdmGrAss | Assignment-grader engines, participation/profile policies and fleet lifecycle |
| GrAss | Academic policy, original paper/question evidence, saved academic results and proposal exports |
| LocalGrAss | Shared import/QC and review workbench, source-bound drafts, immutable revisions and authenticated final decisions |
| d0t | Cross-repository coordination, bounded work orders and the shared status hub |

LocalGrAss maintains the canonical
[architecture](https://github.com/sirdanielm/LocalGrAss/blob/main/docs/GRASS_GREENFIELD_ARCHITECTURE_CONTRACT.md).
Each repository retains its own action gates and installation boundaries.

## Implemented boundaries

The GET-only worker refreshes protected observations while preserving EDIT
scores, formulas, notes and original Sync baselines. New Canvas identities or
assignments require a reviewed append plan; a full-sync operation is not a repair
for GET/EDIT shape differences. Use the [gradebook workflow](sdm-gradebook-workflow.md)
and [worker recovery](sdm-gradebook-worker.md).

GrAss's protected **Grader Proposals** importer preserves teacher-owned review
fields. The authenticated [native EDIT composition](teacher-edit-transfer.md)
separately connects an admitted Unit 1 result and genuine teacher decision to
one exact preserved destination. This transfer is source-accepted and has a
retained one-case local qualification. It does not automatically connect every
proposal inbox record or authorize Canvas delivery.

The ordinary participation receiver uses the existing owner, workbook lock and
history to stage eligible UNAPPROVED score proposals before final approval.
Its newer provider/current-attempt path is a qualified private local overlay
pending portable publication. Analysis stays private and outbound participation
policy is score-only. Refer to the [capability table](goals-and-status.md#source-and-installed-capability)
before treating a local overlay as maintained or installed source.

The older [accepted-pair preview and RELEASE contract](unit1-pair-preview-contract.md)
remains offline and unconnected. Existing publishers do not authenticate a
teacher decision or complete that prototype by themselves.

## Common handoff requirements

1. **Admit the evidence.** Bind original bytes/pages, producer membership, issued
   form, question/rubric policy, exact identity, assignment and actual attempt.
   Missing or conflicting context holds; a numeric zero is an observed value.
2. **Review and retain.** Preserve a revision-bound proposal and reasons. Ordinary
   participation may enter EDIT as UNAPPROVED. An accepted test transfer requires
   authenticated acceptance of its exact score and full feedback. Saving,
   source confirmation, acceptance and publication approval remain distinct.
3. **Preserve the destination.** Recheck current target and complete native
   preimage. Protect higher grades, teacher content and original baselines.
   Exact reviewed exceptions apply only to their bound case; matching hashes
   and caller-created actor flags establish no human authority.
4. **Authorize delivery separately.** Compare current EDIT with Canvas and obtain
   the exact final approval required for each outbound channel. Retain durable
   intent before transport; a lost response enters reconciliation, not retry.
5. **Verify each channel.** Independently confirm score and, when authorized,
   comment author/body and retained history. Score parity does not prove feedback
   delivery. Preserve source, result, policy, decision and operation references.

Reuse existing exact human authorization while its scope and substantive
bindings still match. Routine progress under that bounded scope does not require
another project-level confirmation. This does not create teacher acceptance,
renew paid authority, remove a mandatory tool/platform confirmation or clear a
denied/uncertain operation. Ordinary drafts remain UNAPPROVED and score-only;
accepted-test transfer and Canvas delivery retain their distinct gates.

The newest import/QC attempt remains authoritative when held, failed or
interrupted. Its execution completion is separate from its diagnostic verdict;
an older clean receipt cannot clear a newer hold.

## Remaining work

Promote portable local improvements through one reviewed source lane, keeping
private owner bindings and runtime dependencies out of public commits. New
academic cases still require their source owner's admission, mapping and review;
bounded qualification does not activate unattended staging or broad rollout.
Broader accepted-pair RELEASE integration and Unit 2 provider/policy qualification
remain separate owner tasks. Use the existing capture port, journal and publishers;
do not add another roster, approval ledger or scheduler to duplicate them.

Use the [current agenda](goals-and-status.md#next-work-and-ownership) and
[restart sequence](teacher-edit-transfer.md#activation-agenda-and-restart-sequence)
from the first unfinished gate. Completed canaries are not replayed. Unknown
historical sends use existing no-write reconciliation only.

Originals, crosswalks, source links and detailed receipts stay private. Follow the
[permanent PIN policy](STUDENT-PIN-POLICY.md) for authorized local copies. Earlier
operational counts remain in [dated history](https://github.com/sirdanielm/canvas-mcp/blob/16b06b5151c3595b043cb300e963b7de448ca738/docs/grass-workflow-integration.md),
not in the current task queue. Documentation changes grant no grading, paid-call,
service or Canvas-write authority.
