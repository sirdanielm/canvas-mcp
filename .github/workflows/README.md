# GitHub Actions workflows

Definitions verified at SDM fork main `16b06b5`; live settings read on
2026-10-17. Definitions describe possible effects; live workflow state separately
determines whether they can run. Credentials and deployment targets were not read.

**Observed and applied (2026-10-17, readback at 21:24 UTC):** main retains
Copilot auto-request ruleset `24432455`, with draft reviews and review-on-push
off, plus the new main-only **SDM main reliability** ruleset `25319809`.
The new rule requires PRs, resolved code-review threads and current-base checks;
it prevents main deletion and force pushes. Reviewed PRs and independent review
remain [development policy](../../CLAUDE.md).

**Settings and why:** required GitHub Actions checks are `test-enhancements`,
`lint`, `Security Test Suite`, `Dependency Vulnerability Scan`,
`CodeQL Security Analysis`, and `PR body and commits`. These retain executable
safety checks for Canvas adapters while keeping zero mandatory second-person
approvals for the sole-developer workflow. GitHub's default extra-approval flag
[has no effect at zero required approvals](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-rulesets/available-rules-for-rulesets#additional-approval-for-unattributed-copilot-pull-requests).
The test aggregator excludes lint, so lint is required separately. CodeQL success
establishes analysis execution; advisory SAST/secret steps do not establish a
clean security verdict. Default token access stays read-only; Actions self-approval,
automatic merge and merged-branch deletion stay off to preserve deliberate
reviewed promotion and retained work. No release, deployment or model event
was requested by the settings application.

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

**Observed live state (2026-10-17): all four Claude workflows below are
`disabled_manually`.** Retain that state for controlled classroom work; the table
records dormant definitions. Copilot and the independent Codex app have separate
triggers. PR23 requested Copilot at ready conversion; PR29/31/33 have Codex issue
comments reporting that event even though their reviews arrays are empty. Codex
completed PR31/33 after PR29's historical quota refusal. Current entitlement,
credit use and account settings are unverified; do not test them by publishing.

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
