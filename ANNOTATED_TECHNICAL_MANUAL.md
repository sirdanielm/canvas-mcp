# Annotated technical manual

Source map reviewed October 14, 2026 against `d0794b2` plus the documentation-only
Unit 2 branch. This is a guide to consequential functions, not an exhaustive code
review or evidence of installation. [CLAUDE.md](CLAUDE.md) owns development rules;
[tool contracts](tools/README.md) and the [architecture](internal/architecture.md)
provide the longer reference. Source links below identify the reviewed functions.

## Three interfaces, separate authority

| Interface | Entry point | State and boundary |
| --- | --- | --- |
| General Canvas MCP | `canvas-mcp-server` → `server.main` | Role-filtered MCP tools; shared Python Canvas transport. HTTP callers supply their own token. |
| Private gradebook | `scripts/sdm_gradebook_launcher.py` → `gradebook.server.create_server` | Exact local course/workbook bindings, private immutable snapshots, optional score/comment publication gates. It does not use the general MCP anonymizing client. |
| Course mirror | `scripts/course_mirror.py` → `mirror.core` | GET-only course-content snapshots, local comparisons and draft proposals; separate from student gradebook data. |

The TypeScript code API is another direct Canvas transport inside the optional
execution feature. It does **not** inherit the Python anonymization layer.
The Unit 2 evidence/scoring helper lives outside this repository; this server is
not its grader. Source, installed runtime, teacher acceptance and delivery are
separate facts.

## Function map: MCP and transport

