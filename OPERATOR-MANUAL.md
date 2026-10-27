# Canvas MCP operator manual

Reference edition: 27 October 2026. Verified against maintained `main` commit [`2e9370466f687868b983c6d6035643edf860dff5`](https://github.com/sirdanielm/canvas-mcp/tree/2e9370466f687868b983c6d6035643edf860dff5).

This manual is for a teacher or local operator using Canvas MCP without needing a ChatGPT conversation. It is a reference, not an agent instruction file, controller, installation receipt, or authorization to change classroom records. Commands assume the repository root and a reviewed installation. Uppercase references such as `REQUEST_UUID` are placeholders to replace with actual private operation references. All student examples below are fictional; they are explanations, not live payloads.

## 1. Choose the correct surface

Canvas MCP contains several distinct systems. Choosing the right one prevents a content refresh from becoming a gradebook synchronization or a local draft from being mistaken for delivered feedback.

| Surface | Human access without ChatGPT | Main purpose and boundary |
| --- | --- | --- |
| General Canvas MCP server | Any compatible MCP client; Canvas web UI remains available | Canvas course/content tools, with role, write and account restrictions. It is an MCP service, not a command-line interface for every tool. |
| SDM authoring connection | Compatible MCP client or Canvas web UI | Narrow educator tool profile for curriculum drafts and organization; excludes student/submission/grading tools. |
| Course mirror | `scripts/course_mirror.py` | Content capture, offline QC, comparisons, file capture and local draft proposals. No apply/publish command. |
| Dedicated gradebook service | `scripts/sdm_gradebook_launcher.py --call ...` or MCP client | Private snapshots, comparisons, publisher previews, separately enabled score/comment delivery and batch controls. |
| GET-only workbook worker | CLI, installed workbook menu or installed Desktop shortcut | Refresh protected GET observations while preserving EDIT and its baseline. It writes the bound Google workbook, not Canvas grades. |
| LocalGrAss-to-EDIT bridge | Existing authenticated application objects and Python APIs | Stage an exact source-bound score/feedback pair in the existing workbook. No complete standalone human staging launcher is supplied here. |

The direct gradebook CLI constructs an in-process MCP client itself. It does not require ChatGPT, a model subscription, or the Codex connector installer. The general server has no equivalent generic `--call` option. Its tools can be called by another MCP application; a displayed conversational connector button is a client feature, not the only implementation of the operation. Do not invent a REST endpoint from an MCP tool name.

The installed source revision, client tool allowlist, running process and current account permissions can differ. A source merge does not update an operational checkout, restart its worker, or enable publication. [Installation reference](https://github.com/sirdanielm/canvas-mcp/blob/2e9370466f687868b983c6d6035643edf860dff5/docs/installation.md).

## 2. Installation, accounts and credentials

Use Python 3.11 or newer. For the general server in a new checkout:

```sh
python3 -m venv .venv
. .venv/bin/activate
pip install -e .
cp env.template .env
```

Privately configure `CANVAS_API_URL` with your institution's HTTPS origin ending in `/api/v1`, and `CANVAS_API_TOKEN` with your own institution-authorized token. Do not paste credentials into shell examples, public documents, worksheets or support tickets. Canvas commonly offers token creation under Account → Settings; institutions may require an IT-managed process instead. A role setting cannot grant privileges the Canvas account lacks. Resolve 401/403 responses using the intended account and institution policy.

The SDM macOS launchers use a different credential arrangement. They read the saved origin from `~/.config/canvas-authoring/connection.json` and the token from macOS Keychain, with no plaintext fallback. For a new SDM checkout:

```sh
uv sync --frozen --group dev --extra local-keychain
.venv/bin/python scripts/sdm_canvas_launcher.py --setup
.venv/bin/python scripts/sdm_canvas_launcher.py --check
.venv/bin/python scripts/sdm_canvas_launcher.py --verify
```

Setup prompts with hidden input, validates the proposed credential with one GET and saves it only after success. A rejected replacement preserves the previous credential. `--check` checks local configuration and credential availability without reaching Canvas. `--verify` makes one authenticated profile GET; it proves neither access to every course nor permission to manage grades. These launchers disable dotenv loading, so editing an unrelated `.env` does not repair their Keychain setup.

The dedicated SDM gradebook is deliberately bound to the configured FCPS origin and its `core` and `advanced` courses. It refuses a different origin. It is not a generic two-course launcher for arbitrary institutions. General server configuration is broader; changing one does not change the other. [Credential launcher](https://github.com/sirdanielm/canvas-mcp/blob/2e9370466f687868b983c6d6035643edf860dff5/scripts/sdm_canvas_launcher.py).

Google workbook access uses separate, approved Google OAuth credentials and the intended account. A working Canvas token supplies no Google access. The worker setup below uses a Desktop OAuth client with Sheets API enabled; the account must already have access to the exact bound workbook. Its Google scope can cover the account's spreadsheets, while the local transport restricts operations to the configured workbook.

For XLSX private archives, include `--extra local-exports` in the locked install. Preserve an existing operational environment until its worker is quiescent; installing dependencies in a new test environment is different from upgrading a loaded service.

## 3. Start and check the right process

In the general server environment:

```sh
canvas-mcp-server --test
canvas-mcp-server --config
canvas-mcp-server
```

`--test` checks Canvas connectivity. `--config` displays configuration; review it privately. The last command starts the default stdio MCP service and waits for a protocol client; it is not a human command prompt. `.venv/bin/canvas-mcp-server` avoids relying on an activated shell. The SDM Keychain equivalent is `.venv/bin/python scripts/sdm_canvas_launcher.py`, which starts the educator server with its constrained settings.

Use absolute executable paths and the correct working directory in the MCP client's configuration. A client registration check such as `codex mcp list` establishes registration, not Canvas health. Reconnect the affected client after authorized configuration changes and inspect the actual tools it exposes. There is no documented `/health` route to substitute for these checks. HTTP serving has additional authentication requirements: no server-wide `CANVAS_API_TOKEN`, a per-request `X-Canvas-Token`, and the required access gate. It is not a shortcut for publishing an unauthenticated local server. [Server entry point](https://github.com/sirdanielm/canvas-mcp/blob/2e9370466f687868b983c6d6035643edf860dff5/src/canvas_mcp/server.py).

The dedicated gradebook service starts with:

```sh
.venv/bin/python scripts/sdm_gradebook_launcher.py
```

For a one-shot read without an MCP desktop client:

```sh
.venv/bin/python scripts/sdm_gradebook_launcher.py --snapshot core
.venv/bin/python scripts/sdm_gradebook_launcher.py \
  --call get_canvas_gradebook --arguments '{"course":"core"}'
```

The second form also returns a capture receipt. Results identify private artifacts and aggregate counts; keep their contents local. Inspect the returned JSON, including any `error` field: a completed CLI call is not proof the requested tool succeeded. A successful snapshot proves the particular capture, not workbook freshness or publication permission.

`scripts/install_gradebook_connection.py --upgrade` updates recognized Codex configuration and makes a private backup. It requires an existing supported configuration and refuses unknown customizations. It is unnecessary for direct `--call` use. Its separate `--add-get-controls` and `--add-batch-controls` options install corresponding client entries; they do not activate a writer. [Gradebook launcher](https://github.com/sirdanielm/canvas-mcp/blob/2e9370466f687868b983c6d6035643edf860dff5/scripts/sdm_gradebook_launcher.py).

## 4. Identify courses, assignments and students correctly

Course titles and assignment names are useful labels, but exact IDs establish the destination. General course readers help inspect accessible courses; confirm the intended institution, course code and exact course before editing. The SDM CLI accepts `core` or `advanced` aliases that resolve to fixed source bindings. Workbook, sheet and protection IDs come from `config/sdm-gradebook-workbooks.json`; a tab with the right name alone is insufficient.

Permanent student PINs come from the central **Student Info** authority, joining `Email` to `Student Number` by header. Keep four-digit text, including leading zeros. Do not generate numbers from names, pad guessed values, or treat an assessment's `R1` label as a Canvas attempt. The shared private registry normally resides at `~/QuinnOperator/config/student-pin-source.json`; it pins the trusted roster bytes and schema. It remains outside source control and student-readable working folders.

Retain course, assignment, student, section, original evidence, form/policy and result revision for the applicable case. Before native staging or publication, independently bind the current Canvas target and observed attempt. Typed paper sources may retain an observed null attempt only with no submitted timestamp. Missing or inconsistent observations hold that downstream operation; an unknown Canvas attempt alone does not prevent separately admitted paper review. Missing evidence is not zero and does not hold unrelated eligible cases. A paper reassessment label does not supply a Canvas attempt. [Permanent PIN policy](https://github.com/sirdanielm/canvas-mcp/blob/2e9370466f687868b983c6d6035643edf860dff5/docs/STUDENT-PIN-POLICY.md), [typed attempt contract](https://github.com/sirdanielm/canvas-mcp/blob/2e9370466f687868b983c6d6035643edf860dff5/docs/teacher-edit-transfer.md#L85-L90).

## 5. Refresh the local gradebook without overwriting EDIT

GET tabs are protected observations. EDIT tabs contain teacher staging, scores, formulas and notes. Hidden Sync tabs retain provenance: `_Sync!B2` is the original Working baseline, while B5/B9 describe fresh GET observations. Routine GET-only refresh preserves B2 and every EDIT field. Newly observed Canvas students or assignments do not automatically expand EDIT coverage.

For a new authorized worker installation, configuration generation starts no service:

```sh
.venv/bin/python scripts/sdm_gradebook_worker.py configure
.venv/bin/python scripts/sdm_gradebook_worker.py authorize \
  --client-config /absolute/private/path/desktop-client.json
.venv/bin/python scripts/sdm_gradebook_worker.py --get-only doctor
```

Default private configuration is `~/.config/canvas-authoring/gradebook-worker.json`. `doctor` validates Google access and local baselines by reading; it does not establish Canvas authentication, Google write access or successful refresh. An explicitly authorized foreground worker uses:

```sh
.venv/bin/python scripts/sdm_gradebook_worker.py --get-only run
```

Keep `--get-only` before the subcommand. Omitting it selects the older full-sync mode, which has different preservation assumptions. Do not launch another worker alongside the installed one.

For daily operation, save and pause worksheet edits. Require mode-correct READY no more than 90 seconds old and a clear queue. Use the installed **Canvas Gradebook → Refresh both courses (Canvas GET only)** menu once, the installed **Canvas - Fresh GET** shortcut, or:

```sh
.venv/bin/python scripts/sdm_gradebook_worker.py --get-only request
.venv/bin/python scripts/sdm_gradebook_worker.py --get-only status \
  --request-id REQUEST_UUID
```

Record the request UUID. Resume editing only when that exact operation is VERIFIED, its preservation receipt is complete, `finalized: true`, and queue cleanup is confirmed. A request acknowledgment, populated tab or READY heartbeat is insufficient. The standalone Desktop script also supports `fresh-get` and `review`; these are refresh/review actions, never Canvas publishers.

Review EDIT through the installed shortcut or `review_gradebook_edits`. Its coverage summary can expose new GET identities missing from EDIT. Append-only and sparse coverage planners exist, but there is no registered self-service MCP/Desktop append action. They require an exact reviewed engineering operation with native preflight and complete readback. Do not use full sync to work around a helper formula or incompatible axes. [Worker runbook](https://github.com/sirdanielm/canvas-mcp/blob/2e9370466f687868b983c6d6035643edf860dff5/docs/sdm-gradebook-worker.md), [coverage reconciliation](https://github.com/sirdanielm/canvas-mcp/blob/2e9370466f687868b983c6d6035643edf860dff5/docs/gradebook-edit-axis-reconciliation.md).

## 6. QC, academic results and local EDIT staging

Canvas owns observations, exact targets, workbook integrity and transport. GrAss owns academic evidence/policy; sdmGrAss owns participation engines; LocalGrAss owns shared import/QC, saved results and authenticated review. Canvas MCP does not turn a missing scan into a score or authenticate a teacher decision from a caller-supplied boolean.

For fleet exports, keep unchanged originals and read the newest aggregate import/QC attempt from the installed harness. The documented locator is `~/Desktop/GrAss Local Checks/.fleet-importer/harness-path.txt`; use that harness's `scripts/local_check_status.py --json`. This reads status, not runs QC. A failed or unavailable newest attempt remains a hold; an older clean report cannot replace it. Process completion and diagnostic verdict are separate. Use the installed LocalGrAss/sdmGrAss workflow to run QC rather than inventing a Canvas command.

Three different staging situations matter:

1. **Accepted summative result:** an authenticated exact teacher decision binds final points and full feedback to the saved result. `LocalGrAssEditConnection` can stage that accepted pair through `LocalGrAssEditOwner`.
2. **Unapproved retained result:** `AuthenticatedProposalSource` or `AuthenticatedUnit1ProposalSource` supplies a current source-byte-verified advisory pair. `LocalGrAssProposalEditConnection` can stage it through the same owner with an explicit **UNAPPROVED** note. This creates no acceptance or delivery permission.
3. **Ordinary participation draft:** the qualified participation reader supplies score-only UNAPPROVED staging. The newer provider/current-attempt receiver remains a private operational overlay, not a portable broadly installed public workflow.

Saved teacher decisions or drafts hold conflicting proposal cases. Native preparation checks original baselines, exact target/attempt, current maximum/visibility/excusal and destination preimage. Higher existing grades and teacher content remain protected. Full feedback is retained in local notes for a paired result; note presence is not Canvas comment delivery.

### What a human can actually launch

This verified command checks private application configuration only:

```sh
.venv/bin/python -m canvas_mcp.gradebook.localgrass_application \
  --config /absolute/private/path/application.json \
  --config-sha256 EXACT_CONFIGURATION_SHA256 --check
```

`CONFIGURATION_VERIFIED` explicitly reports staging disabled and `real_case_checked: false`. It opens no database, creates no account/schema and makes no network call. It cannot stage a score.

Actual bridge use requires the existing application to supply its authenticated review/intake objects, Canvas and fixed-workbook Google clients, Store, RefreshJournal, pinned configuration and runtime guard to `build_owner_factory`. The resulting owner has asynchronous `prepare()` and `execute(plan_id, enabled=True)` methods; default execution is disabled. These are callable Python APIs, not a ready-made shell workflow. The proposal contracts use `result_id`; accepted contracts use `decision_id`. The accepted browser `build_application` deliberately rejects proposal configurations. A new operator must arrange/qualify this existing application wiring; this repository supplies no universal “stage this result” Desktop button or direct human launcher.

Typed Unit 1 mapping supports its admitted policy and explicit scale, including `UNIT1_WHOLE_PERCENT_100` decimal half-up mapping where qualified. Generic fictional scoring policies are ineligible. Joined synthetic tests establish source behavior; they do not activate a real case or qualify a changed installation. [EDIT transfer procedure](https://github.com/sirdanielm/canvas-mcp/blob/2e9370466f687868b983c6d6035643edf860dff5/docs/teacher-edit-transfer.md), [application source](https://github.com/sirdanielm/canvas-mcp/blob/2e9370466f687868b983c6d6035643edf860dff5/src/canvas_mcp/gradebook/localgrass_application.py).

## 7. Review and deliver scores and full feedback

Teacher acceptance, local staging and Canvas delivery are separate outcomes. For a summative pair retain one reviewed result's score and full feedback together, then verify the two outbound channels independently. Participation publication remains score-only, with analysis/provenance private.

`preview_gradebook_changes(course, snapshot_id, edits_filename)` compares a private inbox JSON/XLSX edit file with its immutable baseline and fresh Canvas. Native EDIT review provides a separate workbook-backed route. Reviews save private HTML and structured artifacts. Blank, decreased, stale, excused, unsupported or over-maximum changes hold; formulas and duplicate identities are not proposals. Review exact rows and reasons privately, not just a count.

`prepare_gradebook_push(course, review_id)` creates a concrete preview and one-use ten-minute confirmation. Default service configuration omits `confirm_gradebook_push`; actual score publication needs `--enable-push`, the relevant client allowlist when using an external MCP client, and exact teacher approval. The direct CLI still needs its enablement flag but no Codex client allowlist. A token binds the request; it is not evidence that a person reviewed it.

Scores do not send feedback or alter posting policy. Existing Canvas policy may make the new grade visible. Full comments use an independently retained private envelope and digest, `prepare_gradebook_comment_push(course, comments_filename, expected_envelope_sha256)`, and the separately enabled confirmation tool. `--enable-push` does not enable comments. Comments require `--enable-comments` and exact source/decision evidence; a worksheet note is not an outbound envelope. The legacy comment preview defaults to 600 seconds; `--comment-approval-seconds` accepts 600–1800 for future previews only.

For an approved larger workload, immutable batch APIs reduce repeated approval of unchanged chunks:

| Stage | API and outcome |
| --- | --- |
| Prepare scores | `prepare_gradebook_score_batch(course, review_id, approval_seconds=7200)` saves exact eligible chunks and holds. |
| Prepare comments | `prepare_gradebook_comment_batch(course, proposals=[{filename, envelope_sha256}], approval_seconds=7200)` binds exact private envelopes. |
| Authorize | `authorize_gradebook_batch(course, batch_id, confirmation_token)` records the reviewed grant; sends nothing. |
| Dispatch | `execute_gradebook_batch_chunk(course, batch_id, chunk_index)` sends at most 25 score targets or one exact comment. |
| Inspect/stop | `get_gradebook_batch_status` and `revoke_gradebook_batch` preserve original history. |

Grants last two hours by default, with preparation bounded to 600–28800 seconds. Unchanged chunks reuse that exact authorization. Each dispatch remains single-use and freshly checks source, identity, attempt, preimage and grant. Revocation/expiry blocks later sends. Never extend a stored expiry or regenerate a plan to conceal drift. Held targets stay quarantined while independent eligible chunks proceed. The launcher exposes these names through `--call`; use its returned private references, never student rows in arguments. [Publisher procedure](https://github.com/sirdanielm/canvas-mcp/blob/2e9370466f687868b983c6d6035643edf860dff5/docs/sdm-gradebook-workflow.md).

## 8. Reruns, uncertain writes, restart and backup

An operation records durable intent before transport. A timeout after a possible send is **UNCERTAIN**, not proof that nothing happened. Never resend, clear locks, delete the journal, switch state directories or recreate a plan to get around it. Score readback checks semantic state; comment readback additionally binds response-linked comment ID, exact author/body and protected context. `observed_applied` proves present state, not which actor caused it.

For GET-only worker recovery:

```sh
.venv/bin/python scripts/sdm_gradebook_worker.py diagnostics \
  --request-id REQUEST_UUID
.venv/bin/python scripts/sdm_gradebook_worker.py --get-only reconcile REQUEST_UUID
```

Diagnostics is local and read-only; recorded activity is not current remote READY. Reconciliation reads the original operation and native result, never resends grade data. Only an inspected and repaired pre-SENDING HELD request may use `--get-only release-held REQUEST_UUID --confirm`. UNCERTAIN/SENDING/VERIFYING cannot be released that way. Preserve its original mode.

Canvas publishers have their own `get_gradebook_push_status`, `reconcile_gradebook_push` and `reconcile_gradebook_comment_push`. Reconcile original child operations for uncertain batch chunks. Never replay completed/claimed dispatches or append feedback because a comment is currently absent. Local EDIT owners likewise switch retained attempts to readback-only reconciliation.

Before maintenance stop new requests, let active work finish and require no unresolved operations and a clear remote queue. Preserve the worker configuration, launch-agent plist, stable checkout paths and baseline store. Use the installed lifecycle controls; closing a terminal does not stop a login launch agent. After restart require fresh mode-correct READY. Do not duplicate a loaded worker.

Back up private configuration, immutable snapshots/plans/receipts, original exports and original staging/publisher/worker history as one consistent recovery set. Quiesce writers and use a consistent SQLite backup method; copying only the main database while active sidecars exist can lose evidence. Default private state is `local_gradebooks/`, directories 0700 and files 0600. It includes `push-ledger.sqlite3` and `refresh-worker/operations.sqlite3`. A new empty store cannot resolve existing `_Sync!B2` references or uncertain sends. Retain credentials separately in their approved stores. Restoration is a recovery operation, never a reason to replay completed work.

## 9. Downloads, local archives and reconciliation

The content mirror works without a conversational client:

```sh
.venv/bin/python scripts/course_mirror.py status
.venv/bin/python scripts/course_mirror.py get
.venv/bin/python scripts/course_mirror.py verify PATH_TO_SNAPSHOT
.venv/bin/python scripts/course_mirror.py audit PATH_TO_SNAPSHOT
.venv/bin/python scripts/course_mirror.py diff OLD_SNAPSHOT NEW_SNAPSHOT \
  --output local_gradebooks/course_mirror/reports/unique-delta.json
```

Choose the baseline explicitly. Every capture creates a new timestamped directory; failed captures remain INCOMPLETE and cannot be silently combined with later data. Use a QC-valid snapshot. `audit` can succeed while reporting findings, so inspect both QC and findings. Only `get` and `files-get` reach Canvas/read the saved credential; comparison commands are offline.

The base snapshot contains content metadata/bodies, not grades, submissions, all external resources or file bytes. `files-get SNAPSHOT PRIVATE_DESTINATION` downloads the exact captured Canvas file inventory; `assets-verify PRIVATE_DESTINATION SNAPSHOT` verifies it offline. Linked Google/LTI resources need their separate authorized source workflow. A collected hyperlink is not a student-visibility check or permission to export its target. Captures observe an interval, not an atomic or lossless Canvas backup. [Mirror reference](https://github.com/sirdanielm/canvas-mcp/blob/2e9370466f687868b983c6d6035643edf860dff5/docs/course-mirror.md).

For gradebook exports, retain original downloaded XLSX files privately. The export-based `prepare_gradebook_refresh`/`verify_gradebook_refresh` full-sync path is different from GET-only refresh and lacks native preservation coverage for arbitrary helpers/notes/layouts. It requires an exact compatible reviewed operation; do not use it as a routine fallback.

PIN archives are separate values-only private copies. `pseudonymize_gradebook_export.py preflight --source /absolute/private/export.xlsx --expected-source-sha256 EXACT_QC_SOURCE_SHA256` assesses compatibility without publishing an archive. Authorized `ingest` writes a new private destination outside Git. It uses the shared registry and LocalGrAss mapper, not a second roster. Unknown identity content, unsupported objects or changed hashes hold. `ARCHIVE_PUBLICATION_UNCERTAIN` requires inspecting that exact attempted destination before retrying. These archives are not operational refresh inputs or public anonymized datasets, and the post-QC automatic archive hook is not installed behavior. [Archive procedure](https://github.com/sirdanielm/canvas-mcp/blob/2e9370466f687868b983c6d6035643edf860dff5/docs/local-pin-exports.md).

## 10. Curriculum drafts and calendar authority

For unpublished curriculum work, use the narrow authoring client or Canvas UI. Confirm exact course/assignment IDs and reread existing objects before creating to prevent duplicates. New assignments default to unpublished; the SDM workflow temporarily uses `on_paper`, with the teacher initializing institution-specific Google Assignments LTI in Canvas. Supplying `external_tool` alone does not configure that complete launch.

Description-only changes should update only the description, using a fresh source hash and readback that confirms unchanged points, dates, submission types and visibility. The established rubric is an embedded HTML table; do not create a native rubric unless requested. Module, module-item and linked assignment publication are separate states. Publishing a populated container can affect children; reread the full tree and linked assignments after authorized release.

`course_mirror.py stage-description` and `repo-create`/`repo-diff` produce offline drafts marked `DRAFT_NOT_AUTHORIZED`. There is no mirror apply command. Apply an approved exact change through a separate supported authoring tool or Canvas UI, then read it back. Existing authorization for unchanged scope need not be repeatedly renewed, but draft creation does not authorize publication.

The maintained tool inventory contains no general calendar-event CRUD workflow. Assignment dates, section overrides and scheduled discussion posting are different from calendar event management. A/B-day overrides are normal, not errors to erase. The mirror does not capture complete exact override endpoint records; read them through an appropriate authorized route before scheduling changes. Use the institution's actual calendar and explicit teacher decisions as scheduling authority. An old course snapshot or a Google Calendar observation does not itself authorize Canvas date changes. [Authoring procedure](https://github.com/sirdanielm/canvas-mcp/blob/2e9370466f687868b983c6d6035643edf860dff5/docs/sdm-canvas-authoring-workflow.md).

## 11. Synthetic worked examples

**A summative pair.** Fictional student PIN `0042`, fictional assignment `900001`, has an admitted 17/20 result and complete feedback. QC verifies evidence membership, policy, identity and actual attempt. A teacher may accept a correction to 18/20 with revised full feedback, producing a decision bound to that result. The qualified accepted bridge stages the exact pair in EDIT and verifies complete preservation. A fresh review then prepares the score publisher and a separate source-bound comment envelope. Approve the concrete intended delivery, send each enabled channel once, and retain independent score and comment readbacks. A visible 18/20 alone does not prove the feedback arrived.

**An ordinary draft.** Fictional participation evidence supports 4/5. The qualified participation route stages an UNAPPROVED score proposal; analysis stays private. A higher existing 5/5 or teacher-owned conflicting note holds that case. Resolve it without overwriting teacher work; continue another independent ready case. Final score approval precedes score-only publication. Do not convert the analysis note into a student comment.

**A lost response.** An approved comment send times out. Keep its operation/envelope/ledger and inspect the original status. Reconcile author, body and retained comment identity using the existing GET-only recovery. Do not prepare an identical “replacement” comment to make progress. A later missing comment still cannot prove the first append was never sent.

## 12. Canonical files, contracts and consumers

| File or contract | Producer/consumer and meaning |
| --- | --- |
| `config/sdm-gradebook-workbooks.json` | Exact course/workbook/tab/protection bindings read by gradebook and worker. |
| `config/sdm-*.toml.example` | Client configuration examples; not proof of active installed settings. |
| `local_gradebooks/snapshot-HASH.json`, `review-HASH.json`, `refresh-HASH.json`, `push-HASH.json`, `receipt-HASH.json` | Content-addressed private Store artifacts; their hashes and original histories are checked by consumers. |
| `local_gradebooks/inbox/NAME.json` or `NAME.xlsx` | Explicit bounded private inputs; tools take filenames instead of arbitrary filesystem/student payloads. |
| `push-ledger.sqlite3` | Publisher operations, tokens, target locks and batch grants/chunks. |
| `refresh-worker/operations.sqlite3` | Worker operation and recovery history consumed by worker/Desktop diagnostics. |
| `_Sync!B2` / `_Sync!B9` | Original Working baseline / latest protected GET observation reference. |
| `LOCALGRASS_EDIT_APPLICATION_V1`, `LOCALGRASS_EDIT_UNIT1_APPLICATION_V1` | Accepted generic/typed application configurations; bind `decision_id`. |
| `LOCALGRASS_PROPOSAL_EDIT_APP_V1`, `LOCALGRASS_PROPOSAL_EDIT_U1_APP_V1` | Unapproved generic/typed configured owner factories; bind `result_id`. |
| `LOCALGRASS_UNAPPROVED_EDIT_V1` | Proposal connection plan; no academic acceptance or delivery authorization. |
| `DRAFT_NOT_AUTHORIZED` | Content proposal/workspace comparison status, never a publish instruction. |

Use returned artifact paths/references rather than guessing generated filenames. Keep captured HTML untrusted; do not execute it in an unrestricted browser. Public reports should contain aggregate outcomes and bounded errors, not records, signed URLs, originals or private receipts.

## 13. Troubleshooting and contribution

| Symptom | Next useful check |
| --- | --- |
| Tool absent | Check which server/client is loaded, role, allowlist and separate enablement. Do not bypass it with TypeScript or raw requests. |
| Authentication fails | Separate local Keychain availability, one-GET verification and exact course permissions; resolve the intended account. |
| Doctor passes but refresh fails | Doctor does not prove Canvas/write readiness; inspect fresh READY and the exact request receipt. |
| Request watcher closes | Inspect the same UUID; the background operation may still be active. |
| New GET rows absent in EDIT | Review coverage; use a separately reviewed append operation, not full-sync substitution. |
| Proposal configuration verifies but nothing stages | Expected: check CLI is validation-only; qualify existing application/owner wiring. |
| Grade matches but feedback absent | Inspect separate comment envelope, enablement, operation and readback. |
| Rerun blocked by history/preimage | Preserve it; reconcile the original operation or resolve an actual pre-send conflict. |
| Archive preflight holds | Preserve QC originals and resolve exact identity/content compatibility; no partial “clean” copy. |

To contribute documentation, use a reviewed `docs/` branch/PR and perform link, formatting, command-contract and privacy review. Prose-only work does not require fabricated runtime tests; applicable required CI still applies before promotion. `docs/` is the public website upload root, so private bindings, credentials, student records and operational backups never belong there. Website publication is a separate manual deployment. Keep this operator reference separate from `AGENTS.md`/`CLAUDE.md`; changing this manual does not create new agent rules, restart services, admit academic cases or enable writers. [Contribution guidance](https://github.com/sirdanielm/canvas-mcp/blob/2e9370466f687868b983c6d6035643edf860dff5/CLAUDE.md), [documentation map](https://github.com/sirdanielm/canvas-mcp/blob/2e9370466f687868b983c6d6035643edf860dff5/docs/documentation-map.md).
