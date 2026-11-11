# GrAss integration and authority boundaries

Canvas and teacher-folder/paper intake feed source-bound reviewable proposals.
The [goals and capability summary](goals-and-status.md) owns the agenda and dated
status; this page owns cross-repository responsibilities. Procedures stay in the
[EDIT transfer guide](teacher-edit-transfer.md) and
[gradebook workflow](sdm-gradebook-workflow.md).

## Ownership

| Owner | Responsibility |
| --- | --- |
| Canvas MCP | Authoritative observations, retained Canvas captures and accepted-capture promotion, permanent PIN source, exact identity/attempt targeting, protected GET/EDIT integrity, installed Canvas bindings, separately gated score/comment transport and readback |
| sdmGrAss | Assignment-grader engines, participation/profile policies and fleet lifecycle |
| GrAss | Academic policy, original paper/question evidence, saved academic results and canonical proposal/feedback exports |
| LocalGrAss | Shared import/QC and review tools, aggregate retained-submission lookup and downstream intake, source-bound drafts, immutable revisions and authenticated final decisions |
| d0t | One canonical queue, current scoped assignments, original-owner coordination and outcome-driven refill |

LocalGrAss owns the canonical
[architecture](https://github.com/sirdanielm/LocalGrAss/blob/main/docs/GRASS_GREENFIELD_ARCHITECTURE_CONTRACT.md).
A repository's source acceptance does not establish another owner's installation,
academic admission or destination delivery. Follow current case and source
qualification rather than treating the architecture as activation authority.

## Retained Canvas submission library

For a new formative fleet scan or test intake, first discover electronic
submissions through the registered private library. Use independently verified
`course_id + assignment_id`, with purpose `formative` or `test`, following the
[LocalGrAss lookup guide](https://github.com/sirdanielm/LocalGrAss/blob/main/docs/CANVAS-SUBMISSION-LIBRARY.md).
That guide owns the CLI, private registration and optional Desktop shortcut.
`--require-capture-id` can require the currently accepted capture to match an
explicit expectation. Titles alone cannot select an assignment.

Canvas owns the retained bytes, capture verification and accepted pointer.
Its installed archive workflow rescans current Canvas metadata/history, reuses
verified unchanged versions, retains partial runs and admits a capture only
after QC, library indexing and intake-receipt verification. Locate that
workflow through the operator's private registration and runbook; a fresh
source clone does not install it. The separate
[content-mirror CLI](course-mirror.md) and
[gradebook refresh](sdm-gradebook-workflow.md) have different scopes.
Curriculum catalogs retain their capture provenance; accepting a later capture
does not refresh an older catalog export.

LocalGrAss returns aggregate `ARCHIVE_CANDIDATES` or an explicit hold. Candidates
require subsequent exact student identity, actual Canvas attempt/source version,
original-byte and page-completeness checks, academic form/policy and current
eligibility. An empty or held lookup does not prove that no work exists or
justify a zero. Preserve unavailable Canvas-history and provider-only gaps;
Canvas GET does not refresh Google exports or provider-held student work.

Teacher-folder/paper intake proceeds with independently attributed identity,
issued form, physical attempt and ordered pages. It can qualify even when
Canvas has no retained attachment. Keep submission contents, identities,
private locators and capture receipts outside public curriculum catalogs and Git.

## Handoff and recovery

1. **Admit and reuse evidence.** Bind original bytes/pages, producer membership,
   issued form, policy, identity, assignment and actual physical/Canvas attempts.
   Missing context is a hold, not zero. Reuse a durable result only when those
   substantive bindings still match; new model eligibility follows the
   [current formative rule](goals-and-status.md#priorities).
2. **Retain the exact proposal.** Summative work keeps canonical score and full
   feedback together. Ordinary participation may enter EDIT as UNAPPROVED and
   keeps analysis private. An accepted test route additionally needs genuine
   revision-bound teacher acceptance. Use the actual [route contract](teacher-edit-transfer.md),
   including the limits on held totals and feedback-only staging.
3. **Preserve and verify the destination.** The sole EDIT writer rechecks current
   source/target and complete native preimage, teacher content, higher grades,
   original baselines and once history. Retain complete readback; a matching
   score, hash or caller-created actor flag is not authority or feedback proof.
4. **Publish separately.** Existing publishers require current comparison and
   exact approval for the intended score/comment channel. All published Canvas
   grades remain unchanged without that approval; participation is score-only
   under its governing policy. Independently verify each authorized channel.
5. **Reconcile, never replay.** The newest held/failed/interrupted evidence stays
   authoritative for its scope. Completed operations retain their receipts;
   possible sends retain original locks and history. A held case blocks only its
   affected targets or genuinely shared resource, not independent eligible work.

Reuse valid current human authorization rather than requesting a new generic
confirmation for each stage. Existing tool/security/data gates remain effective.
Coordinate actual overlapping writers and runtime changes; do not require an
acknowledgment before disjoint authorized source work.

## Source, installation and history

Use the [capability table](goals-and-status.md#source-and-installed-capability)
before selecting a maintained route, private overlay or offline prototype. A
GET-only refresh preserves EDIT and Sync baselines; it does not repair a shape
mismatch by full-sync. New axes need the existing reviewed append-plan contract.
The older [accepted-pair RELEASE prototype](unit1-pair-preview-contract.md)
remains offline and is not completed by the native publisher's existence.

Private owner bindings, source links, crosswalks, journals and detailed receipts
stay outside Git and the website root. Follow the [permanent PIN policy](STUDENT-PIN-POLICY.md).
Retain [earlier integration detail](https://github.com/sirdanielm/canvas-mcp/blob/5f9f0ee41252556654b3c26d8c4bb0e83520543b/docs/grass-workflow-integration.md)
and original receipts as history. Documentation grants no grading, spending,
installation, service or Canvas-write permission.
