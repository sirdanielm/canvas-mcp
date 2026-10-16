# SDM Canvas gradebooks

Use this guide for the central FDHS Chemistry workbook, private score reviews,
and separately authorized Canvas delivery. See [goals and status](goals-and-status.md)
for the dated operational result, remaining holds and next work. Source availability,
local installation, teacher approval and verified delivery are different states.

## Everyday use

| Surface | What is available |
| --- | --- |
| This source tree | Protected GET-only worker, native EDIT review, Desktop/menu controls, private Canvas snapshots, export-based full sync, exact score preview/push, and a separately enabled comment lane. |
| Reviewed local installation | Only the configured tools and loaded worker mode are available. Verify installation, fresh READY and exact receipts before use. |

Source synchronization does not install controls, reconnect shared services or
verify their liveness.

For the reviewed GET-only installation, save and pause worksheet editing, keep the
Mac awake and online, and choose **Canvas Gradebook → Refresh both courses
(Canvas GET only)** once. Reload the workbook to load the repaired FDHS menu.
Require READY no more than 90 seconds old advertising GET_ONLY before requesting
work;
wait for that exact request's VERIFIED, finalized receipt and cleared queue
before editing again. A populated tab, successful request or READY heartbeat
alone is not completion. If the menu is stale, use the reviewed installed
**Canvas - Fresh GET** shortcut; do not run legacy workbench setup.

**Canvas - Review EDIT** makes a private comparison, not a push. Fresh GET
preserves every EDIT value, formula, feedback note, layout field and `_Sync!B2`.
New students or assignments can appear in GET without moving EDIT cells.
Additional EDIT coverage needs a separately reviewed append plan and complete
readback. Notes on EDIT are teacher staging, not delivered Canvas comments.

The workbook roles are Core/Adv GET, Core/Adv Edit, Student Info, Assignment and
Grader Proposals, plus hidden course Sync tabs. Exact bindings live in
`config/sdm-gradebook-workbooks.json`; names do not establish ownership. Preserve
reference tabs and permanent numbers.

### Historical legacy GET menu error

