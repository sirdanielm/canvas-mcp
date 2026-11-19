# Scoped module authoring profile

This opt-in educator/stdio profile is separate from the normal, prepared-content
and draft-module profiles. Source availability does not establish installation,
operator admission, a fresh client catalog or live Canvas qualification.

## Draft operations

`inspect_module_authoring` reads an exact numeric course/module and returns its
publication state, parent preimage digest and complete ordered item inventory.
Use those values for a single authorized `add_draft_module_item` or
`edit_draft_module_item`, retaining its durable operation ID. Only operator-listed
courses are reachable. Do not substitute a new operation ID after an uncertain
send: reconcile the existing saved intent and Canvas state.

Adding supports an unpublished SubHeader or an exact same-course unpublished
ordinary Assignment, including inside a published module. It does not publish or
unpublish the parent. Linked assignment visibility is checked independently.
Reordering/indent edits support only unpublished Assignment/SubHeader items;
only a SubHeader title can be edited. Assignment title edits are deliberately
excluded because Canvas can rename the linked assignment. Item publication,
requirements, module moves, dates, linked-content replacement and deletion are
not part of these tools. Published children are held.

Full before/after inventories preserve peer content and relative order, allowing
only deterministic position shifts from the requested insert/move. Parent
business fields and linked assignment metadata must remain unchanged. Canvas
has no atomic compare-and-swap here: single-writer coordination is required, and
a post-send race becomes UNVERIFIED without compensation or automatic retry.

## Publication is a separate effect

Publication is off unless both the dedicated flag and exact writer admission
are present. Configure the client's `confirm_module_publication` approval mode
as `prompt`, verify the saved effective setting, and obtain Daniel's explicit
approval for the exact previewed object/effect before calling it. A confirmation
token binds the current target, content and caller; it cannot attest that a human
approved. Existing instruction authority is reused when its scope still matches.

The initial publisher is intentionally limited to an EMPTY module or one whose
every item and linked ordinary assignment is already explicitly published. It
refuses draft children, unsupported content and unknown visibility. It sends
only `module[published]=true` and `module[skip_content_tags]=true`, then compares
fresh parent/items/linked content. This avoids releasing a draft child even if a
tenant ignores the skip flag. General cascading publication and publishing a
container containing drafts are **not qualified**. No current course mutation is
needed or authorized to test this source change.

`prepare_module_publication` returns the exact effect preview and a one-use
process-local token. `confirm_module_publication` rechecks fresh state, records a
durable target-specific intent, makes at most one non-retried PUT and independently
reads back. UNKNOWN/UNVERIFIED blocks replay even with a changed operation ID or
after process restart. Reconciliation of a prior publication intent is an operator
step, not a reason to delete the journal. SIS final-grade publication is rejected.

## Operator setup and rollback

After exact-source review and applicable CI, use the existing normal launcher
and existing supported Keychain entry; never put a token in TOML or arguments:

```text
python /absolute/qualified/source/scripts/sdm_canvas_launcher.py
  --module-authoring-only
  --module-authoring-courses <explicit-comma-separated-numeric-course-IDs>
  --module-authoring-journal /absolute/private/persistent/module-journal
```

The source's environment needs the repository's qualified Python dependencies.
The example is a profile recipe, not an installed runtime pin. Preserve the
previous launcher/source/configuration and journal before an authorized adoption.
Do not silently repin an existing prepared manifest or old durable operation.

Set `ALLOWED_WRITE_TOOLS=add_draft_module_item,edit_draft_module_item` for draft
edits. Unset/empty/none/all or an outside writer never enables this profile's
writers. Optional publication additionally needs `--enable-module-publication`,
`confirm_module_publication` in the explicit allowlist and the verified per-tool
client prompt. Without all three, retain draft editing only. No generic grade,
feedback, assignment writer or broad module updater is registered.

Use the supported host Settings → MCP servers → Save → Restart sequence at a
verified idle boundary. Inspect the new catalog and call only local
`module_authoring_status` for the no-live-write smoke. Compare the catalog to its
explicit reader/writer ceiling; a configured flag alone is not loaded proof.
Restore only the changed profile's exact previous stanza/source and restart via
the same supported route to roll back. Retain all intent journals and uncertain
receipts. Other authoring, Gradebook and feedback profiles remain unchanged.

## API evidence and limits

The upstream item-create controller does not consume a publication override;
the item's type and linked assignment state determine visibility. Item title and
publication updates can affect linked content/other tags. Module update normally
publishes items unless its content-tag skip is set. These are source contracts,
not proof of the deployed school's implementation:

- [Item controller](https://github.com/instructure/canvas-lms/blob/master/app/controllers/context_module_items_api_controller.rb)
- [Content tag](https://github.com/instructure/canvas-lms/blob/master/app/models/content_tag.rb)
- [Module controller](https://github.com/instructure/canvas-lms/blob/master/app/controllers/context_modules_api_controller.rb)
- [Supported Codex MCP setup](https://learn.chatgpt.com/docs/extend/mcp?surface=app)
