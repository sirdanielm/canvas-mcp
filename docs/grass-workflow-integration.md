# GrAss integration and authority boundaries

The intended flow is graders → saved result records → proposals → exact
teacher-approved score/feedback pairs → Canvas publisher → verified GET readback.
Each stage retains its source and revision basis. A successful request, a passing
software test, or a completed QC run does not establish teacher approval or
verified delivery.

The canonical architecture and implementation plan are maintained with
[LocalGrAss](https://github.com/sirdanielm/LocalGrAss), in
`docs/GRASS_GREENFIELD_ARCHITECTURE_CONTRACT.md` and
`docs/GRASS_NEXT_BUILD_PLAN.md`. Repository access may require authentication.
Quinn and local AI remain optional future adapters.

## Repository responsibilities

| Repository | Responsibility |
| --- | --- |
| Canvas MCP SDM profile | Authenticated Canvas reads, local gradebook mirror and permanent PIN source; separately gated publisher |
| sdmGrAss | Grader runtime, lifecycle controls, desktop imports and diagnostic QC |
| GrAss | Saved-result intake and central proposal workflows |
| LocalGrAss | New local core, immutable revisions and explanations of saved score/comment pairs |

The existing gradebook mirror is the recommended first read-only source adapter.
Its captured snapshot and identity bindings must be verified before admission;
snapshot hashes do not establish live Canvas freshness. Originals, private
crosswalks, credentials and detailed student records remain outside Git.

## Current implementation boundary — September 30, 2026

LocalGrAss PR1, sdmGrAss PR333 and PR337, and GrAss PR118 are merged. The new local
core has synthetic validation and retained explanation history. Authenticated
teacher review, verified original-byte adapters and a live publisher remain
separate implementation work. Post-merge review findings must still be evaluated;
merge status alone is not evidence that all findings are resolved.

The desktop import/QC workflow writes durable aggregate receipts. The newest
attempt remains authoritative even when failed, interrupted or held. The
clickable status tool and on-demand agent instructions read these receipts;
no automatic Codex hook or notification was installed.

The gradebook refresh worker's implementation and dated activation evidence are
documented in [its operations guide](sdm-gradebook-worker.md). Syncing its Git
branch neither restarts that worker nor requests another refresh. Its Canvas
transport is GET-only; refreshing reference data is distinct from publishing
teacher-approved pairs.

## Next engineering work

1. Complete remaining runtime recovery reviews without guessing controller
   ownership or discarding resumable work.
2. Address post-merge integrity findings and keep validation claims tied to the
   exact revision checked.
3. Add the narrow read-only source adapter and tested backup/restore path.
4. Implement authenticated decisions and publisher/readback contracts before
   introducing real grading or delivery into the new core.

Assignment point totals and participation/Advanced policies require explicit
academic authority. Missing policy is a hold; it cannot be inferred from an old
grader, an export layout, or a successful software test.
