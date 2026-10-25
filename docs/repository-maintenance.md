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
lane-appropriate proposals. The authenticated Unit 1 EDIT transfer is source-accepted;
the ordinary participation receiver is locally qualified pending portable source
publication. Git maintenance clears no source, teacher-review or delivery hold.

## Settings evidence

Use the existing operator/d0t settings ledger for actual observations; do not
create a second runtime or approval registry. Public source references are:

| Evidence class | Source and limit |
| --- | --- |
| GitHub governance | Read the fork’s current active rules; a branch’s protected flag or a workflow comment does not establish enforced checks. |
| Optional automation | [Workflow inventory](../.github/workflows/README.md) and its definitions describe triggers/effects, not available credentials or permission to run paid review, publication or deployment. |
| General MCP defaults | [Environment template](../env.template) and [overlay limitations](../config/overlays/README.md); unsupported flags implement no control. |
| Gradebook limits and timing | [Worker limits](sdm-gradebook-worker.md#limits-and-tradeoffs), [reference allocation](gradebook-reference-limits.md), [timing](sdm-gradebook-workflow.md#timing-and-freshness). Constructor defaults and launcher overrides can differ. |
| Persisted and loaded installation | Retain the owner’s exact configuration revision and loaded-process evidence privately. A file, startup hash or old receipt alone does not prove current loaded settings or liveness. |

Record verification time, source revision, evidence class, owner and explicit
unknowns. Attribute a failure to a limit only when the exact operation’s evidence
supports it. Changing a client timeout does not renew a security token, stop a
possible remote write or clear an uncertain operation. Settings changes retain
their own review and authorization; documentation reconciliation changes none.

## Reviewed promotion

1. Read current branches, worktrees, upstream containment and actual dirty
   files. Compare advertised remote heads (`git ls-remote --heads origin`) with
   local/tracking refs; stale tracking refs are not server evidence. Identify
   MCP/LaunchAgent runtime paths and active operations before changing a checkout.
2. Preserve exact tracked/untracked changes, ignored evidence and recoverable
   history separately. Verify the snapshot and retain recovery references.
3. Keep one active promotion candidate from the reviewed base. Compare intended
   source changes by bytes and behavior, retain unique commits and resolve stale
   duplicate guidance against current receipts. Separate portable source from
   private owner bindings and runtime overlays; do not publish ignored dependencies
   merely to make an operational checkout clean. Shared local tools are coordinated
   with LocalGrAss; Canvas services and installed targets remain owned here.
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
Keep the operational authoring checkout as the single dirty runtime overlay;
private launcher dependencies, exact owner bindings and receipts remain
separate from portable source review. Operational checkouts referenced by MCP
configuration or LaunchAgents remain in place. A review checkout is eligible
for retirement only after fresh ancestry and file inspection, verified recovery
and dependency checks. Preserve ignored ledgers, baselines, results and
unresolved operations before archiving a managed worktree. The archive must
preserve unique commits and dirty files, with ignored files copied separately
and their recovery verified before retirement. Record a successor for
superseded review checkouts and status documents. Archived receipts retain
their original bytes and timestamps. Missing upstreams, detached heads and
opaque unreachable objects are retention holds, not deletion instructions.

Keep credentials, student data, original evidence, manifests, backup patches and
operational receipts outside Git. `docs/` is also the website upload root:
Git ignore rules alone do not protect website uploads. Maintain corresponding
`docs/.assetsignore` exclusions and keep private backups outside that tree.
Report preserved local evidence, published branches and cleanup separately.

## Closeout and restart

Record the maintained source revision, remaining operational overlay, installed
pins, retained recovery paths and unresolved operations separately. Retire
completed review worktrees after preservation and dependency checks; keep the
primary Git checkout and every active runtime target. A clean checkout is not a
reason to discard private work, rewrite receipts or activate source.

The next owner starts from the current source and installed bindings, identifies
one concrete task and its approval scope, and reuses retained evidence before
commissioning another read or run. A completed operation is closed; uncertain
operations use their existing reconciliation path. Paid calls, publication and
service changes retain their separate explicit gates.

Historical promotions, checkout inventories and paused scopes remain at
[fixed earlier guidance](https://github.com/sirdanielm/canvas-mcp/blob/16b06b5151c3595b043cb300e963b7de448ca738/docs/repository-maintenance.md)
and in private recovery receipts. A documentation merge grants no deployment,
paid-call or Canvas-write authority.
