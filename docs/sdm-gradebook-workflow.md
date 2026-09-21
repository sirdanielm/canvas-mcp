# SDM Canvas gradebooks

The main workbook is [FDHS Chemistry Gradebook — 2026–2027](https://docs.google.com/spreadsheets/d/13ps0FZLBj2qpclMNKo7Eb95kE4Sb_fgf9s7Ki2_KoNc/edit). Its existing sharing permissions are unchanged. It has six visible tabs:

1. Core GET
2. Adv GET
3. Core Edit
4. Adv Edit
5. Student Info
6. Assignment

The mirror tabs are protected GET-only snapshots. The edit tabs have the same layout, with only score cells editable. Student Info retains all 173 permanent numbers, including two students outside the current active roster; never renumber or recycle them. Assignment contains all 52 Canvas assignments, including those outside the published, graded mirror scope, plus prior IC mappings. Refreshing grade tabs must preserve both reference tabs; reconcile their metadata separately by exact IDs, retaining IC fields and permanent numbers.

`_Core Sync` and `_Adv Sync` are hidden system tabs. Course-specific `tab_names` in the binding file normalize these names to the internal Canvas/Working/_Sync roles. The previous standalone workbooks and the user's [backup](https://docs.google.com/spreadsheets/d/1CKIzzHVaSilKa8Aeo8D9sVsTldblQmRRNGuLBD6pUNQ/edit) remain available. The 36 old tabs were removed from the main workbook only after full replacement readback and backup/student-number checks.
The course/workbook/sheet bindings are in `config/sdm-gradebook-workbooks.json`.
No student data is stored in that configuration or in Git.

## Everyday use

Ask Codex to **refresh both Canvas gradebooks** or **preview the changes in my
Core gradebook**. The workflow uses the Canvas gradebook MCP together with the
connected Google Drive tools. It currently needs the agent to perform that
exchange; there is no Apps Script menu, background poller, or direct Google
credential in the Canvas server.

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

The installed connection exposes seven read-only tools, plus the separately confirmed push tool when enabled:

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

Install or upgrade the recognized initial two-tool entry:

```sh
.venv/bin/python scripts/install_gradebook_connection.py --upgrade
```

The installer preserves unrelated settings, saves a private configuration
backup, and refuses unknown customizations. Reload/reconnect the desktop MCP
connection if an existing task still has the earlier tool list. A CLI invocation
of the same MCP tool is also available:

```sh
.venv/bin/python scripts/sdm_gradebook_launcher.py --call get_canvas_gradebook \
  --arguments '{"course":"core"}'
```

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

A refresh merges untouched cells from Canvas while retaining local edits.
Every pending cell also retains its **original** baseline in a content-addressed
working-baseline artifact. Thus, a changed Canvas grade remains a conflict
through repeated refreshes. When Canvas already matches a proposal (including
after a successful push), that edit is fulfilled and clears without another
write. `_Sync!B9` points to the actual current Canvas
snapshot; `_Sync!B2` points to the working baseline, which may retain older
observations for pending cells. If roster or assignment grading schema changes
while edits are pending, refresh stops and preserves the existing workbook.

The supported grid is currently up to 995 students and 256 assignments. Grade columns expand as later assignments are published; larger courses stop rather than truncate. The published assignment count is read from each fresh Canvas snapshot rather than hardcoded. Submission workflow, attempt, timestamps and flags are stored in grade-cell notes, in addition to status colors.

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

The preview holds changed Canvas values/attempts, removed or invisible targets,
changed assignment grading, decreases, removed excusals, blank edits,
over-maximum scores, non-points assignments, and late-policy deductions.
Push preparation additionally refuses group, moderated, anonymous,
rubric-controlled, multi-part, and explicitly closed-period grading, or a grade
that no longer matches the current submission. Canvas remains responsible for
its permissions and grading-period enforcement when an API field is absent.

The confirmed write implementation is present and tested with synthetic data.
**It is enabled in the local connection configuration as of September 20, with prompt approval required for each confirmation. Reconnect the canvas-gradebook connection to load the new configuration.** Launching with
`--enable-push` registers `confirm_gradebook_push`; a client tool allowlist must
also explicitly include it. Enable this only for a reviewed pilot. No live
student grade has been used as a test write.

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

Targeted regressions are the four `tests/test_gradebook*.py` modules. They use
synthetic records and mocked HTTP, including partial failures and process
restart/readback. No real grade writes, model calls, or messages are needed.

API references:
- https://developerdocs.instructure.com/services/canvas/resources/submissions
- https://developerdocs.instructure.com/services/canvas/resources/enrollments
- https://developerdocs.instructure.com/services/canvas/resources/courses
- https://developers.google.com/workspace/sheets/api/reference/rest/v4/spreadsheets/batchUpdate

## Main-workbook migration checkpoint (2026-09-20)

Native XLSX readback verified both GET and Edit tabs against immutable snapshots: 120 Core students, 51 Advanced students, and zero pending edits. No Canvas writes were made. Settings outside the canvas-gradebook connection were preserved. Use the launcher CLI after any binding change so the updated tab names are read afresh. A push requires `--enable-push`, a prepared operation, explicit approval of its exact preview, and its single-use confirmation token; never use an actual grade write as a test.

Live connection behavior follows the [official MCP configuration reference](https://learn.chatgpt.com/docs/extend/mcp?surface=cli). Refresh and push are requested through the agent; editing a cell is not an automatic push, and no in-Sheets button or background schedule was installed.
