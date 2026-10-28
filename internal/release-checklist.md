# Release Checklist

> Workflow behavior and fork/upstream release state checked 2026-10-08. Upstream latest release: v1.13.0 (2026-09-27 EDT / 2026-09-28 UTC). The SDM fork has no published latest release; its merged main includes additional unreleased work.

Select the repository, package ownership and exact candidate before any release.
Tag pushes, workflow dispatches, package publication and website deployment
require their own authorization; a documentation update or merge does not authorize them.

When bumping the version in `pyproject.toml`, also update:

- [ ] `src/canvas_mcp/__init__.py` - Update `__version__`
- [ ] `server.json` - Update both `version` fields (top-level and packages[0]) for MCP Registry
- [ ] `tools/TOOL_MANIFEST.json` - Update `version` field to match new version
- [ ] `README.md` - Update "Latest Release" section with new version, date, and changelog
- [ ] Deploy the site with `./scripts/deploy_site.sh`: it runs `scripts/sync_site_facts.py --dates` (version, tool and skill counts, GitHub stats, sitemap dates; CI fails on a stale fact) and uploads `docs/` without the `.assetsignore` paths. Never run a bare `wrangler pages deploy docs/`.
- [ ] `uv.lock` - Run `uv lock` after bumping `pyproject.toml`; the lock records the project version and drifts otherwise
- [ ] Create git tag: `git tag vX.Y.Z && git push origin vX.Y.Z`
- [ ] Verify each authorized release/deployment result separately. A `v*` tag also triggers the retained `deploy-prod.yml`; successful deployment requires configured credentials and a valid target. Merges to `main` do not deploy production. Manual dispatch from `main` is a separate deployment action.
- [ ] Verify README/site release text was updated in the reviewed source change: `create-release.yml` builds and attaches the Desktop Extension and provenance but does not edit README or create a documentation PR.

> `manifest.json` (Desktop Extension) does **not** need a manual bump — `create-release.yml` stamps the tag version into it and attaches `canvas-mcp.mcpb` to the GitHub Release automatically. The committed `manifest.json` version is just a default.

## Pending for the next release

- SDM `main` includes the gradebook worker, integrity-checked private PIN exporter and publication-free archive preflight; these are merged source features, not claims about the upstream v1.13.0 package. Use [repository maintenance](../docs/repository-maintenance.md) for ownership and integration boundaries.
- Later fork changes include bounded diagnostics, private course exports, independently gated comments, unsent-comment recovery and refresh preservation across newly published assignments. Verify the exact release candidate and installed runtime; a source merge does not enable comments or publish grades.
- The urllib3 lock entry was upgraded from 2.7.0 to 2.8.0 in fork PR5, addressing CVE-2026-97687, CVE-2026-97688 and CVE-2026-97689 in the optional hosted dependency chain. The frozen local audit and fresh hosted CI passed without adding vulnerability ignores. Include this in the next relevant release notes.
- A lockfile repair validates the locked environment; the package publisher installs from project dependency constraints. Verify the built/published artifact and deployment dependency resolution separately before claiming the repair is shipped.

## Gotchas

- A blanket `s/1.3.0/1.4.0/` also hits dep constraints (e.g. `pytest-asyncio>=1.3.0`) — verify `git diff` shows ONLY the package version before committing.
- **`Installing mcp-publisher version: null` (first seen v1.11.0):** NOT the publish race. The
  registry job resolved the mcp-publisher tag via an *unauthenticated* `api.github.com` call,
  hit the per-runner-IP rate limit, and `jq` returned the string `null`. The download URL then
  404'd into a 9-byte body and the step died on `gzip: stdin: not in gzip format` — three steps
  from the real cause. A plain `gh run rerun --failed` succeeded. Hardened afterwards: the call
  is authenticated with `github.token`, the tag is checked for null/empty, and `curl --fail`
  stops an error page reaching `tar`. **Tell the two apart by checking PyPI first:** if
  `curl -s -o /dev/null -w '%{http_code}' https://pypi.org/pypi/canvas-mcp/<ver>/json` already
  returns 200, it is not the propagation race.
- **Publish race:** the MCP Registry job validates the version on PyPI and 404s before PyPI's CDN propagates. Wait until `curl -s -o /dev/null -w '%{http_code}' https://pypi.org/pypi/canvas-mcp/<ver>/json` returns 200, THEN `gh run rerun <id> --failed`.


## Maintaining the MCP publisher pin

The repository maintainer owns the version and Linux amd64 SHA-256 pin in
`.github/workflows/publish-mcp.yml`. The `v1.11.0` incident above refers to a
canvas-mcp release, not the publisher binary. On 2026-10-21 the pinned publisher
v1.8.1 passed `validate server.json` against the live Registry and advertised
`login github-oidc`. This is compatibility evidence, not a completed release.

Before tagging, install the pinned binary with `scripts/install_mcp_publisher.py`,
run `mcp-publisher --version`, `mcp-publisher login --help`, and
`mcp-publisher validate server.json`. Validation does not publish. Recheck after
a schema change or Registry migration. If an update is needed, select an explicit
official Registry release, verify its published Linux amd64 asset digest, update
version and checksum together, rerun installer regressions and live validation,
and review the change through a PR. Never restore an unpinned `latest` download.

Actual OIDC login needs the Actions publishing job. Review protected tags,
publishing environments and OIDC audiences before authorizing a release.
Old tags predating #515 lack the new helper scripts: do not use the revised
manual workflow to republish them. Canvas HTML readback still needs a separately
authorized real-page check before relying on the accessibility `applied` field.
