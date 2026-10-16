# Canvas gradebook shortcuts

The unnumbered **Canvas** shortcuts in **Desktop → GrAss Local Checks** use the
Canvas-owned installation. They are independent of tools 0–9, do not run QC or
imports, and leave the installed GrAss harness pin unchanged.

Double-click **Canvas - Fresh GET** to update both protected GET tabs. Save and
pause worksheet editing, press Return once, and wait until the shortcut reports
VERIFIED. It opens the central workbook after the exact request's complete
GET-only receipt and queue cleanup are verified. Every EDIT value, formula,
feedback note and original baseline remains preserved. A newly populated tab or
READY heartbeat alone is not completion.

Double-click **Canvas - Review EDIT** to compare the retained EDIT score proposals
against their original baseline and fresh Canvas observations. It reads the
current native workbook, checks exact student/assignment identities, and opens
two private HTML reviews. Additional GET students or assignments do not move
EDIT cells. Helper cells outside the mapped score rectangle remain opaque;
formulas in score cells, changed labels, duplicate keys and ambiguous schema
remain holds. The review does not change Sheets or Canvas.

The terminal separately reports populated EDIT and fresh Canvas student and
assignment counts. A coverage warning lists exact-ID additions/removals and the
number of fresh Canvas score slots outside EDIT. It does not change a proposal's
readiness classification. Fresh GET preserves EDIT axes; new coverage requires
the separately reviewed [append procedure](gradebook-edit-axis-reconciliation.md)
with a fresh preflight and complete readback. The installed shortcuts do not
dispatch that engineering operation. A versioned sparse layout keeps declared
physical rows/columns stable and preserves protected helper gaps.

Review every proposed score and hold. To publish, give Codex the exact approved
private review and target scope. The existing publisher then requires its own
exact preview, explicit approval and fresh readback. Neither shortcut registers
or invokes a publisher. An uncertain publication is reconciled rather than
sent again.

Authorized feedback notes may remain on EDIT score cells and are preserved by
Fresh GET. These notes are local teacher staging, not Canvas submission comments;
they are not automatically included in a score push. Actual comment delivery
requires a separate exact approval and its retained-source checks.

The Mac must be awake, online and able to access its existing credentials. If
Fresh GET stops at HELD, ask Codex to inspect and fix the saved cause before an
explicit pre-send release and new request. UNCERTAIN means reconcile the existing
request without retry or release. If the watcher is closed or times out, the
queued request remains saved; check its status before editing or requesting again.

The shortcuts contact online services only after an explicit launch and Return
confirmation. Installing or opening this guide does not run them. They add no
background job, import, grading, paid call, email or Canvas write capability.
The pre-existing GET-only background worker continues to service explicit
queued requests.

Source: `scripts/sdm_gradebook_desktop.py` and its two `.command` launchers.
Read the [worker runbook](sdm-gradebook-worker.md) for the preserved baselines,
receipt verification, source limits and recovery procedure.

The tracked `.command` wrappers resolve their own checkout and contain no fixed
operator home path. Create Desktop symlinks to the files in `scripts/`; copying
a wrapper elsewhere loses its repository-relative location and safely stops.
Existing installed operator-specific shortcuts are not changed by source sync.
