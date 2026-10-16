# Documentation map and authority

Use [goals and status](goals-and-status.md) for direction and dated outcomes
and priorities. Read the relevant guide for procedures, and the current source
and exact installed bindings for capability. Tests, a Git merge or an old
checkpoint do not establish current service liveness or publication authority.

## Maintained references

| Need | Reference |
| --- | --- |
| Dual intake, paired score/feedback outputs and remaining handoffs | [Grading flow](goals-and-status.md#grading-flow), [architecture pointer](GRASS_GREENFIELD_ARCHITECTURE_CONTRACT.md) |
| Start/use the main MCP connection | [README](../README.md), [installation](installation.md), [tool reference](../tools/README.md) |
| Agent/developer rules | [AGENTS.md](../AGENTS.md), [CLAUDE.md](../CLAUDE.md), [main tool manifest](../tools/TOOL_MANIFEST.json) |
| GET/EDIT gradebook operation | [Workflow](sdm-gradebook-workflow.md), [worker](sdm-gradebook-worker.md) |
| Curriculum authoring and course archives | [Authoring](sdm-canvas-authoring-workflow.md), [course mirror](course-mirror.md) |
| Review and publisher ownership | [Integration](grass-workflow-integration.md), [capture port](grass-capture-contract.md), [Unit 1 contract](unit1-pair-preview-contract.md) |
| Private student copies | [PIN policy](STUDENT-PIN-POLICY.md), [exports](local-pin-exports.md), [post-QC archives](post-qc-pin-archives.md) |
| Source promotion and recovery | [Maintenance](repository-maintenance.md), [workflow inventory](../.github/workflows/README.md), [release checklist](../internal/release-checklist.md) |

The main server's manifest excludes the separate gradebook server. Shared local
review/dashboard tooling belongs in [LocalGrAss](https://github.com/sirdanielm/LocalGrAss);
Canvas services and installed targets remain owned here. Preserve the distinction
between advisory results, accepted teacher decisions, authorized delivery and
verified score/comment outcomes.

The [GrAss handoff contract](https://github.com/sirdanielm/GrAss/blob/main/docs/CENTRAL_GRADE_HANDOFF.md#teacher-decision-to-edit-remaining-integration)
owns the remaining revision-bound teacher-decision-to-EDIT requirements; the
proposal inbox and existing Canvas publishers do not connect that step by
themselves. Domain policy details remain in their owning repositories.

## Historical records

Current guides link dated detail to fixed Git revisions. Keep release notes,
design contracts, private receipts and `internal/project-history.md` as evidence;
do not read old queue counts, credential holds or deployment claims as current
status. The [September design-transfer pointer](reviews/grass-next-20260930/README.md)
retains its successor and archive boundaries.

## Publication and privacy

This fork is public, including every tracked `internal/` file. `docs/` is also the
manual website upload root; `.gitignore` alone does not exclude a website upload.
Keep identities, PIN crosswalks, raw evidence, journals, credentials and backups
outside Git and that root, with `docs/.assetsignore` as an upload backstop.
A documentation merge does not upload the website, release a package, restart an
installed service, approve a score or deliver feedback.
