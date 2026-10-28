# Local Canvas gradebook refresh worker

The worker reads Canvas and updates the bound Google workbook. It imports no
Canvas publisher and has no grade/comment send path. Use this runbook with the
[gradebook workflow](sdm-gradebook-workflow.md) and [goals and status](goals-and-status.md).

**Source and runtime:** this source tree includes protected GET-only refresh,
native EDIT review and Desktop/menu controls, alongside the older full-sync
mode. Routine refresh uses `--get-only`; omitting that flag selects full sync.
Git synchronization does not install, restart or verify the local worker or
FDHS Apps Script menu. Verify the reviewed installation, its mode and fresh
READY before requesting work.

## Architecture and authority

An explicit request fixes both courses, workbook and operation identity. Complete
Canvas capture and fresh native preflight precede one atomic Sheets grade-data
batch. Complete readback and durable coordination cleanup establish completion.

Full sync uses `service.prepare_refresh` and preserves pending score drafts with
their original baselines. It can reconcile GET/EDIT axes; it is not the routine
fallback for helper formulas, custom notes or incompatible proposal layouts.
GET-only mode refreshes protected GET tabs and observation metadata while
preserving every EDIT field and `_Sync!B2`. `_Sync!B5` and `_Sync!B9` describe
the fresh GET; the original baseline in B2 and historical pending count in B10
remain unchanged. Reference tabs and permanent PINs stay unchanged. New GET
coverage does not authorize an EDIT append or Canvas publication.

Ownership requires exact IDs/bindings, not names. Native readback checks selected
values, formats, notes, validations, dimensions, protections, rules and filters,
including unrelated tabs. It does not certify every Sheets feature; owned
generated borders have a shared-edge exception. XLSX checks are narrower.

Canvas uses the existing macOS Keychain connection. Google OAuth uses the
existing approved account with access to the bound workbook. Its Sheets scope
covers that account's spreadsheets; the single-workbook restriction is a local
transport guard. Credentials stay outside Git, cells, Apps Script and logs.
FDHS authorization is required to alter the institutional bound script; workbook
reads do not justify changing login profiles, granting scopes or rewriting script
source. Preserve the existing approved credentials unless setup is authorized.

## Everyday use and local operation

For the reviewed GET-only installation, keep the Mac awake, online and able
to use Keychain.
Reload the workbook to load the repaired FDHS menu. Save and pause all worksheet
editing, request **Refresh both courses (Canvas GET only)** once, and use
**Show refresh progress**. New requests use `REFRESH_GET_BOTH`. Before admission,
require READY no more than 90 seconds old in GET_ONLY mode and a clear queue;
a legacy or full-sync heartbeat cannot admit them. Before resuming edits, require
the exact request VERIFIED,
its complete preservation receipt finalized, and queue cleanup confirmed.

**Canvas - Fresh GET** uses the same queue; **Canvas - Review EDIT** only opens
private comparisons. Neither publishes or runs imports/QC. A UUID, updated tab
or READY alone is insufficient. A timed-out watcher may leave work active;
inspect that request instead of queueing another.

The login launch agent polls metadata and reads Canvas only for explicit
requests. Closing a terminal does not stop it. From the stable checkout:

```sh
.venv/bin/python scripts/sdm_gradebook_worker.py --get-only status
.venv/bin/python scripts/sdm_gradebook_worker.py --get-only status --request-id REQUEST_UUID
launchctl print "gui/$(id -u)/org.sdm.canvas-gradebook-refresh"
```

Queue one request, then inspect that same operation:

```sh
.venv/bin/python scripts/sdm_gradebook_worker.py --get-only request
.venv/bin/python scripts/sdm_gradebook_worker.py --get-only status
```

A request acknowledgement is not completion. The configured gradebook MCP
also exposes `request_gradebook_get_refresh` and
`get_gradebook_get_refresh_status` when its local controller is available.
Require the exact request's complete native VERIFIED receipt with
`finalized: true`. Local journal status does not establish current worker
liveness, and an unknown response never permits a blind repeat.

