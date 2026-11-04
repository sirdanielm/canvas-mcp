# Security and resource-limit follow-up status

Track source repairs separately from installed mitigation. HTTP body bounds and
access-key comparison now have focused regressions; the other findings remain
open below. These source changes enable no TypeScript execution, deployment,
service restart or classroom operation. Installed processes retain their current
source and private bindings until separately qualified adoption.

| Finding | Current observation | Follow-up and validation needed |
| --- | --- | --- |
| S2: child-output buffering | `execute_typescript` captures stdout and stderr through `process.communicate()` in [code_execution.py](../../../src/canvas_mcp/tools/code_execution.py). A time limit does not cap accumulated host output bytes. | Bound and drain both pipes without deadlock; test overflow, cancellation and retained diagnostics. This concerns installations that explicitly enable code execution. |
| S4: HTTP body limit — repaired in source | The outer [HTTP middleware](../../../src/canvas_mcp/server.py) bounds complete MCP request bodies to 1 MiB before authentication side effects or parsing; the public confirmation form retains its 8 KiB cap. It rejects oversized declared/streamed bodies, invalid framing and incomplete requests before forwarding. | [Focused HTTP regressions](../../../tests/security/test_http_request_limits.py) exercise the actual launcher stack, chunked/misstated lengths, inclusive boundaries, disconnect/cancellation, replay and real MCP initialization. Proxies still need their own concurrency/header/time limits; this is not an installed-service claim. |
| S5: caller-supplied regex | Announcement selection in [discussions.py](../../../src/canvas_mcp/tools/discussions.py) calls `re.search` on supplied patterns without a time bound. | Choose a bounded matching contract or timeout-capable implementation; preserve preview/confirmation behavior and test compatibility and slow patterns. |
| S6: access-key comparisons — repaired in source | `_access_key_ok` compares UTF-8 bytes against every configured key without short-circuiting on a match. Invalid UTF-8 headers are rejected rather than silently dropping bytes. | [Focused regressions](../../../tests/security/test_http_request_limits.py) check every match position, misses, non-ASCII keys and malformed-header refusal. This removes the early-exit contract defect; it does not promise that the whole HTTP request has constant timing. |
| S7: anonymization cache growth | [anonymization.py](../../../src/canvas_mcp/core/anonymization.py) retains an unbounded process-global mapping cache; an explicit clear helper does not impose a size limit. | Review deterministic-ID and statistics requirements, then remove or bound the cache with identity-compatibility and workload tests. |

The earlier branch-landing instructions, test counts and optional optimization
ideas are retained in [fixed history](https://github.com/sirdanielm/canvas-mcp/blob/16b06b5151c3595b043cb300e963b7de448ca738/docs/superpowers/plans/2026-09-06-security-review-followups.md).
Their age does not close the remaining open findings above. Keep each source
repair's tests and promotion evidence separate from loaded-runtime qualification.

Use the [current goals and owner agenda](../../goals-and-status.md),
[developer validation rules](../../../CLAUDE.md) and
[repository maintenance procedure](../../repository-maintenance.md) to scope
any separately authorized repair.
