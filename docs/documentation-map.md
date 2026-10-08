# Documentation map and authority

This map was reconciled with fork main `a46b252` and GitHub receipts on
October 8, 2026. The maintenance guide records checkout/sync holds. Use the current source
and exact installed configuration to establish capability; a dated plan, green
test, Git merge or setup example does not establish live authorization.

## Maintained references

| Need | Maintained reference | Authority boundary |
| --- | --- | --- |
| Install/use Canvas MCP | [README](https://github.com/sirdanielm/canvas-mcp/blob/main/README.md), [agent guide](https://github.com/sirdanielm/canvas-mcp/blob/main/AGENTS.md), [tool guide](https://github.com/sirdanielm/canvas-mcp/blob/main/tools/README.md), [manifest](https://github.com/sirdanielm/canvas-mcp/blob/main/tools/TOOL_MANIFEST.json) | Main MCP registry and configured role/write/feature gates; separate from the gradebook server |
| Curriculum authoring | [Authoring workflow](sdm-canvas-authoring-workflow.md) | Exact unpublished drafts and explicit publication; no student grading through this connection |
| Canvas observations, working edits and separate comments | [Gradebook workflow](sdm-gradebook-workflow.md), [worker](sdm-gradebook-worker.md), [course mirror](course-mirror.md), [capture port](grass-capture-contract.md) | GET observation, draft refresh, independently gated score/comment delivery and source admission establish separate facts |
| Local identity copies | [Permanent PIN policy](STUDENT-PIN-POLICY.md), [private exports](local-pin-exports.md), [post-QC archive contract](post-qc-pin-archives.md) | Registry-bound Student Info authority; QC compatibility and archive permission are separate |
| Grader results to review to publisher | [Workflow integration](grass-workflow-integration.md), [canonical contract pointer](GRASS_GREENFIELD_ARCHITECTURE_CONTRACT.md) | Immutable results, exact teacher decision, separate release, independent score/feedback verification |
| Unit 1 paper pair preview and wire protocol | [Unit 1 contract](unit1-pair-preview-contract.md) | Unregistered offline observations/forms; fictional controls practice and original-paper inspection remain separate from real acceptance/release |
| Repository and development practice | [Maintenance](repository-maintenance.md), [development guide](https://github.com/sirdanielm/canvas-mcp/blob/main/CLAUDE.md), [workflow inventory](https://github.com/sirdanielm/canvas-mcp/blob/main/.github/workflows/README.md), [security](https://github.com/sirdanielm/canvas-mcp/blob/main/SECURITY.md) | PR and tested revision; deployment, paid review and classroom writes require their own authority |

[LocalGrAss](https://github.com/sirdanielm/LocalGrAss) owns the new local core and
shared toolbox catalog. Canvas-owned services and installed targets remain in
this repository. Read its [production connection plan](https://github.com/sirdanielm/LocalGrAss/blob/main/docs/PRODUCTION_CONNECTION_PLAN.md)
for implemented durable receipt intake/local teacher authentication and the remaining real source/policy/publisher integration. Quinn/local AI remains an optional future adapter.

## Historical records

Dated adoption notes, audits, triage briefs, validation receipts, design plans,
release notes, `internal/project-history.md` and the
[October 4 operating contract](https://github.com/sirdanielm/canvas-mcp/blob/main/internal/SDM-OPERATING-CONTRACT-20261004.md)
record the state at their named
date/revision. Preserve that evidence; do not interpret old queue counts,
credential holds, worktree paths or deployment claims as current status. The
September GrAss transfers and comparison originals have private hash-verified
copies; the [historical review pointer](https://github.com/sirdanielm/canvas-mcp/blob/main/docs/reviews/grass-next-20260930/README.md)
explains their successor. Current designs live in LocalGrAss.

## Publication and privacy

This fork is public. Every tracked file, including `internal/`, examples and
skills, is public on GitHub. `docs/` is also the manual website upload root;
`.gitignore` alone does not exclude files from that upload. Keep private histories,
rosters, PIN crosswalks, journals, backups and raw evidence outside the website
root and Git, with deliberate `docs/.assetsignore` exclusions as a backstop.

The upstream package release and this fork's maintained branch are different
artifacts. Current fork state is [main](https://github.com/sirdanielm/canvas-mcp/tree/main);
validation state is [Actions](https://github.com/sirdanielm/canvas-mcp/actions).
Merging documentation does not upload the website, release a package, restart an
installed service or deliver any student score or feedback.
