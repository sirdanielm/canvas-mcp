# GrAss integration and authority boundaries

The intended flow is graders → saved result records → proposals → exact
teacher-approved score/feedback pairs → Canvas publisher → verified GET readback.
Each stage retains its source and revision basis. A successful request, a passing
software test, or a completed QC run does not establish teacher approval or
verified delivery.

The canonical [architecture contract](https://github.com/sirdanielm/LocalGrAss/blob/main/docs/GRASS_GREENFIELD_ARCHITECTURE_CONTRACT.md),
[build plan](https://github.com/sirdanielm/LocalGrAss/blob/main/docs/GRASS_NEXT_BUILD_PLAN.md),
and [production connection plan](https://github.com/sirdanielm/LocalGrAss/blob/main/docs/PRODUCTION_CONNECTION_PLAN.md)
are maintained with LocalGrAss. Repository access may require authentication.
Quinn and local AI remain optional future adapters.

## Repository responsibilities

| Repository | Responsibility |
| --- | --- |
| Canvas MCP SDM profile | Authenticated Canvas reads, local gradebook mirror and permanent PIN source; separately gated score-only publisher |
| sdmGrAss | Grader runtime, lifecycle controls, desktop imports and diagnostic QC |
| GrAss | Native academic policy, verified paper/question evidence, saved results and proposal exports |
| LocalGrAss | Local review dashboard, durable drafts, immutable revisions and authenticated final pair decisions |

The existing gradebook mirror is the recommended first read-only source adapter.
Its captured snapshot and identity bindings must be verified before admission;
snapshot hashes do not establish live Canvas freshness. Originals, private
crosswalks, credentials and detailed student records remain outside Git.

## Current implementation boundary — October 1, 2026

The [October 1 connection slice](https://github.com/sirdanielm/LocalGrAss/blob/main/docs/PILOT_CONNECTIONS_2026-10-01.md)
adds durable original-byte/catalog evidence associations, a Canvas-owned
[receipt/PIN capture port](grass-capture-contract.md), authenticated DECIDE-only
local teacher review with durable drafts, and an authoritative fake-only
workflow release bridge. Each send-intent transaction rechecks current academic,
identity, binding and decision authority. Independent score/comment readbacks and
restart tests use fictional inputs and FakeTransport only.

Real grouped-policy scoring, source ownership/page/legibility, real evidence
review, authenticated RELEASE provisioning and Canvas target/attempt/feedback
transport remain separate production work. Existing quarantined recovery cannot
activate a restored worker. The Canvas score-edit publisher still does not
deliver feedback or authenticate a teacher's preview approval. See the
[implementation status](https://github.com/sirdanielm/LocalGrAss/blob/main/docs/IMPLEMENTATION_STATUS.md).
No Git merge or successful capture admits a real grading case or enables writes.

The separate [Unit 1 pair-preview prototype](unit1-pair-preview-contract.md)
compares a proposed private accepted-pair envelope with independently retained
source/policy/result/identity/form bindings and exact Canvas observations. It
preserves paper versus Canvas attempts, teacher final versus raw/converted points,
and pending feedback even when a score matches. It is unregistered and offline:
no accepted-pair exporter, live preflight, RELEASE authentication, comment
transport, token or Edit transfer is connected. Publication remains unavailable.

The maintained offline code also has a disabled exact-GET parser and separate
score/comment form specifications, with independent author/payload bindings and
complete existing-comment metadata comparisons. It has no HTTP sender or real
release provider. Desktop tool 7 is optional fictional editing practice; tool 9
inspects original Unit 1 papers read-only. Saving a draft does not approve or
deliver a classroom pair. The pair-preview contract explains these controls and
the remaining production connections.

The desktop import/QC workflow writes durable aggregate receipts. The newest
attempt remains authoritative even when failed, interrupted or held. The
clickable status tool and on-demand agent instructions read these receipts;
no automatic Codex hook or notification was installed.

The gradebook refresh worker's implementation and dated activation evidence are
documented in [its operations guide](sdm-gradebook-worker.md). Syncing its Git
branch neither restarts that worker nor requests another refresh. Its Canvas
transport is GET-only; refreshing reference data is distinct from publishing
teacher-approved pairs.

## Paper-review dashboard coordination — October 2, 2026

The agreed user experience is an original paper page beside the exact question,
accepted rubric, proposed points, a short evidence-based reason and editable
feedback. Question inspection and edits are draft work that rolls up to **one
explicit final assignment score/feedback decision**. Source-fidelity confirmation,
draft saving, pair acceptance, release and verified delivery are distinct actions.
The [LocalGrAss teacher-review contract](https://github.com/sirdanielm/LocalGrAss/blob/main/docs/TEACHER_REVIEW.md)
and [private paper-viewer guide](https://github.com/sirdanielm/LocalGrAss/blob/main/docs/UNIT1-PRIVATE-REVIEW.md)
own the review experience; this section records the connections between repositories.

As checked in the owning repositories on October 2, LocalGrAss has a working-copy
paper viewer and an existing authenticated draft/acceptance journal. The real
Unit 1 viewer remains read-only: its edits and approvals are not connected to that
journal. Tool 7 is fictional practice. Saved progress means explicit saved drafts
and queue context; unsaved browser edits are not durable or autosaved. A persistent
teacher **Hold** action still needs a revision-bound reason in the existing journal;
engineering/evidence holds remain separate and cannot be cleared by that action.
These working-copy features are not a deployment or browser-verification claim.

Build the connection in this order:

1. **Admit exact sources and academic context.** Use independently accepted form,
   rubric, identity, original-page and producer-membership bindings. Missing or
   conflicting authority holds the case. An export hash proves captured bytes,
   not academic acceptance or live Canvas freshness.
2. **Compose the existing records.** Reuse GrAss's private
   `grass_unit1_policy_review_export_v1` records and manifest, verifying the
   manifest, entries digest and native result/feedback revisions. Join question IDs
   and page roles to the existing verified context. Feedback `details` describes
   deductions; it is not the full rubric or all positive evidence. Reuse the native
   rubric/evidence projection rather than rescoring inside the dashboard. Show
   original pages until reviewed crop coordinates exist.
3. **Connect review to the existing journal.** Import the immutable owner result
   through LocalGrAss's existing workflow, compose evidence into teacher review,
   and reuse `save_draft` / `accept_draft` and the existing draft, decision and
   acceptance tables. Do not create a second question-approval store. Preserve
   draft history and require comparison when the source, result or decision changes.
4. **Complete the review controls.** Add a durable teacher Hold reason through the
   same revision-guarded commands. Distinguish saved drafts, accepted assignment
   pairs and unresolved evidence holds. Verify keyboard use, image enlargement,
   narrow windows and browser behavior before calling the dashboard usable.
5. **Connect delivery separately.** Export the exact accepted pair, provision
   scoped authenticated RELEASE, and connect a durable Canvas transport ledger.
   Verify score and feedback with independent GET readbacks. Uncertain sends
   require reconciliation before any retry.

Keep native `FORM_POINTS`, raw criterion points and mastery contributions visible;
no implicit Canvas scaling or acceptance is authorized. The Canvas
[disabled Unit 1 protocol](unit1-pair-preview-contract.md), merged in
[PR8](https://github.com/sirdanielm/canvas-mcp/pull/8) and
[PR9](https://github.com/sirdanielm/canvas-mcp/pull/9), supplies comparison and wire
specifications, not an active publisher. sdmGrAss owns runtime/fleet provenance and
central policy diagnostics; diagnostic QC does not approve a score. Quinn/local AI
remains an optional adapter and is not a dependency of this review path.

## Next engineering work

1. Use the tested capture/intake port with exact original source/page/ownership
   receipts and a supported academic-policy/observation adapter.
2. Extend quarantined database recovery to original evidence and external
   receipt stores; establish exclusive worker ownership before activation.
3. Use authenticated durable review to inspect actual evidence, then add scoped
   RELEASE provisioning and a reviewed real score/feedback publisher.
4. Adopt the coherent academic packet only through fresh source/binding checks
   and guarded setup. Preserve the existing grouped policy; an older unconfirmed
   50/50 draft is not replacement authority. Resolve archive holds separately.

Assignment point totals and participation/Advanced policies require explicit
academic authority. Missing policy is a hold; it cannot be inferred from an old
grader, an export layout, or a successful software test.

## Source and recovery checkpoint — September 30, 18:10 EDT

[Canvas PR4](https://github.com/sirdanielm/canvas-mcp/pull/4) merged at `dbbe93c`.
The new archive preflight shares the full renderer and registry checks, supports
exact QC source hashes, and returns before archive publication. All 2,165 Python
tests passed with 21 existing skips; all 65 exporter tests, lint/types and the
hosted Python matrix, TypeScript and confirmation checks passed.

The batch captured at this checkpoint was **16/16 held**, with no archives
created. First blocker triage found the same unmapped source-owner provenance address in 15
workbooks and an unresolved explicit student email in one cache. The source-owner
address does not match the authenticated Drive profile; it must not be silently
classified as the teacher or mapped to a student PIN. These are two different
authority problems. Later blockers may remain after those first failures clear.
The installed toolbox was preserved; no automatic archive hook was installed.
See the [exact-batch receipt](validation/fleet-archive-preflight-20260930.json).

[LocalGrAss PR4](https://github.com/sirdanielm/LocalGrAss/pull/4) merged at `becae68`.
It adds bounded original-byte verification and WAL-aware SQLite backup with
quarantined restore. All 320 tests passed in the installed full runtime; Python
3.9 passed 318 with two optional PDF skips. Independent reviews covered both
modules. The source verifier does not authenticate identities or yet persist a
byte-catalog/evidence-revision association. Both incomplete and completed restores
are blocked from opening as active Registries. Evidence blobs, external-state
reconciliation and activation remain separate work. See the
[production connection plan](https://github.com/sirdanielm/LocalGrAss/blob/main/docs/PRODUCTION_CONNECTION_PLAN.md).

Authenticated Canvas reads captured at this checkpoint established the two
academic settings for the affected assignment: **Core 30; Advanced DEFINED, 40
including Core**. The captured grouped weights can be preserved with the existing legacy rubric policy; no
invented per-question allocation is needed. Investigation also found an incomplete
Advanced rubric and an obsolete A6 key. A complete private draft repairs eight
fields together. Canonical runtime validation passes both tracks; academic QC on
the candidate has zero findings, versus two errors and one informational finding
on the captured original. This is an offline candidate result, not a cleared live
grader. Current worksheet evidence supports the corrected A6 task; the live
companion key still needs its corresponding correction.

The packet and guarded application plan are retained privately with source hashes.
Actual registry acceptance, current source/routing bindings and setup approval
remain required. The installed QC receipt is still the earlier COMPLETED/STOP
attempt. This pass made read-only source checks and code/documentation changes;
it performed no paid calls, classroom grading, deployment or Canvas/Sheets writes.

## Git synchronization checkpoint — September 30, 17:07 EDT

This is a dated repository snapshot, not a live operational status report.

| Repository | Integrated work | Verified boundary |
| --- | --- | --- |
| Canvas MCP SDM profile | [PR3](https://github.com/sirdanielm/canvas-mcp/pull/3) integrated the current upstream; [PR2](https://github.com/sirdanielm/canvas-mcp/pull/2) merged at `c6fc7be` | Private PIN exporter reviewed and pulled into the SDM checkout; exact-head Python matrix, TypeScript, lint and confirmation proofs passed |
| sdmGrAss | [PR335](https://github.com/sirdanielm/sdmGrAss/pull/335) and [PR336](https://github.com/sirdanielm/sdmGrAss/pull/336) merged after PR334; main `bf1a6f2` | Owning task verified 102 JavaScript programs, 227 Python tests and hosted checks; independent fault injection confirms a stop/gate change during admission prevents transport |
| LocalGrAss | [PR3](https://github.com/sirdanielm/LocalGrAss/pull/3), merge `f931c29` | Five post-merge integrity findings fixed; owning task verified 287 tests; primary main synchronized. No hosted check was attached to this PR |
| GrAss | [PR122](https://github.com/sirdanielm/GrAss/pull/122), merge `695f479` | Duplicate unplanned/sealed source evidence now holds report generation; owning task verified 1,030 Node and 90 Python tests; hosted CI passed and primary main synchronized |

The final Canvas exporter integration passed 2,158 Python tests with 21 existing
skips, including all 58 exporter tests, plus 22 menu tests, 96 TypeScript tests,
Ruff, mypy and the TypeScript build. An isolated locked development installation
and an actual CLI smoke using the shared authority implementation passed with
entirely synthetic inputs. See the [aggregate validation receipt](validation/private-pin-export-20260930.json).
The merge tree matches the reviewed and tested head. These are software checks,
not grading-accuracy or source-freshness claims.

The listed code-review backlog was resolved at this checkpoint. The later
source/recovery checkpoint supersedes its byte-verifier and database-backup TODOs.
Remaining work includes authenticated teacher decisions, production source and
recovery connections, bounded workers and the authoritative release-to-publisher
bridge. The [private PIN exporter](local-pin-exports.md) is opt-in; the automatic
[post-QC archive hook](post-qc-pin-archives.md) remains uninstalled until fleet
compatibility and batch recovery pass. Publication uncertainty requires
reconciliation, never an automatic retry.

The installed status reader was checked again at this checkpoint. Its newest
captured attempt is still the September 30 11:42 EDT run: execution completed,
16/16 workbooks parsed, diagnostic STOP with 2 errors, 50 warnings and 70
informational findings. Reading that receipt did not rerun QC. The previously
recorded academic setup holds remain for teacher resolution; the GENERAL TESTING
canary evidence is historical and was not rerun for these merges.

Local artifacts and concurrently edited checkouts were preserved. The installed
desktop toolbox remains pinned to its reviewed harness. No runtime restart,
deployment, model call, workbook edit or Canvas operation was performed by this
sync pass. Production deployment in the integrated Canvas profile is gated by a
release tag or explicit manual workflow; ordinary SDM branch pushes do not deploy.