A legacy **GrAss Submissions** action targeted a different workbench layout.
Do not clear ownership guards to bypass it. The explanation and original
activation records remain in the
[immutable September guide](https://github.com/sirdanielm/canvas-mcp/blob/d0794b247df2b865150c4805d816b9075768ae92/docs/sdm-gradebook-workflow.md#historical-legacy-get-menu-error).
A Git pull does not update Apps Script, restart the worker or verify its liveness.

## Permanent PINs for local copies

`Student Info` is the shared identity authority: map `Email` to `Student Number`,
preserving four-digit text and leading zeros. Its name fields are `Canvas Name`,
`IC Name` and `Roster Name`; the historical `Student Numbers` layout is obsolete.
Use the registry-bound exporter for local copies. Never guess, regenerate,
renumber or recycle a PIN. Missing or conflicting joins remain held. See the
[Student PIN policy](STUDENT-PIN-POLICY.md); originals and private crosswalks stay
outside Git and public reports.

## Available tools

These belong to the separate gradebook connection, rather than the general
Canvas MCP server and its tool manifest:

| Tool | Result |
| --- | --- |
| `get_canvas_gradebook` | Complete private Canvas snapshot; aggregate counts. |
| `preview_gradebook_changes` | Fresh comparison and private HTML review. |
| `prepare_gradebook_refresh` | Export-based full-sync plan preserving pending drafts. |
| `verify_gradebook_refresh` | Before/after verification of that exact export-based plan. |
| `prepare_gradebook_push` | Exact review and expiring confirmation; no Canvas write. |
| `get_gradebook_push_status` | Durable aggregate operation status. |
| `reconcile_gradebook_push` | GET-only recovery; never resends. |
| `request_gradebook_get_refresh` | Queue one protected GET refresh for both courses. |
| `get_gradebook_get_refresh_status` | Inspect that request's durable aggregate preservation receipt. |
| `review_gradebook_edits` | Compare native EDIT proposals with fresh Canvas; save a private review. |
| `select_gradebook_review_batch` | Select up to 25 ready rows from an existing review, retaining its evidence time and holds. |

The four controller tools require the existing local worker configuration,
matching state store and explicit client allowlist entries. Missing controls do
not permit a workaround. They add no publication authority. A ready batch still
requires teacher review and the publisher's exact preview and confirmation.
The general connector's `ALLOWED_WRITE_TOOLS` does not replace this server's
separate grade/comment enablement and exact approvals.

### Local setup

Run from the stable checkout:

```sh
uv sync --frozen --group dev --extra local-keychain
.venv/bin/python scripts/install_gradebook_connection.py --upgrade
.venv/bin/python scripts/sdm_gradebook_launcher.py --snapshot core
```

If the Canvas connection is missing, run `scripts/Setup Canvas Connection.command`
interactively. It validates with GET and stores the token in macOS Keychain;
only the origin is saved in `~/.config/canvas-authoring/connection.json`.
The configured FCPS classes require `https://fcps.instructure.com` and confirmed
`manage_grades` permission. Never put credentials in tool arguments or worksheets.

The installer requires an existing Codex configuration, backs it up privately
and refuses unknown customizations. Review paths in `config/sdm-gradebook.toml.example`.
Default installation does not enable publication. Reconnect only the affected
connection when needed. An available tool can also run through the CLI:

```sh
.venv/bin/python scripts/sdm_gradebook_launcher.py --call get_canvas_gradebook \
  --arguments '{"course":"core"}'
```

Keep one private state store; `--state-dir` changes it and empty replacements
cannot resolve baselines. Changed bindings require a reviewed new process.

## Agent refresh protocol

Use the reviewed GET-only worker for routine freshness while preserving EDIT:

1. Save and pause worksheet edits. Require fresh READY in GET_ONLY mode and
   a clear queue; request `REFRESH_GET_BOTH` once through the menu, Desktop
   shortcut, `--get-only request` or `request_gradebook_get_refresh`.
2. Retain its request UUID. Inspect the same operation with `--get-only status`
   or `get_gradebook_get_refresh_status`; a local status alone is not liveness.
3. Require its complete native VERIFIED preservation receipt and `finalized: true`
   before resuming edits. `_Sync!B5` and B9 describe fresh GET, while B2 and the
   historical pending count in B10 remain unchanged.
4. Review proposals through `review_gradebook_edits` or **Canvas - Review EDIT**.
   Inspect the separate exact-ID coverage summary. New GET targets require a
   separately reviewed [EDIT append plan](gradebook-edit-axis-reconciliation.md)
   with durable preflight/readback; coverage warnings do not approve scores.

A pre-send HELD operation needs its saved cause repaired and an explicit
mode-correct `release-held REQUEST_UUID --confirm`, then fresh READY before a
new request. UNCERTAIN or any possible send permits reconciliation only, never
release or replay. Use the [worker runbook](sdm-gradebook-worker.md) for recovery.

### Export-based full sync

`prepare_gradebook_refresh` and `verify_gradebook_refresh` remain full-sync XLSX
tools. They do not preserve arbitrary EDIT helpers, notes or divergent axes and
are not a fallback for GET/EDIT shape differences or helper-formula holds. Keep
all editors idle; Sheets offers no compare-and-swap across read and batch update.
For a separately authorized, compatible full-sync operation:

1. Export the exact bound workbook as XLSX into the mode-0600 private inbox.
   Decode the raw export without printing student rows or signed URLs.
2. Resolve `_Sync!B2` to its immutable local baseline; call
   `prepare_gradebook_refresh(course, snapshot_id, workbook_filename)`.
3. Export again and call `verify_gradebook_refresh(..., phase="before")`.
   Stop on any changed input or expired five-minute plan.
4. Only with authorization for that exact Sheets operation, send the saved
   `batch_update` once. Do not recreate or replace the workbook.
5. Export again and verify `phase="after"`. Preserve both exports and the plan
   on failure; never blindly replay the batch.

`_Sync` means the bound course tab. XLSX checks mapped literal values/identities,
not native notes, formatting, protections or references. See the stronger native
checks in [the runbook](sdm-gradebook-worker.md). Full-sync pending proposals retain
their original baseline; achieved proposals resolve without another write.
Changed grading schema, removed targets or unsafe drafts hold the operation.

## Manual paper-credit reconciliation

Verify paper evidence before any proposal: the printed ledger/date, one active
identity/section join, the exact published points assignment and explicit credit
policy. Preserve excusals and equal or higher Canvas scores. Ambiguous marks,
identities or criteria remain held. A missing scan is not proof of no paper work,
and a check mark is not permission to invent a score. Save the private evidence
and target mapping; source acceptance and delivery need separate approvals.

## Grade preview and confirmed push

Preview compares original, current Canvas and proposed values. Blank, decreased,
stale, excused, over-maximum and unsupported edits remain held. Preparation
also checks assignment visibility, grading periods, current submission, late
policy and unsupported group/rubric/anonymous/moderated/multipart contexts.
Formula cells and duplicate identities are never score proposals.

The default connection omits `confirm_gradebook_push`. A reviewed installation
needs both `--enable-push` and its explicit client allowlist entry. Each operation
still requires approval of the exact private preview:

1. Prepare at most 25 changes; resolve every hold.
2. Review the immutable operation and approve its exact scope. Its one-use
   confirmation expires after ten minutes.
3. Confirm once. Fresh checks run immediately before each PUT; durable
   `sending` precedes transport, and semantic GET readback establishes success.
4. A partial failure stops later targets. Inspect status and reconcile the same
   operation; uncertain targets remain locked. `observed_applied` proves the
   present result, not which actor wrote it.

A score match alone does not establish unchanged attempts, visibility or grading
context. A numeric/EX push sends no feedback and changes no posting policy.
Existing Canvas policy may make grades visible. Coordinate with other graders:
Canvas has no atomic conditional-write API, and readback cannot eliminate the
race between the final GET and PUT.

## Separately reviewed student comments

The maintained comment lane is disabled by default and separate from scores.
It does not connect an academic provider or the LocalGrAss accepted-pair release
bridge. `--enable-push` does not enable it. An exact comment proposal needs an
independently retained envelope digest and source/decision evidence; actual
append also needs `--enable-comments`, the client allowlist and exact approval.

Use `prepare_gradebook_comment_push` for preview,
`confirm_gradebook_comment_push` once for delivery, and
`reconcile_gradebook_comment_push` for GET-only recovery. Store proposals in the
private inbox; pass filenames/digests, not student rows. The supported categories
and complete fictional schema remain in the
[baseline contract](https://github.com/sirdanielm/canvas-mcp/blob/d0794b247df2b865150c4805d816b9075768ae92/docs/sdm-gradebook-workflow.md#separately-reviewed-student-comments).

Confirmation holds changed identities, attempts, source bytes or grading context.
It sends only approved text, non-group intent and the uploaded attempt when
applicable; paper work never acquires an invented upload attempt. Readback must
match the response-linked comment ID, exact author/body and protected state.
A lost reply remains uncertain or becomes independently `observed_applied`;
neither permits re-appending. Preserve consumed tokens and historical claims.
Current comment absence does not prove an old request was never sent. Score
parity, worksheet notes and a successful GET refresh do not verify feedback.

## Private artifacts and recovery

Keep `local_gradebooks/` ignored: directories 0700, files 0600. Preserve snapshots,
reviews, exports, receipts and the FULL-synchronous ledger. Never clear uncertain
rows or locks to permit another send. Report aggregates only. Bootstrap scripts
do not provision the combined workbook or repair ownership mismatches.

## Validation

Use fictional controlled transports; no real student write is needed to test:

```sh
.venv/bin/python -m pytest tests/ -q
.venv/bin/ruff check src/ tests/
.venv/bin/mypy src/
node --test tests/gradebook_menu_overlay.test.mjs
```

Tests, source synchronization and old activation receipts do not establish live
READY, fresh source, teacher approval or delivery. Preserve the exact result of
failed/incomplete verification rather than substituting an older clean receipt.

## Main-workbook migration checkpoint (2026-09-20)

Historical layout, counts and activation logs remain in the
[immutable baseline](https://github.com/sirdanielm/canvas-mcp/blob/d0794b247df2b865150c4805d816b9075768ae92/docs/sdm-gradebook-workflow.md#main-workbook-migration-checkpoint-2026-09-20).
They are not current inventory or liveness evidence.

## Receipt-bound LocalGrAss handoff

The [capture contract](grass-capture-contract.md) joins exact Canvas scope and
permanent PINs through a producer-bound private receipt. The intended flow takes
Canvas submissions and teacher-folder/paper evidence through the grading
pipeline, retains paired score and feedback from the same saved result, then
uses local tools to stage reviewed EDIT proposals. The general transfer from a
revision-bound teacher decision into EDIT remains integration work. Existing
protected Grader Proposals intake does not establish that connection.

Source/policy, teacher acceptance and scoped release gates remain independently
owned. A capture, EDIT proposal or Git merge does not establish teacher approval
or Canvas delivery. See [integration boundaries](grass-workflow-integration.md)
and the [current goals](goals-and-status.md).
