# SDM Canvas gradebooks

The main workbook is FDHS Chemistry Gradebook — 2026–2027 (open through the locally configured workbook). Its existing sharing permissions are unchanged. The September 29, 2026 layout has seven visible tabs and nine total:

1. Core GET
2. Adv GET
3. Core Edit
4. Adv Edit
5. Student Info
6. Assignment
7. Grader Proposals

The mirror tabs are protected GET-only snapshots. The edit tabs have the same layout, with only score cells editable. At the September 20, 2026 migration checkpoint, Student Info retained 173 permanent numbers, including two students outside the active roster, and Assignment contained 52 Canvas assignments plus prior IC mappings. Those are historical counts, not configured limits or a live inventory. Never renumber or recycle permanent numbers. Refreshing grade tabs must preserve both reference tabs and Grader Proposals; reconcile reference metadata separately by exact IDs, retaining IC fields and permanent numbers.

`_Core Sync` and `_Adv Sync` are hidden system tabs. Course-specific `tab_names` in the binding file normalize these names to the internal Canvas/Working/_Sync roles. The previous standalone workbooks and the user's backup (open through the locally configured workbook) remain available. The 36 old tabs were removed from the main workbook only after full replacement readback and backup/student-number checks.
The course/workbook/sheet bindings are in `config/sdm-gradebook-workbooks.json`.
No student data is stored in that configuration or in Git.

This workflow contains private student grades and submission-status metadata.
The separate [GET-only course-content mirror](course-mirror.md) archives course
materials and structure without rosters, grades, or student submissions. Running
`scripts/course_mirror.py get` does not refresh this workbook, and fetching a
gradebook snapshot does not update Google Sheets until the refresh protocol is
completed.

## Permanent PINs for local copies

`Student Info` is the cross-project PIN authority: resolve the `Email` header to
`Student Number`, preserving four-digit text and leading zeros. Its private
name fields are `Canvas Name`, `IC Name`, and `Roster Name`. The historical
`Student Numbers` tab is not the current lookup contract. Local document copies
replace identity columns with `student_pin` through the shared exporter and
operator registry; the mirror and original reference tab stay unchanged. See
[Student PIN policy](STUDENT-PIN-POLICY.md) for the common source location,
command, and fail-closed matching rules.

## Everyday use

The new [local refresh worker](sdm-gradebook-worker.md) connects a menu request
to the canonical planner and trusted local baseline store. It prepares both
courses, performs one atomic Google Sheets batch, and verifies the native
result. Canvas remains GET-only. Pending Edit proposals retain their original
baselines; reference tabs remain unchanged.

**Dated activation evidence, September 30:** the user-owned OAuth transport,
installed menu, first native refresh, verified reconciliation and advancing worker
heartbeats were recorded in the [worker runbook](sdm-gradebook-worker.md). This
supersedes the September 29 pending-activation checkpoint; it is not a fresh
liveness check.

Choose **Canvas Gradebook → Refresh both courses (Canvas GET only)** and keep the
workbook idle until **Show refresh progress** reports VERIFIED. Check the current
worker status; the Mac and local worker must be awake. Setup, recovery, limits
and privacy boundaries are in the runbook. A Git pull does not restart or verify
the worker. The general server's `ALLOWED_WRITE_TOOLS` policy does not replace the
separate gradebook service's explicit `--enable-push`, preview and readback gates.

### Historical legacy GET menu error

Before the September 29 overlay, **GrAss Submissions → Snapshot submissions
(GET only)** could report
`Submission snapshot stopped: submission_output_unowned_preserved`. Do not
clear ownership properties or run **Set up central workbench** to force it past
the guard. The main workbook's bound project is **GrAss Submission
Workbench**. Its former `snapshotGrAssSubmissions()` handler ran the standalone
submission-workbench runtime, which requires its own output sheets and ownership
records. Those sheets are absent from the central gradebook. That runtime
stopped while capturing output ownership, before fetching Canvas or
replacing outputs. This was a stale menu/layout mismatch, not evidence of an
expired Canvas credential.

The September 29 overlay replaces the menu entry points while preserving the
old runtime and its ownership guards. After installation and reload, the legacy
command is no longer exposed by the menu; an already-open legacy menu's snapshot
handler redirects to refresh instructions. Preserve a complete bound-project
source backup before installation and verify the complete source afterward.

