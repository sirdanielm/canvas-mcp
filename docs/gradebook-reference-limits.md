# Gradebook reference allocation limits

The October 8 source repair reviews an existing bounded worker read allowance.
The worker sets `sheet_cell_limits={"Unit1 LI Records": 58_000}`. The Google
adapter applies an exact-name reference override before grid capture. The limit
counts allocated rows multiplied by allocated columns, including empty cells;
it is neither a student count nor a limit on grades.

All other reference sheets retain the default 50,000-cell cap. A smaller named
override remains effective. Grade-sheet row/column limits, the aggregate
1,000,000-cell cap, 10,000-cell chunks, request/time/response-byte budgets and
complete native-field verification remain enforced. No oversized input is
silently truncated or partially accepted.

Nine synthetic cases cover the worker factory, 58,000 accepted, 58,001 rejected,
default and exact-name behavior, smaller overrides and retained aggregate/grade
limits. Tests use fictional credentials and an injected transport.

This is a source contract addendum to the existing worker guide. It supersedes
that guide's earlier default-only reference-cap description for this named
worker allowance. Source review is separate from installation, service reload,
remote freshness and authorization to refresh, grade or publish.
