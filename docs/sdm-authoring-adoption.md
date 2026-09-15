# SDM Canvas authoring adoption

Date: September 15, 2026

## Decision

Use this upstream Canvas MCP implementation as a standalone local service. Keep its Python dependencies, release history and upstream updates separate from the Apps Script grading projects GrAss and sdmGrAss. The existing grading repositories were inspected and left unchanged.

The user does not need in-place rubric editing. Remove the proposed custom `update_rubric` feature from the adoption scope. Start with the existing assignment, module, `create_rubric` and `associate_rubric` tools.

## Repository state

- Upstream: https://github.com/vishalsachdev/canvas-mcp
- Reviewed base: `f098b2c472bf68d6c5cf6b21daeaaf4ca0556f04`
- Main clone: `/Users/sdm/coding projects/repos/canvas-mcp`
- Working checkout: `/Users/sdm/coding projects/repos/canvas-mcp-sdm-authoring`
- Working branch: `feature/sdm-authoring`
- Remote `upstream` points to the original project. No personal GitHub fork or `origin` remote has been created.
- Preferred remote setup: create a GitHub fork of upstream, then add that fork as `origin`. Preserve upstream history and the MIT license. A blank repository is unnecessary.

## Rubric workflow

For a new assignment, create the desired rubric and attach it using the existing tools. For an unassessed assignment that already has a rubric, create a new rubric version, attach it to that exact assignment and verify the new rubric ID and contents by reading the assignment back. Keep the previous rubric in the library unless cleanup is specifically needed.

These operations are different:

- **Replace the assignment attachment:** point this assignment at a newly created rubric. This is the intended workflow.
- **Remove an attachment:** delete one RubricAssociation. The Canvas API provides this endpoint, but the reviewed MCP rubric tools do not expose a dedicated removal tool.
- **Delete the rubric:** Canvas documents that this removes all its associations. It is broader than replacing one assignment's rubric and is not needed for the normal workflow. The reviewed MCP tools do not expose a dedicated rubric-delete tool.
- **Overwrite rubric contents:** edit the same rubric object. It is not a separate shortcut around rubric editing and is outside the user's requested scope.

Canvas source enforces one grading-purpose association per assignment; attaching another can remove the previous association and unlink rubric assessments. Therefore, a replacement pilot must use a disposable, unassessed assignment. Do not treat replacement as preserving existing rubric grading. Attaching with `use_for_grading=true` can also synchronize assignment points to rubric points; verify both values. These findings come from current upstream Canvas source, not live verification of the institution's instance.

Sources:

- [Canvas rubric and association endpoints](https://developerdocs.instructure.com/services/canvas/resources/rubrics)
- [Canvas association behavior](https://github.com/instructure/canvas-lms/blob/master/app/models/rubric_association.rb)
- [Existing connector tools](../src/canvas_mcp/tools/rubrics.py)

## Smallest remaining setup

1. Verify the existing Python environment and relevant upstream tests with dummy credentials and mocked Canvas calls.
2. Connect this local service to the intended MCP client with credentials outside Git. No real token, hostname or course IDs are stored in this document.
3. Expose the assignment, rubric and module tools needed for authoring. The built-in educator profile also includes grading and messaging; it is not an authoring-only restriction. Determine whether the client can enforce the desired tool selection before changing server code. Keep general TypeScript execution disabled.
4. Once a test course and live-test authorization are supplied, verify one assignment, one new rubric and one module. Test the replacement path on an unassessed assignment and read back the rubric ID, criteria, points, module placement and publication state.
5. Add custom behavior only for a demonstrated failure in that pilot.

No new rubric-edit tool, rubric-delete tool, grading integration, paid model calls, remote publication or live Canvas operation is part of this setup branch.

## Checkpoint

Local repository and branch prepared. Locked runtime and development dependencies installed into the worktree's ignored `.venv` using Python 3.12.14 and `uv sync --frozen --group dev`. The upstream application code and lockfile are unchanged.

Validation: the full Python test suite completed with **1,542 passed, 21 skipped in 9.55 seconds**. It ran with an explicit dummy Canvas token, `https://canvas.invalid/api/v1`, dotenv loading disabled, and macOS sandbox rules denying network access. Skipped tests are not counted as verified coverage. `git diff --check` passed. These results verify the local baseline, not live Canvas permissions or replacement behavior.

The server has not been connected to Canvas or installed into an MCP client. No real credentials, course IDs or student data were used. No changes were made to GrAss or sdmGrAss.

Estimated remaining work: 30–60 minutes for MCP client setup/tool selection and an authorized test-course pilot if credentials and a suitable test course are available. No rubric-editor development estimate applies to this scope.
