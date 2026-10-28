# Documentation map and authority

[The operator manual](../OPERATOR-MANUAL.md) is the human starting point.
[Goals, methods and current work](goals-and-status.md) describes standing aims
and ownership; the current scoped work order determines the active queue.
Use the relevant procedure below and inspect actual source and installed
bindings before claiming a capability. Tests, a merge or an old checkpoint do
not establish current service liveness or publication authority.

| Need | Maintained reference |
| --- | --- |
| Human setup, operation and recovery without ChatGPT | [Operator manual](../OPERATOR-MANUAL.md) |
| Current aims, intake methods and next owner action | [Goals and methods](goals-and-status.md), [current agenda](goals-and-status.md#next-work-and-ownership) |
| Main MCP connection and tools | [README](../README.md), [installation](installation.md), [tool reference](../tools/README.md) |
| Agent and developer rules | [AGENTS.md](../AGENTS.md), [CLAUDE.md](../CLAUDE.md) |
| Agent tool usage and catalog | [Tool usage](agent-usage.md), [main tool manifest](../tools/TOOL_MANIFEST.json) |
| GET/EDIT gradebook operation | [Workflow](sdm-gradebook-workflow.md), [worker and recovery](sdm-gradebook-worker.md) |
| Accepted decisions and ordinary draft staging | [Transfer methods and restart](teacher-edit-transfer.md), [exact preservation](teacher-edit-preservation.md) |
| Repository ownership and domain contracts | [Integration boundaries](grass-workflow-integration.md), [architecture pointer](GRASS_GREENFIELD_ARCHITECTURE_CONTRACT.md), [capture port](grass-capture-contract.md) |
| Offline accepted-pair RELEASE prototype | [Unit 1 preview contract](unit1-pair-preview-contract.md) |
| Curriculum authoring and course archives | [Authoring](sdm-canvas-authoring-workflow.md), [course mirror](course-mirror.md) |
| Private student copies | [PIN policy](STUDENT-PIN-POLICY.md), [exports](local-pin-exports.md), [post-QC archives](post-qc-pin-archives.md) |
| Source promotion, checkout retirement and recovery | [Maintenance](repository-maintenance.md), [workflow inventory](../.github/workflows/README.md), [release checklist](../internal/release-checklist.md) |
| Known unresolved security findings | [Current open resource/authentication work](superpowers/plans/2026-09-06-security-review-followups.md) |

The main tool manifest excludes the separate gradebook server. Shared local
review tooling belongs in LocalGrAss; Canvas services and installed targets are
owned here. Domain policy stays with its source owner. Advisory results, accepted
decisions, local drafts, authorized delivery and verified channel outcomes are
distinct states.

The authenticated Unit 1 native EDIT transfer is implemented and has bounded
local qualification. The older accepted-pair RELEASE prototype remains separate.
The [capability table](goals-and-status.md#source-and-installed-capability)
distinguishes maintained source from unmerged review commits and private runtime
overlays; none grants broad rollout authority.

## History and privacy

Status lives in [goals and ownership](goals-and-status.md), procedures in the
guides above, and settings evidence in [repository maintenance](repository-maintenance.md#settings-evidence).
Do not create competing root status, workflow or settings ledgers. Source
defaults, persisted configuration and loaded-process observations are distinct.

The October 20 pause and feedback-version notes remain in the
[dated proposal](https://github.com/sirdanielm/canvas-mcp/blob/230bbe1e08161fc8a139a74dea657625b8379a3a/docs/goals-and-status.md).
The [October 25 readiness proposal](https://github.com/sirdanielm/canvas-mcp/commit/4c49c8bdaa38fc7ebc77843922457846094856e8)
retains its original review history. These fixed records do not set today's
queue, prove a saved feedback body or establish installed capability.

Keep historical detail in fixed Git revisions, release notes and private owner
receipts. Update the existing agenda and procedure rather than adding another
competing status file. Old queue counts, credential holds and deployment claims
are dated evidence. The [September design-transfer pointer](reviews/grass-next-20260930/README.md)
retains its archive boundaries.

This fork and every tracked file are public. `docs/` is also the website upload
root; `.gitignore` alone does not exclude uploads. Keep identities, PIN crosswalks,
raw evidence, journals, credentials and backups outside Git and that root, with
`docs/.assetsignore` as an upload backstop. A documentation merge does not upload
the website, install code, restart a service, approve a grade or deliver feedback.
