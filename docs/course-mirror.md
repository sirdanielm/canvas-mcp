# Local course mirror

The local mirror supports content GETs, deterministic offline QC/comparisons, link
inventory, and local description proposals. It has no apply, push, publish, delete,
grading, or messaging command. The existing authoring and gradebook services are
separate capabilities; using this CLI does not enable or call their writers.

## Scope and authority

The fixed allowlist contains Chemistry, Advanced Chemistry, and Advisory at the
configured FCPS Canvas origin. Each course must return `workflow_state=available`
before its content is captured. Unpublished assignments inside those published
courses are retained as context and labeled by their actual publication state.
The unrelated public-webpage course is outside scope.

Canvas remains the source of truth. Captures are observations over a time interval,
not server-side atomic backups. Keep the archive under Git-ignored
`local_gradebooks/`. Student rosters, grades, submissions, replies, and paid/model
calls are outside this content collector. Existing gradebook tooling remains the
separate path for authorized private grade/status snapshots. Permanent PINs come
from its registry-bound `Student Info` source, described in the
[PIN policy](STUDENT-PIN-POLICY.md); this content mirror is not an identity registry.
A content snapshot or description proposal also does not admit evidence into the
[new grading workflow](grass-workflow-integration.md).

## Daily commands

The control interface is `scripts/course_mirror.py`; there is currently no control
spreadsheet, dashboard, background refresh, or automatic baseline selection. `status`
lists local snapshots with their capture times, course scope, and `qc_ok` result.
Use a snapshot with `qc_ok: true` for comparisons or drafting.

Run from the repository root using its existing Python environment:

For a fresh macOS checkout, install with
`uv sync --frozen --group dev --extra local-keychain`, then follow the
[Keychain setup and connection checks](sdm-canvas-authoring-workflow.md#local-setup-and-connection-checks).
`get` requires that saved connection and its fixed FCPS origin; the offline commands
do not require a Canvas credential.

```bash
.venv/bin/python scripts/course_mirror.py get
.venv/bin/python scripts/course_mirror.py status
.venv/bin/python scripts/course_mirror.py verify PATH_TO_SNAPSHOT
.venv/bin/python scripts/course_mirror.py audit PATH_TO_SNAPSHOT
.venv/bin/python scripts/course_mirror.py diff OLD_SNAPSHOT NEW_SNAPSHOT --output local_gradebooks/course_mirror/reports/unique-delta.json
.venv/bin/python scripts/course_mirror.py links PATH_TO_SNAPSHOT --output local_gradebooks/course_mirror/reports/unique-links.json
.venv/bin/python scripts/course_mirror.py resources-check PATH_TO_EXISTING_ARCHIVE
```

For a refresh and delta check, run `status` and record the intended baseline path,
then run `get`. Its JSON output gives the new `snapshot_path`, request count, QC,
course counts, and audit findings. Run `diff BASELINE_PATH NEW_SNAPSHOT_PATH`
separately to calculate the delta; `get` does not calculate or save a delta report.
Use `--output` with `diff`, `audit`, or `verify` to retain a report, and choose a new
filename each time. `links` requires `--output`; it saves the full private link map
there and prints only summary counts.

`get --courses core advanced` narrows a run. Default is all three approved courses.
`get` and `status` accept `--root` to select a different local snapshot directory;
their default is `local_gradebooks/course_mirror/` under the repository root.
The Keychain connection is the same one used by the installed Canvas launcher;
the Canvas API token never enters command arguments, snapshot JSON, or reports.
Raw Canvas responses can contain signed resource URLs, so keep snapshots and link
maps private. Only `get` reads credentials or reaches Canvas. All other commands
work offline.

Every GET run creates a new timestamped directory. It saves each completed endpoint
and updates a durable manifest; a failed or interrupted run remains `INCOMPLETE`.
Run `get` again to create a fresh capture. This first version does not combine a
partial capture with later data or silently select an older baseline. `status`
shows incomplete and valid captures; choose an explicit baseline. No capture is
deleted or rewritten by refresh.

Only full paginated lists can establish absence. A refresh fetches complete content
lists for a later local comparison; it does not claim a universal Canvas delta API
or download only changed objects. Runtime depends on endpoint count, pagination,
latency, and rate limiting. Traffic is sequential, with
100-page limits per endpoint, a 30-second request timeout, and up to three attempts
for 429/502/503/504. A `Retry-After` above 15 seconds or a nonnumeric value stops for
a later fresh run. Network exceptions also stop the capture. No auth retries,
redirect following, or cross-origin/cross-endpoint pagination is allowed.

## Captured and excluded surfaces

Captured: course/syllabus, settings, navigation, sections without roster lists,
assignment descriptions and section-date summaries, assignment groups, modules and
all their items, pages and page bodies, rubrics and details, file metadata, Classic
Quizzes/questions, and announcements. Exact scope and exclusions are in each manifest.

This first CLI does not refresh Google exports, file bytes, New Quizzes/item banks,
submission/grade data, exact override endpoint records, or histories. Existing Google
exports stay in the earlier private archive. `resources-check` verifies their hashes
and sizes; it is not a Google freshness or permission check. Use the Drive connector
for a deliberate linked-resource refresh and retain its revision time and capture
time separately. `links` inventories absolute HTTP(S) HTML hyperlinks/image references,
module URLs, and opaque LTI launch URLs. Relative URLs and other schemes are excluded;
it does not fetch the targets or check for broken links. A resolvable Google ID is not
proof of student visibility.

Use Drive documents as teacher-authorized assumed template/key mappings until the
actual LTI attachment is confirmed. Store that provenance explicitly. Do not infer a
student's source document from a template ID, course title, or assignment code alone.

## QC and comparisons

`verify` checks completion, expected endpoints and details, hashes, counts, duplicate
identities, course identity, and paths. It also recognizes the earlier archive format.
`audit` checks assignment references, publication alignment, repeated module placement,
and published assignments outside modules. Findings are review candidates, not repairs.
An audit can exit successfully while reporting findings: inspect both `qc` and
`findings`. CLI exit code `2` means a returned QC/resource check failed or a proposal
conflicted; exit code `1` means the operation stopped with an error. A successful
command alone is not evidence that the course has no audit findings.

`diff` compares stable object IDs within shared endpoint scopes. Newly added courses
are `scope_added`; omitted endpoints are `scope_absent`, never mass deletions. A missing
object is `removed_from_snapshot`, not proof of deletion. Changed-field lists contain
no response bodies or student values. Top-level `url` and `html_url` fields, selected
timestamps, grading counters, and user lock state are excluded; original JSON is
retained. This normalization applies to every object type, so a page-slug-only change
in `url` is not reported. Inspect original page objects when checking page addressing.
Other fields, including LTI attributes, HTML, points, dates, and module positions,
are compared.
Signed course-image URLs can change when their access tokens rotate even if the
underlying resource is unchanged. Review the stable resource identity before
classifying such a field change as an instructional edit; do not copy signed URLs
into public reports.
Different endpoint include-options can appear as schema differences and need inspection.

Date overrides simply represent separate deadlines/availability for sections such as
A-day and B-day. They are normal and require no automatic cleanup. The mirror observes
them. A future schedule proposal must read exact override records before any edit.

Keep operational/identity files and teacher keys outside a general curriculum corpus.
OCR is a searchable derivative, not a replacement for the scanned page. Sparse alt text
is an accessibility review signal; it is not permission to rewrite source materials.

## Drafting a description change

```bash
.venv/bin/python scripts/course_mirror.py stage-description SNAPSHOT core ASSIGNMENT_ID local-draft.html local_gradebooks/course_mirror/proposals/unique-proposal.json
.venv/bin/python scripts/course_mirror.py check-proposal FRESH_SNAPSHOT local_gradebooks/course_mirror/proposals/unique-proposal.json
```

A proposal preserves the before-description, proposed HTML, source-object hash, and
point/publication/date/LTI fields. Its status is always `DRAFT_NOT_AUTHORIZED`.
`check-proposal` reports a match or conflict; neither authorizes a write, and a conflict
returns a nonzero exit code. Output files are exclusive-create, so a new proposal/report
cannot silently overwrite an earlier one. Raw HTML is untrusted content; do not open it
in an unrestricted browser that can run scripts or fetch remote resources.

The proposal baseline uses the entire original assignment object. Unlike `diff`, it
does not exclude volatile fields, so a timestamp or transport-field change can also
produce a conflict. Review the fresh object and prepare a new proposal when needed;
neither a baseline match nor a clean delta substitutes for fresh authorization.

The future write sequence is: teacher sees the exact diff → teacher explicitly approves
the targets and change → fresh GET baseline check → description-only authorized update
through a separate tool → readback of description and protected fields → durable receipt.
If the source changes, prepare a new diff and obtain approval for its final contents.
No writer has been built as part of this milestone.

## Validation

```bash
.venv/bin/pytest tests/test_course_mirror.py -q
.venv/bin/ruff check src/ tests/
.venv/bin/mypy src/
.venv/bin/pytest tests/ -q
```

Tests use synthetic data and mocked GETs. They cover hostile pagination, redirects,
unexpected endpoints, duplicates, incomplete capture retention, module-count races,
unpublished course rejection, tampering, meaningful deltas, proposal conflicts, and
resource path escape. A live GET plus saved-file verification proves connectivity and
capture integrity; it does not prove grading quality or student permissions.