### Local diagnostics without network or state changes

```sh
.venv/bin/python scripts/sdm_gradebook_worker.py diagnostics
.venv/bin/python scripts/sdm_gradebook_worker.py diagnostics --request-id REQUEST_UUID
```

Diagnostics reads existing SQLite and bounded private telemetry without network,
credentials or filesystem changes. Read-only/immutable SQLite, active-sidecar
checks and inventory bounds prevent incomplete clean results. Unsafe logs are
ignored.

Output contains aggregate phases/ages, recognized failures and startup pins;
arbitrary exception text is suppressed. `worker_running` remains unverified:
recorded activity is not remote READY. Telemetry uses private bounded rotation
and bounded inspection. Diagnostics never authorizes retries.
No tokens, URLs, bodies, student records or cell addresses enter telemetry.
Startup hashes do not prove later edits are loaded by an old process.

For routine maintenance, first stop new requests, confirm zero unresolved
operations and a clear remote queue, and let active work finish. Resolve holds
before changing code, dependencies, bindings or checkout paths. When quiescent:

```sh
launchctl bootout "gui/$(id -u)/org.sdm.canvas-gradebook-refresh"
# After reviewed maintenance and the correct mode's doctor check:
launchctl bootstrap "gui/$(id -u)" \
  "$HOME/Library/LaunchAgents/org.sdm.canvas-gradebook-refresh.plist"
launchctl print "gui/$(id -u)/org.sdm.canvas-gradebook-refresh"
```

Preserve plist, configuration, checkout and baselines. Never duplicate a loaded
worker; require fresh mode-correct READY after restart.

## Setup and activation

For a new, authorized installation, preserve any existing worker configuration
and state. Never replace an installed worker with a different operation mode or
activate full sync against incompatible/sparse EDIT. From the reviewed checkout:

```sh
uv sync --frozen --group dev --extra local-keychain
.venv/bin/python scripts/sdm_gradebook_worker.py configure
```

`configure` creates, never overwrites, private configuration; it starts nothing.
Default: `~/.config/canvas-authoring/gradebook-worker.json`. Keep the MCP baseline
store; an empty replacement cannot resolve existing references.

For authorized Google setup, enable Sheets API in the approved project, configure
the permitted OAuth audience and retain a Desktop client JSON privately:

```sh
.venv/bin/python scripts/sdm_gradebook_worker.py authorize \
  --client-config /absolute/private/path/desktop-client.json
.venv/bin/python scripts/sdm_gradebook_worker.py --get-only doctor
```

Consent uses PKCE, random state and a short-lived loopback callback; credentials
are created exclusively with mode 0600. `doctor` reads Google and validates local
baselines; it writes neither Sheets nor Canvas and publishes no heartbeat. It
does not prove Canvas authentication, Google write access or successful refresh.
GET-only doctor validates the preservation-compatible workbook; it does not
approve full-sync operation or EDIT coverage changes.

Authorized Apps Script edits require the FDHS account. Verify parent workbook,
back up the entire project, preserve legacy runtime/manifest, compare fresh
source, update once and read back everything. Uncertainty requires readback,
never replay. Reload the workbook; a stale label does not justify replacement.

An authorized foreground GET-only pilot uses `--get-only run`. Generate its
reviewable launch-agent template with:

```sh
.venv/bin/python scripts/sdm_gradebook_worker.py --get-only launch-agent \
  --output /absolute/private/path/org.sdm.canvas-gradebook-refresh.plist
```

Generation starts/installs nothing. Review paths and mode before authorized
activation; retain the GET-only flag. Verify complete request/readback
and advancing READY before background use; tests are insufficient.

## Coordination and crash recovery

Request/claim/applied/status/heartbeat metadata contains no student records or
credentials. Editors can see it; it is coordination, not authority. Document and
file locks prevent duplicate admission; ownership/nonce checks detect competing
workers.

