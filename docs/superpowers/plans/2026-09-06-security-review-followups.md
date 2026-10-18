# Known open security and resource-limit work

These previously reported findings remain visible in the current source. They
are unresolved maintenance work, not completed fixes or new execution authority.
Keep them separate from the classroom grading agenda; this documentation change
does not implement mitigations, enable TypeScript execution or alter HTTP policy.

| Finding | Current observation | Follow-up and validation needed |
| --- | --- | --- |
| S2: child-output buffering | `execute_typescript` captures stdout and stderr through `process.communicate()` in [code_execution.py](../../../src/canvas_mcp/tools/code_execution.py). A time limit does not cap accumulated host output bytes. | Bound and drain both pipes without deadlock; test overflow, cancellation and retained diagnostics. This concerns installations that explicitly enable code execution. |
| S4: authenticated HTTP body limit | [server.py](../../../src/canvas_mcp/server.py) bounds the public approval-form body, then forwards authenticated MCP traffic without a universal application-level body cap. | Check the full HTTP path and deployment proxy limits; enforce and test both declared-length and streamed-byte limits before parsing. |
| S5: caller-supplied regex | Announcement selection in [discussions.py](../../../src/canvas_mcp/tools/discussions.py) calls `re.search` on supplied patterns without a time bound. | Choose a bounded matching contract or timeout-capable implementation; preserve preview/confirmation behavior and test compatibility and slow patterns. |
| S6: access-key comparisons | `_access_key_ok` in [server.py](../../../src/canvas_mcp/server.py) uses short-circuiting `any()` even though its comment says every key is compared. | Resolve the documented comparison contract and verify behavior across every configured key without short-circuiting. |
| S7: anonymization cache growth | [anonymization.py](../../../src/canvas_mcp/core/anonymization.py) retains an unbounded process-global mapping cache; an explicit clear helper does not impose a size limit. | Review deterministic-ID and statistics requirements, then remove or bound the cache with identity-compatibility and workload tests. |

The earlier branch-landing instructions, test counts and optional optimization
ideas are retained in [fixed history](https://github.com/sirdanielm/canvas-mcp/blob/16b06b5151c3595b043cb300e963b7de448ca738/docs/superpowers/plans/2026-09-06-security-review-followups.md).
Their age does not close the open findings above. No speculative hardening or
implementation work is included in the current documentation revision.

Use the [current goals and owner agenda](../../goals-and-status.md),
[developer validation rules](../../../CLAUDE.md) and
[repository maintenance procedure](../../repository-maintenance.md) to scope
any separately authorized repair.
