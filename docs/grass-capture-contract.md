# Private Canvas capture port for LocalGrAss

`canvas_mcp.gradebook.capture` is a read-only observation/identity adapter. The
existing `get_canvas_gradebook` service now returns an additive
`capture_receipt_id` alongside its existing aggregate counts and `snapshot_id`.
No tool, credential permission or Canvas write gate is added. This field appears
only after the service loads this source revision; Git sync alone does not
restart an already running MCP process.

## Two retained artifacts, distinct authority

After the dedicated GET-only client returns a complete snapshot, `save_capture`
stores the original immutable snapshot and a private `CANVAS_GET_CAPTURE` receipt.
The receipt binds snapshot identity, Canvas origin, course, observation timestamp,
completed capture scope and zero Canvas writes. It is never a working-edit `_Sync`
B2 baseline, a grading result or a source-document completeness certificate.
Only the trusted GET application calls this helper; hashes authenticate neither
the calling process nor a hand-constructed snapshot.

`build_case_receipt` loads that exact receipt/snapshot and compares independently
selected origin, course, Canvas assignment and student target, plus an
independently selected academic assignment ID. It requires exact roster
and assignment identities, populated cells for the selected assignment, visible
target and a known nonnegative attempt. Missing target/cell/attempt or scope drift
holds. Known attempt does not prove receipt of original student work.

The adapter reads the existing shared private Student Info binding through
LocalGrAss's canonical PIN implementation. It joins exact Canvas ID to the
canonical row's normalized email and four-digit text PIN, preserves leading
zeros, rejects missing/duplicate/conflicting identities, and checks registry and
roster hashes again before returning. It never matches a display name, creates a
PIN, selects another roster or refreshes Student Info. Its identity revision
binds the actual registry and canonical roster bytes; `snapshot_sha256` within
the identity object denotes those roster bytes, not the Canvas grade snapshot.

## Private one-case intake contract

The v1 receipt keeps the independently selected academic `assignment_id` separate
from `canvas_assignment_id`; the remote course/assignment binding cannot invent or
accept local academic identity. It also contains exact case/capture revision, canonical
identity provenance, expected populated record keys, record-to-source membership,
original file relative paths/hashes/byte lengths, and the scoring reference
manifest. It adds no roster name/email, Canvas student ID, score or feedback fields.
Caller-supplied paths/references can still identify a person and remain restricted
private metadata. Case/record/source refs are intended as opaque ASCII tokens;
original paths can contain Unicode.
The receipt is still restricted private evidence metadata and must stay outside
Git, published docs and Quinn's reference library.

The caller independently selects the original source catalog and expected record
keys. This is not a Canvas attachment downloader or automatic ownership/page
matcher. Every source belongs to exactly one populated record, every expected
record is present, and refs match the exact catalog. Duplicate paths/content,
unsafe paths, empty files or over-budget catalogs hold. The default bounds match
the LocalGrAss verifier: 64 files, 16 MiB each, 64 MiB total.

The LocalGrAss [source-intake API](https://github.com/sirdanielm/LocalGrAss/blob/main/docs/SOURCE_INTAKE.md)
verifies original bytes in place and persists their exact evidence association.
Its expected producer, identity and original-catalog digests must come from
independently retained trusted metadata. Computing an expected digest from the
pending untrusted receipt is not identity/source authentication. Historical
replay does not verify current originals; admission repeats byte checks.

## Canonical hashes and integration

Existing Canvas Store IDs retain their original JSON hash algorithm. Intake
expectations use `intake_digest(value)`: LocalGrAss canonical JSON v1, UTF-8,
Unicode preserved, sorted string keys, compact separators, no floats/object
coercion, maximum depth 64 and maximum encoded record 1 MiB. Do not substitute
Canvas `model.digest` for an intake expectation when paths contain Unicode.
Original SHA-256 is over actual source bytes. Canonical source-catalog hashes
come from LocalGrAss `source_catalog_digest` over exact SourceSpec records.

The producer is a callable integration port; there is no folder watcher,
unattended import or new public HTTP endpoint. Its trusted caller supplies exact
source metadata and output privacy. The local core requires accepted academic
scope, separate source/identity authority and authenticated teacher review; this
port grants none of them. No real evidence case is auto-admitted by a mirror read.

## Verified boundaries

Fictional tests cover deterministic PIN joins, zero preservation, missing/current
scope, populated completeness, visibility/attempt holds, duplicate identities,
registry/roster drift, unsafe originals and explicit Unicode hash parity. The
controlled cross-repo check uses the actual producer and shared PIN implementation
through LocalGrAss intake, authenticated review and fake-only release; database
reopen produces no duplicate sends. No real grading/feedback write was needed.

Read [gradebook workflow](sdm-gradebook-workflow.md),
[workflow integration](grass-workflow-integration.md), and LocalGrAss's
[connection status](https://github.com/sirdanielm/LocalGrAss/blob/main/docs/PILOT_CONNECTIONS_2026-10-01.md)
for the remaining real-policy, source ownership, review and publisher boundaries.
