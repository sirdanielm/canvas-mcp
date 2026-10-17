# Exact teacher decision to local EDIT

`gradebook/teacher_edit_transfer.py` implements an **unregistered, offline
planner and readback classifier** for one exact decision. It prepares no Canvas
operation and executes no Sheets request. The authenticated LocalGrAss
composition below exercises the generic Canvas-capture/native-point contract
with fictional records and controlled transports. Source implementation,
installed qualification, production admission and one real local canary are
separate gates; a positive production canary is not established.

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

The first lane's contract requires a generic `COMPUTED` Canvas-capture result
with an explicit `RAW_IDENTITY` point binding. Paper/form-specific results, held
Unit 2 totals and unspecified score transforms remain ineligible. Capture,
current Canvas attempt/submission time, assignment and literal PIN must agree.
The authenticated source takes an explicit `identity_runtime_root` for the
canonical identity implementation; it is distinct from the evidence source root
and must match the existing staging configuration. Neither path is inferred from
request content or the source workspace.

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

## Authenticated application and immutable runtime

The optional LocalGrAss `LocalEditApplication` extends the existing authenticated
review server for one fixed decision, source receipt and section. Browser requests
carry the existing session/CSRF and a single-use preview token; they do not select
an owner, import path or arbitrary target. Preparing rechecks source and session,
and executing consumes the preview before further work. An uncertain response
requires reconciliation of the retained owner operation, never another send.

`localgrass_application.build_application` composes that controller from already
opened `TeacherReview`, `SourceIntake`, Canvas/Sheets clients, `Store` and
`RefreshJournal`. It requires the same registry, existing intake/acceptance rows,
pinned private configuration, original staging history and workbook ownership.
Missing real records hold before owner construction; the factory creates no
schema or acceptance. Staging defaults to `enabled=False`.

The immutable runtime bootstrap supplies a retained `Admission` guard before
imports and on source reentry. It verifies the exact manifest, Python executable,
complete Canvas/domain code closure and external identity-reader dependencies.
Extra files, symlinks or changed pins hold. Admission checks are code-integrity
checks, not a sandbox for malicious trusted code. Application configuration and
bootstrap `--check` modes create no clients, accounts, database or teacher session,
make no network call and leave staging off. A successful check does not establish
an admitted academic case or authorize a local send.

The current generic scorer accepts only `FICTIONAL_EXPLICIT_POINTS_V1`. The
application explicitly rejects fictional policy, including after valid login.
Consequently no admitted generic production result route exists for a real
positive canary. Creating a teacher account or filling acceptance fields cannot
repair that generic scoring gap. The separate typed Unit 1 adapter below reuses
the established owner-result policy. Missing assignment section or
explicit `RAW_IDENTITY` scale also holds; existing participation records cannot
supply those semantics by inference.

## Typed Unit 1 owner-result adapter

`AuthenticatedUnit1DecisionSource` reads one existing
`GRASS_UNIT1_VERIFIED_OWNER_RESULT_V1` result, registered independent paper source
and authenticated teacher acceptance. It retains the accepted
`QUESTION_ATTEMPT_MASTERY_50_50` policy, original form and paper attempt. It creates
no Canvas-capture intake and does not rescore a saved result. The configured
identity runtime is shared by original-source reads and the actual teacher
acceptance checks.

Canvas selects exactly one academic-assignment/track/course/section mapping and
requires explicit `RAW_IDENTITY` with equal form and native maxima. The advisory
total and teacher-final correction remain separate. The actual current Canvas
attempt, including an observed zero for paper-only work, is retained independently
of the paper attempt; later attempt or submission-time changes hold the plan.
Existing higher-grade, custom-note, baseline and complete native preservation
checks still apply.

Trusted application configuration selects `LOCALGRASS_EDIT_UNIT1_APPLICATION_V1`.
It uses the existing fixed-scope fields except `source_root`; `source_receipt_id`
is the registered independent evidence revision. Pass `None` for generic
`SourceIntake`, and supply the already configured review/workflow/paper reader and
the existing Canvas owners. The workflow's explicit identity runtime must match.
No database, academic packet, teacher account or acceptance is created by this
factory. The runtime includes the unchanged pinned native Unit 1 verifier asset.

This source integration is qualified with authenticated fictional fixtures and
controlled native transports. A real advisory pair marked `NOT_RECORDED` for
teacher acceptance remains held. A production canary requires actual current
source/policy/identity admission, reviewed mapping and genuine teacher acceptance.

## Activation agenda and restart sequence

1. **Preserve and inspect.** Record exact source and installed revisions, manifest,
   interpreter and configuration digests, original baseline and operation history.
   Preserve dirty/private work and teacher EDIT scores, notes and formulas. Use one
   destination writer and coordinate an idle browser checkpoint.
2. **Qualify installation and history.** Install only the reviewed code closure
   through its owner; verify the immutable bootstrap with staging off. Resolve
   interpreter drift through reviewed installation rather than replacing a hash
   solely to pass. Inspect existing GET-only status and native queue; require
   current readiness when needed. Use [mode-bound recovery](sdm-gradebook-worker.md#coordination-and-crash-recovery)
   for a preserved request. A possible send permits readback reconciliation only.
   Release a proven pre-SENDING hold only after fixing and reviewing its cause.
3. **Implement real admission.** The domain owner must supply and independently
   validate the production source/policy/result route, or separately implement a
   typed result adapter. Preserve original evidence, exact revisions and academic
   holds. Review the assignment's exact section and native-point semantics. Do
   not relabel fictional policy, infer `RAW_IDENTITY`, manufacture a result or
   convert participation approval into academic acceptance.
4. **Authenticate one accepted case.** Require a current teacher session/CSRF and
   immutable acceptance for that eligible result. Bind the original bytes, current
   draft/result/policy heads, canonical identity, section, assignment and observed
   Canvas attempt. The application must pass its real-policy gate before any
   local selection or plan; login alone does not pass that gate.
5. **Prepare and qualify one canary.** The trusted application prepares one
   immutable review plan through the existing owner. Review its exact score/note
   delta and complete preimage. Under current scoped authority, consume the one
   preview and stage that same plan once. Require complete native readback of
   score and marked full feedback, with all other EDIT/GET/formula/protection and
   Sync state preserved. No paid call or Canvas write is part of this canary.
6. **Reconcile and close out.** Any retained attempt uses native readback only via
   `owner.execute(plan_id, reconcile_only=True)`. Preserve SENDING and terminal
   history; absence or changed teacher content never authorizes replay. Save
   aggregate outcomes, checks, exact revisions/digests, effects, owned resources,
   remaining holds and the first unfinished task. Stop after the scoped canary;
   unattended staging and Canvas publication require their own qualification.

Resume from the first unfinished gate using saved evidence whose bytes still
match. Revalidate current authority and destination state when required. A Git
merge, source sync, installed check or checkpoint starts no runtime and grants
no academic acceptance, model spending or Canvas delivery permission.
