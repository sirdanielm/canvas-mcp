# Append-only EDIT coverage reconciliation

Fresh GET refresh and EDIT coverage reconciliation are separate operations.
Ordinary **Fresh GET** updates protected observations and preserves every EDIT
field and `_Sync!B2`. It never expands the proposal schema. The append-only
reconciliation adds newly observed Canvas students or assignments to EDIT while
keeping every existing row, column, grade, formula and feedback note in place.
It is not a Canvas grade push, feedback delivery, or teacher acceptance.

This is an engineering runbook for pure local planning and verification
modules. The installed Fresh GET and Review EDIT flows do not dispatch an axis
append, and there is no registered self-service MCP or Desktop append action.
Each future coverage change needs a separately reviewed plan, durable dispatch
intent, fresh native preflight and complete readback. A private one-off operator
runner does not establish an installed public tool or authorize later runs.

Use the canonical `EDIT_AXIS_APPEND` planner for an explicitly authorized
contiguous coverage change. A separately reviewed sparse plan may preserve
occupied helper columns as described below. Do not use legacy full-sync refresh to get around an EDIT helper
formula, mismatched GET/EDIT shapes, or an occupied destination.

## Required evidence and boundaries

- Use exact workbook, course, sheet and configured protection IDs. Confirm the
  existing owned editable score rectangle and comparison rule before expanding
  them. A matching sheet name or protection description does not establish
  ownership. Preserve protection editors, restrictions, warning state and all
  unrelated rules.
- Read a complete, bounded native workbook and the content-addressed original
  `_Sync!B2` baseline. Count populated student-ID rows and assignment-ID columns;
  allocated dimensions and formatted cells are capacity, not records.
- Require complete, identity-checked current Canvas observations. Join by
  course, Canvas student ID and Canvas assignment ID. Preserve permanent PINs;
  this operation does not generate PINs or change Student Info.
  Require the exact current snapshot digest in `_Sync!B9` and independently
  verify GET identities, labels, point maxima and score values against it.
  Matching axes alone do not establish grade parity. Unknown or invalid grading
  schema is a hold.
- Existing EDIT identity axes must match the trusted baseline exactly. Check
  labels, point maxima and literal score cells through the native review
  extractor. Preserve existing physical order, including complete row/column
  rearrangements that still retain exact identities and labels in the ordinary
  contiguous layout. A versioned sparse layout additionally binds physical
  positions; its rules below apply after conversion.
- Append missing identities only. Write the new headers, student identity and
  labels, observed score cells and owned grade validation only into proven empty
  destination fields. A formula, note or unrelated validation in a field that
  would be replaced is a hold. Preserve unrelated helper cells and formats.
  Blank or absent Canvas grades remain blank; never convert them to zero.
- Keep existing student labels and assignment metadata in the merged baseline
  consistent with untouched EDIT labels and headers. The planner retains every
  old target's entire original baseline observation, including submission
  context. The review may identify a value already achieved in Canvas as
  fulfilled, but axis expansion does not rebase old records, accept a teacher
  decision or deliver feedback.
- The merged baseline includes appended targets and their exact source records.
  Save it immutably before dispatch. A plan referencing a missing baseline is a
  hold. The resulting native EDIT envelope must validate against that merged
  baseline before and after the proposed batch.
  Its explicit Working-baseline provenance identifies both the original
  baseline and the fresh observation. Do not present this derived baseline as a
  new Canvas capture; `_Sync!B9` remains the actual GET observation reference.
- Target only the new Working fields, its explicitly owned editable rectangle
  and comparison rule, and exact `_Sync!B2`. GET, reference tabs and other sync
  observations remain unchanged. Existing EDIT layout fields, including frozen
  rows, remain unchanged unless separately reviewed and authorized.

## Planning, dispatch and readback

1. Pause all worksheet editing. Keep the complete native preimage, current
   observation references, immutable baseline and exact bindings privately.
2. Call `plan_edit_axis_refresh(course, binding, before_raw, baseline, current)`
   for each course. Review aggregate additions and every allowed request field.
   Reject duplicate keys, old targets removed from Canvas, insufficient capacity, occupied
   new fields, unowned protections or unexpected rules; never guess a repair.
3. Persist each merged baseline and plan. Require `mode: EDIT_AXIS_APPEND`,
   exact binding/input digests and unchanged original preimages. Save a durable
   dispatch intent before any possible Sheets send.
4. Re-read the complete native workbook immediately before dispatch and compare
   its selected-field fingerprint with the plan. If it changed, hold the plan.
   Combine approved course plans in one native batch. Send once; keep every
   request and response private. A response timeout is a possible send.
