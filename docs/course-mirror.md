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
separate path for authorized private grade/status snapshots.

## Daily commands

Run from the repository root using its existing Python environment:

```bash
.venv/bin/python scripts/course_mirror.py get
.venv/bin/python scripts/course_mirror.py status
.venv/bin/python scripts/course_mirror.py verify PATH_TO_SNAPSHOT
.venv/bin/python scripts/course_mirror.py audit PATH_TO_SNAPSHOT
.venv/bin/python scripts/course_mirror.py diff OLD_SNAPSHOT NEW_SNAPSHOT --output local_gradebooks/course_mirror/reports/unique-delta.json
.venv/bin/python scripts/course_mirror.py links PATH_TO_SNAPSHOT --output local_gradebooks/course_mirror/reports/unique-links.json
.venv/bin/python scripts/course_mirror.py resources-check PATH_TO_EXISTING_ARCHIVE
```

`get --courses core advanced` narrows a run. Default is all three approved courses.
The Keychain connection is the same one used by the installed Canvas launcher;
credentials never enter command arguments, snapshot JSON, or reports. Only `get`
reads credentials or reaches Canvas. All other commands work offline.

Every GET run creates a new timestamped directory. It saves each completed endpoint
and updates a durable manifest; a failed or interrupted run remains `INCOMPLETE`.
Run `get` again to create a fresh capture. This first version does not combine a
partial capture with later data or silently select an older baseline. `status`
shows incomplete and valid captures; choose an explicit baseline. No capture is
deleted or rewritten by refresh.

Only full paginated lists can establish absence. A refresh fetches complete content
lists and computes local deltas; it does not claim a universal Canvas delta API or
download only changed objects. This costs about one minute for the current three
courses and avoids false removals from partial reads. Traffic is sequential, with
100-page limits per endpoint, a 30-second request timeout, and up to three attempts
for 429/502/503/504. A long `Retry-After` stops for a later fresh run. No auth retries,
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
time separately. `links` inventories HTML hyperlinks/image references, module URLs,
and opaque LTI launch URLs. A resolvable Google ID is not proof of student visibility.

Use Drive documents as teacher-authorized assumed template/key mappings until the
actual LTI attachment is confirmed. Store that provenance explicitly. Do not infer a
student's source document from a template ID, course title, or assignment code alone.

## QC and comparisons

`verify` checks completion, expected endpoints and details, hashes, counts, duplicate
identities, course identity, and paths. It also recognizes the earlier archive format.
`audit` checks assignment references, publication alignment, repeated module placement,
and published assignments outside modules. Findings are review candidates, not repairs.

`diff` compares stable object IDs within shared endpoint scopes. Newly added courses
are `scope_added`; omitted endpoints are `scope_absent`, never mass deletions. A missing
object is `removed_from_snapshot`, not proof of deletion. Changed-field lists contain
no response bodies or student values. Top-level volatile transport URLs, timestamps,
grading counters, and user lock state are excluded; original JSON is retained. Other
fields, including LTI attributes, HTML, points, dates, and module positions, are compared.
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
