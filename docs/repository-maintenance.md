# Repository and local tooling maintenance

Maintain reviewed source without losing operational work or recovery evidence.
The [current goals and status](goals-and-status.md) records source and installed
capabilities separately. Repository publication, installation, service restart,
workbook refresh and classroom delivery are separate actions.

## Maintained source and ownership

The maintained branch is fork
[`main`](https://github.com/sirdanielm/canvas-mcp/tree/main).
`feature/sdm-authoring` is an installation-compatible branch, synchronized only
after reviewed promotion and safe reconciliation of its operational overlay.
Read [Actions](https://github.com/sirdanielm/canvas-mcp/actions) for validation of
the exact candidate; a passing branch check is not installed parity.

Canvas owns identity/attempt targeting, GET/EDIT integrity, transport gates and
installed Canvas services. LocalGrAss owns shared local tools and review;
GrAss and sdmGrAss retain their domain engines and policy contracts. The
[grading direction](goals-and-status.md#grading-flow) joins both intake lanes to
paired score/feedback proposals. Git maintenance does not complete the remaining
teacher-decision-to-EDIT integration or clear an academic/delivery hold.

## Reviewed promotion

1. Read current branches, worktrees, upstream containment and actual dirty
   files. Compare advertised remote heads (`git ls-remote --heads origin`) with
   local/tracking refs; stale tracking refs are not server evidence. Identify
   MCP/LaunchAgent runtime paths and active operations before changing a checkout.
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
   Fetch remote changes before integrating and push only the reviewed intended
   commits. Prefer clean fast-forwards; preserve divergent work for explicit
   reconciliation. Do not force-push, reset away work or prune branches merely
   to make a checkout appear synchronized.
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
