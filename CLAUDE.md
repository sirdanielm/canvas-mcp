# CLAUDE.md

Guidance for developing the Canvas MCP server. Agents *using* the server: see [tool usage](docs/agent-usage.md).
Design: [internal/architecture.md](internal/architecture.md). Long-form rules and the reasons behind them: [internal/dev-reference.md](internal/dev-reference.md). Completed work: [internal/project-history.md](internal/project-history.md), `CHANGELOG.md`.
Codex starts with `AGENTS.md`; its task router points here for repository development. Keep development rules here and load long references only for the affected task. Historical upstream issue references belong to `vishalsachdev/canvas-mcp` unless explicitly identified as this SDM fork. Use current source and operator receipts for operational status.

## Commands
- Install `uv pip install -e .`; run `canvas-mcp-server` (`--test`, `--config`); `.env` holds `CANVAS_API_TOKEN` and `CANVAS_API_URL`.
- During iteration, run focused checks for the affected behavior. Documentation-only edits need link/format/privacy review, not the application suite. Before promotion, run applicable required CI; Python behavior changes use `uv run python -m pytest tests/ -v -rf`, and TypeScript changes use `npm test` and `npm run build`.

## Git workflow
- Use a reviewed branch and PR for changes to this SDM fork, including documentation. Follow an already authorized workflow without asking again; otherwise clarify only consequential scope or target ambiguity. Prefixes: `feature/`, `fix/`, `docs/`, `refactor/`.
- `main` is the maintained SDM branch; keep the installation-compatible `feature/sdm-authoring` synchronized after reviewed promotion. The primary checkout retains the shared Git directory, and the operational authoring checkout must remain available to installed services. See [repository maintenance](docs/repository-maintenance.md).
- Keep concurrent changes isolated in suitable worktrees. Begin independent authorized work without waiting for owner acknowledgements; coordinate actual overlapping writers and shared runtime changes. Before retiring a completed review checkout, inspect ancestry and actual files, preserve unique changes and ignored evidence, and verify recovery. Archive managed worktrees through Codex; do not automatically delete branches or operational checkouts.
- Use PR review and passing applicable CI for promotion to this fork's `main`. Inspect current GitHub rules before claiming which checks are enforced. Do not bypass failed checks or change repository protection during ordinary development.
- Integrate current base changes without overwriting another session's work, then rerun the relevant validation. Before a release, test the exact merged candidate in an isolated environment; never borrow live credentials merely to make tests pass.
- Run `./scripts/install-hooks.sh` once per clone. `fixes|closes|resolves #N` mid-sentence in a commit or PR body closes the issue on merge: rephrase (`closed [issue 172]`) or set `ALLOW_CLOSING_KEYWORD=1`. A trailer that opens a line (`Closes #173`) is allowed.
- Release steps and publish-race fixes: [internal/release-checklist.md](internal/release-checklist.md). Breaking changes need a minor bump. A merged SDM change is not a package release or deployment.

## Coding Standards
- Type hints on every function; PEP 604 unions (`X | Y`), enforced by ruff UP.
- Tools use `@mcp.tool()` with `@validate_params`, and every tool carries annotations (`tests/test_tool_metadata.py` fails a bare decorator).
- All Canvas calls are async and go through `make_canvas_request()`; paginate every list endpoint.
- Course identifiers are `str | int` resolved with `get_course_id()`; dates go out through `format_date()`.
  Code that needs a numeric course ID (paths, context codes, comparisons) uses `resolve_numeric_course_id()`, which returns `(id, error)` and never yields an unvalidated string. `get_course_id()` matches the same way but keeps its pass-through fallback on a miss.
- Canvas POST/PUT needs `use_form_data=True`, `/conversations` included.
- Errors: dict tools return an `"error"` key; string tools return `"Error ..."`. `modules.py` and `accessibility.py` return JSON-stringified errors; keep the local convention.
- Privacy: student IDs preserved, names anonymized at the client layer (`_should_anonymize_endpoint()`); a new endpoint must be checked against the tier rules.
- Show course codes, not IDs, in user-facing output; handle published and unpublished states.

