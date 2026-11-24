# Prepared draft content profile

[PR #79](https://github.com/sirdanielm/canvas-mcp/pull/79) merged the opt-in
prepared-content registry into the maintained fork. Use the
[authoring workflow](sdm-canvas-authoring-workflow.md#choose-the-authoring-profile)
to choose the profile. Verify the loaded tool list, pinned manifest and journal
through the operator before using the connection for a live task.

## User-facing authority contract

An explicit request to create or edit drafts authorizes preparation without
redundant prompts. Keep two distinct action-time user gates:

1. Exact grade pushes, including the destination, students/attempts, scores and
   associated feedback effects.
2. Any change to Published status, including publication and unpublication, with
   exact objects, linked objects and intended visibility.

These gates do not replace platform permissions or other required protections.
Never use a delayed publication date as a substitute for a private draft. For an
object without a reliable Canvas-native draft state, prepare content outside
Canvas until the appropriate action is authorized. No grade or visibility-change
implementation is included here.

## First slice

`DraftAssignmentService` is the internal service for the separate prepared-content profile. Creation supports
ordinary assignments (on-paper, no submission, text, URL or upload), forces
unpublished and disables peer-review automation. Updates change only name and
HTML description, require the canonical digest of a fresh complete assignment
read, and verify the exact course/assignment and unpublished state before PUT.
Updates omit Published entirely; they never attempt to unpublish a changed target.

The service requires a private operator-owned journal. An exclusive operation-ID
claim is flushed before any network request. Reusing a completed, interrupted or
uncertain operation ID is held, including after process restart. Receipts contain
hashes, status and object IDs, not content, credentials or student data. Writes
have no automatic rate-limit retry. Success requires an independent GET matching
identity, draft status, content and protected metadata. Missing evidence holds.

A prior authorization remains valid for unchanged scope. Neither a content hash
nor an operation ID confers authorization. Canvas has no universal compare-and-
swap: concurrent publication between GET and PUT remains a race. Use single-owner
coordination; a readback change is a hold, not rollback or automatic retry.

## Setup and qualification

- The main server provides `--draft-content-only`, educator/stdio only, mutually
  exclusive with `--draft-modules-only`. It requires an operator-owned mode-0600
  manifest pinned by exact SHA-256 and a separate private journal directory.
- Supported write allowlist: an explicit nonempty subset of
  `apply_prepared_draft_assignment,apply_prepared_draft_module_item`. Absent, empty,
  `none`, `all` or any outside tool disables writers. The only reader is
  `inspect_prepared_draft_assignment`; neither accepts arbitrary content, paths,
  grade values or publication parameters, only a prepared entry key.
- Each create entry requires the complete reviewed `existing_assignment_ids` for
  its course. A fresh fully paginated inventory must match exactly and contain no
  same-name candidate. This intentionally holds ambiguity rather than guessing
  identity. Updates require exact ID and preimage digest. An identical content
  binding with a new operation ID is also held after any prior intent.
- The caller prepares the immutable manifest as part of the explicit task, not
  through another user approval prompt. If the inventory changed, inspect and
  reconcile before preparing a replacement manifest; do not merely refresh the
  baseline to bypass an uncertain creation. Concurrent external creates remain
  a race requiring single-owner coordination and outcome reconciliation.
- For an installed connection, verify journal ownership, permissions, retention
  and uncertain-operation reconciliation through the operator route. Use the
  exact runtime binding, loaded registry and applicable qualification receipt
  for the requested effect.

## Next slices

Pages: force unpublished, teacher editing, no front-page replacement, scheduled
publication or notification. Ungraded discussions: add a real unpublished
adapter; the current general create tool hardcodes publication. Do not include
announcements, graded discussions or replies in this first expansion.

Additional module content link types need their own parent, item and target
checks. The current profile supports the positioned module items below.

Classic quizzes: new adapter using `/api/v1/courses/:course_id/quizzes`, strict
`quiz[published]=false`, exact quiz ID and associated assignment binding. Question
creation uses the Classic question endpoint and requires an unpublished parent
before and after. Hold unsupported question types, submission-bearing objects,
unknown identity or absent publication evidence. Never use attempt/submission
endpoints for authoring.

New Quizzes: separate adapter using `/api/quiz/v1/courses/:course_id/quizzes` and
its item API; the path's quiz identifier is the assignment ID, not interchangeable
with a Classic quiz ID. Verify both quiz and associated Canvas assignment, with
explicit unpublished state, before/after item writes. Do not substitute an
external-tool assignment shell for a fully created New Quiz. Tenant API support,
permissions and supported item schemas must be qualified before enablement.

Official API contracts:
- https://developerdocs.instructure.com/services/canvas/resources/quizzes
- https://developerdocs.instructure.com/services/canvas/resources/quiz_questions
- https://developerdocs.instructure.com/services/canvas/resources/new_quizzes
- https://developerdocs.instructure.com/services/canvas/resources/new_quiz_items

Files, LTI tools, imports/migrations, shared question banks, rubric associations,
grade pushes and publication remain separate capabilities. Stage outside Canvas
when private visibility cannot be verified.

## Source invocation

`canvas-mcp-server --role educator --draft-content-only
--draft-content-manifest /private/absolute/manifest.json
--draft-content-sha256 <exact-byte-sha256>
--draft-content-journal /private/absolute/journal`

For assignment drafts, the operator supplies
`ALLOWED_WRITE_TOOLS=apply_prepared_draft_assignment`. The manifest is
`{"schema_version":1,"assignments":{"entry-key":{...}}}`. Each entry has
`operation_id`, numeric-string `course_id`, `content`, literal `published:false`,
and either create inventory IDs or `assignment_id` plus `expected_sha256`.
Existing-object edits support only name/description. Creation requires canonical
points, group and one all-course due setting as described below. Assignments to
individual students, grade pushes and Published transitions remain unsupported.

## Positioned module items

With `apply_prepared_draft_module_item` explicitly allowed, optional
`module_items` entries select only `SubHeader` (a prepared title)
or `Assignment` (exact existing assignment ID), a numeric course and
module ID, integer position, literal unpublished state, and complete reviewed
`existing_item_ids`. Entries use their own durable operation IDs. The server
checks the parent's unpublished status, exact assignment course/ID/unpublished
status, and fully paginated inventory before creating one item. Independent GETs
verify item identity/type/position/unpublished state, parent visibility and linked
assignment visibility. Missing publication evidence is UNVERIFIED, not success.
No module update, Published transition, completion requirement, date calculation,
quiz creation or assignment-content invention is implemented by this capability.
Position insertion may reorder subsequent items as part of Canvas's normal insert
operation; preview that intended position in the prepared manifest. Cross-object
races remain and require single-owner coordination. Completion requirements
need a separate reviewed capability.

## Canonical new-assignment metadata

Creation now requires authoritative name, description, submission type, finite
nonnegative `points_possible`, numeric-string `assignment_group_id`, and explicit
`due_at`. The due field must be an exact UTC `YYYY-MM-DDTHH:MM:SSZ` or JSON null
for an explicitly reviewed no-due-date assignment. Missing values hold, not a
zero-point shell. The prepared inspector returns this content for review.

The group must appear exactly once in the complete paginated assignment-group
list for the exact course before POST. No groups or weights are changed. New
objects use points grading, no peer reviews and `post_to_sis=false`; readback
must independently match points, group, due, grading type, unpublished state,
no overrides, no SIS posting and no unlock/lock dates. Grade values are never
written. Unknown or mismatched readback is UNVERIFIED.

Section/student overrides, date overrides, unlock/lock windows, notifications,
SIS integration and LTI configuration remain unsupported and are rejected. This
slice supports one explicitly reviewed all-course due date only. Where section
specific due dates are required, do not substitute a common date: hold that
assignment pending a separately designed section-bound preview/write/readback
contract. Existing-object edits accept name/description only and preserve
points, groups and dates.

## Platform boundary

This prepared-content profile requires POSIX ownership, exact private mode bits
and durable directory fsync. Windows is deliberately unsupported until a separate
ACL and durability contract is implemented. Profile initialization rejects it
explicitly before reading a manifest or registering tools; direct service calls
return HELD without creating journals or making requests. Existing read-only and
module-only profiles are not subject to this new platform restriction.
