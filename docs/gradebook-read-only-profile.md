# Read-only gradebook connection

The separate gradebook launcher supports an explicit `--read-only` profile.
It exposes exactly three tools:

| Tool | Effect |
| --- | --- |
| `get_canvas_gradebook` | Read Canvas and save a private snapshot and capture receipt. |
| `preview_gradebook_changes` | Compare a local edit file with its baseline and fresh Canvas; save a private review. |
| `get_gradebook_push_status` | Read the local aggregate status of a generic historical operation. |

The profile omits score/comment preparation, authorization, execution, refresh
coordination and all other tools, including tools added to the server later.
Every retained tool has read-only metadata. Canvas credentials retain their
existing permissions; the fixed server tool set enforces this profile.

## Launch and local state

Use the reviewed environment and a private state directory:

```sh
.venv/bin/python scripts/sdm_gradebook_launcher.py \
  --read-only \
  --state-dir /absolute/private/read-only-state
```

The existing saved Canvas connection and Keychain credential are still required.
The launcher does not load workbook bindings, inspect the worker configuration,
import the refresh worker or initialize a Google controller in this profile.
`--read-only` rejects `--enable-push`, `--enable-comments` and an excluded
`--call` before reading the connection or credential.

The snapshot shortcut also accepts the profile:

```sh
.venv/bin/python scripts/sdm_gradebook_launcher.py \
  --read-only \
  --state-dir /absolute/private/read-only-state \
  --snapshot core
```

Read-only describes remote effects. The local store can initialize its SQLite
ledger and save snapshots, capture receipts and reviews. Keep these artifacts
private; they can contain student records. Tool responses report aggregates and
references rather than raw student rows.

For a cutover, use a new isolated read-only state directory while preserving the
original publication store, baselines, locks and history in place. An empty
isolated store has no historical operations and cannot resolve an uncertain
delivery from another store. Do not copy, clear or rewrite history to make a
status lookup succeed.

## Status and adoption boundaries

Generic historical status remains available even when an operation is expired
or uncertain; reading it does not retry or change it. A plan carrying an
`owner_binding` requires its qualified owner. The portable server holds that
status request instead of treating a generic ledger summary as the owner's
outcome. A malformed owner binding also holds.

Changing source does not update an installed connection or restart its clients.
At a coordinated idle checkpoint, adopt the reviewed launcher and state path,
reconnect the affected clients, then check the loaded source and exact three-tool
registry. Keep the separate GET worker and original history intact.
This gradebook profile does not configure the main Canvas authoring server.

See the [gradebook workflow](sdm-gradebook-workflow.md) for broader capabilities,
the [worker runbook](sdm-gradebook-worker.md) for GET refresh and recovery, and
[repository maintenance](repository-maintenance.md) for source promotion.
