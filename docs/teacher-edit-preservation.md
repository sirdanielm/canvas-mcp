# Exact operator-owned EDIT preservation

An operator can resolve one known local score/note conflict through the existing
pinned staging configuration's optional `edit_preservation_path` and
`edit_preservation_sha256`. Both must be supplied together and identify a private
local JSON file. Browser requests cannot supply this scope. The
`EXACT_LOCAL_EDIT_PRESERVATION_V1` permit binds the authenticated selection digest
(including exact final score, feedback and decision revision), literal workbook
and Canvas target, trusted baseline and current Canvas basis digests, complete native preimage digest,
selected full-cell digest, prior grade and exact prior note. Its
`authorization_ref` retains the direct operator approval receipt hash; a hash
alone establishes no authorization.

Only this exact preimage can replace a numeric local grade that is no higher
than the approved final score. The original grade and complete cell remain in
the immutable retained plan's `before_state`; the original note is retained
verbatim as the prefix before the marked approved feedback. The batch still
changes only that selected cell's value and note. All other native content and
`_Sync!B2` remain unchanged. The owner rechecks the private permit's pinned bytes
and the connection's trusted copy before preparation and execution; revalidation
recomputes the exact plan. Existing excusal, higher-grade, formula, source,
identity, attempt, unresolved-history and no-replay guards remain in force.
The same exact permit can reconcile an originally blank Canvas baseline with
one currently observed numeric grade when that grade matches the native cell.
Only grade/value, grading/posting timestamps and workflow-state changes are
admitted; attempt, submission time, visibility and excusal stay identical. The
comparison may contain only `canvas_changed_since_baseline`; any other reason
still holds. The original baseline is retained without rebasing. Without this
operator configuration the original conflict holds remain.

See [the teacher decision transfer](teacher-edit-transfer.md) for the existing owner, locking and reconciliation sequence. This opt-in plan changes no publication authority.
