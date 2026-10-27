# GitHub Actions workflows

Checked against the integration candidate's workflow files on 2026-10-26.
Workflow definitions describe triggers and effects; they do not prove that a fork has the secrets, publication rights or deployment targets
needed to complete a run.

The October 8 check reported the fork's `main` as protected; its October 1
unprotected status is historical. Reviewed PRs and green applicable CI remain
the project workflow policy. Inspect the exact active rules before claiming enforced checks;
an upstream ruleset is not evidence of the fork's rules. See
[development guidance](../../CLAUDE.md).

## Validation

| Workflow | Triggers | Checks |
|---|---|---|
| [canvas-mcp-testing.yml](canvas-mcp-testing.yml) | Push to `main` or `development`; PR targeting `main` or `feature/sdm-authoring` | Ruff, mypy, site-fact consistency, Ubuntu Python 3.11–3.14 tests, Windows Python 3.14 portable tests, TypeScript tests/build and confirmation-protocol verification |
| [security-testing.yml](security-testing.yml) | Push to `main` or `development`; PR targeting `main`; Sunday 00:00 UTC | Security regression tests, Bandit/Semgrep, frozen-lock dependency audit including all extras, secret scan and CodeQL |
| [closing-keyword-guard.yml](closing-keyword-guard.yml) | PR opened/edited/reopened/synchronized; push to `main` | Guards accidental issue-closing prose; PR scan applies only to the default-branch target |
| [scorecard.yml](scorecard.yml) | Push to `main`; branch-protection events; Monday 06:27 UTC; manual dispatch | OSSF Scorecard, SARIF and public result publication on the default branch |

Both application test jobs install the declared `local-exports` and
`local-keychain` extras. Linux runs the complete suite. Windows reports explicit
capability skips for the separate local POSIX/Keychain tooling and its fixture
imports; portable Canvas tools, model/workbook logic and PIN text checks remain
collected. The declaration and import closure live in `tests/platform_contract.py`.

The test and security workflows do not expose `workflow_dispatch`. Check each
file before suggesting a manual run. `pip-audit` fails on findings; its existing
CVE-2025-69872 exception is unchanged. The 2026-10-01 urllib3 2.8.0 lock repair
resolved three findings without new ignores. See the
[release checklist](../../internal/release-checklist.md) for shipped-versus-locked
version boundaries. Do not use CI-skipping markers to avoid required validation.

## Release and deployment

| Workflow | Triggers | Effects |
|---|---|---|
| [create-release.yml](create-release.yml) | `v*` tag push; manual dispatch naming an existing tag | Builds the Desktop Extension from the exact tag, stamps its manifest version, creates/updates release notes and attaches the bundle and provenance |
| [publish-mcp.yml](publish-mcp.yml) | `v*` tag push; manual dispatch naming an existing tag | Tests/builds the Python package, publishes to PyPI, waits for PyPI visibility, then publishes to MCP Registry |
| [deploy-prod.yml](deploy-prod.yml) | `v*` tag push; manual dispatch (job accepts `main` or `v*` refs) | Builds/pushes the container and deploys the configured production target |
| [deploy-staging.yml](deploy-staging.yml) | Push to `staging`, excluding documentation/tool-only paths; manual dispatch | Builds/pushes the container and deploys the configured staging target |

`create-release.yml` does **not** edit README, push documentation commits or open
a fallback PR. Update release documentation in the reviewed source change.
Merging to `main` does not deploy production. A tag can trigger publication and
production deployment together; neither a test tag nor a manual release run is
a harmless workflow test. Confirm the intended repository, tag, package rights,
target and authorization first.

A source merge does not publish a release or install its dependencies. Follow
the [release checklist](../../internal/release-checklist.md) and verify current
release metadata, each package, registry entry, attached artifact and authorized
deployment separately. Website publication uses `scripts/deploy_site.sh`, whose
staging and exclusion checks keep private operator documents out of Pages; a
bare `wrangler pages deploy docs/` bypasses those checks.

## Model-assisted workflows

These definitions can consume model credentials and perform external actions.
Their presence or GitHub `active` status does not authorize invoking them.

| Workflow | Trigger and effect |
|---|---|
| [claude-code-review.yml](claude-code-review.yml) | PR opened/synchronized; skips drafts, forks and Dependabot; requires configured Claude OAuth and posts review comments. Includes documentation review in its prompt |
| [claude.yml](claude.yml) | Supported issue, comment and review events containing `@claude`; interactive Claude action |
| [weekly-maintenance.yml](weekly-maintenance.yml) | Sunday 00:00 UTC or manual dispatch; model-assisted maintenance analysis and issue creation |
| [auto-label-issues.yml](auto-label-issues.yml) | New issue; model-assisted labels and explanatory comment |

`auto-update-docs.yml` and `auto-claude-review.yml` are not present in this
checkout or the fork's current workflow inventory. There is no automatic
workflow that patches documentation for each tool change. Update the relevant
`docs/agent-usage.md`, `tools/README.md` and `tools/TOOL_MANIFEST.json` guidance
with the implementation. Change `AGENTS.md` only when its operating rules or task
routing change, and review relevant entry-point documentation.

The Claude review job skips draft PRs, fork PRs, Dependabot actors and
Dependabot-authored PRs. A skipped job means no Claude review ran; obtain a
separate maintainer review before merging. Application tests and security scans
continue to run. An eligible same-repository human PR fails explicitly if its
review secret is missing. Paid model review still requires explicit provider,
budget and window authorization; changing a PR's draft status is not that
approval.

Keep the `pull_request` trigger. Do not switch to a privileged
`pull_request_target` workflow that checks out contributor code to obtain
secrets. See [GitHub's Dependabot Actions restrictions](https://docs.github.com/en/code-security/dependabot/troubleshooting-dependabot/troubleshooting-dependabot-on-github-actions).

## Troubleshooting

- Read the exact failed job and its artifacts before retrying. A dependency
  finding, scanner error and runner admission failure need different repairs.
- Publishing uses project dependency constraints, while the dependency audit
  exports `uv.lock`; check both when validating a security release.
- Check version fields, tag contents, trusted-publisher configuration and PyPI
  visibility before retrying a failed publish. The registry workflow already
  polls PyPI for up to six minutes.
- A model workflow without its configured credential cannot run successfully;
  do not add credentials or trigger a paid review merely to validate docs.
- Documentation changes are reviewed source changes. There is no README-update
  workflow or branch-protection fallback PR to wait for.