The local worker implements the current gradebook controller. Before activating
it, preserve the bound project's source and verify these requirements:

- Exact workbook, course, and sheet-ID bindings; no sheet creation or adoption
  merely because a name matches.
- Complete Canvas GET pagination and course/permission checks, with no Canvas
  write transport.
- Stable student and assignment IDs, literal values, submission notes, status
  colors, and protected mirror sheets.
- Preservation of pending Edit proposals and their original trusted baselines,
  including continued compatibility with the local push-preview parser.
- No changes to Student Info, Assignment, or Grader Proposals, an execution lock,
  a fresh-input check before writing, and complete readback after one atomic
  Sheets update.

The local workflow stores immutable baselines outside Apps Script. A menu
controller must explicitly integrate with that store or introduce and validate
a compatible baseline handoff; it must not silently replace `_Sync!B2` with an
unavailable or untrusted snapshot.

Historical checkpoint: on September 23, 2026, the legacy menu and its handler
were verified in the live bound script. An agent-assisted refresh at 10:17 PM EDT
then read back
successfully for 120 Core students and 51 Advanced students, with 17 published
graded assignments per course and zero pending edits. Student Info and
Assignment values were unchanged. Both private refresh receipts reported zero
Canvas writes. At that checkpoint the bound script was inspected, not replaced.
The first September 29 overlay repaired menu guidance and navigation. The
subsequent worker implements the refresh controller; live activation remains a
separate, verified setup step.

For each course, the two grade tabs behave as follows:

1. **GET** is the protected snapshot: student names and sections, assignment
   columns, points possible, and frozen headers. Blue indicates late status,
   yellow indicates excused, and pink indicates Canvas's missing flag.
2. **Edit** is the editable mirror. Change the grade cells here. Green
   highlights differences from the GET tab. Enter numeric points or `EX` /
   `Excused`; a blank never silently clears a grade or becomes zero.

The hidden course-specific sync tab records the baseline and current Canvas snapshot.
Hidden column A contains Canvas student IDs; hidden row 5 contains assignment
IDs. Move complete rows if sorting; do not sort only names or grade cells.
Keep notes and new assignments outside these connector-owned tabs. Assignment
creation and roster changes originate in Canvas.

Protection reduces accidental edits but an owner can override it. The parser
therefore verifies IDs, labels, complete roster/assignment coverage, and the
immutable local baseline. It rejects formulas, duplicate identities, and data
outside the mapped grade columns. Editing the Canvas tab never changes the
trusted baseline. Both Sheets tabs use literal text, including Canvas-authored
labels that begin with formula characters.

This is a spreadsheet adaptation of the Canvas gradebook. It does not copy
Canvas search widgets, totals, custom UI sorting, unpublished assignments, or
inactive enrollments. Canvas's status colors do not indicate mastery.

## Available tools

The tracked connection template exposes seven tools that do not write Canvas,
plus the separately confirmed push tool when explicitly enabled. Snapshot,
review, refresh, and push-preparation tools create private local artifacts;
push preparation and reconciliation also update the local operation ledger.

| Tool | Result |
| --- | --- |
| `get_canvas_gradebook` | Complete private snapshot; aggregate counts |
| `preview_gradebook_changes` | Fresh comparison and private HTML review |
| `prepare_gradebook_refresh` | Private batchUpdate plan preserving pending edits |
| `verify_gradebook_refresh` | Fresh-input check or complete output readback |
| `prepare_gradebook_push` | Exact review and expiring operation confirmation |
| `get_gradebook_push_status` | Durable aggregate operation status |
| `reconcile_gradebook_push` | Read-only reconciliation; never resends a grade |

All return aggregate counts and artifact references, never names, emails,
individual grades, or rosters. Raw data stays in private artifacts. The general
Canvas connector and its anonymization settings are unchanged. The gradebook
transport follows complete Link pagination, rejects changed pagination
origins/endpoints, and checks course identity and grade-management permission.
An incomplete read cannot replace an earlier snapshot.

### Local setup

The dedicated launcher is specific to macOS and the configured FCPS Core and
Advanced courses. It accepts `core` or `advanced`; Advisory belongs to the
content mirror, not this gradebook service. It rejects a saved Canvas origin
other than `https://fcps.instructure.com` and disables dotenv loading.