5. Read back the complete native workbook and call
   `verify_edit_axis_output(before, after, plans, bindings)`. Verify the expanded
   exact axes, merged `_Sync!B2`, unchanged original grades/notes/formulas/layout,
   correct owned protections and validation, and unchanged GET/reference tabs.
6. Require a complete verified receipt before resuming editing. If any send or
   readback is uncertain, retain the preimage, plans and merged baselines and
   reconcile the exact saved operation. Never replay the batch, clear its
   evidence, or substitute an older clean receipt.

Google Sheets has no revision compare-and-swap covering the final read and
batch. The editing pause remains necessary. A native readback verifies the
selected fields supported by the transport; it does not certify every possible
Sheets object. Expanding the score rectangle admits more editable cells but
keeps identities and reference data protected. A collision hold sacrifices
automatic progress to preserve teacher work and avoid a larger recovery.

After reconciliation, run the native private EDIT review against fresh Canvas.
New coverage does not authorize publication. Preserve higher or excused grades,
unknowns, teacher decisions, source lineage and unresolved publishing holds.
Any higher-only copy of existing Canvas scores into EDIT is a separately
reviewed operation; it is not part of append-only coverage.

## Explicit sparse layout for retained helper columns

An occupied append destination remains a hold for `EDIT_AXIS_APPEND`. If the
teacher has authorized retaining those helper columns and adding new coverage
after them, use `plan_sparse_edit_axis_refresh` with mode
`SPARSE_EDIT_AXIS_APPEND`. This is an explicit alternative plan, not an
automatic collision fallback or permission to clear, move or reinterpret a
helper formula.

The planner appends assignment columns after the last existing opaque column
containing a value, note or validation. Existing assignment columns and student
rows remain in place. Every intervening non-assignment column is declared
opaque. New fields must still be empty of values, notes and validation; formats
remain preserved. New students receive only identity/label cells and declared
grade cells. Opaque helper columns retain every existing selected field, even
where their cells intersect a newly added student row.

The immutable merged baseline contains a strict version-one `working_layout`
with exact workbook, course, Working sheet, physical identity positions and
opaque columns. Its `working_baseline` records the original baseline and fresh
observation reference. Save and verify that baseline before the single native
batch. The ownership check requires the configured whole-sheet protection,
exact editable intervals and exact owned comparison rule. Only declared score
column intervals become editable; helper gaps remain protected. The comparison
rule ignores a blank assignment-ID header and matches GET by exact IDs.

Use `verify_sparse_edit_axis_output` to regenerate the canonical plan and compare
the complete selected native preimage/readback. Require every old score, note,
formula, validation, format, protection setting and unrelated tab to remain
unchanged. The native EDIT review must route a baseline with `working_layout`
through the strict sparse extractor before any live conversion. An unversioned
gap, unknown version or mode, duplicate key, changed physical position or
unexpected identity-header content remains a hold. Legacy XLSX and full-sync
parsers keep their original guards; they are not substitutes for this adapter.

After conversion, keep the declared physical positions stable. Sorting complete
rows or columns requires a separately reviewed layout reconciliation; never
alter the saved layout or hidden identity cells by hand to bypass a hold.
Helper values and notes remain opaque during ordinary private reviews; formulas
in declared score cells remain prohibited. A second plan with no new coverage
is a no-op and retains the existing derived baseline.

Sparse coverage uses additional physical columns and therefore has less room
before the existing 258-column capacity boundary. This trades some capacity and
sorting flexibility for preservation of teacher work and a smaller recovery
scope. Ordinary Fresh GET continues to preserve the entire layout and `_Sync!B2`.
Publication still uses the same keyed review, teacher decision, fresh publisher
checks and confirmed readback; a sparse plan grants no Canvas-write authority.

## Scoped review batches

`select_gradebook_review_batch` makes a private scope of at most 25 rows already
classified as ready for review by the captured comparison. It independently
rechecks classification, preserves the parent review and its original source
time, and records `teacher_approval: false`. It does not refresh Canvas, clear
held rows, prepare a publisher, or approve a teacher decision.

`remaining_ready` counts later rows after the selected batch.
`ready_before_batch` counts earlier rows outside that scope; it does not prove
they were processed. `unselected_ready` counts every parent-ready row outside
the selected scope. Held rows remain in the parent. Source-qualified exceptions
still require their original exact review reference and owner checks.

Review the exact child privately. Publisher preparation then obtains fresh
Canvas evidence, applies its separate target and grade guards, and creates an
expiring exact preview. A confirmation token binds that operation; it does not
establish human approval. Confirm only the exact separately approved scope.
An uncertain Canvas operation permits readback reconciliation, never a resend.

See the [worker runbook](sdm-gradebook-worker.md) and
[gradebook workflow](sdm-gradebook-workflow.md) for ordinary fresh reads and
the separate publication path.
