# 2.1c Google Docs intake coordination plan

Prepared September 26, 2026 from the local sdmGrAss checkout at
`0afec98d18d00dde6eb7732f688326b1cfa27bd9`, its `TECHNICAL_MANUAL.md`,
`DEVELOPMENT.md`, target registry, and native-reader/evidence tests.
This is a source-grounded handoff proposal, not live configuration, deployment,
grading, or Canvas publication. The sdmGrAss checkout was inspected without edits.

## Shared identity contract

The Canvas assignment code is `2.1c`; the fleet target is `grader-2-1-3`.
The two numeric Canvas assignment IDs, two student-template IDs, and two teacher-key
IDs are in the private proposal source registry, alongside course and maximum points.
They are exact Drive-document matches treated as teacher-authorized LTI assumptions;
the opaque Google Assignments launch URLs do not prove which template is attached.

Resolve track from the existing exact roster/course mapping. Core uses 20 points and
its own document/key; Advanced uses 25 and its own document/key. Keep the existing
`assignment_key` cross-workflow join and track policy. Do not make a new identity
service, grading ledger, retry queue, or source folder hierarchy.

## Observed current reader path

1. The existing manifest records source identity, MIME type, and modification time.
2. `apps-script/3text.gs` reads Google Docs through
   `DocumentApp.openById(...).getBody().getText()` and records `DOCUMENTAPP_BODY_TEXT`.
3. `apps-script/4media.gs` inventories `getBody().getImages()`, hashes inline-image bytes,
   and retains `DOC_INLINE_IMAGE` locators with document ID and image index. Native
   Docs evidence therefore already has text and media paths.
4. Reuse is fenced by source identity/modification time and evidence hashes. The
   existing pipeline, review, outcall ledger, and paid-call gates remain authoritative.

The observed Docs reader does not explicitly traverse all document tabs or inventory
positioned images/embedded drawings. Treat those layouts as unproven coverage. A body
text read or a `NO_INLINE_IMAGES` sentinel alone cannot establish that the student's
submission contains no visual evidence. The current generic native-reader tests prove
MIME/reuse contracts; they are not a full end-to-end test of these two 2.1c documents.

## Proposed preflight packet

Before using the live 2.1.3 grader, assemble:

- exact assignment/course/track identity and submission attempt/source revision;
- current Canvas description rubric (teacher-approved revision), point total, and source hash;
- exact assigned template plus teacher key, versioned separately by course;
- student's native body text plus every inline screenshot/diagram, in source order;
- template-versus-student text distinction, preserving student additions and captions;
- a visual-coverage record that distinguishes present, absent, unreadable, and unsupported;
- the existing evidence seal and review gates, with all publication/Canvas gates closed.

Do not subtract a template from a student document unless the existing subtraction
path has an exact versioned template and passes its own checks. The answer scaffolds
already present in a blank template are not evidence of student work. Likewise, never
convert an unreadable screenshot, unsupported drawing, or uncertain assignment match
into a zero. Preserve `UNKNOWN`, `AMBIGUOUS`, and `CONFLICT` for teacher review.

## Minimal acceptance harness

Use synthetic native-document fixtures first, then teacher-reviewed/de-identified
examples under separately approved live-read/model scopes:

| Fixture | Required outcome |
|---|---|
| Blank Core template | No scaffold text counted as a student answer; no invented screenshots |
| Core typed responses + three inline screenshots | Text, captions, image hashes, and order preserved; Core contract selected |
| Advanced responses + three base screenshots + extension evidence | Advanced key/25-point contract selected; all requested visual evidence accounted for |
| Caption alternative for A2 | Accepted as the student's explicitly allowed evidence form |
| Drawing, positioned image, or extra tab | Coverage verified or held as unsupported; never silently treated as absent |
| Core source with Advanced routing | Identity conflict retained; no automatic cross-track grading |
| Source edited after scan / same document new attempt | Stale reuse rejected by existing revision/evidence identity controls |
| Missing or unreadable screenshot | Evidence uncertainty preserved for teacher review |
| Gamma response with no shielding work | Evaluated against approved gamma comparison; no shielding penalty |

Run existing `check-native-readers.js`, `check-tier-evidence.js`, and
`check-question-visual-support.js` as baseline checks. Add a targeted Docs-text/media
fixture harness through the actual intake functions before claiming readiness.
Then follow the complete validation commands in sdmGrAss `DEVELOPMENT.md` for any
implementation changes. Do not change the canonical technical manual until an actual
durable contract changes.

## Release and operating sequence

1. Teacher approves the exact Core/Advanced rubric description edits.
2. Apply only those descriptions through separately authorized Canvas writes and
   verify readback; capture a new mirror afterward.
3. Compare live 2.1.3 assignment/config fields and installed source with the canonical
   target registry before proposing any workbook or code change. Registry gates in
   the inspected checkout are closed; that is not a fresh workbook-gate audit.
4. Adjudicate the prior 2.1.3 assignment-match/visual-evidence canary hold against the
   correct document and key. Historical memory reports conflicting match/zero-evidence
   results; its status may be stale and must be refreshed before any paid canary.
5. Validate text/media coverage with the fixture matrix. Only then request exact
   bounded model-call authority for teacher-reviewed examples and measure evidence
   extraction, track routing, score agreement, and abstention.
6. Deploy or configure only after separate approval. Preserve the existing ledger,
   `SEND_UNCERTAIN`, teacher review decisions, and explicit Canvas publication gate.

Do not move, rename, deduplicate, or otherwise reorganize Canvas Assignments source
folders/documents. sdmGrAss treats that Drive tree as immutable evidence; derived
packets belong outside it. The mirror provides source context and drafts while the
fleet retains grading workflow authority.
