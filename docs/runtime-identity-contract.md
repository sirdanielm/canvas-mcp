# Runtime identity diagnostic

## Source status and operational boundary

`get_runtime_identity` is merged general-server source from
[PR44](https://github.com/sirdanielm/canvas-mcp/pull/44), with an explicit
`Effect.READ` classification. Merge and source tests do not install it, expose
it on a client's connection, or establish current service health. The October 31
supported-interface investigation obtained no connected diagnostic response;
actual loaded runtime identity remains **UNKNOWN**.

The original source/testing approval and subsequent publication covered fixed
software metadata in all three general-server profiles. They did not expand
sharing, account permissions, dedicated gradebook coverage, write access,
grading or runtime operations. Private deployment bindings stay outside this
contract. The [earlier qualification record](https://github.com/sirdanielm/canvas-mcp/blob/5f9f0ee41252556654b3c26d8c4bb0e83520543b/docs/runtime-identity-contract.md)
retains the initial five-file stage and its dated test/review history.

## Tool, registration and audience

`async def get_runtime_identity() -> str` takes no parameters. Its MCP argument
object is empty. It offers no module, file, path, URL, target or object selector.
It carries `ToolAnnotations(read_only_hint=True)` and the explicit classification
`"get_runtime_identity": Effect.READ`. No alias, exemption or filter bypass is
used. The zero-argument tool uses the exact approved decorator surface; the
existing `search_canvas_tools` validation decorator remains unchanged.

The existing registration path is `canvas_mcp.server:main` ->
`register_all_tools` -> shared `register_discovery_tools` -> `apply_tool_policy`.
The name is registered before the profile branches, so the source includes the
tool in all three profiles:

| Profile | Application meaning |
| --- | --- |
| student | Shared tools plus student-oriented tools |
| educator | Shared tools plus educator-oriented tools |
| all | Default combination of both role bundles |

Profiles select tool bundles; they do not confer Canvas account permissions.
Any caller admitted to an installed general-server tool surface can
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
and is excluded. This diagnostic does not change it or provide identity for all
served routes/processes. Optional gradebook targets being observable only when
already loaded is not coverage of the separate gradebook service.

SDK serverInfo, initialize and discover contracts remain untouched. The
application has no application-owned `server_info` handler. The SDK property may
default to a FastMCP library version and is not Canvas package identity. This
tool returns a separate JSON text result; it adds no field to SDK identity.

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
Actual connected runtime/target identity remains UNKNOWN without a valid
response through the intended existing authenticated connection.

## Verification and use

Repository tests cover fictional module/file cases, fail-closed filesystem
capabilities, portable UNKNOWN results, pure tool-policy/profile behavior,
controlled SDK registration/schema checks and mixed repository collection.
These source tests do not inspect a live server or qualify account permissions,
scientific results, grade delivery or whole-process readiness.

If the diagnostic is available through the intended authenticated general-server
connection and the current task admits the read, use its empty argument object.
Do not import optional targets, construct a fresh local application, install an
endpoint or substitute process inspection to manufacture loaded-runtime proof.
An unavailable tool or unqualified target remains UNKNOWN. See
[tool usage](agent-usage.md#software-identity-diagnostic) for the calling surface.

The original deployment owner retains installation/restart/activation work.
Keep source publication, installed binding, observed loaded code and service
health as separate evidence. Earlier denied/uncertain operations and all
academic, destination and publication holds retain their original scope.