For a fresh checkout, install the locked dependencies including native Keychain
support:

```sh
uv sync --frozen --group dev --extra local-keychain
```

Run `scripts/Setup Canvas Connection.command` interactively if credentials are
not already saved. The shared setup validates the token with one GET and stores
it in macOS Keychain under service `sdm.canvas-authoring`; only the Canvas origin
is saved in `~/.config/canvas-authoring/connection.json`. Tokens do not belong in
tool arguments, workbook cells, or repository files. The gradebook requires
Canvas to confirm `manage_grades` permission even for its read-only snapshots.

The paths in `config/sdm-gradebook.toml.example` are workstation-specific; review
them before installing on another checkout. Install a missing entry or upgrade
the recognized initial two-tool entry:

```sh
.venv/bin/python scripts/install_gradebook_connection.py --upgrade
```

The installer requires an existing configuration file (by default
`~/.codex/config.toml`; override with `--config`). It preserves unrelated
settings, saves a private configuration backup, and refuses unknown
customizations, including an already customized push-enabled entry. An exact
template match is a no-op. Reload/reconnect the desktop MCP
connection if an existing task still has the earlier tool list. A CLI invocation
of the same MCP tool is also available:

```sh
.venv/bin/python scripts/sdm_gradebook_launcher.py --call get_canvas_gradebook \
  --arguments '{"course":"core"}'
```

`--snapshot core` is a direct GET-only shortcut. Local artifacts default to
`local_gradebooks/`; `--state-dir` changes that store, so use the same directory
for subsequent baseline, preview, and operation references. The launcher loads
workbook bindings on startup. Changing the binding file therefore requires a
new launcher process or reconnect before using the updated mapping.

## Agent refresh protocol

1. Export the **bound** Google workbook with Drive `fetch`,
   `download_raw_file=true`, and XLSX MIME type. Decode the returned base64
   directly to a mode-0600 file in `local_gradebooks/inbox/`; do not print it or
   load student rows into chat. The signed export URL may return 403; the raw
   fetch response is a verified alternative.
2. Read `_Sync!B2` programmatically to select its immutable snapshot. Call
   `prepare_gradebook_refresh(course, snapshot_id, workbook_filename)`.
3. Keep editing paused during refresh. Export the workbook **again** and call
   `verify_gradebook_refresh(..., phase="before")`. Stop on an error. Plans
   expire after five minutes, and every literal input value is fingerprinted.
4. Load the saved plan's `batch_update` inside tool orchestration, without
   emitting it into the conversation, and send it through the connected Google
   Drive `batch_update_spreadsheet` tool. Do not create a replacement workbook.
5. Export the result and call `verify_gradebook_refresh(..., phase="after")`.
   This verifies every Canvas and Working grade by ID and saves a private
   receipt. Keep both exports if verification fails; do not blindly replay
   the previous batch.

In this protocol, `_Sync` denotes `_Core Sync` or `_Adv Sync` through the binding.
The input fingerprint covers literal cells in that course's three mapped tabs;
it does not cover Student Info, Assignment, formatting, notes, or protections.
Post-refresh verification checks roster/assignment identities, labels, grades,
pending edits, and snapshot references. It does not independently inspect native
Google sheet protections, hidden rows/columns, conditional formatting, or notes.
Check those through Sheets metadata/readback when installing or changing the
layout; a successful grade-value receipt alone does not certify the full UI.

A refresh merges untouched cells from Canvas while retaining local edits.
Every pending cell also retains its **original** baseline in a content-addressed
working-baseline artifact. Thus, a changed Canvas grade remains a conflict
through repeated refreshes. When Canvas already matches a proposal (including
after a successful push), that edit is fulfilled and clears without another
write. `_Sync!B9` points to the actual current Canvas
snapshot; `_Sync!B2` points to the working baseline, which may retain older
observations for pending cells. If roster or assignment grading schema changes
while edits are pending, refresh stops and preserves the existing workbook.

