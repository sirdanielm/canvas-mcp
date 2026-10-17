# Exact teacher decision to local EDIT

`gradebook/teacher_edit_transfer.py` implements an **unregistered, offline
planner and readback classifier** for one exact decision. It prepares no Canvas
operation and executes no Sheets request. The authenticated LocalGrAss
composition below qualifies the generic Canvas-capture/native-point lane in
offline integration tests. Installed application bindings and a live canary
remain separate qualifications.

The [GrAss acceptance contract](https://github.com/sirdanielm/GrAss/blob/main/docs/CENTRAL_GRADE_HANDOFF.md#teacher-decision-to-edit-remaining-integration)
owns academic source/result/policy admission. The existing **Grader Proposals**
inbox remains the review surface, including teacher-owned M:O. This adapter adds
no roster, approval table, publisher, scheduler or retry ledger.

## Source and decision authority

The planner retains the selected evaluation's source key, source/result hashes,
evaluation ID, policy, section, literal four-digit PIN, exact Canvas IDs,
paper attempt, observed Canvas attempt, form, raw score/maximum and bound
consumer proposal/scale. A paper `R1` or `R2` label never supplies a Canvas attempt.

The separate final decision binds the same evaluation, source/result and policy,
a substantive decision revision, explicit final Canvas points/maximum and full
teacher feedback. The raw result and consumer projection are retained; this
module does not rescore or round either. Teacher-final points can differ from
the advisory proposal when that exact decision is authenticated.

`source_check(selected, decision, pin_binding)` is trusted owner configuration,
never MCP input. It must independently assert the current saved evidence,
result/supersession, policy, central identity/assignment/section/attempt and
actual teacher final decision in the existing review surface. An arbitrary
M-column string, `is_final: true`, matching hash or participation approval does
not establish that authority. There is no established M-column acceptance
vocabulary to infer. A held Unit 2 result is ineligible.

The callback must return `None` synchronously and fail closed on changes. It
receives copies, so it cannot mutate the planner's inputs. The shared central
Student Info registry remains the PIN authority; its current registry/roster
hashes and unique PIN-to-Canvas join must be revalidated by the owner.

## Native destination checks

The existing native Edit extractor verifies the original trusted baseline,
bindings, protected GET/Sync structure and exact mapped identity axes. The
transfer additionally checks current course/section, explicit attempt, grading
schema, visible/current grade, excusal and higher-score preservation. Unknown
or changed target state holds the transfer.

The resulting batch changes only one Working score and its note, using the
`userEnteredValue,note` mask. The complete teacher feedback is retained with an
exact selection marker. Existing teacher score conflicts or custom notes hold;
canonical baseline notes are preserved as a prefix. All other cells, helpers,
formats, validations, tabs, GET state, proposal M:O and Sync baselines remain in
the complete expected native readback.

The same decision plus its exact score and full marked feedback produces zero
requests. A score that merely happens to match is not evidence that its feedback
or the decision was transferred. Harmless fetch/report timestamps are excluded
from the substantive selection and target basis.

## Owner integration and interruption

1. Authenticate the source and teacher decision through the domain owner and
   read the native destination/current Canvas target through existing owners.
2. Call `prepare_transfer`. Retain the complete plan with the existing immutable
   `Store.save("review", plan)` and keep its externally pinned digest.
3. At an authorized idle checkpoint, call `revalidate_transfer` with that digest,
   current source/PIN authority and fresh native/target evidence. It recomputes
   the narrow plan and requires the complete destination preimage unchanged.
4. The existing local owner may execute that exact batch once only when separately
   authorized. This pure preflight is not an atomic server-side comparison or
   a transport lock; concurrent workbook use still requires owner coordination.
5. Classify a captured complete native readback using `classify_readback` and the
   pinned digest. Planned output, unchanged preimage and divergence are distinct.
   Every result returns `retry_writes: false`. After an uncertain send, an unchanged
   preimage alone never authorizes replay; reconcile the existing owner's retained
   operation evidence first.

The plan and readback expressly deny score/comment delivery authority and do not
claim Canvas delivery verification. Existing publication policy and publishers
continue to gate score, feedback and exact lowering exceptions independently.
Unknown historical append operations remain held; this module does not examine,
clear or replay them. The existing unapproved participation staging adapter is a
different operation and is not converted into a teacher-final decision here.

The offline tests use fictional records and native fixtures. They verify exact
revision/PIN/attempt and scale handling, source holds, existing teacher content,
full feedback, preservation, repeat no-ops and interruption classification.

## Authenticated LocalGrAss composition

`localgrass_teacher_edit.LocalGrAssEditConnection` joins the existing
LocalGrAss `AuthenticatedDecisionSource` to this planner. The source verifies
the existing teacher session, CSRF, immutable acceptance receipt, current draft
and result/dependency heads, current canonical identity and the actual original
file bytes. It does not turn a proposal flag or browser input into a decision.

The qualified first lane is a generic `COMPUTED` Canvas-capture result with an
explicit `RAW_IDENTITY` point binding. Paper/form-specific results, held Unit 2
totals and unspecified score transforms remain ineligible. Capture, current
Canvas attempt/submission time, assignment and literal PIN must still agree.

`localgrass_edit_owner.LocalGrAssEditOwner` composes that connection with the
existing GET-only `GradebookClient`, fixed-workbook `GoogleSheets`, private
`Store` and `RefreshJournal`. Trusted application configuration supplies these
objects, the existing participation configuration path and its pinned SHA-256,
and the existing workbook binding. No MCP input constructs an owner or callback.
The pinned configuration must resolve to the same registered workbook,
assignment bindings, PIN registry, worker state directory and existing staging
history root. A new output directory cannot replace prior send history.

`prepare()` takes the existing workbook lock, refuses unresolved refresh history,
loads the original trusted baseline from native `_Sync!B2`, reads current source
and destination evidence, and saves one immutable review plan. Native sheet IDs
are normalized before persistence, so save/reopen/revalidate and repeated
preparation retain the same substantive plan, including multi-digit sheet IDs.

`execute(plan_id)` defaults to disabled without network calls or new receipts.
An authorized application can explicitly enable local EDIT staging at an idle
workbook checkpoint. The existing workbook lock spans preflight, the shared
participation lock, durable `SENDING`, one `send_preflighted_batch`, and complete
native readback. It does not use `GoogleSheets.batch`, which performs another
metadata/authentication read after the send checkpoint.

Any retained receipt forces native readback only. Post-send verification and
explicit reconciliation read Sheets without requiring a new Canvas snapshot or
a still-active teacher session. A Canvas outage cannot convert reconciliation
into a new send. Unknown/divergent output remains held; neither owner releases
or replays an uncertain operation. A validated completed operation retains its
historical terminal receipt when later teacher edits change the workbook;
`VERIFIED_HISTORY_RETAINED` reports current drift separately and creates no new
uncertain receipt. The existing refresh lock cannot exclude a human browser
editor, so owner coordination still requires an idle workbook.

Cross-repository qualification is explicit: set `LOCALGRASS_TEST_ROOT` to the
reviewed LocalGrAss source and run the joined tests. They use real authenticated
fictional stores and mocked HTTP transports; default CI skips that external
checkout dependency. No installed service, account, workbook or grading policy
is changed by importing these modules or by a passing fixture run.
