# internal/ — non-published project docs

These files are development references outside the Cloudflare Pages upload root,
`docs/`. **Tracked files here are public on GitHub.** The directory name does not
provide confidentiality. Only deliberately reviewed references are un-ignored;
operator history, credentials, recovery copies and private reports remain
Git-ignored. Website exclusion and Git exclusion are separate controls.

Keep private operator/compliance/design notes in Git-ignored locations here or
in Git-ignored `*.local.md` files. Never move them into `docs/` or un-ignore them
for convenience. See the [documentation map](../docs/documentation-map.md) and
[repository maintenance guide](../docs/repository-maintenance.md).

Contents:

- `SECURITY-COMPLIANCE.md` *(gitignored, operator-only)* — FERPA/security evaluation of the hosted deployment; shared privately with IT, not published.
- `architecture-review.md` — adversarial MCP-vs-direct-API design review.
- `session-history.md` *(gitignored, local-only since 2026-08-20)* — full development session log.
- `dev-reference.md` — long-form development rules moved out of `CLAUDE.md` (git workflow, testing guide, hosted architecture, adoption numbers).
- `project-history.md` — completed Current Focus / Roadmap / Backlog items as of 2026-09-30.
- `architecture.md` — design reference.
- `release-checklist.md` — version bump and publish steps.
- `issue-triage/` — daily triage briefs (tracked; see the privacy rule in `CLAUDE.md`).
- `best-practices.md` — internal working notes.
- `research-appservice-mcp-entra.md` — Azure App Service + Entra research notes.
- `ops-hosted.local.md` *(gitignored, operator-only)* — hosted endpoint/auth/deploy runbook, incl. the **mcp-remote OAuth re-auth/hang troubleshooting** (#146).

> Public, human-facing docs live in `docs/` (the HTML guides) and in the
> top-level `README.md` / `AGENTS.md`.
