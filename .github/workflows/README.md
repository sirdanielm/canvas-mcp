# GitHub Actions workflows

Checked against the workflow files and the SDM fork's GitHub workflow inventory
on 2026-10-01. Workflow definitions describe triggers and effects; they do not
prove that a fork has the secrets, publication rights or deployment targets
needed to complete a run.

The fork's `main` is unprotected in GitHub. Reviewed PRs and green applicable CI
remain the project workflow policy. Upstream `main` is protected; do not assume
its rulesets are installed here. See [development guidance](../../CLAUDE.md).

## Validation

| Workflow | Triggers | Checks |
|---|---|---|
| [canvas-mcp-testing.yml](canvas-mcp-testing.yml) | Push to `main` or `development`; PR targeting `main` or `feature/sdm-authoring` | Ruff, mypy, Python 3.11–3.13 tests, TypeScript tests/build, confirmation-protocol verification and enhancement tests |
| [security-testing.yml](security-testing.yml) | Push to `main` or `development`; PR targeting `main`; Sunday 00:00 UTC | Security regression tests, Bandit/Semgrep, frozen-lock dependency audit including all extras, secret scan and CodeQL |
| [closing-keyword-guard.yml](closing-keyword-guard.yml) | PR opened/edited/reopened/synchronized; push to `main` | Guards accidental issue-closing prose; PR scan applies only to the default-branch target |
| [scorecard.yml](scorecard.yml) | Push to `main`; branch-protection events; Monday 06:27 UTC; manual dispatch | OSSF Scorecard, SARIF and public result publication on the default branch |

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

Upstream's latest published release is v1.13.0 (2026-09-27 EDT / 2026-09-28 UTC).
The SDM fork has no published latest release as of this check; merged SDM work
and the hosted-dependency lock repair remain unreleased source changes. Follow
the [release checklist](../../internal/release-checklist.md) and verify each
package, registry entry, attached artifact and authorized deployment separately.

## Model-assisted workflows

These definitions can consume model credentials and perform external actions.
Their presence or GitHub `active` status does not authorize invoking them.

| Workflow | Trigger and effect |
|---|---|
| [claude-code-review.yml](claude-code-review.yml) | PR opened/synchronized; skips drafts; requires configured Claude OAuth and posts review comments. Includes documentation review in its prompt |
| [claude.yml](claude.yml) | Supported issue, comment and review events containing `@claude`; interactive Claude action |
| [weekly-maintenance.yml](weekly-maintenance.yml) | Sunday 00:00 UTC or manual dispatch; model-assisted maintenance analysis and issue creation |
| [auto-label-issues.yml](auto-label-issues.yml) | New issue; model-assisted labels and explanatory comment |

`auto-update-docs.yml` and `auto-claude-review.yml` are not present in this
checkout or the fork's current workflow inventory. There is no automatic
workflow that patches documentation for each tool change. Update `AGENTS.md`,
`tools/README.md` and `tools/TOOL_MANIFEST.json` with the implementation, and
review relevant entry-point documentation.

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
