# Portable source and private runtime composition

Repository promotion preserves reusable transport, comparison and proposal code.
An installed process, private owner policy, teacher decision and delivery receipt
retain their own bindings. Publishing this source neither reloads a service nor
changes an existing operation's expiry, ownership or reconciliation state.

## Owner policy

The gradebook launcher accepts `--owner-adapter` and
`--owner-adapter-sha256` together. The adapter is an explicitly selected absolute
Python file, owned by the current operator, mode `0600`, with no symlink or hard
link and an exact SHA-256 pin. It exports `create_owner_policy()` returning
`canvas_mcp.gradebook.owner_config.OwnerPolicy`.

Keep actual targets, owner imports and private source references in that adapter.
The policy supplies synchronous source-scope and protected-target classifiers,
plus the applicable score-owner, paired-score-owner and comment-release
factories. A source pin verifies bytes; the configured owner must independently
check current source, teacher authority and durable operation history. Adapter
initialization errors are translated to fixed messages without private payloads.

Without an adapter, launcher score sends stay held while reads remain available.
The explicit read-only profile does not load the adapter. Library callers may
supply trusted callbacks directly to `create_server`; MCP arguments cannot select
an adapter, private path, owner callback or raw release body. Batch execution must
apply the same source-owner boundary as individual score operations.

## Other private references

- `TextCommentDelivery` and its fresh-completion subclass require an explicit
  `canonical_root`. Store and ledger identities must match it exactly.
- Manual native readers require an owner-supplied `native_source_ref`; manifests
  cannot choose their own judge. Exact source bytes are rechecked on replay.
- Unit 2 typed capture uses registered bounded read-only ranges and a separately
  pinned sink. The CLI and public capture receipt carry metadata only; native
  cell values belong in the private sink.
- Optional whole-number GET display belongs in the existing private workbook
  binding's `get_whole_number_display` object. Its exact fields are `origin`,
  `spreadsheet_id`, `course_id` and `assignment_ids`. Only explicitly selected
  100-point points assignments receive `NUMBER` pattern `0`. Missing policy
  retains the canonical renderer; malformed policy holds before a Canvas read.
  This changes display only, preserving the numeric value, EDIT fields and B2.

## Reproducible integration checks

The default suite runs fictional transports and portable contracts. Native
integrations remain available with explicitly selected local source and pins;
no implementation is discovered from an operator home directory or copied into
public fixtures. Incomplete settings or changed bytes fail the test; an absent
optional dependency produces an explicit integration skip.

| Integration | Required environment variables |
| --- | --- |
| LocalGrAss participation planner and bounded file helper | `LOCALGRASS_PARTICIPATION_STAGE_SOURCE`, `LOCALGRASS_PARTICIPATION_STAGE_SHA256`, `LOCALGRASS_PARTICIPATION_FILES_SHA256` |
| LocalGrAss reader stage | `LOCALGRASS_READER_STAGE_SOURCE`, `LOCALGRASS_READER_STAGE_SHA256` |
| Unit 2 native reader | `CANVAS_UNIT2_NATIVE_READER_SOURCE`, `CANVAS_UNIT2_NATIVE_READER_SHA256` |
| Unit 2 native capture sink | `CANVAS_UNIT2_CAPTURE_SINK_SOURCE`, `CANVAS_UNIT2_CAPTURE_SINK_SHA256` |

Record exact source pins, passed cases and optional skips privately. Keep native
integration evidence separate from portable CI and installed adoption. A source
repair does not turn an uncertain write into a retryable one.