The workbook refresh layout supports 1–995 students and 1–256 published graded
assignments. The live snapshot transport has a stricter cap of **100 published
graded assignments** and a **120-second deadline** covering all discovery,
pagination, and rate-limit backoff. These are separate limits: workbook capacity
does not permit a live refresh above the transport cap. Reaching either
transport limit retains the previous snapshot and stops without a partial
refresh; see [Gradebook visibility reads](gradebook-visibility-read.md).
Grade columns expand as later assignments are published; empty courses or
courses beyond supported limits stop rather than truncate. The destination
sheets must already have enough rows; the refresh resizes columns but does not
create sheets or expand
their row capacity. The published assignment count is read from each fresh
Canvas snapshot rather than hardcoded. Submission workflow, attempt, timestamps
and flags are stored in grade-cell notes, in addition to status colors.

Google Sheets does not provide a compare-and-swap transaction covering an
export plus a subsequent batchUpdate. The fresh-input check reduces that race
but does not eliminate it: keep the workbook idle while applying a refresh.
An owner can override sheet protection, so it is not a substitute for this
editing pause. The batch itself is atomic; the output check detects divergence.

## Manual paper-credit reconciliation

Paper-mark evidence is reconciled **before** any Canvas write. Use a
teacher-owned normalized ledger with these fields: section, student identity,
assignment code, paper mark, credit points, and source-photo reference. The
ledger and source images are private artifacts; never paste student rows into
chat or commit them to Git.

1. Refresh both GET tabs and retain the verified snapshot IDs.
2. Match each ledger identity to exactly one active Canvas enrollment and its
   recorded section. Never use roster order, a display-name approximation, or a
   blank identifier as a match.
3. Match each assignment code to exactly one published points assignment in
   that student's course. Hold missing, duplicate, unpublished, or changed
   targets.
4. Validate that the paper credit is numeric and within the assignment maximum.
   A full check and a check-minus must already be converted to literal points
   in the ledger; do not infer a score from an unclear mark.
5. Preserve an equal or higher Canvas score and every `EX` / excused result.
   Only a paper-supported score that is strictly higher than current Canvas is
   eligible for a teacher-reviewed change.
6. Produce a private review map with the source reference, exact Canvas target,
   paper score, current score, and proposed score. Identity, section,
   assignment, and mark-reading holds stay out of any push plan.

The September 21, 2026 manual-paper-credit reconciliation demonstrated this
rule set against a fresh read-only Canvas snapshot: it resolved the normalized
ledger by exact identity and section, preserved existing higher or excused
results, and held every unresolved identity. No grade was written to Canvas.

If visible workbook tabs are renamed, update the course-specific `tab_names`
binding before a refresh. A tab-binding preflight failure is a hold: never fall
back to similarly named or positional sheets. Restart the configured MCP
connection or use the launcher CLI after the binding change, then repeat the
fresh export and verification steps.

## Grade preview and confirmed push

`preview_gradebook_changes(course, snapshot_id, edits_filename)` accepts an
exported XLSX or a keyed JSON edit envelope in the private inbox. It compares
original, current Canvas, and proposed values and creates a private HTML
review. All Canvas-authored labels are escaped; the HTML runs no scripts.
Show that artifact to the teacher rather than pasting student rows into chat.

Pass the inbox basename only, using letters, digits, underscores, or hyphens and
the lowercase `.xlsx` or `.json` extension. Symlinks and files larger than
5,000,000 bytes are rejected; XLSX contents also have a 50,000,000-byte uncompressed
limit. A JSON envelope contains `course_id`, `snapshot_id`, and an `edits` array;
each edit has exactly `user_id`, `assignment_id`, and `value`. Use exact Canvas
identities from the private baseline. Comparisons reject more than 10,000 edits;
the confirmed push limit remains 25 changes.

The preview holds changed Canvas values/attempts, removed or invisible targets,
changed assignment grading, decreases, removed excusals, blank edits,
over-maximum scores, non-points assignments, and late-policy deductions.
Push preparation additionally refuses group, moderated, anonymous,
rubric-controlled, multi-part, and explicitly closed-period grading, or a grade
that no longer matches the current submission. Canvas remains responsible for
its permissions and grading-period enforcement when an API field is absent.

The confirmed write implementation is present and tested with synthetic data.
The tracked configuration omits `--enable-push` and does not allow
`confirm_gradebook_push`, so installing it leaves Canvas writes unavailable.
A September 20 deployment checkpoint recorded a locally enabled write tool;
that historical record is not evidence of the current running connection's
settings. Inspect the installed arguments and tool allowlist before a pilot.
Launching with `--enable-push` registers `confirm_gradebook_push`; a client tool
allowlist must also explicitly include it. Each operation still requires
approval of its exact private preview. No live student grade is needed as a
test write.

