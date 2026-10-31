# Unapproved proposal previews

`canvas_mcp.gradebook.proposal_preview` prepares a private review of explicitly
selected, already evaluated results. It does not score evidence, construct a
provider or Canvas client, stage EDIT values or publish anything. The library
has no server registration or live fleet connection. Its availability is
separate from source admission, installation and actual proposal production.

## Prepare a review

Trusted application code supplies at most 25 mapped rows, the original and
current Canvas observations, canonical PIN bindings, exact assignment bindings
and an independent synchronous `source_check`. Use the existing source owner's
qualified reader; an arbitrary callback, copied hash or caller-created flag
does not establish academic authority.

```python
from canvas_mcp.gradebook.proposal_preview import prepare_preview

preview = prepare_preview(
    selected_proposals,
    baseline=original_snapshot,
    current=current_snapshot,
    pin_binding=canonical_pin_binding,
    assignment_bindings=selected_assignment_bindings,
    source_check=qualified_source_check,
)
```

The callback must independently revalidate the actual saved source, request,
result, policy/configuration, identity and review revisions. It receives copies
of the proposed rows and bindings and must return `None`; exceptions or any
other return value stop preparation. Producer references remain opaque. A
`proposal_sha256` identifies the Canvas-mapped row, not a producer's native
serialization or a teacher's approval.

Each selected row must preserve its exact course, user, assignment, section,
actual observed Canvas attempt and submitted timestamp. Canonical PIN joins
must be unique and retain leading zeros. Missing or conflicting evidence is a
hold. Current target visibility, excusal, points, grading type, teacher-owned
corrections and score floors are checked. The existing three-way comparator
holds changed Canvas values and proposed grade decreases. External tools remain
held; Edpuzzle cannot enter an eligible or retained scored pair.

## Keep review and delivery separate

`GRASS_SUMMATIVE` requires `SCORE_AND_FEEDBACK` with complete feedback.
`SDMGRASS_FORMATIVE` requires `SCORE_ONLY`; any retained analysis stays private
and creates no student-comment intent. This policy selects an outbound channel,
not a scoring rule or permission to use that channel.

The result remains `UNAPPROVED`, all approval/publication fields are false and
`requests` is empty. Already satisfied targets create no edit. Held records are
documentary only; Edpuzzle and unknown-scope records retain references without
scored content. A valid unrelated selected row may still be reviewed when
another row is held. Preparation changes none of its supplied inputs.

`save_preview(existing_store, preview)` optionally retains the review through
the existing private, immutable `Store` as a `review` artifact. It validates the
preview digest, channel policies and documentary holds before saving. Use the
existing owner-controlled state; a new directory does not replace operation
history. Repeated identical saves reuse the same content-addressed artifact.
Saving establishes no new source, acceptance or delivery authority.

Keep full rows, feedback, identity mappings, source references and review files
private and outside Git. Report aggregate counts only. The caller owns current
observations and later revalidation; these local checks do not establish an
atomic or permanently fresh view of Canvas. Installation, owner composition,
ordinary draft staging and separately authorized publication remain distinct
steps in the [transfer guide](teacher-edit-transfer.md).
