# CLAUDE.md

Guidance for developing the Canvas MCP server. Agents *using* the server: see [AGENTS.md](./AGENTS.md).
Design: [internal/architecture.md](internal/architecture.md). Long-form rules and the reasons behind them: [internal/dev-reference.md](internal/dev-reference.md). Completed work: [internal/project-history.md](internal/project-history.md), `CHANGELOG.md`.
Codex reads `AGENTS.md`, not this file; its "Developing this server" section points here, so keep development rules in this file only. Engineering workflow and release guidance checked on 2026-10-01. Issue numbers and dated session entries below refer to upstream `vishalsachdev/canvas-mcp` unless explicitly identified as this SDM fork; historical issue/advisory status is not a fresh operational check.

## Commands
- Install `uv pip install -e .`; run `canvas-mcp-server` (`--test`, `--config`); `.env` holds `CANVAS_API_TOKEN` and `CANVAS_API_URL`.
- Before committing: `uv run python -m pytest tests/ -v -rf`. TypeScript changes: `npm test` and `npm run build`.

## Git workflow
- Use a reviewed branch and PR for changes to this SDM fork, including documentation. Follow an already authorized workflow without asking again; otherwise clarify only consequential scope or target ambiguity. Prefixes: `feature/`, `fix/`, `docs/`, `refactor/`.
- `main` is the maintained SDM branch; keep the installation-compatible `feature/sdm-authoring` synchronized after reviewed promotion. The primary checkout retains the shared Git directory, and the operational authoring checkout must remain available to installed services. See [repository maintenance](docs/repository-maintenance.md).
- Keep concurrent changes isolated in suitable worktrees. Before retiring a completed review checkout, inspect ancestry and actual files, preserve unique changes and ignored evidence, and verify recovery. Archive managed worktrees through Codex; do not automatically delete branches or operational checkouts.
- As checked on 2026-10-01, this fork's `main` is **not protected by GitHub**; upstream `main` is protected. PR review and green applicable CI remain the SDM workflow policy, not an enforced setting. Do not bypass failed checks or change repository protection as part of ordinary development.
- Integrate current base changes without overwriting another session's work, then rerun the relevant validation. Before a release, test the exact merged candidate in an isolated environment; never borrow live credentials merely to make tests pass.
- Run `./scripts/install-hooks.sh` once per clone. `fixes|closes|resolves #N` mid-sentence in a commit or PR body closes the issue on merge: rephrase (`closed [issue 172]`) or set `ALLOW_CLOSING_KEYWORD=1`. A trailer that opens a line (`Closes #173`) is allowed.
- Release steps and publish-race fixes: [internal/release-checklist.md](internal/release-checklist.md). Breaking changes need a minor bump. A merged SDM change is not a package release or deployment.

## Coding Standards
- Type hints on every function; PEP 604 unions (`X | Y`), enforced by ruff UP.
- Tools use `@mcp.tool()` with `@validate_params`, and every tool carries annotations (`tests/test_tool_metadata.py` fails a bare decorator).
- All Canvas calls are async and go through `make_canvas_request()`; paginate every list endpoint.
- Course identifiers are `str | int` resolved with `get_course_id()`; dates go out through `format_date()`.
- Canvas POST/PUT needs `use_form_data=True`, `/conversations` included.
- Errors: dict tools return an `"error"` key; string tools return `"Error ..."`. `modules.py` and `accessibility.py` return JSON-stringified errors; keep the local convention.
- Privacy: student IDs preserved, names anonymized at the client layer (`_should_anonymize_endpoint()`); a new endpoint must be checked against the tier rules.
- Show course codes, not IDs, in user-facing output; handle published and unpublished states.

## Testing and behavioral evidence
- New tools need meaningful automated coverage: success, failure, boundary and safety behavior.
- A reproducible bug gets a failing regression first; watch it fail for the intended reason.
- Assert outgoing request contracts and forbidden side effects, from an independent requirement, not from the implementation's own output.
- Use a real client with controlled HTTP transport when the risk is serialization, retries, pagination or error classification.
- Never send live Canvas writes to verify a patch. Never weaken an assertion to get a green run.
- Lean/TLA+ (`verify/`) only for consequential state, ownership or termination invariants; pair with implementation regressions.
- Report what was verified, what failed and what was skipped.

## Documentation Maintenance
- Source of truth: agents `AGENTS.md`; humans `tools/README.md`; machine `tools/TOOL_MANIFEST.json`; `README.md` is the entry point.
- New tool: update `tools/README.md`, then `AGENTS.md`, then `TOOL_MANIFEST.json`. Touch `README.md` only for a major feature. No tool usage docs in this file.
- `docs/` is the public Cloudflare Pages root and deploys manually (`wrangler pages deploy docs/`); nothing internal goes there.
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
- The SDM worker, private archive exporter and archive preflight are merged to `main`; the urllib3 2.8.0 hosted-dependency lock repair is also merged. These are unreleased fork changes; see the [release checklist](internal/release-checklist.md).
- Shared GrAss implementation continues in LocalGrAss; Canvas services and installed targets remain owned here. Next connections are receipt-bound capture, authenticated durable teacher review and an authoritative release bridge, as described in [repository maintenance](docs/repository-maintenance.md).

## Upstream focus snapshot (2026-09-30)
- [ ] **#157** sandbox egress is mitigated, not closed (self-hosted only; `execute_typescript` is disabled on hosted). Needs an egress proxy or network namespace.
- [ ] **#236** OAuth2 developer-key flow: additive only, blocked on admin access to pilot a scoped key.
- [ ] **#172** Canvas Quizzes tools: blocked on a New-Quizzes-enabled sandbox (PR #191 was closed as unverifiable).
- [ ] **#418 to #421** (raw dates, guarded edits, honest pagination, anonymous discussions); #420 includes an `assign_peer_review` placeholder write past 100 submissions.
- [ ] GHSA-hmr8: publish and request a CVE. GHSA-7pp5: decide (in triage since 07-04).
- [ ] Watch, no owner: Agent Plugins packaging (blocked on credential delivery; triggers in project-history).

## Roadmap
- [ ] Grok/xAI integration research and pilot.

## Backlog
- [ ] Module templates; bulk module creation from JSON/YAML; module duplication across courses.
- [ ] Page templates; bulk page creation from markdown; page versioning tools.
- [ ] 2026-09-06 security review follow-ups: check `docs/superpowers/plans/2026-09-06-security-review-followups.md` for items PR #360 did not cover.

## Session Log
> Full history: `internal/session-history.md`, local-only and untracked since 2026-08-20. Do not re-add it to git.

### 2026-09-27 — v1.13.0 released: GHSA-hmr8 fixed, production pinned to releases, hosted service read-only
- **Merged:** #395, #387, #390, #417 (production deploys only on a tag or manual run), #422 (`mcp-remote --header-file`), #425.
- **GHSA-hmr8 fix** (`3f23ed0`): `core/tool_policy.py` + `ALLOWED_WRITE_TOOLS`; `send_conversation` always previews; `get_conversation_details` never marks read. Codex security review clean at round 3.
- **v1.13.0** tagged on `c3207d3`; all five channels verified. Advisory patched version set to 1.13.0, still a draft.
- **Next:** publish GHSA-hmr8; decide GHSA-7pp5; fix the #420 placeholder write; `scripts/rotate-canvas-token.mjs` does not know `--header-file`.
