# Private whole-percent rounding proposals

`canvas_mcp.gradebook.percent_rounding` is a pure local planning module. It has
no MCP/CLI registration, API transport, worksheet writer or publisher. Use an
explicit teacher-selected assignment scope; the module has no default scope
and does not assume that a Unit 1 decision covers every assignment.

`round_score_percent(value, points_possible)` computes
`ROUND_HALF_UP(value / points_possible * 100)` and converts that whole percentage
back to points. A score exactly halfway rounds upward. On a 100-point assignment,
74.5 becomes 75 points. On a 25-point assignment, 18.625 becomes 18.75 points.
The maximum stays exact; nearest whole percent does not imply whole points on
other scales. Binary float inputs use their existing decimal representation;
the module does not reconstruct precision already lost upstream. Numeric
rounding with invalid, negative, over-maximum, zero-maximum or noncanonical
inputs remains held.

`plan_percent_rounding` accepts private paired records keyed by exact
`course_id:user_id:assignment_id`. Every record supplies `course_id`, `user_id`,
`assignment_id`, `value`, `points_possible`, `grading_type`, full `feedback` and
the complete captured `context`. Pass explicit `assignment_scope` mapping each
course to a set of assignment IDs, `eligible_targets`, `protected_targets`, and
an opaque `policy_ref`. The caller owns authority checks and the exact protected
target registry; the planner infers neither.

The result preserves all original records and returns separate proposals with
exact identity, points, feedback and context. It records policy, source input,
authority-selection, original-record and context digests, plus the feedback's
exact UTF-8 SHA-256. Original qualifications remain attached to the unchanged
original evidence. Proposal-level teacher approval and source-approved derivative
binding are explicitly false. Changed ordinary proposals carry
`rounded_derivative_requires_source_binding`; protected targets remain unchanged
with `source_qualified_owner_rounding_required`. Resolve those bindings through
the existing source owner before publication. No rounding result qualifies its
own score authority or feedback delivery.

Blank values, excusals, zero and already rounded scores retain their existing
values and complete feedback. Out-of-scope records remain unchanged. A rounding
operation may reduce a proposal or put it below current Canvas; the canonical
decrease, stale-context, visibility, grading-period and source-qualification
guards still apply. Recompare against fresh Canvas before preparing an exact
user-reviewed operation. An immutable rounding draft is not a publisher token,
an approval, an observed Canvas grade or a verified delivery receipt.

All paired records and plans contain private student data. Save them only in
the ignored private gradebook store with owner-only permissions. Report aggregate
counts and artifact references; never load row-level scores, feedback or IDs
into chat. This module changes no existing score/comment release owner,
confirmed-push limit, posting policy or uncertain-operation recovery behavior.