SQLite FULL commits and immutable private manifests precede dispatch:

`CLAIMING → CLAIMED → PREPARED → SENDING → VERIFYING → VERIFIED`

A failure before send becomes HELD; any possible send without verified readback
becomes UNCERTAIN. Preserve the original mode, identity, preimage and manifest.
Absent markers, empty SQL fields or currently missing grades/comments do not
establish that an old write never occurred.

```sh
.venv/bin/python scripts/sdm_gradebook_worker.py --get-only reconcile REQUEST_UUID
```

Reconciliation reads the original operation and native result; it never resends
grade data. It accepts SENDING, VERIFYING, UNCERTAIN and VERIFIED, not HELD.
Retain `--get-only` for a GET-only operation; use the original full-sync mode
only for an operation recorded in that mode. Recovery validates the persisted
mode, rather than treating absent legacy fields as a GET-only receipt. Require
verified receipt plus finalized cleanup; never change modes to force recovery.

Only after inspecting and repairing an explicitly **pre-SENDING** hold may an
authorized operator retire its exact queue records:

```sh
.venv/bin/python scripts/sdm_gradebook_worker.py --get-only release-held REQUEST_UUID --confirm
```

Use the operation's original mode flag. Release changes no grades and
preserves private evidence; it refuses SENDING, VERIFYING and UNCERTAIN. Cleanup
has its own intent/readback. Never delete journals, clear arbitrary metadata,
replace UUIDs, renew an uncertain operation or resend its saved batch.

## Limits and tradeoffs

| Control | Source behavior |
| --- | --- |
| Idle poll | 30 seconds by default; failure backoff capped at 300 seconds. Lock contention waits without claiming READY. |
| GET-only admission | READY no more than 90 seconds old, explicit GET_ONLY mode, and clear queue. |
| Canvas read | 100 published graded assignments; 120 seconds/course. Incomplete captures retain the previous mirror. |
| Google read | Worker factory: 100,000 allocated cells/chunk and five-second pacing. Whole-capture limits still apply. |
| Whole capture | 80 MB cumulative, 200 chunks, 180 seconds; bounded quota cooldown for workbook reads. |
| Request/plan lifetime | Ten/five minutes; expiry holds before dispatch. |
| Sheets grade-data send | One batch, no transport retry; durable mode and sole-send evidence precede dispatch. |

The [timing table](sdm-gradebook-workflow.md#timing-and-freshness) separates
worker freshness from publisher approval and client timeouts.

Larger bounded read chunks reduce request overhead while increasing per-response
memory; pacing trades latency for quota headroom. These are source settings,
not proof of a running process's loaded configuration.

Allocation bounds are not student counts. Capture is an interval, not an atomic
snapshot. Both modes require independent fresh preflight and full selected-field
readback. Sheets has no compare-and-swap; coordinate editors because locks cannot
prevent edits or restore an overwritten intervening change.

## Validation and references

Test fictional transports and run repository Python, lint/types and menu checks.
Never test a live student write. Tests, hashes and merges do not prove activation
or READY; retain real evidence privately.

The detailed September activation, historical runtime counts and validation
logs remain in the
[immutable baseline runbook](https://github.com/sirdanielm/canvas-mcp/blob/d0794b247df2b865150c4805d816b9075768ae92/docs/sdm-gradebook-worker.md).
They are historical evidence, not permission to resume a paused worker or replay
an old request. Current completion and holds belong in
[goals and status](goals-and-status.md).

Primary references: [desktop OAuth](https://developers.google.com/identity/protocols/oauth2/native-app),
[batch atomicity](https://developers.google.com/workspace/sheets/api/guides/batch),
[developer metadata](https://developers.google.com/workspace/sheets/api/guides/metadata)
and [Sheets limits](https://developers.google.com/workspace/sheets/api/limits).
