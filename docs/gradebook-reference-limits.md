# Gradebook reference allocation limits

The October 8 source repair reviews an existing bounded worker read allowance.
The worker sets `sheet_cell_limits={"Unit1 LI Records": 58_000}`. The Google
adapter applies an exact-name reference override before grid capture. The limit
counts allocated rows multiplied by allocated columns, including empty cells;
it is neither a student count nor a limit on grades.

All other reference sheets retain the default 50,000-cell cap. A smaller named
override remains effective. The reusable `GoogleSheets` constructor defaults to
10,000 allocated cells per chunk and 1.1-second read pacing. The worker factory
explicitly selects 100,000 cells per chunk and 5.0-second pacing alongside the
58,000-cell exact-name override. See
[`GoogleSheets`](../src/canvas_mcp/gradebook/google.py) and
[`google_client`](../scripts/sdm_gradebook_worker.py).

Grade-sheet row/column limits, the aggregate 1,000,000-cell cap, per-response
20 MB and cumulative 80 MB bounds, 200-chunk budget, 180-second whole-read limit
and complete native-field verification remain enforced. These decimal byte
bounds are not a guarantee about Python memory use. Larger chunks reduce
request/pacing overhead while increasing per-response memory; actual allocated
shape, response density and latency determine whether a capture fits. No
oversized input is silently truncated or partially accepted, and source values
do not establish a running process’s loaded configuration.

Nine synthetic cases cover the worker factory, 58,000 accepted, 58,001 rejected,
default and exact-name behavior, smaller overrides and retained aggregate/grade
limits. Tests use fictional credentials and an injected transport.

This is a source contract addendum to the existing worker guide. It supersedes
that guide's earlier default-only reference-cap description for this named
worker allowance. Source review is separate from installation, service reload,
remote freshness and authorization to refresh, grade or publish.
