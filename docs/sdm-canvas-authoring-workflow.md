# SDM Canvas authoring workflow

This guide records the operating contract for the local `canvas-authoring` MCP connection. It covers curriculum authoring and course organization. Student submissions, grading and messaging remain outside this connection's tool allowlist.

## Authority boundary

- Never publish an assignment, module item or module unless the teacher explicitly authorizes that exact publication.
- Creating and editing unpublished drafts is allowed when requested.
- Treat assignment publication, module-item publication and module publication as three separate states.
- Keep general TypeScript execution disabled. It can bypass the MCP server's normal write controls.
- Do not read or write student, submission or grade data during curriculum-authoring work.

The local Codex configuration is the practical capability boundary. `config/sdm-authoring.toml.example` exposes only course, assignment, rubric and module tools. It excludes grading, messaging, enrollment and generic code execution. Canvas account permissions remain the ultimate server-side boundary.

## Local setup and connection checks

From the repository root on macOS:

```sh
uv sync --frozen --group dev --extra local-keychain
.venv/bin/python scripts/sdm_canvas_launcher.py --setup
.venv/bin/python scripts/sdm_canvas_launcher.py --check
.venv/bin/python scripts/sdm_canvas_launcher.py --verify
```

Setup uses hidden terminal input, verifies the proposed credential with one GET,
and only then stores it in macOS Keychain. A rejected replacement preserves the
previous credential. `--check` only checks local configuration and credential
availability; `--verify` makes one GET to confirm authentication. Neither proves
permission to perform a particular course operation.

Use `config/sdm-readonly.toml.example` for the nine course-content readers, or
`config/sdm-authoring.toml.example` for the 20 authoring tools when authorized.
Adapt the examples' absolute paths to the checkout and reload the MCP client
after changing its configuration. An example file is not evidence of the active
client configuration. The launcher forces educator mode, disables general
TypeScript execution and student-write tools, and disables dotenv loading; the
client allowlist narrows the educator server's remaining tools.

For immutable local course-content snapshots and comparisons, use the separate
[course mirror CLI](course-mirror.md). For gradebook refreshes, use the separate
[gradebook workflow](sdm-gradebook-workflow.md).

## Assignment workflow

### New drafts

1. Read the target course and confirm its exact Canvas ID.
2. Create the assignment with `published=false`.
3. Use `on_paper` as the temporary submission type.
4. Let the teacher initialize Google Assignments LTI in Canvas before publication. The current MCP tool accepts `external_tool` as a submission type, but it does not configure the complete institution-specific LTI launch.
5. Read the assignment back and verify its ID, title, points, submission type and unpublished state.

### Existing assignments

Before any update, record the assignment ID, name, points, publication state, submission types, dates and a hash of the live HTML description. Build changes from that live version.

For a description-only edit:

1. Reread the live description immediately before writing and compare its hash with the planned source.
2. Stop if another edit occurred.
3. Call `update_assignment` with `description` only.
4. Read the assignment back.
5. Verify that points, submission types, dates and publication state did not change.

Canvas `points_possible` is authoritative for the rubric total. Preserve Core and Advanced requirements independently when copying layout or wording between courses.

## Description formatting

Place submission guidance above the embedded rubric. For worksheets and simulations, use:

> **SUBMIT your work BELOW (scroll down → click "Load [Assignment] in a new window")**

For video activities, use:

> **Open the video BELOW (scroll down → click "Load [Assignment] in a new window")**

Always include the final closing parenthesis. Use the existing yellow highlight and underline styling from the live course.

## Embedded rubric policy

- Put one student-visible HTML rubric table in the assignment description.
- Do not create or associate a Canvas-native rubric unless the teacher explicitly requests it.
- When a native rubric must be removed, delete only the association or native rubric requested; never remove the HTML table from the assignment description.
- Match the embedded rubric total to the live assignment's `points_possible` value.
- Preserve rubric criteria and scoring language when making a formatting-only change.

Current visual standard:

| Element | Value |
|---|---|
| Outer border | `2px solid #0b5d3b` |
| Title row | `#0b5d3b` with white text |
| Column header | `#dfeee5` |
| Cell borders | `1px solid #777` |
| Cell padding | `8px` |
| Total row | `#f2f2f2` |

## Module workflow

Canvas can propagate publication when a populated module is published. This was observed during the Unit 2 rollout. A successful API response is not proof that linked assignments kept their intended state.

Use this sequence:

1. Create the module with `published=false`.
2. Add each item with an explicit `published=false` unless that exact item is authorized for release.
3. After adding an assignment item, reread both the module item and the linked assignment.
4. Set the intended publication state for each item explicitly.
5. Publish the module container only after every child and linked assignment has been verified.
6. Reread the complete module tree and all linked assignments after the final change.

For the chemistry course structure:

- Put review slides and the track-appropriate study guide at the top.
- Add the test date as a subheader.
- Group each day's assignment with its external slide link.
- Use block labels such as `A13/B13 slides`, not `day 13 slides`.
- Preserve assignment order and Core/Advanced differences.

## Verification receipt

For every write batch, keep a privacy-safe receipt with:

- timestamp and target course ID
- object IDs and intended operation
- before and after publication states
- before and after points, submission types and dates when assignments are touched
- description hash before and after description edits
- module item type, position, content ID or external URL
- readback result and any corrective action

Do not store API tokens, student data or full Canvas responses in Git.

## Tool limitations and safe defaults

- `create_assignment` already defaults to `published=false`.
- This branch changes `create_module` to default to `published=false`.
- This branch adds a `published` option to `add_module_item` so callers can declare visibility during creation.
- The server includes `update_rubric`, but the tracked SDM authoring allowlist does not expose it. If an explicitly authorized native-rubric edit requires it, preserve every criterion/rating ID and the exact association ID, submit the complete replacement set, show the preview, then confirm with its single-use token. Structural additions/removals belong in the Canvas UI. There is no dedicated native-rubric deletion tool. The normal SDM workflow uses description-embedded tables.
- Deleting assignments, modules or module items uses the upstream preview-and-confirm flow. Treat confirmation tokens as single-use and target-specific.

## Final checklist

- Correct course and object IDs
- Correct Core or Advanced scope
- Exact assignment points and rubric total
- Expected description links and closing punctuation
- Expected assignment, item and module publication states
- Expected module order and item types
- No native rubric association unless requested
- No unintended submission-type, date or point changes
- Readback completed from Canvas