## Testing and behavioral evidence
- New tools need meaningful automated coverage: success, failure, boundary and safety behavior.
- A reproducible behavior bug gets a focused failing regression first when practical; observe the intended failure. Prose-only and reversible low-impact changes do not need artificial tests.
- Assert outgoing request contracts and forbidden side effects, from an independent requirement, not from the implementation's own output.
- Use a real client with controlled HTTP transport when the risk is serialization, retries, pagination or error classification.
- Never send live Canvas writes to verify a patch. Never weaken an assertion to get a green run.
- Lean/TLA+ (`verify/`) only for consequential state, ownership or termination invariants; pair with implementation regressions.
- Report what was verified, what failed and what was skipped.

## Documentation Maintenance
- Source of truth: agent working agreement `AGENTS.md`; agent tool usage `docs/agent-usage.md`; human catalog `tools/README.md`; machine catalog `tools/TOOL_MANIFEST.json`. `README.md` is the entry point.
- New tool: update `tools/README.md`, relevant `docs/agent-usage.md` guidance and `TOOL_MANIFEST.json`. Change `AGENTS.md` only when operating rules or task routing change; touch `README.md` for a major feature. No tool usage docs in this file.
- `docs/` is the public Cloudflare Pages root and deploys manually with `scripts/deploy_site.sh` (a bare `wrangler pages deploy docs/` ignores `.assetsignore` and publishes `triage/`, `audits/`, `superpowers/`); nothing internal goes there.
- The site's version, tool and skill counts and GitHub stats come from `scripts/sync_site_facts.py` (CI runs `--check`): change the source, then run it; never hand-edit those numbers.
- `internal/` is deny-by-default in `.gitignore`; un-ignore only a file meant to be public. `internal/session-history.md` stays untracked.
- Triage briefs are tracked: never record a collaborator's affiliation, evaluation status, timeline or competing products. Name the person and the technical issue only.

## Hosted Deployment
- A private, Entra-gated Azure instance serves Gies course staff. Its URL, app IDs, deploy details and key holders stay out of this repo; they live in the gitignored `internal/ops-hosted.local.md`.
- HTTP mode: each caller sends `X-Canvas-Token`; `CANVAS_API_TOKEN` must never be set (startup guard); read-only unless `ALLOWED_WRITE_TOOLS` is set.
- The upstream Azure deployment workflows are retained here; their presence does not establish a configured SDM hosted service. Production triggers are `v*` tags or an authorized manual run from `main`; staging triggers on qualifying pushes to `staging` or manual dispatch. A merge to `main` does not deploy production. Tags and dispatches are consequential release/deployment actions, not routine validation.

## Adoption numbers
- Never print a PyPI download count. Quote stars, forks and contributors, re-pulled from the GitHub API that day, with the date.
- Do not repeat "over 18,000 clones" or "UMich selected it as sole candidate" without a primary source.
- Do not imply a campus security review: the only Illinois artifact is Adam King's LRA, and the public hosted server is retired.

## Current SDM focus

Follow [goals and status](docs/goals-and-status.md). Reuse preserved evidence and
saved results, support Canvas and teacher-folder/paper intake, and retain exact
identity, source, form, policy and attempt bindings. GrAss summative work retains
score and full feedback together; ordinary sdmGrAss participation delivers a
score while keeping its analysis private.

Use the current [transfer guide](docs/teacher-edit-transfer.md) and
[integration boundaries](docs/grass-workflow-integration.md) for route capability
and ownership. Preserve completed canaries and uncertain histories; qualify a new
or materially changed adapter/installation without repeating live canaries for
every unchanged batch. Stage, teacher acceptance and Canvas delivery remain
different states. Reuse existing authorization and valid evidence for the first
unfinished stage.

LocalGrAss owns shared review/workbench tools. Canvas owns exact observations,
GET/EDIT integrity, scoped writers and installed Canvas bindings. Prioritize
source consolidation, eligible proposal review and exact target admission;
retain original evidence and existing teacher edits. Unit 2 requires its issued
forms, keys and sealed policy before advisory scoring. Actual permitted effects
come from the current work order and installed configuration; a documentation
change itself enables no provider, service restart or publisher. A held case does
not stop independent eligible targets or source work.

Historical plans, prototype limitations and test diaries remain in
[project history](internal/project-history.md), [CHANGELOG](CHANGELOG.md) and
[fixed earlier guidance](https://github.com/sirdanielm/canvas-mcp/blob/16b06b5151c3595b043cb300e963b7de448ca738/CLAUDE.md).
Private session history stays in gitignored `internal/session-history.md`.