| Function and source | Input → result; connection and annotation |
| --- | --- |
| [`main`](src/canvas_mcp/server.py#L550) | CLI arguments/environment → configured server. Parses `--help` before loading configuration; validates transport/auth, registers tools, applies write policy and starts serving. Ordinary startup is a live service operation. |
| [`register_all_tools`](src/canvas_mcp/server.py#L427) | FastMCP instance + role → registrations. Installs result contracts, shared tools, role-specific tools and resources. A registered tool can still be removed by policy. |
| [`resolve_tool_policy`](src/canvas_mcp/core/tool_policy.py#L193) | Raw `ALLOWED_WRITE_TOOLS` + transport → policy or error. Unset HTTP defaults to no writes; unset stdio retains legacy behavior. Explicit `none` is the safe read-only choice. |
| [`apply_tool_policy`](src/canvas_mcp/core/tool_policy.py#L242) | Registered server + policy → removed tool names. Removes disallowed side-effect tools; unknown effect classifications fail closed when policy is enforced. This is not the separate gradebook push gate. |
| [`validate_params`](src/canvas_mcp/core/validation.py#L355) | Tool decorator → asynchronous argument-validation wrapper. Uses `validate_parameter` before invoking the tool. This checks shape/type, not academic correctness or human permission. |
| [`make_canvas_request`](src/canvas_mcp/core/client.py#L403) | Method/path/parameters/payload → decoded result or explicit failure. Resolves per-request versus stdio credentials, rejects path smuggling, bounds concurrency, classifies write outcomes and applies endpoint-specific anonymization. Mutation calls require their owning tool's authorization. |
| [`fetch_all_paginated_results`](src/canvas_mcp/core/client.py#L743) | Endpoint + query → complete list or error. Calls the shared request function, follows opaque next links within origin/endpoint constraints, rejects cycles/page-budget exhaustion and anonymizes the completed set once. Partial data is not success. |
| [`ConfirmationGuard.fingerprint`](src/canvas_mcp/core/write_confirmation.py#L126) | Exact preview fields → caller-bound digest. Length-prefixes fields; tokens must remain bound to the same caller, target and content. |
| [`ConfirmationGuard.claim`](src/canvas_mcp/core/write_confirmation.py#L252) | Token + fingerprint → owning claim or error. Single-use process-local reservation; `ConfirmationClaim.finish` releases only a proven non-dispatch/rejection. Uncertain writes remain spent. A token is not proof a teacher approved. |
| [`initializeCanvasClient`](src/canvas_mcp/code_api/client.ts#L31) / [`fetchAllPaginated`](src/canvas_mcp/code_api/client.ts#L257) | Explicit URL/token/config → TypeScript client; endpoint → complete list. Independent direct-HTTP path with its own validation, pagination and request rules. Keep execution disabled unless separately commissioned. |

Representative tests: [Python transport](tests/core/test_client.py),
[transport state machine](tests/core/test_client_state_machine.py),
[write policy](tests/security/test_tool_policy.py),
[confirmation claims](tests/security/test_confirmation_claims.py), and
[TypeScript tests](tests/code_api).

## Function map: private gradebook and worker

| Function and source | Input → result; connection and annotation |
| --- | --- |
| [`gradebook.server.create_server`](src/canvas_mcp/gradebook/server.py#L23) | Dedicated client/store/course map and gates → `canvas-gradebook` MCP server. Registers reads/previews; push and comment tools depend on separate `enable_push`/`enable_comments`. |
| [`GradebookClient.snapshot`](src/canvas_mcp/gradebook/client.py#L127) | Course ID → complete normalized snapshot. Dedicated GET-only methods retain exact identities only in private artifacts. One deadline covers discovery, pagination and rate-limit waits; partial snapshots are rejected. |
| [`Store.save`](src/canvas_mcp/gradebook/store.py#L22) / [`Store.load`](src/canvas_mcp/gradebook/store.py#L50) | Kind + artifact or digest → immutable private file/reference or verified artifact. Digest-checked storage is provenance, not live freshness or teacher acceptance. |
| [`compare_edits`](src/canvas_mcp/gradebook/model.py#L174) | Trusted baseline + fresh snapshot + proposed edits → classified review. Separates eligible changes, no-ops and review-required cases. It neither grades work nor sends updates. |
| [`prepare_refresh`](src/canvas_mcp/gradebook/service.py#L55) | Client/store/course/binding/literal cell maps → saved refresh plan. Reads Canvas, checks trusted baseline and grid order, calls `merge_refresh`, saves artifacts and constructs Sheets requests. It sends neither Sheets nor Canvas mutations. |
| [`merge_refresh`](src/canvas_mcp/gradebook/refresh.py#L67) | Baseline + current + edits → retained baseline/display/review. Preserves each pending edit's original conflict evidence; incompatible roster/schema changes hold refresh. Pure transformation, no transport. |
| [`verify_refresh_output`](src/canvas_mcp/gradebook/refresh.py#L486) | Saved plan + reread cells + phase → verified comparison or exception. Used before sending and after readback; a prepared batch alone does not prove it was applied. |
| [`RefreshWorker.step`](src/canvas_mcp/gradebook/worker.py#L394) | Bound worker + queue metadata/journal → one state transition. Locks one workbook, claims exact requests, prepares both courses before application and reconciles uncertain sending states. Google metadata/Sheet writes are possible; Canvas remains GET-only. |
| [`Publisher.prepare`](src/canvas_mcp/gradebook/publish.py#L570) | Course + saved review → fresh bound preview/operation/token, or hold. Rechecks Canvas, limits a push to 25 changes and writes private plans/ledger state; Canvas writes remain zero. |
| [`Publisher.confirm`](src/canvas_mcp/gradebook/publish.py#L646) | Course + operation + token → durable item outcomes. Claims the operation, revalidates every target, marks `sending`, calls `put_once`, then independently reads back. Stops on rejection/uncertainty/conflict. This can write Canvas scores. |
| [`put_once`](src/canvas_mcp/gradebook/publish.py#L404) | Exact validated change → one score/excuse PUT or classified rejection/uncertainty. No comments, redirect following or automatic retry; a 200 response is insufficient without semantic readback. |
| [`Publisher.reconcile`](src/canvas_mcp/gradebook/publish.py#L713) | Existing operation → refreshed durable outcomes. GET-only reconciliation of `sending`/`uncertain`; does not retransmit. Comment prepare/confirm/reconcile methods are separate and separately enabled. |

Representative tests: [refresh merge/plans](tests/test_gradebook_refresh.py),
[publisher](tests/test_gradebook_publish.py), [worker](tests/test_gradebook_worker.py)
and [worker integration](tests/test_gradebook_worker_integration.py). These use
controlled fixtures; passing them does not establish live grade correctness.

## Function map: course content

| Function and source | Input → result; connection and annotation |
| --- | --- |
| [`capture`](src/canvas_mcp/mirror/core.py#L217) | GET client + selected course + private destination → dated content snapshot/manifest. Preserves source responses and asset provenance. Does not capture student grade/submission records. |
| [`verify`](src/canvas_mcp/mirror/core.py#L357) | Saved snapshot root → structural/hash findings. Offline integrity checking; callers use `require_valid` to refuse invalid snapshots before comparison/proposals. |
| [`diff`](src/canvas_mcp/mirror/core.py#L480) | Two validated snapshots → normalized content differences. No Canvas mutation; draft authoring remains a later explicitly authorized workflow. |

Tests: [course mirror](tests/test_course_mirror.py).

## How the functions connect

```text
General tool request
  → role registration + enforced write allowlist
  → validate_params → tool implementation
  → make_canvas_request / fetch_all_paginated_results → formatted MCP result

Gradebook refresh
  → RefreshWorker.step → prepare both bound courses
  → prepare_refresh → baseline + fresh GET → merge_refresh → private plans
  → fresh-input check → durable SENDING → one Sheets batch
  → verify_refresh_output → VERIFIED, or HELD/UNCERTAIN + readback-only recovery

Reviewed score publication (separately enabled)
  → compare_edits → Publisher.prepare → exact teacher-approved preview
  → Publisher.confirm → ledger sending → put_once → GET comparison
  → verified outcome; uncertain result → Publisher.reconcile, never blind resend
```

Registration and policy happen at startup; they are not repeated by each tool.
The refresh worker and publisher share private artifact contracts, not mutation
authority. General MCP confirmation tokens and gradebook operation tokens are
also different mechanisms. Never substitute one service's token/gate for another.

## Local setup and offline verification

Run from the repository root. Python **3.11+** is declared in `pyproject.toml`;
CI covers 3.11–3.13. `uv.lock` pins Python dependencies. Node/npm are needed only
for the TypeScript build/tests; this repository does not declare a Node engine.

```bash
# Install the reviewed development dependencies; no Canvas credentials required.
uv sync --frozen --group dev --extra local-exports

# Offline command discovery and complete Python tests.
uv run canvas-mcp-server --help
uv run python -m pytest tests/ -v -rf

# Focus a transport/gradebook change; retain the complete suite before delivery.
uv run python -m pytest tests/core/test_client.py tests/security/ -q
uv run python -m pytest tests/test_gradebook_refresh.py tests/test_gradebook_publish.py tests/test_gradebook_worker*.py -q

# TypeScript: install from package-lock, compile, run controlled tests.
npm ci
npm run build
npm test

# Static checks and package build.
uv run ruff check src/ tests/
uv run mypy src/
uv build
```

`uv sync`/`npm ci` download dependencies; tests above use controlled transports,
not teacher records or live credentials. `npm run build` writes generated
JavaScript; none of these commands deploys the server. Formal confirmation/client
proofs have a separately pinned Lean/Java/TLC toolchain; follow
[verify/README.md](verify/README.md), then run `TLA_JAR=/path/to/reviewed/tla2tools.jar uv run python verify/run.py`. Missing proof tools are a reported limitation.

## Credentials, configuration and operational traps

- `env.template` documents settings; a real local `.env` stays private. Stdio uses
  `CANVAS_API_URL` and `CANVAS_API_TOKEN`. HTTP pins the URL and refuses a server
  token; callers supply `X-Canvas-Token` through the configured authentication
  boundary. Do not use `--test` as an offline check: it contacts Canvas.
- For a separately authorized read-only server, explicitly set
  `ALLOWED_WRITE_TOOLS=none` and keep code execution disabled. An unset stdio
  allowlist is not read-only. Do not broaden an installed deployment's allowlist.
- Gradebook launchers use separate local bindings, artifacts and optional Keychain
  dependencies. Follow the [gradebook runbook](docs/sdm-gradebook-workflow.md)
  and [worker runbook](docs/sdm-gradebook-worker.md); a repository update is not an
  installation or worker restart. No generic clasp setup is needed for this Python
  service. The existing Apps Script menu overlay has its own exact-target process.
- `Publisher.prepare` and refresh planning perform fresh reads and save private
  artifacts. They are not pure/offline checks. Score and comment delivery have
  distinct gates; raw response bodies and student artifacts do not belong in Git.
- HTTP retries, pagination, authentication and anonymization are implemented
  differently in the general Python client, private gradebook client and optional
  TypeScript client. Test the actual path affected by a change.

When changing a mapped function, update this guide's source link/contract and its
own regression tests, then run the repository's required checks. Use dated local
receipts for run results; keep changing counts, credentials and target IDs out of
this manual.
