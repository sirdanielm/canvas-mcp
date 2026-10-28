# Runtime identity diagnostic: source-integrated candidate

## Disposition and approved boundary

**SOURCE_INTEGRATED_CANDIDATE_NOT_ADOPTED.** This isolated five-file candidate
adds `get_runtime_identity` to the general server discovery registration and
explicitly classifies it as `Effect.READ`. It has not been merged, installed,
restarted, activated, deployed or called through a real connection. Distinct
combined-source review remains required. The earlier distinct SOURCE_PASS covers
only the unchanged helper and its prior tests/contract, not this integration.

The human approval of October 28, 2026 at 20:20:17 UTC was given in response to
an exact source/testing/review question disclosing all three general-server
profiles, relative software paths, version metadata and code fingerprints.
Approval does not expand data sharing, dedicated gradebook coverage, runtime
operations, authentication, write access, grading, or publication authority.
The exact approved proposal and human evidence are retained outside these public
source files in the private review index. No private deployment locator belongs
in this contract.

The five source paths are `src/canvas_mcp/runtime_identity.py`,
`src/canvas_mcp/tools/discovery.py`, `src/canvas_mcp/core/tool_policy.py`,
`tests/test_runtime_identity.py`, and this document. The helper is byte-identical
to its reviewed starting material. The registration and policy postimages match
the exact approved proposal. Only this test file and contract change further to
cover the actual integrated source behavior. Original application, installed,
editable, dirty and previously frozen sources remain untouched.

## Tool, registration and audience

`async def get_runtime_identity() -> str` takes no parameters. Its MCP argument
object is empty. It offers no module, file, path, URL, target or object selector.
It carries `ToolAnnotations(read_only_hint=True)` and the explicit classification
`"get_runtime_identity": Effect.READ`. No alias, exemption or filter bypass is
used. The zero-argument tool uses the exact approved decorator surface; the
existing `search_canvas_tools` validation decorator remains unchanged.

The existing registration path is `canvas_mcp.server:main` ->
`register_all_tools` -> shared `register_discovery_tools` -> `apply_tool_policy`.
The new name is registered before the profile branches, so the prospective tool
surface expands for all three profiles:

| Profile | Application meaning |
| --- | --- |
| student | Shared tools plus student-oriented tools |
| educator | Shared tools plus educator-oriented tools |
| all | Default combination of both role bundles |

Profiles select tool bundles; they do not confer Canvas account permissions.
Any caller already admitted to a future adopted general-server tool surface can
request this fixed software metadata, including callers using student/read-only
profiles. Existing authentication and all other tool classifications and write
protections remain unchanged and are not qualified by this source work.

The explicit READ entry preserves the tool in both stdio and HTTP modes: unset
policy, explicit none/empty, all, and valid explicit side-effect-tool lists.
The stdio unset default remains unenforced; unknown names are still filtered
whenever policy is enforced. Invalid policies still reject startup. Naming this
READ tool in `ALLOWED_WRITE_TOOLS` remains invalid; do not add it there. No
resolver/filter function or existing side-effect membership changes.

The dedicated `canvas_mcp.gradebook.server` entrypoint does not register discovery
and is excluded. This candidate does not change it or provide identity for all
served routes/processes. Optional gradebook targets being observable only when
already loaded is not coverage of the separate gradebook service.

SDK serverInfo, initialize and discover contracts remain untouched. The accepted
application has no application-owned `server_info` handler. The SDK property may
default to a FastMCP library version and is not Canvas package identity. This
new tool returns a separate JSON text result; it adds no field to SDK identity.

## Result contract

The tool imports only the pure helper, lazily at invocation, and serializes its
result using deterministic JSON key order, compact separators and `allow_nan=False`.
An unavailable helper import yields fixed UNKNOWN with
`IDENTITY_HELPER_UNAVAILABLE`; no exception details are exported.

Normal top-level fields are `schema` (`CANVAS_RUNTIME_IDENTITY_V1`), `attestation`
(`SELF_REPORT_ONLY`), `declared_distribution`, `targets`, and `limitations`.
A top-level failure has only `schema`, `status: UNKNOWN`, and fixed `reason`.

`declared_distribution` is either `status: DECLARED_ON_DISK_ONLY`, fixed
`name: canvas-mcp`, `version: 1.16.0`, `origin: registered_distribution_metadata`,
or UNKNOWN with fixed reason. This is declared disk metadata, never an executing
package-version attestation. The narrow prototype reads one fixed Python3.12,
1.16.0 dist-info software location; it does not discover packages or scan sys.path.
Missing, duplicate, malformed, mismatched or oversized metadata stays UNKNOWN.

Each of at most three targets contains a fixed `target` alias and either UNKNOWN
with fixed `reason`, or `status: OBSERVED_SELF_REPORT`, software-relative `origin`,
`disk_source_sha256`, `loaded_code_sha256`, `code_format: CANVAS_SELECTED_CODE_V1`,
and `disk_loaded_equivalence: NOT_ATTESTED`.

