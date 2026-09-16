# SDM Canvas authoring adoption

Date: September 15–16, 2026

## Decision

Use this upstream Canvas MCP implementation as a standalone local service. Keep its Python dependencies, release history and upstream updates separate from the Apps Script grading projects GrAss and sdmGrAss. The existing grading repositories were inspected and left unchanged.

The user does not need in-place rubric editing. Remove the proposed custom `update_rubric` feature from the adoption scope. Start with the existing assignment, module, `create_rubric` and `associate_rubric` tools.

The production operating contract is documented in [SDM Canvas authoring workflow](sdm-canvas-authoring-workflow.md). It records the publication boundary, draft assignment workflow, embedded rubric standard, module safety sequence and readback requirements established during the first live curriculum-authoring rollout.

## Repository state

- Upstream: https://github.com/vishalsachdev/canvas-mcp
- Reviewed base: `f098b2c472bf68d6c5cf6b21daeaaf4ca0556f04`
- Main clone: `/Users/sdm/coding projects/repos/canvas-mcp`
- Working checkout: `/Users/sdm/coding projects/repos/canvas-mcp-sdm-authoring`
- Working branch: `feature/sdm-authoring`
- Remote `upstream` points to the original project.
- Personal fork and remote `origin`: https://github.com/sirdanielm/canvas-mcp
- Preserve upstream history and the MIT license when taking updates.

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

## Initial baseline checkpoint

Local repository and branch prepared. Locked runtime and development dependencies installed into the worktree's ignored `.venv` using Python 3.12.14 and `uv sync --frozen --group dev`. The upstream application code and lockfile are unchanged.

Validation: the full Python test suite completed with **1,542 passed, 21 skipped in 9.55 seconds**. It ran with an explicit dummy Canvas token, `https://canvas.invalid/api/v1`, dotenv loading disabled, and macOS sandbox rules denying network access. Skipped tests are not counted as verified coverage. `git diff --check` passed. These results verify the local baseline, not live Canvas permissions or replacement behavior.

The server has not been connected to Canvas or installed into an MCP client. No real credentials, course IDs or student data were used. No changes were made to GrAss or sdmGrAss.

Estimated remaining work: 30–60 minutes for MCP client setup/tool selection and an authorized test-course pilot if credentials and a suitable test course are available. No rubric-editor development estimate applies to this scope.


## Local integration checkpoint — September 15, 2026

The existing server is installed in Codex as `canvas-authoring`. Its configuration exposes 20 course-content, assignment, rubric and module tools. Grading, messaging, enrollment and generic code-execution tools are not exposed through this Codex entry. The server itself retains its upstream educator profile; this is a client tool allowlist, not a change to Canvas account permissions.

- Added a small macOS Keychain launcher and an interactive setup entry point; no upstream API tool implementations were changed.
- Declared `local-keychain` as an optional dependency. The dependency versions in the lockfile were preserved.
- `codex mcp get canvas-authoring --json` verifies the installed configuration and exact tool allowlist. There are no tokens in its arguments, environment table or config example.
- Full offline suite after launcher changes: **1,555 passed, 21 skipped in 8.54 seconds**. Ruff passed for the new Python files, and `git diff --check` passed.
- An actual stdio MCP handshake initialized `canvas-api` and found all 20 configured tools. The upstream educator server registered 91 tools; general TypeScript execution was absent. Network access was denied throughout this probe, and it made no Canvas API calls.
- Previous Codex configuration was backed up to `~/.codex/config.toml.before-canvas-20260915T2358`; all other parsed configuration was verified unchanged.

### Finish credential setup

Open `scripts/Setup Canvas Connection.command`. It asks for the Canvas HTTPS home URL and uses hidden terminal input for the token. The token is stored with the native macOS Keychain backend under service `sdm.canvas-authoring`, keyed by the Canvas origin. The only disk setting is the non-secret origin in `~/.config/canvas-authoring/connection.json`; neither the token nor connection file is added to Git.

The setup helper never sends the token to chat, passes it as a command-line argument, or falls back to a plaintext keyring. On startup it retrieves the token in-process and supplies it to the upstream server's environment. Dotenv loading and general TypeScript execution are disabled by the launcher. A missing credential fails startup with a short redacted error.

After saving the credential, this command verifies local credential availability without making an API call:

```sh
.venv/bin/python scripts/sdm_canvas_launcher.py --check
```

Start a fresh Codex session so it loads the newly added MCP configuration. If the desktop app does not refresh the server entry, restart the app. Authentication and test-course behavior still need live verification; successful offline startup is not evidence of a working Canvas token.

For a fresh local checkout, install with:

```sh
uv sync --frozen --group dev --extra local-keychain
```

The sample `config/sdm-authoring.toml.example` contains this workstation's absolute paths; adapt them when using a different checkout. The token is never part of that sample.

### Pending live verification

Credential entry and a user-selected test course remain pending at this checkpoint. No live Canvas read or write has occurred. Once credentials are available, first verify authentication with a read-only request. Only then run the user-selected assignment/rubric/module pilot, record the exact created IDs, and verify each resulting object. Existing grading records are outside the pilot.


## Read-only verification checkpoint — September 15, 2026

The user authorized up to 30 minutes of verification and development with no destructive Canvas operations or publishing. The active Codex entry was narrowed from 20 tools to these nine readers: `list_courses`, `get_course_details`, `list_assignments`, `get_assignment_details`, `list_rubrics`, `get_rubric`, `list_modules`, `list_module_items`, and `get_course_structure`. The full authoring example remains available for later explicit use; `config/sdm-readonly.toml.example` records the currently active list. No server API implementation was changed.

Observed live result: the local credential exists and is readable from macOS Keychain. Two diagnostic `GET /api/v1/users/self/profile` requests received **HTTP 401**. The second classified the response without printing its contents: Canvas explicitly reported an invalid access token, with no insufficient-scope or expiry indication detected. Checks stopped before course enumeration. This establishes rejection of that credential for the configured website; it does not distinguish a revoked, mistyped, or wrong-site token. No replacement credential is assumed valid without a successful check.

The actual configured Keychain-backed launcher also completed a stdio MCP handshake with network access denied. All nine configured tools exist and advertise read-only behavior; generic TypeScript execution is absent. This verifies local launch/tool discovery, not successful Canvas authentication.

Setup improvements:

- Clearly distinguish the example website from a saved/default website.
- Allow Return to keep an explicitly displayed saved website; retry invalid or empty input when no default exists.
- Verify a replacement token using exactly one GET with redirects disabled before saving it. Rejected credentials leave the previous Keychain entry and connection settings unchanged.
- Show redacted authentication errors and keep the setup window open so the operator can read them.
- Add `--verify` for a deliberate read-only authentication check; `--check` still checks only local credential availability.

Validation: **1,567 passed, 21 skipped in 7.98 seconds** in the full suite with network denied and dummy credentials. The 25 launcher tests cover single-GET authentication, failed-response redaction, input retries, and preservation of existing credentials when a replacement is rejected. Ruff and diff checks passed.

Current course impact: **no content creation, editing, deletion, grading, module changes, or publishing**. The initial probe did not reach course data. Manual setup validation also uses GET only. The improved local setup window was reopened; a corrected credential must be accepted before continuing live reader checks.

The backup before enabling this read-only list is `~/.codex/config.toml.before-canvas-readonly-20260916T0017`. A future authorized authoring session can restore the full 20-tool list after verifying the exact intended course and operation.

## Live authoring checkpoint — September 16, 2026

Authentication and the selected authoring tools were subsequently verified against the intended Canvas courses. The first controlled rollout created and revised unpublished assignment drafts, updated assignment-description HTML, managed native rubric associations under explicit authorization, and built Core and Advanced course modules. Publication was limited to the exact items authorized by the teacher.

The rollout established these operational rules:

- Canvas `points_possible` is the authority for rubric totals.
- New drafts use `published=false` and temporary `on_paper` submission mode. The teacher initializes Google Assignments LTI in Canvas.
- Student-facing rubrics normally live as styled HTML tables in assignment descriptions. Canvas-native rubric associations are omitted unless explicitly requested.
- Description-only edits pass only the `description` field and require before/after metadata verification.
- Publishing a populated module can change child visibility. Module, module-item and linked-assignment publication states must be verified independently.
- Course-specific labels use A/B block codes such as `A13/B13 slides`.

No student submissions, grades or messages were accessed through this curriculum-authoring connection. Exact course and assignment IDs remain in local audit receipts rather than public repository documentation.
