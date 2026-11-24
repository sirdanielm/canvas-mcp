**Human operator manual:** [Read the operator manual](OPERATOR-MANUAL.md) - setup, daily operation, outputs, recovery and operation without ChatGPT.

<p align="center">
  <img src="docs/canvas-mcp-header.png" alt="Canvas MCP — AI tools for Canvas LMS" width="800">
</p>

# Canvas MCP Server

<!--mcp-name: io.github.vishalsachdev/canvas-mcp-->

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

A local MCP server for reading Canvas courses, assignments, submissions and grades,
with separately enabled educator and student actions. This is the SDM fork of
[Vishal Sachdev's Canvas MCP](https://github.com/vishalsachdev/canvas-mcp).
Available tools depend on Canvas permissions, role, operator allowlists and feature
flags. The main MCP server, local gradebook worker and course mirror are separate
interfaces. The main-server source defines **up to 129 tools** and
**8 agent skills**; operator and feature gates determine actual availability.

Version 1.19.0 defaults standard stdio and HTTP connections to read-only.
For authorized write access, configure the exact approved tools before switching
a connection to this source; see [enable specific write tools](#enable-specific-write-tools).
Existing installed services keep their loaded source until separately updated.

## Choose the workflow

For a gradebook update, refresh Core GET and Adv GET in the central workbook
and verify the finalized receipt. A private library capture does not update
the Sheet. Private EDIT staging and live Canvas score/comment delivery are
separate; use the exact authorized lane and read back the result.

For grading support, use known original-source and attempt bindings, reuse
compatible saved stages, and verify the receiving result. Paper-folder and
native non-Canvas grading do not depend on a Canvas library capture. Formative
work uses the admitted NO_MODEL run and a current Canvas/Sheet/cache join
before any eligible new analysis.

For new formative scans and test intake, use the registered private Canvas
submission library to discover retained electronic sources by verified course
and assignment IDs. Preserve capture history and use the
[source-intake boundaries](docs/grass-workflow-integration.md#retained-canvas-submission-library)
before selecting individual evidence. Teacher-folder/paper intake remains an
independent lane.

Read [goals and status](docs/goals-and-status.md) for the agenda, dated source
milestones and actual capability limits. A source merge does not identify or
upgrade the running MCP service. LocalGrAss owns shared review tools; Canvas
owns observations, GET/EDIT integrity and installed Canvas bindings.

| Task | Start here |
| --- | --- |
| Read Canvas or use enabled MCP tools | [Installation](docs/installation.md), [tool guide](tools/README.md) |
| Send or verify one Canvas score or comment | [Individual scores and feedback](OPERATOR-MANUAL.md#individual-canvas-scores-and-feedback) |
| Download new or changed submission files | [Private submission archive](OPERATOR-MANUAL.md#download-submission-files) |
| Refresh/compare gradebook GET and EDIT | [Gradebook workflow](docs/sdm-gradebook-workflow.md), [worker](docs/sdm-gradebook-worker.md) |
| Inspect gradebook snapshots, comparisons and historical status without writer controls | [Read-only gradebook connection](docs/gradebook-read-only-profile.md) |
| Archive and inspect course content | [GET-only course mirror](docs/course-mirror.md) |
| Find retained electronic submissions for formative or test intake | [Canvas library and LocalGrAss lookup](docs/grass-workflow-integration.md#retained-canvas-submission-library) |
| Author assignments, rubrics and modules | [Authoring workflow](docs/sdm-canvas-authoring-workflow.md) |
| Understand review/publisher ownership | [Workflow integration](docs/grass-workflow-integration.md) |

## Installation

<a id="local-installation"></a>
<a id="quick-start"></a>

Use Python 3.11+ and a Canvas token issued under your institution's policy.
Optional local TypeScript execution requires Node.js 22.18 or later.
For a source checkout:

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -e .
cp env.template .env
```

Set `CANVAS_API_URL` to your institution's HTTPS URL ending in `/api/v1` and
`CANVAS_API_TOKEN` to your token in the private `.env`. Then configure your MCP
client to launch the absolute `.venv/bin/canvas-mcp-server` path from this checkout.
[Installation and client examples](docs/installation.md) cover manual setup,
packaged desktop extensions, authentication and verification. Local gradebook
and authoring connections require their own setup; this command does not install
them.

<a id="verification"></a>

`canvas-mcp-server --test` checks the Canvas connection; `--config` displays
configuration. Do not include tokens or student records in a support report.

### Enable specific write tools

Set `ALLOWED_WRITE_TOOLS` for each main-server process that needs authorized
write access. For example, `ALLOWED_WRITE_TOOLS=edit_page_content` enables edits
to existing pages; use only the tool names approved for that connection. An unset,
empty or `none` value is read-only. Unknown names stop startup. Tool admission
does not replace the human authorization, preview and readback required for an
individual action.

For Codex, add the environment table under the existing server entry:

```toml
[mcp_servers.canvas-api.env]
ALLOWED_WRITE_TOOLS = "edit_page_content"
```

Other local clients can set the variable in their server environment or private
`.env`. The upstream v1.19 desktop extension exposes **Allowed write tools** with
a default of `none`; older bundles can predate that setting. Hosted operators
set their server allowlist. After a configuration change, reconnect only the
affected connection at an idle checkpoint and inspect its loaded tool list.
Dedicated SDM authoring and gradebook profiles retain their separate admission
and installation contracts.

## Tools and workflows

<a id="available-tools"></a>
<a id="for-ai-agents"></a>

The main server provides **up to 129 tools**. Its default all-role profile
registers fewer, and optional feature-gated tools can raise the total to 129;
operator write restrictions can reduce availability. Students can inspect their
own work; educators can inspect course work and use explicitly enabled
grading/content tools. Learning-design tools cover course
structure and accessibility. Use the [tool reference](tools/README.md) for exact
contracts and [AGENTS.md](AGENTS.md) for agent rules. The
[machine manifest](tools/TOOL_MANIFEST.json) describes the main server, excluding
the separate gradebook server.

`search_canvas_tools` discovers registered MCP tools and TypeScript operations.
Its schema version 2 response separates `mcp_tools` from `code_execution_api`.
An absent write tool is an operator boundary; confirmation tokens bind requests
and do not establish human approval. Current source includes student calendar,
group, quiz-awareness and grade-scenario reads, guarded content edits and
separately gated course-group creation. Quiz-taking remains unavailable. See the
tool guide for each permission and preview contract.

Course names and codes must resolve to a known course. Use `sis_course_id:<id>`
for an explicit SIS lookup. `create_rubric` can attach a new rubric only when
the assignment has no rubric. Editing uses `update_rubric` with every existing
criterion/rating ID and its preview/confirmation flow. An explicitly requested association change uses
`associate_rubric`. See [rubric behavior](docs/rubric-api-behavior.md).

<a id="-agent-skills"></a>

The eight maintained [agent workflows](skills/) are optional recipes on top of
an installed MCP connection. They do not enable disabled tools or grant action
authority. Upstream distributes them through `npx skills add vishalsachdev/canvas-mcp`.

## Privacy and writes

<a id="security"></a>
<a id="-privacy--data-protection"></a>

Keep credentials, original student evidence, PIN crosswalks, journals and backups
outside Git and the public website root. Optional `ENABLE_DATA_ANONYMIZATION=true`
reduces supported identity fields sent to an AI client; Canvas and the client's
own data policies still apply. Private local student copies use the registry-bound
four-digit text PIN from `Student Info`, preserving leading zeros and holding
unmatched/conflicting identities. See the [PIN policy](docs/STUDENT-PIN-POLICY.md).

`ALLOWED_WRITE_TOOLS` governs the main server's side-effect tools. Standard
stdio and HTTP connections are read-only when it is unset or empty. Writes require
explicit human authorization and each tool's preview/readback contract. Scores
and feedback have separate delivery evidence. Never replay an uncertain comment
send.

<a id="code-execution-api"></a>

`execute_typescript` is disabled by default. Enabling it exposes privileged Canvas
credentials and can bypass confirmation and content-fencing guarantees. Each run
requires authorization for its intended effects; a dry run or local sandbox is
not approval. The optional local sandbox now uses Node's permission model,
which restricts filesystem access and child processes. In local and container
mode, the JavaScript network guard requires an allowlisted host for each
connection and refuses missing hosts, local sockets and UDP. Child processes,
native bindings and DNS answers remain outside that guard. See the [code API guide](src/canvas_mcp/code_api/README.md).

<a id="hosted-server-retired"></a>

The public hosted endpoint is retired. Use local mode or an authenticated
self-hosted deployment; see [HTTP deployment guidance](deploy/azure/).

## Development and history

<a id="documentation"></a>
<a id="sdm-repository-maintenance"></a>
<a id="publishing"></a>

The [documentation map](docs/documentation-map.md) identifies current guides.
The [annotated technical manual](ANNOTATED_TECHNICAL_MANUAL.md) maps key functions,
callers, state, setup and offline verification.
[CLAUDE.md](CLAUDE.md) contains development and validation rules;
[maintenance](docs/repository-maintenance.md) explains branch ownership, recovery
and installed overlays. Reviewed source, installed behavior, teacher acceptance
and verified delivery are distinct states. A documentation/source merge does not
restart a service, deploy the menu, release a package or send classroom grades.
Tags and deployment/paid-review actions require separate authorization.

The refreshed source incorporates upstream v1.19.0, including read-only
main-server defaults and a desktop-extension write allowlist. It retains the
stricter TypeScript sandbox network guard, strict course identifiers, guarded
rubric creation and accessibility source validation.
Upstream package releases and this fork's source or installed runtimes have
separate release histories. This update alone installs no runtime.
Release notes remain in [CHANGELOG.md](CHANGELOG.md); dated audits and design
records remain linked from the current guides. The
[pre-trim README](https://github.com/sirdanielm/canvas-mcp/blob/d0794b247df2b865150c4805d816b9075768ae92/README.md)
retains earlier client examples, contributor credits and release narratives.

## License

[MIT](LICENSE). Created by [Vishal Sachdev](https://github.com/vishalsachdev);
maintained SDM changes are tracked in this fork.
