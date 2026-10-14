# Repository and local tooling maintenance

Maintain reviewed source without losing operational work or recovery evidence.
The [current goals and status](goals-and-status.md) records source and installed
capabilities separately. Repository publication, installation, service restart,
workbook refresh and classroom delivery are separate actions.

## Current source and checkout boundary

At the October 14 checkpoint, maintained fork main is `d0794b2`; the primary
checkout is clean. [PR #24](https://github.com/sirdanielm/canvas-mcp/pull/24)
contains the reviewed GET-only refresh and private EDIT-review improvements and
remains open at this checkpoint. Its source validation does not establish merge
or installation. Read the PR and [Actions](https://github.com/sirdanielm/canvas-mcp/actions)
for subsequent revisions and checks.

The operational authoring checkout retains uncommitted work and private
evidence. Keep that overlay intact and review its differences before any source
synchronization. Do not infer that every checkout is clean from the primary
checkout, or that installed tools changed because a branch was published.

## Reviewed promotion

1. Read current branches, worktrees, upstream containment and actual dirty
   files. Identify MCP/LaunchAgent runtime paths and active operations before
   changing a checkout.
2. Preserve exact tracked/untracked changes, ignored evidence and recoverable
   history separately. Verify the snapshot and retain recovery references.
3. Create an isolated candidate from the reviewed base. Reconcile intended
   source differences without overwriting another session's files. Shared local
   tools are coordinated with LocalGrAss; Canvas services and installed targets
   remain owned here.
4. Validate the exact candidate with the repository's existing commands, using
   dummy credentials and offline fixtures. Review privacy, documentation and
   source compatibility, then use a reviewed branch and PR.
5. After merge, verify remote/local revisions and applicable checks. Synchronize
   a retained checkout only when its preserved overlay can be reconciled safely.
   A clean fast-forward is not a reason to discard unique files.
6. Plan installation separately with the runtime owner at an idle checkpoint.
   Record exact adopted hashes and readback. Follow the
   [worker runbook](sdm-gradebook-worker.md); never restart shared MCP processes
   blindly or clear a delivery hold through Git operations.

## Retention and privacy

The primary checkout holds the common Git directory for linked worktrees.
Operational checkouts referenced by MCP configuration or LaunchAgents remain
in place. A review checkout is eligible for retirement only after fresh ancestry
and file inspection, verified recovery and dependency checks. Preserve ignored
ledgers, baselines, results and unresolved operations before archiving a managed
worktree. Missing upstreams, detached heads and opaque unreachable objects are
retention holds, not deletion instructions.

Keep credentials, student data, original evidence, manifests, backup patches and
operational receipts outside Git. `docs/` is also the website upload root:
Git ignore rules alone do not protect website uploads. Maintain corresponding
`docs/.assetsignore` exclusions and keep private backups outside that tree.
Report preserved local evidence, published branches and cleanup separately.

## Historical evidence

The full previous maintenance record remains at immutable revision
[`d0794b2`](https://github.com/sirdanielm/canvas-mcp/blob/d0794b247df2b865150c4805d816b9075768ae92/docs/repository-maintenance.md),
including [verified promotions](https://github.com/sirdanielm/canvas-mcp/blob/d0794b247df2b865150c4805d816b9075768ae92/docs/repository-maintenance.md#verified-promotion)
and the [October 8 closeout](https://github.com/sirdanielm/canvas-mcp/blob/d0794b247df2b865150c4805d816b9075768ae92/docs/repository-maintenance.md#october-8-repository-closeout).
Historical test counts, checkout inventories and paused scopes remain dated
evidence. A documentation merge grants no deployment, paid-call or Canvas-write
authority.
