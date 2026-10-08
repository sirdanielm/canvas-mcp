# Repository and local tooling maintenance

The [central goal and dated work status](https://github.com/sirdanielm/LocalGrAss/blob/main/docs/SDM-GOALS-AND-WORK-STATUS.md)
connects Canvas identity, read-only mirror, and explicitly gated delivery work
to the teacher-reviewed evidence chain. Canvas services and installed targets
remain owned here; a source merge is separate from installation and release.

## October 8 repository closeout

Fresh fork reads verified `main` at
`a46b2528d376d15711bb7e151616f805d339a3d3` and installation-compatible
`feature/sdm-authoring` at `4783049127ac7c76ef979b8ad1b2e052f9991591`.
The main revision's applicable hosted testing/security checks passed. An isolated
offline check of that exact source passed **2,724 Python tests, 21 skipped**,
Ruff and mypy. GitHub now reports fork main as protected; older unprotected
observations remain dated history, not current workflow guidance.

The canonical and operational checkouts remain at `921554d`. Their existing
dirty files were preserved: one tracked edit in the canonical checkout, and
eight tracked edits plus one untracked diagnostics module in the operational
checkout. The operational overlay contains two source differences from current
main, including a sheet-specific native-read limit. The clean `f141640` score
review checkout is already ancestral to current main and remains retained.
Preservation hashes and patches stay in the private closeout receipt, outside
Git and the website tree. No lock, transport or running service was removed.

Do not absorb those files to make a fast-forward succeed. Next, the runtime owner
must review the two remaining overlay differences and coordinate an idle
maintenance window under the [worker runbook](sdm-gradebook-worker.md). Preserve
the exact files and reconcile their intended behavior on an isolated current-base
branch before synchronizing either existing checkout. A Git pull is not a runtime
reload or permission to release a refresh hold.

Public upstream was fetched at `1d07eb3`; against the reviewed fork base it has
145 upstream-only commits and 80 fork-only commits. Those substantial code and
dependency changes need a separate reviewed compatibility candidate, not an
automatic closeout merge. This documentation closeout resumes repository work
only; grading, publication, runtime changes and classroom delivery remain paused.

## Verified promotion

[PR #5](https://github.com/sirdanielm/canvas-mcp/pull/5) merged on October 1, 2026
at `68041f0704f6114d9edad1811843915dbc38e1fb`. Both retained branches were then
synchronized and clean; all eight recorded operational source files matched
before and after promotion. The completed PIN checkout was retired and the
managed sync-review checkout archived, with verified private recovery copies
and branch refs retained. This is a dated completion receipt, not a permanent
claim about the current number of worktrees. New tasks may create review trees.

[PR #8](https://github.com/sirdanielm/canvas-mcp/pull/8) merged on October 2,
2026 at `97852f6e80203776566bacc464de93b27292fd0f` after independent review and
passing applicable CI. The primary `main` and operational `feature/sdm-authoring`
checkouts were then fast-forwarded and verified clean at that revision; the latter
was pushed to its matching remote branch. The added Unit 1 preview and fictional
channel contracts remain unregistered. No runtime restart, package release,
Canvas write or teacher-approval activation accompanied this promotion.

The related [LocalGrAss PR #12](https://github.com/sirdanielm/LocalGrAss/pull/12)
merged at `adc73554c4b373a9428e3ccfb7f4d184e5ca7d43` on the same date. Its exact
`b6c60d7` source passed independent trust-seam review and the required isolated
unittest suite (943 passed, 10 optional skips); current-head hosted CI was absent.
The owner checkout's newer uncommitted source/CLI work was preserved. Recovery
Desk and original-paper review are separate from the still-unactivated academic
provider, paper-source admission and real release connections.

For current revisions and checks, read [fork main](https://github.com/sirdanielm/canvas-mcp/tree/main)
and [GitHub Actions](https://github.com/sirdanielm/canvas-mcp/actions).
The [documentation map](documentation-map.md) identifies maintained guides and
historical records.

## Maintained branch and ownership

The fork's `main` branch contains the reviewed SDM Canvas implementation,
including the read-only gradebook worker and integrity-checked private archive
exporter. `feature/sdm-authoring` remains an installation-compatible branch;
keep it synchronized when promoting reviewed changes. A Git merge does not
restart a service, deploy the bound menu, approve a score or enable publication.

Develop new shared local tools and improvements to their catalogued copies in
[LocalGrAss](https://github.com/sirdanielm/LocalGrAss).
Canvas domain services, policies, authenticated mappings and installed targets
remain owned here. Coordinate interface changes and record source revisions,
validation and installed readback before handing a tested change to its owner.

## Completed worktrees

The September 30 upstream-sync, private PIN archive and archive-preflight
branches were merged into the SDM branch through PRs 3, 2 and 4. Their review
worktrees have no unique implementation to resume. Retire completed checkouts
only after fresh ancestry and actual file inspection, preserving exact local
changes and any ignored operational evidence separately. Retain recovery refs
until archive verification is complete.

The primary checkout holds the common Git directory for linked worktrees.
Operational checkouts referenced by MCP configuration or LaunchAgents remain
in place during ordinary repository cleanup. Removing a review checkout is not
permission to remove a runtime, journal, baseline, result or unresolved send.

## Private history and recovery

Original design transfers, frozen architecture comparisons and detailed
operator checkpoints are kept in the operator's private archive. The public
[architecture pointer](GRASS_GREENFIELD_ARCHITECTURE_CONTRACT.md) leads to the
canonical LocalGrAss contract. The historical review directory remains a
location pointer for earlier documentation.

`docs/` is the website upload root. Git-ignored working documents are not
implicitly excluded from a website upload; keep corresponding exclusions in
`docs/.assetsignore`. Private backups, worktree snapshots, manifests and local
reports belong outside that upload tree and outside GitHub.

## Continuing development

The [Canvas capture port](grass-capture-contract.md) and LocalGrAss durable receipt intake, authenticated local teacher drafts, and authoritative fake-only release bridge now have controlled integration tests. Real academic-policy/source adapters, evidence review and Canvas score/comment publication remain held. Start subsequent work from current maintained main with bounded validation and owner review. Git synchronization does not restart MCP services or clear classroom gates.

## October 4 reviewed source closeout

The reviewed gradebook diagnostics source adds bounded private redacted JSONL,
read-only exact-request inspection and startup/runtime identity reporting.
The source includes the nonblocking no-follow descriptor repair, regular-file
checks, immutable SQLite reads, active-sidecar/change holds and exact bounded
request inventory. Refresh/publish authorization, retry behavior and uncertain
request handling retain their existing boundaries. See
[worker diagnostics](sdm-gradebook-worker.md).

The separately frozen seven-file [course repository export](course-mirror.md)
change adds private archival course layout and referenced asset verification.
Only its code, fictional tests and public documentation are included. Private
exports, teaching content, credentials and per-course receipts remain outside
Git. An archival copy is not a publisher or a live-source replacement.

The integration starts from maintained main
`4783049127ac7c76ef979b8ad1b2e052f9991591` and includes exact reviewed
diagnostics head `7f4f41be8eb145450dc4e8decf14efe0e454bb08` plus the frozen
course code. The combined Python suite passed **2,643 tests, 21 skipped**.
Hosted candidate and post-merge checks are verified separately in the closeout
receipt and [Actions](https://github.com/sirdanielm/canvas-mcp/actions).

The primary checkout's edit and the operational authoring checkout's six-file
installed diagnostics overlay remain preserved in place. This source closeout
does not install, synchronize a dirty operational checkout, restart a service,
refresh a workbook, publish a package, deploy a site or write to Canvas.
The observed baseline's unrelated Claude maintenance workflow failed because
its GitHub App was not installed; applicable code/security checks succeeded.
No workflow, permission, protection or scheduler setting is changed to address
that installation gap.
