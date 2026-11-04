# Security and resource-limit follow-up status

All five findings below have source repairs and focused regressions. Track
reviewed source promotion separately from installed mitigation. These source
changes enable no TypeScript execution, deployment,
service restart or classroom operation. Installed processes retain their current
source and private bindings until separately qualified adoption.

| Finding | Current observation | Follow-up and validation needed |
| --- | --- | --- |
| S2: child-output buffering — repaired in source | [Execution capture](../../../src/canvas_mcp/tools/code_execution.py) concurrently drains stdout/stderr with a shared 1 MiB retention ceiling. Timeout, overflow and cancellation stop/reap the owned process; abnormal container cleanup verifies ownership, removes only the immutable ID and reads back absence. | [Real-child regressions](../../../tests/security/test_subprocess_output_limits.py) cover simultaneous pipe output, exact bounds, timeout, cancellation, diagnostics and descendants. [Daemon-free lifecycle tests](../../../tests/security/test_owned_container_cleanup.py) cover ownership refusal, late creation, bounded cleanup and truthful `HELD/UNKNOWN` outcomes. Prior effects still require reconciliation before another execution. |
| S4: HTTP body limit — repaired in source | The outer [HTTP middleware](../../../src/canvas_mcp/server.py) bounds complete MCP request bodies to 1 MiB before authentication side effects or parsing; the public confirmation form retains its 8 KiB cap. It rejects oversized declared/streamed bodies, invalid framing and incomplete requests before forwarding. | [Focused HTTP regressions](../../../tests/security/test_http_request_limits.py) exercise the actual launcher stack, chunked/misstated lengths, inclusive boundaries, disconnect/cancellation, replay and real MCP initialization. Proxies still need their own concurrency/header/time limits; this is not an installed-service claim. |
| S5: caller-supplied regex — repaired in source | [Announcement selection](../../../src/canvas_mcp/tools/discussions.py) uses an isolated worker with a shared two-second deadline, at most two workers, bounded patterns/titles/input/output, and unchanged Python case-insensitive matching semantics. | [Focused regressions](../../../tests/security/test_announcement_regex_limits.py) cover catastrophic patterns, compatibility, boundaries, cancellation and cleanup. A held selection produces no preview or deletion; exact preview/confirmation bindings remain required. |
| S6: access-key comparisons — repaired in source | `_access_key_ok` compares UTF-8 bytes against every configured key without short-circuiting on a match. Invalid UTF-8 headers are rejected rather than silently dropping bytes. | [Focused regressions](../../../tests/security/test_http_request_limits.py) check every match position, misses, non-ASCII keys and malformed-header refusal. This removes the early-exit contract defect; it does not promise that the whole HTTP request has constant timing. |
| S7: anonymization cache growth — repaired in source | [Pseudonym retention](../../../src/canvas_mcp/core/anonymization.py) is capped at 4,096 entries per stdio process or HTTP request, with bounded retained ID/prefix lengths. Identity generation is independent of retention; statistics explicitly count cached mappings. | [Focused regressions](../../../tests/security/test_anonymization_cache_bounds.py) cover high-cardinality and oversized inputs, subclass bypasses, deterministic IDs/prefixes after eviction/clear, concurrency and HTTP isolation. This is bounded retention, not a lifetime student count or a change to permanent PIN authority. |

The earlier branch-landing instructions, test counts and optional optimization
ideas are retained in [fixed history](https://github.com/sirdanielm/canvas-mcp/blob/16b06b5151c3595b043cb300e963b7de448ca738/docs/superpowers/plans/2026-09-06-security-review-followups.md).
The source repairs above are supported by their current regressions, not the age
of that plan. Keep tests and reviewed promotion separate from loaded-runtime
qualification.

Use the [current goals and owner agenda](../../goals-and-status.md),
[developer validation rules](../../../CLAUDE.md) and
[repository maintenance procedure](../../repository-maintenance.md) to scope
any separately authorized repair.
