# Repository and local tooling maintenance

## Verified promotion

[PR #5](https://github.com/sirdanielm/canvas-mcp/pull/5) merged on October 1, 2026
at `68041f0704f6114d9edad1811843915dbc38e1fb`. Both retained branches were then
synchronized and clean; all eight recorded operational source files matched
before and after promotion. The completed PIN checkout was retired and the
managed sync-review checkout archived, with verified private recovery copies
and branch refs retained. This is a dated completion receipt, not a permanent
claim about the current number of worktrees. New tasks may create review trees.

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

Next shared-tool slices are a receipt-bound Canvas capture adapter,
authenticated teacher review with durable drafts and expected-revision checks,
and an authoritative release bridge for independently verified score and
feedback delivery. Start each from current LocalGrAss `main`, with bounded
offline validation and owner-specific integration review. Existing byte
verification and fake delivery tests do not establish these production links.