After enabling the write tool, the protocol is:

1. Prepare an exact push from a review. Resolve all holds first; no held cells
   are silently skipped. Each operation contains at most **25** changes.
2. Show the new private review and obtain approval of that exact operation.
   A token expires after ten minutes and is bound to an immutable plan. Later
   worksheet edits do not silently change the approved plan.
3. Confirm once. The server rechecks active enrollment and current grades,
   then checks each assignment/submission immediately before its single PUT.
   It records `sending` durably before the request and requires semantic GET
   readback before recording `verified`.
4. A partial failure stops later cells. Use status and read-only reconciliation.
   A timeout, HTTP 5xx, interrupted process, or failed readback never triggers
   an automatic retry. Unresolved targets remain locked against another push.
   Reconciliation can record `observed_applied`, which confirms the desired
   current value without claiming which actor wrote it.
5. Refresh the workbooks and review any remaining edits.

The write sends only numeric points or an explicit excusal. It does not send
comments/messages or change posting policies. **Existing Canvas posting policy
may make a confirmed grade visible to students.** Canvas also has no atomic
conditional-grade-write API: another grader can change a target between the
last GET and PUT. Coordinate the pilot with other graders; readback and durable
receipts do not make that race impossible.

Twenty-five sequential changes balance speed against the failure blast radius
and the cost of fresh checks/readback. There are several reads per change, plus
full-course preflight. The configured 180-second tool timeout is intended for
small deliberate batches, not unrestricted bulk publication. Read 429s receive
bounded backoff; writes never retry automatically.

## Private artifacts and recovery

`local_gradebooks/` is ignored by Git. The root has mode 0700 and files are
mode 0600. Content hashes detect changed snapshots/reviews/plans. Immutable
JSON artifacts are published atomically. SQLite uses full synchronous commits,
transactional token consumption, and per-target locks; process locks prevent
concurrent confirmation/reconciliation of one operation. Preserve the ledger,
snapshots, exports, and receipts. Do not delete a ledger or clear an uncertain
row to get past a hold.

`scripts/build_gradebook_workbooks.mjs` creates the initial files with the
artifact-tool runtime. `scripts/protect_gradebook_workbook.py` supplies XLSX
protection/hidden metadata missing from that renderer's API. Google conversion
loses Excel protection, so native protections were applied and read back.
These bootstrap scripts create the original three-tab Canvas/Working/_Sync
layout; they do not provision the current combined seven-visible-tab workbook or
replace its sheet bindings and reference tabs. Use the refresh protocol for the
existing workbook.
Current QA exports were checked against all saved grades and both visible tabs
were rendered with synthetic labels/scores for privacy-safe visual inspection.

## Validation

```sh
.venv/bin/ruff check src/ tests/
.venv/bin/mypy src/
.venv/bin/pytest tests/ -q
npm run build
npm test
```

Targeted regressions are the `tests/test_gradebook*.py` modules and
`tests/gradebook_menu_overlay.test.mjs`. They use
synthetic records and mocked HTTP, including partial failures and process
restart/readback. No real grade writes, model calls, or messages are needed.

API references:
- https://developerdocs.instructure.com/services/canvas/resources/submissions
- https://developerdocs.instructure.com/services/canvas/resources/enrollments
- https://developerdocs.instructure.com/services/canvas/resources/courses
- https://developers.google.com/workspace/sheets/api/reference/rest/v4/spreadsheets/batchUpdate

## Main-workbook migration checkpoint (2026-09-20)

Native XLSX readback verified both GET and Edit tabs against immutable snapshots: 120 Core students, 51 Advanced students, and zero pending edits. No Canvas writes were made. Settings outside the canvas-gradebook connection were preserved. Use the launcher CLI after any binding change so the updated tab names are read afresh. A push requires `--enable-push`, a prepared operation, explicit approval of its exact preview, and its single-use confirmation token; never use an actual grade write as a test.

This migration checkpoint predates the refresh worker. In the later activated
workflow, the menu queues an explicit refresh; push preparation and confirmation
remain separate gated operations. Editing a cell is not an automatic push.
Fresh installations follow the activation procedure in the
[worker runbook](sdm-gradebook-worker.md); an existing installation requires a
current heartbeat and operation readback, not another installation or a Git pull.
