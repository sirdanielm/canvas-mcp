# PIN copies after the existing local QC workflow

The existing Desktop shortcuts already provide the intended user flow:

1. Download the workbook exports as usual.
2. Double-click **0 - Import Latest Fleet + QC** to assemble the complete batch,
   or **1 - Post-run QC** for an already assembled batch.
3. After QC has read the unchanged originals, create separate private PIN copies.
   Report **QC status** and **PIN archive status** separately.

Step 3 is the integration target, **not currently installed automatic behavior**.
No Google Sheets exporter or Apps Script deployment is needed for this local step.
The supported `pseudonymize_gradebook_export.py preflight` action now allows a
read-only compatibility assessment using the same renderer and shared registry,
without creating an archive. Bind each invocation to the exact source SHA-256
recorded by QC; keep its result separate from the QC verdict.

## One hook and one authority

Both shortcuts reach `sdmGrAss/scripts/local-qc-launcher.py::main`. The single
archive hook belongs immediately after its QC subprocess, for `post-run` mode
only. Do not duplicate it in the Desktop hidden importer or alter the downloaded
files before QC. That would invalidate hashes, identity joins and prior-report
comparisons.

Reuse the shared `LocalGrAss-github/localgrass/student_pin.py` registry binding
and verified email/PIN mapping. The shared selected-table JSON export and the
whole-workbook private archive renderer have different output contracts; neither
should claim that a selected-table pass cleared an entire workbook.

The central registry binds the exact roster bytes and Student Info schema. An
absent shared tool, changed roster hash, unresolved identity or unsupported
workbook feature holds the archive. Never substitute a project-specific roster,
guess a PIN, remove a held case silently, or expose identity values in errors.
The whole-workbook renderer needs Python 3.11 or newer with the local export
dependencies, rather than an arbitrary system `python3`.

## Integration acceptance checks

- Validate the completed QC report, not only its process return code. Codes 0
  and 1 can represent completed diagnostics, but code 1 can also represent
  incomplete scope. Require successful parsing, exact requested target coverage,
  and no unexpected or unclassified workbooks. Code 2 or a malformed report
  keeps the archive held.
- Use the exact workbook hashes from that report and the shared roster binding.
  Verify inputs remain unchanged while rendering. Write new private outputs
  outside the source batch, repository and QC baseline directories.
- Publish a completed batch only after every included workbook passes. Keep
  a bounded aggregate hold receipt when any workbook cannot be sanitized. Treat
  `ARCHIVE_PUBLICATION_UNCERTAIN` separately: retain the exact attempted path and
  reconcile possible output before retrying; a transport/process error does not
  prove that the archive was never created.
- Keep original QC findings and exit status visible independently of archive
  failure. PIN conversion is not grading, privacy clearance for public sharing,
  or publication permission.
- Cover both shortcuts, single invocation, code 0/1/2, incomplete coverage,
  changed/missing registry, source preservation, interrupted/failed batches and
  exclusion from automatic baseline selection with offline regression tests.

## September 28 compatibility checkpoint

An offline trial against the latest complete local download batch examined
15 workbooks with the existing whole-workbook renderer and verified central
mapping. All 15 were held: 14 had unresolved email content and one had an
unresolved identity column. Every source hash remained unchanged and no
completed PIN workbook was emitted. This is a compatibility finding, not a QC
or grading verdict. Resolve these holds and verify batch-level behavior before
activating the launcher hook.

The previously verified central-gradebook private PIN archive is a separate
successful case; it does not establish fleet workbook coverage.

## September 30 compatibility checkpoint

The current `preflight` API examined the 16 workbooks in the exact saved batch
covered by a complete post-run QC report. All 16 source hashes matched that
report. All 16 archives remained held: 15 for unresolved email content and one
for an unresolved identity column. Source files, the shared registry and QC
reports remained unchanged; no archive was created and no desktop tool or
installed harness changed. QC's own diagnostic verdict remains separate.

The [aggregate preflight receipt](validation/fleet-archive-preflight-20260930.json)
binds this observation to the exporter, source-hash set and QC report hashes.
The older 15-workbook assessment used a different batch, so this is not a claim
that a new code change caused an additional failure. Keep the automatic archive
hook inactive. Resolve the exact identity/content holds within the central
authority contract, then repeat this preflight and the batch integration checks;
do not broaden substitutions or silently omit held workbooks to obtain a pass.