| Fixed alias | Already-loaded selected function | Relative software origin |
| --- | --- | --- |
| canvas_server | canvas_mcp.server.create_server | src/canvas_mcp/server.py |
| gradebook_server | canvas_mcp.gradebook.server.create_server | src/canvas_mcp/gradebook/server.py |
| gradebook_google | canvas_mcp.gradebook.google.GoogleSheets.read_workbook | src/canvas_mcp/gradebook/google.py |

The helper reads only these fixed keys of the existing module map. It never
enumerates that map, imports optional targets, invokes a target, constructs a
client or obtains credentials. Absent or unqualified targets stay UNKNOWN.

## Separate observations and limits

1. Declared distribution metadata describes one current disk file only.
2. Current disk source SHA-256 describes the registered source bytes at observation
   time. It is never labelled loaded-runtime proof.
3. Selected loaded-code SHA-256 hashes an immutable canonical representation of
   an already-loaded function code object. A later disk edit can change the disk
   hash while leaving this selected loaded-code hash unchanged.

Module file, spec origin and function code filename must agree with the fixed
registered origin. Exact builtin module/function/class/spec types and selected
dictionary keys avoid descriptors and arbitrary object hooks. Files are bounded,
regular and single-link, with descriptor-based NOFOLLOW directory traversal and
file/directory identities rechecked before accepting bytes. Source reads are
limited to 2,000,000 bytes per fixed target; metadata to 65,536 bytes. Changed,
symlinked, mismatched or otherwise unqualified evidence stays UNKNOWN. Selected
module/function/code identity is checked again after the source read. This is an
interval observation, not an atomic system snapshot.

The code representation includes bytecode, constants, symbol names, flags,
argument counts, exception tables and nested code. It excludes filenames and
line tables/numbers, accepts only exact immutable builtin/code types, bounds
nodes/depth/bytes, and rejects unsupported or nonfinite constants. Transient
canonical bytes, constants, bytecode and source are never returned or saved.
The format is interpreter/code-layout sensitive, not a cross-version semantic
identity proof. The helper never changes original code/module/path bindings.

Output intentionally discloses fixed software identifiers, version metadata,
relative software paths and code fingerprints. It exports no absolute private
path, environment, argv, account/connection detail, configuration, credentials,
student identity, grades, source text, globals, closure cells or default values.
No Store/Google/Canvas/provider/keychain/network/native application client is
called. Mutable global/closure/default/client state, dependency/native ABI,
actual account permissions and whole-process readiness are outside this evidence.

`disk_loaded_equivalence` is always NOT_ATTESTED. Equal versions or hashes do not
establish disk-to-loaded equivalence, third-party attestation, approval, case
admission, scientific correctness, grade readiness, delivery or runtime readiness.
Actual connected runtime/target identity remains UNKNOWN until a separately
admitted future invocation through an existing authenticated connection.

## Software-only verification and remaining gates

The unchanged helper reuses its prior 26 helper checks and 12 independent checks.
Two prior unattached-wiring/policy assertions are updated for this integration.
New focused tests call the exact registration function extracted without changing
its body, using a labelled minimal recording implementation of the public MCP
decorator/list/remove protocol. Signature-derived protocol schema and literal
annotation kwargs are checked; this is not actual FastMCP-generated JSON Schema
or live SDK serialization evidence. The existing validation collaborator is
fictional for the pre-existing search tool; the new zero-argument tool does not
call that collaborator.

The isolated helper and maintained pure policy module use normal imports in a
fresh test-process namespace package. General-server construction wiring is
checked through its exact extracted registration function with labelled fictional
registration/config branch collaborators, never real configuration or clients.
The matrix exercises the real pure resolver/filter across all three profiles,
both transports and the disclosed policy modes. A fictional classification corpus
checks existing READ/write/code-execution membership; it does not claim every
profile registers every tool. Dedicated gradebook exclusion and unchanged source
functions/classifications are checked explicitly.

Full discovery/application imports are deliberately not executed: discovery
imports FastMCP and application validation; validation imports logging with global
logger setup and environment-dependent behavior. This job does not load those
application/SDK contexts or start a server to manufacture a test result. No
sys.modules injection, official class replacement or fake current authority is
used. Missing-helper tests intercept only that exact import to exercise the
fixed-error path. Prior helper fixtures remain wholly fictional.

Distinct combined-source review follows this freeze. Before any later promotion,
normal repository CI and mandatory new-tool catalog/guidance requirements must
be addressed in a separately admitted publication scope; `tools/README.md`,
`tools/TOOL_MANIFEST.json`, and relevant `docs/agent-usage.md` updates are outside
this exact five-file source stage. Dynamic discovery already lists the live
registry and needs no additional API module. No merge/publication is performed.
The original deployment owner retains future target qualification and separately
authorized installation/restart/activation. Source PASS or merge establishes none
of those operations. Historical denied/uncertain communication and all academic,
manifest-sharing, destination and grade-publication holds remain separate.
